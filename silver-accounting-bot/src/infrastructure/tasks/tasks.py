from __future__ import annotations

import logging
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from aiogram import Bot
from arq.connections import RedisSettings
from sqlalchemy import select

from core.di import build_container
from core.logging import configure_logging
from core.settings import Settings
from domain.enums import LiquidationStatus, MarginCallStatus, NotificationStatus
from domain.services.margin import MarginCalculator
from infrastructure.db.models import JournalAccount, JournalEntry, JournalLine, LiquidationEvent, MarginCall, Notification, Position, Price, User, Wallet
from infrastructure.settlement.engine import run_daily_settlement

logger = logging.getLogger("worker")


async def startup(ctx: dict) -> None:
    settings = Settings()
    configure_logging(settings.log_level)
    container = build_container(settings)
    await container.services.ensure_rbac_defaults()
    await container.services.ensure_accounting_defaults()
    ctx["container"] = container
    ctx["bot"] = Bot(token=settings.bot_token)


async def shutdown(ctx: dict) -> None:
    container = ctx.get("container")
    if container is not None:
        await container.redis.close()
        await container.db.engine.dispose()
    bot = ctx.get("bot")
    if bot is not None:
        await bot.session.close()


async def daily_settlement(ctx: dict) -> dict:
    container = ctx["container"]
    return await container.settlement_engine.execute(mode="daily")


async def refresh_prices(ctx: dict) -> dict:
    container = ctx["container"]
    return await container.price_refresh.refresh_once()


async def send_notifications(ctx: dict) -> dict:
    container = ctx["container"]
    bot: Bot = ctx["bot"]
    settings: Settings = container.settings
    sent = 0
    failed = 0
    async with container.db.session() as session:
        async with session.begin():
            rows = (await session.execute(
                select(Notification, User.telegram_id)
                .join(User, User.id == Notification.user_id)
                .where(Notification.status == NotificationStatus.pending.value)
                .order_by(Notification.created_at.asc())
                .limit(settings.notification_batch_size)
            )).all()
            for notif, telegram_id in rows:
                payload = _load_notification_payload(notif.payload)
                scheduled_at = payload.get("scheduled_at")
                if scheduled_at:
                    try:
                        if datetime.fromisoformat(str(scheduled_at)) > datetime.now(timezone.utc):
                            continue
                    except ValueError:
                        pass
                try:
                    await _deliver_notification(bot, int(telegram_id), notif.kind, payload)
                    notif.status = NotificationStatus.sent.value
                    notif.sent_at = datetime.now(timezone.utc)
                    sent += 1
                except Exception as e:
                    attempts = int(payload.get("attempts", 0)) + 1
                    max_attempts = int(payload.get("max_attempts", 1))
                    payload["attempts"] = attempts
                    payload["last_error"] = str(e)
                    notif.payload = json.dumps(payload, ensure_ascii=False)
                    if attempts < max_attempts:
                        notif.status = NotificationStatus.pending.value
                    else:
                        notif.status = NotificationStatus.failed.value
                        failed += 1
            return {"sent": sent, "failed": failed}


def _load_notification_payload(payload_json: str) -> dict:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return {"raw": payload_json}
    if isinstance(payload, dict) and "payload" in payload and "kind" in payload:
        nested = payload.get("payload")
        if isinstance(nested, dict):
            nested["error"] = payload.get("error")
            return nested
    return payload if isinstance(payload, dict) else {"raw": payload_json}


def _render_notification(kind: str, payload: dict) -> str:
    if "raw" in payload:
        return f"{kind}\n{payload['raw']}"

    if kind == "settlement.completed":
        return (
            "Daily settlement completed\n"
            f"Date: {payload.get('settlement_date')}\n"
            f"Price: {payload.get('price_usd')}\n"
            f"PnL: {payload.get('pnl_usd')}"
        )
    if kind == "settlement.report_ready":
        return (
            "Settlement report ready\n"
            f"Date: {payload.get('settlement_date')}\n"
            f"Price: {payload.get('price_usd')}\n"
            f"Affected users: {payload.get('affected_users')}\n"
            f"Net PnL: {payload.get('net_pnl_usd')}"
        )
    if kind == "margin_call":
        return f"Margin call\nRatio: {payload.get('margin_ratio')}\nThreshold: {payload.get('threshold')}"
    if kind == "liquidation":
        return f"Liquidation executed\nPrice: {payload.get('price')}\nPnL: {payload.get('pnl')}"
    if kind == "price.refresh_failed":
        return f"Price refresh failed\nDetails: {json.dumps(payload, ensure_ascii=False)}"
    if kind == "settlement.rollback_completed":
        return (
            "Settlement rollback completed\n"
            f"Rollback of: {payload.get('rollback_of_settlement_id')}\n"
            f"Affected users: {payload.get('affected_users')}\n"
            f"Net PnL: {payload.get('net_pnl_usd')}"
        )
    return f"{kind}\n{json.dumps(payload, ensure_ascii=False)}"


