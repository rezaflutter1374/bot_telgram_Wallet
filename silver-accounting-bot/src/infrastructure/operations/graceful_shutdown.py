from __future__ import annotations

import asyncio
import json
import logging
import signal
from contextlib import suppress
from datetime import datetime, timezone
from types import FrameType

from aiogram import Bot
from redis.asyncio import Redis

from infrastructure.db.session import Database

logger = logging.getLogger("graceful_shutdown")

RUNTIME_STATE_KEY = "runtime:graceful_state"


class GracefulShutdown:
    def __init__(self, db: Database, redis: Redis, bot: Bot | None = None) -> None:
        self._db = db
        self._redis = redis
        self._bot = bot
        self._shutdown_event = asyncio.Event()
        self._ongoing_tasks: set[asyncio.Task] = set()

    def register_handler(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._handle_signal)

    def _handle_signal(self) -> None:
        logger.info("signal_received")
        self._shutdown_event.set()

    def track_task(self, task: asyncio.Task) -> None:
        self._ongoing_tasks.add(task)
        task.add_done_callback(self._ongoing_tasks.discard)

    async def wait_for_shutdown_signal(self) -> None:
        await self._shutdown_event.wait()

    async def drain_workers(self, timeout: int = 30) -> None:
        if not self._ongoing_tasks:
            return
        logger.info("draining_workers", extra={"pending": len(self._ongoing_tasks)})
        done, pending = await asyncio.wait(
            self._ongoing_tasks,
            timeout=timeout,
            return_when=asyncio.ALL_COMPLETED,
        )
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        logger.info("workers_drained", extra={"completed": len(done), "cancelled": len(pending)})

    async def close_connections(self) -> None:
        logger.info("closing_connections")
        if self._bot is not None:
            with suppress(Exception):
                await self._bot.session.close()
                logger.info("bot_session_closed")
        with suppress(Exception):
            await self._redis.close()
            logger.info("redis_closed")
        with suppress(Exception):
            await self._db.engine.dispose()
            logger.info("db_pool_disposed")

    async def save_state(self) -> None:
        state = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "version": 1,
        }
        await self._redis.set(RUNTIME_STATE_KEY, json.dumps(state, ensure_ascii=False))
        logger.info("state_saved")

    async def restore_state(self) -> dict | None:
        raw = await self._redis.get(RUNTIME_STATE_KEY)
        if raw is None:
            return None
        try:
            state = json.loads(raw)
            logger.info("state_restored", extra={"saved_at": state.get("saved_at")})
            return state
        except (json.JSONDecodeError, TypeError):
            logger.warning("state_corrupt")
            return None

    async def shutdown(self, timeout: int = 30) -> None:
        logger.info("shutdown_started")
        await self.save_state()
        await self.drain_workers(timeout=timeout)
        await self.close_connections()
        logger.info("shutdown_complete")

    async def __aenter__(self) -> GracefulShutdown:
        self.register_handler()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_val: BaseException | None = None,
        exc_tb: type[FrameType] | None = None,
    ) -> None:
        await self.shutdown()
