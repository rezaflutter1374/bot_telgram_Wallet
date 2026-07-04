from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol


class LedgerEntryType(str, Enum):
    trade = "trade"
    deposit = "deposit"
    withdrawal = "withdrawal"
    transfer = "transfer"
    fee = "fee"
    funding = "funding"
    settlement = "settlement"
    liquidation = "liquidation"
    insurance = "insurance"
    correction = "correction"
    manual_adjustment = "manual_adjustment"
    margin_transfer = "margin_transfer"
    freeze = "freeze"
    unfreeze = "unfreeze"


LEDGER_ACCOUNT_CODES = {
    "1000": "Cash USD",
    "1100": "Cash Bank",
    "1200": "Accounts Receivable",
    "1300": "Settlement Receivable",
    "1400": "Insurance Fund",
    "2000": "Customer Balances",
    "2100": "Margin Deposits",
    "2200": "Settlement Payable",
    "2300": "Fee Payable",
    "2400": "Funding Payable",
    "3000": "Equity",
    "3100": "Retained Earnings",
    "4000": "Trading Income",
    "4100": "Fee Income",
    "4200": "Funding Income",
    "5000": "Trading Expense",
    "5100": "Fee Expense",
    "5200": "Funding Expense",
    "5300": "Liquidation Expense",
    "5400": "Insurance Expense",
}


@dataclass(frozen=True)
class LedgerAccount:
    code: str
    name: str
    account_type: str  # asset, liability, equity, income, expense
    normal_side: str  # debit or credit

    @property
    def is_asset_or_expense(self) -> bool:
        return self.account_type in ("asset", "expense")

    def balance(self, debit: Decimal, credit: Decimal) -> Decimal:
        if self.is_asset_or_expense:
            return debit - credit
        return credit - debit


DEFAULT_LEDGER_ACCOUNTS: list[LedgerAccount] = [
    LedgerAccount("1000", "Cash USD", "asset", "debit"),
    LedgerAccount("1100", "Cash Bank", "asset", "debit"),
    LedgerAccount("1200", "Accounts Receivable", "asset", "debit"),
    LedgerAccount("1300", "Settlement Receivable", "asset", "debit"),
    LedgerAccount("1400", "Insurance Fund", "asset", "debit"),
    LedgerAccount("2000", "Customer Balances", "liability", "credit"),
    LedgerAccount("2100", "Margin Deposits", "liability", "credit"),
    LedgerAccount("2200", "Settlement Payable", "liability", "credit"),
    LedgerAccount("2300", "Fee Payable", "liability", "credit"),
    LedgerAccount("2400", "Funding Payable", "liability", "credit"),
    LedgerAccount("3000", "Equity", "equity", "credit"),
    LedgerAccount("3100", "Retained Earnings", "equity", "credit"),
    LedgerAccount("4000", "Trading Income", "income", "credit"),
    LedgerAccount("4100", "Fee Income", "income", "credit"),
    LedgerAccount("4200", "Funding Income", "income", "credit"),
    LedgerAccount("5000", "Trading Expense", "expense", "debit"),
    LedgerAccount("5100", "Fee Expense", "expense", "debit"),
    LedgerAccount("5200", "Funding Expense", "expense", "debit"),
    LedgerAccount("5300", "Liquidation Expense", "expense", "debit"),
    LedgerAccount("5400", "Insurance Expense", "expense", "debit"),
]


@dataclass(frozen=True)
class JournalLine:
    account_code: str
    debit_usd: Decimal
    credit_usd: Decimal
    user_id: int | None = None
    description: str | None = None


@dataclass(frozen=True)
class JournalEntry:
    reference: str
    description: str
    entry_type: LedgerEntryType
    lines: list[JournalLine]
    created_by_user_id: int | None = None
    posted_at: datetime | None = None
    correlation_id: str | None = None


class LedgerError(Exception):
    pass


class UnbalancedEntry(LedgerError):
    pass


class InvalidAccount(LedgerError):
    pass


