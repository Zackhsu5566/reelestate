"""WaveSpeed API wrapper: Kling video, nano-banana-2 staging."""

from __future__ import annotations

import asyncio
import time

import httpx

from orchestrator.config import settings

# Model paths
MODEL_KLING = "kwaivgi/kling-v2.5-turbo-pro/image-to-video"
MODEL_STAGING = "google/nano-banana-2/edit"

# Negative prompt（shared across all Kling submissions）
NEGATIVE_PROMPT = (
    "human, person, people, hand, finger, shadow of person, "
    "reflection of person, handheld, walking, footsteps, "
    "camera shake, wobble, vibration, jitter, jerky, shaky cam, "
    "motion blur, sudden movement, fast motion, abrupt acceleration, "
    "lens breathing, rack focus, depth of field shift, "
    "distortion, warping, morphing, fish eye, "
    "new objects appearing, objects disappearing, "
    "changing reflections, mirror artifacts, flickering lights, "
    "texture swimming, surface shimmer, wall bending, "
    "blurry, low quality, unstable frame, interlacing"
)

# Camera movement prompts — v3 (scene-agnostic)
PROMPT_PUSH_IN = (
    "Cinematic architectural visualization. "
    "Camera: slow motorized dolly forward on a straight rail "
    "toward the center of the scene. Constant speed, perfectly "
    "linear motion. Shot on 24mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_PULL_OUT = (
    "Cinematic architectural visualization. "
    "Camera: slow motorized dolly backward on a straight rail, "
    "gradually revealing the full scene. Constant speed, perfectly "
    "linear motion. Shot on 24mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_PAN = (
    "Cinematic architectural visualization. "
    "Camera: slow horizontal pan from left to right on a fluid "
    "head tripod. Fixed position, rotation only. Constant angular "
    "speed. Shot on 35mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_TRUCK_LEFT = (
    "Cinematic architectural visualization. "
    "Camera: slow lateral slide to the left on a motorized rail, "
    "parallel to the nearest surface. Constant speed, perfectly "
    "linear motion. Shot on 35mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_TRUCK_RIGHT = (
    "Cinematic architectural visualization. "
    "Camera: slow lateral slide to the right on a motorized rail, "
    "parallel to the nearest surface. Constant speed, perfectly "
    "linear motion. Shot on 35mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_PEDESTAL_UP = (
    "Cinematic architectural visualization. "
    "Camera: slow vertical rise on a motorized column, starting "
    "from a low angle. Constant speed, perfectly smooth ascent. "
    "Shot on 24mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_PEDESTAL_DOWN = (
    "Cinematic architectural visualization. "
    "Camera: slow vertical descent on a motorized column, starting "
    "from a high angle. Constant speed, perfectly smooth descent. "
    "Shot on 24mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_DRONE_UP = (
    "Aerial view rising slowly upward, revealing the surroundings. "
    "Perfectly stable. No people."
)
PROMPT_ORBIT = (
    "Cinematic architectural visualization. "
    "Camera: slow orbital arc around the subject on a stabilized "
    "gimbal, maintaining constant distance and height. Constant "
    "angular speed, perfectly smooth circular path. Shot on 35mm "
    "lens, f/5.6, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
)
PROMPT_STATIC = (
    "Cinematic architectural visualization. "
    "Camera: completely static, locked-off tripod shot. Zero "
    "camera movement. Shot on 35mm lens, f/8, deep focus. "
    "Every element in the scene remains completely still. "
    "Photorealistic, 4K render quality."
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
                "guidance_scale": 0.8,
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
