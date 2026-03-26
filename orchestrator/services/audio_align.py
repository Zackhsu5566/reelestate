"""Audio alignment: per-scene TTS assembly with silence padding.

Splits narration by section markers, maps sections to Remotion scenes,
and assembles aligned audio with adjusted subtitles.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

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
