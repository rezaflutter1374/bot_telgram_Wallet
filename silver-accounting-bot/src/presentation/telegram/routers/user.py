from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from application.errors import InsufficientDeposit, QuoteExpired, ValidationError
from application.use_cases.services import AppServices
from core.security import Encryptor
from domain.enums import OrderSide, OrderType, PaymentType, TicketPriority
from presentation.telegram.uploads import extract_secure_attachment_file_id

router = Router(name="user")


class KycStates(StatesGroup):
    full_name = State()
    phone = State()
    national_id = State()
    passport = State()
    selfie = State()


class OrderStates(StatesGroup):
    side = State()
    quantity = State()
    order_type = State()
    limit_price = State()


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError("Invalid number")


@router.message(Command("price"))
async def price(message: Message, services: AppServices) -> None:
    p = await services.get_price()
    await message.answer(f"Buy: {p.buy_price} | Sell: {p.sell_price} | Updated: {p.updated_at.isoformat()}")


@router.message(Command("wallet"))
async def wallet(message: Message, services: AppServices) -> None:
    user = await services.register_or_get_user(message.from_user.id)
    w = await services.get_wallet(user.id)
    await message.answer(
        "\n".join(
            [
                f"Available: {w['available_balance_usd']}",
                f"Frozen: {w['frozen_balance_usd']}",
                f"Equity: {w['equity_usd']}",
            ]
        )
    )


@router.message(Command("kyc"))
async def kyc_start(message: Message, state: FSMContext) -> None:
    await state.set_state(KycStates.full_name)
    await message.answer("Full name?")


@router.message(KycStates.full_name)
async def kyc_full_name(message: Message, state: FSMContext) -> None:
    await state.update_data(full_name=message.text or "")
    await state.set_state(KycStates.phone)
    await message.answer("Phone number? (send as text)")


@router.message(KycStates.phone)
async def kyc_phone(message: Message, state: FSMContext) -> None:
    phone = message.contact.phone_number if message.contact else (message.text or "")
    await state.update_data(phone=phone)
    await state.set_state(KycStates.national_id)
    await message.answer("National ID number?")


@router.message(KycStates.national_id)
async def kyc_national_id(message: Message, state: FSMContext) -> None:
    await state.update_data(national_id=message.text or "")
    await state.set_state(KycStates.passport)
    await message.answer("Passport photo/document?")


@router.message(KycStates.passport)
async def kyc_passport(message: Message, state: FSMContext) -> None:
    try:
        file_id = extract_secure_attachment_file_id(message)
    except ValidationError as exc:
        await message.answer(str(exc))
        return
    await state.update_data(passport_file_id=file_id)
    await state.set_state(KycStates.selfie)
    await message.answer("Selfie photo/document?")


@router.message(KycStates.selfie)
async def kyc_selfie(
    message: Message,
    state: FSMContext,
    services: AppServices,
    encryptor: Encryptor,
) -> None:
    try:
        file_id = extract_secure_attachment_file_id(message)
    except ValidationError as exc:
        await message.answer(str(exc))
        return
    data = await state.get_data()
    await state.clear()
    user = await services.register_or_get_user(message.from_user.id)
    await services.submit_kyc(
        user_id=user.id,
        full_name=data.get("full_name", ""),
        phone_number=data.get("phone", ""),
        national_id_enc=encryptor.encrypt_text(data.get("national_id", "")),
        passport_file_id_enc=encryptor.encrypt_text(data.get("passport_file_id", "")),
        selfie_file_id_enc=encryptor.encrypt_text(file_id),
        verification_docs_file_ids_enc=[],
    )
    await message.answer("KYC submitted. Status: pending")


@router.message(Command("buy"))
async def buy_start(message: Message, state: FSMContext) -> None:
    await state.set_state(OrderStates.quantity)
    await state.update_data(side=OrderSide.buy.value)
    await message.answer("Quantity (KG)?")


@router.message(Command("sell"))
async def sell_start(message: Message, state: FSMContext) -> None:
    await state.set_state(OrderStates.quantity)
    await state.update_data(side=OrderSide.sell.value)
    await message.answer("Quantity (KG)?")


@router.message(OrderStates.quantity)
async def order_quantity(message: Message, state: FSMContext) -> None:
    qty = _parse_decimal(message.text or "")
    await state.update_data(quantity=str(qty))
    await state.set_state(OrderStates.order_type)
    await message.answer("Order type? (market/limit)")


@router.message(OrderStates.order_type)
async def order_type(message: Message, state: FSMContext, services: AppServices) -> None:
    t = (message.text or "").strip().lower()
    if t not in {"market", "limit"}:
        await message.answer("Type must be market or limit.")
        return
    await state.update_data(order_type=t)
    if t == "limit":
        await state.set_state(OrderStates.limit_price)
        await message.answer("Limit price (USD)?")
        return
    await state.set_state(None)
    data = await state.get_data()
    await state.clear()
    await _create_order_from_state(message, data, services=services)


