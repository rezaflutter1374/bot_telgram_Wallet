from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

from application.errors import ValidationError
from application.use_cases.services import AppServices
from core.security import Encryptor

router = Router(name="accountant")


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        raise ValidationError("Invalid number")


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValidationError("Invalid datetime. Use ISO-8601 with timezone offset.") from exc
    if parsed.tzinfo is None:
        raise ValidationError("Datetime must include timezone offset")
    return parsed


@router.message(Command("approveorder"))
async def approve_order(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /approveorder <order_id>")
        return
    try:
        order_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid order id")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    order = await services.approve_order(actor.id, order_id, approve=True)
    await message.answer(f"Approved. Order status: {order.status.value}")


@router.message(Command("rejectorder"))
async def reject_order(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /rejectorder <order_id>")
        return
    try:
        order_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid order id")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    order = await services.approve_order(actor.id, order_id, approve=False)
    await message.answer(f"Rejected. Order status: {order.status.value}")


@router.message(Command("approvepayment"))
async def approve_payment(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /approvepayment <payment_id> [note]")
        return
    parts = command.args.split(maxsplit=1)
    try:
        payment_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid payment id")
        return
    note = parts[1] if len(parts) == 2 else None
    actor = await services.register_or_get_user(message.from_user.id)
    p = await services.review_payment_request(actor.id, payment_id, approve=True, note=note)
    await message.answer(f"Payment approved. Status: {p.status.value}")


@router.message(Command("rejectpayment"))
async def reject_payment(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /rejectpayment <payment_id> [note]")
        return
    parts = command.args.split(maxsplit=1)
    try:
        payment_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid payment id")
        return
    note = parts[1] if len(parts) == 2 else None
    actor = await services.register_or_get_user(message.from_user.id)
    p = await services.review_payment_request(actor.id, payment_id, approve=False, note=note)
    await message.answer(f"Payment rejected. Status: {p.status.value}")


@router.message(Command("pendingpayments"))
async def pending_payments(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    rows = await services.list_pending_payments(actor.id, limit=20)
    if not rows:
        await message.answer("No pending payments.")
        return
    lines = []
    for r in rows:
        lines.append(f"#{r['id']} user={r['user_id']} {r['payment_type'].value} {r['amount_usd']} {r['status'].value}")
    await message.answer("\n".join(lines))


@router.message(Command("trialbalance"))
async def trial_balance(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    rows = await services.report_trial_balance(actor.id, None, datetime.now(timezone.utc))
    preview = []
    for r in rows[:30]:
        preview.append(f"{r['code']} {r['name']} debit={r['debit_usd']} credit={r['credit_usd']} bal={r['balance_usd']}")
    await message.answer("\n".join(preview) if preview else "No data.")


@router.message(Command("exporttrialbalance"))
async def export_trial_balance(message: Message, command: CommandObject, services: AppServices) -> None:
    fmt = (command.args or "csv").strip().lower()
    actor = await services.register_or_get_user(message.from_user.id)
    filename, _, payload = await services.export_trial_balance(actor.id, fmt, None, datetime.now(timezone.utc))
    await message.answer_document(BufferedInputFile(payload, filename=filename))


@router.message(Command("pnl"))
async def pnl(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_profit_and_loss(actor.id, None, datetime.now(timezone.utc))
    await message.answer(f"Income: {r['income_usd']}\nExpense: {r['expense_usd']}\nNet: {r['net_profit_usd']}")


@router.message(Command("exportpnl"))
async def export_pnl(message: Message, command: CommandObject, services: AppServices) -> None:
    fmt = (command.args or "csv").strip().lower()
    actor = await services.register_or_get_user(message.from_user.id)
    filename, _, payload = await services.export_profit_and_loss(actor.id, fmt, None, datetime.now(timezone.utc))
    await message.answer_document(BufferedInputFile(payload, filename=filename))


@router.message(Command("balancesheet"))
async def balance_sheet(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_balance_sheet(actor.id, datetime.now(timezone.utc))
    await message.answer(f"Assets: {r['assets_usd']}\nLiabilities: {r['liabilities_usd']}\nEquity: {r['equity_usd']}")


@router.message(Command("exportbalancesheet"))
async def export_balance_sheet(message: Message, command: CommandObject, services: AppServices) -> None:
    fmt = (command.args or "csv").strip().lower()
    actor = await services.register_or_get_user(message.from_user.id)
    filename, _, payload = await services.export_balance_sheet(actor.id, fmt, datetime.now(timezone.utc))
    await message.answer_document(BufferedInputFile(payload, filename=filename))


@router.message(Command("cashflow"))
async def cash_flow(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_cash_flow(actor.id, None, datetime.now(timezone.utc))
    await message.answer(f"Net cash change: {r['net_cash_change_usd']}")


@router.message(Command("financialdashboard"))
async def financial_dashboard(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_financial_dashboard(actor.id, None, datetime.now(timezone.utc))
    await message.answer(
        "\n".join(
            [
                f"Trial Balance Rows: {r['trial_balance_rows']}",
                f"Income: {r['income_usd']}",
                f"Expense: {r['expense_usd']}",
                f"Net Profit: {r['net_profit_usd']}",
                f"Assets: {r['assets_usd']}",
                f"Liabilities: {r['liabilities_usd']}",
                f"Equity: {r['equity_usd']}",
                f"Net Cash Change: {r['net_cash_change_usd']}",
            ]
        )
    )


@router.message(Command("dailyreport"))
async def daily_report(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_period_summary(actor.id, "daily", datetime.now(timezone.utc))
    await message.answer(f"Daily report\nNet Profit: {r['net_profit_usd']}\nNet Cash Change: {r['net_cash_change_usd']}")


@router.message(Command("weeklyreport"))
async def weekly_report(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_period_summary(actor.id, "weekly", datetime.now(timezone.utc))
    await message.answer(f"Weekly report\nNet Profit: {r['net_profit_usd']}\nNet Cash Change: {r['net_cash_change_usd']}")


@router.message(Command("monthlyreport"))
async def monthly_report(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_period_summary(actor.id, "monthly", datetime.now(timezone.utc))
    await message.answer(f"Monthly report\nNet Profit: {r['net_profit_usd']}\nNet Cash Change: {r['net_cash_change_usd']}")


@router.message(Command("yearlyreport"))
async def yearly_report(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    r = await services.report_period_summary(actor.id, "yearly", datetime.now(timezone.utc))
    await message.answer(f"Yearly report\nNet Profit: {r['net_profit_usd']}\nNet Cash Change: {r['net_cash_change_usd']}")


@router.message(Command("settle"))
async def run_settlement(message: Message, command: CommandObject, services: AppServices) -> None:
    settlement_at = None
    if command.args:
        try:
            settlement_at = _parse_iso_datetime(command.args)
        except ValidationError as exc:
            await message.answer(str(exc))
            return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.run_settlement(actor.id, settlement_at=settlement_at, mode="manual")
    await message.answer(
        "\n".join(
            [
                f"Settlement status: {result.status.value}",
                f"Batch: {result.summary.batch_key}",
                f"Settlement ID: {result.summary.settlement_id}",
                f"Price: {result.summary.price_usd}",
                f"Affected users: {result.summary.affected_users}",
                f"Net PnL: {result.summary.net_pnl_usd}",
            ]
        )
    )


@router.message(Command("settlementhistory"))
async def settlement_history(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    rows = await services.settlement_history(actor.id, limit=10)
    if not rows:
        await message.answer("No settlement history.")
        return
    await message.answer(
        "\n".join(
            [
                f"{row.batch_key} | {row.mode.value} | {row.status.value} | settlement={row.settlement_id} | pnl={row.net_pnl_usd}"
                for row in rows
            ]
        )
    )


@router.message(Command("settlementstatus"))
async def settlement_status(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /settlementstatus <batch_key>")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    status = await services.settlement_status(actor.id, batch_key=command.args.strip())
    await message.answer(
        "\n".join(
            [
                f"Batch: {status.batch_key}",
                f"Mode: {status.mode.value}",
                f"Status: {status.status.value}",
                f"Checkpoint: {status.last_checkpoint or '-'}",
                f"Error: {status.error_message or '-'}",
            ]
        )
    )


@router.message(Command("rollbacksettlement"))
async def rollback_settlement(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /rollbacksettlement <settlement_id> [reason]")
        return
    parts = command.args.split(maxsplit=1)
    try:
        settlement_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid settlement id")
        return
    reason = parts[1] if len(parts) == 2 else None
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.rollback_settlement(actor.id, settlement_id=settlement_id, reason=reason)
    await message.answer(f"Rollback status: {result.status.value}\nBatch: {result.summary.batch_key}")


@router.message(Command("replaysettlement"))
async def replay_settlement(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /replaysettlement <settlement_id>")
        return
    try:
        settlement_id = int(command.args.strip())
    except ValueError:
        await message.answer("Invalid settlement id")
        return
    actor = await services.register_or_get_user(message.from_user.id, language_code=message.from_user.language_code)
    result = await services.replay_settlement(actor.id, settlement_id=settlement_id)
    await message.answer(f"Replay status: {result.status.value}\nBatch: {result.summary.batch_key}")


@router.message(Command("manualjournal"))
async def manual_journal(message: Message, command: CommandObject, services: AppServices) -> None:
    if not command.args:
        await message.answer("Usage: /manualjournal <debit_code> <credit_code> <amount_usd> <description>")
        return
    parts = command.args.split(maxsplit=3)
    if len(parts) != 4:
        await message.answer("Usage: /manualjournal <debit_code> <credit_code> <amount_usd> <description>")
        return
    try:
        amount = _parse_decimal(parts[2])
    except ValidationError:
        await message.answer("Invalid amount")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    row = await services.post_manual_transfer(actor.id, parts[0], parts[1], amount, parts[3])
    await message.answer(f"Manual journal posted: #{row['id']}")


@router.message(Command("addbankaccount"))
async def add_bank_account(message: Message, command: CommandObject, services: AppServices, encryptor: Encryptor) -> None:
    if not command.args:
        await message.answer("Usage: /addbankaccount <name>|<account_number>")
        return
    parts = [part.strip() for part in command.args.split("|", maxsplit=1)]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        await message.answer("Usage: /addbankaccount <name>|<account_number>")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    row = await services.create_bank_account(actor.id, parts[0], encryptor.encrypt_text(parts[1]))
    await message.answer(f"Bank account created: #{row['id']} {row['name']}")


@router.message(Command("listbankaccounts"))
async def list_bank_accounts(message: Message, services: AppServices) -> None:
    actor = await services.register_or_get_user(message.from_user.id)
    rows = await services.list_bank_accounts(actor.id, only_active=True)
    if not rows:
        await message.answer("No bank accounts.")
        return
    await message.answer("\n".join([f"#{row['id']} {row['name']} active={row['is_active']}" for row in rows]))


@router.message(Command("addcard"))
async def add_card(message: Message, command: CommandObject, services: AppServices, encryptor: Encryptor) -> None:
    if not command.args:
        await message.answer("Usage: /addcard <bank_account_id> <label>|<card_number>")
        return
    parts = command.args.split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /addcard <bank_account_id> <label>|<card_number>")
        return
    try:
        bank_account_id = int(parts[0])
    except ValueError:
        await message.answer("Invalid bank account id")
        return
    details = [part.strip() for part in parts[1].split("|", maxsplit=1)]
    if len(details) != 2 or not details[0] or not details[1]:
        await message.answer("Usage: /addcard <bank_account_id> <label>|<card_number>")
        return
    actor = await services.register_or_get_user(message.from_user.id)
    row = await services.create_payment_card(actor.id, bank_account_id, details[0], encryptor.encrypt_text(details[1]))
    await message.answer(f"Payment card created: #{row['id']} {row['label']}")


@router.message(Command("listcards"))
async def list_cards(message: Message, command: CommandObject, services: AppServices) -> None:
    bank_account_id = None
    if command.args:
        try:
            bank_account_id = int(command.args.strip())
        except ValueError:
            await message.answer("Invalid bank account id")
            return
    actor = await services.register_or_get_user(message.from_user.id)
    rows = await services.list_payment_cards(actor.id, bank_account_id=bank_account_id, only_active=True)
    if not rows:
        await message.answer("No cards.")
        return
    await message.answer("\n".join([f"#{row['id']} bank={row['bank_account_id']} {row['label']} active={row['is_active']}" for row in rows]))


@router.message(Command("exportcashflow"))
async def export_cash_flow(message: Message, command: CommandObject, services: AppServices) -> None:
    fmt = (command.args or "csv").strip().lower()
    actor = await services.register_or_get_user(message.from_user.id)
    filename, _, payload = await services.export_cash_flow(actor.id, fmt, None, datetime.now(timezone.utc))
    await message.answer_document(BufferedInputFile(payload, filename=filename))
