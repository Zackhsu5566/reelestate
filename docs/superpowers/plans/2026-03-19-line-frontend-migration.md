# LINE 前端遷移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 ReelEstate 前端從 Telegram 遷移至 LINE Messaging API，包含對話狀態機、Gate 審查、影片交付。

**Architecture:** Orchestrator 新增 `/webhook/line` endpoint 處理對話狀態機（照片收集 + 空間標記 + 物件資訊）。`orchestrator/line/bot.py` 取代 `orchestrator/telegram/bot.py`，用 LINE Push API 推送 Gate 預覽和最終影片。n8n 作為閘道器處理 signature 驗證和照片 R2 上傳。

**Tech Stack:** FastAPI, httpx, Redis (conversation state), LINE Messaging API, n8n

**Spec:** `docs/superpowers/specs/2026-03-19-line-frontend-migration-design.md`

**Deploy Note:** 部署前需清理 Redis 中的舊 job 資料（舊 `line_user_id` 存的是 Telegram chat_id），或確認現有 job 都已完成。

---

## File Structure

### 新增

| 檔案 | 職責 |
|------|------|
| `orchestrator/line/__init__.py` | 模組 init，匯出 `line_bot` singleton |
| `orchestrator/line/bot.py` | LINE Push API client（send_message, send_video, send_gate_preview, send_final） |
| `orchestrator/line/conversation.py` | 對話狀態機（Redis-backed，含 debounce 邏輯） |
| `orchestrator/line/webhook.py` | FastAPI router：`/webhook/line` endpoint |
| `tests/test_line_bot.py` | LINE bot client 單元測試 |
| `tests/test_conversation.py` | 對話狀態機單元測試 |
| `tests/test_line_webhook.py` | Webhook endpoint 整合測試 |

### 修改

| 檔案 | 變更 |
|------|------|
| `orchestrator/config.py:34` | `telegram_bot_token` → `line_channel_access_token` + `line_channel_secret` |
| `orchestrator/models.py:104,117,140` | 移除 `callback_url`；新增 `thumbnail_url` |
| `orchestrator/main.py:26,38,51,100` | import 路徑改為 line；lifespan 改用 `line_bot`；掛載 webhook router；移除 `callback_url` |
| `orchestrator/pipeline/jobs.py:22,300-309,323-327` | import 改為 `line_bot`；`send_gate_preview` 和 `send_final` 參數調整 |

### 刪除

| 檔案 | 理由 |
|------|------|
| `orchestrator/telegram/bot.py` | 被 `orchestrator/line/bot.py` 取代 |
| `orchestrator/telegram/__init__.py` | 整個 telegram 模組移除 |

---

## Task 1: LINE Bot Client

**Files:**
- Create: `orchestrator/line/__init__.py`
- Create: `orchestrator/line/bot.py`
- Create: `tests/test_line_bot.py`

- [ ] **Step 1: Write failing tests for LINE bot client**

