from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from application.ports.repositories.uow import UnitOfWork
from application.use_cases.services import AppServices
from domain.enums import OrderSide, OrderStatus, OrderTimeInForce, OrderType
from domain.services.margin import MarginCalculator
from infrastructure.db.base import Base
from infrastructure.db.models import (
    JournalAccount,
    Role,
    User,
    UserRole,
    Wallet,
    Position,
    Price,
    Order,
    MarginAccount,
)
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


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_trading.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    return db


@pytest.fixture
async def setup_db(db):
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with db.session() as session:
        async with session.begin():
            session.add(User(id=1, telegram_id=111, verification_docs_file_ids_enc="[]", kyc_status="approved"))
            session.add(User(id=2, telegram_id=222, verification_docs_file_ids_enc="[]", kyc_status="approved"))
            session.add(Role(id=1, name="admin"))
            session.add(UserRole(user_id=1, role_id=1))
            session.add(Wallet(user_id=1, available_balance_usd=Decimal("10000")))
            session.add(Wallet(user_id=2, available_balance_usd=Decimal("10000")))
            session.add(Position(user_id=1, net_kg=Decimal("0")))
            session.add(Position(user_id=2, net_kg=Decimal("0")))
            session.add(MarginAccount(user_id=1, maintenance_margin_ratio=Decimal("1"), margin_ratio=Decimal("999999")))
            session.add(MarginAccount(user_id=2, maintenance_margin_ratio=Decimal("1"), margin_ratio=Decimal("999999")))
            session.add(
                Price(
                    source="manual_admin",
                    buy_price=Decimal("1000"),
                    sell_price=Decimal("1000"),
                )
            )
            session.add(JournalAccount(code="1000", name="Cash", account_type="asset"))
            session.add(JournalAccount(code="2000", name="Customer", account_type="liability"))
            session.add(JournalAccount(code="4000", name="Income", account_type="income"))
            session.add(JournalAccount(code="5000", name="Expense", account_type="expense"))
    yield db


@pytest.mark.asyncio
async def test_stop_order_triggering(setup_db, db) -> None:
    uow = SqlAlchemyUnitOfWork(db)
    orders = SqlOrderRepo(uow)
    wallets = SqlWalletRepo(uow)
    positions = SqlPositionRepo(uow)
    prices = SqlPriceRepo(uow)
    margin = MarginCalculator(Decimal("100"), Decimal("1"))

    async with uow.transaction():
        order = await orders.create_order(
            user_id=1,
            side=OrderSide.buy,
            order_type=OrderType.stop,
            time_in_force=OrderTimeInForce.gtc,
            quantity_kg=Decimal("1"),
            quoted_price=Decimal("900"),
            limit_price=None,
            stop_price=Decimal("950"),
            reserved_balance_usd=Decimal("0"),
            reserved_margin_usd=Decimal("0"),
            post_only=False,
            reduce_only=False,
            client_order_id=None,
            idempotency_key=None,
            quote_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        assert order["is_triggered"] is False

    async with uow.transaction():
        candidates = await orders.list_triggerable_orders(Decimal("1000"), limit=100)

    matching = [c for c in candidates if c["id"] == order["id"]]
    assert len(matching) == 1

    async with uow.transaction():
        updated = await orders.mark_triggered(order["id"])
    assert updated["is_triggered"] is True


@pytest.mark.asyncio
async def test_stop_order_not_triggered_below_stop(setup_db, db) -> None:
    uow = SqlAlchemyUnitOfWork(db)
    orders = SqlOrderRepo(uow)

    async with uow.transaction():
        order = await orders.create_order(
            user_id=1,
            side=OrderSide.buy,
            order_type=OrderType.stop,
            time_in_force=OrderTimeInForce.gtc,
            quantity_kg=Decimal("1"),
            quoted_price=Decimal("900"),
            limit_price=None,
            stop_price=Decimal("950"),
            reserved_balance_usd=Decimal("0"),
            reserved_margin_usd=Decimal("0"),
            post_only=False,
            reduce_only=False,
            client_order_id=None,
            idempotency_key=None,
            quote_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    async with uow.transaction():
        candidates = await orders.list_triggerable_orders(Decimal("900"), limit=100)
    matching = [c for c in candidates if c["id"] == order["id"]]
    assert len(matching) == 0


@pytest.mark.asyncio
async def test_expire_stale_orders(setup_db, db) -> None:
    uow = SqlAlchemyUnitOfWork(db)
    orders = SqlOrderRepo(uow)

    async with uow.transaction():
        order = await orders.create_order(
            user_id=1,
            side=OrderSide.buy,
            order_type=OrderType.limit,
            time_in_force=OrderTimeInForce.gtc,
            quantity_kg=Decimal("1"),
            quoted_price=Decimal("900"),
            limit_price=Decimal("900"),
            stop_price=None,
            reserved_balance_usd=Decimal("0"),
            reserved_margin_usd=Decimal("0"),
            post_only=False,
            reduce_only=False,
            client_order_id=None,
            idempotency_key=None,
            quote_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    async with uow.transaction():
        candidates = await orders.list_expired_orders(datetime.now(timezone.utc), limit=100)
    matching = [c for c in candidates if c["id"] == order["id"]]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_trigger_stop_orders_integration(setup_db, db) -> None:
    uow = SqlAlchemyUnitOfWork(db)

    async with uow.transaction():
        orders = SqlOrderRepo(uow)
        await orders.create_order(
            user_id=1,
            side=OrderSide.buy,
            order_type=OrderType.stop,
            time_in_force=OrderTimeInForce.gtc,
            quantity_kg=Decimal("1"),
            quoted_price=Decimal("900"),
            limit_price=None,
            stop_price=Decimal("950"),
            reserved_balance_usd=Decimal("0"),
            reserved_margin_usd=Decimal("0"),
            post_only=False,
            reduce_only=False,
            client_order_id=None,
            idempotency_key=None,
            quote_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )

    services = _make_services(db)
    result = await services.trigger_stop_orders()
    assert result["triggered"] == 1


@pytest.mark.asyncio
async def test_expire_stale_orders_integration(setup_db, db) -> None:
    uow = SqlAlchemyUnitOfWork(db)

    async with uow.transaction():
        orders = SqlOrderRepo(uow)
        await orders.create_order(
            user_id=1,
            side=OrderSide.sell,
            order_type=OrderType.limit,
            time_in_force=OrderTimeInForce.gtc,
            quantity_kg=Decimal("1"),
            quoted_price=Decimal("1000"),
            limit_price=Decimal("1000"),
            stop_price=None,
            reserved_balance_usd=Decimal("0"),
            reserved_margin_usd=Decimal("0"),
            post_only=False,
            reduce_only=False,
            client_order_id=None,
            idempotency_key=None,
            quote_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

    services = _make_services(db)
    result = await services.expire_stale_orders()
    assert result["expired"] == 1


def _make_services(db: Database) -> AppServices:
    uow = SqlAlchemyUnitOfWork(db)
    return AppServices(
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
