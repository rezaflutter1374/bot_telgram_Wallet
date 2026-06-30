from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from application.use_cases.services import AppServices
from core.di import Container


class RuntimeGateMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        services: AppServices = data["services"]
        container: Container = data["container"]
        if from_user is None:
            return await handler(event, data)

        current_user = await services.register_or_get_user(
            from_user.id,
            language_code=from_user.language_code,
        )
        await services.ensure_super_admin(current_user.id, from_user.id, container.settings.super_admin_ids)
        data["current_user"] = current_user

        maintenance = await services.get_maintenance_mode()
        allowed = await services.can_access_during_maintenance(current_user.id)
        if allowed:
            return await handler(event, data)

        notice = maintenance.get("message") or "The system is currently under scheduled maintenance. Please try again later."
        if isinstance(event, Message):
            await event.answer(notice)
            return None
        if isinstance(event, CallbackQuery):
            await event.answer(notice, show_alert=True)
            if event.message is not None:
                await event.message.answer(notice)
            return None
        return None
