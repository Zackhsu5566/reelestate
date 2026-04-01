"""Tests for dry-render endpoint."""
import sys
from types import ModuleType
from unittest.mock import MagicMock

import httpx  # noqa: E402 — import before stubs to keep real httpx
import pytest

# Stub config before importing
_config_stub = ModuleType("orchestrator.config")
_config_stub.settings = MagicMock(redis_url="redis://localhost:6379/0")
sys.modules.setdefault("orchestrator.config", _config_stub)

from orchestrator.models import DryRenderRequest, DryRenderOverrides, SceneOverride


class TestDryRenderModels:
    def test_empty_request(self):
        req = DryRenderRequest()
        assert req.overrides is None

    def test_with_overrides(self):
        req = DryRenderRequest(
            overrides=DryRenderOverrides(
                bgm="https://example.com/bgm.mp3",
                title="Test Title",
            )
        )
        assert req.overrides.bgm == "https://example.com/bgm.mp3"
        assert req.overrides.title == "Test Title"

    def test_extra_fields_allowed(self):
        overrides = DryRenderOverrides(custom_field="value")
        assert overrides.custom_field == "value"

    def test_scene_override(self):
        req = DryRenderRequest(
            overrides=DryRenderOverrides(
                scenes=[SceneOverride(index=0, durationInFrames=120)]
            )
        )
        assert req.overrides.scenes[0].index == 0
        assert req.overrides.scenes[0].durationInFrames == 120


import copy

# Stub heavy dependencies so we can import main without installing everything
for _mod_name in [
    "anthropic",
    "redis", "redis.asyncio",
    "httpx",
    "minimax_python",
]:
    sys.modules.setdefault(_mod_name, MagicMock())

# Stub internal service modules that pull in heavy deps
for _mod_name in [
    "orchestrator.pipeline.gates",
    "orchestrator.pipeline.jobs",
    "orchestrator.pipeline.state",
    "orchestrator.services.r2",
    "orchestrator.services.render",
    "orchestrator.services.wavespeed",
    "orchestrator.services.agent",
    "orchestrator.line.bot",
    "orchestrator.line.webhook",
    "orchestrator.line.conversation",
    "orchestrator.stores.user",
]:
    sys.modules.setdefault(_mod_name, MagicMock())

from orchestrator.main import apply_overrides


class TestApplyOverrides:
    def test_no_overrides(self):
        ri = {"title": "Original", "bgm": "old.mp3"}
        result = apply_overrides(ri, None)
        assert result["title"] == "Original"

    def test_top_level_override(self):
        ri = {"title": "Original", "bgm": "old.mp3"}
        result = apply_overrides(ri, {"title": "New Title"})
        assert result["title"] == "New Title"
        assert result["bgm"] == "old.mp3"

    def test_scene_patch_by_index(self):
        ri = {
            "scenes": [
                {"type": "clip", "src": "a.mp4", "durationInFrames": 75},
                {"type": "map", "durationInFrames": 150},
            ]
        }
        result = apply_overrides(ri, {
            "scenes": [{"index": 0, "durationInFrames": 120}]
        })
        assert result["scenes"][0]["durationInFrames"] == 120
        assert result["scenes"][0]["src"] == "a.mp4"  # untouched
        assert result["scenes"][1]["durationInFrames"] == 150  # untouched

    def test_scene_index_out_of_range(self):
        ri = {"scenes": [{"type": "clip"}]}
        with pytest.raises(ValueError, match="index 5 out of range"):
            apply_overrides(ri, {"scenes": [{"index": 5}]})

    def test_does_not_mutate_override_input(self):
        ri = {"scenes": [{"type": "clip", "durationInFrames": 75}]}
        override_scenes = [{"index": 0, "durationInFrames": 120}]
        original_override = copy.deepcopy(override_scenes)
        apply_overrides(ri, {"scenes": override_scenes})
        assert override_scenes == original_override  # not mutated


# ── Endpoint tests ──

from unittest.mock import AsyncMock, patch

from orchestrator.models import JobState, JobStatus, AssetTask, AgentResult, PropertyInfo, SpaceInfo


