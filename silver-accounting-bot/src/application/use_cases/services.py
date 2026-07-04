from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

from application.dto.order import OrderDTO
from application.dto.payment import PaymentDTO
from application.dto.price import PriceDTO
from application.dto.settlement import (
    SettlementHistoryItemDTO,
    SettlementResultDTO,
    SettlementStatusDTO,
    SettlementSummaryDTO,
)
from application.dto.ticket import TicketDTO
from application.dto.user import UserDTO
from application.errors import Forbidden, InsufficientDeposit, NotFound, QuoteExpired, ValidationError
from application.ports.repositories.circuit_breaker_repo import CircuitBreakerRepo
from application.ports.repositories.cleanup_repo import CleanupRepo
from application.ports.repositories.dead_letter_repo import DeadLetterRepo
from application.ports.repositories.risk_calc_repo import RiskCalcRepo
from application.ports.settlement_engine import SettlementEngine
from application.ports.repositories.backup_repo import BackupRepo
from application.ports.repositories.accounting_repo import AccountingRepo
from application.ports.repositories.ledger_repo import LedgerRepo
from application.ports.repositories.liquidation_repo import LiquidationRepo
from application.ports.repositories.audit_repo import AuditRepo
from application.ports.repositories.notification_repo import NotificationRepo
from application.ports.repositories.order_repo import OrderRepo
from application.ports.repositories.payment_repo import PaymentReconciliationRepo, PaymentRepo
from application.ports.repositories.position_repo import PositionRepo
from application.ports.repositories.price_repo import PriceRepo
from application.ports.repositories.risk_repo import RiskRepo
from application.ports.repositories.role_repo import RoleRepo
from application.ports.repositories.runtime_state_repo import RuntimeStateRepo
from application.ports.repositories.ticket_repo import TicketRepo
from application.ports.repositories.uow import UnitOfWork
from application.ports.repositories.user_repo import UserRepo
from application.ports.repositories.wallet_repo import WalletRepo
from core.time import utc_now
from domain.enums import (
    ExecutionType,
    KycStatus,
    OrderTimeInForce,
    OrderCancellationStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    PaymentStatus,
    PaymentType,
    RiskViolationSeverity,
    TicketPriority,
    TicketStatus,
)
from domain.event_bus import EventBus
from domain.events import (
    DomainEvent,
    FinancialPeriodClosed,
    FundingExecuted,
    InsuranceUsed,
    KycStatusChanged,
    LedgerEntryPosted,
    LiquidationCompleted,
    MarginTransferExecuted,
    OrderCreated,
    OrderFilled,
    OrderReplaced,
    OrderSettled,
    PaymentApproved,
    PaymentRejected,
    PriceUpdated,
    RiskAlertTriggered,
    SettlementExecuted,
    SettlementRolledBack,
    TradeExecuted,
)
from infrastructure.event_bus.store import EventStore
from domain.services.arbitration import ArbitrationHandler, ArbitrationReason, ArbitrationStatus
from domain.services.ledger import LedgerService
from domain.services.margin import MarginCalculator
from domain.services.margin_engine import MarginEngine
from domain.services.matching_engine import MatchingEngine
from domain.services.position_engine import PositionEngine
from domain.services.risk_engine import RiskEngine
from domain.services.liquidation_engine import LiquidationEngine, LiquidationOrder
from domain.services.rule_engine import BusinessRuleEngine, OrderValidationRequest


