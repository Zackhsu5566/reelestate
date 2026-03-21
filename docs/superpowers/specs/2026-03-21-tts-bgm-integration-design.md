# TTS + BGM Integration Design

> Date: 2026-03-21
> Status: Draft

## Overview

為 ReelEstate pipeline 加入 MiniMax TTS 旁白與固定 BGM，讓影片從純畫面升級為有聲內容。TTS 為 opt-in 功能，用戶可在 LINE 對話中選擇是否加入旁白。

## 決策摘要

| 決策 | 結論 |
|------|------|
| TTS 模型 | MiniMax `speech-2.8-hd` + `Chinese_casual_guide_vv2` |
| 同步策略 | 旁白配合影片，固定場景時長不動 |
| TTS 失敗 | 降級出片（無旁白，只有 BGM） |
| 用戶選擇 | LINE 對話中問一次「要加旁白嗎？」 |
| 講稿 Gate | 有。素材先跑，TTS 等 Gate 通過才跑 |
| Gate 超時 | 10 分鐘無回應，自動用原始講稿跑 TTS |
| Gate 不通過 | 給「修改講稿」和「不要旁白」兩個選項 |
| BGM | 固定一首 royalty-free，上傳至 R2 |
| 執行時機 | TTS 跟素材平行跑（在 `step_generate` 中） |

---

## 1. Pipeline 流程

```
step_analyze
  └→ Agent 產出 narration 文字
  └→ 狀態 → generating

step_generate（平行）
  ├─ Kling 影片 × N（不等 Gate）
  ├─ Staging 裝潢（不等 Gate）
  ├─ Exterior 影片（不等 Gate）
  └─ 講稿 Gate（僅 narration_enabled=True 時）
       ├─ ✅ 通過 → 跑 TTS（MiniMax async）
       ├─ ✏️ 修改講稿 → 用戶輸入新文字 → 跑 TTS
       ├─ ❌ 不要旁白 → 跳過 TTS
       └─ ⏰ 10 分鐘超時 → 自動用原始講稿跑 TTS

  所有素材 + TTS（若有）都完成後 → 狀態 → rendering

step_render
  └→ _build_render_input 帶入 narration URL（若有）+ bgm URL
  └→ Remotion render

step_deliver（不變）
```

### Narration Gate 機制

Narration gate 不使用 `JobStatus`（不像 preview gate），而是透過 **Redis key 輪詢**實現，因為它在 `step_generate` 內部 inline 運行：

1. `step_generate` 開始時，若 `narration_enabled=True`，推送講稿給用戶，並設 Redis key `narration_gate:{job_id}` = `"pending"`
2. 素材（Kling/staging/exterior）平行開始生成
3. 用戶回應 LINE postback 時，webhook handler 直接寫 Redis key：
   - ✅ 通過 → `"approved"`
   - ✏️ 修改 → `"edit:{新講稿文字}"`
   - ❌ 不要 → `"rejected"`
4. `step_generate` 內有一個 async loop 輪詢此 Redis key（間隔 3s，超時 10min）
5. 超時 → 視為 `"approved"`（自動通過）

**Crash recovery**：`JobState` 新增 `narration_gate_status` 欄位（`pending` | `approved` | `rejected` | `timeout`）。Pipeline 重啟後，若 `narration_gate_status` 已是 `approved`/`timeout` 且 TTS 尚未完成，直接跑 TTS；若為 `rejected`，跳過 TTS。

### Gate 與素材的協調

素材完成後檢查 Gate 狀態：

- Gate 已通過且 TTS 完成 → 進 render
- Gate 已通過但 TTS 還在跑 → 等 TTS
- Gate 未回應 → 等到超時（10 min）自動通過 → 跑 TTS → 進 render
- Gate 拒絕（不要旁白） → 直接進 render

---

## 2. Agent SKILL.md 講稿規則更新

### 動態字數計算

Agent 根據 `spaces` 數量計算目標字數，原則是**寧少勿多，留白讓畫面說話**（約場景時長的 60-70% 有語音）：

