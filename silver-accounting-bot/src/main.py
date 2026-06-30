from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from contextlib import suppress
from urllib.parse import urljoin

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from core.di import build_container
from core.logging import configure_logging
from core.settings import Settings
from infrastructure.db.session import Database
from infrastructure.monitoring.health import HealthChecker, check_database, check_redis
from presentation.telegram.app import build_bot, build_dispatcher


logger = logging.getLogger("main")


def _resolve_bot_mode(settings: Settings) -> str:
    if settings.bot_mode == "auto":
        return "webhook" if settings.webhook_base_url else "polling"
    return settings.bot_mode


def _build_webhook_url(settings: Settings) -> str:
    if not settings.webhook_base_url:
        raise RuntimeError("WEBHOOK_BASE_URL must be configured for webhook mode")
    base = settings.webhook_base_url.rstrip("/") + "/"
    return urljoin(base, settings.webhook_path.lstrip("/"))


def _correlation_id_middleware():
    @web.middleware
    async def middleware(request: web.Request, handler: web.RequestHandler) -> web.StreamResponse:
        correlation_id = request.headers.get("X-Correlation-ID") or request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request["correlation_id"] = correlation_id
        response = await handler(request)
        response.headers["X-Correlation-ID"] = correlation_id
        return response
    return middleware


async def _start_web_server(
    host: str,
    port: int,
    health_path: str,
    metrics_path: str,
    webhook_path: str,
    webhook_secret: str | None,
    db: Database,
    redis,
    bot,
    dispatcher,
) -> web.AppRunner:
    app = web.Application(middlewares=[_correlation_id_middleware()])

    health_checker = HealthChecker()
    health_checker.register("database", lambda: check_database(db))
    health_checker.register("redis", lambda: check_redis(redis))

    async def health(_: web.Request) -> web.Response:
        status = await health_checker.check_all()
        response_status = 200 if status.healthy else 503
        return web.json_response(
            {
                "status": "ok" if status.healthy else "degraded",
                "checks": status.checks,
                "details": status.details,
            },
            status=response_status,
        )

    async def ready(_: web.Request) -> web.Response:
        status = await health_checker.check_all()
        if status.healthy:
            return web.json_response({"status": "ready", "checks": status.checks})
        return web.json_response({"status": "not_ready", "checks": status.checks}, status=503)

    async def live(_: web.Request) -> web.Response:
        try:
            async with db.session() as session:
                await session.execute(text("SELECT 1"))
            await redis.ping()
            return web.json_response({"status": "alive"})
        except Exception:
            return web.json_response({"status": "dead"}, status=503)

    async def metrics(_: web.Request) -> web.Response:
        payload = generate_latest()
        return web.Response(body=payload, headers={"Content-Type": CONTENT_TYPE_LATEST})

    async def telegram_webhook(request: web.Request) -> web.Response:
        if webhook_secret:
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret != webhook_secret:
                raise web.HTTPForbidden(text="invalid webhook secret")
        payload = await request.json()
        await dispatcher.feed_raw_update(bot, payload)
        return web.Response(text="ok")

    app.router.add_get(health_path, health)
    app.router.add_get("/ready", ready)
    app.router.add_get("/live", live)
    app.router.add_get(metrics_path, metrics)
    app.router.add_post(webhook_path, telegram_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=host, port=port)
    await site.start()
    return runner


async def run_bot() -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    mode = _resolve_bot_mode(settings)
    container = build_container(settings)
    await container.services.ensure_rbac_defaults()
    await container.services.ensure_accounting_defaults()

    bot = build_bot(container)
    dp = build_dispatcher(container)

    runner = await _start_web_server(
        host=settings.web_host,
        port=settings.web_port,
        health_path=settings.health_path,
        metrics_path=settings.metrics_path,
        webhook_path=settings.webhook_path,
        webhook_secret=settings.webhook_secret,
        db=container.db,
        redis=container.redis,
        bot=bot,
        dispatcher=dp,
    )

    try:
        logger.info("bot_starting", extra={"mode": mode})
        if mode == "webhook":
            webhook_url = _build_webhook_url(settings)
            await bot.set_webhook(
                url=webhook_url,
                secret_token=settings.webhook_secret,
                allowed_updates=dp.resolve_used_update_types(),
                drop_pending_updates=False,
            )
            logger.info("webhook_configured", extra={"url": webhook_url})
            await asyncio.Event().wait()
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        if mode == "webhook":
            with suppress(Exception):
                await bot.delete_webhook(drop_pending_updates=False)
        await runner.cleanup()
        await bot.session.close()
        await container.redis.close()
        await container.db.engine.dispose()
        logger.info("bot_stopped")


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "bot"
    if mode == "bot":
        asyncio.run(run_bot())
        return
    raise SystemExit(f"Unknown mode: {mode}")


if __name__ == "__main__":
    main()
