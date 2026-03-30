import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from orchestrator.services.minimax import MiniMaxService, _t2s, _group_subtitles


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

    # Mock subtitle fetch response (code uses .read(), not .json())
    import json as _json
    subtitle_resp = AsyncMock()
    subtitle_resp.status = 200
    subtitle_resp.read = AsyncMock(return_value=_json.dumps(fake_subtitles).encode())

    mock_session.post = AsyncMock(return_value=tts_resp)
    mock_session.get = AsyncMock(return_value=subtitle_resp)

    with patch.object(service, "_session", mock_session):
        result = await service.synthesize("測試講稿")

    assert result is not None
    audio_bytes, subtitles = result
    assert audio_bytes == fake_audio
    # After grouping, only text/time_begin/time_end are kept
    assert len(subtitles) == 1
    assert subtitles[0]["text"] == "測試"
    assert subtitles[0]["time_begin"] == 0.0
    assert subtitles[0]["time_end"] == 2000.0


def test_group_subtitles_merges_short_words():
    """Word-level subtitles should be merged into phrases ≤ 20 chars."""
    subs = [
        {"text": "高雄", "time_begin": 400, "time_end": 720},
        {"text": "楠梓", "time_begin": 720, "time_end": 1200},
        {"text": "京城", "time_begin": 1280, "time_end": 1680},
        {"text": "水", "time_begin": 1680, "time_end": 1920},
        {"text": "森林", "time_begin": 1920, "time_end": 2480},
    ]
    groups = _group_subtitles(subs)
    assert len(groups) == 1
    assert groups[0]["text"] == "高雄楠梓京城水森林"
    assert groups[0]["time_begin"] == 400
    assert groups[0]["time_end"] == 2480


def test_group_subtitles_splits_at_char_limit():
    """Groups should split when exceeding _MAX_GROUP_CHARS (14)."""
    subs = [
        {"text": "一進門就是方正客廳", "time_begin": 0, "time_end": 2000},
        {"text": "空間坪效超級高", "time_begin": 2000, "time_end": 4000},
        {"text": "全部都是大面窗", "time_begin": 4000, "time_end": 6000},
    ]
    groups = _group_subtitles(subs)
    # "一進門就是方正客廳" (9) + "空間坪效超級高" (7) = 16 > 14 → new group
    # "空間坪效超級高" (7) + "全部都是大面窗" (7) = 14 ≤ 14 → merge
    assert len(groups) == 2
    assert groups[0]["text"] == "一進門就是方正客廳"
    assert groups[1]["text"] == "空間坪效超級高全部都是大面窗"


def test_group_subtitles_splits_on_gap():
    """A gap > 300ms between words should force a new group."""
    subs = [
        {"text": "高雄", "time_begin": 0, "time_end": 500},
        {"text": "楠梓", "time_begin": 900, "time_end": 1400},  # 400ms gap
    ]
    groups = _group_subtitles(subs)
    assert len(groups) == 2
    assert groups[0]["text"] == "高雄"
    assert groups[1]["text"] == "楠梓"


def test_group_subtitles_empty():
    assert _group_subtitles([]) == []


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

    import json as _json
    subtitle_resp = AsyncMock()
    subtitle_resp.status = 200
    subtitle_resp.read = AsyncMock(return_value=_json.dumps(fake_subtitles).encode())

    mock_session.post = AsyncMock(side_effect=[fail_resp, ok_resp])
    mock_session.get = AsyncMock(return_value=subtitle_resp)

    with patch.object(service, "_session", mock_session), \
         patch("orchestrator.services.minimax.asyncio.sleep", new_callable=AsyncMock):
        result = await service.synthesize("重試測試")

    assert result is not None
    audio_bytes, subtitles = result
    assert audio_bytes == b"retry-audio"
    assert len(subtitles) == 1
    assert subtitles[0]["text"] == "ok"
