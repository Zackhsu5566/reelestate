"""Tests for dry-render endpoint."""
import sys
from types import ModuleType
from unittest.mock import MagicMock

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
