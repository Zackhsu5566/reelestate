# User Management + TTS/BGM Integration Design

> Date: 2026-03-21
> Status: Draft

## Overview

為 ReelEstate pipeline 加入兩大功能：

1. **用戶管理** — 房仲透過 LINE Bot 自助註冊、綁定個人資訊、配額限制、風格選擇
2. **TTS + BGM** — MiniMax TTS 旁白與固定 BGM，讓影片從純畫面升級為有聲內容

兩者共享對話狀態機的改動，因此合併為一份 spec。

## Context

目前所有用戶共用 hardcoded 設定（`premium=True`、`staging_template="japanese_muji"`），房仲個人資訊每次都從 `raw_text` 提取，影片沒有旁白和 BGM。此設計解決這些問題。

---

## Part 1: User Management

### Requirements

1. **身份識別** — 用 LINE userId 綁定房仲個人資訊（姓名、公司、電話）
2. **方案管理** — 預留 Standard / Premium 欄位，測試階段預設全開
3. **配額限制** — 每位用戶預設 3 支影片，用完後擋住
4. **風格選擇** — 每次生成前讓用戶選擇虛擬裝潢風格（不綁定 profile）
5. **Profile 注入** — Profile 為預設值，Agent 從 raw_text 提取到的可覆寫

### Data Model

```python
class UserProfile(BaseModel):
    line_user_id: str       # PK
    name: str               # 必填
    company: str            # 必填
    phone: str              # 必填
    line_id: str | None = None  # LINE ID（顯示用，選填）
    plan: str = "premium"   # standard / premium（預留）
    quota: int = 3          # 總配額
    usage: int = 0          # 已使用數量
    created_at: str         # ISO 時間戳
```

### Storage — Redis Hash

```
Key:    user:{line_user_id}
Type:   Hash
TTL:    無（永久保留）
```

選擇 Redis 的理由：
- 現有 infra，零額外成本
- 用戶量 < 50，Hash 查詢 O(1)
- `HINCRBY` 原子操作適合 quota 計數

**序列化注意**：`hgetall` 回傳的所有值皆為 string。`UserStore.get()` 需對 `quota`、`usage` 做 `int()` 轉型，`line_id` 為空字串時轉為 `None`。

### UserStore API

獨立檔案 `orchestrator/stores/user.py`，與 `JobStore` 分離：

| Method | 說明 |
|--------|------|
| `get(line_user_id) -> UserProfile \| None` | 查詢用戶，處理 Hash → Pydantic 轉型 |
| `create(profile: UserProfile) -> None` | 建立用戶（`hset` mapping） |
| `update(line_user_id, **fields) -> None` | 更新指定欄位 |
| `try_consume_quota(line_user_id) -> bool` | 原子遞增 usage，超額則回滾並返回 False |

`try_consume_quota` 實作（Lua script 確保完全原子性）：

```python
_CONSUME_QUOTA_SCRIPT = """
local key = KEYS[1]
local usage = tonumber(redis.call('HGET', key, 'usage') or '0')
local quota = tonumber(redis.call('HGET', key, 'quota') or '3')
if usage < quota then
    redis.call('HINCRBY', key, 'usage', 1)
    return 1
end
return 0
"""

async def try_consume_quota(self, line_user_id: str) -> bool:
    """Atomically check and increment usage via Lua script."""
    key = f"user:{line_user_id}"
    result = await self.r.eval(_CONSUME_QUOTA_SCRIPT, 1, key)
    return bool(result)
```

### Registration Flow

```
Bot: 「歡迎使用 ReelEstate！請先輸入您的姓名」
用戶: 「王小明」          → conv.reg_name，轉 registering_company
Bot: 「請輸入您的公司名稱」
用戶: 「信義房屋」        → conv.reg_company，轉 registering_phone
Bot: 「請輸入您的聯絡電話」
用戶: 「0912345678」      → 驗證格式，conv.reg_phone，轉 registering_line_id
Bot: 「請輸入您的 LINE ID（選填，將顯示於影片中供客戶聯繫）」 [跳過]
用戶: 「wang.ming」       → 驗證格式，建立 UserProfile，轉 idle
Bot: 「註冊完成！您可以開始傳照片生成影片了 🎬」
```