| 段落 | 場景時長 | 目標字數 | 原則 |
|------|---------|---------|------|
| OPENING | 15s | 30-40 字 | 只講 hook，留空間給地圖動畫 |
| 每個空間 | 4s | 8-12 字 | 一句話點亮點 |
| STATS | 7s | 16-20 字 | 數據簡念 |
| CTA | 5s | 12-16 字 | 報價 + 聯繫 |

以 6 個空間為例：40 + 6×10 + 18 + 14 = **132 字**（影片 51 秒）。

### 語速基準

約 **4 字/秒**，Agent 以此換算各段目標字數。

### 停頓標記

講稿 section 之間插入 `<#秒數#>` 停頓標記（MiniMax 語法），讓 TTS 在轉場處自然停頓：

- OPENING → 第一個空間：`<#1.0#>`
- 場景間：`<#0.5#>`

### Section Marker 保留

`[OPENING]`、`[空間名]`、`[STATS]`、`[CTA]` marker 繼續保留——用於 Gate 時顯示給用戶閱讀，以及未來可能的分段對齊。TTS 前需 strip 掉 marker（只保留停頓標記和正文）。

### 講稿範例（新格式）

```
[OPENING]
信義區精裝兩房，採光無敵，首次公開！
<#1.0#>
[客廳]
超大落地窗，整面採光
<#0.5#>
[主臥]
主臥寬敞舒適
<#0.5#>
[STATS]
三十五坪，兩房兩廳，十二樓高樓層
<#0.5#>
[CTA]
售價兩千九百八十萬，歡迎聯繫看房
```

### 移除「僅供參考」標注

講稿現在會實際用於 TTS，需嚴格控制品質和長度。

---

## 3. MiniMax TTS Service

### 新增 `orchestrator/services/minimax.py`

Async 流程（需走 file upload 才能使用 `<#x#>` 停頓標記）：

```
1. POST /v1/files/upload → file_id（上傳講稿 txt）
2. POST /v1/t2a_async_v2 → task_id（建立 TTS 任務）
3. GET /v1/query/t2a_async_query_v2?task_id=xxx → 輪詢至完成 → file_id
4. GET /v1/files/retrieve_content?file_id=xxx → 音檔 bytes
5. 上傳至 R2 → narration URL
```

### 參數

```python
model = "speech-2.8-hd"
voice_id = "Chinese_casual_guide_vv2"
speed = 1.0
format = "mp3"
audio_sample_rate = 32000
```

### Config 新增

```python
# config.py
minimax_api_key: str = ""
minimax_group_id: str = ""
minimax_poll_interval: float = 3.0
minimax_poll_timeout: float = 120.0  # TTS 通常幾秒完成，120s 足夠
bgm_url: str = ""  # R2 URL，例如 https://assets.replowapp.com/audio/bgm-default.mp3
```

### 錯誤處理

TTS 失敗 → log warning，`narration_url` 維持 `None`，pipeline 繼續（降級出片）。不 raise，不擋住 `step_generate`。

---

## 4. Remotion 端改動

### 4a. `types.ts` — VideoInput 加欄位

```typescript
export type VideoInput = {
  // ...現有欄位
  bgm?: string;
  narration?: string;  // 新增
};
```

### 4b. `ReelEstateVideo.tsx` — 加旁白音軌

```tsx
{/* BGM — 有旁白時降低音量 */}
{bgm && <Audio src={staticFile(bgm)} volume={narration ? 0.05 : 0.15} loop />}

{/* 旁白 — 不 loop，播完就結束 */}
{narration && <Audio src={staticFile(narration)} volume={1.0} />}
```

### 4c. `server/assets.ts` — 下載 narration

跟 BGM 相同邏輯，下載 narration URL 到 `{jobDir}/audio/narration.mp3`。

### 4d. `server/types.ts` — RenderInput 加欄位

```typescript
narration?: string;
```

