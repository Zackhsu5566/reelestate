# User Management + TTS/BGM Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user registration, quota management, per-job style/narration selection, and MiniMax TTS + BGM to the ReelEstate pipeline.

**Architecture:** Redis Hash for user profiles (zero infra cost), conversation state machine extended with 7 new states, MiniMax TTS service with Redis-based narration gate running inline within `step_generate`. Two phases: Phase 1 (User Management) can deploy independently; Phase 2 (TTS+BGM) builds on top.

**Tech Stack:** Python 3.10+ / FastAPI / Redis / Pydantic / LINE Messaging API / MiniMax TTS API / Remotion

**Spec:** `docs/superpowers/specs/2026-03-21-user-mgmt-and-tts-design.md`

**⚠️ Style key 修正：** Spec 列出的風格名與 `staging_prompts.py` 實際 key 不同。實際 keys：`japanese_muji | scandinavian | modern_minimalist | modern_luxury | warm_natural`。Plan 使用實際 keys。Quick Reply 顯示名：`日式無印 | 北歐 | 現代極簡 | 現代奢華 | 溫暖自然`。

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `orchestrator/stores/__init__.py` | Package init |
| `orchestrator/stores/user.py` | `UserStore` — Redis Hash CRUD + Lua quota script |
| `orchestrator/services/minimax.py` | MiniMax TTS async service (upload → create → poll → download → R2) |
| `orchestrator/tests/test_user_store.py` | UserStore unit tests |
| `orchestrator/tests/test_minimax.py` | MiniMax service unit tests |
| `orchestrator/tests/test_registration.py` | Registration flow integration tests |
| `orchestrator/tests/test_narration.py` | Narration choice + gate tests |

### Modified files

| File | Changes |
|------|---------|
| `orchestrator/models.py` | Add `UserProfile`, `JobState` narration fields, `CreateJobRequest.narration_enabled` |
| `orchestrator/config.py` | Add MiniMax + BGM config fields |
| `orchestrator/line/conversation.py` | Extend `ConversationState` (7 new StrEnum values), `_empty_state()`, add registration + style + narration helper methods |
| `orchestrator/line/webhook.py` | Registration handlers, style/narration choice handlers, profile lookup at entry, narration gate postback |
| `orchestrator/line/bot.py` | `send_registration_prompt()`, `send_style_choice()`, `send_narration_choice()`, `send_gate_narration()`, `send_quota_exceeded()` |
| `orchestrator/pipeline/jobs.py` | Profile injection in `step_analyze`, TTS task + gate poll in `step_generate`, narration/bgm in `_build_render_input` |
| `orchestrator/pipeline/state.py` | (No changes — UserStore is separate file) |
| `orchestrator/main.py` | Init `UserStore` in lifespan, pass to webhook router |
| `remotion/src/types.ts` | Add `narration?: string` to `VideoInput` |
| `remotion/src/ReelEstateVideo.tsx` | Add narration `<Audio>`, BGM volume constants |
| `remotion/server/types.ts` | Add `narration?: string` to `RenderInput` |
| `remotion/server/assets.ts` | Download narration audio |

---

## Phase 1: User Management

### Task 1: UserProfile Model + ConversationState Extensions

**Files:**
- Modify: `orchestrator/models.py` (UserProfile, JobState narration fields)
- Modify: `orchestrator/line/conversation.py` (ConversationState enum — it lives here, NOT in models.py)

- [ ] **Step 1: Add `UserProfile` model to `models.py` after `SpaceInput` (line ~129, before `CreateJobRequest`)**

```python
class UserProfile(BaseModel):
    line_user_id: str
    name: str
    company: str
    phone: str
    line_id: str | None = None
    plan: str = "premium"
    quota: int = 3
    usage: int = 0
    created_at: str
```

- [ ] **Step 2: Extend `ConversationState` StrEnum in `conversation.py` (line 15-21)**

⚠️ `ConversationState` is a `StrEnum` defined in `orchestrator/line/conversation.py`, NOT `models.py`.

Add 7 new values after existing ones:

```python
class ConversationState(StrEnum):
    # existing
    idle = "idle"
    collecting_photos = "collecting_photos"
    awaiting_label = "awaiting_label"
    awaiting_info = "awaiting_info"
    processing = "processing"
    awaiting_feedback = "awaiting_feedback"
    # new — registration
    registering_name = "registering_name"
    registering_company = "registering_company"
    registering_phone = "registering_phone"
    registering_line_id = "registering_line_id"
    # new — job options
    choosing_style = "choosing_style"
    awaiting_narration_choice = "awaiting_narration_choice"
    # new — narration edit (during processing)
    editing_narration = "editing_narration"
```

- [ ] **Step 3: Add narration fields to `JobState` in `models.py` (line ~96-123)**

Add after existing fields:

```python
    # TTS
    narration_enabled: bool = False
    narration_gate_status: str | None = None
    narration_text: str | None = None
    narration_task_id: str | None = None
    narration_url: str | None = None
```

- [ ] **Step 4: Add `narration_enabled` to `CreateJobRequest` (line ~135-141)**

```python
    narration_enabled: bool = False
```

- [ ] **Step 5: Commit**

```bash
git add orchestrator/models.py orchestrator/line/conversation.py
git commit -m "feat: add UserProfile model and extend ConversationState with 7 new states"
```

---

### Task 2: UserStore (Redis Hash + Lua Quota)

**Files:**
- Create: `orchestrator/stores/__init__.py`
- Create: `orchestrator/stores/user.py`
- Create: `orchestrator/tests/test_user_store.py`

- [ ] **Step 1: Write failing tests for UserStore**

