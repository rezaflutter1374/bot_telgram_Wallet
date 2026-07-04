from __future__ import annotations

from enum import Enum


class KycStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    suspended = "suspended"
    blocked = "blocked"


class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"
    limit = "limit"
    stop = "stop"
    stop_limit = "stop_limit"
    manual = "manual"


class OrderStatus(str, Enum):
    pending = "pending"
    open = "open"
    awaiting_payment = "awaiting_payment"
    awaiting_review = "awaiting_review"
    approved = "approved"
    rejected = "rejected"
    partially_filled = "partially_filled"
    filled = "filled"
    completed = "completed"
    settled = "settled"
    cancelled = "cancelled"
    expired = "expired"
    rejected_risk = "rejected_risk"

    def can_transition_to(self, target: OrderStatus) -> bool:
        transitions: dict[OrderStatus, set[OrderStatus]] = {
            OrderStatus.pending: {OrderStatus.open, OrderStatus.cancelled, OrderStatus.expired, OrderStatus.rejected, OrderStatus.rejected_risk},
            OrderStatus.open: {OrderStatus.partially_filled, OrderStatus.filled, OrderStatus.cancelled, OrderStatus.expired},
            OrderStatus.awaiting_payment: {OrderStatus.awaiting_review, OrderStatus.cancelled, OrderStatus.expired},
            OrderStatus.awaiting_review: {OrderStatus.completed, OrderStatus.rejected, OrderStatus.cancelled, OrderStatus.expired},
            OrderStatus.partially_filled: {OrderStatus.filled, OrderStatus.cancelled, OrderStatus.expired},
            OrderStatus.filled: {OrderStatus.settled, OrderStatus.cancelled},
            OrderStatus.completed: {OrderStatus.settled},
            OrderStatus.settled: set(),
            OrderStatus.cancelled: set(),
            OrderStatus.expired: set(),
            OrderStatus.rejected: set(),
            OrderStatus.rejected_risk: set(),
        }
        return target in transitions.get(self, set())


class OrderTimeInForce(str, Enum):
    gtc = "gtc"
    ioc = "ioc"
    fok = "fok"
    day = "day"


class ExecutionType(str, Enum):
    accepted = "accepted"
    triggered = "triggered"
    partial_fill = "partial_fill"
    fill = "fill"
    cancel = "cancel"
    expire = "expire"
    reject = "reject"
    risk_block = "risk_block"


class MarginMode(str, Enum):
    cross = "cross"
    isolated = "isolated"


class MarginAlertLevel(str, Enum):
    normal = "normal"
    warning = "warning"
    call = "call"
    liquidation = "liquidation"


class RiskViolationSeverity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class RiskViolationStatus(str, Enum):
    open = "open"
    acknowledged = "acknowledged"
    resolved = "resolved"


class TicketPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TicketStatus(str, Enum):
    open = "open"
    closed = "closed"


class LedgerEntryType(str, Enum):
    income = "income"
    expense = "expense"
    transfer = "transfer"
    adjustment = "adjustment"


class PaymentType(str, Enum):
    deposit = "deposit"
    withdrawal = "withdrawal"


class PaymentStatus(str, Enum):
    uploaded = "uploaded"
    awaiting_review = "awaiting_review"
    approved = "approved"
    rejected = "rejected"
    cancelled = "cancelled"


class JournalAccountType(str, Enum):
    asset = "asset"
    liability = "liability"
    equity = "equity"
    income = "income"
    expense = "expense"


class NotificationStatus(str, Enum):
    pending = "pending"
    sent = "sent"
    failed = "failed"


class MarginCallStatus(str, Enum):
    open = "open"
    resolved = "resolved"


class LiquidationStatus(str, Enum):
    triggered = "triggered"
    in_progress = "in_progress"
    partial = "partial"
    completed = "completed"
    failed = "failed"
    avoided = "avoided"


class SettlementMode(str, Enum):
    daily = "daily"
    manual = "manual"
    replay = "replay"
    rollback = "rollback"
    partial = "partial"
    recovery = "recovery"


class SettlementStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    rolled_back = "rolled_back"
    skipped = "skipped"


class OrderCancellationStatus(str, Enum):
    requested = "requested"
    admin_approved = "admin_approved"
    user_confirmed = "user_confirmed"
    rejected = "rejected"
    completed = "completed"


class CircuitBreakerState(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


class RiskScoreLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    extreme = "extreme"


class LiquidationType(str, Enum):
    manual = "manual"
    auto = "auto"
    forced = "forced"


class DeadLetterReason(str, Enum):
    max_retries = "max_retries"
    unhandled_exception = "unhandled_exception"
    poison_message = "poison_message"
    circuit_breaker_open = "circuit_breaker_open"