---

## 5. LINE 對話流程

### 5a. 新增「旁白選擇」步驟

新增 `ConversationState.awaiting_narration_choice`，位於 `choosing_style` → `processing` 之間。

完整 job 前置流程：`awaiting_info → choosing_style → awaiting_narration_choice → 配額檢查 → processing`

用戶選完風格後：

```
Bot: 要加入 AI 旁白嗎？
    [是] [否]
```

- 選「是」→ `narration_enabled = True` → 建立 job → `processing`
- 選「否」→ `narration_enabled = False` → 建立 job → `processing`

conversation state dict 新增 `narration_enabled` 欄位，傳入 `CreateJobRequest`。

### 5b. 講稿 Gate（narration_enabled = True）

`step_generate` 開始後推送：

```
Bot: 📝 AI 生成的旁白講稿：

「信義區精裝兩房，首次公開！
 一進門就是超大面落地窗…」

    [✅ 通過] [✏️ 修改講稿] [❌ 不要旁白]
```

- ✅ 通過 → 跑 TTS
- ✏️ 修改講稿 → Bot 回「請輸入修改後的講稿：」→ 用戶回傳 → 更新 narration → 跑 TTS
- ❌ 不要旁白 → `narration_enabled = False`，跳過 TTS
- ⏰ 10 分鐘無回應 → 自動通過，用原始講稿跑 TTS

---

## 6. BGM

1. 準備一首 royalty-free BGM
2. 上傳至 R2
3. `_build_render_input` 從 `settings.bgm_url` 讀取，有值才帶入
4. 音量由 Remotion 端根據有無旁白動態調整

---

## 7. Models 改動

### JobState 新增

```python
narration_enabled: bool = False
narration_gate_status: str | None = None  # pending | approved | rejected | timeout
narration_text: str | None = None  # 最終講稿（可能經用戶編輯），TTS 用此文字
narration_url: str | None = None  # TTS 輸出的 R2 URL
```

`narration_text` 初始值從 `agent_result.narration` 複製；用戶透過 Gate 修改時更新此欄位，`agent_result.narration` 保留原始版本。

### CreateJobRequest 新增

```python
narration_enabled: bool = False
```

### Narration Gate 不走 `gates.py`

Narration gate 透過 Redis key 輪詢（見 Section 1），不使用現有 `GATE_STATUS_MAP` / `handle_gate_callback` 機制。LINE webhook handler 直接寫 Redis key 回應。

---

## 8. 改動檔案清單

| 檔案 | 改動 |
|------|------|
| `orchestrator/services/minimax.py` | **新增** — MiniMax TTS service |
| `orchestrator/config.py` | 新增 `minimax_api_key`, `minimax_group_id`, `minimax_poll_interval`, `minimax_poll_timeout`, `bgm_url` |
| `orchestrator/models.py` | JobState 加 `narration_enabled`, `narration_gate_status`, `narration_text`, `narration_url`；CreateJobRequest 加 `narration_enabled` |
| `orchestrator/pipeline/jobs.py` | `step_generate` 加 TTS task + Gate Redis 輪詢邏輯；`_build_render_input` 加 narration + bgm |
| `orchestrator/line/conversation.py` | 新增 `awaiting_narration_choice` 狀態 |
| `orchestrator/line/webhook.py` | 處理 narration gate postback → 寫 Redis key |
| `orchestrator/line/bot.py` | 新增 `send_gate_narration()` |
| `orchestrator/.env.example` | 確認 MINIMAX 環境變數 |
| `agent/SKILL.md` | 更新講稿規則（動態字數、停頓標記、移除「僅供參考」） |
| `remotion/src/types.ts` | VideoInput 加 `narration` |
| `remotion/src/ReelEstateVideo.tsx` | 加旁白 Audio 元件，BGM 音量動態調整 |
| `remotion/server/types.ts` | RenderInput 加 `narration` |
| `remotion/server/assets.ts` | 下載 narration 音檔 |
