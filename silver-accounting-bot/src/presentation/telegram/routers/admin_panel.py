from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from application.use_cases.services import AppServices
from core.di import Container
from domain.enums import KycStatus

router = Router(name="admin_panel")

_PAGE_SIZE = 10


def _back_btn(callback: str) -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton(text="\u2190 Back", callback_data=callback)]]


def _home_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="\U0001f4ca Statistics", callback_data="admin:stats"))
    builder.row(
        InlineKeyboardButton(text="\U0001f4b1 Trading", callback_data="admin:trading"),
        InlineKeyboardButton(text="\u2696\ufe0f Settlement", callback_data="admin:settlement"),
    )
    builder.row(
        InlineKeyboardButton(text="\u26a0\ufe0f Risk", callback_data="admin:risk"),
        InlineKeyboardButton(text="\U0001f464 Users", callback_data="admin:users"),
    )
    builder.row(
        InlineKeyboardButton(text="\U0001f4e2 Broadcast", callback_data="admin:broadcast"),
        InlineKeyboardButton(text="\U0001f4b0 Prices", callback_data="admin:prices"),
    )
    builder.row(
        InlineKeyboardButton(text="\u23f0 Scheduler", callback_data="admin:scheduler"),
        InlineKeyboardButton(text="\U0001f6a7 Maintenance", callback_data="admin:maintenance"),
    )
    builder.row(
        InlineKeyboardButton(text="\U0001f512 KYC Review", callback_data="admin:kyc"),
        InlineKeyboardButton(text="\U0001f465 Roles", callback_data="admin:roles"),
    )
    builder.row(
        InlineKeyboardButton(text="\U0001f4b5 Accounting", callback_data="admin:accounting"),
        InlineKeyboardButton(text="\U0001f50d Audit Log", callback_data="admin:audit_log"),
    )
    builder.row(
        InlineKeyboardButton(text="\U0001f9fe Payment Approvals", callback_data="admin:payments"),
        InlineKeyboardButton(text="\U0001f4be Backup/Restore", callback_data="admin:backup"),
    )
    return builder.as_markup()


@router.message(Command("admin"))
async def admin_home(message: Message, container: Container) -> None:
    user = await container.services.register_or_get_user(message.from_user.id)
    allowed = await container.services.user_has_permission(user.id, "configure_system")
    if not allowed:
        await message.answer("Forbidden")
        return
    await message.answer("Admin Panel \u2014 select a section:", reply_markup=_home_kb())


@router.callback_query(F.data == "admin:home")
async def admin_home_cb(callback: CallbackQuery, container: Container) -> None:
    await callback.message.edit_text("Admin Panel \u2014 select a section:", reply_markup=_home_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(callback: CallbackQuery, container: Container) -> None:
    services: AppServices = container.services
    report = await services.report_financial_dashboard(0, None, datetime.now(timezone.utc))
    lines = [
        "\U0001f4ca System Statistics",
        f"  Income: {report.get('income_usd', '-')}",
        f"  Expense: {report.get('expense_usd', '-')}",
        f"  Net Profit: {report.get('net_profit_usd', '-')}",
        f"  Assets: {report.get('assets_usd', '-')}",
        f"  Liabilities: {report.get('liabilities_usd', '-')}",
        f"  Equity: {report.get('equity_usd', '-')}",
    ]
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:prices")
async def admin_prices(callback: CallbackQuery, container: Container) -> None:
    try:
        p = await container.services.get_price()
        text = f"\U0001f4b0 Current Price\nBuy: {p.buy_price}\nSell: {p.sell_price}\nSpread: {p.spread}\nUpdated: {p.updated_at.isoformat()}"
    except Exception:
        text = "\U0001f4b0 Price not yet set"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:trading")
async def admin_trading(callback: CallbackQuery, container: Container) -> None:
    text = "\U0001f4b1 Trading\n\nCommands:\n/setprice <buy> <sell>\nOrders: /pendingcancels /approvecancel /rejectcancel"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:settlement")
async def admin_settlement(callback: CallbackQuery, container: Container) -> None:
    services: AppServices = container.services
    rows = await services.settlement_history(0, limit=5)
    lines = ["\u2696\ufe0f Settlement", "Recent:"]
    for r in rows:
        lines.append(f"  {r.batch_key}: {r.status.value} | pnl={r.net_pnl_usd}")
    lines.append("")
    lines.append("Commands: /settle /settlementhistory /settlementstatus /rollbacksettlement /replaysettlement")
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:risk")
async def admin_risk(callback: CallbackQuery, container: Container) -> None:
    services: AppServices = container.services
    cb_states = await services.circuit_breaker_all_states()
    dl_counts = await services.dead_letter_counts()
    lines = ["\u26a0\ufe0f Risk Dashboard"]
    for cb in cb_states:
        lines.append(f"  CB {cb['circuit_name']}: {cb['state']} (failures={cb['failure_count']})")
    for source, count in dl_counts.items():
        lines.append(f"  DLQ {source}: {count} entries")
    if not cb_states and not dl_counts:
        lines.append("  No active risk events")
    lines.append("")
    lines.append("Commands: /setrisk /pendingcancels")
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery, container: Container) -> None:
    text = "\U0001f464 User Management\n\nCommands:\n/grantrole <telegram_id> <role>\n/reviewkyc <telegram_id> <status>"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast(callback: CallbackQuery, container: Container) -> None:
    text = "\U0001f4e2 Broadcast\n\nCommands:\n/broadcast <message>\n/broadcastrole <role> <message>\n/broadcastlang <lang> <message>\n/broadcastkyc <status> <message>\n/broadcastactive <true|false> <message>\n/broadcastschedule <ISO-datetime> <message>\n/broadcastreply (reply to a msg)"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:scheduler")
