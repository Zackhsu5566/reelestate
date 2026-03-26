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


class TestGateNarrationDisplay:
    def test_markers_converted_to_emoji_titles(self):
        bot = LineBot()
        text = (
            "[OPENING]\n今天帶你來看\n\n"
            "[客廳]\n超大面落地窗\n\n"
            "[MAP]\n信義安和站旁邊\n\n"
            "[STATS]\n三十五坪\n\n"
            "[CTA]\n售價兩千九百八十萬\n"
        )
        display = bot._format_narration_preview(text)
        assert "🎬 開場" in display
        assert "🏠 客廳" in display
        assert "🗺️ 周邊" in display
        assert "📊 規格" in display
        assert "📞 聯繫" in display
        assert "[OPENING]" not in display
        assert "今天帶你來看" in display

    def test_reverse_mapping_emoji_to_markers(self):
        bot = LineBot()
        edited = (
            "🎬 開場\n今天帶你來看\n\n"
            "🏠 客廳\n改過的客廳描述\n\n"
            "🗺️ 周邊\n信義安和站\n\n"
            "📊 規格\n三十五坪\n\n"
            "📞 聯繫\n售價兩千萬\n"
        )
        restored = bot._parse_edited_narration(edited)
        assert "[OPENING]" in restored
        assert "[客廳]" in restored
        assert "[MAP]" in restored
        assert "[STATS]" in restored
        assert "[CTA]" in restored
        assert "今天帶你來看" in restored
        assert "改過的客廳描述" in restored
