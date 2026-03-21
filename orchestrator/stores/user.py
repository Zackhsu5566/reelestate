from __future__ import annotations

import logging
from redis.asyncio import Redis

from orchestrator.models import UserProfile

logger = logging.getLogger(__name__)

_CONSUME_QUOTA_LUA = """
local key = KEYS[1]
local usage = tonumber(redis.call('HGET', key, 'usage')) or 0
local quota = tonumber(redis.call('HGET', key, 'quota')) or 3
if usage < quota then
    redis.call('HINCRBY', key, 'usage', 1)
    return 1
end
return 0
"""

# Redis Hash 所有值都是 string，需要轉型的欄位
_INT_FIELDS = {"quota", "usage"}
_OPTIONAL_STR_FIELDS = {"line_id"}


class UserStore:
    def __init__(self, redis: Redis) -> None:
        self.r = redis

    async def get(self, line_user_id: str) -> UserProfile | None:
        key = f"user:{line_user_id}"
        data = await self.r.hgetall(key)
        if not data:
            return None
        # 轉型：Redis Hash 值皆為 string，需轉回正確型別
        parsed: dict = {}
        for k, v in data.items():
            if k in _INT_FIELDS:
                parsed[k] = int(v)
            elif k in _OPTIONAL_STR_FIELDS:
                parsed[k] = v if v else None
            else:
                parsed[k] = v
        return UserProfile(**parsed)

    async def create(self, profile: UserProfile) -> None:
        key = f"user:{profile.line_user_id}"
        mapping = {
            k: ("" if v is None else str(v))
            for k, v in profile.model_dump().items()
        }
        await self.r.hset(key, mapping=mapping)

    async def update(self, line_user_id: str, **fields: str | int | None) -> None:
        key = f"user:{line_user_id}"
        mapping = {
            k: ("" if v is None else str(v))
            for k, v in fields.items()
        }
        await self.r.hset(key, mapping=mapping)

    async def try_consume_quota(self, line_user_id: str) -> bool:
        key = f"user:{line_user_id}"
        result = await self.r.eval(_CONSUME_QUOTA_LUA, 1, key)
        return bool(result)
