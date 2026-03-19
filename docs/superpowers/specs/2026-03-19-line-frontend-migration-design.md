# LINE 前端遷移設計

## 目標

將 ReelEstate 的使用者前端從 Telegram 全面遷移至 LINE Messaging API，包含：
- 照片接收與空間標記
- Gate 審查（預覽影片確認）
- 最終影片交付

## 背景

- 台灣 LINE 滲透率遠高於 Telegram，房仲日常使用 LINE
- 降低使用門檻，不需要房仲額外安裝 Telegram
- n8n 保留作為中間層，未來擴展用戶管理、付費狀態、用量追蹤
- Gate 1（講稿確認）和 Gate 1.5（TTS 試聽）已在 2026-03-19 pipeline 簡化中移除，本次遷移只涉及 Gate 2（預覽影片確認）

## 架構

```
房仲（LINE App）
  ↓ LINE Messaging API webhook
n8n（signature 驗證、webhook 轉發、用戶管理、照片下載 + R2 上傳）
  ↓ 轉發至 FastAPI
FastAPI Orchestrator
  ├─ /webhook/line（對話狀態機：照片收集、空間標記、物件資訊）
  ├─ /jobs（pipeline 核心不變）
  └─ LINE Push API（Gate 通知、最終交付）
  ↓
房仲（LINE App）收到預覽 / 最終影片
```

**關鍵決策**：對話狀態機放在 FastAPI orchestrator（`/webhook/line`），不放在 n8n。原因：n8n webhook 是 stateless 的，多輪對話狀態管理在 Python 中更好維護和測試。n8n 負責 signature 驗證、照片二進制下載 + R2 上傳、用戶管理邏輯。

n8n 與 orchestrator 部署在同一台 VPS。

## 對話流程

### 照片階段

```
房仲傳照片（可一次選多張）
  → 5 秒內連續傳的照片視為同一批次
  → 批次結束後 bot：「這是什麼空間？」
房仲：「客廳」→ bot：「✓ 客廳（N 張），請繼續傳下一張或輸入『完成』」
房仲傳照片 → bot：「這是什麼空間？」
房仲：「外觀」→ 自動歸為 exterior_photo
...
房仲：「完成」
```

### 資訊階段

```
bot：「請輸入物件資訊：」
房仲：自由格式文字（地址、坪數、格局、樓層、價格、姓名、電話等）
→ Agent 解析結構化資訊
→ pipeline 啟動
→ bot：「✓ 收到！開始生成影片，約需 5-10 分鐘。」
```

### Gate 階段（預覽確認）

```
bot：推送預覽影片 + Confirm Template
    「通過」按鈕 → postback → /webhook/line → POST /jobs/{id}/gate (approved: true)
    「不通過」按鈕 → postback → bot：「請說明需要修改的地方」
    房仲回覆 feedback → 記錄至 job state（人工介入處理）
```

### 交付階段

```
bot：推送最終 MP4（video message）
```

### 錯誤處理

| 情境 | 處理方式 |
|------|----------|
| 無法辨識的空間名稱 | bot：「抱歉，請輸入空間名稱（如：客廳、主臥、廚房、外觀等）」 |
| `awaiting_label` 狀態下又傳了照片 | 加入同一批次，重設 5 秒 debounce timer |
| Agent 解析物件資訊失敗 | bot：「資訊格式無法辨識，請重新輸入（地址/坪數/格局/樓層/價格/姓名/電話）」 |
| Pipeline 中途失敗 | bot 推送錯誤通知：「影片生成失敗，我們正在處理，稍後會通知您。」 |
| LINE Push API 失敗 | 記 warning log，不中斷 pipeline（與現有 Telegram 行為一致） |

## 需要變更的元件

### 新增

| 元件 | 說明 |
|------|------|
| LINE Official Account | 建立帳號、設定 Messaging API channel |
| n8n LINE workflow | LINE webhook → signature 驗證 → 照片下載/R2 上傳 → 轉發至 FastAPI |
| `orchestrator/line/bot.py` | LINE Push API client（取代 `orchestrator/telegram/bot.py`） |
| `orchestrator/line/__init__.py` | 模組 init |
| `orchestrator/line/webhook.py` | `/webhook/line` endpoint + 對話狀態機 |
| `orchestrator/line/conversation.py` | 對話狀態管理（Redis-backed） |

### 修改

| 檔案 | 變更 |
|------|------|
| `orchestrator/config.py` | `telegram_bot_token` → `line_channel_access_token` + `line_channel_secret` |
| `orchestrator/pipeline/jobs.py` | import 路徑 `orchestrator.telegram.bot` → `orchestrator.line.bot`；`telegram_bot.send_*` → `line_bot.send_*` |
| `orchestrator/main.py` | import 路徑更新；lifespan 初始化改用 LINE client；掛載 `/webhook/line` router |
| `ARCHITECTURE.md` | Telegram 參照改為 LINE |
| `concept.md` | Telegram 參照改為 LINE |

### 刪除

| 檔案 | 理由 |
|------|------|
| `orchestrator/telegram/bot.py` | 被 `orchestrator/line/bot.py` 取代 |
| `orchestrator/telegram/__init__.py` | 整個 telegram 模組移除 |

### 不變

