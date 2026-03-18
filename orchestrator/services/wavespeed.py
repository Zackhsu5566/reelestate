"""WaveSpeed API wrapper: Kling video, nano-banana-2 staging."""

from __future__ import annotations

import asyncio
import time

import httpx

from orchestrator.config import settings

# Model paths
MODEL_KLING = "kwaivgi/kling-v1.6-i2v-standard"
MODEL_STAGING = "google/nano-banana-2/edit"

# Prompt constants
PROMPT_DRONE_UP = "Cinematic drone shot rising vertically high above the space, revealing more of the vast surroundings."
PROMPT_ROTATE = "Slow horizontal camera pan from left to right across the room"


MAX_CONCURRENT_SUBMITS = 3  # Limit parallel WaveSpeed API submits to avoid 429


class WaveSpeedService:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_SUBMITS)

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=30,
            headers={"Authorization": f"Bearer {settings.wavespeed_api_key}"},
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "WaveSpeedService not started"
        return self._client

    # ── Submit + Poll (generic) ──

    async def submit(self, model: str, payload: dict) -> str:
        """Submit job, return prediction_id. Respects concurrency limit."""
        async with self._semaphore:
            url = f"{settings.wavespeed_base_url}/{model}"
            resp = await self.client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"WaveSpeed {model} submit failed ({resp.status_code}): {resp.text}")
            return resp.json()["data"]["id"]

    async def poll(self, prediction_id: str) -> str:
        """Poll until completed, return output URL."""
        url = f"{settings.wavespeed_base_url}/predictions/{prediction_id}/result"
        start = time.monotonic()
        while True:
            resp = await self.client.get(url)
            resp.raise_for_status()
            data = resp.json()["data"]
            status = data.get("status")

            if status == "completed":
                return data["outputs"][0]
            if status in ("failed", "canceled"):
                raise RuntimeError(
                    f"WaveSpeed {prediction_id} {status}: {data.get('error')}"
                )

            if time.monotonic() - start > settings.wavespeed_poll_timeout:
                raise TimeoutError(f"WaveSpeed {prediction_id} timed out")

            await asyncio.sleep(settings.wavespeed_poll_interval)

    # ── High-level methods ──

    async def kling_video(
        self,
        image_url: str,
        prompt: str,
        existing_id: str | None = None,
    ) -> str:
        """Generate video from image+prompt via Kling. Returns output URL."""
        if existing_id:
            return await self.poll(existing_id)

        pid = await self.kling_submit(image_url, prompt)
        return await self.poll(pid)

    async def kling_submit(self, image_url: str, prompt: str) -> str:
        """Submit Kling video, return prediction_id."""
        return await self.submit(
            MODEL_KLING,
            {"image": image_url, "duration": 5, "prompt": prompt, "guidance_scale": 0.3},
        )

    async def staging(
        self,
        image_url: str,
        prompt: str,
        existing_id: str | None = None,
    ) -> str:
        """Generate virtual staging via nano-banana-2. Returns output URL."""
        if existing_id:
            return await self.poll(existing_id)

        pid = await self.submit(
            MODEL_STAGING,
            {"images": [image_url], "prompt": prompt},
        )
        return await self.poll(pid)

    async def staging_submit(self, image_url: str, prompt: str) -> str:
        """Submit staging, return prediction_id."""
        return await self.submit(
            MODEL_STAGING,
            {"images": [image_url], "prompt": prompt},
        )


wavespeed = WaveSpeedService()
