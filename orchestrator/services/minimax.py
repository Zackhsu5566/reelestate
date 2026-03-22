"""MiniMax Text-to-Speech service wrapper (async, t2a_async_v2 API)."""

from __future__ import annotations

import asyncio
import logging
import re
import time

import aiohttp

logger = logging.getLogger(__name__)

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
        poll_timeout: float = 120.0,
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

    async def synthesize(self, narration_text: str) -> bytes | None:
        """Full TTS pipeline. Returns audio bytes or None on any failure."""
        async with _tts_semaphore:
            try:
                return await self._synthesize_inner(narration_text)
            except Exception:
                logger.exception("TTS synthesis failed")
                return None

    async def _synthesize_inner(self, narration_text: str) -> bytes | None:
        text = self._strip_markers(narration_text)
        session = await self._get_session()

        task_id = await self._create_task(session, text)
        if not task_id:
            return None

        audio_file_id = await self._poll_task(session, task_id)
        if not audio_file_id:
            return None

        return await self._download_audio(session, audio_file_id)

    async def _create_task(
        self, session: aiohttp.ClientSession, text: str
    ) -> str | None:
        url = f"{_BASE_URL}/t2a_async_v2?GroupId={self.group_id}"
        payload = {
            "model": "speech-2.8-hd",
            "text": text,
            "voice_setting": {
                "voice_id": "Chinese (Mandarin)_Male_Announcer",
                "speed": 1.0,
                "language_boost": "Chinese",
            },
            "audio_setting": {
                "format": "mp3",
                "sample_rate": 32000,
            },
        }
        try:
            resp = await session.post(url, json=payload)
            if resp.status == 200:
                data = await resp.json()
                task_id = data.get("task_id")
                if not task_id:
                    logger.warning("TTS create task: no task_id in response: %s", data)
                return task_id
            body = await resp.text()
            logger.warning("TTS create task failed: status=%d body=%s", resp.status, body[:200])
        except Exception:
            logger.exception("TTS create task error")
        return None

    async def _poll_task(
        self, session: aiohttp.ClientSession, task_id: str
    ) -> str | None:
        url = f"{_BASE_URL}/query/t2a_async_query_v2?task_id={task_id}"
        deadline = time.monotonic() + self.poll_timeout
        while time.monotonic() < deadline:
            try:
                resp = await session.get(url)
                if resp.status == 200:
                    data = await resp.json()
                    status = data.get("status")
                    if status == "Success":
                        return data.get("file_id")
                    if status == "Failed":
                        logger.warning("TTS task failed: %s", data)
                        return None
            except Exception:
                logger.exception("TTS poll error")
            await asyncio.sleep(self.poll_interval)
        logger.warning("TTS poll timeout after %.0fs", self.poll_timeout)
        return None

    async def _download_audio(
        self, session: aiohttp.ClientSession, file_id: str
    ) -> bytes | None:
        url = f"{_BASE_URL}/files/retrieve_content?file_id={file_id}"
        try:
            resp = await session.get(url)
            if resp.status == 200:
                data = await resp.read()
                if data:
                    return data
                logger.warning("TTS download: empty audio")
        except Exception:
            logger.exception("TTS download error")
        return None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