```python
# orchestrator/tests/test_user_store.py
import pytest
from unittest.mock import AsyncMock
from orchestrator.stores.user import UserStore
from orchestrator.models import UserProfile


@pytest.fixture
def mock_redis():
    _hash_store: dict[str, dict[str, str]] = {}

    r = AsyncMock()

    async def _hset(key, mapping=None):
        _hash_store[key] = {k: str(v) for k, v in mapping.items()}

    async def _hgetall(key):
        return _hash_store.get(key, {})

    async def _eval(script, num_keys, *args):
        # 簡易模擬 Lua script
        key = args[0]
        data = _hash_store.get(key, {})
        usage = int(data.get("usage", "0"))
        quota = int(data.get("quota", "3"))
        if usage < quota:
            data["usage"] = str(usage + 1)
            return 1
        return 0

    r.hset = AsyncMock(side_effect=_hset)
    r.hgetall = AsyncMock(side_effect=_hgetall)
    r.eval = AsyncMock(side_effect=_eval)
    return r, _hash_store


@pytest.fixture
def store(mock_redis):
    r, _ = mock_redis
    return UserStore(r)


@pytest.mark.asyncio
async def test_create_and_get(store, mock_redis):
    profile = UserProfile(
        line_user_id="U123",
        name="王小明",
        company="信義房屋",
        phone="0912345678",
        created_at="2026-03-21T10:00:00",
    )
    await store.create(profile)
    result = await store.get("U123")
    assert result is not None
    assert result.name == "王小明"
    assert result.quota == 3
    assert result.usage == 0


@pytest.mark.asyncio
async def test_get_nonexistent(store):
    result = await store.get("NONEXIST")
    assert result is None


@pytest.mark.asyncio
async def test_try_consume_quota_success(store, mock_redis):
    _, hash_store = mock_redis
    hash_store["user:U123"] = {
        "line_user_id": "U123", "name": "Test", "company": "Co",
        "phone": "0912345678", "plan": "premium",
        "quota": "3", "usage": "0", "created_at": "2026-03-21T10:00:00",
    }
    assert await store.try_consume_quota("U123") is True


@pytest.mark.asyncio
async def test_try_consume_quota_exceeded(store, mock_redis):
    _, hash_store = mock_redis
    hash_store["user:U123"] = {
        "line_user_id": "U123", "name": "Test", "company": "Co",
        "phone": "0912345678", "plan": "premium",
        "quota": "3", "usage": "3", "created_at": "2026-03-21T10:00:00",
    }
    assert await store.try_consume_quota("U123") is False


@pytest.mark.asyncio
async def test_update_preserves_other_fields(store, mock_redis):
    _, hash_store = mock_redis
    hash_store["user:U123"] = {
        "line_user_id": "U123", "name": "Old", "company": "Co",
        "phone": "0912345678", "plan": "premium", "line_id": "",
        "quota": "3", "usage": "2", "created_at": "2026-03-21T10:00:00",
    }
    await store.update("U123", name="New Name", company="New Co")
    result = await store.get("U123")
    assert result.name == "New Name"
    assert result.usage == 2  # preserved
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_user_store.py -v`
Expected: ImportError — `orchestrator.stores.user` does not exist

- [ ] **Step 3: Create `orchestrator/stores/__init__.py`**

```python
# orchestrator/stores/__init__.py
```

- [ ] **Step 4: Implement `UserStore`**

```python
# orchestrator/stores/user.py
from __future__ import annotations

import logging
from redis.asyncio import Redis

from orchestrator.models import UserProfile

logger = logging.getLogger(__name__)

_CONSUME_QUOTA_LUA = """
local key = KEYS[1]
local usage = tonumber(redis.call('HGET', key, 'usage') or '0')
local quota = tonumber(redis.call('HGET', key, 'quota') or '3')
if usage < quota then
    redis.call('HINCRBY', key, 'usage', 1)
    return 1
end
return 0
"""

# Redis Hash 所有值都是 string，需要轉型的欄位
_INT_FIELDS = {"quota", "usage"}
_OPTIONAL_STR_FIELDS = {"line_id"}


class UserStore:
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def get(self, line_user_id: str) -> UserProfile | None:
        key = f"user:{line_user_id}"
        data = await self.r.hgetall(key)
        if not data:
            return None
        # 轉型
        parsed: dict = {}
        for k, v in data.items():
            if k in _INT_FIELDS:
                parsed[k] = int(v)
            elif k in _OPTIONAL_STR_FIELDS:
                parsed[k] = v if v else None
            else:
                parsed[k] = v
        return UserProfile(**parsed)

    async def create(self, profile: UserProfile) -> None:
        key = f"user:{profile.line_user_id}"
        mapping = {
            k: ("" if v is None else str(v))
            for k, v in profile.model_dump().items()
        }
        await self.r.hset(key, mapping=mapping)

    async def update(self, line_user_id: str, **fields: str | int | None) -> None:
        key = f"user:{line_user_id}"
        mapping = {
            k: ("" if v is None else str(v))
            for k, v in fields.items()
        }
        await self.r.hset(key, mapping=mapping)

    async def try_consume_quota(self, line_user_id: str) -> bool:
        key = f"user:{line_user_id}"
        result = await self.r.eval(_CONSUME_QUOTA_LUA, 1, key)
        return bool(result)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_user_store.py -v`
Expected: All 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add orchestrator/stores/ orchestrator/tests/test_user_store.py
git commit -m "feat: add UserStore with Redis Hash storage and Lua quota script"
```

---

### Task 3: Registration Helpers in ConversationManager

**Files:**
- Modify: `orchestrator/line/conversation.py`
- Modify: `orchestrator/tests/test_conversation.py`

- [ ] **Step 1: Write failing tests for registration state transitions**

Append to `orchestrator/tests/test_conversation.py`:

```python
@pytest.mark.asyncio
async def test_start_registration(manager):
    await manager.start_registration("U999")
    state = await manager.get("U999")
    assert state["state"] == ConversationState.registering_name


@pytest.mark.asyncio
async def test_set_reg_name(manager):
    await manager.start_registration("U999")
    await manager.set_reg_field("U999", "reg_name", "王小明",
                                 ConversationState.registering_company)
    state = await manager.get("U999")
    assert state["reg_name"] == "王小明"
    assert state["state"] == ConversationState.registering_company


@pytest.mark.asyncio
async def test_complete_registration(manager):
    await manager.start_registration("U999")
    await manager.set_reg_field("U999", "reg_name", "Test",
                                 ConversationState.registering_company)
    await manager.set_reg_field("U999", "reg_company", "Co",
                                 ConversationState.registering_phone)
    await manager.set_reg_field("U999", "reg_phone", "0912345678",
                                 ConversationState.registering_line_id)
    state = await manager.get("U999")
    assert state["state"] == ConversationState.registering_line_id
    assert state["reg_name"] == "Test"
    assert state["reg_company"] == "Co"
    assert state["reg_phone"] == "0912345678"


@pytest.mark.asyncio
async def test_set_choosing_style(manager):
    # 先設到 awaiting_info 完成後的狀態
    await manager._save("U999", {"state": ConversationState.choosing_style,
                                  "chosen_style": None})
    await manager.set_chosen_style("U999", "japanese_muji")
    state = await manager.get("U999")
    assert state["chosen_style"] == "japanese_muji"
    assert state["state"] == ConversationState.awaiting_narration_choice