class AppServices:
    def __init__(
        self,
        uow: UnitOfWork,
        users: UserRepo,
        wallets: WalletRepo,
        roles: RoleRepo,
        prices: PriceRepo,
        payments: PaymentRepo,
        accounting: AccountingRepo,
        notifications: NotificationRepo,
        audit: AuditRepo,
        risk: RiskRepo,
        orders: OrderRepo,
        positions: PositionRepo,
        tickets: TicketRepo,
        backup: BackupRepo,
        margin_calculator: MarginCalculator,
        runtime_state: RuntimeStateRepo | None = None,
        settlement_engine: SettlementEngine | None = None,
        circuit_breaker_repo: CircuitBreakerRepo | None = None,
        dead_letter_repo: DeadLetterRepo | None = None,
        cleanup_repo: CleanupRepo | None = None,
        risk_calc: RiskCalcRepo | None = None,
        rule_engine: BusinessRuleEngine | None = None,
        arbitration_handler: ArbitrationHandler | None = None,
        event_bus: EventBus | None = None,
        event_store: EventStore | None = None,
        payment_reconciliation: PaymentReconciliationRepo | None = None,
        ledger_repo: LedgerRepo | None = None,
        liquidation_repo: LiquidationRepo | None = None,
        matching_engine: MatchingEngine | None = None,
        ledger_service: LedgerService | None = None,
        position_engine: PositionEngine | None = None,
        margin_engine: MarginEngine | None = None,
        risk_engine: RiskEngine | None = None,
        liquidation_engine: LiquidationEngine | None = None,
    ) -> None:
        self._uow = uow
        self._users = users
        self._wallets = wallets
        self._roles = roles
        self._prices = prices
        self._payments = payments
        self._accounting = accounting
        self._notifications = notifications
        self._audit = audit
        self._risk = risk
        self._orders = orders
        self._positions = positions
        self._tickets = tickets
        self._backup = backup
        self._margin = margin_calculator
        self._runtime_state = runtime_state
        self._settlement_engine = settlement_engine
        self._circuit_breaker = circuit_breaker_repo
        self._dead_letter = dead_letter_repo
        self._cleanup = cleanup_repo
        self._risk_calc = risk_calc
        self._rules = rule_engine or BusinessRuleEngine()
        self._arbitration = arbitration_handler or ArbitrationHandler()
        self._event_bus = event_bus
        self._event_store = event_store
        self._payment_reconciliation = payment_reconciliation
        self._ledger_repo = ledger_repo
        self._liquidation_repo = liquidation_repo
        self._matching_engine = matching_engine or MatchingEngine()
        self._ledger_service = ledger_service or LedgerService()
        self._position_engine = position_engine or PositionEngine()
        self._margin_engine = margin_engine or MarginEngine(margin_calculator)
        self._risk_engine = risk_engine or RiskEngine()
        self._liquidation_engine = liquidation_engine or LiquidationEngine()

    async def _publish(self, event: DomainEvent) -> None:
        if self._event_store is not None:
            await self._event_store.append(event)
        if self._event_bus is not None:
            await self._event_bus.publish(event)

    async def ensure_rbac_defaults(self) -> None:
        async with self._uow.transaction():
            await self._roles.ensure_defaults()

    async def ensure_accounting_defaults(self) -> None:
        async with self._uow.transaction():
            await self._accounting.ensure_default_chart()

    async def ensure_super_admin(self, user_id: int, telegram_id: int, super_admin_ids: set[int]) -> None:
        if telegram_id not in super_admin_ids:
            return
        async with self._uow.transaction():
            await self._roles.grant_role(user_id, "super_admin")
            await self._audit.add(user_id, "rbac.super_admin_assigned", "user", str(user_id), {"telegram_id": telegram_id})

    async def register_or_get_user(
        self,
        telegram_id: int,
        *,
        language_code: str | None = None,
    ) -> UserDTO:
        normalized_language = language_code.strip().lower() if language_code else None
        async with self._uow.transaction():
            existing = await self._users.get_by_telegram_id(telegram_id)
            if existing is not None:
                await self._wallets.ensure_wallet(existing["id"])
                if normalized_language is not None and existing.get("language_code") != normalized_language:
                    existing = await self._users.set_language_code(existing["id"], normalized_language)
                return UserDTO(**existing)
            created = await self._users.create_user(
                telegram_id=telegram_id,
                full_name=None,
                phone_number=None,
                kyc_status=KycStatus.pending,
                language_code=normalized_language,
            )
            await self._wallets.ensure_wallet(created["id"])
            await self._roles.grant_role(created["id"], "guest")
            return UserDTO(**created)

    async def get_user_by_telegram_id(self, telegram_id: int) -> UserDTO:
        async with self._uow.transaction():
            row = await self._users.get_by_telegram_id(telegram_id)
            if row is None:
                raise NotFound("User not found")
            return UserDTO(**row)

    async def user_has_permission(self, user_id: int, permission: str) -> bool:
        async with self._uow.transaction():
            return await self._roles.user_has_permission(user_id, permission)

    async def submit_kyc(
        self,
        user_id: int,
        full_name: str,
        phone_number: str,
        national_id_enc: str,
        passport_file_id_enc: str,
        selfie_file_id_enc: str,
        verification_docs_file_ids_enc: list[str],
    ) -> UserDTO:
        if not full_name.strip():
            raise ValidationError("Full name is required")
        if not phone_number.strip():
            raise ValidationError("Phone number is required")
        async with self._uow.transaction():
            user = await self._users.get(user_id)
            if user is None:
                raise NotFound("User not found")
            updated = await self._users.update_kyc(
                user_id=user_id,
                full_name=full_name,
                phone_number=phone_number,
                national_id_enc=national_id_enc,
                passport_file_id_enc=passport_file_id_enc,
                selfie_file_id_enc=selfie_file_id_enc,
                verification_docs_file_ids_enc=verification_docs_file_ids_enc,
                kyc_status=KycStatus.pending,
            )
            await self._roles.grant_role(user_id, "verified_user")
            return UserDTO(**updated)

    async def review_kyc(self, actor_user_id: int, target_user_id: int, status: KycStatus, note: str | None) -> None:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "verify_identity")
            if not allowed:
                raise Forbidden("Not allowed")
            user = await self._users.get(target_user_id)
            if user is None:
                raise NotFound("User not found")
            await self._users.set_kyc_status(target_user_id, status)
            await self._audit.add(actor_user_id, "kyc.review", "user", str(target_user_id), {"status": status.value, "note": note})
            await self._notifications.enqueue(target_user_id, "kyc.status_changed", {"status": status.value, "note": note})
            await self._publish(KycStatusChanged(
                aggregate_id=str(target_user_id),
                aggregate_type="user",
                actor_user_id=actor_user_id,
                payload={"status": status.value, "note": note},
            ))

    async def set_price(
        self,
        actor_user_id: int,
        buy_price: Decimal,
        sell_price: Decimal,
        spread: Decimal = Decimal("0"),
        commission: Decimal = Decimal("0"),
        premium: Decimal = Decimal("0"),
        discount: Decimal = Decimal("0"),
    ) -> PriceDTO:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_prices")
            if not allowed:
                raise Forbidden("Not allowed")
            row = await self._prices.upsert(
                buy_price=buy_price,
                sell_price=sell_price,
                spread=spread,
                commission=commission,
                premium=premium,
                discount=discount,
            )
            await self._publish(PriceUpdated(
                aggregate_id=f"price:{row.get('updated_at')}",
                aggregate_type="price",
                actor_user_id=actor_user_id,
                payload={"buy_price": str(buy_price), "sell_price": str(sell_price), "spread": str(spread)},
            ))
            return PriceDTO(**row)

    async def get_price(self) -> PriceDTO:
        async with self._uow.transaction():
            row = await self._prices.get_latest()
            if row is None:
                raise NotFound("Price not set")
            return PriceDTO(**row)

    def _calculate_fee(self, *, notional_usd: Decimal, commission: Decimal, quantity_kg: Decimal) -> Decimal:
        if commission <= Decimal("0"):
            return Decimal("0")
        if commission <= Decimal("1"):
            return (notional_usd * commission).quantize(Decimal("0.000001"))
        return (commission * quantity_kg).quantize(Decimal("0.000001"))

    def _trade_price_crosses(self, incoming: dict, resting: dict) -> bool:
        if incoming["side"] == OrderSide.buy:
            if incoming["order_type"] == OrderType.market:
                return True
            return Decimal(resting["quoted_price"]) <= Decimal(incoming["quoted_price"])
        if incoming["order_type"] == OrderType.market:
            return True
        return Decimal(resting["quoted_price"]) >= Decimal(incoming["quoted_price"])

    async def create_order(
        self,
        user_id: int,
        side: OrderSide,
        order_type: OrderType,
        quantity_kg: Decimal,
        limit_price: Decimal | None,
        *,
        time_in_force: OrderTimeInForce = OrderTimeInForce.gtc,
        stop_price: Decimal | None = None,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> OrderDTO:
        if quantity_kg <= 0:
            raise ValidationError("Quantity must be > 0")
        async with self._uow.transaction():
            if idempotency_key:
                existing = await self._orders.get_by_idempotency_key(idempotency_key)
                if existing is not None:
                    return OrderDTO(**existing)
            user = await self._users.get(user_id)
            if user is None:
                raise NotFound("User not found")
            violations = await self._risk.list_violations(user_id, limit=10)
            active_violations = [v for v in violations if v.get("status", "").lower() == "open"]
            position = await self._positions.get_position(user_id)
            net_kg = Decimal(position["net_kg"])
            wallet = await self._wallets.get_wallet(user_id)
            if wallet is None:
                raise NotFound("Wallet not found")
            margin_ratio = Decimal(wallet.get("margin_ratio", "999999"))

            validation_req = OrderValidationRequest(
                side=side.value,
                order_type=order_type,
                quantity_kg=quantity_kg,
                limit_price=limit_price,
                time_in_force=time_in_force,
                stop_price=stop_price,
                post_only=post_only,
                reduce_only=reduce_only,
                user_kyc_status=user.get("kyc_status", "pending"),
                user_active_violations=len(active_violations),
                current_exposure_kg=abs(net_kg),
                current_margin_ratio=margin_ratio,
            )
            rule_results = self._rules.validate_order(validation_req)
            errors = [r for r in rule_results if not r.passed]
            if errors:
                raise ValidationError("; ".join(f"{e.rule_name}: {e.message}" for e in errors))

            price_row = await self._prices.get_latest()
            if price_row is None:
                raise NotFound("Price not set")
            price = PriceDTO(**price_row)
            current_price = price.buy_price if side == OrderSide.buy else price.sell_price
            if order_type in {OrderType.limit, OrderType.stop_limit}:
                if limit_price is None or limit_price <= 0:
                    raise ValidationError("Limit price required")
                quoted_price = limit_price
            else:
                quoted_price = current_price
            if order_type in {OrderType.stop, OrderType.stop_limit} and (stop_price is None or stop_price <= 0):
                raise ValidationError("Stop price required")

            quote_expires_at = utc_now() + timedelta(seconds=60)
            exposure_after = (net_kg + quantity_kg) if side == OrderSide.buy else (net_kg - quantity_kg)
            active_rule = await self._risk.get_active_rule()
            if active_rule is not None and active_rule.get("enabled", False):
                max_order = active_rule["max_order_kg"]
                max_exposure = active_rule["max_user_exposure_kg"]
                if max_order > 0 and quantity_kg > max_order:
                    await self._risk.create_violation(
                        user_id=user_id,
                        order_id=None,
                        severity=RiskViolationSeverity.warning.value,
                        violation_type="max_order_size",
                        message="Order size exceeds configured risk limit",
                        payload={"quantity_kg": str(quantity_kg), "max_order_kg": str(max_order)},
                    )
                    raise ValidationError("Order size exceeds risk limit")
                if max_exposure > 0 and abs(exposure_after) > max_exposure:
                    await self._risk.create_violation(
                        user_id=user_id,
                        order_id=None,
                        severity=RiskViolationSeverity.critical.value,
                        violation_type="max_user_exposure",
                        message="Exposure exceeds configured risk limit",
                        payload={"exposure_after_kg": str(abs(exposure_after)), "max_user_exposure_kg": str(max_exposure)},
                    )
                    raise ValidationError("Exposure exceeds risk limit")
                if active_rule.get("max_leverage", Decimal("0")) > 0 and abs(exposure_after) > 0:
                    required_equity = abs(exposure_after) * current_price / active_rule["max_leverage"]
                    available_equity = (
                        wallet["available_balance_usd"] + wallet["frozen_balance_usd"] + wallet["margin_balance_usd"]
                    )
                    if required_equity > available_equity:
                        await self._risk.create_violation(
                            user_id=user_id,
                            order_id=None,
                            severity=RiskViolationSeverity.critical.value,
                            violation_type="max_leverage",
                            message="Leverage limit exceeded",
                            payload={"required_equity_usd": str(required_equity), "available_equity_usd": str(available_equity)},
                        )
                        raise ValidationError("Leverage exceeds risk limit")
            snapshot = self._margin.snapshot(
                available_balance_usd=wallet["available_balance_usd"],
                frozen_balance_usd=wallet["frozen_balance_usd"],
                margin_balance_usd=wallet["margin_balance_usd"],
                floating_pnl_usd=(current_price - position["avg_price_usd"]) * net_kg,
                exposure_kg=abs(exposure_after),
                mark_price_usd=current_price,
                average_entry_price_usd=position["avg_price_usd"],
            )
            if snapshot.free_margin_usd < Decimal("0"):
                raise InsufficientDeposit("Deposit requirement not satisfied")
            if reduce_only and ((side == OrderSide.buy and net_kg >= 0) or (side == OrderSide.sell and net_kg <= 0)):
                raise ValidationError("Reduce-only order does not reduce exposure")

            reserve_balance = Decimal("0")
            reserve_margin = Decimal("0")
            notional_value = (quoted_price * quantity_kg).quantize(Decimal("0.000001"))
            if side == OrderSide.buy:
                reserve_balance = notional_value
                if wallet["available_balance_usd"] < reserve_balance:
                    raise InsufficientDeposit("Insufficient available balance")
                await self._wallets.freeze(user_id, reserve_balance)
            if abs(exposure_after) > abs(net_kg):
                reserve_margin = self._margin.required_deposit_usd(abs(exposure_after) - abs(net_kg))
                if wallet["available_balance_usd"] - reserve_balance < reserve_margin:
                    raise InsufficientDeposit("Insufficient margin buffer")
                await self._wallets.transfer_available_to_margin(user_id, reserve_margin)

            order = await self._orders.create_order(
                user_id=user_id,
                side=side,
                order_type=order_type,
                time_in_force=time_in_force,
                quantity_kg=quantity_kg,
                quoted_price=quoted_price,
                limit_price=limit_price if order_type in {OrderType.limit, OrderType.stop_limit} else None,
                stop_price=stop_price,
                reserved_balance_usd=reserve_balance,
                reserved_margin_usd=reserve_margin,
                post_only=post_only,
                reduce_only=reduce_only,
                client_order_id=client_order_id,
                idempotency_key=idempotency_key,
                quote_expires_at=quote_expires_at,
            )
            await self._publish(OrderCreated(
                aggregate_id=str(order["id"]),
                aggregate_type="order",
                actor_user_id=user_id,
                payload={
                    "side": side.value,
                    "order_type": order_type.value,
                    "quantity_kg": str(quantity_kg),
                    "quoted_price": str(quoted_price),
                },
            ))
            await self._orders.add_execution_report(
                order_id=order["id"],
                execution_type=ExecutionType.accepted,
                status=order["status"],
                quantity_kg=Decimal("0"),
                price_usd=quoted_price,
                fee_usd=Decimal("0"),
                payload={"client_order_id": client_order_id, "idempotency_key": idempotency_key},
            )
            triggered = order_type in {OrderType.market, OrderType.limit, OrderType.manual}
            if not triggered:
                return OrderDTO(**order)

            opposite_side = OrderSide.sell if side == OrderSide.buy else OrderSide.buy
            candidates = await self._orders.list_open_orders(side=opposite_side, limit=200)
            matching = [
                row
                for row in candidates
                if row["user_id"] != user_id and row["is_triggered"] and self._trade_price_crosses(order, row)
            ]
            if post_only and matching:
                if reserve_balance > 0:
                    await self._wallets.unfreeze(user_id, reserve_balance)
                if reserve_margin > 0:
                    await self._wallets.release_margin_to_available(user_id, reserve_margin)
                await self._orders.release_reservations(order["id"])
                rejected = await self._orders.set_status(order["id"], OrderStatus.rejected)
                await self._orders.add_execution_report(
                    order_id=order["id"],
                    execution_type=ExecutionType.reject,
                    status=OrderStatus.rejected,
                    quantity_kg=Decimal("0"),
                    price_usd=quoted_price,
                    fee_usd=Decimal("0"),
                    payload={"reason": "post_only_would_cross"},
                )
                return OrderDTO(**rejected)

            if order_type == OrderType.market and time_in_force == OrderTimeInForce.gtc:
                time_in_force = OrderTimeInForce.ioc

            if time_in_force == OrderTimeInForce.fok:
                available_qty = sum(Decimal(row["remaining_quantity_kg"]) for row in matching)
                if available_qty < quantity_kg:
                    if reserve_balance > 0:
                        await self._wallets.unfreeze(user_id, reserve_balance)
                    if reserve_margin > 0:
                        await self._wallets.release_margin_to_available(user_id, reserve_margin)
                    await self._orders.release_reservations(order["id"])
                    cancelled = await self._orders.set_status(order["id"], OrderStatus.cancelled)
                    await self._orders.add_execution_report(
                        order_id=order["id"],
                        execution_type=ExecutionType.cancel,
                        status=OrderStatus.cancelled,
                        quantity_kg=Decimal("0"),
                        price_usd=quoted_price,
                        fee_usd=Decimal("0"),
                        payload={"reason": "fok_insufficient_liquidity"},
                    )
                    return OrderDTO(**cancelled)

            incoming = order
            for resting in matching:
                if Decimal(incoming["remaining_quantity_kg"]) <= 0:
                    break
                fill_qty = min(Decimal(incoming["remaining_quantity_kg"]), Decimal(resting["remaining_quantity_kg"]))
                if fill_qty <= 0:
                    continue
                trade_price = Decimal(resting["quoted_price"])
                trade_notional = (fill_qty * trade_price).quantize(Decimal("0.000001"))
                buy_fee = self._calculate_fee(notional_usd=trade_notional, commission=price.commission, quantity_kg=fill_qty)
                sell_fee = self._calculate_fee(notional_usd=trade_notional, commission=price.commission, quantity_kg=fill_qty)
                incoming_release_balance = Decimal("0")
                incoming_release_margin = Decimal("0")
                resting_release_balance = Decimal("0")
                resting_release_margin = Decimal("0")
                if Decimal(incoming["remaining_quantity_kg"]) > 0:
                    incoming_release_balance = (
                        Decimal(incoming["reserved_balance_usd"]) * fill_qty / Decimal(incoming["remaining_quantity_kg"])
                    ).quantize(Decimal("0.01")) if Decimal(incoming["reserved_balance_usd"]) > 0 else Decimal("0")
                    incoming_release_margin = (
                        Decimal(incoming["reserved_margin_usd"]) * fill_qty / Decimal(incoming["remaining_quantity_kg"])
                    ).quantize(Decimal("0.01")) if Decimal(incoming["reserved_margin_usd"]) > 0 else Decimal("0")
                if Decimal(resting["remaining_quantity_kg"]) > 0:
                    resting_release_balance = (
                        Decimal(resting["reserved_balance_usd"]) * fill_qty / Decimal(resting["remaining_quantity_kg"])
                    ).quantize(Decimal("0.01")) if Decimal(resting["reserved_balance_usd"]) > 0 else Decimal("0")
                    resting_release_margin = (
                        Decimal(resting["reserved_margin_usd"]) * fill_qty / Decimal(resting["remaining_quantity_kg"])
                    ).quantize(Decimal("0.01")) if Decimal(resting["reserved_margin_usd"]) > 0 else Decimal("0")
                incoming_status = OrderStatus.filled if Decimal(incoming["remaining_quantity_kg"]) == fill_qty else OrderStatus.partially_filled
                resting_status = OrderStatus.filled if Decimal(resting["remaining_quantity_kg"]) == fill_qty else OrderStatus.partially_filled
                trade = await self._orders.create_trade(
                    maker_order_id=resting["id"],
                    taker_order_id=incoming["id"],
                    buy_order_id=incoming["id"] if side == OrderSide.buy else resting["id"],
                    sell_order_id=incoming["id"] if side == OrderSide.sell else resting["id"],
                    match_key=f"{incoming['id']}:{resting['id']}:{int(utc_now().timestamp() * 1000000)}",
                    price_usd=trade_price,
                    quantity_kg=fill_qty,
                    buy_fee_usd=buy_fee,
                    sell_fee_usd=sell_fee,
                    slippage_bps=(abs(trade_price - Decimal(incoming["quoted_price"])) / Decimal(incoming["quoted_price"]) * Decimal("10000")).quantize(Decimal("0.000001")),
                    payload={"maker_order_id": resting["id"], "taker_order_id": incoming["id"]},
                    executed_at=utc_now(),
                )
                incoming = await self._orders.apply_fill(
                    order_id=incoming["id"],
                    filled_quantity_kg=fill_qty,
                    fill_price_usd=trade_price,
                    fee_usd=buy_fee if side == OrderSide.buy else sell_fee,
                    slippage_bps=trade["slippage_bps"],
                    status=incoming_status,
                    executed_at=utc_now(),
                )
                resting = await self._orders.apply_fill(
                    order_id=resting["id"],
                    filled_quantity_kg=fill_qty,
                    fill_price_usd=trade_price,
                    fee_usd=sell_fee if side == OrderSide.buy else buy_fee,
                    slippage_bps=trade["slippage_bps"],
                    status=resting_status,
                    executed_at=utc_now(),
                )
                await self._positions.apply_trade(user_id=incoming["user_id"], side=incoming["side"].value, quantity_kg=fill_qty, price_usd=trade_price)
                await self._positions.apply_trade(user_id=resting["user_id"], side=resting["side"].value, quantity_kg=fill_qty, price_usd=trade_price)
                await self._wallets.apply_trade_cashflow(
                    user_id=incoming["user_id"],
                    side=incoming["side"].value,
                    gross_amount_usd=trade_notional,
                    fee_usd=buy_fee if incoming["side"] == OrderSide.buy else sell_fee,
                    reserved_balance_released_usd=incoming_release_balance,
                    reserved_margin_released_usd=incoming_release_margin,
                )
                await self._wallets.apply_trade_cashflow(
                    user_id=resting["user_id"],
                    side=resting["side"].value,
                    gross_amount_usd=trade_notional,
                    fee_usd=buy_fee if resting["side"] == OrderSide.buy else sell_fee,
                    reserved_balance_released_usd=resting_release_balance,
                    reserved_margin_released_usd=resting_release_margin,
                )
                await self._orders.add_execution_report(
                    order_id=incoming["id"],
                    trade_id=trade["id"],
                    execution_type=ExecutionType.fill if incoming_status == OrderStatus.filled else ExecutionType.partial_fill,
                    status=incoming_status,
                    quantity_kg=fill_qty,
                    price_usd=trade_price,
                    fee_usd=buy_fee if incoming["side"] == OrderSide.buy else sell_fee,
                    payload={"match_key": trade["match_key"]},
                )
                await self._orders.add_execution_report(
                    order_id=resting["id"],
                    trade_id=trade["id"],
                    execution_type=ExecutionType.fill if resting_status == OrderStatus.filled else ExecutionType.partial_fill,
                    status=resting_status,
                    quantity_kg=fill_qty,
                    price_usd=trade_price,
                    fee_usd=buy_fee if resting["side"] == OrderSide.buy else sell_fee,
                    payload={"match_key": trade["match_key"]},
                )

            await self._publish(OrderCreated(
                aggregate_id=str(order["id"]),
                aggregate_type="order",
                actor_user_id=user_id,
                payload={
                    "side": side.value,
                    "order_type": order_type.value,
                    "quantity_kg": str(quantity_kg),
                    "quoted_price": str(quoted_price),
                },
            ))

            if Decimal(incoming["remaining_quantity_kg"]) > 0 and time_in_force in {OrderTimeInForce.ioc, OrderTimeInForce.fok}:
                if Decimal(incoming["reserved_balance_usd"]) > 0:
                    await self._wallets.unfreeze(incoming["user_id"], Decimal(incoming["reserved_balance_usd"]))
                if Decimal(incoming["reserved_margin_usd"]) > 0:
                    await self._wallets.release_margin_to_available(incoming["user_id"], Decimal(incoming["reserved_margin_usd"]))
                await self._orders.release_reservations(incoming["id"])
                incoming = await self._orders.set_status(incoming["id"], OrderStatus.cancelled)
                await self._orders.add_execution_report(
                    order_id=incoming["id"],
                    execution_type=ExecutionType.cancel,
                    status=OrderStatus.cancelled,
                    quantity_kg=Decimal("0"),
                    price_usd=quoted_price,
                    fee_usd=Decimal("0"),
                    payload={"reason": "time_in_force_cancelled_remainder"},
                )
            return OrderDTO(**order)

    async def attach_receipt(self, user_id: int, order_id: int, receipt_file_id_enc: str) -> OrderDTO:
        async with self._uow.transaction():
            order = await self._orders.get(order_id)
            if order is None:
                raise NotFound("Order not found")
            if order["user_id"] != user_id:
                raise Forbidden("Not allowed")
            if utc_now() > order["quote_expires_at"]:
                raise QuoteExpired("Quote expired")
            if order["status"] not in {OrderStatus.pending, OrderStatus.awaiting_payment}:
                raise ValidationError("Invalid order state")
            updated = await self._orders.attach_receipt(
                order_id=order_id,
                receipt_file_id_enc=receipt_file_id_enc,
                status=OrderStatus.awaiting_review,
            )
            return OrderDTO(**updated)

    async def approve_order(self, actor_user_id: int, order_id: int, approve: bool) -> OrderDTO:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "approve_payments")
            if not allowed:
                raise Forbidden("Not allowed")
            order = await self._orders.get(order_id)
            if order is None:
                raise NotFound("Order not found")
            cancellation = await self._orders.get_cancellation(order_id)
            if cancellation is not None and cancellation["status"] in {
                OrderCancellationStatus.requested,
                OrderCancellationStatus.admin_approved,
                OrderCancellationStatus.user_confirmed,
            }:
                raise ValidationError("Order cancellation in progress")
            current = OrderStatus(order["status"])
            if not current.can_transition_to(OrderStatus.rejected if not approve else OrderStatus.completed):
                raise ValidationError(f"Order in {current.value} cannot be approved/rejected")

            if not approve:
                updated = await self._orders.set_status(order_id, OrderStatus.rejected)
                await self._notifications.enqueue(order["user_id"], "order.rejected", {"order_id": order_id})
                return OrderDTO(**updated)

            await self._positions.adjust_net_kg(
                user_id=order["user_id"],
                delta_kg=order["quantity_kg"] if order["side"] == OrderSide.buy else -order["quantity_kg"],
                avg_price_usd=order["quoted_price"],
            )
            updated = await self._orders.set_status(order_id, OrderStatus.completed)
            await self._notifications.enqueue(order["user_id"], "order.completed", {"order_id": order_id})
            await self._publish(OrderFilled(
                aggregate_id=str(order_id),
                aggregate_type="order",
                actor_user_id=actor_user_id,
                payload={"user_id": order["user_id"], "side": order["side"], "quantity_kg": str(order["quantity_kg"])},
            ))
            return OrderDTO(**updated)

    async def create_ticket(self, user_id: int, subject: str, priority: TicketPriority) -> TicketDTO:
        if not subject.strip():
            raise ValidationError("Subject required")
        async with self._uow.transaction():
            ticket = await self._tickets.create_ticket(user_id=user_id, subject=subject, priority=priority)
            await self._tickets.add_message(
                ticket_id=ticket["id"],
                author_user_id=user_id,
                author_role="customer",
                message=subject,
                attachment_file_ids_enc=[],
            )
            return TicketDTO(**ticket)

    async def reply_ticket(
        self,
        actor_user_id: int,
        ticket_id: int,
        message: str,
        attachment_file_ids_enc: list[str],
    ) -> None:
        if not message.strip():
            raise ValidationError("Message required")
        async with self._uow.transaction():
            ticket = await self._tickets.get(ticket_id)
            if ticket is None:
                raise NotFound("Ticket not found")
            roles = await self._roles.get_user_roles(actor_user_id)
            is_support = "support" in roles or "admin" in roles or "super_admin" in roles
            if not is_support and ticket["user_id"] != actor_user_id:
                raise Forbidden("Not allowed")
            author_role = "support" if is_support else "customer"
            await self._tickets.add_message(
                ticket_id=ticket_id,
                author_user_id=actor_user_id if not is_support else None,
                author_role=author_role,
                message=message,
                attachment_file_ids_enc=attachment_file_ids_enc,
            )

    async def close_ticket(self, actor_user_id: int, ticket_id: int) -> None:
        async with self._uow.transaction():
            ticket = await self._tickets.get(ticket_id)
            if ticket is None:
                raise NotFound("Ticket not found")
            roles = await self._roles.get_user_roles(actor_user_id)
            is_support = "support" in roles or "admin" in roles or "super_admin" in roles
            if not is_support and ticket["user_id"] != actor_user_id:
                raise Forbidden("Not allowed")
            await self._tickets.set_status(ticket_id, TicketStatus.closed)

    async def reopen_ticket(self, actor_user_id: int, ticket_id: int) -> None:
        async with self._uow.transaction():
            ticket = await self._tickets.get(ticket_id)
            if ticket is None:
                raise NotFound("Ticket not found")
            roles = await self._roles.get_user_roles(actor_user_id)
            is_support = "support" in roles or "admin" in roles or "super_admin" in roles
            if not is_support and ticket["user_id"] != actor_user_id:
                raise Forbidden("Not allowed")
            await self._tickets.set_status(ticket_id, TicketStatus.open)

    async def add_internal_ticket_note(self, actor_user_id: int, ticket_id: int, message: str) -> None:
        if not message.strip():
            raise ValidationError("Message required")
        async with self._uow.transaction():
            ticket = await self._tickets.get(ticket_id)
            if ticket is None:
                raise NotFound("Ticket not found")
            roles = await self._roles.get_user_roles(actor_user_id)
            is_support = "support" in roles or "admin" in roles or "super_admin" in roles
            if not is_support:
                raise Forbidden("Not allowed")
            await self._tickets.add_message(
                ticket_id=ticket_id,
                author_user_id=None,
                author_role="internal_note",
                message=message,
                attachment_file_ids_enc=[],
            )

    async def list_tickets(
        self,
        actor_user_id: int,
        *,
        status: TicketStatus | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        async with self._uow.transaction():
            roles = await self._roles.get_user_roles(actor_user_id)
            is_support = "support" in roles or "admin" in roles or "super_admin" in roles
            return await self._tickets.list_tickets(
                user_id=None if is_support else actor_user_id,
                status=status,
                query=query,
                limit=limit,
            )

    async def get_wallet(self, user_id: int) -> dict:
        async with self._uow.transaction():
            wallet = await self._wallets.get_wallet(user_id)
            if wallet is None:
                raise NotFound("Wallet not found")
            return wallet

    async def list_orders(self, user_id: int, limit: int = 10) -> list[dict]:
        async with self._uow.transaction():
            return await self._orders.list_for_user(user_id, limit=limit)

    async def grant_role(self, actor_user_id: int, target_telegram_id: int, role: str) -> None:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_roles")
            if not allowed:
                raise Forbidden("Not allowed")
            user = await self._users.get_by_telegram_id(target_telegram_id)
            if user is None:
                created = await self._users.create_user(
                    telegram_id=target_telegram_id,
                    full_name=None,
                    phone_number=None,
                    kyc_status=KycStatus.pending,
                )
                await self._wallets.ensure_wallet(created["id"])
                await self._roles.grant_role(created["id"], "guest")
                user_id = created["id"]
            else:
                user_id = user["id"]
            await self._roles.grant_role(user_id, role)
            await self._audit.add(actor_user_id, "rbac.role_granted", "user", str(user_id), {"role": role, "telegram_id": target_telegram_id})

    async def set_risk_rule(self, actor_user_id: int, name: str, max_user_exposure_kg: Decimal, max_order_kg: Decimal, enabled: bool) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "approve_critical_actions")
            if not allowed:
                raise Forbidden("Not allowed")
            row = await self._risk.upsert_rule(name, max_user_exposure_kg, max_order_kg, enabled)
            await self._audit.add(actor_user_id, "risk.rule_upsert", "risk_rule", str(row["id"]), row)
            return row

    async def create_payment_request(
        self,
        user_id: int,
        payment_type: PaymentType,
        amount_usd: Decimal,
        receipt_file_ids_enc: list[str],
        bank_account_id: int | None,
        reference_number: str | None = None,
    ) -> PaymentDTO:
        if amount_usd <= 0:
            raise ValidationError("Amount must be > 0")
        if not receipt_file_ids_enc:
            raise ValidationError("Receipt required")
        async with self._uow.transaction():
            user = await self._users.get(user_id)
            if user is None:
                raise NotFound("User not found")
            if user["kyc_status"] not in {KycStatus.approved, KycStatus.pending}:
                raise Forbidden("KYC blocked")
            wallet = await self._wallets.get_wallet(user_id)
            if wallet is None:
                raise NotFound("Wallet not found")
            if payment_type == PaymentType.withdrawal:
                if wallet["available_balance_usd"] < amount_usd:
                    raise ValidationError("Insufficient balance")
                await self._wallets.freeze(user_id, amount_usd)

            if self._payment_reconciliation is not None and reference_number:
                existing_ref = await self._payment_reconciliation.find_by_reference(reference_number)
                if existing_ref is not None:
                    raise ValidationError(f"Reference number {reference_number} already exists")

            receipt_concat = "|".join(sorted(receipt_file_ids_enc))
            receipt_hash = str(hash(f"{user_id}:{amount_usd}:{receipt_concat}"))
            if self._payment_reconciliation is not None:
                dup = await self._payment_reconciliation.find_duplicate(user_id, amount_usd, receipt_hash)
                if dup is not None:
                    raise ValidationError("Duplicate payment request detected")

            row = await self._payments.create_request(user_id, payment_type, amount_usd, receipt_file_ids_enc, bank_account_id)
            await self._audit.add(user_id, "payment.request_created", "payment_request", str(row["id"]), {"type": payment_type.value, "amount": str(amount_usd)})

            if self._payment_reconciliation is not None:
                await self._payment_reconciliation.record(
                    row["id"],
                    reference_number=reference_number,
                    duplicate_check_hash=receipt_hash,
                )
            return PaymentDTO(**row)

    async def review_payment_request(self, actor_user_id: int, payment_id: int, approve: bool, note: str | None) -> PaymentDTO:
        async with self._uow.transaction():
            
            permission = "approve_payments" if approve else "reject_payments"
            allowed = await self._roles.user_has_permission(actor_user_id, permission)
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            pr = await self._payments.get(payment_id)
            if pr is None:
                raise NotFound("Payment not found")
            if pr["status"] != PaymentStatus.awaiting_review:
                raise ValidationError("Invalid payment state")

            cash = await self._accounting.get_account_by_code("1000")
            customer = await self._accounting.get_account_by_code("2000")
            if cash is None or customer is None:
                raise NotFound("Accounting chart not ready")

            if not approve:
                if pr["payment_type"] == PaymentType.withdrawal:
                    await self._wallets.unfreeze(pr["user_id"], pr["amount_usd"])
                updated = await self._payments.set_status(payment_id, PaymentStatus.rejected, actor_user_id, note)
                await self._audit.add(actor_user_id, "payment.rejected", "payment_request", str(payment_id), {"note": note})
                await self._notifications.enqueue(pr["user_id"], "payment.rejected", {"payment_id": payment_id, "note": note})
                await self._publish(PaymentRejected(
                    aggregate_id=str(payment_id),
                    aggregate_type="payment_request",
                    actor_user_id=actor_user_id,
                    payload={"user_id": pr["user_id"], "amount_usd": str(pr["amount_usd"]), "note": note},
                ))
                return PaymentDTO(**updated)

            if pr["payment_type"] == PaymentType.deposit:
                await self._wallets.credit_available(pr["user_id"], pr["amount_usd"])
                await self._accounting.post_journal_entry(
                    reference=f"deposit:{payment_id}",
                    description="Customer deposit",
                    posted_at=datetime.now(tz=utc_now().tzinfo),
                    created_by_user_id=actor_user_id,
                    lines=[
                        {"account_id": cash["id"], "debit_usd": pr["amount_usd"], "credit_usd": Decimal("0"), "user_id": None},
                        {"account_id": customer["id"], "debit_usd": Decimal("0"), "credit_usd": pr["amount_usd"], "user_id": pr["user_id"]},
                    ],
                )
            else:
                await self._wallets.unfreeze(pr["user_id"], pr["amount_usd"])
                await self._wallets.debit_available(pr["user_id"], pr["amount_usd"])
                await self._accounting.post_journal_entry(
                    reference=f"withdrawal:{payment_id}",
                    description="Customer withdrawal",
                    posted_at=datetime.now(tz=utc_now().tzinfo),
                    created_by_user_id=actor_user_id,
                    lines=[
                        {"account_id": customer["id"], "debit_usd": pr["amount_usd"], "credit_usd": Decimal("0"), "user_id": pr["user_id"]},
                        {"account_id": cash["id"], "debit_usd": Decimal("0"), "credit_usd": pr["amount_usd"], "user_id": None},
                    ],
                )

            updated = await self._payments.set_status(payment_id, PaymentStatus.approved, actor_user_id, note)
            await self._audit.add(actor_user_id, "payment.approved", "payment_request", str(payment_id), {"note": note})
            await self._notifications.enqueue(pr["user_id"], "payment.approved", {"payment_id": payment_id, "note": note})
            await self._publish(PaymentApproved(
                aggregate_id=str(payment_id),
                aggregate_type="payment_request",
                actor_user_id=actor_user_id,
                payload={"user_id": pr["user_id"], "amount_usd": str(pr["amount_usd"]), "note": note},
            ))
            return PaymentDTO(**updated)

    async def list_pending_payments(self, actor_user_id: int, limit: int = 20) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "approve_payments")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._payments.list_pending(limit=limit)

    async def report_trial_balance(self, actor_user_id: int, from_dt: datetime | None, to_dt: datetime | None) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "view_financial_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            return await self._accounting.trial_balance(from_dt, to_dt)

    async def report_profit_and_loss(self, actor_user_id: int, from_dt: datetime | None, to_dt: datetime | None) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "view_financial_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            return await self._accounting.profit_and_loss(from_dt, to_dt)

    async def report_balance_sheet(self, actor_user_id: int, at_dt: datetime | None) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "view_financial_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            return await self._accounting.balance_sheet(at_dt)

    async def report_cash_flow(self, actor_user_id: int, from_dt: datetime | None, to_dt: datetime | None) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "view_financial_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            return await self._accounting.cash_flow(from_dt, to_dt)

    async def report_financial_dashboard(
        self,
        actor_user_id: int,
        from_dt: datetime | None,
        to_dt: datetime | None,
    ) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "view_financial_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            return await self._accounting.financial_dashboard(from_dt, to_dt)

    async def report_period_summary(self, actor_user_id: int, period: str, at_dt: datetime | None = None) -> dict:
        base = at_dt or utc_now()
        normalized = period.strip().lower()
        if normalized == "daily":
            start = base.replace(hour=0, minute=0, second=0, microsecond=0)
        elif normalized == "weekly":
            start = (base - timedelta(days=base.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif normalized == "monthly":
            start = base.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif normalized == "yearly":
            start = base.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            raise ValidationError("Unsupported period")
        dashboard = await self.report_financial_dashboard(actor_user_id, start, base)
        return {"period": normalized, "from_dt": start, "to_dt": base, **dashboard}

    async def create_bank_account(self, actor_user_id: int, name: str, account_number_enc: str) -> dict:
        if not name.strip():
            raise ValidationError("Name required")
        if not account_number_enc.strip():
            raise ValidationError("Account number required")
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            row = await self._accounting.create_bank_account(name.strip(), account_number_enc)
            await self._audit.add(actor_user_id, "bank_account.created", "bank_account", str(row["id"]), {"name": name.strip()})
            return row

    async def list_bank_accounts(self, actor_user_id: int, only_active: bool = True) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._accounting.list_bank_accounts(only_active=only_active)

    async def create_payment_card(self, actor_user_id: int, bank_account_id: int, label: str, card_number_enc: str) -> dict:
        if not label.strip():
            raise ValidationError("Label required")
        if not card_number_enc.strip():
            raise ValidationError("Card number required")
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            row = await self._accounting.create_payment_card(bank_account_id, label.strip(), card_number_enc)
            await self._audit.add(actor_user_id, "payment_card.created", "payment_card", str(row["id"]), {"label": label.strip()})
            return row

    async def list_payment_cards(self, actor_user_id: int, bank_account_id: int | None = None, only_active: bool = True) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._accounting.list_payment_cards(bank_account_id=bank_account_id, only_active=only_active)

    async def post_manual_journal_entry(
        self,
        actor_user_id: int,
        reference: str | None,
        description: str,
        posted_at: datetime,
        lines: list[dict],
    ) -> dict:
        if not description.strip():
            raise ValidationError("Description required")
        if not lines:
            raise ValidationError("Lines required")
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            row = await self._accounting.post_journal_entry(reference, description.strip(), posted_at, actor_user_id, lines)
            await self._audit.add(actor_user_id, "journal.manual_posted", "journal_entry", str(row["id"]), {"reference": reference})
            return row

    async def post_manual_transfer(
        self,
        actor_user_id: int,
        debit_account_code: str,
        credit_account_code: str,
        amount_usd: Decimal,
        description: str,
        reference: str | None = None,
    ) -> dict:
        if amount_usd <= 0:
            raise ValidationError("Amount must be > 0")
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            debit = await self._accounting.get_account_by_code(debit_account_code)
            credit = await self._accounting.get_account_by_code(credit_account_code)
            if debit is None or credit is None:
                raise NotFound("Account not found")
            row = await self._accounting.post_journal_entry(
                reference=reference,
                description=description,
                posted_at=utc_now(),
                created_by_user_id=actor_user_id,
                lines=[
                    {"account_id": debit["id"], "debit_usd": amount_usd, "credit_usd": Decimal("0"), "user_id": None},
                    {"account_id": credit["id"], "debit_usd": Decimal("0"), "credit_usd": amount_usd, "user_id": None},
                ],
            )
            await self._audit.add(
                actor_user_id,
                "journal.manual_transfer_posted",
                "journal_entry",
                str(row["id"]),
                {"debit_account_code": debit_account_code, "credit_account_code": credit_account_code, "amount_usd": str(amount_usd)},
            )
            return row

    async def close_financial_period(self, actor_user_id: int, period_type: str, label: str, start_date: datetime, end_date: datetime) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            result = await self._accounting.close_period(period_type, label, start_date, end_date, actor_user_id)
            await self._audit.add(actor_user_id, "accounting.period_closed", "financial_period", str(result["id"]), {"period_type": period_type, "label": label})
            await self._publish(FinancialPeriodClosed(
                aggregate_id=str(result["id"]),
                aggregate_type="financial_period",
                actor_user_id=actor_user_id,
                payload={"period_type": period_type, "label": label, "net_income_usd": str(result["net_income_usd"])},
            ))
            return result

    async def list_financial_periods(self, actor_user_id: int, period_type: str | None = None, limit: int = 20) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "view_financial_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._accounting.list_periods(period_type=period_type, limit=limit)

    async def reopen_financial_period(self, actor_user_id: int, period_id: int) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_accounts")
            if not allowed:
                raise Forbidden("Not allowed")
            result = await self._accounting.reopen_period(period_id, actor_user_id)
            await self._audit.add(actor_user_id, "accounting.period_reopened", "financial_period", str(period_id), {})
            return result

    async def reconcile_payment(self, actor_user_id: int, payment_id: int, reference_number: str | None = None) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "approve_payments")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._payments.reconcile(payment_id, reference_number=reference_number, reconciled_by_user_id=actor_user_id)

    async def detect_price_anomaly(
        self,
        actor_user_id: int,
        *,
        anomaly_type: str,
        severity: str,
        observed_value_usd: Decimal,
        expected_value_usd: Decimal,
        deviation_pct: Decimal,
        threshold_pct: Decimal,
    ) -> dict | None:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_prices")
            if not allowed:
                raise Forbidden("Not allowed")
            price_row = await self._prices.get_latest()
            if price_row is None:
                return None
            price_id = price_row.get("id", 0)
            return await self._prices.detect_anomaly(
                anomaly_type=anomaly_type,
                severity=severity,
                observed_value_usd=observed_value_usd,
                expected_value_usd=expected_value_usd,
                deviation_pct=deviation_pct,
                threshold_pct=threshold_pct,
                price_id=price_id,
            )

    async def list_price_anomalies(self, actor_user_id: int, anomaly_type: str | None = None, is_resolved: bool | None = None, limit: int = 50) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_prices")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._prices.list_anomalies(anomaly_type=anomaly_type, is_resolved=is_resolved, limit=limit)

    async def resolve_price_anomaly(self, actor_user_id: int, anomaly_id: int) -> dict | None:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_prices")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._prices.resolve_anomaly(anomaly_id, actor_user_id)

    async def get_price_history(self, actor_user_id: int, limit: int = 20) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_prices")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._prices.get_price_history(limit=limit)

    def _export_csv(self, headers: list[str], rows: list[dict]) -> bytes:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: (v.value if hasattr(v, "value") else v) for k, v in r.items()})
        return buf.getvalue().encode("utf-8")

    def _export_xlsx(self, headers: list[str], rows: list[dict]) -> bytes:
        wb = Workbook()
        ws = wb.active
        ws.title = "Report"
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for r in rows:
            ws.append([(r.get(h).value if hasattr(r.get(h), "value") else r.get(h)) for h in headers])
        out = io.BytesIO()
        wb.save(out)
        return out.getvalue()

    def _export_pdf(self, headers: list[str], rows: list[dict]) -> bytes:
        out = io.BytesIO()
        doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm)
        data: list[list[object]] = [headers]
        for r in rows:
            data.append([(r.get(h).value if hasattr(r.get(h), "value") else r.get(h)) for h in headers])
        table = Table(data, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        doc.build([table])
        return out.getvalue()

    def _export_table(self, fmt: str, headers: list[str], rows: list[dict]) -> tuple[str, str, bytes]:
        f = fmt.strip().lower()
        if f == "csv":
            return "csv", "text/csv; charset=utf-8", self._export_csv(headers, rows)
        if f == "xlsx":
            return "xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", self._export_xlsx(headers, rows)
        if f == "pdf":
            return "pdf", "application/pdf", self._export_pdf(headers, rows)
        raise ValidationError("Unsupported export format")

    async def export_trial_balance(
        self,
        actor_user_id: int,
        fmt: str,
        from_dt: datetime | None,
        to_dt: datetime | None,
    ) -> tuple[str, str, bytes]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "export_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            rows = await self._accounting.trial_balance(from_dt, to_dt)
            headers = ["code", "name", "account_type", "debit_usd", "credit_usd", "balance_usd"]
            ext, mime, payload = self._export_table(fmt, headers, rows)
            return f"trial_balance.{ext}", mime, payload

    async def export_profit_and_loss(
        self,
        actor_user_id: int,
        fmt: str,
        from_dt: datetime | None,
        to_dt: datetime | None,
    ) -> tuple[str, str, bytes]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "export_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            r = await self._accounting.profit_and_loss(from_dt, to_dt)
            rows = [
                {"metric": "income_usd", "value": r["income_usd"]},
                {"metric": "expense_usd", "value": r["expense_usd"]},
                {"metric": "net_profit_usd", "value": r["net_profit_usd"]},
            ]
            headers = ["metric", "value"]
            ext, mime, payload = self._export_table(fmt, headers, rows)
            return f"profit_and_loss.{ext}", mime, payload

    async def export_balance_sheet(self, actor_user_id: int, fmt: str, at_dt: datetime | None) -> tuple[str, str, bytes]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "export_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            r = await self._accounting.balance_sheet(at_dt)
            rows = [
                {"metric": "assets_usd", "value": r["assets_usd"]},
                {"metric": "liabilities_usd", "value": r["liabilities_usd"]},
                {"metric": "equity_usd", "value": r["equity_usd"]},
            ]
            headers = ["metric", "value"]
            ext, mime, payload = self._export_table(fmt, headers, rows)
            return f"balance_sheet.{ext}", mime, payload

    async def export_cash_flow(
        self,
        actor_user_id: int,
        fmt: str,
        from_dt: datetime | None,
        to_dt: datetime | None,
    ) -> tuple[str, str, bytes]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "export_reports")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._accounting.ensure_default_chart()
            r = await self._accounting.cash_flow(from_dt, to_dt)
            rows = [{"metric": "net_cash_change_usd", "value": r["net_cash_change_usd"]}]
            headers = ["metric", "value"]
            ext, mime, payload = self._export_table(fmt, headers, rows)
            return f"cash_flow.{ext}", mime, payload

    async def request_order_cancellation(self, user_id: int, order_id: int) -> dict:
        async with self._uow.transaction():
            order = await self._orders.get(order_id)
            if order is None:
                raise NotFound("Order not found")
            if order["user_id"] != user_id:
                raise Forbidden("Not allowed")
            if order["status"] in {OrderStatus.cancelled, OrderStatus.completed, OrderStatus.rejected}:
                raise ValidationError("Order cannot be cancelled")
            cancellation = await self._orders.request_cancellation(order_id=order_id, requested_by_user_id=user_id)
            await self._audit.add(user_id, "order.cancel_requested", "order", str(order_id), {"cancellation_id": cancellation["id"]})
            return cancellation

    async def list_pending_cancellations(self, actor_user_id: int, limit: int = 20) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_orders")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._orders.list_pending_cancellations(limit=limit)

    async def review_order_cancellation(self, actor_user_id: int, order_id: int, approve: bool) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_orders")
            if not allowed:
                raise Forbidden("Not allowed")
            existing = await self._orders.get_cancellation(order_id)
            if existing is None:
                raise NotFound("Cancellation request not found")
            if existing["status"] != OrderCancellationStatus.requested:
                raise ValidationError("Invalid cancellation state")
            status = OrderCancellationStatus.admin_approved if approve else OrderCancellationStatus.rejected
            updated = await self._orders.set_cancellation_status(order_id, status=status)
            await self._audit.add(actor_user_id, "order.cancel_reviewed", "order", str(order_id), {"status": status.value})
            await self._notifications.enqueue(updated["requested_by_user_id"], "order.cancel_reviewed", {"order_id": order_id, "status": status.value})
            return updated

    async def confirm_order_cancellation(self, user_id: int, order_id: int) -> dict:
        async with self._uow.transaction():
            existing = await self._orders.get_cancellation(order_id)
            if existing is None:
                raise NotFound("Cancellation request not found")
            if existing["requested_by_user_id"] != user_id:
                raise Forbidden("Not allowed")
            if existing["status"] != OrderCancellationStatus.admin_approved:
                raise ValidationError("Cancellation not approved")
            order = await self._orders.get(order_id)
            if order is None:
                raise NotFound("Order not found")
            if order["status"] in {OrderStatus.completed, OrderStatus.rejected, OrderStatus.cancelled}:
                raise ValidationError("Order cannot be cancelled")
            await self._orders.set_cancellation_status(order_id, status=OrderCancellationStatus.user_confirmed)
            await self._orders.set_status(order_id, OrderStatus.cancelled)
            updated = await self._orders.set_cancellation_status(order_id, status=OrderCancellationStatus.completed)
            await self._audit.add(user_id, "order.cancel_completed", "order", str(order_id), {"cancellation_id": updated["id"]})
            return updated

    async def backup_snapshot(self, actor_user_id: int) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "configure_system")
            if not allowed:
                raise Forbidden("Not allowed")
            snapshot = await self._backup.create_snapshot()
            await self._audit.add(actor_user_id, "system.backup_created", "system", "backup", {"tables": list(snapshot.get("tables", {}).keys())})
            return snapshot

    async def restore_snapshot(self, actor_user_id: int, snapshot: dict) -> None:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "configure_system")
            if not allowed:
                raise Forbidden("Not allowed")
            await self._backup.restore_snapshot(snapshot, wipe_existing=True)
            await self._audit.add(actor_user_id, "system.backup_restored", "system", "restore", {"tables": list(snapshot.get("tables", {}).keys())})

    async def run_settlement(
        self,
        actor_user_id: int,
        *,
        settlement_at: datetime | None = None,
        mode: str = "manual",
        user_ids: list[int] | None = None,
        idempotency_key: str | None = None,
    ) -> SettlementResultDTO:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_settlement")
            if not allowed:
                raise Forbidden("Not allowed")
        if self._settlement_engine is None:
            raise ValidationError("Settlement engine is not configured")
        result = await self._settlement_engine.execute(
            mode=mode,
            settlement_at=settlement_at,
            actor_user_id=actor_user_id,
            user_ids=user_ids,
            idempotency_key=idempotency_key,
        )
        async with self._uow.transaction():
            await self._audit.add(
                actor_user_id,
                "settlement.executed",
                "settlement_batch",
                result["summary"]["batch_key"],
                {"mode": mode, "idempotent": result["idempotent"]},
            )
        await self._publish(SettlementExecuted(
            aggregate_id=result["summary"]["batch_key"],
            aggregate_type="settlement_batch",
            actor_user_id=actor_user_id,
            payload={
                "mode": mode,
                "status": result["status"],
                "affected_users": result["summary"]["affected_users"],
                "net_pnl_usd": str(result["summary"]["net_pnl_usd"]),
            },
        ))
        return SettlementResultDTO(
            status=result["status"],
            idempotent=result["idempotent"],
            summary=SettlementSummaryDTO(**result["summary"]),
        )

    async def rollback_settlement(
        self,
        actor_user_id: int,
        *,
        settlement_id: int,
        reason: str | None = None,
    ) -> SettlementResultDTO:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_settlement")
            if not allowed:
                raise Forbidden("Not allowed")
        if self._settlement_engine is None:
            raise ValidationError("Settlement engine is not configured")
        result = await self._settlement_engine.rollback(
            settlement_id=settlement_id,
            actor_user_id=actor_user_id,
            reason=reason,
        )
        async with self._uow.transaction():
            await self._audit.add(
                actor_user_id,
                "settlement.rolled_back",
                "settlement",
                str(settlement_id),
                {"reason": reason, "batch_key": result["summary"]["batch_key"]},
            )
        await self._publish(SettlementRolledBack(
            aggregate_id=result["summary"]["batch_key"],
            aggregate_type="settlement_batch",
            actor_user_id=actor_user_id,
            payload={"settlement_id": settlement_id, "reason": reason},
        ))
        return SettlementResultDTO(
            status=result["status"],
            idempotent=result["idempotent"],
            summary=SettlementSummaryDTO(**result["summary"]),
        )

    async def replay_settlement(
        self,
        actor_user_id: int,
        *,
        settlement_id: int,
        idempotency_key: str | None = None,
    ) -> SettlementResultDTO:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_settlement")
            if not allowed:
                raise Forbidden("Not allowed")
        if self._settlement_engine is None:
            raise ValidationError("Settlement engine is not configured")
        result = await self._settlement_engine.replay(
            settlement_id=settlement_id,
            actor_user_id=actor_user_id,
            idempotency_key=idempotency_key,
        )
        async with self._uow.transaction():
            await self._audit.add(
                actor_user_id,
                "settlement.replayed",
                "settlement",
                str(settlement_id),
                {"batch_key": result["summary"]["batch_key"]},
            )
        return SettlementResultDTO(
            status=result["status"],
            idempotent=result["idempotent"],
            summary=SettlementSummaryDTO(**result["summary"]),
        )

    async def settlement_history(self, actor_user_id: int, *, limit: int = 20) -> list[SettlementHistoryItemDTO]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_settlement")
            if not allowed:
                raise Forbidden("Not allowed")
        if self._settlement_engine is None:
            raise ValidationError("Settlement engine is not configured")
        rows = await self._settlement_engine.list_history(limit=limit)
        return [SettlementHistoryItemDTO(**row) for row in rows]

    async def settlement_status(self, actor_user_id: int, *, batch_key: str) -> SettlementStatusDTO:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_settlement")
            if not allowed:
                raise Forbidden("Not allowed")
        if self._settlement_engine is None:
            raise ValidationError("Settlement engine is not configured")
        row = await self._settlement_engine.get_status(batch_key=batch_key)
        if row is None:
            raise NotFound("Settlement batch not found")
        return SettlementStatusDTO(
            batch_key=row["batch_key"],
            mode=row["mode"],
            status=row["status"],
            last_checkpoint=row.get("last_checkpoint"),
            error_message=row.get("error_message"),
            target_date=row["target_date"],
            created_at=row["created_at"],
            completed_at=row.get("completed_at"),
        )

    async def get_maintenance_mode(self) -> dict:
        if self._runtime_state is None:
            return {
                "enabled": False,
                "message": None,
                "actor_user_id": None,
                "updated_at": None,
            }
        return await self._runtime_state.get_maintenance_mode()

    async def set_maintenance_mode(self, actor_user_id: int, enabled: bool, message: str | None = None) -> dict:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "configure_system")
            if not allowed:
                raise Forbidden("Not allowed")
        if self._runtime_state is None:
            raise ValidationError("Runtime state backend is not configured")
        state = await self._runtime_state.set_maintenance_mode(enabled=enabled, message=message, actor_user_id=actor_user_id)
        async with self._uow.transaction():
            await self._audit.add(
                actor_user_id,
                "system.maintenance_mode_changed",
                "system",
                "maintenance",
                {"enabled": state["enabled"], "message": state["message"]},
            )
        return state

    async def can_access_during_maintenance(self, user_id: int) -> bool:
        state = await self.get_maintenance_mode()
        if not state["enabled"]:
            return True
        async with self._uow.transaction():
            return await self._roles.user_has_permission(user_id, "configure_system")

    async def broadcast_message(
        self,
        actor_user_id: int,
        *,
        message_type: str,
        text: str | None = None,
        caption: str | None = None,
        file_id: str | None = None,
        forward_from_chat_id: int | None = None,
        forward_message_id: int | None = None,
        role: str | None = None,
        language_code: str | None = None,
        kyc_status: KycStatus | None = None,
        trading_active: bool | None = None,
        silent: bool = False,
        scheduled_at: datetime | None = None,
    ) -> dict:
        normalized_language = language_code.strip().lower() if language_code else None
        normalized_type = message_type.strip().lower()
        if normalized_type not in {"text", "photo", "document", "video", "forward"}:
            raise ValidationError("Unsupported broadcast type")
        if normalized_type == "text" and not (text and text.strip()):
            raise ValidationError("Broadcast text is required")
        if normalized_type in {"photo", "document", "video"} and not file_id:
            raise ValidationError("Media file id is required")
        if normalized_type == "forward" and (forward_from_chat_id is None or forward_message_id is None):
            raise ValidationError("Forward source is required")

        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "broadcast_messages")
            if not allowed:
                raise Forbidden("Not allowed")
            targets = await self._users.list_users(
                role=role,
                kyc_status=kyc_status,
                language_code=normalized_language,
                trading_active=trading_active,
                limit=10000,
            )
            payload = {
                "message_type": normalized_type,
                "text": text.strip() if text else None,
                "caption": caption.strip() if caption else None,
                "file_id": file_id,
                "forward_from_chat_id": forward_from_chat_id,
                "forward_message_id": forward_message_id,
                "silent": silent,
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
                "attempts": 0,
                "max_attempts": 3,
                "filters": {
                    "role": role,
                    "language_code": normalized_language,
                    "kyc_status": kyc_status.value if kyc_status else None,
                    "trading_active": trading_active,
                },
            }
            for user in targets:
                await self._notifications.enqueue(user["id"], "broadcast.telegram", payload)
            await self._audit.add(
                actor_user_id,
                "broadcast.created",
                "broadcast",
                None,
                {
                    "message_type": normalized_type,
                    "recipients": len(targets),
                    "filters": payload["filters"],
                    "silent": silent,
                    "scheduled_at": payload["scheduled_at"],
                },
            )
            return {"recipients": len(targets), "filters": payload["filters"], "scheduled_at": payload["scheduled_at"]}

    async def settle_order(self, actor_user_id: int, order_id: int) -> OrderDTO:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "manage_settlement")
            if not allowed:
                raise Forbidden("Not allowed")
            order = await self._orders.get(order_id)
            if order is None:
                raise NotFound("Order not found")
            current = OrderStatus(order["status"])
            if not current.can_transition_to(OrderStatus.settled):
                raise ValidationError(f"Cannot settle order in {current.value}")

            await self._accounting.ensure_default_chart()
            cash = await self._accounting.get_account_by_code("1000")
            revenue = await self._accounting.get_account_by_code("4000")
            if cash is None or revenue is None:
                raise NotFound("Accounting chart not ready")

            notional = (Decimal(order["quoted_price"]) * Decimal(order["quantity_kg"])).quantize(Decimal("0.01"))
            fee = Decimal(order["executed_fee_usd"])
            net_amount = (notional - fee).quantize(Decimal("0.01"))

            await self._accounting.post_journal_entry(
                reference=f"settle_order:{order_id}",
                description=f"Settlement of order {order_id} for user {order['user_id']}",
                posted_at=utc_now(),
                created_by_user_id=actor_user_id,
                lines=[
                    {"account_id": cash["id"], "debit_usd": net_amount, "credit_usd": Decimal("0"), "user_id": order["user_id"]},
                    {"account_id": revenue["id"], "debit_usd": Decimal("0"), "credit_usd": net_amount, "user_id": None},
                ],
            )

            updated = await self._orders.set_status(order_id, OrderStatus.settled)
            await self._audit.add(actor_user_id, "order.settled", "order", str(order_id), {"notional_usd": str(notional)})
            await self._notifications.enqueue(order["user_id"], "order.settled", {"order_id": order_id, "net_amount_usd": str(net_amount)})
            await self._publish(OrderSettled(
                aggregate_id=str(order_id),
                aggregate_type="order",
                actor_user_id=actor_user_id,
                payload={"user_id": order["user_id"], "notional_usd": str(notional)},
            ))
            return OrderDTO(**updated)

    async def arbitration_correct_trade(
        self,
        actor_user_id: int,
        trade_id: int,
        reason: ArbitrationReason,
        new_price_usd: Decimal | None = None,
        new_pnl_usd: Decimal | None = None,
        notes: str | None = None,
    ) -> dict:
        allowed = await self._roles.user_has_permission(actor_user_id, "approve_critical_actions")
        if not allowed:
            raise Forbidden("Not allowed")

        is_valid, err = self._arbitration.validate_arbitration_request(reason, None, new_price_usd, notes)
        if not is_valid:
            raise ValidationError(err or "Invalid arbitration request")

        async with self._uow.transaction():
            trade = await self._orders.get_trade(trade_id)
            if trade is None:
                raise NotFound("Trade not found")

            old_price = Decimal(trade["price_usd"])
            quantity = Decimal(trade["quantity_kg"])
            adjustment = self._arbitration.compute_adjustment(
                reason=reason,
                old_price_usd=old_price,
                new_price_usd=new_price_usd,
                quantity_kg=quantity,
                old_pnl_usd=None,
                new_pnl_usd=new_pnl_usd,
            )

            await self._audit.add(
                actor_user_id,
                "arbitration.correction",
                "trade",
                str(trade_id),
                {
                    "reason": reason.value,
                    "old_price_usd": str(old_price),
                    "new_price_usd": str(new_price_usd) if new_price_usd else None,
                    "adjustment_usd": str(adjustment),
                    "notes": notes,
                },
            )

            await self._notifications.enqueue(
                trade["buy_order_id"] if hasattr(trade, "buy_order_id") else 0,
                "arbitration.correction",
                {"trade_id": trade_id, "adjustment_usd": str(adjustment), "reason": reason.value, "notes": notes},
            )

            return {
                "arbitration_id": 0,
                "trade_id": trade_id,
                "reason": reason.value,
                "old_price_usd": old_price,
                "new_price_usd": new_price_usd,
                "adjustment_usd": adjustment,
                "status": ArbitrationStatus.approved.value,
                "actor_user_id": actor_user_id,
                "notes": notes,
            }

    async def list_audit_logs(
        self,
        actor_user_id: int,
        *,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        entity_type: str | None = None,
    ) -> list[dict]:
        async with self._uow.transaction():
            allowed = await self._roles.user_has_permission(actor_user_id, "view_audit_logs")
            if not allowed:
                raise Forbidden("Not allowed")
            return await self._audit.list_events(limit=limit, offset=offset, event_type=event_type, entity_type=entity_type)

    async def trigger_stop_orders(self) -> dict:
        async with self._uow.transaction():
            price_row = await self._prices.get_latest()
            if price_row is None:
                return {"triggered": 0, "reason": "no_price"}
            current_price = Decimal(price_row["sell_price"])
            candidates = await self._orders.list_triggerable_orders(current_price, limit=200)
            triggered = []
            for order in candidates:
                updated = await self._orders.mark_triggered(order["id"])
                triggered.append(updated)
                await self._orders.add_execution_report(
                    order_id=order["id"],
                    execution_type=ExecutionType.triggered,
                    status=updated["status"],
                    quantity_kg=Decimal("0"),
                    price_usd=current_price,
                    fee_usd=Decimal("0"),
                    payload={"stop_price": str(order.get("stop_price", "")), "current_price": str(current_price)},
                )
            return {"triggered": len(triggered)}

    async def expire_stale_orders(self) -> dict:
        async with self._uow.transaction():
            now = utc_now()
            candidates = await self._orders.list_expired_orders(now, limit=200)
            expired = []
            for order in candidates:
                if Decimal(order.get("reserved_balance_usd", "0")) > 0:
                    await self._wallets.unfreeze(order["user_id"], Decimal(order["reserved_balance_usd"]))
                if Decimal(order.get("reserved_margin_usd", "0")) > 0:
                    await self._wallets.release_margin_to_available(order["user_id"], Decimal(order["reserved_margin_usd"]))
                await self._orders.release_reservations(order["id"])
                updated = await self._orders.set_status(order["id"], OrderStatus.expired)
                expired.append(updated)
                await self._orders.add_execution_report(
                    order_id=order["id"],
                    execution_type=ExecutionType.expire,
                    status=OrderStatus.expired,
                    quantity_kg=Decimal("0"),
                    price_usd=Decimal("0"),
                    fee_usd=Decimal("0"),
                    payload={"reason": "stale"},
                )
            return {"expired": len(expired)}

    async def calculate_user_exposure(self, user_id: int) -> dict:
        async with self._uow.transaction():
            pos = await self._positions.get_position(user_id)
            wallet = await self._wallets.get_wallet(user_id)
            if pos is None or wallet is None:
                return {}
            price_row = await self._prices.get_latest()
            current_price = Decimal(price_row["sell_price"]) if price_row else Decimal("0")
            net_kg = Decimal(pos["net_kg"])
            exposure_kg = abs(net_kg)
            notional_usd = exposure_kg * current_price
            equity = (
                Decimal(wallet["available_balance_usd"])
                + Decimal(wallet["frozen_balance_usd"])
                + Decimal(wallet["margin_balance_usd"])
            )
            leverage = (notional_usd / equity).quantize(Decimal("0.01")) if equity > 0 else Decimal("0")
            floating = (current_price - Decimal(pos["avg_price_usd"])) * net_kg
            return {
                "user_id": user_id,
                "net_kg": net_kg,
                "exposure_kg": exposure_kg,
                "notional_usd": notional_usd.quantize(Decimal("0.01")),
                "equity_usd": equity,
                "leverage": leverage,
                "floating_pnl_usd": floating.quantize(Decimal("0.01")),
                "mark_price_usd": current_price,
            }

    async def calculate_risk_score(self, user_id: int) -> dict:
        async with self._uow.transaction():
            if self._risk_calc is None:
                return {"score": Decimal("0"), "level": "unknown"}
            exposure = await self.calculate_user_exposure(user_id)
            violations = await self._risk.list_violations(user_id, limit=50)
            score, level = self._risk_calc.compute_score(exposure, violations)
            payload = {"score": str(score), "level": level.value, "violation_count": len(violations)}
            await self._risk.create_snapshot(user_id=user_id, payload=payload)
            return {"score": score, "level": level.value, "violation_count": len(violations)}

    async def circuit_breaker_state(self, name: str) -> dict | None:
        if self._circuit_breaker is None:
            return None
        return await self._circuit_breaker.get_state(name)

    async def circuit_breaker_reset(self, name: str) -> None:
        if self._circuit_breaker is None:
            return
        await self._circuit_breaker.reset(name)

    async def circuit_breaker_all_states(self) -> list[dict]:
        if self._circuit_breaker is None:
            return []
        return await self._circuit_breaker.all_states()

    async def dead_letter_list(self, limit: int = 50, source: str | None = None) -> list[dict]:
        if self._dead_letter is None:
            return []
        return await self._dead_letter.list_entries(limit=limit, source=source)

    async def dead_letter_counts(self) -> dict[str, int]:
        if self._dead_letter is None:
            return {}
        return await self._dead_letter.count_by_source()

    async def cleanup_old_data(self, retention_days: int) -> dict:
        if self._cleanup is None:
            return {"cleaned": 0, "skipped": "cleanup not configured"}
        async with self._uow.transaction():
            return await self._cleanup.purge_old_records(retention_days)

    # ── Phase 2: Matching Engine Integration ──────────────────────

    async def replace_order(
        self,
        user_id: int,
        order_id: int,
        *,
        quantity_kg: Decimal | None = None,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
    ) -> OrderDTO:
        async with self._uow.transaction():
            order = await self._orders.get(order_id)
            if order is None:
                raise NotFound("Order not found")
            if order["user_id"] != user_id:
                raise Forbidden("Not allowed")
            replacement_ok, reason = self._matching_engine.can_replace_order(order)
            if not replacement_ok:
                raise ValidationError(reason)
            updates: dict[str, object] = {}
            if quantity_kg is not None:
                updates["quantity_kg"] = quantity_kg
            if limit_price is not None:
                updates["quoted_price"] = limit_price
                updates["limit_price"] = limit_price
            if stop_price is not None:
                updates["stop_price"] = stop_price
            updated = await self._orders.replace_order(order_id, **updates)
            if quantity_kg is not None and quantity_kg > Decimal(order.get("filled_quantity_kg", "0")):
                remaining = quantity_kg - Decimal(order.get("filled_quantity_kg", "0"))
                price_row = await self._prices.get_latest()
                if price_row is not None:
                    current_price = Decimal(price_row["buy_price"]) if order["side"] == OrderSide.buy else Decimal(price_row["sell_price"])
                    exposure = await self.calculate_user_exposure(user_id)
                    net_kg = Decimal(exposure.get("net_kg", "0"))
                    new_exposure = (net_kg + remaining) if order["side"] == OrderSide.buy else (net_kg - remaining)
                    margin_req = self._margin_engine.calculate_requirements(
                        position_value=abs(new_exposure) * current_price,
                        equity_usd=Decimal(exposure.get("equity_usd", "0")),
                        leverage=Decimal(exposure.get("leverage", "1")),
                        margin_mode="cross",
                    )
                    if not self._margin_engine.validate_margin_sufficient(margin_req, Decimal(order.get("reserved_margin_usd", "0")) + Decimal(order.get("reserved_balance_usd", "0"))):
                        raise InsufficientDeposit("Insufficient margin for increased quantity")
            await self._publish(OrderReplaced(
                aggregate_id=str(order_id),
                aggregate_type="order",
                actor_user_id=user_id,
                payload={"order_id": order_id, **updates},
            ))
            return OrderDTO(**updated)

    # ── Phase 3: Position Engine Integration ──────────────────────

    async def get_position_pnl(self, user_id: int) -> dict:
        async with self._uow.transaction():
            pos = await self._positions.get_position(user_id)
            if pos is None:
                return {"user_id": user_id, "net_kg": 0, "realized_pnl_usd": 0, "unrealized_pnl_usd": 0}
            price_row = await self._prices.get_latest()
            mark_price = Decimal(price_row["sell_price"]) if price_row else Decimal("0")
            pnl = self._position_engine.calculate_pnl_at_price(
                net_kg=Decimal(pos["net_kg"]),
                avg_price=Decimal(pos["avg_price_usd"]),
                current_price=mark_price,
            )
            return {
                "user_id": user_id,
                "net_kg": pos["net_kg"],
                "avg_price_usd": pos["avg_price_usd"],
                "realized_pnl_usd": pos.get("realized_pnl_usd", Decimal("0")),
                "unrealized_pnl_usd": pnl.total.quantize(Decimal("0.01")),
                "mark_price_usd": mark_price,
                "position_value_usd": self._position_engine.position_value(Decimal(pos["net_kg"]), mark_price).quantize(Decimal("0.01")),
            }

    async def get_unrealized_pnl(self, user_id: int) -> Decimal:
        async with self._uow.transaction():
            pos = await self._positions.get_position(user_id)
            if pos is None:
                return Decimal("0")
            price_row = await self._prices.get_latest()
            current_price = Decimal(price_row["sell_price"]) if price_row else Decimal("0")
            return self._position_engine.calculate_unrealized_pnl(
                net_kg=Decimal(pos["net_kg"]),
                avg_price=Decimal(pos["avg_price_usd"]),
                current_price=current_price,
            )

    async def get_position_history(self, user_id: int, limit: int = 50) -> list[dict]:
        async with self._uow.transaction():
            return await self._positions.get_position_history(user_id, limit=limit)

    # ── Phase 4: Margin Engine Integration ────────────────────────

    async def margin_transfer(self, user_id: int, amount_usd: Decimal, *, from_wallet: bool = True) -> dict:
        if amount_usd <= 0:
            raise ValidationError("Amount must be > 0")
        async with self._uow.transaction():
            wallet = await self._wallets.get_wallet(user_id)
            if wallet is None:
                raise NotFound("Wallet not found")
            margin_account = await self._wallets.get_margin_account(user_id)
            if from_wallet:
                if Decimal(wallet["available_balance_usd"]) < amount_usd:
                    raise InsufficientDeposit("Insufficient available balance")
                await self._wallets.transfer_available_to_margin(user_id, amount_usd)
            else:
                if Decimal(margin_account.get("free_margin_usd", "0")) < amount_usd if margin_account else 0:
                    raise InsufficientDeposit("Insufficient free margin")
                await self._wallets.release_margin_to_available(user_id, amount_usd)
            await self._publish(MarginTransferExecuted(
                aggregate_id=str(user_id),
                aggregate_type="user",
                actor_user_id=user_id,
                payload={"amount_usd": str(amount_usd), "from_wallet": from_wallet},
            ))
            return {"user_id": user_id, "amount_usd": amount_usd, "from_wallet": from_wallet}

    async def set_margin_mode(self, user_id: int, mode: str) -> dict:
        if mode not in ("cross", "isolated"):
            raise ValidationError("Margin mode must be 'cross' or 'isolated'")
        async with self._uow.transaction():
            existing = await self._wallets.set_margin_mode(user_id, mode)
            return {"user_id": user_id, "margin_mode": mode}

    async def set_leverage(self, user_id: int, leverage: Decimal) -> dict:
        if leverage < 1 or leverage > 100:
            raise ValidationError("Leverage must be between 1 and 100")
        async with self._uow.transaction():
            existing = await self._wallets.set_leverage(user_id, leverage)
            return {"user_id": user_id, "leverage": leverage}

    async def collect_funding_fees(self) -> dict:
        rate = Decimal("0.0001")
        async with self._uow.transaction():
            price_row = await self._prices.get_latest()
            if price_row is None:
                return {"collected": 0, "reason": "no_price"}
            mark_price = Decimal(price_row["sell_price"])
            positions = await self._positions.list_positions(limit=500)
            collected = 0
            for pos in positions:
                net_kg = Decimal(pos["net_kg"])
                if net_kg == 0:
                    continue
                funding = self._margin_engine.calculate_funding_fee(net_kg, mark_price, rate)
                if funding <= 0:
                    continue
                wallet = await self._wallets.get_wallet(pos["user_id"])
                if wallet and Decimal(wallet["available_balance_usd"]) >= funding:
                    await self._wallets.freeze(pos["user_id"], funding)
                    await self._publish(FundingExecuted(
                        aggregate_id=str(pos["user_id"]),
                        aggregate_type="user",
                        actor_user_id=pos["user_id"],
                        payload={"funding_usd": str(funding), "rate": str(rate)},
                    ))
                    collected += 1
            return {"collected": collected, "rate": str(rate)}

    # ── Phase 5: Risk Engine Integration ──────────────────────────

    async def evaluate_risk_limits(self, user_id: int) -> dict:
        async with self._uow.transaction():
            exposure = await self.calculate_user_exposure(user_id)
            net_kg = Decimal(exposure.get("net_kg", "0"))
            price_row = await self._prices.get_latest()
            mark_price = Decimal(price_row["sell_price"]) if price_row else Decimal("0")
            pos = await self._positions.get_position(user_id)
            violations = await self._risk.list_violations(user_id, limit=10)
            open_violations = [v for v in violations if v.get("status", "").lower() == "open"]
            wallet = await self._wallets.get_wallet(user_id)
            equity = Decimal("0")
            if wallet:
                equity = Decimal(wallet["available_balance_usd"]) + Decimal(wallet["frozen_balance_usd"]) + Decimal(wallet["margin_balance_usd"])
            risk_snapshot = self._risk_engine.build_snapshot(
                user_id=user_id,
                net_kg=net_kg,
                avg_price=Decimal(pos["avg_price_usd"] if pos else "0"),
                mark_price=mark_price,
                equity=equity,
                open_violations=len(open_violations),
            )
            limits = [
                self._risk_engine.check_position_limit(risk_snapshot, max_kg=Decimal("50000")),
                self._risk_engine.check_exposure_limit(risk_snapshot, max_exposure_kg=Decimal("100000")),
                self._risk_engine.check_leverage_limit(risk_snapshot, max_leverage=Decimal("10")),
                self._risk_engine.check_daily_loss_limit(risk_snapshot, max_daily_loss_usd=Decimal("50000")),
                self._risk_engine.check_volume_limit(risk_snapshot, max_volume_kg=Decimal("100000")),
                self._risk_engine.check_max_drawdown(risk_snapshot, max_drawdown_pct=Decimal("0.5")),
                self._risk_engine.check_concentration(risk_snapshot, max_pct=Decimal("0.8")),
            ]
            failed = [r for r in limits if not r.passed]
            if failed:
                for r in failed:
                    await self._risk.create_violation(
                        user_id=user_id,
                        order_id=None,
                        severity=r.severity.value,
                        violation_type=r.limit_type.value,
                        message=r.message,
                        payload={"limit_value": str(r.limit_value), "current_value": str(r.current_value)},
                    )
                await self._publish(RiskAlertTriggered(
                    aggregate_id=str(user_id),
                    aggregate_type="user",
                    actor_user_id=None,
                    payload={"failed_checks": len(failed), "violations": [r.message for r in failed]},
                ))
            return {
                "user_id": user_id,
                "checked": len(limits),
                "passed": len([r for r in limits if r.passed]),
                "failed": len(failed),
                "violations": [r.message for r in failed],
            }

    # ── Phase 6: Liquidation Engine Integration ───────────────────

    async def trigger_liquidations(self, batch_size: int = 50) -> dict:
        if self._liquidation_repo is None:
            return {"liquidated": 0, "reason": "liquidation_repo_not_available"}
        async with self._uow.transaction():
            price_row = await self._prices.get_latest()
            if price_row is None:
                return {"liquidated": 0, "reason": "no_price"}
            mark_price = Decimal(price_row["sell_price"])
            positions = await self._positions.list_positions(limit=batch_size)
            candidates = []
            for pos in positions:
                net_kg = Decimal(pos["net_kg"])
                if net_kg == 0:
                    continue
                wallet = await self._wallets.get_wallet(pos["user_id"])
                if wallet is None:
                    continue
                floating = mark_price - Decimal(pos["avg_price_usd"])
                equity = Decimal(wallet["available_balance_usd"]) + Decimal(wallet["frozen_balance_usd"]) + Decimal(wallet["margin_balance_usd"]) + floating * net_kg
                margin_req = self._margin_engine.calculate_requirements(
                    position_value=abs(net_kg) * mark_price,
                    equity_usd=equity if equity > 0 else Decimal("0"),
                    leverage=Decimal("1"),
                    margin_mode="cross",
                )
                trigger = self._liquidation_engine.check_liquidation_trigger(
                    margin_ratio=margin_req.margin_ratio,
                    maintenance_margin_ratio=Decimal("0.5"),
                )
                if trigger:
                    candidates.append({
                        "user_id": pos["user_id"],
                        "net_kg": net_kg,
                        "avg_price_usd": Decimal(pos["avg_price_usd"]),
                        "margin_ratio": margin_req.margin_ratio,
                    })
            if not candidates:
                return {"liquidated": 0, "reason": "no_candidates"}
            orders = [LiquidationOrder(
                user_id=c["user_id"],
                position_net_kg=c["net_kg"],
                avg_price_usd=c["avg_price_usd"],
                margin_ratio=c["margin_ratio"],
                mark_price_usd=mark_price,
                created_at=utc_now(),
            ) for c in candidates]
            prioritized = self._liquidation_engine.prioritize(orders, strategy="highest_leverage")
            liquidated = 0
            for lq in prioritized[:10]:
                insurance_balance = await self._liquidation_repo.get_insurance_balance()
                result = self._liquidation_engine.execute_liquidation(
                    liquidation_order=lq,
                    insurance_balance=insurance_balance,
                    max_close_ratio=Decimal("1"),
                )
                await self._wallets.freeze(lq.user_id, abs(result.pnl_usd))
                pos = await self._positions.get_position(lq.user_id)
                if pos:
                    old_net = Decimal(pos["net_kg"])
                    await self._positions.update_position(
                        user_id=lq.user_id,
                        net_kg=Decimal("0"),
                        avg_price_usd=Decimal("0"),
                        realized_pnl_usd=Decimal(pos.get("realized_pnl_usd", "0")) + result.pnl_usd,
                    )
                await self._liquidation_repo.create_event(
                    user_id=lq.user_id,
                    margin_ratio=lq.margin_ratio,
                    status=LiquidationStatus.completed,
                    payload={
                        "pnl_usd": str(result.pnl_usd),
                        "insurance_used_usd": str(result.insurance_used_usd),
                        "close_price_usd": str(result.close_price_usd),
                        "filled_quantity_kg": str(result.filled_quantity_kg),
                    },
                )
                if result.insurance_used_usd > 0:
                    await self._liquidation_repo.debit_insurance(result.insurance_used_usd)
                    await self._publish(InsuranceUsed(
                        aggregate_id=str(lq.user_id),
                        aggregate_type="user",
                        actor_user_id=None,
                        payload={"amount_usd": str(result.insurance_used_usd), "user_id": lq.user_id},
                    ))
                await self._publish(LiquidationCompleted(
                    aggregate_id=str(lq.user_id),
                    aggregate_type="user",
                    actor_user_id=None,
                    payload={"user_id": lq.user_id, "pnl_usd": str(result.pnl_usd)},
                ))
                liquidated += 1
            return {"liquidated": liquidated, "candidates_found": len(candidates)}

    async def get_liquidation_status(self, user_id: int) -> list[dict]:
        if self._liquidation_repo is None:
            return []
        async with self._uow.transaction():
            return await self._liquidation_repo.list_events(user_id=user_id, limit=20)

    async def get_insurance_balance(self) -> Decimal:
        if self._liquidation_repo is None:
            return Decimal("0")
        async with self._uow.transaction():
            return await self._liquidation_repo.get_insurance_balance()

    # ── Phase 1: Ledger Service Integration ───────────────────────

    async def get_ledger_entries(self, user_id: int | None = None, limit: int = 50) -> list[dict]:
        if self._ledger_repo is None:
            return []
        async with self._uow.transaction():
            return await self._ledger_repo.list_entries(user_id=user_id, limit=limit)

    async def get_account_balance(self, account_code: str) -> Decimal:
        if self._ledger_repo is None:
            return Decimal("0")
        async with self._uow.transaction():
            return await self._ledger_repo.account_balance(account_code)

    async def post_trade_journal_entry(
        self,
        user_id: int,
        buy_order_id: int,
        sell_order_id: int,
        trade_price: Decimal,
        quantity_kg: Decimal,
        buy_fee_usd: Decimal,
        sell_fee_usd: Decimal,
    ) -> None:
        if self._ledger_repo is None:
            return
        async with self._uow.transaction():
            entry = self._ledger_service.create_trade_entry(
                user_id=user_id,
                trade_price=trade_price,
                quantity_kg=quantity_kg,
                buy_fee_usd=buy_fee_usd,
                sell_fee_usd=sell_fee_usd,
                buy_order_id=buy_order_id,
                sell_order_id=sell_order_id,
            )
            await self._ledger_repo.post_entry(entry)
            await self._publish(LedgerEntryPosted(
                aggregate_id=f"ledger:{entry.reference}",
                aggregate_type="ledger",
                actor_user_id=user_id,
                payload={"reference": entry.reference, "entry_type": "trade"},
            ))
