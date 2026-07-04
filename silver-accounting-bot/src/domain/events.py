from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4


class EventVersion(str, Enum):
    v1 = "1"
    v2 = "2"
    v3 = "3"


class EventCategory(str, Enum):
    order = "order"
    trade = "trade"
    settlement = "settlement"
    payment = "payment"
    kyc = "kyc"
    wallet = "wallet"
    price = "price"
    margin = "margin"
    risk = "risk"
    admin = "admin"
    system = "system"
    audit = "audit"
    notification = "notification"
    arbitration = "arbitration"


@dataclass(frozen=True)
class DomainEvent:
    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: str = ""
    category: EventCategory = EventCategory.system
    version: EventVersion = EventVersion.v1
    aggregate_id: str | None = None
    aggregate_type: str | None = None
    actor_user_id: int | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None


@dataclass(frozen=True)
class OrderCreated(DomainEvent):
    event_type: str = "order.created"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class OrderFilled(DomainEvent):
    event_type: str = "order.filled"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class OrderSettled(DomainEvent):
    event_type: str = "order.settled"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class OrderCancelled(DomainEvent):
    event_type: str = "order.cancelled"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class TradeExecuted(DomainEvent):
    event_type: str = "trade.executed"
    category: EventCategory = EventCategory.trade


@dataclass(frozen=True)
class SettlementExecuted(DomainEvent):
    event_type: str = "settlement.executed"
    category: EventCategory = EventCategory.settlement


@dataclass(frozen=True)
class SettlementRolledBack(DomainEvent):
    event_type: str = "settlement.rolled_back"
    category: EventCategory = EventCategory.settlement


@dataclass(frozen=True)
class PaymentApproved(DomainEvent):
    event_type: str = "payment.approved"
    category: EventCategory = EventCategory.payment


@dataclass(frozen=True)
class PaymentRejected(DomainEvent):
    event_type: str = "payment.rejected"
    category: EventCategory = EventCategory.payment


@dataclass(frozen=True)
class KycStatusChanged(DomainEvent):
    event_type: str = "kyc.status_changed"
    category: EventCategory = EventCategory.kyc


@dataclass(frozen=True)
class PriceUpdated(DomainEvent):
    event_type: str = "price.updated"
    category: EventCategory = EventCategory.price


@dataclass(frozen=True)
class MarginCallTriggered(DomainEvent):
    event_type: str = "margin.call_triggered"
    category: EventCategory = EventCategory.margin


@dataclass(frozen=True)
class LiquidationExecuted(DomainEvent):
    event_type: str = "margin.liquidation"
    category: EventCategory = EventCategory.margin


@dataclass(frozen=True)
class WalletCredited(DomainEvent):
    event_type: str = "wallet.credited"
    category: EventCategory = EventCategory.wallet


@dataclass(frozen=True)
class WalletDebited(DomainEvent):
    event_type: str = "wallet.debited"
    category: EventCategory = EventCategory.wallet


@dataclass(frozen=True)
class RiskViolationCreated(DomainEvent):
    event_type: str = "risk.violation_created"
    category: EventCategory = EventCategory.risk


@dataclass(frozen=True)
class SupervisorOverride(DomainEvent):
    event_type: str = "supervisor.override"
    category: EventCategory = EventCategory.arbitration


@dataclass(frozen=True)
class JournalEntryPosted(DomainEvent):
    event_type: str = "accounting.journal_posted"
    category: EventCategory = EventCategory.audit


@dataclass(frozen=True)
class FinancialPeriodClosed(DomainEvent):
    event_type: str = "accounting.period_closed"
    category: EventCategory = EventCategory.admin


@dataclass(frozen=True)
class BackupCreated(DomainEvent):
    event_type: str = "system.backup_created"
    category: EventCategory = EventCategory.system


@dataclass(frozen=True)
class MaintenanceModeChanged(DomainEvent):
    event_type: str = "system.maintenance_changed"
    category: EventCategory = EventCategory.system


@dataclass(frozen=True)
class OrderPartiallyFilled(DomainEvent):
    event_type: str = "order.partially_filled"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class OrderExpired(DomainEvent):
    event_type: str = "order.expired"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class OrderRejected(DomainEvent):
    event_type: str = "order.rejected"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class OrderReplaced(DomainEvent):
    event_type: str = "order.replaced"
    category: EventCategory = EventCategory.order


@dataclass(frozen=True)
class PositionChanged(DomainEvent):
    event_type: str = "position.changed"
    category: EventCategory = EventCategory.trade


@dataclass(frozen=True)
class LiquidationTriggered(DomainEvent):
    event_type: str = "liquidation.triggered"
    category: EventCategory = EventCategory.margin


@dataclass(frozen=True)
class LiquidationPartial(DomainEvent):
    event_type: str = "liquidation.partial"
    category: EventCategory = EventCategory.margin


@dataclass(frozen=True)
class LiquidationCompleted(DomainEvent):
    event_type: str = "liquidation.completed"
    category: EventCategory = EventCategory.margin


@dataclass(frozen=True)
class MarginTransferExecuted(DomainEvent):
    event_type: str = "margin.transfer_executed"
    category: EventCategory = EventCategory.margin


@dataclass(frozen=True)
class FundingExecuted(DomainEvent):
    event_type: str = "funding.executed"
    category: EventCategory = EventCategory.settlement


@dataclass(frozen=True)
class InsuranceUsed(DomainEvent):
    event_type: str = "insurance.used"
    category: EventCategory = EventCategory.settlement


@dataclass(frozen=True)
class LedgerEntryPosted(DomainEvent):
    event_type: str = "ledger.entry_posted"
    category: EventCategory = EventCategory.audit


@dataclass(frozen=True)
class EmergencyShutdown(DomainEvent):
    event_type: str = "system.emergency_shutdown"
    category: EventCategory = EventCategory.system


@dataclass(frozen=True)
class RiskAlertTriggered(DomainEvent):
    event_type: str = "risk.alert_triggered"
    category: EventCategory = EventCategory.risk