@pytest.mark.asyncio
async def test_set_narration_choice(manager):
    await manager._save("U999", {"state": ConversationState.awaiting_narration_choice,
                                  "narration_enabled": None})
    await manager.set_narration_choice("U999", True)
    state = await manager.get("U999")
    assert state["narration_enabled"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_conversation.py -v -k "test_start_registration or test_set_reg or test_complete_registration or test_set_choosing or test_set_narration"`
Expected: AttributeError — methods don't exist yet

- [ ] **Step 3: Extend `_empty_state()` and add helper methods**

In `orchestrator/line/conversation.py`:

Update `_empty_state()` (line ~24):
```python
def _empty_state() -> dict:
    return {
        "state": ConversationState.idle,
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
        # registration temp
        "reg_name": None,
        "reg_company": None,
        "reg_phone": None,
        # job options
        "chosen_style": None,
        "narration_enabled": None,
        "raw_text": None,
    }
```

Add methods to `ConversationManager` class (after existing methods).

⚠️ **Naming**: The internal save method is `_save` (not `_set`). Redis attribute is `_r` (not `r`). Follow existing code conventions.

```python
    async def start_registration(self, user_id: str) -> None:
        state = _empty_state()
        state["state"] = ConversationState.registering_name
        await self._save(user_id, state)

    async def set_reg_field(
        self, user_id: str, field: str, value: str, next_state: ConversationState,
    ) -> None:
        state = await self.get(user_id)
        state[field] = value
        state["state"] = next_state
        await self._save(user_id, state)

    async def complete_registration(self, user_id: str) -> dict:
        """Clear reg_* fields and return to idle. Returns the reg data."""
        state = await self.get(user_id)
        reg_data = {
            "name": state["reg_name"],
            "company": state["reg_company"],
            "phone": state["reg_phone"],
        }
        state["reg_name"] = None
        state["reg_company"] = None
        state["reg_phone"] = None
        state["state"] = ConversationState.idle
        await self._save(user_id, state)
        return reg_data

    async def set_choosing_style(self, user_id: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.choosing_style
        await self._save(user_id, state)

    async def set_chosen_style(self, user_id: str, style: str) -> None:
        state = await self.get(user_id)
        state["chosen_style"] = style
        state["state"] = ConversationState.awaiting_narration_choice
        await self._save(user_id, state)

    async def set_narration_choice(self, user_id: str, enabled: bool) -> None:
        state = await self.get(user_id)
        state["narration_enabled"] = enabled
        await self._save(user_id, state)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_conversation.py -v`
Expected: All tests PASS (new + existing)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/line/conversation.py orchestrator/tests/test_conversation.py
git commit -m "feat: extend conversation manager with registration, style, narration helpers"
```

---

### Task 4: Validation Helpers

**Files:**
- Create: `orchestrator/line/validators.py`
- Create: `orchestrator/tests/test_validators.py`

- [ ] **Step 1: Write failing tests**

```python
# orchestrator/tests/test_validators.py
import pytest
from orchestrator.line.validators import validate_name, validate_company, validate_phone, validate_line_id


class TestValidateName:
    def test_valid_chinese(self):
        assert validate_name("王小明") == "王小明"

    def test_valid_with_dot(self):
        assert validate_name("乃木·希典") == "乃木·希典"

    def test_trim_whitespace(self):
        assert validate_name("  王小明  ") == "王小明"

    def test_empty(self):
        assert validate_name("") is None

    def test_too_long(self):
        assert validate_name("a" * 21) is None

    def test_invalid_chars(self):
        assert validate_name("王123!@#") is None


class TestValidateCompany:
    def test_valid(self):
        assert validate_company("信義房屋") == "信義房屋"

    def test_valid_with_parens(self):
        assert validate_company("永慶房屋（台北）") == "永慶房屋（台北）"

    def test_too_long(self):
        assert validate_company("a" * 31) is None


class TestValidatePhone:
    def test_valid(self):
        assert validate_phone("0912345678") == "0912345678"

    def test_with_dashes(self):
        assert validate_phone("0912-345-678") == "0912345678"

    def test_with_spaces(self):
        assert validate_phone("0912 345 678") == "0912345678"

    def test_invalid_prefix(self):
        assert validate_phone("0812345678") is None

    def test_too_short(self):
        assert validate_phone("091234") is None


class TestValidateLineId:
    def test_valid(self):
        assert validate_line_id("wang.ming") == "wang.ming"

    def test_uppercase_normalized(self):
        assert validate_line_id("Wang.Ming") == "wang.ming"

    def test_skip_keyword(self):
        assert validate_line_id("跳過") == "SKIP"

    def test_skip_keyword_alt(self):
        assert validate_line_id("略過") == "SKIP"

    def test_invalid_chars(self):
        assert validate_line_id("wang@ming") is None

    def test_too_long(self):
        assert validate_line_id("a" * 21) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_validators.py -v`
Expected: ImportError

- [ ] **Step 3: Implement validators**

```python
# orchestrator/line/validators.py
from __future__ import annotations

import re

_NAME_PATTERN = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z\s·]+$")
_COMPANY_PATTERN = re.compile(r"^[\u4e00-\u9fff\u3400-\u4dbfa-zA-Z\s·（）()\-、]+$")
_PHONE_PATTERN = re.compile(r"^09\d{8}$")
_LINE_ID_PATTERN = re.compile(r"^[a-z0-9._\-]+$")

_SKIP_KEYWORDS = {"跳過", "略過"}


def validate_name(text: str) -> str | None:
    text = text.strip()
    if not text or len(text) > 20:
        return None
    if not _NAME_PATTERN.match(text):
        return None
    return text


def validate_company(text: str) -> str | None:
    text = text.strip()
    if not text or len(text) > 30:
        return None
    if not _COMPANY_PATTERN.match(text):
        return None
    return text


def validate_phone(text: str) -> str | None:
    normalized = re.sub(r"[\s\-]", "", text.strip())
    if not _PHONE_PATTERN.match(normalized):
        return None
    return normalized


def validate_line_id(text: str) -> str | None:
    text = text.strip()
    if text in _SKIP_KEYWORDS:
        return "SKIP"
    text = text.lower()
    if not text or len(text) > 20:
        return None
    if not _LINE_ID_PATTERN.match(text):
        return None
    return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_validators.py -v`
Expected: All 15 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/line/validators.py orchestrator/tests/test_validators.py
git commit -m "feat: add registration field validation helpers"
```

---

### Task 5: LINE Bot Registration & Choice Messages

**Files:**
- Modify: `orchestrator/line/bot.py`

- [ ] **Step 1: Add registration prompt methods to `LineBot`**

Add after existing methods (line ~373):

```python
    async def send_registration_name_prompt(self, chat_id: str) -> None:
        await self.send_message(
            chat_id,
            "歡迎使用 ReelEstate！🏠\n請先輸入您的姓名：",
        )

    async def send_registration_company_prompt(self, chat_id: str) -> None:
        await self.send_message(chat_id, "請輸入您的公司名稱：")

    async def send_registration_phone_prompt(self, chat_id: str) -> None:
        await self.send_message(chat_id, "請輸入您的聯絡電話：")

    async def send_registration_line_id_prompt(self, chat_id: str) -> None:
        """Send LINE ID prompt with Quick Reply skip button."""
        await self._push(chat_id, [{
            "type": "text",
            "text": "請輸入您的 LINE ID（選填，將顯示於影片中供客戶聯繫）",
            "quickReply": {
                "items": [{
                    "type": "action",
                    "action": {
                        "type": "postback",
                        "label": "跳過",
                        "data": "skip_line_id",
                        "displayText": "跳過",
                    },
                }],
            },
        }])

    async def send_registration_complete(self, chat_id: str) -> None:
        await self.send_message(
            chat_id,
            "註冊完成！您可以開始傳照片生成影片了 🎬\n\n"
            "直接傳送房屋照片即可開始。",
        )

    async def send_style_choice(self, chat_id: str) -> None:
        """Send style Quick Reply buttons."""
        styles = [
            ("日式無印", "style:japanese_muji"),
            ("北歐", "style:scandinavian"),
            ("現代極簡", "style:modern_minimalist"),
            ("現代奢華", "style:modern_luxury"),
            ("溫暖自然", "style:warm_natural"),
        ]
        items = [
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": label,
                    "data": data,
                    "displayText": label,
                },
            }
            for label, data in styles
        ]
        await self._push(chat_id, [{
            "type": "text",
            "text": "請選擇虛擬裝潢風格：",
            "quickReply": {"items": items},
        }])

    async def send_narration_choice(self, chat_id: str) -> None:
        """Send narration opt-in Quick Reply."""
        items = [
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "是",
                    "data": "narration:yes",
                    "displayText": "是",
                },
            },
            {
                "type": "action",
                "action": {
                    "type": "postback",
                    "label": "否",
                    "data": "narration:no",
                    "displayText": "否",
                },
            },
        ]
        await self._push(chat_id, [{
            "type": "text",
            "text": "要加入 AI 旁白嗎？",
            "quickReply": {"items": items},
        }])

    async def send_quota_exceeded(self, chat_id: str, usage: int, quota: int) -> None:
        await self.send_message(
            chat_id,
            f"您已使用 {usage}/{quota} 支影片額度，目前無法再生成。",
        )

    async def send_validation_error(self, chat_id: str, message: str) -> None:
        await self.send_message(chat_id, message)

    async def send_text_only_reminder(self, chat_id: str, reprompt: str) -> None:
        await self.send_message(chat_id, f"請輸入文字訊息喔！\n{reprompt}")
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/line/bot.py
git commit -m "feat: add LINE bot methods for registration, style, narration, quota messages"
```

---

### Task 6: Webhook Registration + Style/Narration Handlers

**Files:**
- Modify: `orchestrator/line/webhook.py`
- Create: `orchestrator/tests/test_registration.py`

- [ ] **Step 1: Write failing tests for registration flow**

```python
# orchestrator/tests/test_registration.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from orchestrator.models import ConversationState


