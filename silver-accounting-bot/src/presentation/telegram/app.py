from __future__ import annotations

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage

from core.di import Container
from presentation.telegram.middlewares.container import ContainerMiddleware
from presentation.telegram.middlewares.rbac import RbacMiddleware
from presentation.telegram.middlewares.runtime_gate import RuntimeGateMiddleware
from presentation.telegram.middlewares.throttling import ThrottlingMiddleware
from presentation.telegram.routers import admin, admin_panel, accountant, common, support, user


def build_dispatcher(container: Container) -> Dispatcher:
    storage = RedisStorage(redis=container.redis)
    dp = Dispatcher(storage=storage)

    dp.update.middleware(ContainerMiddleware(container))
    dp.update.middleware(RuntimeGateMiddleware())
    dp.update.middleware(
        ThrottlingMiddleware(
            container.rate_limiter,
            limit=container.settings.rate_limit_limit,
            window_seconds=container.settings.rate_limit_window_seconds,
        )
    )
    dp.update.middleware(RbacMiddleware(container.services))

    dp.include_router(common.router)
    dp.include_router(user.router)
    dp.include_router(support.router)
    dp.include_router(accountant.router)
    dp.include_router(admin_panel.router)
    dp.include_router(admin.router)
    return dp


def build_bot(container: Container) -> Bot:
    return Bot(token=container.settings.bot_token)
