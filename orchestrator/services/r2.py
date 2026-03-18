from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx

from orchestrator.config import settings

CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".flac": "audio/flac",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


def _guess_content_type(path_or_url: str) -> str:
    parsed = urlparse(path_or_url)
    ext = os.path.splitext(parsed.path)[1].lower()
    return CONTENT_TYPES.get(ext, "application/octet-stream")


class R2Service:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(timeout=120)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "R2Service not started"
        return self._client

    async def upload_bytes(
        self, data: bytes, r2_key: str, content_type: str | None = None
    ) -> str:
        ct = content_type or _guess_content_type(r2_key)
        resp = await self.client.put(
            f"{settings.r2_proxy_url}/{r2_key}",
            content=data,
            headers={
                "X-Upload-Token": settings.r2_upload_token,
                "Content-Type": ct,
            },
        )
        resp.raise_for_status()
        return resp.json()["url"]

    async def upload_from_url(self, source_url: str, r2_key: str) -> str:
        ct = _guess_content_type(source_url)
        async with httpx.AsyncClient(timeout=120) as dl:
            dl_resp = await dl.get(source_url)
            dl_resp.raise_for_status()
        return await self.upload_bytes(dl_resp.content, r2_key, content_type=ct)


r2_service = R2Service()
