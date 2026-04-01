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
