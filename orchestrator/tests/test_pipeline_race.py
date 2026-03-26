"""Tests for pipeline race condition fixes."""
import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

# Stub orchestrator.config before importing state module to avoid env validation
_config_stub = ModuleType("orchestrator.config")
_config_stub.settings = MagicMock(redis_url="redis://localhost:6379/0")  # type: ignore[attr-defined]
sys.modules.setdefault("orchestrator.config", _config_stub)

from orchestrator.models import JobState, JobStatus, AssetTask
from orchestrator.pipeline.state import JobStore


def _make_state(**overrides) -> JobState:
    defaults = dict(
        job_id="test-123",
        status=JobStatus.generating,
        raw_text="test",
        line_user_id="U123",
    )
    defaults.update(overrides)
    return JobState(**defaults)


class TestUpdateNarration:
    """update_narration must only touch narration fields, preserving asset_tasks."""

    @pytest.mark.asyncio
    async def test_preserves_asset_tasks(self):
        """Simulate: asset task written, then narration update — asset task must survive."""
        store = JobStore()
        store._redis = AsyncMock()

        state = _make_state(
            asset_tasks={"clip:客廳:0": AssetTask(status="completed", output_url="https://example.com/a.mp4")},
        )

        store._redis.get = AsyncMock(return_value=state.model_dump_json())
        store._redis.set = AsyncMock()

        await store.update_narration("test-123", narration_gate_status="approved", narration_text="hello")

        saved_json = store._redis.set.call_args[0][1]
        saved = JobState.model_validate_json(saved_json)
        assert "clip:客廳:0" in saved.asset_tasks
        assert saved.asset_tasks["clip:客廳:0"].status == "completed"
        assert saved.narration_gate_status == "approved"
        assert saved.narration_text == "hello"

    @pytest.mark.asyncio
    async def test_ignores_none_values(self):
        store = JobStore()
        store._redis = AsyncMock()

        state = _make_state(narration_text="original")
        store._redis.get = AsyncMock(return_value=state.model_dump_json())
        store._redis.set = AsyncMock()

        await store.update_narration("test-123", narration_gate_status="pending")

        saved_json = store._redis.set.call_args[0][1]
        saved = JobState.model_validate_json(saved_json)
        assert saved.narration_text == "original"
        assert saved.narration_gate_status == "pending"

    @pytest.mark.asyncio
    async def test_rejects_non_narration_fields(self):
        store = JobStore()
        store._redis = AsyncMock()

        state = _make_state()
        store._redis.get = AsyncMock(return_value=state.model_dump_json())

        with pytest.raises(ValueError, match="Not a narration field"):
            await store.update_narration("test-123", status="failed")


class TestTaskTtsNoOverwrite:
    """_task_tts must never call store.save(state) directly."""

    @pytest.mark.asyncio
    async def test_tts_uses_update_narration(self):
        """After _task_tts runs, store.save must NOT be called — only update_narration."""
        from orchestrator.pipeline.state import JobStore

        state = _make_state(
            narration_enabled=True,
            narration_text="[OPENING]\n測試旁白",
        )

        mock_store = JobStore()
        mock_store._redis = AsyncMock()
        mock_store.save = AsyncMock()
        mock_store.update_narration = AsyncMock()
        # store.get() is called to re-read state for scene building
        mock_store.get = AsyncMock(return_value=state)

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value="approved")

        # synthesize returns (audio_bytes, subtitles_list)
        # Generate valid MP3 bytes so pydub can decode them in assemble_audio
        from pydub import AudioSegment as _AS
        from io import BytesIO as _BIO
        _buf = _BIO()
        _AS.silent(duration=500).export(_buf, format="mp3")
        fake_audio = _buf.getvalue()
        fake_subs = [{"text": "測試旁白", "time_begin": 0, "time_end": 500}]
        mock_minimax = AsyncMock()
        mock_minimax.synthesize = AsyncMock(return_value=(fake_audio, fake_subs))

        mock_r2 = AsyncMock()
        mock_r2.upload_bytes = AsyncMock(return_value="https://example.com/narration.mp3")

        # Stub heavy dependencies so jobs module can be imported
        for mod_name in [
            "anthropic", "orchestrator.services.agent",
            "orchestrator.services.wavespeed", "orchestrator.services.render",
            "orchestrator.services.r2", "orchestrator.stores.user",
            "orchestrator.line.bot", "orchestrator.staging_prompts",
        ]:
            sys.modules.setdefault(mod_name, MagicMock())

        from orchestrator.pipeline import jobs
        original_store = jobs.store
        original_line_bot = jobs.line_bot
        try:
            jobs.store = mock_store
            jobs.line_bot = None
            result = await jobs._task_tts(state, mock_redis, mock_minimax)
        finally:
            jobs.store = original_store
            jobs.line_bot = original_line_bot

        mock_store.save.assert_not_called()
        assert mock_store.update_narration.call_count >= 1
        # _task_tts now returns (sections, section_results) for later alignment
        assert result is not None
        sections, section_results = result
        assert len(sections) == 1
        assert sections[0]["marker"] == "OPENING"
        assert len(section_results) == 1


from orchestrator.models import SpaceInfo, SpaceInput, AgentResult, PropertyInfo, AgentMeta

# Stub heavy dependencies so jobs module can be imported at class level
for _mod_name in [
    "anthropic", "orchestrator.services.agent",
    "orchestrator.services.wavespeed", "orchestrator.services.render",
    "orchestrator.services.r2", "orchestrator.stores.user",
    "orchestrator.line.bot", "orchestrator.staging_prompts",
    "orchestrator.services.minimax",
]:
    sys.modules.setdefault(_mod_name, MagicMock())


def _make_agent_result(spaces: list[SpaceInfo]) -> AgentResult:
    return AgentResult(
        property=PropertyInfo(address="test"),
        title="test",
        narration="test narration",
        spaces=spaces,
        meta=AgentMeta(agent_version="3.0"),
    )


class TestDuplicateSpaceKeys:
    """Two spaces with same name must produce unique asset_task keys."""

    def test_build_task_key_prefix_unique(self):
        from orchestrator.pipeline.jobs import _build_task_key_prefix
        assert _build_task_key_prefix(0) != _build_task_key_prefix(1)

    def test_get_space_photos_uses_agent_photos(self):
        from orchestrator.pipeline.jobs import _get_space_photos

        state = _make_state(
            spaces_input=[
                SpaceInput(label="臥室", photos=["photo_A.jpg"]),
                SpaceInput(label="臥室", photos=["photo_B.jpg"]),
            ],
        )
        space_a = SpaceInfo(name="臥室", photo_count=1, photos=["photo_A.jpg"])
        space_b = SpaceInfo(name="臥室", photo_count=1, photos=["photo_B.jpg"])

        assert _get_space_photos(state, space_a, 0) == ["photo_A.jpg"]
        assert _get_space_photos(state, space_b, 1) == ["photo_B.jpg"]

    def test_fallback_uses_positional_index(self):
        from orchestrator.pipeline.jobs import _get_space_photos

        state = _make_state(
            spaces_input=[
                SpaceInput(label="臥室", photos=["photo_A.jpg"]),
                SpaceInput(label="臥室", photos=["photo_B.jpg"]),
            ],
        )
        space_a = SpaceInfo(name="臥室", photo_count=1, photos=[])
        space_b = SpaceInfo(name="臥室", photo_count=1, photos=[])

        assert _get_space_photos(state, space_a, 0) == ["photo_A.jpg"]
        assert _get_space_photos(state, space_b, 1) == ["photo_B.jpg"]
