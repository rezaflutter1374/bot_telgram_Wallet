from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select

from core.settings import Settings
from infrastructure.db.base import Base
from infrastructure.db.models import JournalAccount, Notification, Order, Ticket, TicketMessage, User
from infrastructure.redis.cache import PriceCache
from infrastructure.redis.rate_limiter import RateLimiter
from infrastructure.db.session import Database, SqlAlchemyUnitOfWork
from infrastructure.repositories.runtime_state_repo import RedisRuntimeStateRepo
from infrastructure.repositories.sql_repos import (
    SqlAccountingRepo,
    SqlAuditRepo,
    SqlNotificationRepo,
    SqlOrderRepo,
    SqlPriceRepo,
    SqlRoleRepo,
    SqlTicketRepo,
    SqlUserRepo,
    SqlWalletRepo,
    _as_order_side,
    _as_order_status,
    _as_order_type,
    _as_ticket_priority,
    _as_ticket_status,
    ensure_utc,
    json_dumps,
)
from infrastructure.repositories.cached_price_repo import CachedPriceRepo
from domain.enums import JournalAccountType, KycStatus, NotificationStatus, OrderSide, OrderStatus, OrderType, TicketPriority, TicketStatus


@pytest.mark.asyncio
async def test_wallet_credit_freeze_unfreeze(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'w.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    users = SqlUserRepo(uow)
    wallets = SqlWalletRepo(uow)

    async with uow.transaction():
        u = await users.create_user(telegram_id=1, full_name=None, phone_number=None, kyc_status=KycStatus.pending)
        await wallets.ensure_wallet(u["id"])
        await wallets.credit_available(u["id"], Decimal("200"))
        await wallets.freeze(u["id"], Decimal("50"))
        await wallets.unfreeze(u["id"], Decimal("20"))
        w = await wallets.get_wallet(u["id"])

    assert w is not None
    assert w["available_balance_usd"] == Decimal("170")
    assert w["frozen_balance_usd"] == Decimal("30")

    await db.engine.dispose()


def test_settings_validation() -> None:
    valid = Settings(
        bot_token="123:abc",
        database_url="sqlite+aiosqlite:///tmp/test.db",
        redis_url="redis://localhost:6379/0",
        encryption_key="abcdefghijklmnopqrstuvwxyzABCDEFG1234567890=",
    )
    assert valid.log_level == "INFO"

    with pytest.raises(PydanticValidationError):
        Settings(
            bot_token="CHANGE_ME",
            database_url="sqlite+aiosqlite:///tmp/test.db",
            redis_url="redis://localhost:6379/0",
            encryption_key="abcdefghijklmnopqrstuvwxyzABCDEFG1234567890=",
        )

    with pytest.raises(PydanticValidationError):
        Settings(
            bot_token="123:abc",
            database_url="postgresql://bad",
            redis_url="redis://localhost:6379/0",
            encryption_key="abcdefghijklmnopqrstuvwxyzABCDEFG1234567890=",
        )


@pytest.mark.asyncio
async def test_rate_limiter_and_price_cache_runtime_settings() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.incr_calls = 0
            self.expire_calls: list[tuple[str, int]] = []
            self.values: dict[str, str] = {}

        async def incr(self, key: str, amount: int) -> int:
            self.incr_calls += 1
            value = int(self.values.get(key, "0")) + amount
            self.values[key] = str(value)
            return value

        async def expire(self, key: str, seconds: int) -> None:
            self.expire_calls.append((key, seconds))

        async def get(self, key: str) -> str | None:
            return self.values.get(key)

        async def set(self, key: str, value: str, ex: int) -> None:
            self.values[key] = value
            self.expire_calls.append((key, ex))

    redis = FakeRedis()
    limiter = RateLimiter(redis)  # type: ignore[arg-type]
    assert await limiter.allow("u:1", limit=2, window=timedelta(seconds=10)) is True
    assert await limiter.allow("u:1", limit=2, window=timedelta(seconds=10)) is True
    assert await limiter.allow("u:1", limit=2, window=timedelta(seconds=10)) is False
    assert redis.expire_calls[0] == ("rate:u:1", 10)

    cache = PriceCache(redis, ttl_seconds=9)  # type: ignore[arg-type]
    await cache.set(
        {
            "buy_price": Decimal("1"),
            "sell_price": Decimal("2"),
            "spread": Decimal("0"),
            "commission": Decimal("0"),
            "premium": Decimal("0"),
            "discount": Decimal("0"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    assert redis.expire_calls[-1] == ("prices:latest", 9)
    row = await cache.get()
    assert row is not None
    assert row["buy_price"] == Decimal("1")


@pytest.mark.asyncio
async def test_price_latest_and_orders_listing(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'p.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)
    users = SqlUserRepo(uow)
    wallets = SqlWalletRepo(uow)
    prices = SqlPriceRepo(uow)
    orders = SqlOrderRepo(uow)

    async with uow.transaction():
        await roles.ensure_defaults()
        u = await users.create_user(telegram_id=10, full_name=None, phone_number=None, kyc_status=KycStatus.pending)
        await wallets.ensure_wallet(u["id"])
        await prices.upsert(Decimal("10"), Decimal("11"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
        await prices.upsert(Decimal("12"), Decimal("13"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
        latest = await prices.get_latest()
        assert latest is not None
        assert latest["buy_price"] == Decimal("12")

        now = datetime.now(timezone.utc)
        o1 = await orders.create_order(
            user_id=u["id"],
            side=OrderSide.buy,
            order_type=OrderType.market,
            quantity_kg=Decimal("1"),
            quoted_price=Decimal("12"),
            quote_expires_at=now + timedelta(seconds=60),
        )
        await orders.attach_receipt(o1["id"], "enc:file", OrderStatus.awaiting_review)
        await orders.set_status(o1["id"], OrderStatus.completed)

        await orders.create_order(
            user_id=u["id"],
            side=OrderSide.sell,
            order_type=OrderType.limit,
            quantity_kg=Decimal("0.5"),
            quoted_price=Decimal("13"),
            quote_expires_at=now + timedelta(seconds=60),
        )

        lst = await orders.list_for_user(u["id"], limit=10)
        assert len(lst) == 2

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_ticket_repo(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    users = SqlUserRepo(uow)
    tickets = SqlTicketRepo(uow)

    async with uow.transaction():
        u = await users.create_user(telegram_id=20, full_name=None, phone_number=None, kyc_status=KycStatus.pending)
        t = await tickets.create_ticket(u["id"], "Test", TicketPriority.high)
        await tickets.add_message(t["id"], author_user_id=u["id"], author_role="customer", message="Hello", attachment_file_ids_enc=["enc:a"])
        await tickets.set_status(t["id"], TicketStatus.closed)
        rows = await tickets.list_tickets(user_id=u["id"], status=TicketStatus.closed, query="Tes", limit=10)
        assert len(rows) == 1

    async with db.session() as session:
        ticket = await session.get(Ticket, t["id"])
        assert ticket is not None
        assert ticket.status == "closed"
        msgs = (await session.scalars(select(TicketMessage).where(TicketMessage.ticket_id == t["id"]))).all()
        assert len(msgs) == 1

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_role_permissions(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'r.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)
    users = SqlUserRepo(uow)

    async with uow.transaction():
        await roles.ensure_defaults()
        u = await users.create_user(telegram_id=30, full_name=None, phone_number=None, kyc_status=KycStatus.pending)
        await roles.grant_role(u["id"], "admin")
        assert await roles.user_has_permission(u["id"], "manage_prices") is True
        assert await roles.user_has_permission(u["id"], "non_existing_perm") is False
        rs = await roles.get_user_roles(u["id"])
        assert "admin" in rs

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_user_repo_filters_and_language_updates(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'users.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    roles = SqlRoleRepo(uow)
    users = SqlUserRepo(uow)
    wallets = SqlWalletRepo(uow)
    orders = SqlOrderRepo(uow)

    async with uow.transaction():
        await roles.ensure_defaults()
        user_a = await users.create_user(telegram_id=101, full_name="A", phone_number=None, kyc_status=KycStatus.approved, language_code="en")
        user_b = await users.create_user(telegram_id=102, full_name="B", phone_number=None, kyc_status=KycStatus.pending, language_code="fa")
        await roles.grant_role(user_a["id"], "admin")
        await roles.grant_role(user_b["id"], "support")
        await wallets.ensure_wallet(user_a["id"])
        await wallets.ensure_wallet(user_b["id"])
        await orders.create_order(
            user_id=user_a["id"],
            side=OrderSide.buy,
            order_type=OrderType.market,
            quantity_kg=Decimal("1"),
            quoted_price=Decimal("12"),
            quote_expires_at=datetime.now(timezone.utc) + timedelta(seconds=60),
        )
        updated = await users.set_language_code(user_b["id"], "en")
        assert updated["language_code"] == "en"
        admins = await users.list_users(role="admin", limit=10)
        assert [row["id"] for row in admins] == [user_a["id"]]
        approved = await users.list_users(kyc_status=KycStatus.approved, language_code="en", limit=10)
        assert [row["id"] for row in approved] == [user_a["id"]]
        trading_active = await users.list_users(trading_active=True, limit=10)
        assert [row["id"] for row in trading_active] == [user_a["id"]]
        inactive = await users.list_users(trading_active=False, limit=10)
        assert [row["id"] for row in inactive] == [user_b["id"]]

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_runtime_state_repo() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        async def get(self, key: str) -> str | None:
            return self.values.get(key)

        async def set(self, key: str, value: str) -> None:
            self.values[key] = value

    repo = RedisRuntimeStateRepo(FakeRedis())  # type: ignore[arg-type]
    initial = await repo.get_maintenance_mode()
    assert initial["enabled"] is False
    updated = await repo.set_maintenance_mode(True, "Maintenance window", 55)
    assert updated["enabled"] is True
    assert updated["message"] == "Maintenance window"
    loaded = await repo.get_maintenance_mode()
    assert loaded["enabled"] is True
    assert loaded["actor_user_id"] == 55


def test_repo_helper_converters() -> None:
    assert _as_order_side(OrderSide.buy) == OrderSide.buy
    assert _as_order_type(OrderType.market) == OrderType.market
    assert _as_order_status(OrderStatus.pending) == OrderStatus.pending
    assert _as_ticket_priority(TicketPriority.high) == TicketPriority.high
    assert _as_ticket_status(TicketStatus.open) == TicketStatus.open
    dt = datetime(2020, 1, 1, tzinfo=timezone.utc)
    assert ensure_utc(dt) == dt
    assert json_dumps({"a": Decimal("1.2"), "b": dt, "c": OrderStatus.pending})  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_repo_error_paths(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'e.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    prices = SqlPriceRepo(uow)
    orders = SqlOrderRepo(uow)
    wallets = SqlWalletRepo(uow)
    users = SqlUserRepo(uow)
    tickets = SqlTicketRepo(uow)

    async with uow.transaction():
        assert await prices.get_latest() is None
        assert await orders.get(999) is None
        assert await tickets.get(999) is None
        u = await users.create_user(telegram_id=40, full_name=None, phone_number=None, kyc_status=KycStatus.pending)
        await wallets.ensure_wallet(u["id"])
        await wallets.credit_available(u["id"], Decimal("10"))
        await wallets.debit_available(u["id"], Decimal("5"))

    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_notification_repo_mark_and_errors(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'n.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    users = SqlUserRepo(uow)
    roles = SqlRoleRepo(uow)
    notif = SqlNotificationRepo(uow)
    audit = SqlAuditRepo(uow)
    acc = SqlAccountingRepo(uow)

    async with uow.transaction():
        await roles.ensure_defaults()
        await acc.ensure_default_chart()
        u = await users.create_user(telegram_id=77, full_name=None, phone_number=None, kyc_status=KycStatus.pending)
        created = await notif.enqueue(u["id"], "k", {"x": "y"})
        pending = await notif.list_pending(limit=10)
        assert any(x["id"] == created["id"] for x in pending)
        await notif.mark(created["id"], NotificationStatus.failed, error="e")
        await audit.add(u["id"], "evt", "x", "1", {"a": 1})

    with pytest.raises(RuntimeError):
        async with uow.transaction():
            await notif.mark(999, NotificationStatus.sent)

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_accounting_parent_missing(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    acc = SqlAccountingRepo(uow)
    async with uow.transaction():
        await acc.ensure_default_chart()
        with pytest.raises(RuntimeError):
            await acc.create_account("9999", "X", JournalAccountType.asset, parent_code="does-not-exist")
        assert await acc.get_account_by_code("does-not-exist") is None

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_cached_price_repo(tmp_path) -> None:
    class FakeCache:
        def __init__(self) -> None:
            self.value: dict | None = None

        async def get(self) -> dict | None:
            return self.value

        async def set(self, price_row: dict) -> None:
            self.value = price_row

    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    inner = SqlPriceRepo(uow)
    cache = FakeCache()
    repo = CachedPriceRepo(inner=inner, cache=cache)

    async with uow.transaction():
        assert await repo.get_latest() is None
        row = await repo.upsert(Decimal("1"), Decimal("2"), Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0"))
        assert cache.value is not None
        assert row["buy_price"] == Decimal("1")
        cache.value = {"buy_price": Decimal("9"), "sell_price": Decimal("9"), "spread": Decimal("0"), "commission": Decimal("0"), "premium": Decimal("0"), "discount": Decimal("0"), "updated_at": datetime.now(timezone.utc)}
        cached2 = await repo.get_latest()
        assert cached2 is not None
        assert cached2["buy_price"] == Decimal("9")
        cache.value = None
        cached = await repo.get_latest()
        assert cached is not None
        assert cached["sell_price"] == Decimal("2")

    await db.engine.dispose()
