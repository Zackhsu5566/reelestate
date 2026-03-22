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

        mock_store = JobStore()
        mock_store._redis = AsyncMock()
        mock_store.save = AsyncMock()
        mock_store.update_narration = AsyncMock()

        state = _make_state(
            narration_enabled=True,
            narration_text="[OPENING]\n測試旁白",
        )

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock()
        mock_redis.get = AsyncMock(return_value="approved")

        mock_minimax = AsyncMock()
        mock_minimax.synthesize = AsyncMock(return_value=b"fake-mp3-data")

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
            await jobs._task_tts(state, mock_redis, mock_minimax, mock_r2)
        finally:
            jobs.store = original_store
            jobs.line_bot = original_line_bot

        mock_store.save.assert_not_called()
        assert mock_store.update_narration.call_count >= 1