async def _deliver_notification(bot: Bot, chat_id: int, kind: str, payload: dict) -> None:
    if kind == "broadcast.telegram":
        message_type = str(payload.get("message_type", "text")).lower()
        silent = bool(payload.get("silent", False))
        if message_type == "text":
            await bot.send_message(chat_id=chat_id, text=str(payload.get("text") or ""), disable_notification=silent)
            return
        if message_type == "photo":
            await bot.send_photo(
                chat_id=chat_id,
                photo=str(payload.get("file_id")),
                caption=payload.get("caption"),
                disable_notification=silent,
            )
            return
        if message_type == "document":
            await bot.send_document(
                chat_id=chat_id,
                document=str(payload.get("file_id")),
                caption=payload.get("caption"),
                disable_notification=silent,
            )
            return
        if message_type == "video":
            await bot.send_video(
                chat_id=chat_id,
                video=str(payload.get("file_id")),
                caption=payload.get("caption"),
                disable_notification=silent,
            )
            return
        if message_type == "forward":
            await bot.forward_message(
                chat_id=chat_id,
                from_chat_id=int(payload["forward_from_chat_id"]),
                message_id=int(payload["forward_message_id"]),
                disable_notification=silent,
            )
            return
        raise RuntimeError(f"Unsupported broadcast message type: {message_type}")

    text = _render_notification(kind, payload)
    await bot.send_message(chat_id=chat_id, text=text)


async def monitor_margin_calls(ctx: dict) -> dict:
    container = ctx["container"]
    settings: Settings = container.settings
    created = 0
    async with container.db.session() as session:
        async with session.begin():
            price = await session.scalar(
                select(Price)
                .where(Price.is_verified.is_(True), Price.is_stale.is_(False))
                .order_by(Price.updated_at.desc())
            )
            if price is None:
                return {"created": 0, "reason": "no_price"}
            current = Decimal(price.sell_price)
            rows = (
                await session.execute(
                    select(Wallet, Position)
                    .join(Position, Position.user_id == Wallet.user_id)
                    .limit(settings.wallet_scan_batch_size)
                )
            ).all()
            calc = MarginCalculator(Decimal("100"), settings.margin_call_threshold_ratio, warning_ratio_threshold=settings.margin_warning_ratio, liquidation_ratio_threshold=settings.margin_liquidation_critical_ratio)
            for w, pos in rows:
                net_kg = Decimal(pos.net_kg)
                exposure = abs(net_kg)
                if exposure == 0:
                    continue
                floating = (current - Decimal(pos.avg_price_usd)) * net_kg
                snap = calc.snapshot(
                    available_balance_usd=Decimal(w.available_balance_usd),
                    frozen_balance_usd=Decimal(w.frozen_balance_usd),
                    floating_pnl_usd=floating,
                    exposure_kg=exposure,
                )
                if snap.margin_ratio < settings.margin_call_threshold_ratio:
                    existing = await session.scalar(
                        select(MarginCall).where(MarginCall.user_id == w.user_id, MarginCall.status == MarginCallStatus.open.value)
                    )
                    if existing is None:
                        session.add(
                            MarginCall(
                                user_id=w.user_id,
                                margin_ratio=snap.margin_ratio,
                                threshold=settings.margin_call_threshold_ratio,
                                status=MarginCallStatus.open.value,
                                created_at=datetime.now(timezone.utc),
                            )
                        )
                        session.add(
                            Notification(
                                user_id=w.user_id,
                                channel="telegram",
                                kind="margin_call",
                                payload=f'{{"margin_ratio":"{snap.margin_ratio}","threshold":"{settings.margin_call_threshold_ratio}"}}',
                                status=NotificationStatus.pending.value,
                                created_at=datetime.now(timezone.utc),
                            )
                        )
                        created += 1
    return {"created": created}


