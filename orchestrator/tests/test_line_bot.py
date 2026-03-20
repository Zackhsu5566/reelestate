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
    mock_response.status_code = 200
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
    mock_response.status_code = 200
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
    mock_response.status_code = 200
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
    mock_response.status_code = 200
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
    mock_response.status_code = 200
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
