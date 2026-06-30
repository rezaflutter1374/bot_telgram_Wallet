from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from application.use_cases.services import AppServices
from application.errors import Forbidden, NotFound, QuoteExpired, ValidationError
from domain.enums import KycStatus, OrderSide, OrderType, SettlementMode, SettlementStatus, TicketPriority, TicketStatus
from domain.services.margin import MarginCalculator
from infrastructure.db.base import Base
from infrastructure.db.models import Notification, Order, Role, Ticket, TicketMessage, UserRole
from infrastructure.db.session import Database, SqlAlchemyUnitOfWork
from infrastructure.repositories.sql_repos import (
    SqlAccountingRepo,
    SqlAuditRepo,
    SqlBackupRepo,
    SqlNotificationRepo,
    SqlOrderRepo,
    SqlPaymentRepo,
    SqlPositionRepo,
    SqlPriceRepo,
    SqlRiskRepo,
    SqlRoleRepo,
    SqlTicketRepo,
    SqlUserRepo,
    SqlWalletRepo,
)


@pytest.mark.asyncio
async def test_register_set_price_order_flow(tmp_path) -> None:
    db_path = tmp_path / "app.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    users = SqlUserRepo(uow)
    wallets = SqlWalletRepo(uow)
    roles = SqlRoleRepo(uow)
    prices = SqlPriceRepo(uow)
    payments = SqlPaymentRepo(uow)
    accounting = SqlAccountingRepo(uow)
    notifications = SqlNotificationRepo(uow)
    audit = SqlAuditRepo(uow)
    risk = SqlRiskRepo(uow)
    orders = SqlOrderRepo(uow)
    positions = SqlPositionRepo(uow)
    tickets = SqlTicketRepo(uow)
    backup = SqlBackupRepo(uow)
    services = AppServices(
        uow=uow,
        users=users,
        wallets=wallets,
        roles=roles,
        prices=prices,
        payments=payments,
        accounting=accounting,
        notifications=notifications,
        audit=audit,
        risk=risk,
        orders=orders,
        positions=positions,
        tickets=tickets,
        backup=backup,
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )

    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()
    user = await services.register_or_get_user(telegram_id=1000)
    admin = await services.register_or_get_user(telegram_id=2000)

    async with uow.transaction():
        await roles.grant_role(admin.id, "admin")

    p = await services.set_price(admin.id, Decimal("10"), Decimal("11"))
    assert p.buy_price == Decimal("10")
    assert p.sell_price == Decimal("11")

    async with uow.transaction():
        await wallets.credit_available(user.id, Decimal("100"))

    order = await services.create_order(
        user_id=user.id,
        side=OrderSide.buy,
        order_type=OrderType.market,
        quantity_kg=Decimal("1"),
        limit_price=None,
    )
    assert order.status.value in {"awaiting_payment", "pending"}

    order2 = await services.attach_receipt(user.id, order.id, receipt_file_id_enc="enc:file")
    assert order2.status.value == "awaiting_review"

    accountant = await services.register_or_get_user(telegram_id=3000)
    async with uow.transaction():
        await roles.grant_role(accountant.id, "accountant")

    order3 = await services.approve_order(accountant.id, order.id, approve=True)
    assert order3.status.value == "completed"

    async with db.session() as session:
        row = await session.scalar(select(Order).where(Order.id == order.id))
        assert row is not None
        assert row.status == "completed"

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_rbac_default_roles_present(tmp_path) -> None:
    db_path = tmp_path / "rbac.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)

    async with uow.transaction():
        await roles.ensure_defaults()

    async with db.session() as session:
        names = (await session.scalars(select(Role.name))).all()
        assert "admin" in names
        assert "super_admin" in names

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_kyc_and_ticket_flow(tmp_path) -> None:
    db_path = tmp_path / "flow.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    services = AppServices(
        uow=uow,
        users=SqlUserRepo(uow),
        wallets=SqlWalletRepo(uow),
        roles=SqlRoleRepo(uow),
        prices=SqlPriceRepo(uow),
        payments=SqlPaymentRepo(uow),
        accounting=SqlAccountingRepo(uow),
        notifications=SqlNotificationRepo(uow),
        audit=SqlAuditRepo(uow),
        risk=SqlRiskRepo(uow),
        orders=SqlOrderRepo(uow),
        positions=SqlPositionRepo(uow),
        tickets=SqlTicketRepo(uow),
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )

    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()
    user = await services.register_or_get_user(telegram_id=4000)
    await services.submit_kyc(
        user_id=user.id,
        full_name="Test User",
        phone_number="+93700000000",
        national_id_enc="enc:nid",
        passport_file_id_enc="enc:pass",
        selfie_file_id_enc="enc:selfie",
        verification_docs_file_ids_enc=["enc:doc1"],
    )

    t = await services.create_ticket(user.id, "Need help", priority=TicketPriority.medium)
    assert t.id > 0

    support = await services.register_or_get_user(telegram_id=5000)
    async with uow.transaction():
        await services._roles.grant_role(support.id, "support")

    await services.reply_ticket(support.id, t.id, "We received your ticket", [])
    await services.add_internal_ticket_note(support.id, t.id, "Escalated internally")
    await services.close_ticket(support.id, t.id)
    await services.reopen_ticket(user.id, t.id)
    listing = await services.list_tickets(user.id, status=TicketStatus.open, query="Need", limit=10)
    assert any(row["id"] == t.id for row in listing)

    async with db.session() as session:
        ticket = await session.get(Ticket, t.id)
        assert ticket is not None
        assert ticket.status == "open"
        messages = (await session.scalars(select(TicketMessage).where(TicketMessage.ticket_id == t.id))).all()
        assert len(messages) >= 3
        assert any(msg.author_role == "internal_note" for msg in messages)

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_quote_expired(tmp_path) -> None:
    db_path = tmp_path / "quote.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    services = AppServices(
        uow=uow,
        users=SqlUserRepo(uow),
        wallets=SqlWalletRepo(uow),
        roles=SqlRoleRepo(uow),
        prices=SqlPriceRepo(uow),
        payments=SqlPaymentRepo(uow),
        accounting=SqlAccountingRepo(uow),
        notifications=SqlNotificationRepo(uow),
        audit=SqlAuditRepo(uow),
        risk=SqlRiskRepo(uow),
        orders=SqlOrderRepo(uow),
        positions=SqlPositionRepo(uow),
        tickets=SqlTicketRepo(uow),
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )
    await services.ensure_rbac_defaults()
    user = await services.register_or_get_user(telegram_id=6000)
    admin = await services.register_or_get_user(telegram_id=6001)
    async with uow.transaction():
        await services._roles.grant_role(admin.id, "admin")
    await services.set_price(admin.id, Decimal("10"), Decimal("10"))
    async with uow.transaction():
        await services._wallets.credit_available(user.id, Decimal("100"))
    order = await services.create_order(
        user_id=user.id,
        side=OrderSide.buy,
        order_type=OrderType.market,
        quantity_kg=Decimal("1"),
        limit_price=None,
    )
    async with db.session() as session:
        async with session.begin():
            row = await session.get(Order, order.id)
            assert row is not None
            row.quote_expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)

    with pytest.raises(QuoteExpired):
        await services.attach_receipt(user.id, order.id, "enc:file")

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_service_validation_and_forbidden_paths(tmp_path) -> None:
    db_path = tmp_path / "paths.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)
    services = AppServices(
        uow=uow,
        users=SqlUserRepo(uow),
        wallets=SqlWalletRepo(uow),
        roles=roles,
        prices=SqlPriceRepo(uow),
        payments=SqlPaymentRepo(uow),
        accounting=SqlAccountingRepo(uow),
        notifications=SqlNotificationRepo(uow),
        audit=SqlAuditRepo(uow),
        risk=SqlRiskRepo(uow),
        orders=SqlOrderRepo(uow),
        positions=SqlPositionRepo(uow),
        tickets=SqlTicketRepo(uow),
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )

    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()
    u = await services.register_or_get_user(telegram_id=7000)
    await services.ensure_super_admin(u.id, telegram_id=7000, super_admin_ids=set())
    with pytest.raises(NotFound):
        await services.get_user_by_telegram_id(999999)

    with pytest.raises(ValidationError):
        await services.submit_kyc(u.id, "", "+1", "x", "x", "x", [])
    with pytest.raises(ValidationError):
        await services.submit_kyc(u.id, "A", "", "x", "x", "x", [])
    with pytest.raises(NotFound):
        await services.get_price()

    admin = await services.register_or_get_user(telegram_id=7001)
    with pytest.raises(Forbidden):
        await services.set_price(admin.id, Decimal("1"), Decimal("2"))
    with pytest.raises(Forbidden):
        await services.list_pending_payments(admin.id, limit=1)

    async with uow.transaction():
        await roles.grant_role(admin.id, "admin")
    await services.set_price(admin.id, Decimal("10"), Decimal("10"))

    with pytest.raises(Forbidden):
        await services.review_kyc(u.id, u.id, KycStatus.approved, note=None)

    with pytest.raises(ValidationError):
        await services.create_order(u.id, OrderSide.buy, OrderType.market, Decimal("0"), None)
    with pytest.raises(ValidationError):
        await services.create_order(u.id, OrderSide.buy, OrderType.limit, Decimal("1"), None)

    with pytest.raises(ValidationError):
        await services.create_ticket(u.id, "   ", TicketPriority.low)
    with pytest.raises(ValidationError):
        await services.reply_ticket(u.id, ticket_id=999, message="", attachment_file_ids_enc=[])

    with pytest.raises(NotFound):
        await services.close_ticket(u.id, ticket_id=999)

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_maintenance_and_broadcast_services(tmp_path) -> None:
    class FakeRuntimeStateRepo:
        def __init__(self) -> None:
            self.state = {"enabled": False, "message": None, "actor_user_id": None, "updated_at": None}

        async def get_maintenance_mode(self) -> dict:
            return dict(self.state)

        async def set_maintenance_mode(self, enabled: bool, message: str | None, actor_user_id: int | None) -> dict:
            self.state = {
                "enabled": enabled,
                "message": message,
                "actor_user_id": actor_user_id,
                "updated_at": "2026-06-30T00:00:00+00:00",
            }
            return dict(self.state)

    db_path = tmp_path / "runtime.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)
    services = AppServices(
        uow=uow,
        users=SqlUserRepo(uow),
        wallets=SqlWalletRepo(uow),
        roles=roles,
        prices=SqlPriceRepo(uow),
        payments=SqlPaymentRepo(uow),
        accounting=SqlAccountingRepo(uow),
        notifications=SqlNotificationRepo(uow),
        audit=SqlAuditRepo(uow),
        risk=SqlRiskRepo(uow),
        orders=SqlOrderRepo(uow),
        positions=SqlPositionRepo(uow),
        tickets=SqlTicketRepo(uow),
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
        runtime_state=FakeRuntimeStateRepo(),
    )

    await services.ensure_rbac_defaults()
    admin = await services.register_or_get_user(telegram_id=7000, language_code="en")
    user = await services.register_or_get_user(telegram_id=7001, language_code="fa")

    async with uow.transaction():
        await roles.grant_role(admin.id, "admin")

    state = await services.set_maintenance_mode(admin.id, True, "Scheduled maintenance")
    assert state["enabled"] is True
    assert await services.can_access_during_maintenance(admin.id) is True
    assert await services.can_access_during_maintenance(user.id) is False

    result = await services.broadcast_message(
        admin.id,
        message_type="text",
        text="System announcement",
        language_code="fa",
        silent=True,
    )
    assert result["recipients"] == 1

    async with db.session() as session:
        rows = (await session.scalars(select(Notification).order_by(Notification.id.asc()))).all()
        assert len(rows) == 1
        assert rows[0].kind == "broadcast.telegram"
        assert "\"silent\": true" in rows[0].payload.lower()

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_settlement_service_methods(tmp_path) -> None:
    class FakeSettlementEngine:
        async def execute(self, **kwargs) -> dict:
            return {
                "status": "completed",
                "idempotent": False,
                "summary": {
                    "settlement_id": 11,
                    "batch_key": kwargs.get("idempotency_key") or "manual:batch",
                    "mode": kwargs.get("mode", "manual"),
                    "status": "completed",
                    "target_date": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "price_usd": Decimal("10"),
                    "price_source": "manual_admin",
                    "affected_users": 1,
                    "net_pnl_usd": Decimal("2"),
                    "report_json": "{}",
                    "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                    "completed_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
                },
            }

        async def rollback(self, **kwargs) -> dict:
            return {
                "status": "completed",
                "idempotent": False,
                "summary": {
                    "settlement_id": 12,
                    "batch_key": "rollback:11",
                    "mode": "rollback",
                    "status": "completed",
                    "target_date": datetime(2026, 7, 2, tzinfo=timezone.utc),
                    "price_usd": Decimal("10"),
                    "price_source": "manual_admin",
                    "affected_users": 1,
                    "net_pnl_usd": Decimal("-2"),
                    "report_json": "{}",
                    "created_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
                    "completed_at": datetime(2026, 7, 2, tzinfo=timezone.utc),
                },
            }

        async def replay(self, **kwargs) -> dict:
            return {
                "status": "completed",
                "idempotent": True,
                "summary": {
                    "settlement_id": 13,
                    "batch_key": "replay:11",
                    "mode": "replay",
                    "status": "completed",
                    "target_date": datetime(2026, 7, 3, tzinfo=timezone.utc),
                    "price_usd": Decimal("10"),
                    "price_source": "manual_admin",
                    "affected_users": 1,
                    "net_pnl_usd": Decimal("2"),
                    "report_json": "{}",
                    "created_at": datetime(2026, 7, 3, tzinfo=timezone.utc),
                    "completed_at": datetime(2026, 7, 3, tzinfo=timezone.utc),
                    "replay_of_settlement_id": 11,
                    "rollback_of_settlement_id": None,
                },
            }

        async def list_history(self, *, limit: int = 20) -> list[dict]:
            return [
                {
                    "settlement_id": 13,
                    "batch_key": "replay:11",
                    "mode": "replay",
                    "status": "completed",
                    "target_date": datetime(2026, 7, 3, tzinfo=timezone.utc),
                    "price_usd": Decimal("10"),
                    "price_source": "manual_admin",
                    "affected_users": 1,
                    "net_pnl_usd": Decimal("2"),
                    "report_json": "{}",
                    "created_at": datetime(2026, 7, 3, tzinfo=timezone.utc),
                    "completed_at": datetime(2026, 7, 3, tzinfo=timezone.utc),
                    "replay_of_settlement_id": 11,
                    "rollback_of_settlement_id": None,
                }
            ]

        async def get_status(self, *, batch_key: str) -> dict | None:
            if batch_key == "missing":
                return None
            return {
                "settlement_id": 13,
                "batch_key": batch_key,
                "mode": "replay",
                "status": "completed",
                "target_date": datetime(2026, 7, 3, tzinfo=timezone.utc),
                "price_usd": Decimal("10"),
                "price_source": "manual_admin",
                "affected_users": 1,
                "net_pnl_usd": Decimal("2"),
                "report_json": "{}",
                "created_at": datetime(2026, 7, 3, tzinfo=timezone.utc),
                "completed_at": datetime(2026, 7, 3, tzinfo=timezone.utc),
                "last_checkpoint": "completed",
                "error_message": None,
                "replay_of_settlement_id": 11,
                "rollback_of_settlement_id": None,
            }

    db_path = tmp_path / "settlement_services.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)
    services = AppServices(
        uow=uow,
        users=SqlUserRepo(uow),
        wallets=SqlWalletRepo(uow),
        roles=roles,
        prices=SqlPriceRepo(uow),
        payments=SqlPaymentRepo(uow),
        accounting=SqlAccountingRepo(uow),
        notifications=SqlNotificationRepo(uow),
        audit=SqlAuditRepo(uow),
        risk=SqlRiskRepo(uow),
        orders=SqlOrderRepo(uow),
        positions=SqlPositionRepo(uow),
        tickets=SqlTicketRepo(uow),
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
        settlement_engine=FakeSettlementEngine(),
    )
    await services.ensure_rbac_defaults()
    admin = await services.register_or_get_user(telegram_id=7100)
    user = await services.register_or_get_user(telegram_id=7101)
    async with uow.transaction():
        await roles.grant_role(admin.id, "accountant")

    result = await services.run_settlement(admin.id, mode="manual", idempotency_key="manual:batch")
    assert result.status == SettlementStatus.completed
    assert result.summary.mode == SettlementMode.manual

    rollback = await services.rollback_settlement(admin.id, settlement_id=11, reason="fix")
    assert rollback.summary.mode == SettlementMode.rollback

    replay = await services.replay_settlement(admin.id, settlement_id=11)
    assert replay.idempotent is True
    assert replay.summary.mode == SettlementMode.replay

    history = await services.settlement_history(admin.id, limit=10)
    assert len(history) == 1
    assert history[0].mode == SettlementMode.replay

    status = await services.settlement_status(admin.id, batch_key="replay:11")
    assert status.status == SettlementStatus.completed
    assert status.last_checkpoint == "completed"

    with pytest.raises(NotFound):
        await services.settlement_status(admin.id, batch_key="missing")

    with pytest.raises(Forbidden):
        await services.run_settlement(user.id)
    with pytest.raises(Forbidden):
        await services.rollback_settlement(user.id, settlement_id=11)

    services_no_engine = AppServices(
        uow=uow,
        users=SqlUserRepo(uow),
        wallets=SqlWalletRepo(uow),
        roles=roles,
        prices=SqlPriceRepo(uow),
        payments=SqlPaymentRepo(uow),
        accounting=SqlAccountingRepo(uow),
        notifications=SqlNotificationRepo(uow),
        audit=SqlAuditRepo(uow),
        risk=SqlRiskRepo(uow),
        orders=SqlOrderRepo(uow),
        positions=SqlPositionRepo(uow),
        tickets=SqlTicketRepo(uow),
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )
    await services_no_engine.ensure_rbac_defaults()
    with pytest.raises(ValidationError):
        await services_no_engine.run_settlement(admin.id)

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_more_service_branches(tmp_path) -> None:
    db_path = tmp_path / "branches.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    users = SqlUserRepo(uow)
    wallets = SqlWalletRepo(uow)
    roles = SqlRoleRepo(uow)
    prices = SqlPriceRepo(uow)
    payments = SqlPaymentRepo(uow)
    accounting = SqlAccountingRepo(uow)
    notifications = SqlNotificationRepo(uow)
    audit = SqlAuditRepo(uow)
    risk = SqlRiskRepo(uow)
    orders = SqlOrderRepo(uow)
    positions = SqlPositionRepo(uow)
    tickets = SqlTicketRepo(uow)
    services = AppServices(
        uow=uow,
        users=users,
        wallets=wallets,
        roles=roles,
        prices=prices,
        payments=payments,
        accounting=accounting,
        notifications=notifications,
        audit=audit,
        risk=risk,
        orders=orders,
        positions=positions,
        tickets=tickets,
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )

    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    u1 = await services.register_or_get_user(telegram_id=8000)
    u1_again = await services.register_or_get_user(telegram_id=8000)
    assert u1_again.id == u1.id

    await services.ensure_super_admin(u1.id, telegram_id=8000, super_admin_ids={8000})
    async with uow.transaction():
        r = await roles.get_user_roles(u1.id)
    assert "super_admin" in r

    with pytest.raises(NotFound):
        await services.submit_kyc(999, "A", "B", "x", "x", "x", [])

    admin = await services.register_or_get_user(telegram_id=8001)
    async with uow.transaction():
        await roles.grant_role(admin.id, "admin")
        await roles.grant_role(admin.id, "accountant")
        await wallets.credit_available(u1.id, Decimal("100"))
    await services.set_price(admin.id, Decimal("10"), Decimal("10"))

    order = await services.create_order(u1.id, OrderSide.buy, OrderType.market, Decimal("1"), None)

    other = await services.register_or_get_user(telegram_id=8002)
    with pytest.raises(Forbidden):
        await services.attach_receipt(other.id, order.id, "enc:file")

    async with db.session() as session:
        async with session.begin():
            row = await session.get(Order, order.id)
            assert row is not None
            row.status = "completed"
    with pytest.raises(ValidationError):
        await services.attach_receipt(u1.id, order.id, "enc:file")

    with pytest.raises(Forbidden):
        await services.approve_order(other.id, order.id, approve=True)

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_order_cancellation_flow(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'cancel.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)
    services = AppServices(
        uow=uow,
        users=SqlUserRepo(uow),
        wallets=SqlWalletRepo(uow),
        roles=roles,
        prices=SqlPriceRepo(uow),
        payments=SqlPaymentRepo(uow),
        accounting=SqlAccountingRepo(uow),
        notifications=SqlNotificationRepo(uow),
        audit=SqlAuditRepo(uow),
        risk=SqlRiskRepo(uow),
        orders=SqlOrderRepo(uow),
        positions=SqlPositionRepo(uow),
        tickets=SqlTicketRepo(uow),
        backup=SqlBackupRepo(uow),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )
    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    user = await services.register_or_get_user(telegram_id=12000)
    admin = await services.register_or_get_user(telegram_id=12001)
    async with uow.transaction():
        await roles.grant_role(admin.id, "admin")
        await services._wallets.credit_available(user.id, Decimal("100"))
        await roles.grant_role(admin.id, "admin")

    await services.set_price(admin.id, Decimal("10"), Decimal("11"))
    order = await services.create_order(user.id, OrderSide.buy, OrderType.market, Decimal("1"), None)

    c1 = await services.request_order_cancellation(user.id, order.id)
    assert c1["order_id"] == order.id
    assert c1["status"].value == "requested"

    with pytest.raises(Forbidden):
        await services.list_pending_cancellations(user.id, limit=1)

    pending = await services.list_pending_cancellations(admin.id, limit=20)
    assert any(x["order_id"] == order.id for x in pending)

    rejected = await services.review_order_cancellation(admin.id, order.id, approve=False)
    assert rejected["status"].value == "rejected"
    with pytest.raises(ValidationError):
        await services.confirm_order_cancellation(user.id, order.id)

    await services.request_order_cancellation(user.id, order.id)
    c2 = await services.review_order_cancellation(admin.id, order.id, approve=True)
    assert c2["status"].value == "admin_approved"

    c3 = await services.confirm_order_cancellation(user.id, order.id)
    assert c3["status"].value == "completed"

    async with db.session() as session:
        row = await session.get(Order, order.id)
        assert row is not None
        assert row.status == "cancelled"

    blocked_order = await services.create_order(user.id, OrderSide.buy, OrderType.market, Decimal("1"), None)
    async with db.session() as session:
        async with session.begin():
            r = await session.get(Order, blocked_order.id)
            assert r is not None
            r.status = "completed"
    with pytest.raises(ValidationError):
        await services.request_order_cancellation(user.id, blocked_order.id)

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_report_exports_and_backup_restore(tmp_path) -> None:
    db1 = Database(f"sqlite+aiosqlite:///{tmp_path / 'b1.db'}")
    async with db1.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow1 = SqlAlchemyUnitOfWork(db1)
    roles1 = SqlRoleRepo(uow1)
    services1 = AppServices(
        uow=uow1,
        users=SqlUserRepo(uow1),
        wallets=SqlWalletRepo(uow1),
        roles=roles1,
        prices=SqlPriceRepo(uow1),
        payments=SqlPaymentRepo(uow1),
        accounting=SqlAccountingRepo(uow1),
        notifications=SqlNotificationRepo(uow1),
        audit=SqlAuditRepo(uow1),
        risk=SqlRiskRepo(uow1),
        orders=SqlOrderRepo(uow1),
        positions=SqlPositionRepo(uow1),
        tickets=SqlTicketRepo(uow1),
        backup=SqlBackupRepo(uow1),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )
    await services1.ensure_rbac_defaults()
    await services1.ensure_accounting_defaults()

    actor = await services1.register_or_get_user(telegram_id=13000)
    user = await services1.register_or_get_user(telegram_id=13001)
    async with uow1.transaction():
        await roles1.grant_role(actor.id, "super_admin")
        await services1._wallets.credit_available(user.id, Decimal("100"))
        await roles1.grant_role(actor.id, "admin")

    await services1.set_price(actor.id, Decimal("10"), Decimal("11"))
    await services1.create_ticket(user.id, "Hello", TicketPriority.low)

    csv_name, _, csv_payload = await services1.export_trial_balance(actor.id, "csv", None, datetime.now(timezone.utc))
    assert csv_name.endswith(".csv")
    assert b"code" in csv_payload

    xlsx_name, _, xlsx_payload = await services1.export_trial_balance(actor.id, "xlsx", None, datetime.now(timezone.utc))
    assert xlsx_name.endswith(".xlsx")
    wb = load_workbook(io.BytesIO(xlsx_payload))
    assert wb.active["A1"].value == "code"

    pdf_name, _, pdf_payload = await services1.export_trial_balance(actor.id, "pdf", None, datetime.now(timezone.utc))
    assert pdf_name.endswith(".pdf")
    assert pdf_payload[:4] == b"%PDF"

    with pytest.raises(ValidationError):
        await services1.export_trial_balance(actor.id, "badfmt", None, datetime.now(timezone.utc))

    pnl_name, _, pnl_payload = await services1.export_profit_and_loss(actor.id, "csv", None, datetime.now(timezone.utc))
    assert pnl_name.endswith(".csv")
    assert b"net_profit_usd" in pnl_payload

    bs_name, _, bs_payload = await services1.export_balance_sheet(actor.id, "csv", datetime.now(timezone.utc))
    assert bs_name.endswith(".csv")
    assert b"assets_usd" in bs_payload

    cf_name, _, cf_payload = await services1.export_cash_flow(actor.id, "csv", None, datetime.now(timezone.utc))
    assert cf_name.endswith(".csv")
    assert b"net_cash_change_usd" in cf_payload

    with pytest.raises(Forbidden):
        await services1.backup_snapshot(user.id)

    snapshot = await services1.backup_snapshot(actor.id)

    db2 = Database(f"sqlite+aiosqlite:///{tmp_path / 'b2.db'}")
    async with db2.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow2 = SqlAlchemyUnitOfWork(db2)
    roles2 = SqlRoleRepo(uow2)
    services2 = AppServices(
        uow=uow2,
        users=SqlUserRepo(uow2),
        wallets=SqlWalletRepo(uow2),
        roles=roles2,
        prices=SqlPriceRepo(uow2),
        payments=SqlPaymentRepo(uow2),
        accounting=SqlAccountingRepo(uow2),
        notifications=SqlNotificationRepo(uow2),
        audit=SqlAuditRepo(uow2),
        risk=SqlRiskRepo(uow2),
        orders=SqlOrderRepo(uow2),
        positions=SqlPositionRepo(uow2),
        tickets=SqlTicketRepo(uow2),
        backup=SqlBackupRepo(uow2),
        margin_calculator=MarginCalculator(Decimal("100"), Decimal("1")),
    )
    await services2.ensure_rbac_defaults()
    await services2.ensure_accounting_defaults()
    actor2 = await services2.register_or_get_user(telegram_id=14000)
    async with uow2.transaction():
        await roles2.grant_role(actor2.id, "super_admin")

    with pytest.raises(RuntimeError):
        await services2.restore_snapshot(actor2.id, {"tables": "not-a-dict"})

    await services2.restore_snapshot(actor2.id, snapshot)

    restored = await services2.get_user_by_telegram_id(13001)
    assert restored.telegram_id == 13001

    db3 = Database(f"sqlite+aiosqlite:///{tmp_path / 'b3.db'}")
    async with db3.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    uow3 = SqlAlchemyUnitOfWork(db3)
    backup3 = SqlBackupRepo(uow3)
    async with uow3.transaction():
        await backup3.restore_snapshot(snapshot, wipe_existing=False)
    await db3.engine.dispose()

    await db1.engine.dispose()
    await db2.engine.dispose()
