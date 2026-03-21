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
    reg_data = await manager.complete_registration("U999")
    assert reg_data == {"name": "Test", "company": "Co", "phone": "0912345678"}
    state = await manager.get("U999")
    assert state["state"] == ConversationState.idle
    assert state["reg_name"] is None
    assert state["reg_company"] is None
    assert state["reg_phone"] is None


@pytest.mark.asyncio
async def test_set_choosing_style(manager):
    # 從 awaiting_info 狀態呼叫 set_choosing_style
    await manager._save("U999", {"state": ConversationState.awaiting_info})
    await manager.set_choosing_style("U999")
    state = await manager.get("U999")
    assert state["state"] == ConversationState.choosing_style


@pytest.mark.asyncio
async def test_set_chosen_style(manager):
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
