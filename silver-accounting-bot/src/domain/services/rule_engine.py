from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from domain.enums import OrderStatus, OrderTimeInForce, OrderType, SettlementMode


class RuleCategory(str, Enum):
    compliance = "compliance"
    risk = "risk"
    settlement = "settlement"
    trading = "trading"
    supervisor = "supervisor"


@dataclass(frozen=True)
class RuleResult:
    passed: bool
    rule_name: str
    category: RuleCategory
    message: str | None = None
    severity: str = "error"


@dataclass(frozen=True)
class OrderValidationRequest:
    side: str
    order_type: OrderType
    quantity_kg: Decimal
    limit_price: Decimal | None
    time_in_force: OrderTimeInForce
    stop_price: Decimal | None
    post_only: bool
    reduce_only: bool
    user_kyc_status: str
    user_active_violations: int
    current_exposure_kg: Decimal
    current_margin_ratio: Decimal


class BusinessRuleEngine:
    _AFGHAN_TZ = timezone(timedelta(hours=4, minutes=30))

    SETTLEMENT_HOUR = 1
    SETTLEMENT_MINUTE = 25
    ORDER_MAX_LIFETIME_SECONDS = 60
    MARGIN_REQUIREMENT_PER_KG_USD = Decimal("100")
    DAILY_SETTLEMENT_DAYS = "mon-fri"

    def __init__(self, settings: dict | None = None) -> None:
        self._settings = settings or {}

    def validate_order(self, request: OrderValidationRequest) -> list[RuleResult]:
        results: list[RuleResult] = []

        if request.quantity_kg <= 0:
            results.append(RuleResult(
                passed=False, rule_name="order_quantity_positive",
                category=RuleCategory.trading, message="Quantity must be > 0",
            ))

        if request.order_type in {OrderType.limit, OrderType.stop_limit} and request.limit_price is None:
            results.append(RuleResult(
                passed=False, rule_name="limit_price_required",
                category=RuleCategory.trading, message="Limit price required",
            ))

        if request.order_type in {OrderType.stop, OrderType.stop_limit} and request.stop_price is None:
            results.append(RuleResult(
                passed=False, rule_name="stop_price_required",
                category=RuleCategory.trading, message="Stop price required",
            ))

        if request.user_kyc_status not in {"approved", "pending"}:
            results.append(RuleResult(
                passed=False, rule_name="kyc_required",
                category=RuleCategory.compliance, message="KYC approval required",
            ))

        if request.reduce_only:
            if request.side == "buy" and request.current_exposure_kg >= 0:
                results.append(RuleResult(
                    passed=False, rule_name="reduce_only_no_reduction",
                    category=RuleCategory.trading, message="Reduce-only does not reduce exposure",
                ))
            elif request.side == "sell" and request.current_exposure_kg <= 0:
                results.append(RuleResult(
                    passed=False, rule_name="reduce_only_no_reduction",
                    category=RuleCategory.trading, message="Reduce-only does not reduce exposure",
                ))

        if request.current_margin_ratio < Decimal("0.5"):
            results.append(RuleResult(
                passed=False, rule_name="margin_liquidation_threshold",
                category=RuleCategory.risk, message="Margin ratio below liquidation threshold",
                severity="critical",
            ))

        if request.user_active_violations >= 3:
            results.append(RuleResult(
                passed=False, rule_name="too_many_active_violations",
                category=RuleCategory.risk, message=f"User has {request.user_active_violations} active risk violations",
                severity="warning",
            ))

        return results

    def validate_cancellation(self, order_status: OrderStatus) -> RuleResult:
        if order_status in {OrderStatus.cancelled, OrderStatus.completed, OrderStatus.rejected, OrderStatus.expired, OrderStatus.settled}:
            return RuleResult(
                passed=False, rule_name="order_cannot_be_cancelled",
                category=RuleCategory.trading, message=f"Order in {order_status.value} cannot be cancelled",
            )
        return RuleResult(passed=True, rule_name="order_cancellable", category=RuleCategory.trading)

    def is_settlement_time(self, dt: datetime | None = None) -> bool:
        now = (dt or datetime.now(self._AFGHAN_TZ))
        return now.hour == self.SETTLEMENT_HOUR and now.minute == self.SETTLEMENT_MINUTE

    def next_settlement_time(self, from_dt: datetime | None = None) -> datetime:
        now = (from_dt or datetime.now(self._AFGHAN_TZ))
        candidate = now.replace(hour=self.SETTLEMENT_HOUR, minute=self.SETTLEMENT_MINUTE, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    def order_has_expired(self, created_at: datetime, quote_expires_at: datetime | None = None) -> bool:
        if quote_expires_at is not None:
            return datetime.now(timezone.utc) > quote_expires_at
        return datetime.now(timezone.utc) > created_at + timedelta(seconds=self.ORDER_MAX_LIFETIME_SECONDS)

    def validate_settlement_mode(self, mode: str) -> RuleResult:
        valid_modes = {e.value for e in SettlementMode}
        if mode not in valid_modes:
            return RuleResult(
                passed=False, rule_name="invalid_settlement_mode",
                category=RuleCategory.settlement, message=f"Invalid mode: {mode}",
            )
        return RuleResult(passed=True, rule_name="settlement_mode_valid", category=RuleCategory.settlement)

    def validate_supervisor_override(self, actor_role: str, reason: str | None) -> RuleResult:
        if actor_role not in {"super_admin", "admin"}:
            return RuleResult(
                passed=False, rule_name="supervisor_override_forbidden",
                category=RuleCategory.supervisor, message="Only super_admin can override",
            )
        if not reason or len(reason.strip()) < 10:
            return RuleResult(
                passed=False, rule_name="supervisor_override_reason_required",
                category=RuleCategory.supervisor, message="Override requires detailed reason (min 10 chars)",
            )
        return RuleResult(passed=True, rule_name="supervisor_override_allowed", category=RuleCategory.supervisor)

    def validate_mutual_cancellation(self, order_status: OrderStatus, counterparty_agreed: bool) -> RuleResult:
        if order_status not in {OrderStatus.open, OrderStatus.partially_filled, OrderStatus.pending}:
            return RuleResult(
                passed=False, rule_name="mutual_cancel_state_invalid",
                category=RuleCategory.trading, message="Mutual cancellation requires active order",
            )
        if not counterparty_agreed:
            return RuleResult(
                passed=False, rule_name="mutual_cancel_no_agreement",
                category=RuleCategory.trading, message="Counterparty must agree to mutual cancellation",
            )
        return RuleResult(passed=True, rule_name="mutual_cancel_valid", category=RuleCategory.trading)

    def allowed_order_status_transition(self, current: OrderStatus, next_status: OrderStatus) -> RuleResult:
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
        allowed = transitions.get(current, set())
        if next_status not in allowed:
            return RuleResult(
                passed=False, rule_name="invalid_status_transition",
                category=RuleCategory.compliance,
                message=f"Cannot transition from {current.value} to {next_status.value}",
            )
        return RuleResult(passed=True, rule_name="status_transition_valid", category=RuleCategory.compliance)
