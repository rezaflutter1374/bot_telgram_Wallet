from __future__ import annotations

import json
from datetime import datetime, timezone

from redis.asyncio import Redis


class RedisRuntimeStateRepo:
    def __init__(self, redis: Redis, key: str = "runtime:maintenance") -> None:
        self._redis = redis
        self._key = key

    async def get_maintenance_mode(self) -> dict:
        raw = await self._redis.get(self._key)
        if raw is None:
            return {
                "enabled": False,
                "message": None,
                "actor_user_id": None,
                "updated_at": None,
            }
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {
                "enabled": False,
                "message": None,
                "actor_user_id": None,
                "updated_at": None,
            }
        return {
            "enabled": bool(data.get("enabled", False)),
            "message": data.get("message"),
            "actor_user_id": data.get("actor_user_id"),
            "updated_at": data.get("updated_at"),
        }

    async def set_maintenance_mode(self, enabled: bool, message: str | None, actor_user_id: int | None) -> dict:
        payload = {
            "enabled": enabled,
            "message": message.strip() if message else None,
            "actor_user_id": actor_user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.set(self._key, json.dumps(payload, ensure_ascii=False))
        return payload
