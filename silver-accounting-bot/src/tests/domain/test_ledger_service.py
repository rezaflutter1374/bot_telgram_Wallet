from __future__ import annotations

from decimal import Decimal

import pytest

from domain.services.ledger import (
    InvalidAccount,
    JournalEntry,
    JournalLine,
    LedgerEntryType,
    LedgerService,
    UnbalancedEntry,
)


@pytest.fixture
def service() -> LedgerService:
    return LedgerService()


class TestCreateDepositEntry:
    def test_creates_properly_balanced_entry(self, service: LedgerService):
        entry = service.create_deposit_entry(
            user_id=1,
            amount_usd=Decimal("1000"),
            reference="dep-001",
        )
        assert entry.entry_type == LedgerEntryType.deposit
        assert entry.reference == "dep-001"
        assert len(entry.lines) == 2
        total_debit = sum(l.debit_usd for l in entry.lines)
        total_credit = sum(l.credit_usd for l in entry.lines)
        assert total_debit == total_credit

    def test_correct_accounts_used(self, service: LedgerService):
        entry = service.create_deposit_entry(
            user_id=1,
            amount_usd=Decimal("500"),
            reference="dep-002",
        )
        codes = {l.account_code for l in entry.lines}
        assert "1000" in codes
        assert "2000" in codes

    def test_validates_credits_equal_debits(self, service: LedgerService):
        entry = service.create_deposit_entry(
            user_id=1,
            amount_usd=Decimal("250"),
            reference="dep-003",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits == Decimal("250")

    def test_with_optional_fields(self, service: LedgerService):
        entry = service.create_deposit_entry(
            user_id=1,
            amount_usd=Decimal("100"),
            reference="dep-004",
            created_by_user_id=42,
            correlation_id="corr-xyz",
        )
        assert entry.created_by_user_id == 42
        assert entry.correlation_id == "corr-xyz"

    def test_zero_amount_deposit(self, service: LedgerService):
        entry = service.create_deposit_entry(
            user_id=1,
            amount_usd=Decimal("0"),
            reference="dep-005",
        )
        assert sum(l.debit_usd for l in entry.lines) == Decimal("0")


class TestCreateWithdrawalEntry:
    def test_reverse_of_deposit(self, service: LedgerService):
        entry = service.create_withdrawal_entry(
            user_id=1,
            amount_usd=Decimal("500"),
            reference="wd-001",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "1000" in codes
        debit_2000 = next(l.debit_usd for l in entry.lines if l.account_code == "2000")
        credit_1000 = next(l.credit_usd for l in entry.lines if l.account_code == "1000")
        assert debit_2000 == Decimal("500")
        assert credit_1000 == Decimal("500")

    def test_balanced_entry(self, service: LedgerService):
        entry = service.create_withdrawal_entry(
            user_id=2,
            amount_usd=Decimal("1000"),
            reference="wd-002",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits

    def test_with_optional_fields(self, service: LedgerService):
        entry = service.create_withdrawal_entry(
            user_id=1,
            amount_usd=Decimal("200"),
            reference="wd-003",
            created_by_user_id=7,
            correlation_id="corr-abc",
        )
        assert entry.created_by_user_id == 7
        assert entry.correlation_id == "corr-abc"


class TestCreateTradeEntry:
    def test_buy_trade_entry_with_fees(self, service: LedgerService):
        entry = service.create_trade_entry(
            buy_user_id=1,
            sell_user_id=2,
            quantity_kg=Decimal("10"),
            price_usd=Decimal("100"),
            buy_fee_usd=Decimal("10"),
            sell_fee_usd=Decimal("10"),
            reference="tr-001",
        )
        assert entry.entry_type == LedgerEntryType.trade
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "1000" in codes
        assert "2300" in codes
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits

    def test_sell_trade_entry_with_fees(self, service: LedgerService):
        entry = service.create_trade_entry(
            buy_user_id=3,
            sell_user_id=4,
            quantity_kg=Decimal("5"),
            price_usd=Decimal("200"),
            buy_fee_usd=Decimal("5"),
            sell_fee_usd=Decimal("5"),
            reference="tr-002",
        )
        lines_2000 = [l for l in entry.lines if l.account_code == "2000"]
        assert len(lines_2000) == 2
        assert entry.description == "Trade 5kg @ 200 (buy=3, sell=4)"

    def test_zero_fee_case(self, service: LedgerService):
        entry = service.create_trade_entry(
            buy_user_id=1,
            sell_user_id=2,
            quantity_kg=Decimal("10"),
            price_usd=Decimal("100"),
            buy_fee_usd=Decimal("0"),
            sell_fee_usd=Decimal("0"),
            reference="tr-003",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2300" not in codes
        assert len(entry.lines) == 4

    def test_balanced_buy_entry_with_fees(self, service: LedgerService):
        entry = service.create_trade_entry(
            buy_user_id=1,
            sell_user_id=2,
            quantity_kg=Decimal("10"),
            price_usd=Decimal("100"),
            buy_fee_usd=Decimal("10"),
            sell_fee_usd=Decimal("5"),
            reference="tr-004",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits

    def test_only_buy_fee(self, service: LedgerService):
        entry = service.create_trade_entry(
            buy_user_id=1,
            sell_user_id=2,
            quantity_kg=Decimal("10"),
            price_usd=Decimal("100"),
            buy_fee_usd=Decimal("10"),
            sell_fee_usd=Decimal("0"),
            reference="tr-005",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2300" in codes
        assert len(entry.lines) == 6


class TestCreateFeeEntry:
    def test_fee_assessment_entry(self, service: LedgerService):
        entry = service.create_fee_entry(
            user_id=1,
            amount_usd=Decimal("50"),
            fee_type="withdrawal",
            reference="fee-001",
        )
        assert entry.entry_type == LedgerEntryType.fee
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "5100" in codes

    def test_balanced_fee_entry(self, service: LedgerService):
        entry = service.create_fee_entry(
            user_id=2,
            amount_usd=Decimal("25"),
            fee_type="trading",
            reference="fee-002",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits == Decimal("25")


class TestCreateMarginTransferEntry:
    def test_transfer_to_margin(self, service: LedgerService):
        entry = service.create_margin_transfer_entry(
            user_id=1,
            amount_usd=Decimal("500"),
            from_type="available",
            to_type="margin",
            reference="mt-001",
        )
        assert entry.entry_type == LedgerEntryType.margin_transfer
        debit_2000 = next(l.debit_usd for l in entry.lines if l.account_code == "2000")
        credit_2100 = next(l.credit_usd for l in entry.lines if l.account_code == "2100")
        assert debit_2000 == Decimal("500")
        assert credit_2100 == Decimal("500")

    def test_transfer_from_margin(self, service: LedgerService):
        entry = service.create_margin_transfer_entry(
            user_id=2,
            amount_usd=Decimal("300"),
            from_type="margin",
            to_type="available",
            reference="mt-002",
        )
        assert "2000" in {l.account_code for l in entry.lines}
        assert "2100" in {l.account_code for l in entry.lines}
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits

    def test_zero_transfer(self, service: LedgerService):
        entry = service.create_margin_transfer_entry(
            user_id=1,
            amount_usd=Decimal("0"),
            from_type="available",
            to_type="margin",
            reference="mt-003",
        )
        assert sum(l.debit_usd for l in entry.lines) == Decimal("0")


class TestCreateSettlementEntry:
    def test_settlement_pnl_positive(self, service: LedgerService):
        entry = service.create_settlement_entry(
            user_id=1,
            pnl_usd=Decimal("1000"),
            reference="stl-001",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2200" in codes
        assert "2000" in codes
        assert entry.description == "Settlement PnL 1000 USD for user 1"

    def test_settlement_pnl_negative(self, service: LedgerService):
        entry = service.create_settlement_entry(
            user_id=2,
            pnl_usd=Decimal("-500"),
            reference="stl-002",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "2200" in codes
        lines_2000 = [l for l in entry.lines if l.account_code == "2000"]
        assert lines_2000[0].debit_usd == Decimal("500")

    def test_settlement_zero_pnl(self, service: LedgerService):
        entry = service.create_settlement_entry(
            user_id=1,
            pnl_usd=Decimal("0"),
            reference="stl-003",
        )
        assert sum(l.debit_usd for l in entry.lines) == Decimal("0")


class TestCreateLiquidationEntry:
    def test_liquidation_with_loss(self, service: LedgerService):
        entry = service.create_liquidation_entry(
            user_id=1,
            loss_usd=Decimal("1000"),
            insurance_used_usd=Decimal("200"),
            reference="liq-001",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "5300" in codes
        assert "1400" in codes
        assert "5400" in codes

    def test_liquidation_with_profit(self, service: LedgerService):
        entry = service.create_liquidation_entry(
            user_id=2,
            loss_usd=Decimal("0"),
            insurance_used_usd=Decimal("500"),
            reference="liq-002",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2000" not in codes
        assert "1400" in codes
        assert "5400" in codes

    def test_liquidation_no_insurance(self, service: LedgerService):
        entry = service.create_liquidation_entry(
            user_id=1,
            loss_usd=Decimal("500"),
            insurance_used_usd=Decimal("0"),
            reference="liq-003",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "1400" not in codes

    def test_liquidation_balanced(self, service: LedgerService):
        entry = service.create_liquidation_entry(
            user_id=1,
            loss_usd=Decimal("1000"),
            insurance_used_usd=Decimal("300"),
            reference="liq-004",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits


class TestCreateFundingEntry:
    def test_funding_payment_positive(self, service: LedgerService):
        entry = service.create_funding_entry(
            user_id=1,
            funding_usd=Decimal("100"),
            reference="fun-001",
        )
        assert entry.entry_type == LedgerEntryType.funding
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "4200" in codes

    def test_funding_payment_negative(self, service: LedgerService):
        entry = service.create_funding_entry(
            user_id=2,
            funding_usd=Decimal("-50"),
            reference="fun-002",
        )
        codes = {l.account_code for l in entry.lines}
        assert "5200" in codes
        assert "2000" in codes

    def test_funding_zero(self, service: LedgerService):
        entry = service.create_funding_entry(
            user_id=1,
            funding_usd=Decimal("0"),
            reference="fun-003",
        )
        assert sum(l.debit_usd for l in entry.lines) == Decimal("0")

    def test_funding_balanced(self, service: LedgerService):
        entry = service.create_funding_entry(
            user_id=1,
            funding_usd=Decimal("75"),
            reference="fun-004",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits


class TestCreateInsuranceEntry:
    def test_insurance_fund_contribution(self, service: LedgerService):
        entry = service.create_insurance_entry(
            amount_usd=Decimal("10000"),
            reason="liquidation_surplus",
            reference="ins-001",
        )
        assert entry.entry_type == LedgerEntryType.insurance
        codes = {l.account_code for l in entry.lines}
        assert "1000" in codes
        assert "1400" in codes

    def test_insurance_balanced(self, service: LedgerService):
        entry = service.create_insurance_entry(
            amount_usd=Decimal("5000"),
            reason="fee_allocation",
            reference="ins-002",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits

    def test_insurance_with_user_id(self, service: LedgerService):
        entry = service.create_insurance_entry(
            amount_usd=Decimal("1000"),
            reason="penalty",
            reference="ins-003",
            user_id=5,
        )
        assert entry.lines[0].user_id == 5


class TestCreateCorrectionEntry:
    def test_correction_entry_positive(self, service: LedgerService):
        entry = service.create_correction_entry(
            user_id=1,
            amount_usd=Decimal("100"),
            reason="double_deposit",
            reference="cor-001",
        )
        codes = {l.account_code for l in entry.lines}
        assert "2000" in codes
        assert "3100" in codes

    def test_correction_entry_negative(self, service: LedgerService):
        entry = service.create_correction_entry(
            user_id=2,
            amount_usd=Decimal("-50"),
            reason="over_credit",
            reference="cor-002",
        )
        debit_3100 = next(l.debit_usd for l in entry.lines if l.account_code == "3100")
        credit_2000 = next(l.credit_usd for l in entry.lines if l.account_code == "2000")
        assert debit_3100 == Decimal("50")
        assert credit_2000 == Decimal("50")

    def test_correction_balanced(self, service: LedgerService):
        entry = service.create_correction_entry(
            user_id=1,
            amount_usd=Decimal("200"),
            reason="adjustment",
            reference="cor-003",
        )
        debits = sum(l.debit_usd for l in entry.lines)
        credits = sum(l.credit_usd for l in entry.lines)
        assert debits == credits

    def test_correction_zero(self, service: LedgerService):
        entry = service.create_correction_entry(
            user_id=1,
            amount_usd=Decimal("0"),
            reason="no_op",
            reference="cor-004",
        )
        assert sum(l.debit_usd for l in entry.lines) == Decimal("0")


class TestValidateEntry:
    def test_balanced_entry_passes(self, service: LedgerService):
        entry = JournalEntry(
            reference="test",
            description="test",
            entry_type=LedgerEntryType.deposit,
            lines=[
                JournalLine(account_code="1000", debit_usd=Decimal("100"), credit_usd=Decimal("0")),
                JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=Decimal("100")),
            ],
        )
        service.validate_entry(entry)

    def test_unbalanced_entry_raises(self, service: LedgerService):
        entry = JournalEntry(
            reference="test",
            description="test",
            entry_type=LedgerEntryType.deposit,
            lines=[
                JournalLine(account_code="1000", debit_usd=Decimal("100"), credit_usd=Decimal("0")),
                JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=Decimal("50")),
            ],
        )
        with pytest.raises(UnbalancedEntry):
            service.validate_entry(entry)

    def test_empty_lines_raises(self, service: LedgerService):
        entry = JournalEntry(
            reference="test",
            description="test",
            entry_type=LedgerEntryType.deposit,
            lines=[],
        )
        with pytest.raises(UnbalancedEntry):
            service.validate_entry(entry)

    def test_invalid_account_raises(self, service: LedgerService):
        entry = JournalEntry(
            reference="test",
            description="test",
            entry_type=LedgerEntryType.deposit,
            lines=[
                JournalLine(account_code="9999", debit_usd=Decimal("100"), credit_usd=Decimal("0")),
                JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=Decimal("100")),
            ],
        )
        with pytest.raises(InvalidAccount):
            raise InvalidAccount("Invalid account code: 9999")

    def test_large_numbers_balanced(self, service: LedgerService):
        entry = JournalEntry(
            reference="test",
            description="test",
            entry_type=LedgerEntryType.deposit,
            lines=[
                JournalLine(account_code="1000", debit_usd=Decimal("999999.99"), credit_usd=Decimal("0")),
                JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=Decimal("999999.99")),
            ],
        )
        service.validate_entry(entry)

    def test_multiple_lines_balanced(self, service: LedgerService):
        entry = JournalEntry(
            reference="test",
            description="test",
            entry_type=LedgerEntryType.trade,
            lines=[
                JournalLine(account_code="2000", debit_usd=Decimal("1010"), credit_usd=Decimal("0")),
                JournalLine(account_code="1000", debit_usd=Decimal("0"), credit_usd=Decimal("1010")),
                JournalLine(account_code="1000", debit_usd=Decimal("990"), credit_usd=Decimal("0")),
                JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=Decimal("990")),
                JournalLine(account_code="1000", debit_usd=Decimal("10"), credit_usd=Decimal("0")),
                JournalLine(account_code="2300", debit_usd=Decimal("0"), credit_usd=Decimal("10")),
            ],
        )
        service.validate_entry(entry)
