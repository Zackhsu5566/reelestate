"""Audio alignment: per-scene TTS assembly with silence padding.

Splits narration by section markers, maps sections to Remotion scenes,
and assembles aligned audio with adjusted subtitles.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO

from pydub import AudioSegment

logger = logging.getLogger(__name__)

_MARKER_RE = re.compile(r"^\[(.+?)\]\s*$", re.MULTILINE)

# ── Remotion frame constants ──
# Source of truth: remotion/src/ReelEstateVideo.tsx lines 15-19
FADE_FRAMES = 10
WIPE_FRAMES = 28
STAGING_FRAMES = 90
HOLD_FRAMES = 35
HOOK_FRAMES_PER_IMAGE = 30
MAX_HOOK_IMAGES = 3
FPS = 30


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


# ---------------------------------------------------------------------------
# Scene start time calculation (mirrors Remotion calcTotalFrames)
# ---------------------------------------------------------------------------


def _needs_fade_between(curr: dict, next_scene: dict) -> bool:
    """Same-space clip->clip has no fade; everything else fades."""
    if curr["type"] == "clip" and next_scene["type"] == "clip":
        if curr.get("label") == next_scene.get("label"):
            return False
    return True


def _calc_scene_start_frames(
    scenes: list[dict], hook_image_count: int
) -> dict[int, float]:
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


def _calc_space_duration(
    scenes: list[dict], first_index: int, label: str
) -> float:
    """Total available ms for all consecutive clips with same label (+ staging overhead)."""
    total_frames = 0
    for i in range(first_index, len(scenes)):
        scene = scenes[i]
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
    """Map section markers to {start_ms, available_ms}."""
    result: dict[str, dict] = {}
    scene_starts = _calc_scene_start_frames(scenes, hook_image_count)

    # OPENING: from frame 0, available until the first non-exterior scene starts
    first_non_exterior_idx = next(
        (
            i
            for i, s in enumerate(scenes)
            if not (s["type"] == "clip" and s.get("label") == "外觀")
        ),
        None,
    )
    if first_non_exterior_idx is not None:
        opening_available = scene_starts[first_non_exterior_idx]
    else:
        hook_ms = hook_image_count * HOOK_FRAMES_PER_IMAGE / FPS * 1000
        first_clip_ms = (
            scenes[0]["durationInFrames"] / FPS * 1000 if scenes else 0
        )
        opening_available = hook_ms + first_clip_ms
    result["OPENING"] = {"start_ms": 0, "available_ms": opening_available}

    # Space clips + special scene types
    seen_labels: set[str] = set()
    for i, scene in enumerate(scenes):
        if scene["type"] == "clip":
            label = scene.get("label", "")
            if label == "外觀":
                continue
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


def extend_scenes_for_audio(
    scenes: list[dict],
    section_results: list[dict],
    section_map: dict[str, dict],
) -> bool:
    """Extend scene durationInFrames if TTS audio exceeds available duration.

    Mutates scenes in-place. Returns True if any scene was extended.
    """
    import math

    # Build marker → scene index lookup
    marker_to_scene: dict[str, int] = {}
    for i, scene in enumerate(scenes):
        if scene["type"] == "map":
            marker_to_scene["MAP"] = i
        elif scene["type"] == "stats":
            marker_to_scene["STATS"] = i
        elif scene["type"] == "cta":
            marker_to_scene["CTA"] = i
        elif scene["type"] == "clip" and scene.get("label") and scene["label"] != "外觀":
            if scene["label"] not in marker_to_scene:
                marker_to_scene[scene["label"]] = i

    changed = False
    for section in section_results:
        marker = section["marker"]
        mapping = section_map.get(marker)
        if mapping is None:
            continue
        audio = AudioSegment.from_mp3(BytesIO(section["audio_bytes"]))
        audio_ms = len(audio)
        available_ms = mapping["available_ms"]
        if audio_ms <= available_ms:
            continue

        scene_idx = marker_to_scene.get(marker)
        if scene_idx is None:
            continue

        extra_ms = audio_ms - available_ms
        extra_frames = math.ceil(extra_ms / 1000 * FPS)
        scenes[scene_idx]["durationInFrames"] += extra_frames
        logger.info(
            "Extended scene %s by %d frames (+%.1fs) to fit narration",
            marker, extra_frames, extra_ms / 1000,
        )
        changed = True

    return changed


# ---------------------------------------------------------------------------
# Audio assembly: pad silence between sections and concatenate
# ---------------------------------------------------------------------------


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

        gap = target_start_ms - len(final_audio)
        if gap > 0:
            final_audio += AudioSegment.silent(duration=gap)
        elif gap < 0:
            logger.warning(
                "Audio overlap: section %s starts at %dms but previous audio ends at %dms (overlap=%dms)",
                section["marker"], target_start_ms, len(final_audio), -gap,
            )

        section_audio = AudioSegment.from_mp3(BytesIO(section["audio_bytes"]))
        if len(section_audio) > available_ms:
            logger.warning(
                "Section %s audio (%dms) exceeds available duration (%dms)",
                section["marker"], len(section_audio), available_ms,
            )
        final_audio += section_audio

        # Skip subtitles for STATS and CTA (text already shown on screen)
        if section["marker"] not in ("STATS", "CTA"):
            for sub in section["subtitles"]:
                final_subtitles.append({
                    "text": sub["text"],
                    "time_begin": sub["time_begin"] + target_start_ms,
                    "time_end": sub["time_end"] + target_start_ms,
                })

    buf = BytesIO()
    final_audio.export(buf, format="mp3")
    return buf.getvalue(), final_subtitles
