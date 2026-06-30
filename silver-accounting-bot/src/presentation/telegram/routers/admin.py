from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from application.errors import ValidationError
from application.use_cases.services import AppServices
from core.security import Encryptor
from domain.enums import KycStatus
from presentation.telegram.uploads import validate_backup_document

router = Router(name="admin")


def _d(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise ValueError("Invalid decimal")


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("Invalid datetime. Use ISO-8601, for example 2026-07-01T10:30:00+00:00") from exc
    if parsed.tzinfo is None:
        raise ValueError("Datetime must include timezone offset")
    return parsed


@router.message(Command("setprice"))
async def set_price(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /setprice <buy_price> <sell_price>")
        return
    parts = command.args.split()
    if len(parts) != 2:
        await message.answer("Usage: /setprice <buy_price> <sell_price>")
        return
    try:
        buy = _d(parts[0])
        sell = _d(parts[1])
    except ValueError:
        await message.answer("Invalid prices")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    p = await services.set_price(actor.id, buy, sell)
    await message.answer(f"Price updated. Buy: {p.buy_price} | Sell: {p.sell_price}")


@router.message(Command("grantrole"))
async def grant_role(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /grantrole <telegram_id> <role>")
        return
    parts = command.args.split()
    if len(parts) != 2:
        await message.answer("Usage: /grantrole <telegram_id> <role>")
        return
    try:
        telegram_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid telegram id")
        return
    role = parts[1].strip()
    actor = await services.register_or_get_user(message.from_user.id)
    await services.grant_role(actor.id, telegram_id, role)
    await message.answer("Role granted.")


@router.message(Command("reviewkyc"))
async def review_kyc(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /reviewkyc <telegram_id> <approved|rejected|suspended|blocked> [note]")
        return
    parts = command.args.split(maxsplit=2)
    if len(parts) < 2:
        await message.answer("Usage: /reviewkyc <telegram_id> <approved|rejected|suspended|blocked> [note]")
        return
    try:
        telegram_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid telegram id")
        return
    status_str = parts[1].strip().lower()
    note = parts[2] if len(parts) == 3 else None
    try:
        status = KycStatus(status_str)
    except ValueError:
        await message.answer("Invalid status")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    target = await services.get_user_by_telegram_id(telegram_id)
    await services.review_kyc(actor.id, target.id, status, note=note)
    await message.answer("KYC reviewed.")


@router.message(Command("setrisk"))
async def set_risk(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /setrisk <name> <max_user_exposure_kg> <max_order_kg> <enabled true|false>")
        return
    parts = command.args.split()
    if len(parts) != 4:
        await message.answer("Usage: /setrisk <name> <max_user_exposure_kg> <max_order_kg> <enabled true|false>")
        return
    name = parts[0].strip()
    try:
        max_exposure = _d(parts[1])
        max_order = _d(parts[2])
    except ValueError:
        await message.answer("Invalid numeric values")
        return
    enabled_raw = parts[3].strip().lower()
    if enabled_raw not in {"true", "false"}:
        await message.answer("Enabled must be true or false")
        return
    enabled = enabled_raw == "true"
    actor = await services.register_or_get_user(message.from_user.id)
    row = await services.set_risk_rule(actor.id, name, max_exposure, max_order, enabled)
    await message.answer(f"Risk rule saved: #{row['id']} enabled={row['enabled']}")


@router.message(Command("pendingcancels"))
async def pending_cancels(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    rows = await services.list_pending_cancellations(actor.id, limit=20)
    if not rows:
        await message.answer("No pending cancellations.")
        return
    lines = []
    for r in rows:
        lines.append(f"#{r['id']} order={r['order_id']} user={r['requested_by_user_id']} {r['status'].value}")
    await message.answer("\n".join(lines))


@router.message(Command("approvecancel"))
async def approve_cancel(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /approvecancel <order_id>")
        return
    try:
        order_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid order id")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    c = await services.review_order_cancellation(actor.id, order_id, approve=True)
    await message.answer(f"Cancellation approved. Status: {c['status'].value}")


@router.message(Command("rejectcancel"))
async def reject_cancel(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /rejectcancel <order_id>")
        return
    try:
        order_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid order id")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    c = await services.review_order_cancellation(actor.id, order_id, approve=False)
    await message.answer(f"Cancellation rejected. Status: {c['status'].value}")


@router.message(Command("backup"))
async def backup(message: Message, services: AppServices, encryptor: Encryptor) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    snapshot = await services.backup_snapshot(actor.id)
    token = encryptor.encrypt_text(json.dumps(snapshot, ensure_ascii=False))
    payload = token.encode("utf-8")
    await message.answer_document(BufferedInputFile(payload, filename="backup.enc.json"))


@router.message(Command("restore"))
async def restore(message: Message, services: AppServices, encryptor: Encryptor) -> None:
    try:
        file_id = validate_backup_document(message)
    except ValidationError as exc:
        await message.answer(str(exc))
        return
    actor = await services.register_or_get_user(message.from_user.id)
    buf = await message.bot.download(file_id)
    token = buf.getvalue().decode("utf-8")
    raw = encryptor.decrypt_text(token)
    snapshot = json.loads(raw)
    await services.restore_snapshot(actor.id, snapshot)
    await message.answer("Restore completed.")


@router.message(Command("maintenance"))
async def maintenance_status(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    if not await services.user_has_permission(actor.id, "configure_system"):
        await message.answer("Forbidden")
        return
    state = await services.get_maintenance_mode()
    await message.answer(
        "\n".join(
            [
                f"Enabled: {state['enabled']}",
                f"Message: {state.get('message') or '-'}",
                f"Updated at: {state.get('updated_at') or '-'}",
            ]
        )
    )


@router.message(Command("maintenanceon"))
async def maintenance_on(message: Message, command: CommandObject, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    state = await services.set_maintenance_mode(
        actor.id,
        True,
        message=command.args or "The system is currently under scheduled maintenance. Please try again later.",
    )
    await message.answer(f"Maintenance mode enabled.\nMessage: {state.get('message') or '-'}")


@router.message(Command("maintenanceoff"))
async def maintenance_off(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    await services.set_maintenance_mode(actor.id, False, message=None)
    await message.answer("Maintenance mode disabled.")


@router.message(Command("broadcast"))
async def broadcast_all(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /broadcast <message>")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.broadcast_message(actor.id, message_type="text", text=command.args)
    await message.answer(f"Broadcast queued for {result['recipients']} recipients.")


@router.message(Command("broadcastrole"))
async def broadcast_role(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /broadcastrole <role> <message>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /broadcastrole <role> <message>")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.broadcast_message(actor.id, message_type="text", text=parts[1], role=parts[0].strip())
    await message.answer(f"Role broadcast queued for {result['recipients']} recipients.")


@router.message(Command("broadcastlang"))
async def broadcast_language(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /broadcastlang <language_code> <message>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /broadcastlang <language_code> <message>")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.broadcast_message(actor.id, message_type="text", text=parts[1], language_code=parts[0].strip())
    await message.answer(f"Language broadcast queued for {result['recipients']} recipients.")


@router.message(Command("broadcastkyc"))
async def broadcast_kyc(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /broadcastkyc <pending|approved|rejected|suspended|blocked> <message>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /broadcastkyc <pending|approved|rejected|suspended|blocked> <message>")
        return
    try:
        status = KycStatus(parts[0].strip().lower())
    except ValueError:
        await message.answer("Invalid KYC status")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.broadcast_message(actor.id, message_type="text", text=parts[1], kyc_status=status)
    await message.answer(f"KYC broadcast queued for {result['recipients']} recipients.")


@router.message(Command("broadcastactive"))
async def broadcast_active(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /broadcastactive <true|false> <message>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /broadcastactive <true|false> <message>")
        return
    raw_flag = parts[0].strip().lower()
    if raw_flag not in {"true", "false"}:
        await message.answer("The trading_active flag must be true or false")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.broadcast_message(actor.id, message_type="text", text=parts[1], trading_active=raw_flag == "true")
    await message.answer(f"Activity broadcast queued for {result['recipients']} recipients.")


@router.message(Command("broadcastschedule"))
async def broadcast_schedule(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /broadcastschedule <ISO-8601 datetime> <message>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /broadcastschedule <ISO-8601 datetime> <message>")
        return
    try:
        scheduled_at = _parse_iso_datetime(parts[0])
    except ValueError as exc:
        await message.answer(str(exc))
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.broadcast_message(actor.id, message_type="text", text=parts[1], scheduled_at=scheduled_at)
    await message.answer(f"Scheduled broadcast queued for {result['recipients']} recipients.")


@router.message(Command("broadcastreply"))
async def broadcast_reply(message: Message, services: AppServices) -> None:
    reply = message.reply_to_message
    if reply is None:
        await message.answer("Reply to a text, photo, document, or video message and run /broadcastreply.")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    if reply.photo:
        result = await services.broadcast_message(
            actor.id,
            message_type="photo",
            file_id=reply.photo[-1].file_id,
            caption=reply.caption,
        )
    elif reply.document is not None:
        result = await services.broadcast_message(
            actor.id,
            message_type="document",
            file_id=reply.document.file_id,
            caption=reply.caption,
        )
    elif reply.video is not None:
        result = await services.broadcast_message(
            actor.id,
            message_type="video",
            file_id=reply.video.file_id,
            caption=reply.caption,
        )
    elif reply.text:
        result = await services.broadcast_message(actor.id, message_type="forward", forward_from_chat_id=reply.chat.id, forward_message_id=reply.message_id)
    else:
        await message.answer("Unsupported reply content for broadcast.")
        return
    await message.answer(f"Reply broadcast queued for {result['recipients']} recipients.")
