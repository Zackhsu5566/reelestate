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

`try_consume_quota` 實作（解決 race condition）：

```python
async def try_consume_quota(self, line_user_id: str) -> bool:
    """Atomically increment usage; roll back if over quota."""
    key = f"user:{line_user_id}"
    new_usage = await self.r.hincrby(key, "usage", 1)
    quota = int(await self.r.hget(key, "quota") or 3)
    if new_usage > quota:
        await self.r.hincrby(key, "usage", -1)
        return False
    return True
```

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
  → choosing_style → 配額檢查 → processing → awaiting_feedback

完整流程（既有用戶）：
  idle → collecting_photos → awaiting_label → awaiting_info
  → choosing_style → 配額檢查 → processing → awaiting_feedback
```

### Conv State 暫存欄位

`_empty_state()` 需新增欄位以暫存註冊中資料和風格選擇：

```python
def _empty_state() -> dict:
    return {
        "state": ConversationState.idle,
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
        # 新增
        "reg_name": None,       # 註冊中暫存姓名
        "reg_company": None,    # 註冊中暫存公司
        "chosen_style": None,   # 風格選擇結果
    }
```

註冊完成時，`reg_name` / `reg_company` 清除（資料已寫入 `user:` Hash）。Conv state 的 24 小時 TTL 自然處理中斷的註冊——過期後重新開始。

### Registration Flow

```
Bot: 「歡迎使用 ReelEstate！請先輸入您的姓名」
用戶: 「王小明」          → 存入 conv.reg_name，轉 registering_company
Bot: 「請輸入您的公司名稱」
用戶: 「信義房屋」        → 存入 conv.reg_company，轉 registering_phone
Bot: 「請輸入您的聯絡電話」
用戶: 「0912345678」      → 驗證格式，建立 UserProfile，轉 idle
Bot: 「註冊完成！您可以開始傳照片生成影片了」
```

三個欄位皆必填，不可跳過。電話號碼需通過基本格式驗證（台灣手機 `09` 開頭、10 位數字）。

全域指令（「重新開始」「取消」「使用說明」）在 registering 狀態下同樣有效，會清除暫存資料、重置回初始狀態（不建立 profile），下次傳訊息會重新進入註冊。

### Style Selection Flow

`awaiting_info` 完成後，raw_text 暫存到 conv state，轉入 `choosing_style`。

用 LINE Quick Reply buttons 呈現選項：

```
日式無印 | 極簡 | 北歐 | 奢華 | 工業風
```

對應值：`japanese_muji | minimalist | scandinavian | luxury | industrial`

用戶點選後值存入 `conv.chosen_style`，接著進行配額檢查，通過後建立 job。

### Quota Check

**提前攔截**：在用戶傳第一張照片（進入 `collecting_photos`）時就檢查 `usage < quota`，額度不足直接告知，避免用戶花時間上傳照片後才被擋。

**正式扣額**：在 `choosing_style` 完成、建立 job 前呼叫 `try_consume_quota()`：

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
    staging_template=conv_state["chosen_style"],   # 從對話狀態取
    premium=profile.plan == "premium",              # 從 profile 取
    line_user_id=user_id,
)
```

`_create_job` 函式簽名需新增 `profile: UserProfile` 參數。

## Files Changed

| 檔案 | 變更 |
|------|------|
| `orchestrator/models.py` | 新增 `UserProfile`、`ConversationState` 加 `registering_*` + `choosing_style` |
| `orchestrator/stores/__init__.py` | 新增 module |
| `orchestrator/stores/user.py` | 新增 `UserStore` class |
| `orchestrator/line/conversation.py` | `_empty_state()` 加暫存欄位、處理 `registering_*` 和 `choosing_style` 狀態邏輯 |
| `orchestrator/line/webhook.py` | 入口加 profile 查詢、新用戶導向註冊、`_create_job` 接受 profile + style |
| `orchestrator/pipeline/jobs.py` | `step_analyze` 後插入 profile injection |

## Not Changed

- Redis infra / Docker — 不需改動
- Remotion 端 — input.json 格式不變
- Agent service — 照常分析 raw_text
- Gate 邏輯 — 不受影響

## Redis Key Overview

```
user:{line_user_id}   → Hash（永久）  用戶 profile
conv:{line_user_id}   → String/JSON   對話狀態（既有，24h TTL）
job:{job_id}          → Hash          Job 狀態（既有，7天 TTL）
jobs:active           → Set           活動 job（既有）
```

## Future Considerations

- 用戶量超過 50 後可考慮遷移 SQLite / PostgreSQL
- 月度配額重置（訂閱制）
- LINE Mini App 自助管理（Phase 2）
- 管理員後台（查看用量、調整配額）
