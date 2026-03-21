# User Management System Design

## Overview

為 ReelEstate pipeline 加入用戶管理機制，讓房仲透過 LINE Bot 自助註冊、綁定個人資訊，並支援配額限制與風格選擇。

## Context

目前所有用戶共用 hardcoded 設定（`premium=True`、`staging_template="japanese_muji"`），房仲個人資訊每次都從 `raw_text` 提取。此設計引入持久化的用戶 profile，解決重複輸入、配額管控、風格客製化等需求。

## Requirements

1. **身份識別** — 用 LINE userId 綁定房仲個人資訊（姓名、公司、電話）
2. **方案管理** — 預留 Standard / Premium 欄位，測試階段預設全開
3. **配額限制** — 每位用戶預設 3 支影片，用完後擋住
4. **風格選擇** — 每次生成前讓用戶選擇虛擬裝潢風格（不綁定 profile）
5. **Profile 注入** — Profile 為預設值，Agent 從 raw_text 提取到的可覆寫

## Design

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
- 與 `conv:` / `job:` 同一套存取模式

### UserStore API

放在 `orchestrator/pipeline/state.py`（與 `JobStore` 同檔）：

| Method | 說明 |
|--------|------|
| `get(line_user_id) -> UserProfile \| None` | 查詢用戶 |
| `create(profile: UserProfile) -> None` | 建立用戶 |
| `update(line_user_id, **fields) -> None` | 更新欄位 |
| `increment_usage(line_user_id) -> int` | 原子遞增 usage（HINCRBY） |
| `check_quota(line_user_id) -> bool` | `usage < quota` |

### Conversation State Machine

新增 4 個狀態：

```
新增（註冊）：
  registering_name → registering_company → registering_phone → idle

新增（風格選擇）：
  choosing_style（在 awaiting_info 之後）

完整流程（新用戶）：
  首次訊息 → registering_name → registering_company → registering_phone
  → idle → collecting_photos → awaiting_label → awaiting_info
  → choosing_style → processing → awaiting_feedback

完整流程（既有用戶）：
  idle → collecting_photos → awaiting_label → awaiting_info
  → choosing_style → processing → awaiting_feedback
```

### Registration Flow

```
Bot: 「歡迎使用 ReelEstate！請先輸入您的姓名」
用戶: 「王小明」
Bot: 「請輸入您的公司名稱」
用戶: 「信義房屋」
Bot: 「請輸入您的聯絡電話」
用戶: 「0912345678」
Bot: 「註冊完成！您可以開始傳照片生成影片了」
→ 建立 UserProfile，狀態回到 idle
```

三個欄位皆必填，不可跳過。全域指令（「重新開始」「取消」「使用說明」）在 registering 狀態下同樣有效。

### Style Selection Flow

`awaiting_info` 完成後進入 `choosing_style`，用 LINE Quick Reply buttons：

```
japanese_muji | minimalist | scandinavian | luxury | industrial
```

用戶點選後值存入 `conv` 狀態，建立 job 時帶入 `JobState.staging_template`。

### Quota Check

在 `_create_job()` 建立 job 之前檢查：

- `user_store.check_quota(user_id)` 返回 False → 回覆額度已滿，重置對話
- 返回 True → `user_store.increment_usage(user_id)` 原子遞增，然後建立 job
- 計數時機：job 建立時（非 render 完成後），防止連續送多個 job 超額
- Pipeline 失敗不退還額度，管理員可手動調整

### Profile Injection

Agent 分析完成後合併 profile 資訊：

```python
# Profile 為預設，Agent 提取的可覆寫
state.agent_result.agent_name = agent_result.agent_name or profile.name
state.agent_result.company = agent_result.company or profile.company
state.agent_result.phone = agent_result.phone or profile.phone
state.agent_result.line = agent_result.line or profile.line_id
```

### Job Creation

```python
job_state = JobState(
    ...,
    staging_template=conv_state.get("chosen_style"),  # 從對話狀態取
    premium=profile.plan == "premium",                 # 從 profile 取
    line_user_id=user_id,
)
```

## Files Changed

| 檔案 | 變更 |
|------|------|
| `orchestrator/models.py` | 新增 `UserProfile`、`ConversationState` 加 `registering_*` + `choosing_style` |
| `orchestrator/pipeline/state.py` | 新增 `UserStore` class |
| `orchestrator/line/conversation.py` | 處理 `registering_*` 和 `choosing_style` 訊息邏輯 |
| `orchestrator/line/webhook.py` | 入口加 profile 查詢，新用戶導向註冊 |
| `orchestrator/pipeline/jobs.py` | `_create_job` 加配額檢查、profile 注入 |

## Not Changed

- Redis infra / Docker — 不需改動
- Remotion 端 — input.json 格式不變
- Agent service — 照常分析 raw_text
- Gate 邏輯 — 不受影響

## Redis Key Overview

```
user:{line_user_id}   → Hash（永久）  用戶 profile
conv:{line_user_id}   → String/JSON   對話狀態（既有）
job:{job_id}          → Hash          Job 狀態（既有，7天 TTL）
jobs:active           → Set           活動 job（既有）
```

## Future Considerations

- 用戶量超過 50 後可考慮遷移 SQLite / PostgreSQL
- 月度配額重置（訂閱制）
- LINE Mini App 自助管理（Phase 2）
- 管理員後台（查看用量、調整配額）
