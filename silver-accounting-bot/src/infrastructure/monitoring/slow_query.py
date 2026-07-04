from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, TypeVar

from infrastructure.monitoring.metrics import db_operation_duration

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def track_query(threshold_ms: float = 100.0) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                return await func(*args, **kwargs)
            finally:
                duration_s = time.monotonic() - start
                duration_ms = duration_s * 1000
                db_operation_duration.labels(operation=func.__name__).observe(duration_s)
                if duration_ms > threshold_ms:
                    logger.warning(
                        "slow_query",
                        extra={
                            "query": func.__name__,
                            "duration_ms": round(duration_ms, 2),
                            "threshold_ms": threshold_ms,
                        },
                    )

        return wrapper

    return decorator
