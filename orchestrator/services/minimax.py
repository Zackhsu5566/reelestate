"""MiniMax Text-to-Speech service wrapper (sync t2a_v2 API with subtitles)."""

from __future__ import annotations

import asyncio
import logging
import re

import aiohttp
import opencc

logger = logging.getLogger(__name__)

# Traditional → Simplified Chinese converter (MiniMax TTS trained on Simplified)
_t2s = opencc.OpenCC("t2s")
_s2t = opencc.OpenCC("s2t")

# Limit parallel TTS submissions at module level so all instances share the cap
_tts_semaphore = asyncio.Semaphore(5)

# Matches section headers like [OPENING] or [客廳] on their own line
_SECTION_MARKER_RE = re.compile(r"^\[.+?\]\s*$", re.MULTILINE)

_BASE_URL = "https://api.minimaxi.chat/v1"


class MiniMaxService:
    def __init__(
        self,
        api_key: str,
        group_id: str,
        poll_interval: float = 3.0,
        poll_timeout: float = 300.0,
    ) -> None:
        self.api_key = api_key
        self.group_id = group_id
        self.poll_interval = poll_interval
        self.poll_timeout = poll_timeout
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        return self._session

    def _strip_markers(self, text: str) -> str:
        """Remove [SECTION_NAME] markers; preserve pause markers like <#1.0#>."""
        return _SECTION_MARKER_RE.sub("", text).strip()

    async def synthesize(self, narration_text: str) -> tuple[bytes, list[dict]] | None:
        """Full TTS pipeline with 1 retry. Returns (audio_bytes, subtitles) or None."""
        async with _tts_semaphore:
            for attempt in range(2):
                try:
                    result = await self._synthesize_inner(narration_text)
                    if result is not None:
                        return result
                    if attempt == 0:
                        logger.warning("TTS attempt 1 failed, retrying in 5s...")
                        await asyncio.sleep(5)
                except Exception:
                    logger.exception("TTS synthesis failed (attempt %d)", attempt + 1)
                    if attempt == 0:
                        await asyncio.sleep(5)
            return None

    async def _synthesize_inner(
        self, narration_text: str
    ) -> tuple[bytes, list[dict]] | None:
        text = self._strip_markers(narration_text)
        text = _t2s.convert(text)
        session = await self._get_session()

        url = f"{_BASE_URL}/t2a_v2?GroupId={self.group_id}"
        payload = {
            "model": "speech-2.8-hd",
            "text": text,
            "voice_setting": {
                "voice_id": "Chinese_casual_guide_vv2",
                "speed": 1.0,
                "language_boost": "Chinese",
            },
            "audio_setting": {
                "format": "mp3",
                "sample_rate": 32000,
            },
            "subtitle_enable": True,
        }

        timeout = aiohttp.ClientTimeout(total=self.poll_timeout)

        try:
            resp = await session.post(url, json=payload, timeout=timeout)
            if resp.status != 200:
                body = await resp.text()
                logger.warning(
                    "TTS sync request failed: status=%d body=%s",
                    resp.status,
                    body[:200],
                )
                return None

            data = await resp.json()
            base_resp = data.get("base_resp", {})
            if base_resp.get("status_code", -1) != 0:
                logger.warning(
                    "TTS sync API error: %s",
                    base_resp.get("status_msg", "unknown"),
                )
                return None

            audio_hex = data.get("data", {}).get("audio")
            subtitle_url = data.get("data", {}).get("subtitle_file")

            if not audio_hex:
                logger.warning("TTS sync response missing audio data")
                return None

            audio_bytes = bytes.fromhex(audio_hex)

            # Fetch subtitle JSON
            subtitles: list[dict] = []
            if subtitle_url:
                try:
                    sub_resp = await session.get(subtitle_url, timeout=timeout)
                    if sub_resp.status == 200:
                        subtitles = await sub_resp.json(content_type=None)
                    else:
                        logger.warning(
                            "TTS subtitle fetch failed: status=%d", sub_resp.status
                        )
                except Exception:
                    logger.exception("TTS subtitle fetch error")

            # Convert subtitle text back to Traditional Chinese
            for sub in subtitles:
                if "text" in sub:
                    sub["text"] = _s2t.convert(sub["text"])

            return (audio_bytes, subtitles)

        except Exception:
            logger.exception("TTS sync request error")
            return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
