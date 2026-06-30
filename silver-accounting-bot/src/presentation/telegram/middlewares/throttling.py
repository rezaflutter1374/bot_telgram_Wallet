from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramBadRequest

from infrastructure.redis.rate_limiter import RateLimiter


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limiter: RateLimiter, *, limit: int = 30, window_seconds: int = 10) -> None:
        self._limiter = limiter
        self._limit = limit
        self._window = timedelta(seconds=window_seconds)

    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None:
            key = f"user:{user.id}"
            allowed = await self._limiter.allow(key, limit=self._limit, window=self._window)
            if not allowed:
                try:
                    await getattr(event, "answer")("Rate limit. Try again.")
                except TelegramBadRequest:
                    return None
                return None
        return await handler(event, data)