### Registration Validation Rules

**Non-text message handling**：所有 `registering_*` 狀態下收到非文字訊息（sticker、圖片、音訊、位置）時，回覆「請輸入文字訊息喔！」+ 當前步驟提示，不改變狀態。

| Field | Required | Max Length | Pattern | Normalize | Reject Message |
|-------|----------|-----------|---------|-----------|----------------|
| name | Yes | 20 | 中英文、空格、`·` | trim | 「請輸入 1-20 字的姓名」 |
| company | Yes | 30 | 上述 + `（）()-、` | trim | 「請輸入 1-30 字的公司名稱」 |
| phone | Yes | 10 (stored) | `09\d{8}` | strip `-` and spaces | 「請輸入正確的手機號碼（例如 0912345678）」 |
| line_id | No | 20 | `[a-z0-9._-]+` | lowercase, trim | 「LINE ID 格式不正確，請重新輸入或點選跳過」 |

- **name**：1–20 字元，允許中文、英文、空格、`·`（如「乃木·希典」）。去除前後空白。
- **company**：1–30 字元，name 字集 + 常見標點 `（）()-、`。去除前後空白。
- **phone**：先 strip `-` 和空格再驗證，所以 `0912-345-678` 和 `0912 345 678` 都可接受。儲存正規化後的 10 位數字。
- **line_id**：1–20 字元，小寫英數字 + `.` `_` `-`。使用 Quick Reply `[跳過]` 按鈕（postback data: `skip_line_id`）設為 `None`。也接受文字輸入「跳過」「略過」作為 fallback。

### 修改資料

- 正常流程：`UserStore.get()` 回傳 profile → 跳過註冊 → idle
- 修改資料：用戶輸入「修改資料」→ 保留現有 `usage`/`quota`/`created_at`，重新進入 `registering_name` 填寫個人資訊
- 完成後用 `UserStore.update()` 覆寫 `name`、`company`、`phone`、`line_id`，不動 `usage`/`quota`
- 「修改資料」為全域指令，與「重新開始」「取消」「使用說明」並列

全域指令在 `registering_*` 狀態下同樣有效（「重新開始」「取消」清除暫存、重置狀態、不建立 profile）。

### Style Selection Flow

`awaiting_info` 完成後，raw_text 暫存到 conv state，轉入 `choosing_style`。

用 LINE Quick Reply buttons 呈現選項：

```
日式無印 | 極簡 | 北歐 | 奢華 | 工業風
```

對應值：`japanese_muji | minimalist | scandinavian | luxury | industrial`

用戶點選後值存入 `conv.chosen_style`，進入下一步（旁白選擇）。

### Quota Check

**提前攔截**：在用戶傳第一張照片（進入 `collecting_photos`）時就檢查 `usage < quota`，額度不足直接告知，避免用戶花時間上傳照片後才被擋。

**正式扣額**：在所有前置選擇完成、建立 job 前呼叫 `try_consume_quota()`：

- 返回 True → 建立 job，進入 processing
- 返回 False → 回覆「您已使用 N/N 支影片額度」，重置對話

計數時機：job 建立時（非 render 完成後），防止連續送多個 job 超額。Pipeline 失敗不退還額度，管理員可手動用 `UserStore.update()` 調整。

### Profile Injection

Agent 分析完成後（`step_analyze` 內），合併 profile 到 `PropertyInfo`：

```python
profile = await user_store.get(state.line_user_id)
prop = state.agent_result.property

# Profile 為 fallback，Agent 提取到的優先
prop.agent_name = prop.agent_name or profile.name
prop.company = prop.company or profile.company
prop.phone = prop.phone or profile.phone
prop.line = prop.line or profile.line_id
```

### Job Creation

`_create_job` 改為從 conv state 和 profile 取值（移除 hardcoded 預設）：

