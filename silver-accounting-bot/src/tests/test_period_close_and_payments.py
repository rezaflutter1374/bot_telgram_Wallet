from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import select

from application.use_cases.services import AppServices
from application.errors import ValidationError
from domain.enums import PaymentType, PaymentStatus
from domain.services.margin import MarginCalculator
from infrastructure.db.base import Base
from infrastructure.db.models import (
    FinancialPeriod,
    JournalAccount,
    JournalEntry,
    JournalLine,
    PaymentReconciliation,
    Price,
    User,
    Wallet,
)
from infrastructure.db.session import Database, SqlAlchemyUnitOfWork
from infrastructure.repositories.sql_repos import (
    SqlAccountingRepo,
    SqlAuditRepo,
    SqlBackupRepo,
    SqlNotificationRepo,
    SqlOrderRepo,
    SqlPaymentReconciliationRepo,
    SqlPaymentRepo,
    SqlPositionRepo,
    SqlPriceRepo,
    SqlRiskRepo,
    SqlRoleRepo,
    SqlTicketRepo,
    SqlUserRepo,
    SqlWalletRepo,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@pytest_asyncio.fixture
async def services(tmp_path) -> AsyncGenerator[AppServices, None]:
    db_path = tmp_path / "test_period.db"
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
    payment_recon = SqlPaymentReconciliationRepo(uow)

    svc = AppServices(
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
        payment_reconciliation=payment_recon,
    )

    await svc.ensure_rbac_defaults()

    yield svc

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_close_monthly_period(services: AppServices) -> None:
    accountant = await services.register_or_get_user(telegram_id=999)
    async with services._uow.transaction():
        await services._roles.grant_role(accountant.id, "accountant")

    async with services._uow.transaction():
        await services._accounting.ensure_default_chart()
        cash = await services._accounting.get_account_by_code("1000")
        income = await services._accounting.get_account_by_code("4000")
        expense = await services._accounting.get_account_by_code("5000")
        assert cash is not None and income is not None and expense is not None

        start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = utcnow().replace(day=28, hour=23, minute=59, second=59, microsecond=0)

        await services._accounting.post_journal_entry(
            reference="test_revenue",
            description="Test revenue",
            posted_at=datetime.fromtimestamp(start.timestamp() + 1, tz=timezone.utc),
            created_by_user_id=accountant.id,
            lines=[
                {"account_id": cash["id"], "debit_usd": Decimal("1000"), "credit_usd": Decimal("0"), "user_id": None},
                {"account_id": income["id"], "debit_usd": Decimal("0"), "credit_usd": Decimal("1000"), "user_id": None},
            ],
        )

    result = await services.close_financial_period(accountant.id, "monthly", "2026-06", start, end)
    assert result["period_type"] == "monthly"
    assert result["is_closed"] is True
    assert result["net_income_usd"] > 0
    assert result["closing_journal_entry_id"] is not None

    async with services._uow.transaction():
        row = await services._uow.session.scalar(select(FinancialPeriod).where(FinancialPeriod.id == result["id"]))
        assert row is not None
        assert row.is_closed is True


@pytest.mark.asyncio
async def test_list_periods(services: AppServices) -> None:
    accountant = await services.register_or_get_user(telegram_id=888)
    async with services._uow.transaction():
        await services._roles.grant_role(accountant.id, "accountant")

    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = utcnow().replace(day=28, hour=23, minute=59, second=59, microsecond=0)

    await services.close_financial_period(accountant.id, "monthly", "2026-05", start, end)
    await services.close_financial_period(accountant.id, "monthly", "2026-06", start, end)

    periods = await services.list_financial_periods(accountant.id, period_type="monthly")
    assert len(periods) >= 2


@pytest.mark.asyncio
async def test_reopen_period(services: AppServices) -> None:
    accountant = await services.register_or_get_user(telegram_id=777)
    async with services._uow.transaction():
        await services._roles.grant_role(accountant.id, "accountant")

    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = utcnow().replace(day=28, hour=23, minute=59, second=59, microsecond=0)

    result = await services.close_financial_period(accountant.id, "monthly", "2026-07", start, end)
    reopened = await services.reopen_financial_period(accountant.id, result["id"])
    assert reopened["is_closed"] is False


@pytest.mark.asyncio
async def test_forbid_close_period_without_permission(services: AppServices) -> None:
    user = await services.register_or_get_user(telegram_id=666)
    start = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = utcnow().replace(day=28, hour=23, minute=59, second=59, microsecond=0)
    with pytest.raises(Exception):
        await services.close_financial_period(user.id, "monthly", "2026-08", start, end)


@pytest.mark.asyncio
async def test_duplicate_payment_detection(tmp_path) -> None:
    db_path = tmp_path / "dup_pay.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    users = SqlUserRepo(uow)
    wallets = SqlWalletRepo(uow)
    roles = SqlRoleRepo(uow)
    payments = SqlPaymentRepo(uow)
    accounting = SqlAccountingRepo(uow)
    notifications = SqlNotificationRepo(uow)
    audit = SqlAuditRepo(uow)
    risk = SqlRiskRepo(uow)
    orders = SqlOrderRepo(uow)
    positions = SqlPositionRepo(uow)
    tickets = SqlTicketRepo(uow)
    backup = SqlBackupRepo(uow)
    prices = SqlPriceRepo(uow)
    payment_recon = SqlPaymentReconciliationRepo(uow)

    svc = AppServices(
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
        payment_reconciliation=payment_recon,
    )

    await svc.ensure_rbac_defaults()
    user = await svc.register_or_get_user(telegram_id=555)
    async with uow.transaction():
        await wallets.credit_available(user.id, Decimal("1000"))

    pr1 = await svc.create_payment_request(
        user.id, PaymentType.deposit, Decimal("100"),
        ["enc:receipt1"], None, reference_number="REF-001",
    )
    assert pr1.id is not None

    with pytest.raises(ValidationError, match="Duplicate payment"):
        await svc.create_payment_request(
            user.id, PaymentType.deposit, Decimal("100"),
            ["enc:receipt1"], None, reference_number="REF-002",
        )

    with pytest.raises(ValidationError, match="already exists"):
        await svc.create_payment_request(
            user.id, PaymentType.deposit, Decimal("200"),
            ["enc:receipt2"], None, reference_number="REF-001",
        )

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_payment_reconciliation(services: AppServices) -> None:
    accountant = await services.register_or_get_user(telegram_id=444)
    user = await services.register_or_get_user(telegram_id=445)
    async with services._uow.transaction():
        await services._roles.grant_role(accountant.id, "accountant")
    async with services._uow.transaction():
        await services._wallets.credit_available(user.id, Decimal("500"))

    pr = await services.create_payment_request(
        user.id, PaymentType.deposit, Decimal("100"),
        ["enc:receipt_recon"], None, reference_number="REF-RECON",
    )
    result = await services.reconcile_payment(accountant.id, pr.id, reference_number="BANK-REF-001")
    assert result["reconciled"] is True


@pytest.mark.asyncio
async def test_price_anomaly_detection(services: AppServices) -> None:
    admin = await services.register_or_get_user(telegram_id=333)
    async with services._uow.transaction():
        await services._roles.grant_role(admin.id, "admin")

    await services.set_price(admin.id, Decimal("10"), Decimal("11"))

    anomaly = await services.detect_price_anomaly(
        admin.id,
        anomaly_type="outlier",
        severity="warning",
        observed_value_usd=Decimal("50"),
        expected_value_usd=Decimal("10"),
        deviation_pct=Decimal("400"),
        threshold_pct=Decimal("10"),
    )
    assert anomaly is not None
    assert anomaly["anomaly_type"] == "outlier"

    anomalies = await services.list_price_anomalies(admin.id)
    assert len(anomalies) >= 1
    assert anomalies[0]["anomaly_type"] == "outlier"

    resolved = await services.resolve_price_anomaly(admin.id, anomaly["id"])
    assert resolved is not None
    assert resolved["is_resolved"] is True

    price_history = await services.get_price_history(admin.id)
    assert len(price_history) >= 1


@pytest.mark.asyncio
async def test_wallet_pending_and_settlement_balances(tmp_path) -> None:
    db_path = tmp_path / "wallet_ext.db"
    db = Database(f"sqlite+aiosqlite:///{db_path}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db.session() as session:
        async with session.begin():
            session.add(User(id=1, telegram_id=1, verification_docs_file_ids_enc="[]"))
            session.add(Wallet(user_id=1, available_balance_usd=Decimal("100"), pending_balance_usd=Decimal("0"), settlement_balance_usd=Decimal("0"), equity_usd=Decimal("100")))

    uow = SqlAlchemyUnitOfWork(db)
    wallets = SqlWalletRepo(uow)

    async with uow.transaction():
        await wallets.credit_pending(1, Decimal("50"))
        wallet = await wallets.get_wallet(1)
        assert wallet["pending_balance_usd"] == Decimal("50")

    async with uow.transaction():
        await wallets.pending_to_available(1, Decimal("30"))
        wallet = await wallets.get_wallet(1)
        assert wallet["pending_balance_usd"] == Decimal("20")
        assert wallet["available_balance_usd"] == Decimal("130")

    async with uow.transaction():
        await wallets.credit_settlement(1, Decimal("200"))
        wallet = await wallets.get_wallet(1)
        assert wallet["settlement_balance_usd"] == Decimal("200")

    async with uow.transaction():
        await wallets.settlement_to_available(1, Decimal("100"))
        wallet = await wallets.get_wallet(1)
        assert wallet["settlement_balance_usd"] == Decimal("100")
        assert wallet["available_balance_usd"] == Decimal("230")

    async with uow.transaction():
        await wallets.available_to_pending(1, Decimal("50"))
        wallet = await wallets.get_wallet(1)
        assert wallet["available_balance_usd"] == Decimal("180")
        assert wallet["pending_balance_usd"] == Decimal("70")

    await db.engine.dispose()
