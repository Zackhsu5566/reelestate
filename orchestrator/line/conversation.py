from __future__ import annotations

import json
import logging
from enum import StrEnum

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

KEY_PREFIX = "conv"
CONV_TTL = 86400  # 24 hours


class ConversationState(StrEnum):
    idle = "idle"
    collecting_photos = "collecting"
    awaiting_label = "awaiting_label"
    awaiting_info = "awaiting_info"
    processing = "processing"
    awaiting_feedback = "awaiting_feedback"


def _empty_state() -> dict:
    return {
        "state": ConversationState.idle,
        "pending_photos": [],
        "spaces": [],
        "exterior_photo": None,
        "job_id": None,
    }


class ConversationManager:
    """Redis-backed conversation state for LINE users."""

    def __init__(self, redis: Redis) -> None:
        self._r = redis

    def _key(self, user_id: str) -> str:
        return f"{KEY_PREFIX}:{user_id}"

    async def get(self, user_id: str) -> dict:
        data = await self._r.get(self._key(user_id))
        if data is None:
            return _empty_state()
        return json.loads(data)

    async def _save(self, user_id: str, state: dict) -> None:
        await self._r.set(
            self._key(user_id),
            json.dumps(state, ensure_ascii=False),
            ex=CONV_TTL,
        )

    async def add_photo(self, user_id: str, photo_url: str) -> int:
        """Add photo to pending batch. Returns updated pending count.

        Only transitions to collecting_photos from idle; other states
        (e.g. awaiting_label) keep their current state so the photo is
        queued without disrupting the flow.
        """
        state = await self.get(user_id)
        state["pending_photos"].append(photo_url)
        if state["state"] == ConversationState.idle:
            state["state"] = ConversationState.collecting_photos
        await self._save(user_id, state)
        return len(state["pending_photos"])

    async def finalize_batch(self, user_id: str) -> None:
        state = await self.get(user_id)
        if state["state"] == ConversationState.collecting_photos:
            state["state"] = ConversationState.awaiting_label
            await self._save(user_id, state)

    async def assign_label(self, user_id: str, label: str) -> None:
        state = await self.get(user_id)
        if state["state"] != ConversationState.awaiting_label:
            return

        photos = state["pending_photos"]

        if label == "外觀":
            if photos:
                state["exterior_photo"] = photos[0]
        else:
            state["spaces"].append({"label": label, "photos": photos})

        state["pending_photos"] = []
        state["state"] = ConversationState.idle
        await self._save(user_id, state)

    async def complete_photos(self, user_id: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.awaiting_info
        await self._save(user_id, state)

    async def set_processing(self, user_id: str, job_id: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.processing
        state["job_id"] = job_id
        await self._save(user_id, state)

    async def set_awaiting_feedback(self, user_id: str) -> None:
        state = await self.get(user_id)
        state["state"] = ConversationState.awaiting_feedback
        await self._save(user_id, state)

    async def reset(self, user_id: str) -> None:
        await self._save(user_id, _empty_state())

    async def delete(self, user_id: str) -> None:
        await self._r.delete(self._key(user_id))
