import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI
import httpx
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
    m.add_photo = AsyncMock(return_value=1)
    return m


@pytest.fixture
def mock_user_store():
    """User store mock that returns a registered user within quota by default."""
    profile = MagicMock()
    profile.usage = 0
    profile.quota = 3
    m = AsyncMock()
    m.get = AsyncMock(return_value=profile)
    return m


@pytest.mark.asyncio
async def test_webhook_image_event(test_app, mock_conv_manager, mock_user_store):
    """n8n forwards image event with photo_url — first photo triggers send_photo_started."""
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.user_store", mock_user_store):
                with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                    mock_bot.send_photo_started = AsyncMock()
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
    mock_bot.send_photo_started.assert_called_once_with("U1234")


@pytest.mark.asyncio
async def test_webhook_image_during_collecting(test_app, mock_conv_manager):
    """Second photo during collecting_photos should NOT send photo_started."""
    mock_conv_manager.get.return_value = {
        "state": "collecting",
        "pending_photos": ["https://r2.example.com/p1.jpg"],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }
    mock_conv_manager.add_photo = AsyncMock(return_value=2)
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                mock_bot.send_photo_started = AsyncMock()
                resp = await client.post("/webhook/line", json={
                    "events": [{
                        "type": "message",
                        "message": {"type": "image"},
                        "source": {"userId": "U1234"},
                        "photo_url": "https://r2.example.com/photo2.jpg",
                    }]
                })
    assert resp.status_code == 200
    mock_conv_manager.add_photo.assert_called_once()
    mock_bot.send_photo_started.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_image_during_processing(test_app, mock_conv_manager):
    """Photos during processing should be rejected."""
    mock_conv_manager.get.return_value = {
        "state": "processing",
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": "job-001",
    }
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
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
    mock_conv_manager.add_photo.assert_not_called()
    mock_bot.send_message.assert_called_once()
    assert "製作中" in mock_bot.send_message.call_args[0][1]


