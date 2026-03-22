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


def test_strip_section_markers(service):
    text = "[OPENING]\n信義區\n<#1.0#>\n[客廳]\n大落地窗"
    result = service._strip_markers(text)
    assert "[OPENING]" not in result
    assert "[客廳]" not in result
    assert "<#1.0#>" in result
    assert "信義區" in result
    assert "大落地窗" in result


@pytest.mark.asyncio
async def test_synthesize_success(service):
    """Test full TTS flow: create task → poll → download."""
    mock_session = AsyncMock()
    mock_session.closed = False

    # Mock create task response (single POST, no upload step)
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

    mock_session.post = AsyncMock(return_value=create_resp)
    mock_session.get = AsyncMock(side_effect=[poll_resp, download_resp])

    with patch.object(service, "_session", mock_session):
        audio_bytes = await service.synthesize("測試講稿")

    assert audio_bytes == b"fake-mp3-data"


@pytest.mark.asyncio
async def test_synthesize_returns_none_on_failure(service):
    """TTS failure should return None (graceful degradation)."""
    mock_session = AsyncMock()
    mock_session.closed = False
    create_resp = AsyncMock()
    create_resp.status = 500
    create_resp.text = AsyncMock(return_value="Internal Server Error")
    mock_session.post = AsyncMock(return_value=create_resp)

    with patch.object(service, "_session", mock_session):
        result = await service.synthesize("測試")

    assert result is None
