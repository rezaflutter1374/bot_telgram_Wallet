from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from arq.connections import RedisSettings, create_pool

from core.logging import configure_logging
from core.settings import Settings

logger = logging.getLogger("scheduler")


async def enqueue_daily_settlement(pool) -> None:
    await pool.enqueue_job("daily_settlement")


async def enqueue_job(pool, job_name: str) -> None:
    await pool.enqueue_job(job_name)


async def main_async() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    scheduler = AsyncIOScheduler(timezone=settings.timezone)
    scheduler.add_job(
        enqueue_daily_settlement,
        trigger=CronTrigger(day_of_week="mon-fri", hour=1, minute=25, timezone=settings.timezone),
        args=[pool],
        id="daily_settlement",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_job,
        trigger=IntervalTrigger(seconds=settings.price_refresh_interval_seconds),
        args=[pool, "refresh_prices"],
        id="refresh_prices",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_job,
        trigger=IntervalTrigger(seconds=15),
        args=[pool, "send_notifications"],
        id="send_notifications",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_job,
        trigger=IntervalTrigger(seconds=30),
        args=[pool, "monitor_margin_calls"],
        id="monitor_margin_calls",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_job,
        trigger=IntervalTrigger(seconds=30),
        args=[pool, "monitor_liquidations"],
        id="monitor_liquidations",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_job,
        trigger=IntervalTrigger(seconds=15),
        args=[pool, "trigger_stop_orders_task"],
        id="trigger_stop_orders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_job,
        trigger=IntervalTrigger(seconds=60),
        args=[pool, "expire_stale_orders_task"],
        id="expire_stale_orders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enqueue_job,
        trigger=CronTrigger(hour=3, minute=0, timezone=settings.timezone),
        args=[pool, "cleanup_old_data_task"],
        id="cleanup_old_data",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("scheduler_started")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        scheduler.shutdown(wait=False)
        pool.close()
        with suppress(Exception):
            await pool.wait_closed()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