@pytest.fixture
def mock_deps():
    """Set up all mock dependencies for webhook handlers."""
    bot = AsyncMock()
    conv = AsyncMock()
    user_store = AsyncMock()
    return bot, conv, user_store


@pytest.mark.asyncio
async def test_new_user_starts_registration(mock_deps):
    """New user (no profile) should enter registering_name.

    Note: This tests the webhook module's _handle_text function.
    Module-level singletons (line_bot, conv_manager, user_store) must be
    patched at module level.
    """
    bot, conv, user_store = mock_deps
    user_store.get.return_value = None  # no profile
    conv.get.return_value = {"state": ConversationState.idle}

    with patch("orchestrator.line.webhook.user_store", user_store), \
         patch("orchestrator.line.webhook.conv_manager", conv), \
         patch("orchestrator.line.webhook.line_bot", bot):
        from orchestrator.line.webhook import _handle_text
        await _handle_text("U123", "hello")

    conv.start_registration.assert_called_once_with("U123")
    bot.send_registration_name_prompt.assert_called_once_with("U123")


@pytest.mark.asyncio
async def test_registering_name_valid(mock_deps):
    """Valid name should advance to registering_company."""
    bot, conv, user_store = mock_deps
    user_store.get.return_value = None
    conv.get.return_value = {"state": ConversationState.registering_name}

    from orchestrator.line.webhook import _handle_registration
    await _handle_registration("U123", "王小明", ConversationState.registering_name,
                                bot, conv)

    conv.set_reg_field.assert_called_once_with(
        "U123", "reg_name", "王小明", ConversationState.registering_company,
    )
    bot.send_registration_company_prompt.assert_called_once()


@pytest.mark.asyncio
async def test_registering_name_invalid(mock_deps):
    """Invalid name should show error, not advance."""
    bot, conv, user_store = mock_deps
    conv.get.return_value = {"state": ConversationState.registering_name}

    from orchestrator.line.webhook import _handle_registration
    await _handle_registration("U123", "", ConversationState.registering_name,
                                bot, conv)

    conv.set_reg_field.assert_not_called()
    bot.send_validation_error.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_registration.py -v`
Expected: ImportError — `_handle_message_with_profile` doesn't exist

- [ ] **Step 3: Refactor webhook.py to add registration + style/narration handling**

This is the largest change. Modify `orchestrator/line/webhook.py`:

**Add imports at top:**
```python
from orchestrator.stores.user import UserStore
from orchestrator.line.validators import (
    validate_name, validate_company, validate_phone, validate_line_id,
)
```

**Add module-level `user_store` variable (alongside existing `conv_manager`, `bot`):**
```python
user_store: UserStore | None = None
```

**Add registration handler function:**
```python
# Registration validation rules
_REG_STEPS = {
    ConversationState.registering_name: {
        "field": "reg_name",
        "validate": validate_name,
        "next": ConversationState.registering_company,
        "error": "請輸入 1-20 字的姓名",
        "prompt": "send_registration_company_prompt",
    },
    ConversationState.registering_company: {
        "field": "reg_company",
        "validate": validate_company,
        "next": ConversationState.registering_phone,
        "error": "請輸入 1-30 字的公司名稱",
        "prompt": "send_registration_phone_prompt",
    },
    ConversationState.registering_phone: {
        "field": "reg_phone",
        "validate": validate_phone,
        "next": ConversationState.registering_line_id,
        "error": "請輸入正確的手機號碼（例如 0912345678）",
        "prompt": "send_registration_line_id_prompt",
    },
}


async def _handle_registration(
    user_id: str, text: str, state: ConversationState,
    bot_inst, conv, line_id_value: str | None = None,
) -> None:
    """Handle registering_name / registering_company / registering_phone steps."""
    step = _REG_STEPS[state]
    validated = step["validate"](text)
    if validated is None:
        await bot_inst.send_validation_error(user_id, step["error"])
        return
    await conv.set_reg_field(user_id, step["field"], validated, step["next"])
    await getattr(bot_inst, step["prompt"])(user_id)


