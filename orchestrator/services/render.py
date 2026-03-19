"""VPS Remotion Render Server wrapper."""

from __future__ import annotations

import asyncio
import time

import httpx

from orchestrator.config import settings


class RenderService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={"Authorization": f"Bearer {settings.render_token}"},
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "RenderService not started"
        return self._client

    async def submit(self, job_id: str, render_input: dict) -> str:
        """Submit render job, return remotion job_id."""
        resp = await self.client.post(
            f"{settings.render_url}/render",
            json={"jobId": job_id, "input": render_input},
        )
        resp.raise_for_status()
        return resp.json()["jobId"]

    async def poll(self, job_id: str) -> dict:
        """Poll until render complete, return result dict with outputUrl and optional thumbnailUrl."""
        start = time.monotonic()
        while True:
            resp = await self.client.get(f"{settings.render_url}/render/{job_id}")
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")

            if status == "completed":
                return {
                    "outputUrl": data["outputUrl"],
                    "thumbnailUrl": data.get("thumbnailUrl"),
                }
            if status == "failed":
                raise RuntimeError(
                    f"Render {job_id} failed: {data.get('error')}"
                )

            if time.monotonic() - start > settings.render_poll_timeout:
                raise TimeoutError(f"Render {job_id} timed out")

            await asyncio.sleep(settings.render_poll_interval)

    async def render(self, job_id: str, render_input: dict) -> dict:
        """Submit + poll, return result dict."""
        rid = await self.submit(job_id, render_input)
        return await self.poll(rid)

render_service = RenderService()
