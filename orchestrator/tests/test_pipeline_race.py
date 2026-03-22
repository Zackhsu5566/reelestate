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