```python
job_state = JobState(
    ...,
    staging_template=conv_state["chosen_style"],        # 從對話狀態取
    narration_enabled=conv_state["narration_enabled"],   # 從對話狀態取
    premium=profile.plan == "premium",                   # 從 profile 取
    line_user_id=user_id,
)
```

`_create_job` 函式簽名需新增 `profile: UserProfile` 參數。

---

## Part 2: TTS + BGM

### 決策摘要

| 決策 | 結論 |
|------|------|
| TTS 模型 | MiniMax `speech-2.8-hd` + `Chinese_casual_guide_vv2` |
| 同步策略 | 旁白配合影片，固定場景時長不動 |
| TTS 失敗 | 降級出片（無旁白，只有 BGM） |
| 用戶選擇 | LINE 對話中問一次「要加旁白嗎？」（`choosing_style` 之後） |
| 講稿 Gate | 有。素材先跑，TTS 等 Gate 通過才跑 |
| Gate 超時 | 10 分鐘無回應，自動用原始講稿跑 TTS |
| Gate 不通過 | 給「修改講稿」和「不要旁白」兩個選項 |
| BGM | 固定一首 royalty-free，上傳至 R2 |
| 執行時機 | TTS 跟素材平行跑（在 `step_generate` 中） |

### Pipeline 流程

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

1. `step_generate` 開始時，若 `narration_enabled=True`，推送講稿給用戶，並設 Redis key `narration_gate:{job_id}` = `"pending"`（TTL 1 小時，避免 key 堆積）
2. 素材（Kling/staging/exterior）平行開始生成
3. 用戶回應 LINE postback 時，webhook handler 直接寫 Redis key：
   - ✅ 通過 → `"approved"`
   - ✏️ 修改 → `"edit_pending"`（同時設 conv state 為 `editing_narration`）
   - ❌ 不要 → `"rejected"`
4. 若用戶選「修改」，進入 `editing_narration` conv state：
   - 用戶輸入新講稿文字 → webhook 寫 Redis key `"edit:{新講稿文字}"` → conv state 回 `processing`
   - 字數限制：不超過原始講稿長度的 1.5 倍，超過則提醒用戶縮短
   - 非文字訊息（sticker、圖片等）→ 回覆「請輸入文字訊息喔！」，不改變狀態
   - 全域指令「取消」/「重新開始」→ 寫 Redis key `"rejected"`（跳過旁白），conv state 回 `processing`，不取消整個 job
5. `step_generate` 內有一個 async loop 輪詢此 Redis key（間隔 3s，超時 10min）
   - 讀到 `"pending"` / `"edit_pending"` → 繼續等待
   - 讀到 `"approved"` → 用原始講稿跑 TTS
   - 讀到 `"edit:{text}"` → 用新講稿跑 TTS
   - 讀到 `"rejected"` → 跳過 TTS
6. 超時 → 視為 `"approved"`（自動通過）

**Crash recovery**：`JobState` 新增 `narration_gate_status` 欄位（`pending` | `approved` | `edit_pending` | `rejected` | `timeout`）及 `narration_task_id` 欄位。Pipeline 重啟後：
- `narration_gate_status` 為 `approved`/`timeout` 且有 `narration_task_id` → 恢復 TTS 輪詢
- `narration_gate_status` 為 `approved`/`timeout` 且無 `narration_task_id` → 重新跑 TTS
- `narration_gate_status` 為 `rejected` → 跳過 TTS
- `narration_gate_status` 為 `pending`/`edit_pending` → 恢復 Gate 輪詢

### Gate 與素材的協調

素材完成後檢查 Gate 狀態：

- Gate 已通過且 TTS 完成 → 進 render
- Gate 已通過但 TTS 還在跑 → 等 TTS
- Gate 未回應 → 等到超時（10 min）自動通過 → 跑 TTS → 進 render
- Gate 拒絕（不要旁白） → 直接進 render

### Narration Choice Flow

用戶選完風格後，進入 `awaiting_narration_choice`：