- Pipeline 核心邏輯（analyze → generate → render → deliver）
- Remotion 影片生成
- WaveSpeed API 呼叫
- Redis job state
- Gate 狀態機邏輯（`gates.py`）— 只是觸發來源改變
- `models.py` 的 `line_user_id` 欄位（歷史原因：目前存的是 Telegram chat_id，遷移後語義才真正正確）
- `callback_url` 欄位移除（LINE postback 直接走 webhook → orchestrator，不需要額外 callback URL）

## 對話狀態機

### 狀態定義

```python
class ConversationState(str, Enum):
    idle = "idle"                       # 等待照片
    collecting_photos = "collecting"    # 收到照片，debounce 5 秒等更多照片
    awaiting_label = "awaiting_label"   # 批次結束，等空間名稱
    awaiting_info = "awaiting_info"     # 照片完成，等物件資訊
    processing = "processing"           # pipeline 執行中
    awaiting_feedback = "awaiting_feedback"  # Gate 被拒，等修改說明
```

### Redis 儲存

Key：`conv:{line_user_id}`，與 orchestrator 的 `job:*` 命名空間隔離。

```json
{
  "state": "awaiting_label",
  "pending_photos": ["https://r2.example.com/abc.jpg", "https://r2.example.com/def.jpg"],
  "spaces": [
    {"label": "客廳", "photos": ["https://r2.example.com/001.jpg"]}
  ],
  "job_id": null
}
```

### 照片批次 Debounce

收到 image event 時：
1. 將照片 R2 URL 加入 `pending_photos`
2. 狀態設為 `collecting_photos`
3. 重設 5 秒 timer（用 `asyncio` delayed task 或 Redis TTL key）
4. 5 秒內無新照片 → 狀態轉為 `awaiting_label`，bot 發問「這是什麼空間？」

## LINE 技術細節

| 項目 | 選擇 |
|------|------|
| SDK | 直接用 httpx 呼叫 REST API（與現有風格一致） |
| 照片接收 | n8n 用 Content API 下載 binary → 上傳 R2 → 將 R2 URL 轉發給 orchestrator |
| 影片推送 | Push API + video message type（需 HTTPS URL，R2 CDN 已滿足） |
| 影片限制 | LINE video message 上限 200MB / 1 分鐘。ReelEstate 影片通常 30-60 秒，在限制內 |
| Gate 按鈕 | Confirm Template + postback action（`data: "approve:{job_id}:preview"` / `"reject:{job_id}:preview"`） |
| 用戶識別 | LINE userId（webhook event source 自帶） |
| Webhook 驗證 | n8n 驗證 `x-line-signature`（HMAC-SHA256，用 channel secret） |

## LINE Push API 訊息格式

### 預覽影片 + Gate 按鈕

```json
{
  "to": "<line_user_id>",
  "messages": [
    {
      "type": "video",
      "originalContentUrl": "https://assets.example.com/preview.mp4",
      "previewImageUrl": "https://assets.example.com/preview-thumb.jpg"
    },
    {
      "type": "template",
      "altText": "預覽影片確認",
      "template": {
        "type": "confirm",
        "text": "請確認預覽影片是否 OK",
        "actions": [
          {
            "type": "postback",
            "label": "✅ 通過",
            "data": "approve:{job_id}:preview"
          },
          {
            "type": "postback",
            "label": "❌ 不通過",
            "data": "reject:{job_id}:preview"
          }
        ]
      }
    }
  ]
}
```

### 最終影片交付

```json
{
  "to": "<line_user_id>",
  "messages": [
    {
      "type": "video",
      "originalContentUrl": "https://assets.example.com/final.mp4",
      "previewImageUrl": "https://assets.example.com/final-thumb.jpg"
    },
    {
      "type": "text",
      "text": "🎉 影片完成！可直接下載使用。"
    }
  ]
}
```

## 預覽縮圖

LINE video message 需要 `previewImageUrl`。

方案：在 VPS render server 端處理，render 完成後同時用 ffmpeg 擷取第一幀作為縮圖，上傳至 R2，在 render response 中一起回傳 `thumbnail_url`。避免 orchestrator 下載整個影片再處理。

## n8n Workflow 設計

n8n 的角色簡化為「閘道器」，不做複雜邏輯：

```
LINE Webhook Trigger
  → 驗證 x-line-signature
  → Switch（依 event type）
    → message/image：
        Content API 下載圖片 binary → 上傳 R2 → 取得 R2 URL
        → POST orchestrator /webhook/line（附 event + photo_url）
    → message/text：
        → POST orchestrator /webhook/line（原封轉發）
    → postback：
        → POST orchestrator /webhook/line（原封轉發）
```

未來用戶管理邏輯（付費狀態檢查、用量限制）也在 n8n 層加入，作為 middleware。

## 部署步驟

1. 建立 LINE Official Account + Messaging API channel
2. VPS 安裝 n8n（Docker，與 orchestrator 同機）
3. 設定 n8n LINE webhook URL（需 HTTPS，用 existing reverse proxy）
4. 建立 n8n workflow（signature 驗證 + 照片處理 + 轉發）
5. 實作 orchestrator LINE 模組（`orchestrator/line/`）
6. 修改 orchestrator（刪除 telegram 模組、更新 import）
7. Render server 新增縮圖生成功能
8. 環境變數更新：`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`
9. 更新 `ARCHITECTURE.md`、`concept.md`
10. E2E 測試