async def _handle_registration_line_id(
    user_id: str, text: str, bot_inst, conv, user_store_inst,
) -> None:
    """Handle registering_line_id step (optional, can skip).

    Handles both new registration and 修改資料 flow:
    - New user: create full profile
    - Existing user (修改資料): update only personal info, preserve usage/quota
    """
    validated = validate_line_id(text)
    if validated is None:
        await bot_inst.send_validation_error(
            user_id, "LINE ID 格式不正確，請重新輸入或點選跳過",
        )
        return
    line_id = None if validated == "SKIP" else validated
    conv_state = await conv.get(user_id)

    existing = await user_store_inst.get(user_id)
    if existing:
        # 修改資料 — only update personal info, preserve usage/quota
        await user_store_inst.update(
            user_id,
            name=conv_state["reg_name"],
            company=conv_state["reg_company"],
            phone=conv_state["reg_phone"],
            line_id=line_id,
        )
    else:
        # New user — create full profile
        from datetime import datetime, timezone
        profile = UserProfile(
            line_user_id=user_id,
            name=conv_state["reg_name"],
            company=conv_state["reg_company"],
            phone=conv_state["reg_phone"],
            line_id=line_id,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        await user_store_inst.create(profile)

    await conv.complete_registration(user_id)
    await bot_inst.send_registration_complete(user_id)
```

**Modify `_handle_text` (line ~72) to route through profile check:**

At the top of `_handle_text`, before state dispatch:
```python
async def _handle_text(user_id: str, text: str) -> None:
    # 全域指令 — 在任何狀態都有效
    lower = text.strip().lower()
    if lower in ("重新開始", "取消"):
        # editing_narration 特殊處理：寫 rejected，不取消 job
        state = await conv_manager.get(user_id)
        if state["state"] == ConversationState.editing_narration:
            job_id = state.get("job_id")
            if job_id:
                await conv_manager._r.set(
                    f"narration_gate:{job_id}", "rejected", ex=3600,
                )
            await conv_manager.set_processing(user_id, job_id)
            await bot.send_message(user_id, "已取消旁白。")
            return
        await conv_manager.reset(user_id)
        await bot.send_welcome(user_id)
        return
    if lower == "使用說明":
        await bot.send_welcome(user_id)
        return
    if lower == "修改資料":
        profile = await user_store.get(user_id)
        if profile:
            await conv_manager.start_registration(user_id)
            await bot.send_registration_name_prompt(user_id)
        return

    # Profile 檢查
    profile = await user_store.get(user_id)
    state = await conv_manager.get(user_id)
    current = state["state"]

    # 註冊流程
    if current in _REG_STEPS:
        await _handle_registration(user_id, text, current, bot, conv_manager)
        return
    if current == ConversationState.registering_line_id:
        await _handle_registration_line_id(user_id, text, bot, conv_manager, user_store)
        return

    # 新用戶 → 開始註冊
    if profile is None:
        await conv_manager.start_registration(user_id)
        await bot.send_registration_name_prompt(user_id)
        return

    # --- 以下為既有用戶邏輯 ---
    # (existing handler logic continues, with modifications below)
```

**Modify `awaiting_info` handler (line ~141-143):**

Replace direct `_create_job` call with style selection:
```python
    if current == ConversationState.awaiting_info:
        # 暫存 raw_text 到 conv state，進入風格選擇
        state["raw_text"] = text
        await conv_manager._save(user_id, state)
        await conv_manager.set_choosing_style(user_id)
        await line_bot.send_style_choice(user_id)
        return
```

**Modify `_handle_postback` (line ~199) to handle style/narration/skip_line_id:**

```python
async def _handle_postback(user_id: str, data: str) -> None:
    # Skip LINE ID
    if data == "skip_line_id":
        await _handle_registration_line_id(user_id, "跳過", bot, conv_manager, user_store)
        return

    # Style selection
    if data.startswith("style:"):
        style = data.split(":", 1)[1]
        await conv_manager.set_chosen_style(user_id, style)
        await bot.send_narration_choice(user_id)
        return

    # Narration choice
    if data.startswith("narration:"):
        enabled = data == "narration:yes"
        await conv_manager.set_narration_choice(user_id, enabled)
        # 配額檢查 + 建立 job
        profile = await user_store.get(user_id)
        state = await conv_manager.get(user_id)

        # 提前檢查配額
        if not await user_store.try_consume_quota(user_id):
            updated_profile = await user_store.get(user_id)
            await bot.send_quota_exceeded(
                user_id, updated_profile.usage, updated_profile.quota,
            )
            await conv_manager.reset(user_id)
            return

        await _create_job(user_id, state.get("raw_text", ""), state, profile)
        return

    # existing approve/reject handling...
```

**Modify `_create_job` (line ~171-193) to accept profile:**

```python
async def _create_job(user_id: str, raw_text: str, state: dict,
                       profile: UserProfile | None = None) -> None:
    job_id = f"line-{uuid.uuid4().hex[:12]}"
    job_state = JobState(
        job_id=job_id,
        raw_text=raw_text,
        spaces_input=[
            SpaceInput(label=s["label"], photos=s["photos"],
                       is_small_space=s.get("is_small_space", False))
            for s in state.get("spaces", [])
        ],
        exterior_photo=state.get("exterior_photo"),
        line_user_id=user_id,
        premium=profile.plan == "premium" if profile else True,
        staging_template=state.get("chosen_style") or "japanese_muji",
        narration_enabled=state.get("narration_enabled") or False,
    )
    await store.create(job_state)
    await conv_manager.set_processing(user_id, job_id)
    asyncio.create_task(pipeline_runner(job_id))
```

**Add non-text handler for registration states in `_handle_image`:**

At the top of `_handle_image` (line ~38), add guards for states that only accept text:
```python
    state = await conv_manager.get(user_id)
    text_only_reprompts = {
        ConversationState.registering_name: "請輸入您的姓名：",
        ConversationState.registering_company: "請輸入您的公司名稱：",
        ConversationState.registering_phone: "請輸入您的聯絡電話：",
        ConversationState.registering_line_id: "請輸入您的 LINE ID 或點選跳過：",
        ConversationState.editing_narration: "請輸入修改後的講稿：",
    }
    reprompt = text_only_reprompts.get(state["state"])
    if reprompt:
        await line_bot.send_text_only_reminder(user_id, reprompt)
        return
```

**Add quota early check at photo upload (in `_handle_image`, after collecting_photos check):**

```python
    # 提前攔截配額
    if state["state"] == ConversationState.idle:
        profile = await user_store.get(user_id)
        if profile and profile.usage >= profile.quota:
            await bot.send_quota_exceeded(user_id, profile.usage, profile.quota)
            return
```

- [ ] **Step 4: Run all tests**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/line/webhook.py orchestrator/tests/test_registration.py
git commit -m "feat: add registration, style selection, narration choice, and quota check to webhook"
```

---

### Task 7: Profile Injection in Pipeline

**Files:**
- Modify: `orchestrator/pipeline/jobs.py`

- [ ] **Step 1: Import UserStore and add profile injection**

Add import at top:
```python
from orchestrator.stores.user import UserStore
```

In `step_analyze` (line ~85-100), after agent result is saved, add profile injection:

```python
    # Profile injection — fallback to user profile
    if state.line_user_id:
        user_store = UserStore(store.r)
        profile = await user_store.get(state.line_user_id)
        if profile and state.agent_result:
            prop = state.agent_result.property
            if prop:
                prop.agent_name = prop.agent_name or profile.name
                prop.company = prop.company or profile.company
                prop.phone = prop.phone or profile.phone
                prop.line = prop.line or profile.line_id
                await store.save(state)
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/pipeline/jobs.py
git commit -m "feat: inject user profile as fallback for agent-extracted contact info"
```

---

### Task 8: Init UserStore in main.py

**Files:**
- Modify: `orchestrator/main.py`

- [ ] **Step 1: Add UserStore init in lifespan**

Add import:
```python
from orchestrator.stores.user import UserStore
```

In lifespan startup (line ~34-61), after `conv_manager` init:
```python
    from orchestrator.line import webhook as wh
    wh.user_store = UserStore(redis)
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/main.py
git commit -m "feat: init UserStore in FastAPI lifespan"
```

---

## Phase 2: TTS + BGM

### Task 9: Config — MiniMax + BGM

**Files:**
- Modify: `orchestrator/config.py`

- [ ] **Step 1: Add config fields after LINE settings (line ~36)**

```python
    # MiniMax TTS
    minimax_api_key: str = ""
    minimax_group_id: str = ""
    minimax_poll_interval: float = 3.0
    minimax_poll_timeout: float = 120.0
    # BGM
    bgm_url: str = ""
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/config.py
git commit -m "feat: add MiniMax TTS and BGM config fields"
```

---

### Task 10: MiniMax TTS Service

**Files:**
- Create: `orchestrator/services/minimax.py`
- Create: `orchestrator/tests/test_minimax.py`

- [ ] **Step 1: Write failing tests**

```python
# orchestrator/tests/test_minimax.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from orchestrator.services.minimax import MiniMaxService


@pytest.fixture
def service():
    return MiniMaxService(
        api_key="test-key",
        group_id="test-group",
        poll_interval=0.1,
        poll_timeout=1.0,
    )


@pytest.mark.asyncio
async def test_strip_section_markers(service):
    text = "[OPENING]\n信義區\n<#1.0#>\n[客廳]\n大落地窗"
    result = service._strip_markers(text)
    assert "[OPENING]" not in result
    assert "[客廳]" not in result
    assert "<#1.0#>" in result
    assert "信義區" in result
    assert "大落地窗" in result


@pytest.mark.asyncio
async def test_synthesize_success(service):
    """Test full TTS flow with mocked HTTP calls."""
    mock_session = AsyncMock()

    # Mock file upload response
    upload_resp = AsyncMock()
    upload_resp.status = 200
    upload_resp.json = AsyncMock(return_value={"file": {"file_id": "f123"}})

    # Mock create task response
    create_resp = AsyncMock()
    create_resp.status = 200
    create_resp.json = AsyncMock(return_value={"task_id": "t456"})

    # Mock poll response (completed)
    poll_resp = AsyncMock()
    poll_resp.status = 200
    poll_resp.json = AsyncMock(return_value={
        "status": "Success",
        "file_id": "audio_f789",
    })

    # Mock download response
    download_resp = AsyncMock()
    download_resp.status = 200
    download_resp.read = AsyncMock(return_value=b"fake-mp3-data")

    mock_session.post = AsyncMock(side_effect=[upload_resp, create_resp])
    mock_session.get = AsyncMock(side_effect=[poll_resp, download_resp])

    with patch.object(service, "_session", mock_session):
        audio_bytes = await service.synthesize("測試講稿")

    assert audio_bytes == b"fake-mp3-data"


@pytest.mark.asyncio
async def test_synthesize_returns_none_on_failure(service):
    """TTS failure should return None (graceful degradation)."""
    mock_session = AsyncMock()
    upload_resp = AsyncMock()
    upload_resp.status = 500
    mock_session.post = AsyncMock(return_value=upload_resp)

    with patch.object(service, "_session", mock_session):
        result = await service.synthesize("測試")

    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_minimax.py -v`
Expected: ImportError

- [ ] **Step 3: Implement MiniMax service**

```python
# orchestrator/services/minimax.py
from __future__ import annotations

import asyncio
import logging
import re
import time

import aiohttp

logger = logging.getLogger(__name__)

_tts_semaphore = asyncio.Semaphore(5)

_SECTION_MARKER_RE = re.compile(r"^\[.+?\]\s*$", re.MULTILINE)

_BASE_URL = "https://api.minimaxi.chat/v1"


class MiniMaxService:
    def __init__(
        self,
        api_key: str,
        group_id: str,
        poll_interval: float = 3.0,
        poll_timeout: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.group_id = group_id
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._session

    def _strip_markers(self, text: str) -> str:
        return _SECTION_MARKER_RE.sub("", text).strip()

    async def synthesize(self, narration_text: str) -> bytes | None:
        """Full TTS pipeline. Returns audio bytes or None on failure."""
        async with _tts_semaphore:
            try:
                return await self._synthesize_inner(narration_text)
            except Exception:
                logger.exception("TTS synthesis failed")
                return None

    async def _synthesize_inner(self, narration_text: str) -> bytes | None:
        text = self._strip_markers(narration_text)
        session = await self._get_session()

        # Step 1: Upload text file
        file_id = await self._upload_text(session, text)
        if not file_id:
            return None

        # Step 2: Create async TTS task
        task_id = await self._create_task(session, file_id)
        if not task_id:
            return None

        # Step 3: Poll until complete
        audio_file_id = await self._poll_task(session, task_id)
        if not audio_file_id:
            return None

        # Step 4: Download audio
        audio_bytes = await self._download_audio(session, audio_file_id)
        return audio_bytes

    async def _upload_text(self, session: aiohttp.ClientSession, text: str) -> str | None:
        url = f"{_BASE_URL}/files/upload"
        form = aiohttp.FormData()
        form.add_field("file", text.encode("utf-8"),
                       filename="narration.txt", content_type="text/plain")
        form.add_field("purpose", "file-extract")
        for attempt in range(2):
            try:
                resp = await session.post(url, data=form)
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("file", {}).get("file_id")
                logger.warning("TTS upload failed: status=%d", resp.status)
            except Exception:
                logger.exception("TTS upload error (attempt %d)", attempt + 1)
        return None

    async def _create_task(self, session: aiohttp.ClientSession, file_id: str) -> str | None:
        url = f"{_BASE_URL}/t2a_async_v2?GroupId={self.group_id}"
        payload = {
            "model": "speech-2.8-hd",
            "voice_setting": {
                "voice_id": "Chinese_casual_guide_vv2",
                "speed": 1.0,
            },
            "audio_setting": {
                "format": "mp3",
                "sample_rate": 32000,
            },
            "file_setting": {
                "file_id": file_id,
            },
        }
        try:
            resp = await session.post(url, json=payload)
            if resp.status == 200:
                data = await resp.json()
                return data.get("task_id")
            logger.warning("TTS create task failed: status=%d", resp.status)
        except Exception:
            logger.exception("TTS create task error")
        return None

    async def _poll_task(self, session: aiohttp.ClientSession, task_id: str) -> str | None:
        url = f"{_BASE_URL}/query/t2a_async_query_v2?task_id={task_id}"
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            try:
                resp = await session.get(url)
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "Success":
                        return data.get("file_id")
                    if data.get("status") == "Failed":
                        logger.warning("TTS task failed: %s", data)
                        return None
            except Exception:
                logger.exception("TTS poll error")
            await asyncio.sleep(self.poll_interval)
        logger.warning("TTS poll timeout after %.0fs", self.poll_timeout)
        return None

    async def _download_audio(self, session: aiohttp.ClientSession, file_id: str) -> bytes | None:
        url = f"{_BASE_URL}/files/retrieve_content?file_id={file_id}"
        try:
            resp = await session.get(url)
            if resp.status == 200:
                data = await resp.read()
                if data:
                    return data
                logger.warning("TTS download: empty audio")
        except Exception:
            logger.exception("TTS download error")
        return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_minimax.py -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/minimax.py orchestrator/tests/test_minimax.py
git commit -m "feat: add MiniMax TTS service with graceful degradation"
```

---

### Task 11: Narration Gate in Pipeline

**Files:**
- Modify: `orchestrator/pipeline/jobs.py`

- [ ] **Step 1: Add narration gate + TTS task in `step_generate`**

Add imports:
```python
from orchestrator.services.minimax import MiniMaxService
from orchestrator.services.r2 import R2Service
```

Add narration gate helper function:

```python
async def _narration_gate_poll(job_id: str, redis) -> tuple[str, str | None]:
    """Poll narration gate Redis key. Returns (action, edited_text).
    action: 'approved' | 'rejected' | 'edit'
    """
    key = f"narration_gate:{job_id}"
    deadline = time.monotonic() + 600  # 10 min
    while time.monotonic() < deadline:
        val = await redis.get(key)
        if val is None or val in ("pending", "edit_pending"):
            await asyncio.sleep(3)
            continue
        if val == "approved":
            return "approved", None
        if val == "rejected":
            return "rejected", None
        if val.startswith("edit:"):
            return "edit", val[5:]
        await asyncio.sleep(3)
    # Timeout → auto-approve
    return "approved", None


async def _task_tts(state: JobState, redis, minimax: MiniMaxService,
                     r2: R2Service) -> None:
    """Run narration gate + TTS. Updates state in-place."""
    if not state.narration_enabled or not state.narration_text:
        return

    # Set gate pending
    gate_key = f"narration_gate:{state.job_id}"
    await redis.set(gate_key, "pending", ex=3600)

    # Notify user — push narration preview (use existing singleton)
    from orchestrator.line.bot import line_bot
    if line_bot and state.line_user_id:
        await line_bot.send_gate_narration(
            state.line_user_id, state.job_id, state.narration_text,
        )

    state.narration_gate_status = "pending"
    await store.save(state)

    # Wait for gate
    action, edited_text = await _narration_gate_poll(state.job_id, redis)

    if action == "rejected":
        state.narration_gate_status = "rejected"
        state.narration_enabled = False
        await store.save(state)
        return

    # Use edited text if provided
    final_text = edited_text if action == "edit" else state.narration_text
    state.narration_text = final_text
    state.narration_gate_status = "approved"
    await store.save(state)

    # Run TTS
    audio_bytes = await minimax.synthesize(final_text)
    if not audio_bytes:
        logger.warning("TTS failed, degrading to no narration: job=%s", state.job_id)
        state.narration_url = None
        await store.save(state)
        return

    # Log duration (observability)
    try:
        import subprocess
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            logger.info("TTS audio duration: %.1fs (job=%s)", duration, state.job_id)
    except Exception:
        pass  # observability only

    # Upload to R2
    r2_key = f"audio/{state.job_id}/narration.mp3"
    narration_url = await r2.upload_bytes(audio_bytes, r2_key, "audio/mpeg")
    state.narration_url = narration_url
    await store.save(state)
```

- [ ] **Step 2: Modify `step_generate` to include TTS task**

In `step_generate` (line ~237), after creating all asset tasks and before `await asyncio.gather(...)`, add the TTS task:

```python
    # TTS task (parallel with assets)
    tts_task = None
    if state.narration_enabled and state.narration_text:
        from orchestrator.config import settings
        minimax = MiniMaxService(
            api_key=settings.minimax_api_key,
            group_id=settings.minimax_group_id,
            poll_interval=settings.minimax_poll_interval,
            poll_timeout=settings.minimax_poll_timeout,
        )
        r2 = R2Service(settings.r2_proxy_url)
        tts_task = asyncio.create_task(_task_tts(state, store.r, minimax, r2))

    # existing gather for asset tasks...
    await asyncio.gather(*tasks, return_exceptions=True)

    # Wait for TTS if running, then cleanup
    if tts_task:
        await tts_task
        await minimax.close()
```

- [ ] **Step 3: Copy narration text from agent result**

In `step_analyze`, after agent result is saved and profile injection:

```python
    # Copy narration text for TTS
    if state.narration_enabled and state.agent_result and state.agent_result.narration:
        state.narration_text = state.agent_result.narration
        await store.save(state)
```

- [ ] **Step 4: Commit**

```bash
git add orchestrator/pipeline/jobs.py
git commit -m "feat: add narration gate polling and TTS task in step_generate"
```

---

### Task 12: Narration Gate Postback + Bot Method

**Files:**
- Modify: `orchestrator/line/bot.py`
- Modify: `orchestrator/line/webhook.py`

- [ ] **Step 1: Add `send_gate_narration()` to bot.py**

```python
    async def send_gate_narration(
        self, chat_id: str, job_id: str, narration_text: str,
    ) -> None:
        """Send narration preview with approve/edit/reject buttons."""
        # Strip section markers for display
        import re
        display_text = re.sub(r"^\[.+?\]\s*$", "", narration_text, flags=re.MULTILINE)
        display_text = re.sub(r"<#[\d.]+#>", "", display_text).strip()

        actions = [
            {
                "type": "postback",
                "label": "✅ 通過",
                "data": f"narration_gate:{job_id}:approved",
            },
            {
                "type": "postback",
                "label": "✏️ 修改講稿",
                "data": f"narration_gate:{job_id}:edit",
            },
            {
                "type": "postback",
                "label": "❌ 不要旁白",
                "data": f"narration_gate:{job_id}:rejected",
            },
        ]
        bubble = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": "📝 AI 生成的旁白講稿", "weight": "bold", "size": "lg"},
                    {"type": "separator", "margin": "md"},
                    {"type": "text", "text": display_text, "wrap": True,
                     "size": "sm", "margin": "md"},
                ],
            },
            "footer": {
                "type": "box",
                "layout": "horizontal",
                "spacing": "sm",
                "contents": [
                    {"type": "button", "action": a, "style": "primary"
                     if a["label"].startswith("✅") else "secondary",
                     "height": "sm"}
                    for a in actions
                ],
            },
        }
        await self._push(chat_id, [{"type": "flex", "altText": "旁白講稿確認", "contents": bubble}])
```

- [ ] **Step 2: Add narration gate postback handler in webhook.py**

In `_handle_postback`, add before existing approve/reject handling:

```python
    # Narration gate
    if data.startswith("narration_gate:"):
        parts = data.split(":")
        if len(parts) == 3:
            job_id, action = parts[1], parts[2]
            gate_key = f"narration_gate:{job_id}"
            if action == "approved":
                await conv_manager._r.set(gate_key, "approved", ex=3600)
            elif action == "rejected":
                await conv_manager._r.set(gate_key, "rejected", ex=3600)
            elif action == "edit":
                await conv_manager._r.set(gate_key, "edit_pending", ex=3600)
                state = await conv_manager.get(user_id)
                state["state"] = ConversationState.editing_narration
                await conv_manager._save(user_id, state)
                await line_bot.send_message(user_id, "請輸入修改後的講稿：")
        return
```

**Add editing_narration text handler in `_handle_text`:**

After the registration handlers, before existing state dispatch:

```python
    if current == ConversationState.editing_narration:
        job_id = state.get("job_id")
        # 字數限制檢查
        job_state = await store.get(job_id)
        if job_state and job_state.narration_text:
            max_len = int(len(job_state.narration_text) * 1.5)
            if len(text) > max_len:
                await line_bot.send_message(
                    user_id,
                    f"講稿過長（{len(text)} 字），請縮短至 {max_len} 字以內。",
                )
                return
        gate_key = f"narration_gate:{job_id}"
        await conv_manager._r.set(gate_key, f"edit:{text}", ex=3600)
        state["state"] = ConversationState.processing
        await conv_manager._save(user_id, state)
        await line_bot.send_message(user_id, "講稿已更新，正在生成旁白...")
        return
```

- [ ] **Step 3: Commit**

```bash
git add orchestrator/line/bot.py orchestrator/line/webhook.py
git commit -m "feat: add narration gate postback handler and editing flow"
```

---

### Task 13: BGM + Narration in _build_render_input

**Files:**
- Modify: `orchestrator/pipeline/jobs.py`

- [ ] **Step 1: Add narration and BGM to render input**

In `_build_render_input` (line ~451), at the end of the dict construction (before return):

```python
    # Audio
    from orchestrator.config import settings
    if settings.bgm_url:
        render_input["bgm"] = settings.bgm_url
    if state.narration_url:
        render_input["narration"] = state.narration_url
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/pipeline/jobs.py
git commit -m "feat: include narration URL and BGM in render input"
```

---

### Task 14: Remotion — Narration Audio Support

**Files:**
- Modify: `remotion/src/types.ts`
- Modify: `remotion/src/ReelEstateVideo.tsx`
- Modify: `remotion/server/types.ts`
- Modify: `remotion/server/assets.ts`

- [ ] **Step 1: Add `narration` to `VideoInput` in `types.ts`**

After `bgm?: string;` (line ~56):
```typescript
  narration?: string;
```

- [ ] **Step 2: Add `narration` to `RenderInput` in `server/types.ts`**

After `bgm?: string;` (line ~61):
```typescript
  narration?: string;
```

- [ ] **Step 3: Update `ReelEstateVideo.tsx` — audio constants and narration track**

Add constants at top (replace existing bgm volume inline):
```typescript
const BGM_VOLUME = 0.15;
const BGM_VOLUME_WITH_NARRATION = 0.05;
const NARRATION_VOLUME = 1.0;
```

Update the audio section (line ~188-189):
```tsx
{bgm && <Audio src={staticFile(bgm)} volume={narration ? BGM_VOLUME_WITH_NARRATION : BGM_VOLUME} loop />}
{narration && <Audio src={staticFile(narration)} volume={NARRATION_VOLUME} />}
```

Add `narration` to destructured props:
```typescript
const { title, location, ..., bgm, narration } = props;
```

- [ ] **Step 4: Update `assets.ts` — download narration**

In `downloadAssets` (line ~137-147), after BGM download block, add:

```typescript
  // Download narration
  if (input.narration && input.narration.startsWith('http')) {
    const ext = input.narration.split('.').pop() || 'mp3';
    const localPath = path.join(audioDir, `narration.${ext}`);
    await downloadFile(input.narration, localPath);
    input.narration = `audio/narration.${ext}`;
  }
```

- [ ] **Step 5: Commit**

```bash
git add remotion/src/types.ts remotion/src/ReelEstateVideo.tsx remotion/server/types.ts remotion/server/assets.ts
git commit -m "feat: add narration audio track to Remotion with dynamic BGM volume"
```

---

### Task 15: Init MiniMax Service in main.py

**Files:**
- Modify: `orchestrator/main.py`

- [ ] **Step 1: Add MiniMax init in lifespan startup**

This is for crash recovery. The MiniMax service is created on-demand in `step_generate`, but we need to ensure `settings` has the config loaded.

Add to `.env.example`:
```
MINIMAX_API_KEY=
MINIMAX_GROUP_ID=
BGM_URL=
```

No code change needed in `main.py` — MiniMax service is created inline in `step_generate` using `settings`. Just ensure env vars are documented.

- [ ] **Step 2: Commit**

```bash
git add orchestrator/.env.example
git commit -m "docs: add MiniMax and BGM env vars to .env.example"
```

---

### Task 16: Agent SKILL.md — Narration Rules Update

**Files:**
- Modify: `agent/SKILL.md` (or wherever the agent prompt lives)

- [ ] **Step 1: Update narration section**

Add/update the narration rules per spec:
- Dynamic word count table
- 4 字/秒 speech rate
- `<#秒數#>` pause markers between sections
- Keep `[SECTION]` markers (stripped before TTS)
- Remove 「僅供參考」
- Add narration example

- [ ] **Step 2: Commit**

```bash
git add agent/SKILL.md
git commit -m "feat: update agent narration rules with dynamic word count and pause markers"
```

---

## Integration Checklist

After all tasks complete:

- [ ] Run full test suite: `cd orchestrator && python -m pytest tests/ -v`
- [ ] Manual test: new user registration via LINE Bot
- [ ] Manual test: existing user photo → style → narration → job creation
- [ ] Manual test: quota exceeded scenario
- [ ] Manual test: 「修改資料」command
- [ ] Deploy to VPS (use `deploy-update` skill)