```python
# tests/test_line_bot.py
import pytest
from unittest.mock import AsyncMock

from orchestrator.line.bot import LineBot


@pytest.fixture
def bot():
    return LineBot(channel_access_token="test-token")


@pytest.mark.asyncio
async def test_start_creates_client(bot):
    await bot.start()
    assert bot._client is not None
    await bot.close()


@pytest.mark.asyncio
async def test_send_message(bot):
    await bot.start()
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    bot._client.post = AsyncMock(return_value=mock_response)

    await bot.send_message("U1234", "Hello")

    bot._client.post.assert_called_once()
    call_kwargs = bot._client.post.call_args
    assert call_kwargs[0][0] == "https://api.line.me/v2/bot/message/push"
    body = call_kwargs[1]["json"]
    assert body["to"] == "U1234"
    assert body["messages"][0]["type"] == "text"
    assert body["messages"][0]["text"] == "Hello"
    await bot.close()


@pytest.mark.asyncio
async def test_send_video(bot):
    await bot.start()
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    bot._client.post = AsyncMock(return_value=mock_response)

    await bot.send_video("U1234", "https://example.com/v.mp4", "https://example.com/thumb.jpg")

    body = bot._client.post.call_args[1]["json"]
    assert body["messages"][0]["type"] == "video"
    assert body["messages"][0]["originalContentUrl"] == "https://example.com/v.mp4"
    assert body["messages"][0]["previewImageUrl"] == "https://example.com/thumb.jpg"
    await bot.close()


@pytest.mark.asyncio
async def test_send_gate_preview(bot):
    await bot.start()
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    bot._client.post = AsyncMock(return_value=mock_response)

    await bot.send_gate_preview(
        chat_id="U1234",
        job_id="job-001",
        video_url="https://example.com/preview.mp4",
        thumbnail_url="https://example.com/thumb.jpg",
    )

    body = bot._client.post.call_args[1]["json"]
    messages = body["messages"]
    assert len(messages) == 2
    assert messages[0]["type"] == "video"
    assert messages[1]["type"] == "template"
    assert messages[1]["template"]["type"] == "confirm"
    actions = messages[1]["template"]["actions"]
    assert actions[0]["data"] == "approve:job-001:preview"
    assert actions[1]["data"] == "reject:job-001:preview"
    await bot.close()


@pytest.mark.asyncio
async def test_send_gate_preview_no_thumbnail(bot):
    """When thumbnail_url is None, send only confirm template without video."""
    await bot.start()
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    bot._client.post = AsyncMock(return_value=mock_response)

    await bot.send_gate_preview(
        chat_id="U1234",
        job_id="job-001",
        video_url="https://example.com/preview.mp4",
        thumbnail_url=None,
    )

    body = bot._client.post.call_args[1]["json"]
    messages = body["messages"]
    # Without thumbnail: send video URL as text + confirm template
    assert messages[0]["type"] == "text"
    assert "preview.mp4" in messages[0]["text"]
    assert messages[1]["type"] == "template"
    await bot.close()


@pytest.mark.asyncio
async def test_send_final(bot):
    await bot.start()
    mock_response = AsyncMock()
    mock_response.raise_for_status = AsyncMock()
    bot._client.post = AsyncMock(return_value=mock_response)

    await bot.send_final("U1234", "https://example.com/final.mp4", "https://example.com/thumb.jpg")

    body = bot._client.post.call_args[1]["json"]
    messages = body["messages"]
    assert len(messages) == 2
    assert messages[0]["type"] == "video"
    assert messages[1]["type"] == "text"
    assert "完成" in messages[1]["text"]
    await bot.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_line_bot.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement LINE bot client**

```python
# orchestrator/line/__init__.py
from orchestrator.line.bot import line_bot

__all__ = ["line_bot"]
```

```python
# orchestrator/line/bot.py
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineBot:
    """LINE Messaging API Push client."""

    def __init__(self, channel_access_token: str = "") -> None:
        self._token = channel_access_token
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=30)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("LineBot not started. Call start() first.")
        return self._client

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _push(self, to: str, messages: list[dict]) -> None:
        resp = await self.client.post(
            PUSH_URL,
            json={"to": to, "messages": messages},
            headers=self._headers(),
        )
        resp.raise_for_status()

    def _video_message(self, video_url: str, thumbnail_url: str) -> dict:
        return {
            "type": "video",
            "originalContentUrl": video_url,
            "previewImageUrl": thumbnail_url,
        }

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._push(chat_id, [{"type": "text", "text": text}])

    async def send_video(
        self, chat_id: str, video_url: str, thumbnail_url: str
    ) -> None:
        await self._push(chat_id, [self._video_message(video_url, thumbnail_url)])

    async def send_gate_preview(
        self,
        chat_id: str,
        job_id: str,
        video_url: str,
        thumbnail_url: str | None = None,
    ) -> None:
        confirm = {
            "type": "template",
            "altText": "預覽影片確認",
            "template": {
                "type": "confirm",
                "text": "請確認預覽影片是否 OK",
                "actions": [
                    {
                        "type": "postback",
                        "label": "✅ 通過",
                        "data": f"approve:{job_id}:preview",
                    },
                    {
                        "type": "postback",
                        "label": "❌ 不通過",
                        "data": f"reject:{job_id}:preview",
                    },
                ],
            },
        }
        if thumbnail_url:
            messages = [self._video_message(video_url, thumbnail_url), confirm]
        else:
            # No thumbnail: send video URL as text instead
            messages = [
                {"type": "text", "text": f"🎬 預覽影片：\n{video_url}"},
                confirm,
            ]
        await self._push(chat_id, messages)

    async def send_final(
        self, chat_id: str, video_url: str, thumbnail_url: str | None = None
    ) -> None:
        if thumbnail_url:
            messages = [
                self._video_message(video_url, thumbnail_url),
                {"type": "text", "text": "🎉 影片完成！可直接下載使用。"},
            ]
        else:
            messages = [
                {"type": "text", "text": f"🎉 影片完成！可直接下載使用。\n{video_url}"},
            ]
        await self._push(chat_id, messages)