def _make_state(**overrides) -> JobState:
    defaults = dict(
        job_id="test-job-123",
        status=JobStatus.rendering,
        raw_text="test property",
        line_user_id="U123",
        agent_result=AgentResult(
            property=PropertyInfo(address="台北市信義區"),
            title="測試物件",
            narration="test narration",
            spaces=[SpaceInfo(name="客廳", photo_count=1, photos=["https://example.com/photo.jpg"])],
        ),
        asset_tasks={"clip:客廳:0": AssetTask(status="completed", output_url="https://example.com/clip.mp4")},
    )
    defaults.update(overrides)
    return JobState(**defaults)


class TestDryRenderEndpoint:
    @pytest.mark.asyncio
    async def test_job_not_found(self):
        from orchestrator.main import app
        from httpx import AsyncClient, ASGITransport

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("orchestrator.main.store") as mock_store:
                mock_store.get = AsyncMock(return_value=None)
                resp = await client.post("/jobs/nonexistent/dry-render")
                assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_job_not_ready(self):
        from orchestrator.main import app
        from httpx import AsyncClient, ASGITransport

        state = _make_state(status=JobStatus.analyzing)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch("orchestrator.main.store") as mock_store:
                mock_store.get = AsyncMock(return_value=state)
                resp = await client.post("/jobs/test-job-123/dry-render")
                assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_successful_dry_render(self):
        from orchestrator.main import app
        from httpx import AsyncClient, ASGITransport

        state = _make_state()
        mock_render_input = {"title": "Test", "scenes": []}

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with (
                patch("orchestrator.main.store") as mock_store,
                patch("orchestrator.main._build_render_input", new_callable=AsyncMock) as mock_build,
                patch("orchestrator.main.render_service") as mock_render,
            ):
                mock_store.get = AsyncMock(return_value=state)
                mock_build.return_value = mock_render_input
                mock_render.submit = AsyncMock(return_value="render-server-job-id")
                mock_render.poll = AsyncMock(return_value={"outputUrl": "https://example.com/output.mp4"})

                resp = await client.post("/jobs/test-job-123/dry-render")
                assert resp.status_code == 200
                data = resp.json()
                assert data["render_job_id"] == "render-server-job-id"
                assert data["output_url"] == "https://example.com/output.mp4"

                # Verify poll was called with the ID returned by submit (not locally generated)
                mock_render.poll.assert_called_once_with("render-server-job-id")

    @pytest.mark.asyncio
    async def test_dry_render_with_overrides(self):
        from orchestrator.main import app
        from httpx import AsyncClient, ASGITransport

        state = _make_state()
        mock_render_input = {
            "title": "Original",
            "bgm": "old.mp3",
            "scenes": [{"type": "clip", "durationInFrames": 75}],
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with (
                patch("orchestrator.main.store") as mock_store,
                patch("orchestrator.main._build_render_input", new_callable=AsyncMock) as mock_build,
                patch("orchestrator.main.render_service") as mock_render,
            ):
                mock_store.get = AsyncMock(return_value=state)
                mock_build.return_value = mock_render_input
                mock_render.submit = AsyncMock(return_value="dry-123")
                mock_render.poll = AsyncMock(return_value={"outputUrl": "https://example.com/out.mp4"})

                resp = await client.post(
                    "/jobs/test-job-123/dry-render",
                    json={"overrides": {"title": "New Title"}},
                )
                assert resp.status_code == 200

                # Verify submit received overridden input
                submit_input = mock_render.submit.call_args[0][1]
                assert submit_input["title"] == "New Title"
                assert submit_input["bgm"] == "old.mp3"  # untouched

    @pytest.mark.asyncio
    async def test_render_timeout(self):
        from orchestrator.main import app
        from httpx import AsyncClient, ASGITransport

        state = _make_state()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with (
                patch("orchestrator.main.store") as mock_store,
                patch("orchestrator.main._build_render_input", new_callable=AsyncMock) as mock_build,
                patch("orchestrator.main.render_service") as mock_render,
            ):
                mock_store.get = AsyncMock(return_value=state)
                mock_build.return_value = {"title": "Test", "scenes": []}
                mock_render.submit = AsyncMock(return_value="dry-timeout")
                mock_render.poll = AsyncMock(side_effect=TimeoutError("timed out"))

                resp = await client.post("/jobs/test-job-123/dry-render")
                assert resp.status_code == 504
