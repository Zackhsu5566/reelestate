"""Tests for orchestrator.services.audio_align."""

import pytest

from orchestrator.services.audio_align import split_by_markers


class TestSplitByMarkers:
    def test_standard_narration(self):
        text = (
            "[OPENING]\n"
            "今天帶你來看這間\n"
            "\n"
            "[客廳]\n"
            "一進門就是超大面落地窗\n"
            "\n"
            "[MAP]\n"
            "位置就在信義安和站旁邊\n"
            "\n"
            "[STATS]\n"
            "整屋三十五坪\n"
            "\n"
            "[CTA]\n"
            "售價兩千九百八十萬\n"
        )
        sections = split_by_markers(text)
        assert len(sections) == 5
        assert sections[0]["marker"] == "OPENING"
        assert "今天帶你來看這間" in sections[0]["text"]
        assert sections[1]["marker"] == "客廳"
        assert sections[3]["marker"] == "STATS"
        assert sections[4]["marker"] == "CTA"

    def test_multiple_spaces(self):
        text = (
            "[OPENING]\n開場白\n\n"
            "[客廳]\n客廳描述\n\n"
            "[主臥]\n主臥描述\n\n"
            "[MAP]\n地圖\n\n"
            "[STATS]\n規格\n\n"
            "[CTA]\n聯繫\n"
        )
        sections = split_by_markers(text)
        assert len(sections) == 6
        assert sections[2]["marker"] == "主臥"

    def test_strips_pause_markers(self):
        text = "[OPENING]\n今天<#1.0#>帶你來看\n"
        sections = split_by_markers(text)
        assert "<#1.0#>" in sections[0]["text"]

    def test_empty_section(self):
        text = "[OPENING]\n\n[MAP]\n地圖\n"
        sections = split_by_markers(text)
        assert len(sections) == 2
        assert sections[0]["marker"] == "OPENING"
        assert sections[0]["text"].strip() == ""

    def test_no_markers(self):
        text = "一段沒有 marker 的文字"
        sections = split_by_markers(text)
        assert len(sections) == 0


from orchestrator.services.audio_align import map_sections_to_scenes, _calc_scene_start_frames


class TestCalcSceneStartFrames:
    """Cross-validate with Remotion calcTotalFrames logic."""

    def test_simple_clips_no_staging(self):
        scenes = [
            {"type": "clip", "label": "外觀", "durationInFrames": 105},
            {"type": "clip", "label": "客廳", "durationInFrames": 105},
            {"type": "map", "durationInFrames": 300},
            {"type": "stats", "durationInFrames": 210},
            {"type": "cta", "durationInFrames": 150},
        ]
        starts = _calc_scene_start_frames(scenes, hook_image_count=3)
        # Hook = 3 * 30 = 90 frames
        assert starts[0] == 90 / 30 * 1000  # 外觀: 3000ms
        # 外觀→客廳: different label, fade overlap (FADE_FRAMES=10)
        assert starts[1] == (90 + 105 - 10) / 30 * 1000  # 6166.67ms
        # 客廳→map: fade overlap
        assert starts[2] == (90 + 105 - 10 + 105 - 10) / 30 * 1000

    def test_clip_with_staging(self):
        scenes = [
            {"type": "clip", "label": "外觀", "durationInFrames": 105},
            {"type": "clip", "label": "客廳", "durationInFrames": 105, "stagingImage": "http://img"},
            {"type": "map", "durationInFrames": 300},
        ]
        starts = _calc_scene_start_frames(scenes, hook_image_count=3)
        # 外觀→客廳: different label, fade
        # 客廳 has staging: +HOLD(35) +STAGING(90) -WIPE(28) -FADE(10)
        cursor_after_exterior = 90 + 105 - 10  # 185
        cursor_after_living = 185 + 105 + 35 + 90 - 28 - 10  # 377
        assert starts[2] == pytest.approx(377 / 30 * 1000, abs=1)

    def test_same_space_no_fade(self):
        scenes = [
            {"type": "clip", "label": "客廳", "durationInFrames": 105},
            {"type": "clip", "label": "客廳", "durationInFrames": 105},
            {"type": "map", "durationInFrames": 300},
        ]
        starts = _calc_scene_start_frames(scenes, hook_image_count=3)
        # Same label → no fade between clips
        assert starts[1] == (90 + 105) / 30 * 1000  # no fade subtracted


class TestMapSectionsToScenes:
    def test_opening_available_until_first_space(self):
        sections = [{"marker": "OPENING", "text": "..."}]
        scenes = [
            {"type": "clip", "label": "外觀", "durationInFrames": 105},
            {"type": "clip", "label": "客廳", "durationInFrames": 105},
        ]
        result = map_sections_to_scenes(sections, scenes, hook_image_count=3)
        assert result["OPENING"]["start_ms"] == 0
        # OPENING available = until 客廳 starts (accounts for fade overlap)
        starts = _calc_scene_start_frames(scenes, hook_image_count=3)
        assert result["OPENING"]["available_ms"] == starts[1]

    def test_space_maps_to_first_clip(self):
        sections = [
            {"marker": "OPENING", "text": "..."},
            {"marker": "客廳", "text": "..."},
        ]
        scenes = [
            {"type": "clip", "label": "外觀", "durationInFrames": 105},
            {"type": "clip", "label": "客廳", "durationInFrames": 105},
            {"type": "clip", "label": "客廳", "durationInFrames": 105},
            {"type": "map", "durationInFrames": 300},
        ]
        result = map_sections_to_scenes(sections, scenes, hook_image_count=3)
        assert "客廳" in result
        starts = _calc_scene_start_frames(scenes, hook_image_count=3)
        assert result["客廳"]["start_ms"] == starts[1]
        # available = 2 clips * 105 frames = 210 frames
        assert result["客廳"]["available_ms"] == 210 / 30 * 1000

    def test_map_stats_cta(self):
        scenes = [
            {"type": "clip", "label": "外觀", "durationInFrames": 105},
            {"type": "map", "durationInFrames": 300},
            {"type": "stats", "durationInFrames": 210},
            {"type": "cta", "durationInFrames": 150},
        ]
        sections = [
            {"marker": "OPENING", "text": "..."},
            {"marker": "MAP", "text": "..."},
            {"marker": "STATS", "text": "..."},
            {"marker": "CTA", "text": "..."},
        ]
        result = map_sections_to_scenes(sections, scenes, hook_image_count=3)
        assert result["MAP"]["available_ms"] == 300 / 30 * 1000
        assert result["STATS"]["available_ms"] == 210 / 30 * 1000
        assert result["CTA"]["available_ms"] == 150 / 30 * 1000