@pytest.mark.asyncio
async def test_webhook_text_label(test_app, mock_conv_manager, mock_user_store):
    """User sends space label while in awaiting_label state."""
    mock_conv_manager.get.return_value = {
        "state": "awaiting_label",
        "pending_photos": ["https://r2.example.com/p1.jpg"],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.user_store", mock_user_store):
                with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                    mock_bot.send_space_summary = AsyncMock()
                    # After assign_label, get() returns updated state
                    mock_conv_manager.get.side_effect = [
                        {  # First call in _handle_text
                            "state": "awaiting_label",
                            "pending_photos": ["https://r2.example.com/p1.jpg"],
                            "spaces": [],
                            "exterior_photo": None,
                            "job_id": None,
                        },
                        {  # Second call after assign_label
                            "state": "idle",
                            "pending_photos": [],
                            "spaces": [{"label": "客廳", "photos": ["https://r2.example.com/p1.jpg"]}],
                            "exterior_photo": None,
                            "job_id": None,
                        },
                    ]
                    resp = await client.post("/webhook/line", json={
                        "events": [{
                            "type": "message",
                            "message": {"type": "text", "text": "客廳"},
                            "source": {"userId": "U1234"},
                        }]
                    })
    assert resp.status_code == 200
    mock_conv_manager.assign_label.assert_called_once_with("U1234", "客廳")
    mock_bot.send_space_summary.assert_called_once()


@pytest.mark.asyncio
async def test_webhook_complete_command(test_app, mock_conv_manager, mock_user_store):
    """User sends '完成' in idle with spaces → complete_photos + send_info_prompt."""
    mock_conv_manager.get.return_value = {
        "state": "idle",
        "pending_photos": [],
        "spaces": [{"label": "客廳", "photos": ["url"]}],
        "exterior_photo": None,
        "job_id": None,
    }
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.user_store", mock_user_store):
                with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                    mock_bot.send_info_prompt = AsyncMock()
                    resp = await client.post("/webhook/line", json={
                        "events": [{
                            "type": "message",
                            "message": {"type": "text", "text": "完成"},
                            "source": {"userId": "U1234"},
                        }]
                    })
    assert resp.status_code == 200
    mock_conv_manager.complete_photos.assert_called_once_with("U1234")
    mock_bot.send_info_prompt.assert_called_once_with("U1234")


@pytest.mark.asyncio
async def test_webhook_batch_complete(test_app, mock_conv_manager, mock_user_store):
    """User sends '完成' during collecting_photos → finalize + label prompt."""
    mock_conv_manager.get.return_value = {
        "state": "collecting",
        "pending_photos": ["url1", "url2"],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.user_store", mock_user_store):
                with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                    mock_bot.send_label_prompt = AsyncMock()
                    resp = await client.post("/webhook/line", json={
                        "events": [{
                            "type": "message",
                            "message": {"type": "text", "text": "完成"},
                            "source": {"userId": "U1234"},
                        }]
                    })
    assert resp.status_code == 200
    mock_conv_manager.finalize_batch.assert_called_once_with("U1234")
    mock_bot.send_label_prompt.assert_called_once_with("U1234", 2)


@pytest.mark.asyncio
async def test_webhook_reset_command(test_app, mock_conv_manager):
    """'重新開始' resets conversation and sends welcome."""
    mock_conv_manager.get.return_value = {
        "state": "collecting",
        "pending_photos": ["url1"],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                mock_bot.send_welcome = AsyncMock()
                resp = await client.post("/webhook/line", json={
                    "events": [{
                        "type": "message",
                        "message": {"type": "text", "text": "重新開始"},
                        "source": {"userId": "U1234"},
                    }]
                })
    assert resp.status_code == 200
    mock_conv_manager.reset.assert_called_once_with("U1234")
    mock_bot.send_welcome.assert_called_once_with("U1234")


@pytest.mark.asyncio
async def test_webhook_text_during_collecting(test_app, mock_conv_manager, mock_user_store):
    """Random text during collecting_photos should hint to use '完成'."""
    mock_conv_manager.get.return_value = {
        "state": "collecting",
        "pending_photos": ["url1"],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.user_store", mock_user_store):
                with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                    mock_bot.send_message = AsyncMock()
                    resp = await client.post("/webhook/line", json={
                        "events": [{
                            "type": "message",
                            "message": {"type": "text", "text": "你好"},
                            "source": {"userId": "U1234"},
                        }]
                    })
    assert resp.status_code == 200
    assert "完成" in mock_bot.send_message.call_args[0][1]


@pytest.mark.asyncio
async def test_webhook_text_during_processing(test_app, mock_conv_manager, mock_user_store):
    """Text during processing should show 'making video' message."""
    mock_conv_manager.get.return_value = {
        "state": "processing",
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": "job-001",
    }
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", mock_conv_manager):
            with patch("orchestrator.line.webhook.user_store", mock_user_store):
                with patch("orchestrator.line.webhook.line_bot") as mock_bot:
                    mock_bot.send_message = AsyncMock()
                    resp = await client.post("/webhook/line", json={
                        "events": [{
                            "type": "message",
                            "message": {"type": "text", "text": "好了嗎"},
                            "source": {"userId": "U1234"},
                        }]
                    })
    assert resp.status_code == 200
    assert "製作中" in mock_bot.send_message.call_args[0][1]


@pytest.mark.asyncio
async def test_webhook_postback_approve(test_app, mock_conv_manager):
    """User taps approve button on gate preview."""
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
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
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
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
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
        with patch("orchestrator.line.webhook.conv_manager", None):
            resp = await client.post("/webhook/line", json={
                "events": [{
                    "type": "message",
                    "message": {"type": "text", "text": "hello"},
                    "source": {"userId": "U1234"},
                }]
            })
    assert resp.status_code == 503