@router.message(OrderStates.limit_price)
async def order_limit_price(message: Message, state: FSMContext, services: AppServices) -> None:
    limit_price = _parse_decimal(message.text or "")
    data = await state.get_data()
    await state.clear()
    data["limit_price"] = str(limit_price)
    await _create_order_from_state(message, data, services=services)


async def _create_order_from_state(message: Message, data: dict, services: AppServices) -> None:
    user = await services.register_or_get_user(message.from_user.id)
    side = OrderSide(data["side"])
    qty = _parse_decimal(data["quantity"])
    order_type = OrderType.limit if data.get("order_type") == "limit" else OrderType.market
    limit_price = _parse_decimal(data["limit_price"]) if data.get("limit_price") else None
    try:
        order = await services.create_order(
            user_id=user.id,
            side=side,
            order_type=order_type,
            quantity_kg=qty,
            limit_price=limit_price,
        )
    except InsufficientDeposit:
        await message.answer("Deposit requirement not satisfied (100 USD per KG).")
        return
    await message.answer(
        "\n".join(
            [
                f"Order #{order.id}",
                f"{order.side.value} {order.quantity_kg} KG @ {order.quoted_price}",
                f"Quote expires: {order.quote_expires_at.isoformat()}",
                "Send receipt with: /receipt <order_id> (attach photo/pdf)",
            ]
        )
    )


@router.message(Command("receipt"))
async def receipt(message: Message, command: CommandObject, services: AppServices, encryptor: Encryptor) -> None:
    if not command.args:
        await message.answer("Usage: /receipt <order_id> with attachment")
        return
    try:
        order_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid order id")
        return
    try:
        file_id = extract_secure_attachment_file_id(message)
    except ValidationError as exc:
        await message.answer(str(exc))
        return
    user = await services.register_or_get_user(message.from_user.id)
    try:
        order = await services.attach_receipt(user.id, order_id, encryptor.encrypt_text(file_id))
    except QuoteExpired:
        await message.answer("Quote expired. Order cancelled.")
        return
    await message.answer(f"Receipt attached. Order status: {order.status.value}")


@router.message(Command("orders"))
async def orders(message: Message, services: AppServices) -> None:
    user = await services.register_or_get_user(message.from_user.id)
    rows = await services.list_orders(user.id, limit=10)
    if not rows:
        await message.answer("No orders.")
        return
    lines = []
    for o in rows:
        lines.append(f"#{o['id']} {o['side'].value} {o['quantity_kg']}KG {o['status'].value}")
    await message.answer("\n".join(lines))


@router.message(Command("cancelorder"))
async def cancel_order(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /cancelorder <order_id>")
        return
    try:
        order_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid order id")
        return
    user = await services.register_or_get_user(message.from_user.id)
    c = await services.request_order_cancellation(user.id, order_id)
    await message.answer(f"Cancellation requested. Status: {c['status'].value}")


@router.message(Command("confirmcancel"))
async def confirm_cancel(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /confirmcancel <order_id>")
        return
    try:
        order_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid order id")
        return
    user = await services.register_or_get_user(message.from_user.id)
    c = await services.confirm_order_cancellation(user.id, order_id)
    await message.answer(f"Cancellation completed. Status: {c['status'].value}")


@router.message(Command("ticket"))
async def ticket(message: Message, command: CommandObject, services: AppServices) -> None:
    subject = (command.args or "").strip()
    if not subject:
        await message.answer("Usage: /ticket <subject>")
        return
    user = await services.register_or_get_user(message.from_user.id)
    t = await services.create_ticket(user.id, subject, TicketPriority.medium)
    await message.answer(f"Ticket #{t.id} created.")


@router.message(Command("deposit"))
async def deposit(message: Message, command: CommandObject, services: AppServices, encryptor: Encryptor) -> None:
    if not command.args:
        await message.answer("Usage: /deposit <amount_usd> with attachment")
        return
    amount = _parse_decimal(command.args)
    try:
        file_ids = [encryptor.encrypt_text(extract_secure_attachment_file_id(message))]
    except ValidationError as exc:
        await message.answer(str(exc))
        return
    user = await services.register_or_get_user(message.from_user.id)
    p = await services.create_payment_request(user.id, PaymentType.deposit, amount, file_ids, bank_account_id=None)
    await message.answer(f"Deposit request created: #{p.id} status={p.status.value}")


@router.message(Command("withdraw"))
async def withdraw(message: Message, command: CommandObject, services: AppServices, encryptor: Encryptor) -> None:
    if not command.args:
        await message.answer("Usage: /withdraw <amount_usd> with attachment")
        return
    amount = _parse_decimal(command.args)
    try:
        file_ids = [encryptor.encrypt_text(extract_secure_attachment_file_id(message))]
    except ValidationError as exc:
        await message.answer(str(exc))
        return
    user = await services.register_or_get_user(message.from_user.id)
    p = await services.create_payment_request(user.id, PaymentType.withdrawal, amount, file_ids, bank_account_id=None)
    await message.answer(f"Withdrawal request created: #{p.id} status={p.status.value}")
