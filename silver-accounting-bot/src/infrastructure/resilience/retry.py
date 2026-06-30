from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

logger = logging.getLogger("resilience.retry")


@dataclass(frozen=True)
class RetryConfig:
    max_retries: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


_retry_default = RetryConfig()


def retry_config(*, max_retries: int = 3, base_delay: float = 1.0) -> RetryConfig:
    return RetryConfig(max_retries=max_retries, base_delay_seconds=base_delay)


F = TypeVar("F", bound=Callable[..., Awaitable])


def async_retry(
    config: RetryConfig = _retry_default,
    *,
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(config.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    if attempt >= config.max_retries:
                        raise
                    if on_retry:
                        on_retry(exc, attempt + 1)
                    delay = min(config.base_delay_seconds * (config.exponential_base ** attempt), config.max_delay_seconds)
                    if config.jitter:
                        import random
                        delay *= 0.5 + random.random() * 0.5
                    logger.warning("retry_attempt", extra={"func": func.__name__, "attempt": attempt + 1, "delay": round(delay, 2), "error": str(exc)})
                    await asyncio.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
