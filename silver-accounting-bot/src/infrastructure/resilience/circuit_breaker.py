from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from domain.enums import CircuitBreakerState

logger = logging.getLogger("resilience.circuit_breaker")


@dataclass
class CircuitBreakerConfig:
    error_threshold: int = 5
    recovery_timeout_seconds: float = 60.0
    half_open_max_calls: int = 3


class CircuitBreaker:
    def __init__(self, name: str, config: CircuitBreakerConfig) -> None:
        self._name = name
        self._config = config
        self._state = CircuitBreakerState.closed
        self._failure_count = 0
        self._half_open_calls = 0
        self._opened_at: float | None = None
        self._half_open_at: float | None = None
        self._last_success_at: float | None = None
        self._last_failure_at: float | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def call(self, func: Callable[..., Awaitable], *args, **kwargs):
        self._evaluate_state()
        if self._state == CircuitBreakerState.open:
            raise CircuitBreakerOpenError(self._name)
        if self._state == CircuitBreakerState.half_open:
            if self._half_open_calls >= self._config.half_open_max_calls:
                raise CircuitBreakerOpenError(self._name)
            self._half_open_calls += 1
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _evaluate_state(self) -> None:
        if self._state == CircuitBreakerState.open:
            if self._opened_at is not None and (time.monotonic() - self._opened_at) >= self._config.recovery_timeout_seconds:
                logger.info("circuit_half_open", extra={"circuit": self._name, "previous_state": self._state.value})
                self._state = CircuitBreakerState.half_open
                self._half_open_calls = 0
                self._half_open_at = time.monotonic()

    def _on_success(self) -> None:
        self._last_success_at = time.monotonic()
        if self._state == CircuitBreakerState.half_open:
            logger.info("circuit_closed", extra={"circuit": self._name, "half_open_calls": self._half_open_calls})
            self._state = CircuitBreakerState.closed
            self._failure_count = 0
            self._half_open_calls = 0
            self._opened_at = None
            self._half_open_at = None

    def _on_failure(self) -> None:
        self._last_failure_at = time.monotonic()
        self._failure_count += 1
        if self._state == CircuitBreakerState.half_open:
            self._state = CircuitBreakerState.open
            self._opened_at = time.monotonic()
            self._half_open_at = None
            self._half_open_calls = 0
            logger.warning("circuit_reopened", extra={"circuit": self._name, "failure_count": self._failure_count})
        elif self._state == CircuitBreakerState.closed and self._failure_count >= self._config.error_threshold:
            self._state = CircuitBreakerState.open
            self._opened_at = time.monotonic()
            logger.warning("circuit_opened", extra={"circuit": self._name, "failure_count": self._failure_count})

    def to_dict(self) -> dict:
        return {
            "circuit_name": self._name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "error_threshold": self._config.error_threshold,
            "recovery_timeout_seconds": self._config.recovery_timeout_seconds,
            "opened_at": self._opened_at,
            "last_failure_at": self._last_failure_at,
            "last_success_at": self._last_success_at,
        }


class CircuitBreakerOpenError(Exception):
    def __init__(self, name: str) -> None:
        self.circuit_name = name
        super().__init__(f"Circuit breaker '{name}' is open")


class CircuitBreakerRegistry:
    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str, config: CircuitBreakerConfig | None = None) -> CircuitBreaker:
        if name not in self._breakers:
            cfg = config or CircuitBreakerConfig()
            self._breakers[name] = CircuitBreaker(name, cfg)
        return self._breakers[name]

    async def get_state(self, name: str) -> dict | None:
        cb = self._breakers.get(name)
        if cb is None:
            return None
        return cb.to_dict()

    async def all_states(self) -> list[dict]:
        return [cb.to_dict() for cb in self._breakers.values()]

    async def reset(self, name: str) -> None:
        self._breakers.pop(name, None)
