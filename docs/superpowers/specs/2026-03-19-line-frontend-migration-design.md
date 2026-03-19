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

## 架構

```
房仲（LINE App）
  ↓ LINE Messaging API webhook
n8n（對話狀態機、照片分組、R2 上傳、用戶管理）
  ↓ POST /jobs
FastAPI Orchestrator（pipeline 核心不變）
  ↓ LINE Push API
房仲（LINE App）收到預覽 / 最終影片
```

n8n 與 orchestrator 部署在同一台 VPS。

## 對話流程

### 照片階段

```
房仲傳照片 → bot：「這是什麼空間？」
房仲：「客廳」→ bot：「✓ 客廳，請繼續傳下一張或輸入『完成』」
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
```

### Gate 階段（預覽確認）

```
bot：推送預覽影片 + Confirm Template
    「通過」按鈕 → postback action → n8n → POST /jobs/{id}/gate (approved: true)
    「不通過」按鈕 → postback action → bot：「請說明需要修改的地方」→ 記錄 feedback
```

### 交付階段

```
bot：推送最終 MP4（video message）
```

## 需要變更的元件

### 新增

| 元件 | 說明 |
|------|------|
| LINE Official Account | 建立帳號、設定 Messaging API channel |
| n8n LINE workflow | LINE webhook → 對話狀態機 → 照片分組 → R2 上傳 → POST /jobs |
| `orchestrator/line/bot.py` | LINE Push API client（取代 `orchestrator/telegram/bot.py`） |

### 修改

| 檔案 | 變更 |
|------|------|
| `orchestrator/config.py` | `telegram_bot_token` → `line_channel_access_token` + `line_channel_secret` |
| `orchestrator/pipeline/jobs.py` | `telegram_bot.send_*` → `line_bot.send_*` |
| `orchestrator/main.py` | lifespan 初始化改用 LINE client |

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
- `models.py` 的 `line_user_id` 欄位（名稱已經是 LINE 的了）

## LINE 技術細節

| 項目 | 選擇 |
|------|------|
| SDK | 直接用 httpx 呼叫 REST API（與現有 Telegram bot 風格一致） |
| 照片接收 | n8n 處理 LINE image message event，用 Content API 下載 binary → 上傳 R2 |
| 影片推送 | Push API + video message type（需 HTTPS URL，R2 CDN 已滿足） |
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

## n8n Workflow 設計

### 主要節點

```
LINE Webhook Trigger
  → Switch（依 event type）
    → message/image：下載圖片 → 上傳 R2 → Reply「這是什麼空間？」→ 等回覆
    → message/text：
      ├─ 空間標記回覆 → 記錄配對 → Reply「✓ {空間}，請繼續或輸入『完成』」
      ├─ 「完成」→ Reply「請輸入物件資訊：」→ 切換狀態
      ├─ 物件資訊文字 → POST /jobs（含 spaces + raw_text + line_user_id）
      └─ Gate feedback → POST /jobs/{id}/gate
    → postback：
      ├─ approve:* → POST /jobs/{id}/gate (approved: true)
      └─ reject:* → Reply「請說明需要修改的地方」
```

### 對話狀態管理

n8n 需要追蹤每個 `line_user_id` 的對話狀態：

| 狀態 | 說明 |
|------|------|
| `idle` | 等待照片 |
| `awaiting_label` | 剛收到照片，等空間名稱 |
| `awaiting_info` | 照片完成，等物件資訊 |
| `awaiting_feedback` | Gate 被拒，等修改說明 |

儲存方式：n8n 內建的 workflow static data 或 Redis（與 orchestrator 共用）。

## 預覽縮圖

LINE video message 需要 `previewImageUrl`。方案：
- Render 完成後用 ffmpeg 擷取第一幀作為縮圖
- 上傳至 R2，URL 傳入 LINE Push API

這一步加在 `step_render()` 結尾，render 完成後立即產生。

## 部署步驟

1. 建立 LINE Official Account + Messaging API channel
2. VPS 安裝 n8n（Docker，與 orchestrator 同機）
3. 設定 n8n LINE webhook URL（需 HTTPS，用 existing reverse proxy）
4. 建立 n8n workflow
5. 修改 orchestrator（telegram → line）
6. 環境變數更新：`LINE_CHANNEL_ACCESS_TOKEN`、`LINE_CHANNEL_SECRET`
7. E2E 測試
