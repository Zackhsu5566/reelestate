import pytest
from unittest.mock import AsyncMock, patch
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
    return m


@pytest.mark.asyncio
async def test_webhook_image_event(test_app, mock_conv_manager):
    """n8n forwards image event with photo_url already uploaded to R2."""
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
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
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
    async with AsyncClient(transport=httpx.ASGITransport(app=test_app), base_url="http://test") as client:
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