# Module-level singleton (initialized with empty token; config applied at startup)
line_bot = LineBot()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_line_bot.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/line/__init__.py orchestrator/line/bot.py tests/test_line_bot.py
git commit -m "feat: add LINE Messaging API bot client"
```

---

## Task 2: Conversation State Machine

**Files:**
- Create: `orchestrator/line/conversation.py`
- Create: `tests/test_conversation.py`

- [ ] **Step 1: Write failing tests for conversation state machine**

Note: mock_redis uses an in-memory dict so `set`/`get` work correctly across calls.

```python
# tests/test_conversation.py
import pytest
from unittest.mock import AsyncMock

from orchestrator.line.conversation import ConversationManager, ConversationState


@pytest.fixture
def mock_redis():
    """In-memory Redis mock that preserves state across set/get calls."""
    _store = {}
    r = AsyncMock()
    r.get = AsyncMock(side_effect=lambda k: _store.get(k))
    r.set = AsyncMock(side_effect=lambda k, v, **kw: _store.__setitem__(k, v))
    r.delete = AsyncMock(side_effect=lambda k: _store.pop(k, None))
    return r


@pytest.fixture
def manager(mock_redis):
    return ConversationManager(mock_redis)


@pytest.mark.asyncio
async def test_get_new_user_returns_idle(manager):
    state = await manager.get("U1234")
    assert state["state"] == ConversationState.idle
    assert state["pending_photos"] == []
    assert state["spaces"] == []


@pytest.mark.asyncio
async def test_add_photo_sets_collecting(manager):
    await manager.add_photo("U1234", "https://r2.example.com/photo1.jpg")
    state = await manager.get("U1234")
    assert state["state"] == ConversationState.collecting_photos
    assert "https://r2.example.com/photo1.jpg" in state["pending_photos"]


@pytest.mark.asyncio
async def test_add_multiple_photos(manager):
    await manager.add_photo("U1234", "https://r2.example.com/p1.jpg")
    await manager.add_photo("U1234", "https://r2.example.com/p2.jpg")
    state = await manager.get("U1234")
    assert len(state["pending_photos"]) == 2


@pytest.mark.asyncio
async def test_finalize_batch_moves_to_awaiting_label(manager):
    await manager.add_photo("U1234", "https://r2.example.com/photo1.jpg")
    await manager.add_photo("U1234", "https://r2.example.com/photo2.jpg")
    await manager.finalize_batch("U1234")
    state = await manager.get("U1234")
    assert state["state"] == ConversationState.awaiting_label
    assert len(state["pending_photos"]) == 2


@pytest.mark.asyncio
async def test_assign_label_creates_space(manager):
    await manager.add_photo("U1234", "https://r2.example.com/photo1.jpg")
    await manager.finalize_batch("U1234")
    await manager.assign_label("U1234", "客廳")
    state = await manager.get("U1234")
    assert state["state"] == ConversationState.idle
    assert len(state["spaces"]) == 1
    assert state["spaces"][0]["label"] == "客廳"
    assert state["spaces"][0]["photos"] == ["https://r2.example.com/photo1.jpg"]
    assert state["pending_photos"] == []


@pytest.mark.asyncio
async def test_assign_exterior_label(manager):
    await manager.add_photo("U1234", "https://r2.example.com/ext.jpg")
    await manager.finalize_batch("U1234")
    await manager.assign_label("U1234", "外觀")
    state = await manager.get("U1234")
    assert state["exterior_photo"] == "https://r2.example.com/ext.jpg"
    assert state["state"] == ConversationState.idle


@pytest.mark.asyncio
async def test_complete_photos_moves_to_awaiting_info(manager):
    await manager.add_photo("U1234", "https://r2.example.com/photo1.jpg")
    await manager.finalize_batch("U1234")
    await manager.assign_label("U1234", "客廳")
    await manager.complete_photos("U1234")
    state = await manager.get("U1234")
    assert state["state"] == ConversationState.awaiting_info