async def monitor_liquidations(ctx: dict) -> dict:
    container = ctx["container"]
    settings: Settings = container.settings
    liquidated = 0
    critical = settings.margin_liquidation_critical_ratio
    async with container.db.session() as session:
        async with session.begin():
            price = await session.scalar(
                select(Price)
                .where(Price.is_verified.is_(True), Price.is_stale.is_(False))
                .order_by(Price.updated_at.desc())
            )
            if price is None:
                return {"liquidated": 0, "reason": "no_price"}
            current = Decimal(price.sell_price)
            rows = (
                await session.execute(
                    select(Wallet, Position)
                    .join(Position, Position.user_id == Wallet.user_id)
                    .limit(settings.wallet_scan_batch_size)
                )
            ).all()
            calc = MarginCalculator(Decimal("100"), settings.margin_call_threshold_ratio, warning_ratio_threshold=settings.margin_warning_ratio, liquidation_ratio_threshold=critical)
            customer = await session.scalar(select(JournalAccount).where(JournalAccount.code == "2000"))
            income = await session.scalar(select(JournalAccount).where(JournalAccount.code == "4000"))
            expense = await session.scalar(select(JournalAccount).where(JournalAccount.code == "5000"))
            for w, pos in rows:
                net_kg = Decimal(pos.net_kg)
                exposure = abs(net_kg)
                if exposure == 0:
                    continue
                floating = (current - Decimal(pos.avg_price_usd)) * net_kg
                snap = calc.snapshot(
                    available_balance_usd=Decimal(w.available_balance_usd),
                    frozen_balance_usd=Decimal(w.frozen_balance_usd),
                    floating_pnl_usd=floating,
                    exposure_kg=exposure,
                )
                if snap.margin_ratio <= critical:
                    if customer is None or income is None or expense is None:
                        raise RuntimeError("Accounting chart not ready")
                    session.add(
                        LiquidationEvent(
                            user_id=w.user_id,
                            margin_ratio=snap.margin_ratio,
                            critical_level=critical,
                            close_price_usd=current,
                            status=LiquidationStatus.completed.value,
                            created_at=datetime.now(timezone.utc),
                            completed_at=datetime.now(timezone.utc),
                        )
                    )
                    realized = (current - Decimal(pos.avg_price_usd)) * net_kg
                    w.available_balance_usd = Decimal(w.available_balance_usd) + realized
                    w.updated_at = datetime.now(timezone.utc)
                    amt = abs(realized).quantize(Decimal("0.01"))
                    if amt > 0:
                        entry = JournalEntry(
                            reference=f"liquidation:{w.user_id}:{datetime.now(timezone.utc).date().isoformat()}",
                            description="Auto liquidation PnL",
                            posted_at=datetime.now(timezone.utc),
                            created_by_user_id=None,
                            created_at=datetime.now(timezone.utc),
                        )
                        session.add(entry)
                        await session.flush()
                        if realized > 0:
                            session.add(JournalLine(entry_id=entry.id, account_id=expense.id, user_id=None, debit_usd=amt, credit_usd=Decimal("0"), created_at=datetime.now(timezone.utc)))
                            session.add(JournalLine(entry_id=entry.id, account_id=customer.id, user_id=w.user_id, debit_usd=Decimal("0"), credit_usd=amt, created_at=datetime.now(timezone.utc)))
                        else:
                            session.add(JournalLine(entry_id=entry.id, account_id=customer.id, user_id=w.user_id, debit_usd=amt, credit_usd=Decimal("0"), created_at=datetime.now(timezone.utc)))
                            session.add(JournalLine(entry_id=entry.id, account_id=income.id, user_id=None, debit_usd=Decimal("0"), credit_usd=amt, created_at=datetime.now(timezone.utc)))
                    pos.net_kg = Decimal("0")
                    pos.avg_price_usd = Decimal("0")
                    pos.updated_at = datetime.now(timezone.utc)
                    session.add(
                        Notification(
                            user_id=w.user_id,
                            channel="telegram",
                            kind="liquidation",
                            payload=f'{{"price":"{current}","pnl":"{realized}"}}',
                            status=NotificationStatus.pending.value,
                            created_at=datetime.now(timezone.utc),
                        )
                    )
                    liquidated += 1
    return {"liquidated": liquidated}


async def trigger_stop_orders_task(ctx: dict) -> dict:
    container = ctx["container"]
    return await container.services.trigger_stop_orders()


async def expire_stale_orders_task(ctx: dict) -> dict:
    container = ctx["container"]
    return await container.services.expire_stale_orders()


async def cleanup_old_data_task(ctx: dict) -> dict:
    container = ctx["container"]
    settings: Settings = container.settings
    retention_days = settings.retention_days_settlement
    async with container.db.session() as session:
        async with session.begin():
            cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
            deleted = 0
            from infrastructure.db.models import SettlementReconciliation, SettlementReport, Settlement, Notification, AuditEvent
            for table in [SettlementReconciliation, SettlementReport, Settlement, Notification, AuditEvent]:
                stmt = select(table).where(table.created_at < cutoff).limit(settings.cleanup_batch_size)
                rows = (await session.execute(stmt)).scalars().all()
                for row in rows:
                    await session.delete(row)
                    deleted += 1
            await session.commit()
            return {"deleted": deleted}


class WorkerSettings:
    functions = [
        daily_settlement,
        refresh_prices,
        send_notifications,
        monitor_margin_calls,
        monitor_liquidations,
        trigger_stop_orders_task,
        expire_stale_orders_task,
        cleanup_old_data_task,
    ]
    on_startup = startup
    on_shutdown = shutdown

    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