```
Bot: 要加入 AI 旁白嗎？
    [是] [否]
```

- 選「是」→ `conv.narration_enabled = True` → 配額檢查 → 建立 job → `processing`
- 選「否」→ `conv.narration_enabled = False` → 配額檢查 → 建立 job → `processing`

### 講稿 Gate（narration_enabled = True）

`step_generate` 開始後推送：

```
Bot: 📝 AI 生成的旁白講稿：

「信義區精裝兩房，首次公開！
 一進門就是超大面落地窗…」

    [✅ 通過] [✏️ 修改講稿] [❌ 不要旁白]
```

- ✅ 通過 → 跑 TTS
- ✏️ 修改講稿 → Bot 回「請輸入修改後的講稿：」→ conv state 轉為 `editing_narration` → 用戶回傳文字（≤ 原始長度 1.5 倍）→ 更新 narration → 跑 TTS
- ❌ 不要旁白 → `narration_enabled = False`，跳過 TTS
- ⏰ 10 分鐘無回應 → 自動通過，用原始講稿跑 TTS

### Agent SKILL.md 講稿規則更新

#### 動態字數計算

Agent 根據 `spaces` 數量計算目標字數，原則是**寧少勿多，留白讓畫面說話**（約場景時長的 60-70% 有語音）：

| 段落 | 場景時長 | 目標字數 | 原則 |
|------|---------|---------|------|
| OPENING | 15s | 30-40 字 | 只講 hook，留空間給地圖動畫 |
| 每個空間 | 4s | 8-12 字 | 一句話點亮點 |
| STATS | 7s | 16-20 字 | 數據簡念 |
| CTA | 5s | 12-16 字 | 報價 + 聯繫 |

以 6 個空間為例：40 + 6×10 + 18 + 14 = **132 字**（影片 51 秒）。

#### 語速基準

約 **4 字/秒**，Agent 以此換算各段目標字數。

#### 停頓標記

講稿 section 之間插入 `<#秒數#>` 停頓標記（MiniMax 語法），讓 TTS 在轉場處自然停頓：

- OPENING → 第一個空間：`<#1.0#>`
- 場景間：`<#0.5#>`

#### Section Marker 保留

`[OPENING]`、`[空間名]`、`[STATS]`、`[CTA]` marker 繼續保留——用於 Gate 時顯示給用戶閱讀，以及未來可能的分段對齊。TTS 前需 strip 掉 marker（只保留停頓標記和正文）。

#### 講稿範例（新格式）

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

#### 移除「僅供參考」標注

講稿現在會實際用於 TTS，需嚴格控制品質和長度。

### MiniMax TTS Service

#### 新增 `orchestrator/services/minimax.py`

Async 流程（需走 file upload 才能使用 `<#x#>` 停頓標記）：

```
1. POST /v1/files/upload → file_id（上傳講稿 txt）
2. POST /v1/t2a_async_v2 → task_id（建立 TTS 任務）
3. GET /v1/query/t2a_async_query_v2?task_id=xxx → 輪詢至完成 → file_id
4. GET /v1/files/retrieve_content?file_id=xxx → 音檔 bytes
5. 上傳至 R2 → narration URL
```

#### 參數

```python
model = "speech-2.8-hd"
voice_id = "Chinese_casual_guide_vv2"
speed = 1.0
format = "mp3"
audio_sample_rate = 32000
```

#### 錯誤處理（per-step）

| 步驟 | 失敗情境 | 處理 |
|------|---------|------|
| File upload | 413 / network error | Retry 1 次，失敗則降級 |
| Create task | 400（bad text） | Log 原始文字，降級 |
| Poll timeout | 超過 120s | 降級 |
| Download audio | 空檔 / corrupt | 降級 |
| R2 upload | Network error | Retry 1 次，失敗則降級 |

所有降級 = log warning，`narration_url` 維持 `None`，pipeline 繼續（無旁白出片）。不 raise，不擋住 `step_generate`。

#### 並發控制

Module-level semaphore 限制同時進行的 MiniMax API 呼叫：

