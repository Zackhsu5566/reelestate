"""WaveSpeed API wrapper: Kling video, nano-banana-2 staging."""

from __future__ import annotations

import asyncio
import time

import httpx

from orchestrator.config import settings

# Model paths
MODEL_KLING = "kwaivgi/kling-v1.6-i2v-standard"
MODEL_STAGING = "google/nano-banana-2/edit"

# Negative prompt（shared across all Kling submissions）
NEGATIVE_PROMPT = (
    "Human, person, people, pedestrian, crowd, hand, finger, shadow of person, "
    "handheld shake, camera wobble, vibration, jitter, motion blur, sudden movement, "
    "fast motion, jerky, shaky cam, distortion, warping, morphing, new objects appearing, "
    "mirror reflection changes, blurry, low quality, unstable frame"
)

# Camera movement prompts
PROMPT_PUSH_IN = (
    "Shot on a professional camera dolly with stabilizer. Ultra smooth gliding motion. "
    "Cinematic dolly in, camera glides slowly forward toward the center of the room. "
    "Steady movement. Empty interior, no people."
)
PROMPT_ROTATE = (
    "Shot on a professional camera dolly with stabilizer. Ultra smooth gliding motion. "
    "Slow smooth horizontal pan from left to right. Camera stays in place, rotating gently. "
    "Empty room, real estate showcase style."
)
PROMPT_TRUCK_LEFT = (
    "Shot on a professional camera dolly with stabilizer. Ultra smooth gliding motion. "
    "Camera glides slowly to the left, parallel to the wall. Steady sliding motion. "
    "Keep all objects stable and consistent. Empty space, no people."
)
PROMPT_TRUCK_RIGHT = (
    "Shot on a professional camera dolly with stabilizer. Ultra smooth gliding motion. "
    "Camera glides slowly to the right, parallel to the wall. Steady sliding motion. "
    "Keep all objects stable and consistent. Empty space, no people."
)
PROMPT_PEDESTAL_UP = (
    "Shot on a professional camera dolly with stabilizer. Ultra smooth gliding motion. "
    "Camera rises slowly from a low angle upward. Smooth vertical lift. "
    "Interior stays consistent. Empty room, no people."
)
PROMPT_DRONE_UP = (
    "Shot on a professional camera dolly with stabilizer. Ultra smooth gliding motion. "
    "Cinematic aerial view rising slowly upward, revealing the surrounding area from above. "
    "Smooth vertical ascent. Stable frame. Empty scene, no people."
)


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
            {
                "image": image_url,
                "duration": 5,
                "prompt": prompt,
                "negative_prompt": NEGATIVE_PROMPT,
                "guidance_scale": 0.75,
            },
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
