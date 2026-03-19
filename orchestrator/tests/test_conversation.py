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