```python
# orchestrator/services/minimax.py (module level)
_tts_semaphore = asyncio.Semaphore(5)
```

所有 TTS 呼叫共用同一個 semaphore instance，確保整個 process 的並發上限。

#### 音檔時長 Observability

下載音檔後（step 4），用 ffprobe 記錄音檔時長至 log。不 block pipeline，純 observability 用途，方便日後排查旁白超出影片時長的問題：

```python
logger.info("TTS audio duration: %.1fs (job=%s)", duration_sec, job_id)
```

### BGM

1. 準備一首 royalty-free BGM
2. 上傳至 R2
3. `_build_render_input` 從 `settings.bgm_url` 讀取，有值才帶入
4. 音量由 Remotion 端根據有無旁白動態調整

### Remotion 端改動

#### `types.ts` — VideoInput 加欄位

```typescript
export type VideoInput = {
  // ...現有欄位
  bgm?: string;
  narration?: string;  // 新增
};
```

#### `ReelEstateVideo.tsx` — 加旁白音軌

```tsx
// 檔案頂部常數（方便調整）
const BGM_VOLUME = 0.15;
const BGM_VOLUME_WITH_NARRATION = 0.05;
const NARRATION_VOLUME = 1.0;

// JSX
{bgm && <Audio src={staticFile(bgm)} volume={narration ? BGM_VOLUME_WITH_NARRATION : BGM_VOLUME} loop />}
{narration && <Audio src={staticFile(narration)} volume={NARRATION_VOLUME} />}
```

> 注意：BGM `loop` 在影片結束時會被 Remotion 截斷（不需額外 fade-out）。音量值需實測調整，先用這組預設。

#### `server/assets.ts` — 下載 narration

跟 BGM 相同邏輯，下載 narration URL 到 `{jobDir}/audio/narration.mp3`。

#### `server/types.ts` — RenderInput 加欄位

```typescript
narration?: string;
```

---

## Unified Conversation State Machine

### 新增狀態總覽

| 狀態 | 來源 | 用途 |
|------|------|------|
| `registering_name` | User Mgmt | 註冊：輸入姓名 |
| `registering_company` | User Mgmt | 註冊：輸入公司 |
| `registering_phone` | User Mgmt | 註冊：輸入電話 |
| `registering_line_id` | User Mgmt | 註冊：輸入 LINE ID（可跳過） |
| `choosing_style` | User Mgmt | 選擇虛擬裝潢風格 |
| `awaiting_narration_choice` | TTS | 選擇是否加入旁白 |
| `editing_narration` | TTS | 修改講稿（在 processing 中） |

### 完整流程

```
新用戶：
  首次訊息 → registering_name → registering_company → registering_phone
  → registering_line_id → idle

所有用戶（每次生成）：
  idle → collecting_photos → awaiting_label → awaiting_info
  → choosing_style → awaiting_narration_choice → 配額檢查
  → processing → awaiting_feedback

processing 中（narration_enabled=True）：
  pipeline 推送講稿 Gate → editing_narration（若用戶選修改）→ processing
```

### 全域指令

| 指令 | 行為 | 在 editing_narration 中的特殊行為 |
|------|------|------|
| 「重新開始」 | 清除對話狀態（含暫存），回到 idle（registering 中不建立 profile） | 寫 `rejected` 到 gate key，跳過旁白，不取消 job |
| 「取消」 | 同上 | 同上 |
| 「使用說明」 | 顯示歡迎訊息 | — |
| 「修改資料」 | 保留 usage/quota，重新進入 registering_name 修改個人資訊 | — |

### Conv State 暫存欄位

```python
def _empty_state() -> dict:
    return {
        "state": ConversationState.idle,
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
        # 註冊暫存
        "reg_name": None,
        "reg_company": None,
        "reg_phone": None,
        # Job 前置選擇
        "chosen_style": None,
        "narration_enabled": None,
    }
```

註冊完成時 `reg_*` 清除。Conv state 24h TTL 自然處理中斷的註冊。

---

## Unified Models Changes

