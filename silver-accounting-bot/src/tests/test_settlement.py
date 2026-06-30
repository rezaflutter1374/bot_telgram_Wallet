from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from infrastructure.db.base import Base
from infrastructure.db.models import (
    JournalAccount,
    Notification,
    Position,
    Price,
    Role,
    RolePermission,
    Settlement,
    SettlementBatch,
    SettlementCheckpoint,
    SettlementReconciliation,
    SettlementReport,
    User,
    UserRole,
    Wallet,
)
from infrastructure.db.session import Database
from infrastructure.settlement.engine import run_daily_settlement
from infrastructure.settlement.service import SettlementEngineService


@pytest.mark.asyncio
async def test_daily_settlement_updates_wallet(tmp_path) -> None:
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")

    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db.session() as session:
        async with session.begin():
            session.add(User(id=1, telegram_id=111, full_name=None, phone_number=None, verification_docs_file_ids_enc="[]", kyc_status="pending"))
            session.add(User(id=3, telegram_id=333, full_name=None, phone_number=None, verification_docs_file_ids_enc="[]", kyc_status="pending"))
            session.add(User(id=10, telegram_id=1010, full_name=None, phone_number=None, verification_docs_file_ids_enc="[]", kyc_status="pending"))
            session.add(Role(id=1, name="admin"))
            session.add(UserRole(user_id=10, role_id=1))
            session.add(JournalAccount(code="2000", name="Customer Balances", account_type="liability", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="4000", name="Trading Income", account_type="income", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="5000", name="Trading Expense", account_type="expense", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(
                Price(
                    source="manual_admin",
                    buy_price=Decimal("10"),
                    sell_price=Decimal("10"),
                    spread=Decimal("0"),
                    commission=Decimal("0"),
                    premium=Decimal("0"),
                    discount=Decimal("0"),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.add(Wallet(user_id=1, available_balance_usd=Decimal("0"), frozen_balance_usd=Decimal("0")))
            session.add(Position(user_id=1, net_kg=Decimal("2"), last_settlement_price_usd=Decimal("8")))
            session.add(Wallet(user_id=3, available_balance_usd=Decimal("0"), frozen_balance_usd=Decimal("0")))
            session.add(Position(user_id=2, net_kg=Decimal("0"), last_settlement_price_usd=Decimal("0")))
            session.add(Position(user_id=3, net_kg=Decimal("1"), last_settlement_price_usd=Decimal("0")))

    result = await run_daily_settlement(db)
    assert result["status"] == "ok"

    async with db.session() as session:
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == 1))
        assert wallet is not None
        assert Decimal(wallet.available_balance_usd) == Decimal("4")
        report = await session.scalar(select(SettlementReport))
        assert report is not None
        assert "\"price_source\": \"manual_admin\"" in report.summary_json
        notifications = (await session.scalars(select(Notification).order_by(Notification.user_id.asc()))).all()
        assert len(notifications) == 2
        assert {n.kind for n in notifications} == {"settlement.completed", "settlement.report_ready"}
        pos2 = await session.scalar(select(Position).where(Position.user_id == 2))
        assert pos2 is not None
        assert Decimal(pos2.last_settlement_price_usd) == Decimal("0")
        pos3 = await session.scalar(select(Position).where(Position.user_id == 3))
        assert pos3 is not None
        assert Decimal(pos3.last_settlement_price_usd) == Decimal("10")

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_daily_settlement_skips_without_price(tmp_path) -> None:
    db_path = tmp_path / "no_price.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    result = await run_daily_settlement(db)
    assert result["status"] == "skipped"

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_daily_settlement_ignores_unverified_latest_price(tmp_path) -> None:
    db_path = tmp_path / "verified_price.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db.session() as session:
        async with session.begin():
            session.add(User(id=1, telegram_id=111, full_name=None, phone_number=None, verification_docs_file_ids_enc="[]", kyc_status="pending"))
            session.add(JournalAccount(code="2000", name="Customer Balances", account_type="liability", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="4000", name="Trading Income", account_type="income", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="5000", name="Trading Expense", account_type="expense", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(Wallet(user_id=1, available_balance_usd=Decimal("0"), frozen_balance_usd=Decimal("0")))
            session.add(Position(user_id=1, net_kg=Decimal("1"), last_settlement_price_usd=Decimal("8")))
            session.add(
                Price(
                    source="manual_admin",
                    buy_price=Decimal("10"),
                    sell_price=Decimal("10"),
                    spread=Decimal("0"),
                    commission=Decimal("0"),
                    premium=Decimal("0"),
                    discount=Decimal("0"),
                    is_verified=True,
                    is_stale=False,
                    updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                )
            )
            session.add(
                Price(
                    source="goldapi",
                    buy_price=Decimal("99"),
                    sell_price=Decimal("99"),
                    spread=Decimal("0"),
                    commission=Decimal("0"),
                    premium=Decimal("0"),
                    discount=Decimal("0"),
                    is_verified=False,
                    is_stale=True,
                    updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                )
            )

    result = await run_daily_settlement(db)
    assert result["status"] == "ok"
    assert result["price_usd"] == "10.000000"

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_settlement_engine_idempotency_and_checkpoints(tmp_path) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        async def set(self, key: str, value: str, ex: int | None = None, nx: bool | None = None):
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

        async def get(self, key: str) -> str | None:
            return self.values.get(key)

        async def delete(self, key: str) -> None:
            self.values.pop(key, None)

    db_path = tmp_path / "idempotent_settlement.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db.session() as session:
        async with session.begin():
            session.add(User(id=1, telegram_id=111, full_name=None, phone_number=None, verification_docs_file_ids_enc="[]", kyc_status="pending"))
            session.add(Role(id=1, name="admin"))
            session.add(UserRole(user_id=1, role_id=1))
            session.add(JournalAccount(code="2000", name="Customer Balances", account_type="liability", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="4000", name="Trading Income", account_type="income", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="5000", name="Trading Expense", account_type="expense", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(Price(source="manual_admin", buy_price=Decimal("10"), sell_price=Decimal("10"), spread=Decimal("0"), commission=Decimal("0"), premium=Decimal("0"), discount=Decimal("0"), updated_at=datetime.now(timezone.utc)))
            session.add(Wallet(user_id=1, available_balance_usd=Decimal("100"), frozen_balance_usd=Decimal("0")))
            session.add(Position(user_id=1, net_kg=Decimal("2"), last_settlement_price_usd=Decimal("8")))

    engine = SettlementEngineService(db=db, redis=FakeRedis())  # type: ignore[arg-type]
    first = await engine.execute(mode="manual", settlement_at=datetime(2026, 7, 1, tzinfo=timezone.utc), actor_user_id=1, idempotency_key="manual:1")
    second = await engine.execute(mode="manual", settlement_at=datetime(2026, 7, 1, tzinfo=timezone.utc), actor_user_id=1, idempotency_key="manual:1")

    assert first["status"] == "completed"
    assert second["idempotent"] is True

    async with db.session() as session:
        batches = (await session.scalars(select(SettlementBatch))).all()
        assert len(batches) == 1
        checkpoints = (await session.scalars(select(SettlementCheckpoint).order_by(SettlementCheckpoint.id.asc()))).all()
        assert [row.checkpoint_name for row in checkpoints] == ["verified_inputs", "applied_positions", "completed"]
        reconciliations = (await session.scalars(select(SettlementReconciliation))).all()
        assert len(reconciliations) == 1

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_settlement_engine_rollback_and_replay(tmp_path) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.values: dict[str, str] = {}

        async def set(self, key: str, value: str, ex: int | None = None, nx: bool | None = None):
            if nx and key in self.values:
                return False
            self.values[key] = value
            return True

        async def get(self, key: str) -> str | None:
            return self.values.get(key)

        async def delete(self, key: str) -> None:
            self.values.pop(key, None)

    db_path = tmp_path / "rollback_settlement.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db.session() as session:
        async with session.begin():
            session.add(User(id=1, telegram_id=111, full_name=None, phone_number=None, verification_docs_file_ids_enc="[]", kyc_status="pending"))
            session.add(Role(id=1, name="admin"))
            session.add(UserRole(user_id=1, role_id=1))
            session.add(JournalAccount(code="2000", name="Customer Balances", account_type="liability", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="4000", name="Trading Income", account_type="income", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(JournalAccount(code="5000", name="Trading Expense", account_type="expense", parent_id=None, is_active=True, created_at=datetime.now(timezone.utc)))
            session.add(Price(source="manual_admin", buy_price=Decimal("10"), sell_price=Decimal("10"), spread=Decimal("0"), commission=Decimal("0"), premium=Decimal("0"), discount=Decimal("0"), updated_at=datetime.now(timezone.utc)))
            session.add(Wallet(user_id=1, available_balance_usd=Decimal("100"), frozen_balance_usd=Decimal("0")))
            session.add(Position(user_id=1, net_kg=Decimal("1"), last_settlement_price_usd=Decimal("8")))

    engine = SettlementEngineService(db=db, redis=FakeRedis())  # type: ignore[arg-type]
    first = await engine.execute(mode="manual", settlement_at=datetime(2026, 7, 2, tzinfo=timezone.utc), actor_user_id=1, idempotency_key="manual:rollback")
    rollback = await engine.rollback(settlement_id=first["summary"]["settlement_id"], actor_user_id=1, reason="correction")
    replay = await engine.replay(settlement_id=first["summary"]["settlement_id"], actor_user_id=1)

    assert rollback["status"] == "completed"
    assert replay["status"] == "completed"

    async with db.session() as session:
        original = await session.scalar(select(Settlement).where(Settlement.id == first["summary"]["settlement_id"]))
        assert original is not None
        assert original.status == "rolled_back"
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == 1))
        assert wallet is not None
        assert Decimal(wallet.available_balance_usd) == Decimal("102.00")
        reports = (await session.scalars(select(SettlementReport).order_by(SettlementReport.id.asc()))).all()
        assert len(reports) == 3

    await db.engine.dispose()