@pytest.mark.asyncio
async def test_set_processing(manager):
    await manager.set_processing("U1234", "job-001")
    state = await manager.get("U1234")
    assert state["state"] == ConversationState.processing
    assert state["job_id"] == "job-001"


@pytest.mark.asyncio
async def test_reset_clears_state(manager):
    await manager.add_photo("U1234", "https://r2.example.com/photo1.jpg")
    await manager.reset("U1234")
    state = await manager.get("U1234")
    assert state["state"] == ConversationState.idle
    assert state["spaces"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_conversation.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement conversation state machine**

```python
# orchestrator/line/conversation.py
from __future__ import annotations

import json
import logging
from enum import StrEnum

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

KEY_PREFIX = "conv"
CONV_TTL = 86400  # 24 hours


class ConversationState(StrEnum):
    idle = "idle"
    collecting_photos = "collecting"
    awaiting_label = "awaiting_label"
    awaiting_info = "awaiting_info"
    processing = "processing"
    awaiting_feedback = "awaiting_feedback"


def _empty_state() -> dict:
    return {
        "state": ConversationState.idle,
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }


class ConversationManager:
    """Redis-backed conversation state for LINE users."""

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    def _key(self, user_id: str) -> str:
        return f"{KEY_PREFIX}:{user_id}"

    async def get(self, user_id: str) -> dict:
        data = await self._r.get(self._key(user_id))
        if data is None:
            return _empty_state()
        return json.loads(data)

    async def _save(self, user_id: str, state: dict) -> None:
        await self._r.set(
            self._key(user_id),
            json.dumps(state, ensure_ascii=False),
            ex=CONV_TTL,
        )

    async def add_photo(self, user_id: str, photo_url: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.collecting_photos
        state["pending_photos"].append(photo_url)
        await self._save(user_id, state)

    async def finalize_batch(self, user_id: str) -> None:
        state = await self.get(user_id)
        if state["state"] == ConversationState.collecting_photos:
            state["state"] = ConversationState.awaiting_label
            await self._save(user_id, state)

    async def assign_label(self, user_id: str, label: str) -> None:
        state = await self.get(user_id)
        if state["state"] != ConversationState.awaiting_label:
            return

        photos = state["pending_photos"]

        if label == "外觀":
            if photos:
                state["exterior_photo"] = photos[0]
        else:
            state["spaces"].append({"label": label, "photos": photos})

        state["pending_photos"] = []
        state["state"] = ConversationState.idle
        await self._save(user_id, state)

    async def complete_photos(self, user_id: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.awaiting_info
        await self._save(user_id, state)

    async def set_processing(self, user_id: str, job_id: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.processing
        state["job_id"] = job_id
        await self._save(user_id, state)

    async def set_awaiting_feedback(self, user_id: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.awaiting_feedback
        await self._save(user_id, state)

    async def reset(self, user_id: str) -> None:
        await self._save(user_id, _empty_state())

    async def delete(self, user_id: str) -> None:
        await self._r.delete(self._key(user_id))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_conversation.py -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/line/conversation.py tests/test_conversation.py
git commit -m "feat: add Redis-backed conversation state machine for LINE"
```

---

## Task 3: LINE Webhook Endpoint

**Files:**
- Create: `orchestrator/line/webhook.py`
- Create: `tests/test_line_webhook.py`

Note: Tests use a standalone FastAPI test app to avoid dependency on main.py (which still imports Telegram at this point).

- [ ] **Step 1: Write failing tests for webhook endpoint**

```python
# tests/test_line_webhook.py
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from httpx import AsyncClient

from orchestrator.line.webhook import router


def _make_test_app():
    """Create a standalone test app with just the LINE webhook router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def test_app():
    return _make_test_app()


@pytest.fixture
def mock_conv_manager():
    m = AsyncMock()
    m.get = AsyncMock(return_value={
        "state": "idle",
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    })
    return m


@pytest.mark.asyncio
async def test_webhook_image_event(test_app, mock_conv_manager):
    """n8n forwards image event with photo_url already uploaded to R2."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                mock_bot.send_message = AsyncMock()
                resp = await client.post("/webhook/line", json={
                    "events": [{
                        "type": "message",
                        "message": {"type": "image"},
                        "source": {"userId": "U1234"},
                        "photo_url": "https://r2.example.com/photo1.jpg",
                    }]
                })
    assert resp.status_code == 200
    mock_conv_manager.add_photo.assert_called_once_with("U1234", "https://r2.example.com/photo1.jpg")


@pytest.mark.asyncio
async def test_webhook_text_label(test_app, mock_conv_manager):
    """User sends space label while in awaiting_label state."""
    mock_conv_manager.get.return_value = {
        "state": "awaiting_label",
        "pending_photos": ["https://r2.example.com/p1.jpg"],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                mock_bot.send_message = AsyncMock()
                resp = await client.post("/webhook/line", json={
                    "events": [{
                        "type": "message",
                        "message": {"type": "text", "text": "客廳"},
                        "source": {"userId": "U1234"},
                    }]
                })
    assert resp.status_code == 200
    mock_conv_manager.assign_label.assert_called_once_with("U1234", "客廳")


@pytest.mark.asyncio
async def test_webhook_complete_command(test_app, mock_conv_manager):
    """User sends '完成' to finish photo collection."""
    mock_conv_manager.get.return_value = {
        "state": "idle",
        "pending_photos": [],
        "spaces": [{"label": "客廳", "photos": ["url"]}],
        "exterior_photo": None,
        "job_id": None,
    }
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                mock_bot.send_message = AsyncMock()
                resp = await client.post("/webhook/line", json={
                    "events": [{
                        "type": "message",
                        "message": {"type": "text", "text": "完成"},
                        "source": {"userId": "U1234"},
                    }]
                })
    assert resp.status_code == 200
    mock_conv_manager.complete_photos.assert_called_once_with("U1234")


@pytest.mark.asyncio
async def test_webhook_postback_approve(test_app, mock_conv_manager):
    """User taps approve button on gate preview."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.handle_gate_callback", new_callable=AsyncMock) as mock_gate:
                mock_gate.return_value = {"ok": True, "action": "approved"}
                resp = await client.post("/webhook/line", json={
                    "events": [{
                        "type": "postback",
                        "postback": {"data": "approve:job-001:preview"},
                        "source": {"userId": "U1234"},
                    }]
                })
    assert resp.status_code == 200
    mock_gate.assert_called_once_with(
        job_id="job-001", gate="preview", approved=True, feedback=None
    )


@pytest.mark.asyncio
async def test_webhook_postback_reject(test_app, mock_conv_manager):
    """User taps reject button — should ask for feedback."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                mock_bot.send_message = AsyncMock()
                resp = await client.post("/webhook/line", json={
                    "events": [{
                        "type": "postback",
                        "postback": {"data": "reject:job-001:preview"},
                        "source": {"userId": "U1234"},
                    }]
                })
    assert resp.status_code == 200
    mock_conv_manager.set_awaiting_feedback.assert_called_once_with("U1234")


@pytest.mark.asyncio
async def test_webhook_returns_503_when_not_initialized(test_app):
    """Should return 503 if conv_manager not yet initialized."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", None):
            resp = await client.post("/webhook/line", json={
                "events": [{
                    "type": "message",
                    "message": {"type": "text", "text": "hello"},
                    "source": {"userId": "U1234"},
                }]
            })
    assert resp.status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_line_webhook.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement webhook endpoint**

```python
# orchestrator/line/webhook.py
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from orchestrator.line.bot import line_bot
from orchestrator.line.conversation import ConversationManager, ConversationState
from orchestrator.pipeline.gates import handle_gate_callback

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialized in main.py lifespan
conv_manager: ConversationManager | None = None

# Debounce timers: {user_id: asyncio.Task}
_debounce_tasks: dict[str, asyncio.Task] = {}

DEBOUNCE_SECONDS = 5.0


async def _debounce_finalize(user_id: str) -> None:
    """Wait DEBOUNCE_SECONDS then finalize photo batch and ask for label."""
    await asyncio.sleep(DEBOUNCE_SECONDS)
    _debounce_tasks.pop(user_id, None)
    await conv_manager.finalize_batch(user_id)
    state = await conv_manager.get(user_id)
    n = len(state["pending_photos"])
    await line_bot.send_message(user_id, f"收到 {n} 張照片，這是什麼空間？")


def _reset_debounce(user_id: str) -> None:
    """Cancel existing debounce timer and start a new one."""
    existing = _debounce_tasks.get(user_id)
    if existing and not existing.done():
        existing.cancel()
    _debounce_tasks[user_id] = asyncio.create_task(_debounce_finalize(user_id))


async def _handle_image(user_id: str, event: dict) -> None:
    photo_url = event.get("photo_url")
    if not photo_url:
        logger.warning(f"Image event without photo_url for {user_id}")
        return
    await conv_manager.add_photo(user_id, photo_url)
    _reset_debounce(user_id)


async def _handle_text(user_id: str, text: str) -> None:
    state = await conv_manager.get(user_id)
    current = state["state"]

    if current == ConversationState.awaiting_label:
        await conv_manager.assign_label(user_id, text)
        updated = await conv_manager.get(user_id)
        if text == "外觀":
            await line_bot.send_message(
                user_id, "✓ 外觀照片，請繼續傳下一張或輸入『完成』"
            )
        else:
            last_space = updated["spaces"][-1] if updated["spaces"] else None
            count = len(last_space["photos"]) if last_space else 0
            await line_bot.send_message(
                user_id,
                f"✓ {text}（{count} 張），請繼續傳下一張或輸入『完成』",
            )
        return

    if text == "完成":
        if current == ConversationState.collecting_photos:
            # Cancel debounce, finalize immediately
            existing = _debounce_tasks.pop(user_id, None)
            if existing and not existing.done():
                existing.cancel()
            await conv_manager.finalize_batch(user_id)
            await line_bot.send_message(
                user_id,
                "收到，這批照片是什麼空間？先回覆空間名稱再輸入『完成』",
            )
            return

        if not state["spaces"] and not state["exterior_photo"]:
            await line_bot.send_message(user_id, "還沒有傳任何照片喔，請先傳照片。")
            return
        await conv_manager.complete_photos(user_id)
        await line_bot.send_message(user_id, "請輸入物件資訊：")
        return

    if current == ConversationState.awaiting_info:
        await _create_job(user_id, text, state)
        return

    if current == ConversationState.awaiting_feedback:
        if state.get("job_id"):
            await handle_gate_callback(
                job_id=state["job_id"],
                gate="preview",
                approved=False,
                feedback=text,
            )
        await line_bot.send_message(user_id, "✓ 已收到您的回饋，我們會盡快處理。")
        return

    # Default: idle state, unexpected text
    await line_bot.send_message(
        user_id, "請傳照片開始建立影片，或輸入『完成』結束上傳。"
    )


async def _create_job(user_id: str, raw_text: str, state: dict) -> None:
    """Create a pipeline job from conversation state."""
    from orchestrator.pipeline.state import store
    from orchestrator.models import JobState, JobStatus, SpaceInput
    from orchestrator.pipeline.jobs import pipeline_runner
    import uuid

    job_id = f"line-{uuid.uuid4().hex[:12]}"
    spaces_input = [
        SpaceInput(label=s["label"], photos=s["photos"]) for s in state["spaces"]
    ]
    job_state = JobState(
        job_id=job_id,
        status=JobStatus.analyzing,
        raw_text=raw_text,
        spaces_input=spaces_input,
        exterior_photo=state.get("exterior_photo"),
        line_user_id=user_id,
    )
    await store.create(job_state)
    await conv_manager.set_processing(user_id, job_id)
    await line_bot.send_message(user_id, "✓ 收到！開始生成影片，約需 5-10 分鐘。")
    asyncio.create_task(pipeline_runner(job_id))


async def _handle_postback(user_id: str, data: str) -> None:
    """Handle postback from confirm template buttons."""
    parts = data.split(":")
    if len(parts) != 3:
        logger.warning(f"Invalid postback data: {data}")
        return

    action, job_id, gate = parts

    if action == "approve":
        await handle_gate_callback(
            job_id=job_id, gate=gate, approved=True, feedback=None
        )
    elif action == "reject":
        await conv_manager.set_awaiting_feedback(user_id)
        await line_bot.send_message(user_id, "請說明需要修改的地方：")


@router.post("/webhook/line")
async def line_webhook(body: dict) -> dict:
    """Handle forwarded LINE webhook events from n8n."""
    if conv_manager is None:
        raise HTTPException(status_code=503, detail="Service not ready")

    events = body.get("events", [])
    for event in events:
        user_id = event.get("source", {}).get("userId")
        if not user_id:
            continue

        event_type = event.get("type")

        if event_type == "message":
            msg = event.get("message", {})
            msg_type = msg.get("type")

            if msg_type == "image":
                await _handle_image(user_id, event)
            elif msg_type == "text":
                await _handle_text(user_id, msg.get("text", "").strip())

        elif event_type == "postback":
            data = event.get("postback", {}).get("data", "")
            await _handle_postback(user_id, data)

    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_line_webhook.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/line/webhook.py tests/test_line_webhook.py
git commit -m "feat: add LINE webhook endpoint with conversation flow"
```

---

## Task 4: Update Config + Models

**Files:**
- Modify: `orchestrator/config.py:34`
- Modify: `orchestrator/models.py:104,117,140`

- [ ] **Step 1: Update config.py — replace Telegram token with LINE credentials**

In `orchestrator/config.py`, replace:
```python
telegram_bot_token: str = ""
```
with:
```python
line_channel_access_token: str = ""
line_channel_secret: str = ""
```

- [ ] **Step 2: Update models.py — remove callback_url, add thumbnail_url**

In `orchestrator/models.py`:

1. Remove `callback_url: str = ""` from `JobState` (line 104)
2. Add `thumbnail_url: str | None = None` to `JobState` (after `preview_url`, around line 117)
3. Remove `callback_url: str = ""` from `CreateJobRequest` (line 140)

- [ ] **Step 3: Run existing tests to check for breakage**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add orchestrator/config.py orchestrator/models.py
git commit -m "refactor: replace Telegram config with LINE credentials, remove callback_url, add thumbnail_url"
```

---

## Task 5: Wire Up main.py + jobs.py

**Files:**
- Modify: `orchestrator/main.py:26,38,51,100`
- Modify: `orchestrator/pipeline/jobs.py:22,300-309,323-327`

- [ ] **Step 1: Update main.py imports and lifespan**

In `orchestrator/main.py`:

Replace import (line 26):
```python
from orchestrator.telegram.bot import telegram_bot
```
with:
```python
from orchestrator.line.bot import line_bot
from orchestrator.line.webhook import router as line_router
from orchestrator.line.conversation import ConversationManager
```

Replace startup (line 38):
```python
await telegram_bot.start()
```
with:
```python
line_bot._token = settings.line_channel_access_token
await line_bot.start()
import orchestrator.line.webhook as line_wh
line_wh.conv_manager = ConversationManager(store.r)
```

Replace shutdown (line 51):
```python
await telegram_bot.close()
```
with:
```python
await line_bot.close()
```

Remove `callback_url` from job creation (line 100):
```python
        callback_url=req.callback_url,
```
Delete this line entirely.

Add router mount (after app creation, before routes):
```python
app.include_router(line_router)
```

- [ ] **Step 2: Update jobs.py imports and send calls**

In `orchestrator/pipeline/jobs.py`:

Replace import (line 22):
```python
from orchestrator.telegram.bot import telegram_bot
```
with:
```python
from orchestrator.line.bot import line_bot
```

Replace send_gate_preview call (lines 300-309):
```python
if state.line_user_id:
    try:
        await telegram_bot.send_gate_preview(
            chat_id=state.line_user_id,
            job_id=state.job_id,
            video_url=url,
            callback_url=state.callback_url,
        )
    except Exception as e:
        logger.warning(f"[{state.job_id}] Telegram send_gate_preview failed: {e}")
```
with:
```python
if state.line_user_id:
    try:
        await line_bot.send_gate_preview(
            chat_id=state.line_user_id,
            job_id=state.job_id,
            video_url=url,
            thumbnail_url=state.thumbnail_url,
        )
    except Exception as e:
        logger.warning(f"[{state.job_id}] LINE send_gate_preview failed: {e}")
```

Replace send_final call (lines 323-327):
```python
if state.line_user_id and state.final_url:
    try:
        await telegram_bot.send_final(state.line_user_id, state.final_url)
    except Exception as e:
        logger.warning(f"[{state.job_id}] Telegram send_final failed: {e}")
```
with:
```python
if state.line_user_id and state.final_url:
    try:
        await line_bot.send_final(
            state.line_user_id,
            state.final_url,
            state.thumbnail_url,
        )
    except Exception as e:
        logger.warning(f"[{state.job_id}] LINE send_final failed: {e}")
```

- [ ] **Step 3: Run all tests**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add orchestrator/main.py orchestrator/pipeline/jobs.py
git commit -m "refactor: wire LINE bot into main.py and jobs.py, replace Telegram calls"
```

---

## Task 6: Delete Telegram Module

**Files:**
- Delete: `orchestrator/telegram/bot.py`
- Delete: `orchestrator/telegram/__init__.py`

- [ ] **Step 1: Verify no remaining references to telegram module**

Run: `grep -r "telegram" orchestrator/ --include="*.py" -l`
Expected: No files returned

- [ ] **Step 2: Delete telegram module**

```bash
rm -rf orchestrator/telegram/
```

- [ ] **Step 3: Run all tests to confirm nothing breaks**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add -A orchestrator/telegram/
git commit -m "refactor: remove Telegram bot module (replaced by LINE)"
```

---

## Task 7: Render Server Thumbnail Support

**Files:**
- Modify: `orchestrator/pipeline/jobs.py` (step_render)

- [ ] **Step 1: Update step_render to capture thumbnail_url from render response**

In `orchestrator/pipeline/jobs.py`, in `step_render()`, after getting the render output URL from `render_service.poll()`, add:

```python
state.thumbnail_url = render_result.get("thumbnailUrl")
```

Note: The render server needs a separate deploy to generate thumbnails (ffmpeg first frame → R2 upload → return `thumbnailUrl`). Until then, `thumbnail_url` will be `None` and `send_gate_preview`/`send_final` will gracefully fall back to text-only messages.

- [ ] **Step 2: Run all tests**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add orchestrator/pipeline/jobs.py
git commit -m "feat: capture thumbnail_url from render response for LINE video messages"
```

---

## Task 8: Update Documentation

**Files:**
- Modify: `ARCHITECTURE.md`
- Modify: `concept.md`

- [ ] **Step 1: Update ARCHITECTURE.md**

Replace all Telegram references with LINE:
- 「Telegram Bot」→「LINE Messaging API」
- 「Telegram 推送」→「LINE Push API」
- 「telegram/bot.py」→「line/bot.py」
- Add `line/webhook.py` and `line/conversation.py` to architecture diagram
- 新增 `/webhook/line` endpoint 說明

- [ ] **Step 2: Update concept.md**

Replace Telegram references:
- 「Telegram（房仲傳照片 + 空間標記 + 物件文字）」→「LINE（房仲傳照片 + 空間標記 + 物件文字）」
- 「Telegram 推送 + 等 callback」→「LINE Push API + postback」
- Gate 表格更新

- [ ] **Step 3: Commit**

```bash
git add ARCHITECTURE.md concept.md
git commit -m "docs: update architecture and concept docs for LINE migration"
```

---

## Task 9: Environment Variables + .env

**Files:**
- Modify: `orchestrator/.env.example`

- [ ] **Step 1: Update .env.example**

Replace:
```
TELEGRAM_BOT_TOKEN=
```
with:
```
LINE_CHANNEL_ACCESS_TOKEN=
LINE_CHANNEL_SECRET=
```

- [ ] **Step 2: Commit**

```bash
git add orchestrator/.env.example
git commit -m "chore: update .env.example for LINE credentials"
```

---

## Task 10: E2E Smoke Test (Manual)

This task is manual — verify the full flow after LINE Official Account is set up.

- [ ] **Step 1: Set up LINE Official Account + Messaging API channel**
- [ ] **Step 2: Configure webhook URL in LINE Developer Console → point to n8n**
- [ ] **Step 3: Set up n8n workflow (signature verification + photo R2 upload + forward to orchestrator)**
- [ ] **Step 4: Set environment variables on VPS**
- [ ] **Step 5: Deploy orchestrator update (ensure Redis has no stale Telegram-era jobs)**
- [ ] **Step 6: Test flow: send photo via LINE → label → complete → info → wait for pipeline → gate → final delivery**

---

## Out of Scope (Future Tasks)

- **Render server thumbnail generation**: VPS render server needs to generate thumbnail (ffmpeg first frame) and return `thumbnailUrl` in response. Deploy separately. Until then, LINE messages fall back to text + URL.
- **n8n workflow creation**: Detailed n8n node configuration is out of scope for this code plan.
- **LINE Official Account setup**: Manual setup in LINE Developer Console.
- **Pipeline error notification to LINE**: Currently logs warning only. Future enhancement to push error messages to LINE user.
