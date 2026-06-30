from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from application.errors import Forbidden, NotFound, ValidationError
from application.use_cases.services import AppServices
from domain.enums import JournalAccountType, KycStatus, NotificationStatus, PaymentType
from domain.services.margin import MarginCalculator
from infrastructure.db.base import Base
from infrastructure.db.models import BankAccount, JournalAccount, JournalEntry, JournalLine, PaymentCard, PaymentRequest, User, Wallet
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


def build_services(db: Database) -> tuple[AppServices, SqlAlchemyUnitOfWork]:
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
    return services, uow


@pytest.mark.asyncio
async def test_deposit_withdraw_approve_reject_and_reports(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'acc.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    services, uow = build_services(db)
    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    user = await services.register_or_get_user(telegram_id=9100)
    await services.submit_kyc(user.id, "A B", "+1", "enc:n", "enc:p", "enc:s", [])

    deposit = await services.create_payment_request(
        user_id=user.id,
        payment_type=PaymentType.deposit,
        amount_usd=Decimal("50"),
        receipt_file_ids_enc=["enc:r1"],
        bank_account_id=None,
    )
    assert deposit.amount_usd == Decimal("50")

    accountant = await services.register_or_get_user(telegram_id=9101)
    async with uow.transaction():
        await services._roles.grant_role(accountant.id, "accountant")

    approved = await services.review_payment_request(accountant.id, deposit.id, approve=True, note="ok")
    assert approved.status.value == "approved"

    w = await services.get_wallet(user.id)
    assert w["available_balance_usd"] == Decimal("50")

    withdrawal = await services.create_payment_request(
        user_id=user.id,
        payment_type=PaymentType.withdrawal,
        amount_usd=Decimal("10"),
        receipt_file_ids_enc=["enc:r2"],
        bank_account_id=None,
    )
    w2 = await services.get_wallet(user.id)
    assert w2["available_balance_usd"] == Decimal("40")
    assert w2["frozen_balance_usd"] == Decimal("10")

    approved_w = await services.review_payment_request(accountant.id, withdrawal.id, approve=True, note=None)
    assert approved_w.status.value == "approved"

    w3 = await services.get_wallet(user.id)
    assert w3["available_balance_usd"] == Decimal("40")
    assert w3["frozen_balance_usd"] == Decimal("0")

    withdrawal2 = await services.create_payment_request(
        user_id=user.id,
        payment_type=PaymentType.withdrawal,
        amount_usd=Decimal("5"),
        receipt_file_ids_enc=["enc:r3"],
        bank_account_id=None,
    )
    rejected = await services.review_payment_request(accountant.id, withdrawal2.id, approve=False, note="bad")
    assert rejected.status.value == "rejected"
    w4 = await services.get_wallet(user.id)
    assert w4["frozen_balance_usd"] == Decimal("0")

    tb = await services.report_trial_balance(accountant.id, None, datetime.now(timezone.utc))
    assert any(r["code"] == "1000" for r in tb)

    pnl = await services.report_profit_and_loss(accountant.id, None, datetime.now(timezone.utc))
    assert "net_profit_usd" in pnl

    bs = await services.report_balance_sheet(accountant.id, datetime.now(timezone.utc))
    assert "assets_usd" in bs

    cf = await services.report_cash_flow(accountant.id, None, datetime.now(timezone.utc))
    assert "net_cash_change_usd" in cf

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_kyc_review_and_risk_rule(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'risk.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    services, uow = build_services(db)
    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    user = await services.register_or_get_user(telegram_id=9200)
    await services.submit_kyc(user.id, "A", "+1", "x", "x", "x", [])

    admin = await services.register_or_get_user(telegram_id=9201)
    manager = await services.register_or_get_user(telegram_id=9202)
    async with uow.transaction():
        await services._roles.grant_role(admin.id, "admin")
        await services._roles.grant_role(manager.id, "manager")

    await services.review_kyc(admin.id, user.id, KycStatus.approved, note="approved")

    async with uow.transaction():
        u = await services._users.get(user.id)
        assert u is not None
        assert u["kyc_status"] == KycStatus.approved

    rr = await services.set_risk_rule(manager.id, "default", Decimal("10"), Decimal("2"), True)
    assert rr["name"] == "default"

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_accounting_posting_unbalanced_rejected(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'unbalanced.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    services, uow = build_services(db)
    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    async with uow.transaction():
        cash = await services._accounting.get_account_by_code("1000")
        customer = await services._accounting.get_account_by_code("2000")
        assert cash is not None
        assert customer is not None
        with pytest.raises(RuntimeError):
            await services._accounting.post_journal_entry(
                reference="x",
                description="bad",
                posted_at=datetime.now(timezone.utc),
                created_by_user_id=None,
                lines=[
                    {"account_id": cash["id"], "debit_usd": Decimal("1"), "credit_usd": Decimal("0"), "user_id": None},
                    {"account_id": customer["id"], "debit_usd": Decimal("0"), "credit_usd": Decimal("2"), "user_id": 1},
                ],
            )

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_notifications_and_risk_repo_branches(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'notif.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    services, uow = build_services(db)
    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    u = await services.register_or_get_user(telegram_id=9300)
    await services.submit_kyc(u.id, "A", "+1", "x", "x", "x", [])

    async with uow.transaction():
        n = await services._notifications.enqueue(u.id, "test", {"a": Decimal("1.23")})
        pending = await services._notifications.list_pending(limit=10)
        assert any(x["id"] == n["id"] for x in pending)
        await services._notifications.mark(n["id"], status=NotificationStatus.sent)

    async with uow.transaction():
        await services._risk.upsert_rule("disabled", Decimal("1"), Decimal("1"), False)
        await services._risk.upsert_rule("enabled", Decimal("2"), Decimal("1"), True)
        r = await services._risk.get_active_rule()
        assert r is not None
        assert r["enabled"] is True

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_manual_accounting_bank_cards_and_period_reports(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'ops.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    services, uow = build_services(db)
    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    accountant = await services.register_or_get_user(telegram_id=9400)
    async with uow.transaction():
        await services._roles.grant_role(accountant.id, "accountant")

    bank = await services.create_bank_account(accountant.id, "Main Bank", "enc:iban")
    assert bank["name"] == "Main Bank"

    banks = await services.list_bank_accounts(accountant.id)
    assert len(banks) == 1

    card = await services.create_payment_card(accountant.id, bank["id"], "Treasury Card", "enc:card")
    assert card["label"] == "Treasury Card"

    cards = await services.list_payment_cards(accountant.id, bank_account_id=bank["id"])
    assert len(cards) == 1

    row = await services.post_manual_transfer(
        accountant.id,
        debit_account_code="1000",
        credit_account_code="3000",
        amount_usd=Decimal("25"),
        description="Capital injection",
    )
    assert row["id"] > 0

    dashboard = await services.report_financial_dashboard(accountant.id, None, datetime.now(timezone.utc))
    assert dashboard["assets_usd"] >= Decimal("25")
    assert dashboard["trial_balance_rows"] >= 2

    daily = await services.report_period_summary(accountant.id, "daily", datetime.now(timezone.utc))
    assert daily["period"] == "daily"

    monthly = await services.report_period_summary(accountant.id, "monthly", datetime.now(timezone.utc))
    assert monthly["period"] == "monthly"

    async with db.session() as session:
        assert await session.scalar(select(BankAccount.id)) is not None
        assert await session.scalar(select(PaymentCard.id)) is not None
        assert await session.scalar(select(JournalEntry.id)) is not None

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_accounting_management_validation_and_forbidden_paths(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'ops_forbidden.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    services, uow = build_services(db)
    await services.ensure_rbac_defaults()
    await services.ensure_accounting_defaults()

    user = await services.register_or_get_user(telegram_id=9500)
    accountant = await services.register_or_get_user(telegram_id=9501)
    async with uow.transaction():
        await services._roles.grant_role(accountant.id, "accountant")

    with pytest.raises(Forbidden):
        await services.create_bank_account(user.id, "X", "enc:x")

    with pytest.raises(ValidationError):
        await services.create_bank_account(accountant.id, " ", "enc:x")

    bank = await services.create_bank_account(accountant.id, "Ops Bank", "enc:acct")

    with pytest.raises(ValidationError):
        await services.create_payment_card(accountant.id, bank["id"], " ", "enc:card")

    with pytest.raises(RuntimeError):
        await services.create_payment_card(accountant.id, 999, "Ops", "enc:card")

    with pytest.raises(Forbidden):
        await services.list_bank_accounts(user.id)

    with pytest.raises(Forbidden):
        await services.list_payment_cards(user.id)

    with pytest.raises(ValidationError):
        await services.report_period_summary(accountant.id, "bad-period", datetime.now(timezone.utc))

    with pytest.raises(ValidationError):
        await services.post_manual_journal_entry(accountant.id, None, " ", datetime.now(timezone.utc), [])

    with pytest.raises(ValidationError):
        await services.post_manual_transfer(accountant.id, "1000", "2000", Decimal("0"), "bad")

    with pytest.raises(NotFound):
        await services.post_manual_transfer(accountant.id, "9999", "2000", Decimal("1"), "missing")

    await db.engine.dispose()
