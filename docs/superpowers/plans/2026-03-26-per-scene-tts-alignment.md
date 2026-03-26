# Per-Scene TTS Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace single-TTS narration with per-scene TTS calls so each section's subtitles naturally align to its scene, eliminating char-offset misalignment risk.

**Architecture:** Split narration text by section markers, call MiniMax TTS in parallel per section, calculate scene start times (mirroring Remotion's `calcTotalFrames`), then pad/concat audio segments with silence to align each section to its scene's start time. Remotion receives a single `narration.mp3` + aligned subtitles — zero frontend changes.

**Tech Stack:** Python 3.10+, pydub (audio manipulation), asyncio (parallel TTS), pytest (testing)

**Spec:** `docs/superpowers/specs/2026-03-26-per-scene-tts-alignment-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `orchestrator/services/audio_align.py` (create) | Core alignment logic: split markers, map sections→scenes, assemble audio |
| `orchestrator/tests/test_audio_align.py` (create) | Unit tests for audio_align |
| `orchestrator/pipeline/jobs.py` (modify) | Change `_task_tts()` to use per-scene TTS + alignment |
| `orchestrator/line/bot.py` (modify) | Change `send_gate_narration()` to show sectioned preview |
| `orchestrator/requirements.txt` (modify) | Add `pydub` |
| `agent/SKILL.md` (modify) | Update per-section character limits |

---

### Task 1: Add pydub dependency

**Files:**
- Modify: `orchestrator/requirements.txt`

- [ ] **Step 1: Add pydub to requirements.txt**

```
pydub>=0.25.1
```

Append after the last line in `orchestrator/requirements.txt`.

- [ ] **Step 2: Verify import works**

Run: `cd orchestrator && python -c "from pydub import AudioSegment; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add orchestrator/requirements.txt
git commit -m "chore: add pydub dependency for audio alignment"
```

---

### Task 2: Implement `split_by_markers()`

**Files:**
- Create: `orchestrator/services/audio_align.py`
- Create: `orchestrator/tests/test_audio_align.py`

- [ ] **Step 1: Write failing tests for split_by_markers**

Create `orchestrator/tests/test_audio_align.py`:

```python
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
        # Pause markers should be preserved (MiniMax handles them)
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_audio_align.py -v`
Expected: FAIL — `ImportError: cannot import name 'split_by_markers'`

- [ ] **Step 3: Implement split_by_markers**

Create `orchestrator/services/audio_align.py`:

```python
"""Audio alignment: per-scene TTS assembly with silence padding.

Splits narration by section markers, maps sections to Remotion scenes,
and assembles aligned audio with adjusted subtitles.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Matches section headers like [OPENING] or [客廳] on their own line
_MARKER_RE = re.compile(r"^\[(.+?)\]\s*$", re.MULTILINE)


def split_by_markers(narration_text: str) -> list[dict]:
    """Split narration text by [MARKER] lines.

    Returns list of {marker: str, text: str} in order.
    """
    matches = list(_MARKER_RE.finditer(narration_text))
    if not matches:
        return []

    sections: list[dict] = []
    for i, m in enumerate(matches):
        marker = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(narration_text)
        text = narration_text[start:end].strip()
        sections.append({"marker": marker, "text": text})

    return sections
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_audio_align.py::TestSplitByMarkers -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/audio_align.py orchestrator/tests/test_audio_align.py
git commit -m "feat: add split_by_markers for narration section parsing"
```

---

### Task 3: Implement `_calc_scene_start_frames()` and `map_sections_to_scenes()`

**Files:**
- Modify: `orchestrator/services/audio_align.py`
- Modify: `orchestrator/tests/test_audio_align.py`

Reference: `remotion/src/ReelEstateVideo.tsx:53-82` (`calcTotalFrames`)

- [ ] **Step 1: Write failing tests**

Append to `orchestrator/tests/test_audio_align.py`:

```python
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
        # 外觀→客廳: different label, fade overlap
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
        # OPENING available = until 客廳 starts
        # 客廳 start = (90 + 105 - 10) / 30 * 1000 = 6166.67ms (hook + exterior - fade)
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
        # 客廳 start = scene index 1's start_ms
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_audio_align.py -k "Calc or Map" -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement _calc_scene_start_frames and map_sections_to_scenes**

Append to `orchestrator/services/audio_align.py`:

```python
# ── Remotion frame constants ──
# Source of truth: remotion/src/ReelEstateVideo.tsx lines 15-19
FADE_FRAMES = 10
WIPE_FRAMES = 28
STAGING_FRAMES = 90
HOLD_FRAMES = 35
HOOK_FRAMES_PER_IMAGE = 30
FPS = 30


def _needs_fade_between(curr: dict, next_scene: dict) -> bool:
    """Same-space clip→clip has no fade; everything else fades."""
    if curr["type"] == "clip" and next_scene["type"] == "clip":
        if curr.get("label") == next_scene.get("label"):
            return False
    return True


def _calc_scene_start_frames(scenes: list[dict], hook_image_count: int) -> dict[int, float]:
    """Return {scene_index: start_ms}. Mirrors Remotion calcTotalFrames."""
    starts: dict[int, float] = {}
    cursor = hook_image_count * HOOK_FRAMES_PER_IMAGE

    for i, scene in enumerate(scenes):
        starts[i] = cursor / FPS * 1000

        cursor += scene["durationInFrames"]

        if scene["type"] == "clip" and scene.get("stagingImage"):
            cursor += HOLD_FRAMES
            cursor += STAGING_FRAMES
            cursor -= WIPE_FRAMES
            next_scene = scenes[i + 1] if i + 1 < len(scenes) else None
            if next_scene:
                cursor -= FADE_FRAMES
        elif i + 1 < len(scenes):
            next_scene = scenes[i + 1]
            if _needs_fade_between(scene, next_scene):
                cursor -= FADE_FRAMES

    return starts


def _calc_space_duration(scenes: list[dict], first_index: int, label: str) -> float:
    """Total available ms for all consecutive clips with same label (+ staging overhead)."""
    total_frames = 0
    for i in range(first_index, len(scenes)):
        scene = scenes[i]
        # Same-label clips are always consecutive in the scenes array
        if scene["type"] != "clip" or scene.get("label") != label:
            break
        total_frames += scene["durationInFrames"]
        if scene.get("stagingImage"):
            total_frames += HOLD_FRAMES + STAGING_FRAMES - WIPE_FRAMES
    return total_frames / FPS * 1000


def map_sections_to_scenes(
    sections: list[dict],
    scenes: list[dict],
    hook_image_count: int,
) -> dict[str, dict]:
    """Map section markers to {start_ms, available_ms}.

    Mapping rules:
    - OPENING: start_ms=0, available = hook frames + exterior clip
    - Space names: first clip of that space, available = all same-label clips
    - MAP/STATS/CTA: matched by scene type
    """
    result: dict[str, dict] = {}
    scene_starts = _calc_scene_start_frames(scenes, hook_image_count)

    # OPENING: from frame 0, available until the first non-exterior scene starts
    # Find the first non-exterior clip's start_ms as the OPENING boundary
    first_non_exterior_idx = next(
        (i for i, s in enumerate(scenes)
         if not (s["type"] == "clip" and s.get("label") == "外觀")),
        None,
    )
    if first_non_exterior_idx is not None:
        opening_available = scene_starts[first_non_exterior_idx]
    else:
        hook_ms = hook_image_count * HOOK_FRAMES_PER_IMAGE / FPS * 1000
        first_clip_ms = scenes[0]["durationInFrames"] / FPS * 1000 if scenes else 0
        opening_available = hook_ms + first_clip_ms
    result["OPENING"] = {
        "start_ms": 0,
        "available_ms": opening_available,
    }

    # Space clips + special scene types
    seen_labels: set[str] = set()
    for i, scene in enumerate(scenes):
        if scene["type"] == "clip":
            label = scene.get("label", "")
            if label == "外觀":
                continue  # exterior belongs to OPENING
            if label not in seen_labels:
                seen_labels.add(label)
                result[label] = {
                    "start_ms": scene_starts[i],
                    "available_ms": _calc_space_duration(scenes, i, label),
                }
        elif scene["type"] == "map":
            result["MAP"] = {
                "start_ms": scene_starts[i],
                "available_ms": scene["durationInFrames"] / FPS * 1000,
            }
        elif scene["type"] == "stats":
            result["STATS"] = {
                "start_ms": scene_starts[i],
                "available_ms": scene["durationInFrames"] / FPS * 1000,
            }
        elif scene["type"] == "cta":
            result["CTA"] = {
                "start_ms": scene_starts[i],
                "available_ms": scene["durationInFrames"] / FPS * 1000,
            }

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_audio_align.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/audio_align.py orchestrator/tests/test_audio_align.py
git commit -m "feat: add scene start time calculation mirroring Remotion calcTotalFrames"
```

---

### Task 4: Implement `assemble_audio()`

**Files:**
- Modify: `orchestrator/services/audio_align.py`
- Modify: `orchestrator/tests/test_audio_align.py`

- [ ] **Step 1: Write failing tests**

Append to `orchestrator/tests/test_audio_align.py`:

```python
from unittest.mock import patch
from pydub import AudioSegment
from orchestrator.services.audio_align import assemble_audio


def _make_audio_bytes(duration_ms: int) -> bytes:
    """Generate silent MP3 bytes of given duration."""
    seg = AudioSegment.silent(duration=duration_ms)
    buf = seg.export(format="mp3")
    return buf.read()


class TestAssembleAudio:
    def test_basic_assembly(self):
        section_results = [
            {"marker": "OPENING", "audio_bytes": _make_audio_bytes(2000), "subtitles": [
                {"text": "開場", "time_begin": 0, "time_end": 2000},
            ]},
            {"marker": "客廳", "audio_bytes": _make_audio_bytes(1500), "subtitles": [
                {"text": "客廳", "time_begin": 0, "time_end": 1500},
            ]},
        ]
        section_map = {
            "OPENING": {"start_ms": 0, "available_ms": 6500},
            "客廳": {"start_ms": 6500, "available_ms": 3500},
        }
        audio_bytes, subtitles = assemble_audio(section_results, section_map)
        assert isinstance(audio_bytes, bytes)
        assert len(subtitles) == 2
        # OPENING subtitle stays at 0
        assert subtitles[0]["time_begin"] == 0
        assert subtitles[0]["time_end"] == 2000
        # 客廳 subtitle offset by 6500
        assert subtitles[1]["time_begin"] == 6500
        assert subtitles[1]["time_end"] == 8000

    def test_overlap_warning(self):
        """When previous section overflows, gap < 0 should log warning."""
        section_results = [
            {"marker": "OPENING", "audio_bytes": _make_audio_bytes(7000), "subtitles": []},
            {"marker": "客廳", "audio_bytes": _make_audio_bytes(1000), "subtitles": []},
        ]
        section_map = {
            "OPENING": {"start_ms": 0, "available_ms": 6500},
            "客廳": {"start_ms": 6500, "available_ms": 3500},
        }
        with patch("orchestrator.services.audio_align.logger") as mock_logger:
            audio_bytes, subtitles = assemble_audio(section_results, section_map)
            # Should warn about overflow and overlap
            assert mock_logger.warning.call_count >= 1

    def test_empty_section_results(self):
        audio_bytes, subtitles = assemble_audio([], {})
        assert isinstance(audio_bytes, bytes)
        assert subtitles == []

    def test_unknown_marker_skipped(self):
        """Section with marker not in section_map should be skipped, not crash."""
        section_results = [
            {"marker": "OPENING", "audio_bytes": _make_audio_bytes(1000), "subtitles": []},
            {"marker": "浴室", "audio_bytes": _make_audio_bytes(1000), "subtitles": []},
        ]
        section_map = {
            "OPENING": {"start_ms": 0, "available_ms": 6500},
            # No 浴室 mapping
        }
        with patch("orchestrator.services.audio_align.logger") as mock_logger:
            audio_bytes, subtitles = assemble_audio(section_results, section_map)
            assert isinstance(audio_bytes, bytes)
            # Should warn about missing mapping
            assert any("浴室" in str(c) for c in mock_logger.warning.call_args_list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd orchestrator && python -m pytest tests/test_audio_align.py::TestAssembleAudio -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement assemble_audio**

Append to `orchestrator/services/audio_align.py`:

```python
from io import BytesIO
from pydub import AudioSegment


def assemble_audio(
    section_results: list[dict],
    section_map: dict[str, dict],
) -> tuple[bytes, list[dict]]:
    """Pad and concatenate per-section audio, adjusting subtitle timestamps.

    Args:
        section_results: [{marker, audio_bytes, subtitles}] in order
        section_map: {marker: {start_ms, available_ms}} from map_sections_to_scenes

    Returns:
        (final_mp3_bytes, aligned_subtitles)
    """
    if not section_results:
        seg = AudioSegment.silent(duration=100)
        buf = BytesIO()
        seg.export(buf, format="mp3")
        return buf.getvalue(), []

    final_audio = AudioSegment.empty()
    final_subtitles: list[dict] = []

    for section in section_results:
        mapping = section_map.get(section["marker"])
        if mapping is None:
            logger.warning("No scene mapping for section %s, skipping", section["marker"])
            continue
        target_start_ms = mapping["start_ms"]
        available_ms = mapping["available_ms"]

        # Pad silence to reach target position
        gap = target_start_ms - len(final_audio)
        if gap > 0:
            final_audio += AudioSegment.silent(duration=gap)
        elif gap < 0:
            logger.warning(
                "Audio overlap: section %s starts at %dms but previous audio ends at %dms (overlap=%dms)",
                section["marker"], target_start_ms, len(final_audio), -gap,
            )

        # Append section audio
        section_audio = AudioSegment.from_mp3(BytesIO(section["audio_bytes"]))
        if len(section_audio) > available_ms:
            logger.warning(
                "Section %s audio (%dms) exceeds available duration (%dms)",
                section["marker"], len(section_audio), available_ms,
            )
        final_audio += section_audio

        # Offset subtitles
        for sub in section["subtitles"]:
            final_subtitles.append({
                "text": sub["text"],
                "time_begin": sub["time_begin"] + target_start_ms,
                "time_end": sub["time_end"] + target_start_ms,
            })

    buf = BytesIO()
    final_audio.export(buf, format="mp3")
    return buf.getvalue(), final_subtitles
```

Note: Move `from io import BytesIO` and `from pydub import AudioSegment` to the top of the file, after the existing imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_audio_align.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/services/audio_align.py orchestrator/tests/test_audio_align.py
git commit -m "feat: add assemble_audio for per-scene audio padding and subtitle alignment"
```

---

### Task 5: Update `send_gate_narration()` for sectioned preview

**Files:**
- Modify: `orchestrator/line/bot.py:491-540`
- Modify: `orchestrator/tests/test_line_bot.py` (if gate narration tests exist)

- [ ] **Step 1: Write failing test**

Append to `orchestrator/tests/test_line_bot.py` (or create if needed):

```python
from orchestrator.line.bot import LineBot


class TestGateNarrationDisplay:
    def test_markers_converted_to_emoji_titles(self):
        """Verify markers are displayed as emoji section titles."""
        bot = LineBot()
        text = (
            "[OPENING]\n今天帶你來看\n\n"
            "[客廳]\n超大面落地窗\n\n"
            "[MAP]\n信義安和站旁邊\n\n"
            "[STATS]\n三十五坪\n\n"
            "[CTA]\n售價兩千九百八十萬\n"
        )
        display = bot._format_narration_preview(text)
        assert "🎬 開場" in display
        assert "🏠 客廳" in display
        assert "🗺️ 周邊" in display
        assert "📊 規格" in display
        assert "📞 聯繫" in display
        assert "[OPENING]" not in display
        assert "今天帶你來看" in display
```

    def test_reverse_mapping_emoji_to_markers(self):
        """Verify edited text with emojis can be converted back to markers."""
        bot = LineBot()
        edited = (
            "🎬 開場\n今天帶你來看\n\n"
            "🏠 客廳\n改過的客廳描述\n\n"
            "🗺️ 周邊\n信義安和站\n\n"
            "📊 規格\n三十五坪\n\n"
            "📞 聯繫\n售價兩千萬\n"
        )
        restored = bot._parse_edited_narration(edited)
        assert "[OPENING]" in restored
        assert "[客廳]" in restored
        assert "[MAP]" in restored
        assert "[STATS]" in restored
        assert "[CTA]" in restored
        assert "今天帶你來看" in restored
        assert "改過的客廳描述" in restored

- [ ] **Step 2: Run test to verify it fails**

Run: `cd orchestrator && python -m pytest tests/test_line_bot.py::TestGateNarrationDisplay -v`
Expected: FAIL — `AttributeError`

- [ ] **Step 3: Implement _format_narration_preview and update send_gate_narration**

In `orchestrator/line/bot.py`, add a `_format_narration_preview` method to `LineBot` and update `send_gate_narration`:

```python
# Add this mapping as a module constant near the top of bot.py
_MARKER_EMOJI_MAP = {
    "OPENING": "🎬 開場",
    "MAP": "🗺️ 周邊",
    "STATS": "📊 規格",
    "CTA": "📞 聯繫",
}

# Inside LineBot class:

def _format_narration_preview(self, narration_text: str) -> str:
    """Convert section markers to emoji titles for LINE preview."""
    import re
    lines = narration_text.split("\n")
    result: list[str] = []
    marker_re = re.compile(r"^\[(.+?)\]\s*$")

    for line in lines:
        m = marker_re.match(line.strip())
        if m:
            marker = m.group(1)
            display = _MARKER_EMOJI_MAP.get(marker, f"🏠 {marker}")
            result.append(f"\n{display}")
        else:
            # Strip pause markers like <#1.0#>
            cleaned = re.sub(r"<#[\d.]+#>", "", line)
            if cleaned.strip():
                result.append(cleaned)

    return "\n".join(result).strip()

# Reverse mapping: emoji titles back to [MARKER] for edited text
_EMOJI_TO_MARKER = {
    "🎬 開場": "[OPENING]",
    "🗺️ 周邊": "[MAP]",
    "📊 規格": "[STATS]",
    "📞 聯繫": "[CTA]",
}
# Pattern to match "🏠 空間名" (space names default to 🏠)
_SPACE_EMOJI_RE = re.compile(r"^🏠\s+(.+)$")

def _parse_edited_narration(self, edited_text: str) -> str:
    """Convert emoji-titled edited text back to [MARKER] format."""
    import re
    lines = edited_text.split("\n")
    result: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Check known emoji markers
        marker = _EMOJI_TO_MARKER.get(stripped)
        if marker:
            result.append(marker)
            continue
        # Check space emoji pattern (🏠 客廳 → [客廳])
        m = _SPACE_EMOJI_RE.match(stripped)
        if m:
            result.append(f"[{m.group(1)}]")
            continue
        result.append(line)

    return "\n".join(result)
```

Then update `send_gate_narration` to use it:

```python
async def send_gate_narration(
    self, chat_id: str, job_id: str, narration_text: str,
) -> None:
    """Send narration preview with approve/edit/reject buttons."""
    display_text = self._format_narration_preview(narration_text)
    # ... rest unchanged (actions, bubble, etc.)
```

Replace line 496-497 (`display_text = re.sub(...)`) with the single line above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd orchestrator && python -m pytest tests/test_line_bot.py::TestGateNarrationDisplay -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add orchestrator/line/bot.py orchestrator/tests/test_line_bot.py
git commit -m "feat: show sectioned narration preview with emoji titles in LINE gate"
```

---

### Task 6: Update `_task_tts()` to use per-scene TTS + alignment

**Files:**
- Modify: `orchestrator/pipeline/jobs.py:79-157`

- [ ] **Step 1: Import audio_align in jobs.py**

Add to imports at top of `orchestrator/pipeline/jobs.py`:

```python
from orchestrator.services.audio_align import split_by_markers, map_sections_to_scenes, assemble_audio
```

- [ ] **Step 2: Rewrite _task_tts**

Replace the `_task_tts` function (lines 79-157) with:

```python
async def _task_tts(
    state: JobState, redis, minimax: MiniMaxService, r2
) -> None:
    """Run narration gate + per-scene TTS + audio alignment."""
    job_id = state.job_id
    if not state.narration_enabled or not state.narration_text:
        return

    # Set gate pending
    gate_key = f"narration_gate:{job_id}"
    await redis.set(gate_key, "pending", ex=3600)

    # Notify user — push narration preview
    if line_bot and state.line_user_id:
        await line_bot.send_gate_narration(
            state.line_user_id, job_id, state.narration_text,
        )

    await store.update_narration(job_id, narration_gate_status="pending")

    # Wait for gate
    action, edited_text = await _narration_gate_poll(job_id, redis)

    if action == "rejected":
        await store.update_narration(
            job_id, narration_gate_status="rejected", narration_enabled=False,
        )
        return

    # Use edited text if provided
    final_text = edited_text if action == "edit" else state.narration_text
    await store.update_narration(
        job_id, narration_text=final_text, narration_gate_status="approved",
    )

    # Split narration into sections
    sections = split_by_markers(final_text)
    if not sections:
        logger.warning("No section markers found in narration, skipping TTS: job=%s", job_id)
        return

    # Per-section TTS (parallel)
    # Note: minimax.synthesize() already has built-in 1-retry (see minimax.py:56-68)
    # Filter out empty sections before TTS, insert silence for them later
    tts_results = await asyncio.gather(*[
        minimax.synthesize(section["text"])
        for section in sections
        if section["text"].strip()
    ], return_exceptions=True)

    # Re-align results with sections (empty sections get None)
    result_iter = iter(tts_results)
    aligned_results = [
        next(result_iter) if section["text"].strip() else None
        for section in sections
    ]

    # Build section_results, handling failures
    section_results: list[dict] = []
    for i, (section, result) in enumerate(zip(sections, aligned_results)):
        if isinstance(result, Exception) or result is None:
            logger.warning(
                "TTS failed for section %s, inserting silence: job=%s",
                section["marker"], job_id,
            )
            # Empty audio + no subtitles for failed section
            from pydub import AudioSegment
            from io import BytesIO
            silent = AudioSegment.silent(duration=100)
            buf = BytesIO()
            silent.export(buf, format="mp3")
            section_results.append({
                "marker": section["marker"],
                "audio_bytes": buf.getvalue(),
                "subtitles": [],
            })
        else:
            audio_bytes, subtitles = result
            section_results.append({
                "marker": section["marker"],
                "audio_bytes": audio_bytes,
                "subtitles": subtitles,
            })

    # Build scenes and compute mapping
    # Re-read state to get latest asset_tasks (scenes built from same logic as _build_render_input)
    fresh_state = await store.get(job_id)
    if fresh_state is None:
        logger.error("Job %s disappeared during TTS", job_id)
        return
    render_input = await _build_render_input(fresh_state)
    scenes = render_input["scenes"]

    # Count hook images (staging images from first 3 clip scenes)
    hook_image_count = min(
        sum(1 for s in scenes if s["type"] == "clip" and s.get("stagingImage")),
        3,
    )

    section_map = map_sections_to_scenes(sections, scenes, hook_image_count)
    audio_bytes, subtitles = assemble_audio(section_results, section_map)

    # Log duration (observability)
    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", tmp_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            duration = float(result.stdout.strip())
            logger.info("TTS aligned audio duration: %.1fs (job=%s)", duration, job_id)
    except Exception:
        pass  # observability only

    # Upload audio to R2
    r2_key = f"audio/{job_id}/narration.mp3"
    narration_url = await r2.upload_bytes(audio_bytes, r2_key, "audio/mpeg")

    # Upload subtitles to R2
    subtitles_url = None
    if subtitles:
        import json as _json
        sub_key = f"audio/{job_id}/subtitles.json"
        subtitles_url = await r2.upload_bytes(
            _json.dumps(subtitles).encode(), sub_key, "application/json"
        )

    await store.update_narration(
        job_id,
        narration_url=narration_url,
        narration_subtitles=subtitles,
        narration_subtitles_url=subtitles_url,
    )
```

- [ ] **Step 3: Fix hook_image_count calculation**

The hook image extraction in Remotion uses `extractHookImages` which picks staging images. Check `remotion/src/ReelEstateVideo.tsx` for the exact logic. The Python equivalent:

```python
# In _task_tts, the hook_image_count should match Remotion's extractHookImages.
# Remotion picks the first MAX_HOOK_IMAGES (3) staging images from scenes.
hook_image_count = min(
    sum(1 for s in scenes if s["type"] == "clip" and s.get("stagingImage")),
    3,
)
```

Verify this matches `remotion/src/ReelEstateVideo.tsx`'s `extractHookImages`. If it extracts all staging images limited to 3, the above is correct.

- [ ] **Step 4: Run existing tests to check for regressions**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All existing tests PASS (TTS mocks may need updating if they test `_task_tts` directly)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/pipeline/jobs.py
git commit -m "feat: replace single TTS with per-scene TTS + audio alignment"
```

---

### Task 7: Integration verification

**Files:**
- No new files — verify the full pipeline works

- [ ] **Step 1: Run full test suite**

Run: `cd orchestrator && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Verify imports are clean**

Run: `cd orchestrator && python -c "from orchestrator.services.audio_align import split_by_markers, map_sections_to_scenes, assemble_audio; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit any fixes**

If any tests needed updating, commit:

```bash
git add -A
git commit -m "fix: update tests for per-scene TTS integration"
```

---

### Task 8: Update agent/SKILL.md character limits

**Files:**
- Modify: `agent/SKILL.md`

- [ ] **Step 1: Find the character limit section in agent/SKILL.md**

Search for existing character limits or narration guidelines.

- [ ] **Step 2: Update character limits per section**

Add or update the per-section character limits:

```markdown
### 旁白字數上限（每段 section）

| Section | 場景時長 | 字數上限 |
|---------|---------|---------|
| OPENING（開場 + 外觀）| ~6.2s | 29 字 |
| 一般空間 clip | 3.5s | 16 字 |
| 小空間 clip（is_small_space） | 2.8s | 13 字 |
| MAP（周邊） | 10s | 48 字 |
| STATS（規格） | 7s | 33 字 |
| CTA（聯繫） | 5s | 24 字 |

> 計算基準：1.2x 語速 ≈ 4.8 字/秒。超過上限會導致旁白與畫面錯位。
```

- [ ] **Step 3: Commit**

```bash
git add agent/SKILL.md
git commit -m "docs: update agent narration character limits for per-scene TTS"
```

---

## Task Dependency Graph

```
Task 1 (pydub) ──────────────────────────────────────┐
Task 2 (split_by_markers) ──→ Task 3 (scene mapping) ─→ Task 4 (assemble_audio) ──→ Task 6 (_task_tts) ──→ Task 7 (integration)
Task 5 (gate preview + reverse mapping) ───────────────→ Task 6 (_task_tts) ──→ Task 7 (integration)
Task 8 (agent SKILL.md) ── independent, can run anytime
```

Tasks 1, 2, 5, 8 can run in parallel. Tasks 3, 4 are sequential. Task 6 depends on 1-5. Task 7 is final verification.
