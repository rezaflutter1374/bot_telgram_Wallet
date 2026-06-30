from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from application.use_cases.services import AppServices
from core.di import Container

router = Router(name="common")


@router.message(Command("start"))
async def start(message: Message, services: AppServices, container: Container) -> None:
    user = await services.register_or_get_user(message.from_user.id)
    await services.ensure_super_admin(user.id, message.from_user.id, container.settings.super_admin_ids)
    await message.answer(
        "\n".join(
            [
                "Silver Accounting & Trading Bot",
                f"User ID: {user.id}",
                f"KYC: {user.kyc_status.value}",
                "",
                "Commands:",
                "/kyc",
                "/price",
                "/wallet",
                "/buy",
                "/sell",
                "/orders",
                "/ticket",
            ]
        )
    )


@router.message(Command("help"))
async def help_cmd(message: Message) -> None:
    await message.answer("Use /start to see available commands.")

