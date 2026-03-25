from __future__ import annotations

import asyncio
import json

import redis.asyncio as redis

from orchestrator.config import settings
from orchestrator.models import AssetTask, JobState, JobStatus


class JobStore:
    JOB_TTL = 7 * 24 * 3600  # 7 days

    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._job_locks: dict[str, asyncio.Lock] = {}

    async def connect(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    @property
    def r(self) -> redis.Redis:
        assert self._redis is not None, "JobStore not connected"
        return self._redis

    # ── CRUD ──

    async def create(self, state: JobState) -> None:
        pipe = self.r.pipeline()
        pipe.set(f"job:{state.job_id}", state.model_dump_json(), ex=self.JOB_TTL)
        pipe.sadd("jobs:active", state.job_id)
        await pipe.execute()

    async def get(self, job_id: str) -> JobState | None:
        data = await self.r.get(f"job:{job_id}")
        if data is None:
            return None
        return JobState.model_validate_json(data)

    async def save(self, state: JobState) -> None:
        await self.r.set(
            f"job:{state.job_id}", state.model_dump_json(), ex=self.JOB_TTL
        )

    def _get_lock(self, job_id: str) -> asyncio.Lock:
        """Get or create a per-job lock for atomic read-modify-write."""
        if job_id not in self._job_locks:
            self._job_locks[job_id] = asyncio.Lock()
        return self._job_locks[job_id]

    async def set_status(self, job_id: str, status: JobStatus) -> None:
        async with self._get_lock(job_id):
            state = await self.get(job_id)
            if state is None:
                return
            state.status = status
            await self.save(state)
        if status in (JobStatus.done, JobStatus.failed):
            await self.r.srem("jobs:active", job_id)
            self._job_locks.pop(job_id, None)

    async def update_asset_task(
        self, job_id: str, task_key: str, task: AssetTask
    ) -> None:
        async with self._get_lock(job_id):
            state = await self.get(job_id)
            if state is None:
                return
            state.asset_tasks[task_key] = task
            await self.save(state)

    _NARRATION_FIELDS = {
        "narration_enabled", "narration_gate_status",
        "narration_text", "narration_task_id", "narration_url",
        "narration_subtitles", "narration_subtitles_url",
    }

    async def update_narration(self, job_id: str, **fields) -> None:
        """Atomically update only narration fields without clobbering asset_tasks."""
        async with self._get_lock(job_id):
            state = await self.get(job_id)
            if state is None:
                return
            for k, v in fields.items():
                if k not in self._NARRATION_FIELDS:
                    raise ValueError(f"Not a narration field: {k}")
                setattr(state, k, v)
            await self.save(state)

    async def append_error(self, job_id: str, error: str) -> None:
        async with self._get_lock(job_id):
            state = await self.get(job_id)
            if state is None:
                return
            state.errors.append(error)
            await self.save(state)

    # ── Active jobs (for startup recovery) ──

    async def get_active_job_ids(self) -> list[str]:
        return list(await self.r.smembers("jobs:active"))

    # ── Gate lock ──

    async def try_acquire_gate_lock(self, job_id: str, gate: str) -> bool:
        key = f"gate:{job_id}:{gate}"
        return bool(await self.r.set(key, "1", nx=True, ex=120))

    async def release_gate_lock(self, job_id: str, gate: str) -> None:
        await self.r.delete(f"gate:{job_id}:{gate}")

    # ── Geo cache (reuse geocoding results for same location) ──

    GEO_CACHE_TTL = 30 * 24 * 3600  # 30 days

    async def get_geo_cache(self, cache_key: str) -> dict | None:
        data = await self.r.get(f"geo:{cache_key}")
        if data is None:
            return None
        return json.loads(data)

    async def set_geo_cache(self, cache_key: str, values: dict) -> None:
        """Merge values into existing cache (or create new)."""
        existing = await self.get_geo_cache(cache_key) or {}
        existing.update(values)
        await self.r.set(
            f"geo:{cache_key}", json.dumps(existing), ex=self.GEO_CACHE_TTL
        )


store = JobStore()