### 新增 UserProfile

（見 Part 1 Data Model）

### JobState 新增欄位

```python
# TTS 相關
narration_enabled: bool = False
narration_gate_status: str | None = None  # pending | edit_pending | approved | rejected | timeout
narration_text: str | None = None  # 最終講稿（可能經用戶編輯），TTS 用此文字
narration_task_id: str | None = None  # MiniMax async task ID（crash recovery 用）
narration_url: str | None = None  # TTS 輸出的 R2 URL
```

`narration_text` 初始值從 `agent_result.narration` 複製；用戶透過 Gate 修改時更新此欄位，`agent_result.narration` 保留原始版本。

### CreateJobRequest 新增

```python
narration_enabled: bool = False
```

### Narration Gate 不走 `gates.py`

Narration gate 透過 Redis key 輪詢（見 Part 2 Narration Gate 機制），不使用現有 `GATE_STATUS_MAP` / `handle_gate_callback` 機制。LINE webhook handler 直接寫 Redis key 回應。

---

## Config 新增

```python
# config.py
minimax_api_key: str = ""
minimax_group_id: str = ""
minimax_poll_interval: float = 3.0
minimax_poll_timeout: float = 120.0
bgm_url: str = ""  # R2 URL
```

---

## Files Changed（完整清單）

| 檔案 | 變更 |
|------|------|
| `orchestrator/models.py` | 新增 `UserProfile`；`ConversationState` 加 7 個新狀態；`JobState` 加 narration 欄位；`CreateJobRequest` 加 `narration_enabled` |
| `orchestrator/stores/__init__.py` | 新增 module |
| `orchestrator/stores/user.py` | 新增 `UserStore` class |
| `orchestrator/config.py` | 新增 MiniMax + BGM 設定 |
| `orchestrator/services/minimax.py` | **新增** — MiniMax TTS service |
| `orchestrator/line/conversation.py` | `_empty_state()` 加暫存欄位；處理 `registering_*`、`choosing_style`、`awaiting_narration_choice`、`editing_narration` 狀態邏輯 |
| `orchestrator/line/webhook.py` | 入口加 profile 查詢；新用戶導向註冊；`_create_job` 接受 profile + style + narration；narration gate postback handler |
| `orchestrator/line/bot.py` | 新增 `send_gate_narration()` |
| `orchestrator/pipeline/jobs.py` | `step_analyze` 後 profile injection；`step_generate` 加 TTS task + Gate 輪詢；`_build_render_input` 加 narration + bgm |
| `orchestrator/.env.example` | 新增 MINIMAX 環境變數 |
| `agent/SKILL.md` | 更新講稿規則（動態字數、停頓標記、移除「僅供參考」） |
| `remotion/src/types.ts` | VideoInput 加 `narration` |
| `remotion/src/ReelEstateVideo.tsx` | 加旁白 Audio 元件，BGM 音量動態調整 |
| `remotion/server/types.ts` | RenderInput 加 `narration` |
| `remotion/server/assets.ts` | 下載 narration 音檔 |

## Not Changed

- Redis infra / Docker — 不需改動
- Gate 邏輯（`gates.py`）— preview gate 不受影響

## Redis Key Overview

```
user:{line_user_id}        → Hash（永久）       用戶 profile
conv:{line_user_id}        → String/JSON        對話狀態（24h TTL）
job:{job_id}               → Hash               Job 狀態（7天 TTL）
jobs:active                → Set                 活動 job
narration_gate:{job_id}    → String（1h TTL）     講稿 Gate 狀態（TTS 新增）
```

## Future Considerations

- 用戶量超過 50 後可考慮遷移 SQLite / PostgreSQL
- 月度配額重置（訂閱制）
- LINE Mini App 自助管理（Phase 2）
- 管理員後台（查看用量、調整配額）
- 多語言 TTS voice 支援
- 用戶自選 BGM
- BGM fade-out：影片最後 1-2 秒做 volume ramp down（目前硬切）
- TTS 音檔時長超出影片時長的自動裁切