async def admin_scheduler(callback: CallbackQuery, container: Container) -> None:
    job_lines = [
        "\u23f0 Scheduled Jobs",
        "  Daily Settlement: Mon-Fri 01:25 AT",
        "  Price Refresh: periodic",
        "  Notifications: every 15s",
        "  Margin Monitor: every 30s",
        "  Liquidations: every 30s",
        "  Stop Orders: every 15s",
        "  Expire Orders: every 60s",
        "  Cleanup: daily 03:00 UTC",
    ]
    await callback.message.edit_text("\n".join(job_lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:maintenance")
async def admin_maintenance(callback: CallbackQuery, container: Container) -> None:
    state = await container.services.get_maintenance_mode()
    text = (
        "\U0001f6a7 Maintenance Mode\n"
        f"Enabled: {state['enabled']}\n"
        f"Message: {state.get('message') or '-'}\n\n"
        "Commands: /maintenance /maintenanceon /maintenanceoff"
    )
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:kyc")
async def admin_kyc(callback: CallbackQuery, container: Container) -> None:
    text = "\U0001f512 KYC Review\n\nCommand: /reviewkyc <telegram_id> <approved|rejected|suspended|blocked> [note]"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:roles")
async def admin_roles(callback: CallbackQuery, container: Container) -> None:
    text = "\U0001f465 Role Management\n\nCommand: /grantrole <telegram_id> <role>"
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:accounting")
async def admin_accounting(callback: CallbackQuery, container: Container) -> None:
    services: AppServices = container.services
    report = await services.report_financial_dashboard(0, None, datetime.now(timezone.utc))
    lines = [
        "\U0001f4b5 Accounting Dashboard",
        "",
        f"Income: {report.get('income_usd', '-')}",
        f"Expense: {report.get('expense_usd', '-')}",
        f"Net Profit: {report.get('net_profit_usd', '-')}",
        f"Assets: {report.get('assets_usd', '-')}",
        f"Liabilities: {report.get('liabilities_usd', '-')}",
        f"Equity: {report.get('equity_usd', '-')}",
        f"Cash Flow: {report.get('net_cash_change_usd', '-')}",
        "",
        "Commands: /trialbalance /pnl /balancesheet /cashflow",
        "Export: /export <csv|xlsx|pdf> <trial|pnl|bs|cashflow>",
    ]
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:audit_log")
async def admin_audit_log(callback: CallbackQuery, container: Container) -> None:
    services: AppServices = container.services
    try:
        events = await services.list_audit_logs(0, limit=10)
        if not events:
            lines = ["\U0001f50d Audit Log", "  No events recorded"]
        else:
            lines = ["\U0001f50d Recent Audit Events"]
            for e in events:
                ts = e["created_at"].strftime("%Y-%m-%d %H:%M") if hasattr(e["created_at"], "strftime") else str(e["created_at"])
                lines.append(f"  {ts} | {e['event_type']} | {e.get('entity_type','-')}:{e.get('entity_id','-')}")
    except Exception:
        lines = ["\U0001f50d Audit Log", "  Error loading events"]
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:payments")
async def admin_payments(callback: CallbackQuery, container: Container) -> None:
    services: AppServices = container.services
    try:
        pending = await services.list_pending_payments(0, limit=10)
        if not pending:
            lines = ["\U0001f9fe Payment Approvals", "  No pending payments"]
        else:
            lines = ["\U0001f9fe Pending Payment Approvals"]
            for p in pending:
                t = p.get("payment_type", "?").value if hasattr(p.get("payment_type"), "value") else p.get("payment_type", "?")
                s = p.get("status", "?").value if hasattr(p.get("status"), "value") else p.get("status", "?")
                lines.append(f"  #{p['id']} {t} ${p['amount_usd']} [{s}]")
            lines.append("")
            lines.append("Commands: /approvepayment <id> /rejectpayment <id> <reason>")
    except Exception:
        lines = ["\U0001f9fe Payment Approvals", "  Error loading payments"]
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()


@router.callback_query(F.data == "admin:backup")
async def admin_backup(callback: CallbackQuery, container: Container) -> None:
    lines = [
        "\U0001f4be Backup/Restore",
        "",
        "Commands:",
        "  /backup - create a full DB snapshot",
        "  /restore - restore from last snapshot",
        "",
        "Note: Backup captures all tables. Restore wipes existing data.",
    ]
    await callback.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=_back_btn("admin:home")))
    await callback.answer()
