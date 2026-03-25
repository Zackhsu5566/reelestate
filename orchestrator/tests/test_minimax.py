import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from orchestrator.services.minimax import MiniMaxService, _t2s


@pytest.fixture
def service():
    return MiniMaxService(
        api_key="test-key",
        group_id="test-group",
        poll_interval=0.1,
        poll_timeout=1.0,
    )


def test_strip_section_markers(service):
    text = "[OPENING]\n信義區\n<#1.0#>\n[客廳]\n大落地窗"
    result = service._strip_markers(text)
    assert "[OPENING]" not in result
    assert "[客廳]" not in result
    assert "<#1.0#>" in result
    assert "信義區" in result
    assert "大落地窗" in result


def test_traditional_to_simplified_conversion(service):
    """Narration text should be converted to Simplified Chinese for MiniMax."""
    assert _t2s.convert("信義區的優質物件") == "信义区的优质物件"
    assert _t2s.convert("大落地窗與陽台") == "大落地窗与阳台"


@pytest.mark.asyncio
async def test_synthesize_success(service):
    """Test sync TTS flow: POST t2a_v2 → decode hex audio + fetch subtitles."""
    mock_session = AsyncMock()
    mock_session.closed = False

    fake_audio = b"fake-mp3-data"
    fake_audio_hex = fake_audio.hex()

    fake_subtitles = [
        {"text": "測試", "time_begin": 0.0, "time_end": 2000.0, "pronounce_text": "測試"},
    ]

    # Mock sync TTS response
    tts_resp = AsyncMock()
    tts_resp.status = 200
    tts_resp.json = AsyncMock(return_value={
        "data": {
            "audio": fake_audio_hex,
            "subtitle_file": "https://cdn.minimax.chat/subtitles/abc123.json",
        },
        "base_resp": {"status_code": 0},
    })

    # Mock subtitle fetch response
    subtitle_resp = AsyncMock()
    subtitle_resp.status = 200
    subtitle_resp.json = AsyncMock(return_value=fake_subtitles)

    mock_session.post = AsyncMock(return_value=tts_resp)
    mock_session.get = AsyncMock(return_value=subtitle_resp)

    with patch.object(service, "_session", mock_session):
        result = await service.synthesize("測試講稿")

    assert result is not None
    audio_bytes, subtitles = result
    assert audio_bytes == fake_audio
    assert subtitles == fake_subtitles


@pytest.mark.asyncio
async def test_synthesize_returns_none_on_failure(service):
    """TTS failure should return None (graceful degradation)."""
    mock_session = AsyncMock()
    mock_session.closed = False
    tts_resp = AsyncMock()
    tts_resp.status = 500
    tts_resp.text = AsyncMock(return_value="Internal Server Error")
    mock_session.post = AsyncMock(return_value=tts_resp)

    with patch.object(service, "_session", mock_session):
        result = await service.synthesize("測試")

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_returns_none_on_api_error_status(service):
    """Non-zero base_resp.status_code should return None."""
    mock_session = AsyncMock()
    mock_session.closed = False

    tts_resp = AsyncMock()
    tts_resp.status = 200
    tts_resp.json = AsyncMock(return_value={
        "data": {},
        "base_resp": {"status_code": 1001, "status_msg": "rate limit"},
    })
    mock_session.post = AsyncMock(return_value=tts_resp)

    with patch.object(service, "_session", mock_session):
        result = await service.synthesize("測試")

    assert result is None


@pytest.mark.asyncio
async def test_synthesize_retries_on_first_failure(service):
    """Should retry once after first failure then succeed."""
    mock_session = AsyncMock()
    mock_session.closed = False

    fake_audio = b"retry-audio"
    fake_subtitles = [{"text": "ok", "time_begin": 0.0, "time_end": 1000.0}]

    # First call fails (500), second succeeds
    fail_resp = AsyncMock()
    fail_resp.status = 500
    fail_resp.text = AsyncMock(return_value="error")

    ok_resp = AsyncMock()
    ok_resp.status = 200
    ok_resp.json = AsyncMock(return_value={
        "data": {
            "audio": fake_audio.hex(),
            "subtitle_file": "https://cdn.minimax.chat/sub.json",
        },
        "base_resp": {"status_code": 0},
    })

    subtitle_resp = AsyncMock()
    subtitle_resp.status = 200
    subtitle_resp.json = AsyncMock(return_value=fake_subtitles)

    mock_session.post = AsyncMock(side_effect=[fail_resp, ok_resp])
    mock_session.get = AsyncMock(return_value=subtitle_resp)

    with patch.object(service, "_session", mock_session), \
         patch("orchestrator.services.minimax.asyncio.sleep", new_callable=AsyncMock):
        result = await service.synthesize("重試測試")

    assert result is not None
    audio_bytes, subtitles = result
    assert audio_bytes == fake_audio