class LedgerService:
    def validate_entry(self, entry: JournalEntry) -> None:
        if not entry.lines:
            raise UnbalancedEntry("Journal entry must have at least one line")
        total_debit = sum(line.debit_usd for line in entry.lines)
        total_credit = sum(line.credit_usd for line in entry.lines)
        if total_debit != total_credit:
            raise UnbalancedEntry(
                f"Unbalanced entry: debit={total_debit}, credit={total_credit}"
            )

    def create_deposit_entry(
        self,
        user_id: int,
        amount_usd: Decimal,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        return JournalEntry(
            reference=reference,
            description=f"Deposit {amount_usd} USD for user {user_id}",
            entry_type=LedgerEntryType.deposit,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="1000", debit_usd=amount_usd, credit_usd=Decimal("0"), user_id=None, description="Cash received"),
                JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=amount_usd, user_id=user_id, description="Customer deposit"),
            ],
        )

    def create_withdrawal_entry(
        self,
        user_id: int,
        amount_usd: Decimal,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        return JournalEntry(
            reference=reference,
            description=f"Withdrawal {amount_usd} USD for user {user_id}",
            entry_type=LedgerEntryType.withdrawal,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="2000", debit_usd=amount_usd, credit_usd=Decimal("0"), user_id=user_id, description="Customer withdrawal"),
                JournalLine(account_code="1000", debit_usd=Decimal("0"), credit_usd=amount_usd, user_id=None, description="Cash paid"),
            ],
        )

    def create_trade_entry(
        self,
        buy_user_id: int,
        sell_user_id: int,
        quantity_kg: Decimal,
        price_usd: Decimal,
        buy_fee_usd: Decimal,
        sell_fee_usd: Decimal,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        notional = (quantity_kg * price_usd).quantize(Decimal("0.01"))
        buy_net = (notional + buy_fee_usd).quantize(Decimal("0.01"))
        sell_net = (notional - sell_fee_usd).quantize(Decimal("0.01"))
        lines = [
            JournalLine(account_code="2000", debit_usd=buy_net, credit_usd=Decimal("0"), user_id=buy_user_id, description="Buyer settlement"),
            JournalLine(account_code="1000", debit_usd=Decimal("0"), credit_usd=buy_net, user_id=None, description="Buyer payment"),
            JournalLine(account_code="1000", debit_usd=sell_net, credit_usd=Decimal("0"), user_id=None, description="Seller receipt"),
            JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=sell_net, user_id=sell_user_id, description="Seller settlement"),
        ]
        if buy_fee_usd > 0:
            lines.append(JournalLine(account_code="1000", debit_usd=buy_fee_usd, credit_usd=Decimal("0"), user_id=None, description="Buy fee collected"))
            lines.append(JournalLine(account_code="2300", debit_usd=Decimal("0"), credit_usd=buy_fee_usd, user_id=None, description="Buy fee payable"))
        if sell_fee_usd > 0:
            lines.append(JournalLine(account_code="1000", debit_usd=sell_fee_usd, credit_usd=Decimal("0"), user_id=None, description="Sell fee collected"))
            lines.append(JournalLine(account_code="2300", debit_usd=Decimal("0"), credit_usd=sell_fee_usd, user_id=None, description="Sell fee payable"))
        return JournalEntry(
            reference=reference,
            description=f"Trade {quantity_kg}kg @ {price_usd} (buy={buy_user_id}, sell={sell_user_id})",
            entry_type=LedgerEntryType.trade,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=lines,
        )

    def create_fee_entry(
        self,
        user_id: int,
        amount_usd: Decimal,
        fee_type: str,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        return JournalEntry(
            reference=reference,
            description=f"{fee_type} fee {amount_usd} USD for user {user_id}",
            entry_type=LedgerEntryType.fee,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="2000", debit_usd=amount_usd, credit_usd=Decimal("0"), user_id=user_id, description=f"{fee_type} fee"),
                JournalLine(account_code=f"5100", debit_usd=Decimal("0"), credit_usd=amount_usd, user_id=None, description=f"{fee_type} fee income"),
            ],
        )

    def create_margin_transfer_entry(
        self,
        user_id: int,
        amount_usd: Decimal,
        from_type: str,
        to_type: str,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        return JournalEntry(
            reference=reference,
            description=f"Margin transfer {from_type}->{to_type} {amount_usd} USD",
            entry_type=LedgerEntryType.margin_transfer,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="2000", debit_usd=amount_usd, credit_usd=Decimal("0"), user_id=user_id, description=f"From {from_type}"),
                JournalLine(account_code="2100", debit_usd=Decimal("0"), credit_usd=amount_usd, user_id=user_id, description=f"To {to_type}"),
            ],
        )

    def create_settlement_entry(
        self,
        user_id: int,
        pnl_usd: Decimal,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        if pnl_usd >= 0:
            return JournalEntry(
                reference=reference,
                description=f"Settlement PnL {pnl_usd} USD for user {user_id}",
                entry_type=LedgerEntryType.settlement,
                created_by_user_id=created_by_user_id,
                correlation_id=correlation_id,
                lines=[
                    JournalLine(account_code="2200", debit_usd=pnl_usd, credit_usd=Decimal("0"), user_id=user_id, description="Settlement PnL"),
                    JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=pnl_usd, user_id=user_id, description="PnL credited"),
                ],
            )
        amt = abs(pnl_usd)
        return JournalEntry(
            reference=reference,
            description=f"Settlement PnL {pnl_usd} USD for user {user_id}",
            entry_type=LedgerEntryType.settlement,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="2000", debit_usd=amt, credit_usd=Decimal("0"), user_id=user_id, description="PnL debited"),
                JournalLine(account_code="2200", debit_usd=Decimal("0"), credit_usd=amt, user_id=user_id, description="Settlement PnL"),
            ],
        )

    def create_liquidation_entry(
        self,
        user_id: int,
        loss_usd: Decimal,
        insurance_used_usd: Decimal,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        lines: list[JournalLine] = []
        if loss_usd > 0:
            lines.append(JournalLine(account_code="2000", debit_usd=loss_usd, credit_usd=Decimal("0"), user_id=user_id, description="Liquidation loss"))
            lines.append(JournalLine(account_code="5300", debit_usd=Decimal("0"), credit_usd=loss_usd, user_id=user_id, description="Liquidation expense"))
        if insurance_used_usd > 0:
            lines.append(JournalLine(account_code="1400", debit_usd=insurance_used_usd, credit_usd=Decimal("0"), user_id=None, description="Insurance used"))
            lines.append(JournalLine(account_code="5400", debit_usd=Decimal("0"), credit_usd=insurance_used_usd, user_id=None, description="Insurance expense"))
        return JournalEntry(
            reference=reference,
            description=f"Liquidation for user {user_id}",
            entry_type=LedgerEntryType.liquidation,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=lines,
        )

    def create_funding_entry(
        self,
        user_id: int,
        funding_usd: Decimal,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        amount = abs(funding_usd)
        if funding_usd >= 0:
            return JournalEntry(
                reference=reference,
                description=f"Funding income {funding_usd} USD for user {user_id}",
                entry_type=LedgerEntryType.funding,
                created_by_user_id=created_by_user_id,
                correlation_id=correlation_id,
                lines=[
                    JournalLine(account_code="2000", debit_usd=amount, credit_usd=Decimal("0"), user_id=user_id, description="Funding"),
                    JournalLine(account_code="4200", debit_usd=Decimal("0"), credit_usd=amount, user_id=None, description="Funding income"),
                ],
            )
        return JournalEntry(
            reference=reference,
            description=f"Funding expense {funding_usd} USD for user {user_id}",
            entry_type=LedgerEntryType.funding,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="5200", debit_usd=amount, credit_usd=Decimal("0"), user_id=None, description="Funding expense"),
                JournalLine(account_code="2000", debit_usd=Decimal("0"), credit_usd=amount, user_id=user_id, description="Funding"),
            ],
        )

    def create_insurance_entry(
        self,
        amount_usd: Decimal,
        reason: str,
        reference: str,
        user_id: int | None = None,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        return JournalEntry(
            reference=reference,
            description=f"Insurance {reason}: {amount_usd} USD",
            entry_type=LedgerEntryType.insurance,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="1000", debit_usd=amount_usd, credit_usd=Decimal("0"), user_id=user_id, description=reason),
                JournalLine(account_code="1400", debit_usd=Decimal("0"), credit_usd=amount_usd, user_id=None, description="Insurance fund"),
            ],
        )

    def create_correction_entry(
        self,
        user_id: int,
        amount_usd: Decimal,
        reason: str,
        reference: str,
        created_by_user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> JournalEntry:
        debit = max(amount_usd, Decimal("0"))
        credit = abs(min(amount_usd, Decimal("0")))
        return JournalEntry(
            reference=reference,
            description=f"Correction {reason}: {amount_usd} USD for user {user_id}",
            entry_type=LedgerEntryType.correction,
            created_by_user_id=created_by_user_id,
            correlation_id=correlation_id,
            lines=[
                JournalLine(account_code="2000", debit_usd=debit, credit_usd=credit, user_id=user_id, description=reason),
                JournalLine(account_code="3100", debit_usd=credit, credit_usd=debit, user_id=None, description=reason),
            ],
        )
