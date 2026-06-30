from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from application.errors import ValidationError
from application.use_cases.services import AppServices
from core.security import Encryptor
from domain.enums import TicketStatus
from presentation.telegram.uploads import extract_secure_attachment_file_id

router = Router(name="support")


@router.message(Command("replyticket"))
async def reply_ticket(message: Message, command: CommandObject, services: AppServices, encryptor: Encryptor) -> None:
    if not command.args:
        await message.answer("Usage: /replyticket <ticket_id> <message> (optionally attach files)")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /replyticket <ticket_id> <message>")
        return
    try:
        ticket_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid ticket id")
        return
    text = parts[1]
    attachments: list[str] = []
    if message.document or message.photo:
        try:
            attachments.append(encryptor.encrypt_text(extract_secure_attachment_file_id(message)))
        except ValidationError as exc:
            await message.answer(str(exc))
            return
    user = await services.register_or_get_user(message.from_user.id)
    await services.reply_ticket(user.id, ticket_id, text, attachments)
    await message.answer("Replied.")


@router.message(Command("closeticket"))
async def close_ticket(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /closeticket <ticket_id>")
        return
    try:
        ticket_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid ticket id")
        return
    user = await services.register_or_get_user(message.from_user.id)
    await services.close_ticket(user.id, ticket_id)
    await message.answer("Closed.")


@router.message(Command("reopenticket"))
async def reopen_ticket(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /reopenticket <ticket_id>")
        return
    try:
        ticket_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid ticket id")
        return
    user = await services.register_or_get_user(message.from_user.id)
    await services.reopen_ticket(user.id, ticket_id)
    await message.answer("Reopened.")


@router.message(Command("internalticketnote"))
async def internal_ticket_note(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /internalticketnote <ticket_id> <message>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /internalticketnote <ticket_id> <message>")
        return
    try:
        ticket_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid ticket id")
        return
    user = await services.register_or_get_user(message.from_user.id)
    await services.add_internal_ticket_note(user.id, ticket_id, parts[1])
    await message.answer("Internal note added.")


@router.message(Command("tickets"))
async def list_tickets(message: Message, command: CommandObject, services: AppServices) -> None:
    status = None
    query = None
    if command.args:
        parts = command.args.split(maxsplit=1)
        if parts[0].strip().lower() in {"open", "closed"}:
            status = TicketStatus(parts[0].strip().lower())
            query = parts[1].strip() if len(parts) == 2 else None
        else:
            query = command.args.strip()
    user = await services.register_or_get_user(message.from_user.id)
    rows = await services.list_tickets(user.id, status=status, query=query, limit=20)
    if not rows:
        await message.answer("No tickets found.")
        return
    lines = [f"#{row['id']} user={row['user_id']} {row['status'].value} {row['subject']}" for row in rows]
    await message.answer("\n".join(lines))
