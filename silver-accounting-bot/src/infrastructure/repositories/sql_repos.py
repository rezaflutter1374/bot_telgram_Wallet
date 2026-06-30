from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Numeric, func, or_, select

from domain.enums import (
    ExecutionType,
    JournalAccountType,
    KycStatus,
    NotificationStatus,
    MarginAlertLevel,
    MarginMode,
    OrderCancellationStatus,
    OrderSide,
    OrderStatus,
    OrderTimeInForce,
    OrderType,
    PaymentStatus,
    PaymentType,
    RiskScoreLevel,
    RiskViolationSeverity,
    RiskViolationStatus,
    TicketPriority,
    TicketStatus,
)
from infrastructure.db.models import (
    AuditEvent,
    BankAccount,
    FinancialPeriod,
    JournalAccount,
    JournalEntry,
    JournalLine,
    LiquidationEvent,
    MarginAccount,
    MarginSnapshot,
    MarginCall,
    Notification,
    Order,
    OrderCancellation,
    OrderExecutionReport,
    Permission,
    PaymentRequest,
    PaymentCard,
    PaymentReconciliation,
    Position,
    Price,
    PriceAnomaly,
    PriceProviderStatus,
    RiskRule,
    RiskSnapshot,
    RiskViolation,
    Role,
    RolePermission,
    Ticket,
    TicketMessage,
    Trade,
    User,
    UserRole,
    Wallet,
)
from infrastructure.db.base import Base
from infrastructure.db.session import SqlAlchemyUnitOfWork


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def json_dumps(value: object) -> str:
    def _default(obj: object) -> object:
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, Enum):
            return obj.value
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    return json.dumps(value, ensure_ascii=False, default=_default)


def _as_kyc(value: str | KycStatus) -> KycStatus:
    if isinstance(value, KycStatus):
        return value
    return KycStatus(value)


def _as_order_side(value: str | OrderSide) -> OrderSide:
    if isinstance(value, OrderSide):
        return value
    return OrderSide(value)


def _as_order_type(value: str | OrderType) -> OrderType:
    if isinstance(value, OrderType):
        return value
    return OrderType(value)


def _as_order_time_in_force(value: str | OrderTimeInForce) -> OrderTimeInForce:
    if isinstance(value, OrderTimeInForce):
        return value
    return OrderTimeInForce(value)


def _as_order_status(value: str | OrderStatus) -> OrderStatus:
    if isinstance(value, OrderStatus):
        return value
    return OrderStatus(value)


def _as_order_cancellation_status(value: str | OrderCancellationStatus) -> OrderCancellationStatus:
    if isinstance(value, OrderCancellationStatus):
        return value
    return OrderCancellationStatus(value)


def _as_execution_type(value: str | ExecutionType) -> ExecutionType:
    if isinstance(value, ExecutionType):
        return value
    return ExecutionType(value)


def _as_margin_mode(value: str | MarginMode) -> MarginMode:
    if isinstance(value, MarginMode):
        return value
    return MarginMode(value)


def _as_margin_health(value: str | MarginAlertLevel) -> MarginAlertLevel:
    if isinstance(value, MarginAlertLevel):
        return value
    return MarginAlertLevel(value)


def _as_risk_violation_severity(value: str | RiskViolationSeverity) -> RiskViolationSeverity:
    if isinstance(value, RiskViolationSeverity):
        return value
    return RiskViolationSeverity(value)


def _as_risk_violation_status(value: str | RiskViolationStatus) -> RiskViolationStatus:
    if isinstance(value, RiskViolationStatus):
        return value
    return RiskViolationStatus(value)


def _as_ticket_priority(value: str | TicketPriority) -> TicketPriority:
    if isinstance(value, TicketPriority):
        return value
    return TicketPriority(value)


def _as_ticket_status(value: str | TicketStatus) -> TicketStatus:
    if isinstance(value, TicketStatus):
        return value
    return TicketStatus(value)


class SqlUserRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def get_by_telegram_id(self, telegram_id: int) -> dict | None:
        session = self._session()
        row = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if row is None:
            return None
        return {
            "id": row.id,
            "telegram_id": row.telegram_id,
            "full_name": row.full_name,
            "phone_number": row.phone_number,
            "language_code": row.language_code,
            "kyc_status": _as_kyc(row.kyc_status),
            "created_at": row.created_at,
        }

    async def get(self, user_id: int) -> dict | None:
        session = self._session()
        row = await session.get(User, user_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "telegram_id": row.telegram_id,
            "full_name": row.full_name,
            "phone_number": row.phone_number,
            "language_code": row.language_code,
            "kyc_status": _as_kyc(row.kyc_status),
            "created_at": row.created_at,
        }

    async def list_users(
        self,
        *,
        role: str | None = None,
        kyc_status: KycStatus | None = None,
        language_code: str | None = None,
        trading_active: bool | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        session = self._session()
        stmt = select(User).order_by(User.created_at.asc()).limit(limit)
        if role is not None:
            stmt = stmt.join(UserRole, UserRole.user_id == User.id).join(Role, Role.id == UserRole.role_id).where(Role.name == role).distinct()
        if kyc_status is not None:
            stmt = stmt.where(User.kyc_status == kyc_status.value)
        if language_code is not None:
            stmt = stmt.where(User.language_code == language_code)
        if trading_active is True:
            stmt = stmt.where(
                or_(
                    select(Position.id).where(Position.user_id == User.id, Position.net_kg != 0).exists(),
                    select(Order.id).where(Order.user_id == User.id).exists(),
                )
            )
        elif trading_active is False:
            stmt = stmt.where(
                ~or_(
                    select(Position.id).where(Position.user_id == User.id, Position.net_kg != 0).exists(),
                    select(Order.id).where(Order.user_id == User.id).exists(),
                )
            )
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": row.id,
                "telegram_id": row.telegram_id,
                "full_name": row.full_name,
                "phone_number": row.phone_number,
                "language_code": row.language_code,
                "kyc_status": _as_kyc(row.kyc_status),
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def create_user(
        self,
        telegram_id: int,
        full_name: str | None,
        phone_number: str | None,
        kyc_status: KycStatus,
        language_code: str | None = None,
    ) -> dict:
        session = self._session()
        user = User(
            telegram_id=telegram_id,
            full_name=full_name,
            phone_number=phone_number,
            language_code=language_code,
            kyc_status=kyc_status.value,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(user)
        await session.flush()
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "full_name": user.full_name,
            "phone_number": user.phone_number,
            "language_code": user.language_code,
            "kyc_status": _as_kyc(user.kyc_status),
            "created_at": user.created_at,
        }

    async def update_kyc(
        self,
        user_id: int,
        full_name: str | None,
        phone_number: str | None,
        national_id_enc: str | None,
        passport_file_id_enc: str | None,
        selfie_file_id_enc: str | None,
        verification_docs_file_ids_enc: list[str],
        kyc_status: KycStatus,
    ) -> dict:
        session = self._session()
        user = await session.get(User, user_id)
        if user is None:
            raise RuntimeError("User not found")
        user.full_name = full_name
        user.phone_number = phone_number
        user.national_id_enc = national_id_enc
        user.passport_file_id_enc = passport_file_id_enc
        user.selfie_file_id_enc = selfie_file_id_enc
        user.verification_docs_file_ids_enc = json.dumps(verification_docs_file_ids_enc, ensure_ascii=False)
        user.kyc_status = kyc_status.value
        user.updated_at = utcnow()
        await session.flush()
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "full_name": user.full_name,
            "phone_number": user.phone_number,
            "language_code": user.language_code,
            "kyc_status": _as_kyc(user.kyc_status),
            "created_at": user.created_at,
        }

    async def set_kyc_status(self, user_id: int, kyc_status: KycStatus) -> dict:
        session = self._session()
        user = await session.get(User, user_id)
        if user is None:
            raise RuntimeError("User not found")
        user.kyc_status = kyc_status.value
        user.updated_at = utcnow()
        await session.flush()
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "full_name": user.full_name,
            "phone_number": user.phone_number,
            "language_code": user.language_code,
            "kyc_status": _as_kyc(user.kyc_status),
            "created_at": user.created_at,
        }

    async def set_language_code(self, user_id: int, language_code: str | None) -> dict:
        session = self._session()
        user = await session.get(User, user_id)
        if user is None:
            raise RuntimeError("User not found")
        user.language_code = language_code.strip().lower() if language_code else None
        user.updated_at = utcnow()
        await session.flush()
        return {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "full_name": user.full_name,
            "phone_number": user.phone_number,
            "language_code": user.language_code,
            "kyc_status": _as_kyc(user.kyc_status),
            "created_at": user.created_at,
        }


class SqlWalletRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def ensure_wallet(self, user_id: int) -> dict:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            wallet = Wallet(user_id=user_id, created_at=utcnow(), updated_at=utcnow())
            session.add(wallet)
        pos = await session.scalar(select(Position).where(Position.user_id == user_id))
        if pos is None:
            session.add(Position(user_id=user_id, updated_at=utcnow()))
        margin = await session.scalar(select(MarginAccount).where(MarginAccount.user_id == user_id))
        if margin is None:
            session.add(MarginAccount(user_id=user_id, updated_at=utcnow()))
        await session.flush()
        return {"user_id": user_id}

    async def get_wallet(self, user_id: int) -> dict | None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            return None
        return {
            "user_id": wallet.user_id,
            "available_balance_usd": Decimal(wallet.available_balance_usd),
            "frozen_balance_usd": Decimal(wallet.frozen_balance_usd),
            "margin_balance_usd": Decimal(wallet.margin_balance_usd),
            "pending_balance_usd": Decimal(wallet.pending_balance_usd),
            "settlement_balance_usd": Decimal(wallet.settlement_balance_usd),
            "equity_usd": Decimal(wallet.equity_usd),
        }

    async def credit_available(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def debit_available(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) - amount_usd
        wallet.updated_at = utcnow()

    async def freeze(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) - amount_usd
        wallet.frozen_balance_usd = Decimal(wallet.frozen_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def unfreeze(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.frozen_balance_usd = Decimal(wallet.frozen_balance_usd) - amount_usd
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def transfer_available_to_margin(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) - amount_usd
        wallet.margin_balance_usd = Decimal(wallet.margin_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def release_margin_to_available(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.margin_balance_usd = Decimal(wallet.margin_balance_usd) - amount_usd
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def apply_trade_cashflow(
        self,
        *,
        user_id: int,
        side: str,
        gross_amount_usd: Decimal,
        fee_usd: Decimal,
        reserved_balance_released_usd: Decimal,
        reserved_margin_released_usd: Decimal,
    ) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        available = Decimal(wallet.available_balance_usd)
        frozen = Decimal(wallet.frozen_balance_usd)
        margin_balance = Decimal(wallet.margin_balance_usd)
        if reserved_balance_released_usd > 0:
            frozen -= reserved_balance_released_usd
        if reserved_margin_released_usd > 0:
            margin_balance -= reserved_margin_released_usd
        if side == OrderSide.buy.value:
            spent = gross_amount_usd + fee_usd
            surplus = reserved_balance_released_usd - spent
            available += surplus
        else:
            available += gross_amount_usd - fee_usd
        wallet.available_balance_usd = available
        wallet.frozen_balance_usd = frozen
        wallet.margin_balance_usd = margin_balance
        wallet.equity_usd = available + frozen + margin_balance
        wallet.updated_at = utcnow()

    async def credit_pending(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.pending_balance_usd = Decimal(wallet.pending_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def debit_pending(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.pending_balance_usd = Decimal(wallet.pending_balance_usd) - amount_usd
        wallet.updated_at = utcnow()

    async def pending_to_available(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.pending_balance_usd = Decimal(wallet.pending_balance_usd) - amount_usd
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def available_to_pending(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) - amount_usd
        wallet.pending_balance_usd = Decimal(wallet.pending_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def credit_settlement(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.settlement_balance_usd = Decimal(wallet.settlement_balance_usd) + amount_usd
        wallet.updated_at = utcnow()

    async def debit_settlement(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.settlement_balance_usd = Decimal(wallet.settlement_balance_usd) - amount_usd
        wallet.updated_at = utcnow()

    async def settlement_to_available(self, user_id: int, amount_usd: Decimal) -> None:
        session = self._session()
        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == user_id))
        if wallet is None:
            raise RuntimeError("Wallet not found")
        wallet.settlement_balance_usd = Decimal(wallet.settlement_balance_usd) - amount_usd
        wallet.available_balance_usd = Decimal(wallet.available_balance_usd) + amount_usd
        wallet.updated_at = utcnow()


class SqlPriceRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    def _serialize_price(self, row: Price) -> dict:
        return {
            "id": row.id,
            "source": row.source,
            "buy_price": Decimal(row.buy_price),
            "sell_price": Decimal(row.sell_price),
            "spread": Decimal(row.spread),
            "commission": Decimal(row.commission),
            "premium": Decimal(row.premium),
            "discount": Decimal(row.discount),
            "is_verified": bool(row.is_verified),
            "is_stale": bool(row.is_stale),
            "updated_at": ensure_utc(row.updated_at),
        }

    async def get_latest(self, *, valid_only: bool = True) -> dict | None:
        session = self._session()
        stmt = select(Price).order_by(Price.updated_at.desc())
        if valid_only:
            stmt = stmt.where(Price.is_verified.is_(True), Price.is_stale.is_(False))
        row = await session.scalar(stmt)
        if row is None:
            return None
        return self._serialize_price(row)

    async def get_last_good(self) -> dict | None:
        session = self._session()
        row = await session.scalar(
            select(Price)
            .where(Price.is_verified.is_(True), Price.is_stale.is_(False))
            .order_by(Price.updated_at.desc())
        )
        if row is None:
            return None
        return self._serialize_price(row)

    async def upsert(
        self,
        buy_price: Decimal,
        sell_price: Decimal,
        spread: Decimal,
        commission: Decimal,
        premium: Decimal,
        discount: Decimal,
        *,
        source: str = "manual_admin",
        external_id: str | None = None,
        provider_timestamp: datetime | None = None,
        is_verified: bool = True,
        is_stale: bool = False,
        raw_payload: str | None = None,
    ) -> dict:
        session = self._session()
        row = Price(
            source=source,
            external_id=external_id,
            provider_timestamp=ensure_utc(provider_timestamp) if provider_timestamp is not None else None,
            buy_price=buy_price,
            sell_price=sell_price,
            spread=spread,
            commission=commission,
            premium=premium,
            discount=discount,
            is_verified=is_verified,
            is_stale=is_stale,
            raw_payload=raw_payload,
            updated_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return self._serialize_price(row)

    async def is_duplicate(
        self,
        *,
        source: str,
        buy_price: Decimal,
        sell_price: Decimal,
        provider_timestamp: datetime | None,
        window_seconds: int = 60,
    ) -> bool:
        session = self._session()
        stmt = (
            select(Price)
            .where(
                Price.source == source,
                Price.buy_price == buy_price,
                Price.sell_price == sell_price,
            )
            .order_by(Price.updated_at.desc())
        )
        if provider_timestamp is not None:
            base_dt = ensure_utc(provider_timestamp)
            stmt = stmt.where(
                Price.provider_timestamp.is_not(None),
                Price.provider_timestamp >= base_dt - timedelta(seconds=window_seconds),
                Price.provider_timestamp <= base_dt + timedelta(seconds=window_seconds),
            )
        else:
            stmt = stmt.where(Price.updated_at >= utcnow() - timedelta(seconds=window_seconds))
        return await session.scalar(stmt) is not None

    async def set_provider_status(
        self,
        *,
        provider_name: str,
        is_healthy: bool,
        checked_at: datetime,
        error: str | None = None,
        last_price_usd_per_kg: Decimal | None = None,
    ) -> dict:
        session = self._session()
        row = await session.scalar(select(PriceProviderStatus).where(PriceProviderStatus.provider_name == provider_name))
        checked_at = ensure_utc(checked_at)
        if row is None:
            row = PriceProviderStatus(
                provider_name=provider_name,
                is_healthy=is_healthy,
                consecutive_failures=0 if is_healthy else 1,
                last_success_at=checked_at if is_healthy else None,
                last_failure_at=None if is_healthy else checked_at,
                last_error=None if is_healthy else error,
                last_price_usd_per_kg=last_price_usd_per_kg,
                updated_at=checked_at,
            )
            session.add(row)
        else:
            row.is_healthy = is_healthy
            row.updated_at = checked_at
            row.last_price_usd_per_kg = last_price_usd_per_kg
            if is_healthy:
                row.consecutive_failures = 0
                row.last_success_at = checked_at
                row.last_error = None
            else:
                row.consecutive_failures = int(row.consecutive_failures) + 1
                row.last_failure_at = checked_at
                row.last_error = error
        await session.flush()
        return {
            "provider_name": row.provider_name,
            "is_healthy": bool(row.is_healthy),
            "consecutive_failures": int(row.consecutive_failures),
            "last_error": row.last_error,
            "last_price_usd_per_kg": Decimal(row.last_price_usd_per_kg) if row.last_price_usd_per_kg is not None else None,
            "updated_at": ensure_utc(row.updated_at),
        }

    async def detect_anomaly(
        self,
        *,
        anomaly_type: str,
        severity: str,
        observed_value_usd: Decimal,
        expected_value_usd: Decimal,
        deviation_pct: Decimal,
        threshold_pct: Decimal,
        price_id: int,
        payload: dict | None = None,
    ) -> dict | None:
        session = self._session()
        existing = await session.scalar(
            select(PriceAnomaly).where(
                PriceAnomaly.price_id == price_id,
                PriceAnomaly.anomaly_type == anomaly_type,
                PriceAnomaly.is_resolved.is_(False),
            )
        )
        if existing is not None:
            return None
        row = PriceAnomaly(
            price_id=price_id,
            anomaly_type=anomaly_type,
            severity=severity,
            observed_value_usd=observed_value_usd,
            expected_value_usd=expected_value_usd,
            deviation_pct=deviation_pct,
            threshold_pct=threshold_pct,
            is_resolved=False,
            payload_json=json.dumps(payload or {}, default=str),
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return {
            "id": row.id,
            "anomaly_type": row.anomaly_type,
            "severity": row.severity,
            "observed_value_usd": Decimal(row.observed_value_usd),
            "expected_value_usd": Decimal(row.expected_value_usd),
            "deviation_pct": Decimal(row.deviation_pct),
            "threshold_pct": Decimal(row.threshold_pct),
            "is_resolved": bool(row.is_resolved),
        }

    async def list_anomalies(
        self,
        *,
        anomaly_type: str | None = None,
        is_resolved: bool | None = None,
        limit: int = 50,
    ) -> list[dict]:
        session = self._session()
        stmt = select(PriceAnomaly).order_by(PriceAnomaly.created_at.desc()).limit(limit)
        if anomaly_type is not None:
            stmt = stmt.where(PriceAnomaly.anomaly_type == anomaly_type)
        if is_resolved is not None:
            stmt = stmt.where(PriceAnomaly.is_resolved.is_(is_resolved))
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": r.id,
                "price_id": r.price_id,
                "anomaly_type": r.anomaly_type,
                "severity": r.severity,
                "observed_value_usd": Decimal(r.observed_value_usd),
                "expected_value_usd": Decimal(r.expected_value_usd),
                "deviation_pct": Decimal(r.deviation_pct),
                "threshold_pct": Decimal(r.threshold_pct),
                "is_resolved": bool(r.is_resolved),
                "resolved_at": r.resolved_at,
                "created_at": r.created_at,
            }
            for r in rows
        ]

    async def resolve_anomaly(self, anomaly_id: int, resolved_by_user_id: int) -> dict | None:
        session = self._session()
        row = await session.get(PriceAnomaly, anomaly_id)
        if row is None:
            return None
        row.is_resolved = True
        row.resolved_by_user_id = resolved_by_user_id
        row.resolved_at = utcnow()
        await session.flush()
        return {
            "id": row.id,
            "is_resolved": True,
            "resolved_at": row.resolved_at,
            "resolved_by_user_id": row.resolved_by_user_id,
        }

    async def get_price_history(self, limit: int = 20) -> list[dict]:
        session = self._session()
        rows = (
            await session.scalars(
                select(Price).order_by(Price.updated_at.desc()).limit(limit)
            )
        ).all()
        return [self._serialize_price(r) for r in rows]


class SqlOrderRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    def _serialize_order(self, order: Order) -> dict:
        return {
            "id": order.id,
            "user_id": order.user_id,
            "side": _as_order_side(order.side),
            "order_type": _as_order_type(order.order_type),
            "time_in_force": _as_order_time_in_force(order.time_in_force),
            "quantity_kg": Decimal(order.quantity_kg),
            "remaining_quantity_kg": Decimal(order.remaining_quantity_kg),
            "filled_quantity_kg": Decimal(order.filled_quantity_kg),
            "quoted_price": Decimal(order.quoted_price),
            "limit_price": Decimal(order.limit_price) if order.limit_price is not None else None,
            "stop_price": Decimal(order.stop_price) if order.stop_price is not None else None,
            "average_fill_price_usd": Decimal(order.average_fill_price_usd),
            "notional_value_usd": Decimal(order.notional_value_usd),
            "reserved_balance_usd": Decimal(order.reserved_balance_usd),
            "reserved_margin_usd": Decimal(order.reserved_margin_usd),
            "executed_fee_usd": Decimal(order.executed_fee_usd),
            "slippage_bps": Decimal(order.slippage_bps),
            "post_only": bool(order.post_only),
            "reduce_only": bool(order.reduce_only),
            "is_triggered": bool(order.is_triggered),
            "client_order_id": order.client_order_id,
            "idempotency_key": order.idempotency_key,
            "quote_expires_at": ensure_utc(order.quote_expires_at),
            "status": _as_order_status(order.status),
            "receipt_file_id_enc": order.receipt_file_id_enc,
            "created_at": ensure_utc(order.created_at),
            "updated_at": ensure_utc(order.updated_at),
            "executed_at": ensure_utc(order.executed_at) if order.executed_at is not None else None,
            "cancelled_at": ensure_utc(order.cancelled_at) if order.cancelled_at is not None else None,
        }

    def _serialize_trade(self, trade: Trade) -> dict:
        return {
            "id": trade.id,
            "match_key": trade.match_key,
            "maker_order_id": trade.maker_order_id,
            "taker_order_id": trade.taker_order_id,
            "buy_order_id": trade.buy_order_id,
            "sell_order_id": trade.sell_order_id,
            "price_usd": Decimal(trade.price_usd),
            "quantity_kg": Decimal(trade.quantity_kg),
            "buy_fee_usd": Decimal(trade.buy_fee_usd),
            "sell_fee_usd": Decimal(trade.sell_fee_usd),
            "slippage_bps": Decimal(trade.slippage_bps),
            "payload": json.loads(trade.payload_json),
            "executed_at": ensure_utc(trade.executed_at),
        }

    def _serialize_execution_report(self, row: OrderExecutionReport) -> dict:
        return {
            "id": row.id,
            "order_id": row.order_id,
            "trade_id": row.trade_id,
            "sequence_no": row.sequence_no,
            "execution_type": _as_execution_type(row.execution_type),
            "status": _as_order_status(row.status),
            "quantity_kg": Decimal(row.quantity_kg),
            "price_usd": Decimal(row.price_usd),
            "fee_usd": Decimal(row.fee_usd),
            "payload": json.loads(row.payload_json),
            "created_at": ensure_utc(row.created_at),
        }

    async def create_order(
        self,
        user_id: int,
        side: OrderSide,
        order_type: OrderType,
        time_in_force: OrderTimeInForce,
        quantity_kg: Decimal,
        quoted_price: Decimal,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
        reserved_balance_usd: Decimal,
        reserved_margin_usd: Decimal,
        post_only: bool,
        reduce_only: bool,
        client_order_id: str | None,
        idempotency_key: str | None,
        quote_expires_at: datetime,
    ) -> dict:
        session = self._session()
        order = Order(
            user_id=user_id,
            side=side.value,
            order_type=order_type.value,
            time_in_force=time_in_force.value,
            quantity_kg=quantity_kg,
            remaining_quantity_kg=quantity_kg,
            filled_quantity_kg=Decimal("0"),
            quoted_price=quoted_price,
            limit_price=limit_price,
            stop_price=stop_price,
            average_fill_price_usd=Decimal("0"),
            notional_value_usd=(quantity_kg * quoted_price).quantize(Decimal("0.000001")),
            reserved_balance_usd=reserved_balance_usd,
            reserved_margin_usd=reserved_margin_usd,
            executed_fee_usd=Decimal("0"),
            slippage_bps=Decimal("0"),
            post_only=post_only,
            reduce_only=reduce_only,
            is_triggered=order_type in {OrderType.market, OrderType.limit, OrderType.manual},
            client_order_id=client_order_id,
            idempotency_key=idempotency_key,
            quote_expires_at=quote_expires_at,
            status=OrderStatus.open.value if order_type != OrderType.manual else OrderStatus.awaiting_payment.value,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(order)
        await session.flush()
        return self._serialize_order(order)

    async def get(self, order_id: int) -> dict | None:
        session = self._session()
        order = await session.get(Order, order_id)
        if order is None:
            return None
        return self._serialize_order(order)

    async def get_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        session = self._session()
        order = await session.scalar(select(Order).where(Order.idempotency_key == idempotency_key))
        if order is None:
            return None
        return self._serialize_order(order)

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[dict]:
        session = self._session()
        res = await session.scalars(select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(limit))
        return [self._serialize_order(order) for order in res.all()]

    async def list_open_orders(self, *, side: OrderSide | None = None, limit: int = 100) -> list[dict]:
        session = self._session()
        stmt = select(Order).where(
            Order.status.in_([OrderStatus.open.value, OrderStatus.partially_filled.value]),
            Order.remaining_quantity_kg > 0,
        )
        if side is not None:
            stmt = stmt.where(Order.side == side.value)
        stmt = stmt.order_by(Order.quoted_price.asc() if side == OrderSide.buy else Order.quoted_price.desc(), Order.created_at.asc()).limit(limit)
        rows = (await session.scalars(stmt)).all()
        return [self._serialize_order(row) for row in rows]

    async def list_triggerable_orders(self, current_price: Decimal, *, limit: int = 100) -> list[dict]:
        session = self._session()
        rows = (
            await session.scalars(
                select(Order)
                .where(
                    Order.status == OrderStatus.open.value,
                    Order.is_triggered.is_(False),
                    Order.stop_price.is_not(None),
                )
                .order_by(Order.created_at.asc())
                .limit(limit)
            )
        ).all()
        result: list[dict] = []
        for row in rows:
            stop_price = Decimal(row.stop_price or 0)
            if row.side == OrderSide.buy.value and current_price >= stop_price:
                result.append(self._serialize_order(row))
            if row.side == OrderSide.sell.value and current_price <= stop_price:
                result.append(self._serialize_order(row))
        return result

    async def list_expired_orders(self, as_of: datetime, *, limit: int = 100) -> list[dict]:
        session = self._session()
        rows = (
            await session.scalars(
                select(Order)
                .where(
                    Order.status.in_([OrderStatus.open.value, OrderStatus.partially_filled.value, OrderStatus.awaiting_payment.value]),
                    Order.quote_expires_at <= ensure_utc(as_of),
                )
                .order_by(Order.quote_expires_at.asc())
                .limit(limit)
            )
        ).all()
        return [self._serialize_order(row) for row in rows]

    async def mark_triggered(self, order_id: int) -> dict:
        session = self._session()
        order = await session.get(Order, order_id)
        if order is None:
            raise RuntimeError("Order not found")
        order.is_triggered = True
        order.updated_at = utcnow()
        await session.flush()
        return self._serialize_order(order)

    async def attach_receipt(self, order_id: int, receipt_file_id_enc: str, status: OrderStatus) -> dict:
        session = self._session()
        order = await session.get(Order, order_id)
        if order is None:
            raise RuntimeError("Order not found")
        order.receipt_file_id_enc = receipt_file_id_enc
        order.status = status.value
        order.updated_at = utcnow()
        await session.flush()
        return self._serialize_order(order)

    async def set_status(self, order_id: int, status: OrderStatus) -> dict:
        session = self._session()
        order = await session.get(Order, order_id)
        if order is None:
            raise RuntimeError("Order not found")
        order.status = status.value
        if status == OrderStatus.cancelled:
            order.cancelled_at = utcnow()
        if status in {OrderStatus.filled, OrderStatus.completed}:
            order.executed_at = utcnow()
        order.updated_at = utcnow()
        await session.flush()
        return self._serialize_order(order)

    async def apply_fill(
        self,
        *,
        order_id: int,
        filled_quantity_kg: Decimal,
        fill_price_usd: Decimal,
        fee_usd: Decimal,
        slippage_bps: Decimal,
        status: OrderStatus,
        executed_at: datetime,
    ) -> dict:
        session = self._session()
        order = await session.get(Order, order_id)
        if order is None:
            raise RuntimeError("Order not found")
        previous_filled = Decimal(order.filled_quantity_kg)
        new_filled = (previous_filled + filled_quantity_kg).quantize(Decimal("0.000001"))
        total_notional_before = previous_filled * Decimal(order.average_fill_price_usd)
        total_notional_after = total_notional_before + (filled_quantity_kg * fill_price_usd)
        order.filled_quantity_kg = new_filled
        order.remaining_quantity_kg = (Decimal(order.quantity_kg) - new_filled).quantize(Decimal("0.000001"))
        order.average_fill_price_usd = (
            (total_notional_after / new_filled).quantize(Decimal("0.000001")) if new_filled > 0 else Decimal("0")
        )
        order.executed_fee_usd = Decimal(order.executed_fee_usd) + fee_usd
        order.slippage_bps = slippage_bps
        order.status = status.value
        order.executed_at = ensure_utc(executed_at)
        order.updated_at = utcnow()
        await session.flush()
        return self._serialize_order(order)

    async def release_reservations(self, order_id: int) -> dict:
        session = self._session()
        order = await session.get(Order, order_id)
        if order is None:
            raise RuntimeError("Order not found")
        order.reserved_balance_usd = Decimal("0")
        order.reserved_margin_usd = Decimal("0")
        order.updated_at = utcnow()
        await session.flush()
        return self._serialize_order(order)

    async def create_trade(
        self,
        *,
        maker_order_id: int,
        taker_order_id: int,
        buy_order_id: int,
        sell_order_id: int,
        match_key: str,
        price_usd: Decimal,
        quantity_kg: Decimal,
        buy_fee_usd: Decimal,
        sell_fee_usd: Decimal,
        slippage_bps: Decimal,
        payload: dict,
        executed_at: datetime,
    ) -> dict:
        session = self._session()
        trade = Trade(
            match_key=match_key,
            maker_order_id=maker_order_id,
            taker_order_id=taker_order_id,
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
            price_usd=price_usd,
            quantity_kg=quantity_kg,
            buy_fee_usd=buy_fee_usd,
            sell_fee_usd=sell_fee_usd,
            slippage_bps=slippage_bps,
            payload_json=json_dumps(payload),
            executed_at=ensure_utc(executed_at),
        )
        session.add(trade)
        await session.flush()
        return self._serialize_trade(trade)

    async def add_execution_report(
        self,
        *,
        order_id: int,
        execution_type: ExecutionType,
        status: OrderStatus,
        quantity_kg: Decimal,
        price_usd: Decimal,
        fee_usd: Decimal,
        payload: dict,
        trade_id: int | None = None,
    ) -> dict:
        session = self._session()
        current_seq = await session.scalar(
            select(func.coalesce(func.max(OrderExecutionReport.sequence_no), 0)).where(OrderExecutionReport.order_id == order_id)
        )
        row = OrderExecutionReport(
            order_id=order_id,
            trade_id=trade_id,
            sequence_no=int(current_seq or 0) + 1,
            execution_type=execution_type.value,
            status=status.value,
            quantity_kg=quantity_kg,
            price_usd=price_usd,
            fee_usd=fee_usd,
            payload_json=json_dumps(payload),
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return self._serialize_execution_report(row)

    async def list_execution_reports(self, order_id: int, limit: int = 100) -> list[dict]:
        session = self._session()
        rows = (
            await session.scalars(
                select(OrderExecutionReport)
                .where(OrderExecutionReport.order_id == order_id)
                .order_by(OrderExecutionReport.sequence_no.asc())
                .limit(limit)
            )
        ).all()
        return [self._serialize_execution_report(row) for row in rows]

    async def get_trade(self, trade_id: int) -> dict | None:
        session = self._session()
        row = await session.get(Trade, trade_id)
        if row is None:
            return None
        return self._serialize_trade(row)

    async def list_trade_history(self, *, user_id: int | None = None, limit: int = 100) -> list[dict]:
        session = self._session()
        stmt = select(Trade).order_by(Trade.executed_at.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.join(Order, Order.id == Trade.buy_order_id).where(
                or_(
                    Trade.buy_order_id.in_(select(Order.id).where(Order.user_id == user_id)),
                    Trade.sell_order_id.in_(select(Order.id).where(Order.user_id == user_id)),
                )
            )
        rows = (await session.scalars(stmt)).all()
        return [self._serialize_trade(row) for row in rows]

    async def get_cancellation(self, order_id: int) -> dict | None:
        session = self._session()
        row = await session.scalar(select(OrderCancellation).where(OrderCancellation.order_id == order_id))
        if row is None:
            return None
        return {
            "id": row.id,
            "order_id": row.order_id,
            "requested_by_user_id": row.requested_by_user_id,
            "status": _as_order_cancellation_status(row.status),
            "admin_approved_at": row.admin_approved_at,
            "user_confirmed_at": row.user_confirmed_at,
            "rejected_at": row.rejected_at,
            "created_at": row.created_at,
        }

    async def request_cancellation(self, order_id: int, requested_by_user_id: int) -> dict:
        session = self._session()
        row = await session.scalar(select(OrderCancellation).where(OrderCancellation.order_id == order_id))
        if row is None:
            row = OrderCancellation(
                order_id=order_id,
                requested_by_user_id=requested_by_user_id,
                status=OrderCancellationStatus.requested.value,
                created_at=utcnow(),
            )
            session.add(row)
        else:
            row.requested_by_user_id = requested_by_user_id
            row.status = OrderCancellationStatus.requested.value
            row.admin_approved_at = None
            row.user_confirmed_at = None
            row.rejected_at = None
        await session.flush()
        return {
            "id": row.id,
            "order_id": row.order_id,
            "requested_by_user_id": row.requested_by_user_id,
            "status": _as_order_cancellation_status(row.status),
            "admin_approved_at": row.admin_approved_at,
            "user_confirmed_at": row.user_confirmed_at,
            "rejected_at": row.rejected_at,
            "created_at": row.created_at,
        }

    async def set_cancellation_status(self, order_id: int, status: OrderCancellationStatus) -> dict:
        session = self._session()
        row = await session.scalar(select(OrderCancellation).where(OrderCancellation.order_id == order_id))
        if row is None:
            raise RuntimeError("Cancellation not found")
        row.status = status.value
        now = utcnow()
        if status == OrderCancellationStatus.admin_approved:
            row.admin_approved_at = now
        elif status == OrderCancellationStatus.user_confirmed:
            row.user_confirmed_at = now
        elif status == OrderCancellationStatus.rejected:
            row.rejected_at = now
        await session.flush()
        return {
            "id": row.id,
            "order_id": row.order_id,
            "requested_by_user_id": row.requested_by_user_id,
            "status": _as_order_cancellation_status(row.status),
            "admin_approved_at": row.admin_approved_at,
            "user_confirmed_at": row.user_confirmed_at,
            "rejected_at": row.rejected_at,
            "created_at": row.created_at,
        }

    async def list_pending_cancellations(self, limit: int = 50) -> list[dict]:
        session = self._session()
        res = await session.scalars(
            select(OrderCancellation)
            .where(OrderCancellation.status.in_([OrderCancellationStatus.requested.value, OrderCancellationStatus.admin_approved.value]))
            .order_by(OrderCancellation.created_at.asc())
            .limit(limit)
        )
        rows = []
        for row in res.all():
            rows.append(
                {
                    "id": row.id,
                    "order_id": row.order_id,
                    "requested_by_user_id": row.requested_by_user_id,
                    "status": _as_order_cancellation_status(row.status),
                    "admin_approved_at": row.admin_approved_at,
                    "user_confirmed_at": row.user_confirmed_at,
                    "rejected_at": row.rejected_at,
                    "created_at": row.created_at,
                }
            )
        return rows


class SqlPositionRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    def _serialize_position(self, pos: Position) -> dict:
        return {
            "user_id": pos.user_id,
            "net_kg": Decimal(pos.net_kg),
            "avg_price_usd": Decimal(pos.avg_price_usd),
            "last_settlement_price_usd": Decimal(pos.last_settlement_price_usd),
            "updated_at": ensure_utc(pos.updated_at),
        }

    async def get_net_kg(self, user_id: int) -> Decimal:
        session = self._session()
        pos = await session.scalar(select(Position).where(Position.user_id == user_id))
        if pos is None:
            pos = Position(user_id=user_id, updated_at=utcnow())
            session.add(pos)
            await session.flush()
        return Decimal(pos.net_kg)

    async def adjust_net_kg(self, user_id: int, delta_kg: Decimal, avg_price_usd: Decimal) -> None:
        session = self._session()
        pos = await session.scalar(select(Position).where(Position.user_id == user_id))
        if pos is None:
            pos = Position(user_id=user_id, updated_at=utcnow())
            session.add(pos)
            await session.flush()
        net_before = Decimal(pos.net_kg)
        net_after = (net_before + delta_kg).quantize(Decimal("0.000001"))
        pos.net_kg = net_after
        if net_after > 0 and delta_kg > 0:
            pos.avg_price_usd = Decimal(avg_price_usd)
        pos.updated_at = utcnow()

    async def get_position(self, user_id: int) -> dict:
        session = self._session()
        pos = await session.scalar(select(Position).where(Position.user_id == user_id))
        if pos is None:
            pos = Position(user_id=user_id, updated_at=utcnow())
            session.add(pos)
            await session.flush()
        return self._serialize_position(pos)

    async def apply_trade(
        self,
        *,
        user_id: int,
        side: str,
        quantity_kg: Decimal,
        price_usd: Decimal,
    ) -> dict:
        session = self._session()
        pos = await session.scalar(select(Position).where(Position.user_id == user_id))
        if pos is None:
            pos = Position(user_id=user_id, updated_at=utcnow())
            session.add(pos)
            await session.flush()
        signed_qty = quantity_kg if side == OrderSide.buy.value else -quantity_kg
        current_qty = Decimal(pos.net_kg)
        current_avg = Decimal(pos.avg_price_usd)
        next_qty = (current_qty + signed_qty).quantize(Decimal("0.000001"))
        if current_qty == 0 or (current_qty > 0 and signed_qty > 0) or (current_qty < 0 and signed_qty < 0):
            total_qty = abs(current_qty) + abs(signed_qty)
            if total_qty > 0:
                weighted_notional = (abs(current_qty) * current_avg) + (abs(signed_qty) * price_usd)
                pos.avg_price_usd = (weighted_notional / total_qty).quantize(Decimal("0.000001"))
        elif next_qty == 0:
            pos.avg_price_usd = Decimal("0")
        elif current_qty > 0 > next_qty or current_qty < 0 < next_qty:
            pos.avg_price_usd = price_usd
        pos.net_kg = next_qty
        pos.updated_at = utcnow()
        await session.flush()
        return self._serialize_position(pos)


class SqlTicketRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def create_ticket(self, user_id: int, subject: str, priority: TicketPriority) -> dict:
        session = self._session()
        ticket = Ticket(
            user_id=user_id,
            subject=subject,
            priority=priority.value,
            status=TicketStatus.open.value,
            created_at=utcnow(),
        )
        session.add(ticket)
        await session.flush()
        return {
            "id": ticket.id,
            "user_id": ticket.user_id,
            "subject": ticket.subject,
            "priority": _as_ticket_priority(ticket.priority),
            "status": _as_ticket_status(ticket.status),
            "created_at": ticket.created_at,
        }

    async def get(self, ticket_id: int) -> dict | None:
        session = self._session()
        ticket = await session.get(Ticket, ticket_id)
        if ticket is None:
            return None
        return {
            "id": ticket.id,
            "user_id": ticket.user_id,
            "subject": ticket.subject,
            "priority": _as_ticket_priority(ticket.priority),
            "status": _as_ticket_status(ticket.status),
            "created_at": ticket.created_at,
        }

    async def add_message(
        self,
        ticket_id: int,
        author_user_id: int | None,
        author_role: str,
        message: str,
        attachment_file_ids_enc: list[str],
    ) -> dict:
        session = self._session()
        msg = TicketMessage(
            ticket_id=ticket_id,
            author_user_id=author_user_id,
            author_role=author_role,
            message=message,
            attachment_file_ids_enc=json.dumps(attachment_file_ids_enc, ensure_ascii=False),
            created_at=utcnow(),
        )
        session.add(msg)
        await session.flush()
        return {"id": msg.id}

    async def set_status(self, ticket_id: int, status: TicketStatus) -> dict:
        session = self._session()
        ticket = await session.get(Ticket, ticket_id)
        if ticket is None:
            raise RuntimeError("Ticket not found")
        ticket.status = status.value
        await session.flush()
        return {"id": ticket.id}

    async def list_tickets(
        self,
        *,
        user_id: int | None = None,
        status: TicketStatus | None = None,
        query: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        session = self._session()
        stmt = select(Ticket).order_by(Ticket.created_at.desc()).limit(limit)
        if user_id is not None:
            stmt = stmt.where(Ticket.user_id == user_id)
        if status is not None:
            stmt = stmt.where(Ticket.status == status.value)
        if query:
            like = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Ticket.subject.ilike(like),
                    select(TicketMessage.id).where(TicketMessage.ticket_id == Ticket.id, TicketMessage.message.ilike(like)).exists(),
                )
            )
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": ticket.id,
                "user_id": ticket.user_id,
                "subject": ticket.subject,
                "priority": _as_ticket_priority(ticket.priority),
                "status": _as_ticket_status(ticket.status),
                "created_at": ticket.created_at,
            }
            for ticket in rows
        ]


class SqlRoleRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def ensure_defaults(self) -> None:
        session = self._session()
        roles = [
            "guest",
            "verified_user",
            "trader",
            "support",
            "accountant",
            "manager",
            "admin",
            "super_admin",
        ]
        permissions = [
            "register",
            "verify_identity",
            "deposit",
            "withdraw",
            "trade",
            "view_orders",
            "open_ticket",
            "view_tickets",
            "reply_tickets",
            "close_tickets",
            "approve_payments",
            "reject_payments",
            "manage_accounts",
            "view_financial_reports",
            "export_reports",
            "manage_settlement",
            "monitor_statistics",
            "view_reports",
            "approve_critical_actions",
            "manage_users",
            "manage_orders",
            "manage_prices",
            "manage_wallets",
            "manage_roles",
            "broadcast_messages",
            "configure_system",
            "view_audit_logs",
        ]

        existing_roles = (await session.scalars(select(Role))).all()
        existing_role_names = {r.name for r in existing_roles}
        for name in roles:
            if name not in existing_role_names:
                session.add(Role(name=name))

        existing_perms = (await session.scalars(select(Permission))).all()
        existing_perm_names = {p.name for p in existing_perms}
        for name in permissions:
            if name not in existing_perm_names:
                session.add(Permission(name=name))

        await session.flush()

        role_rows = (await session.scalars(select(Role))).all()
        perm_rows = (await session.scalars(select(Permission))).all()
        role_by_name = {r.name: r for r in role_rows}
        perm_by_name = {p.name: p for p in perm_rows}

        grants: dict[str, set[str]] = {
            "guest": {"register"},
            "verified_user": {"deposit", "withdraw", "view_orders", "open_ticket", "view_tickets"},
            "trader": {"deposit", "withdraw", "trade", "view_orders"},
            "support": {"view_tickets", "reply_tickets", "close_tickets"},
            "accountant": {"approve_payments", "reject_payments", "manage_accounts", "view_financial_reports", "export_reports", "manage_settlement"},
            "manager": {"monitor_statistics", "view_reports", "approve_critical_actions"},
            "admin": {
                "verify_identity",
                "manage_users",
                "manage_orders",
                "manage_prices",
                "manage_wallets",
                "manage_roles",
                "broadcast_messages",
                "configure_system",
                "view_reports",
                "monitor_statistics",
                "view_audit_logs",
            },
            "super_admin": set(permissions),
        }

        existing_rp = (await session.scalars(select(RolePermission))).all()
        existing_pairs = {(rp.role_id, rp.permission_id) for rp in existing_rp}
        for role_name, perm_names in grants.items():
            role = role_by_name[role_name]
            for perm_name in perm_names:
                perm = perm_by_name[perm_name]
                pair = (role.id, perm.id)
                if pair not in existing_pairs:
                    session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await session.flush()

    async def grant_role(self, user_id: int, role: str) -> None:
        session = self._session()
        role_row = await session.scalar(select(Role).where(Role.name == role))
        if role_row is None:
            role_row = Role(name=role)
            session.add(role_row)
            await session.flush()
        existing = await session.scalar(select(UserRole).where(UserRole.user_id == user_id, UserRole.role_id == role_row.id))
        if existing is None:
            session.add(UserRole(user_id=user_id, role_id=role_row.id))
            await session.flush()

    async def user_has_permission(self, user_id: int, permission: str) -> bool:
        session = self._session()
        perm = await session.scalar(select(Permission).where(Permission.name == permission))
        if perm is None:
            return False
        res = await session.scalar(
            select(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .join(RolePermission, RolePermission.role_id == Role.id)
            .where(UserRole.user_id == user_id, RolePermission.permission_id == perm.id)
        )
        return res is not None

    async def get_user_roles(self, user_id: int) -> set[str]:
        session = self._session()
        res = await session.scalars(select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id))
        return set(res.all())


def _as_payment_type(value: str | PaymentType) -> PaymentType:
    if isinstance(value, PaymentType):
        return value
    return PaymentType(value)


def _as_payment_status(value: str | PaymentStatus) -> PaymentStatus:
    if isinstance(value, PaymentStatus):
        return value
    return PaymentStatus(value)


def _as_notification_status(value: str | NotificationStatus) -> NotificationStatus:
    if isinstance(value, NotificationStatus):
        return value
    return NotificationStatus(value)


def _as_account_type(value: str | JournalAccountType) -> JournalAccountType:
    if isinstance(value, JournalAccountType):
        return value
    return JournalAccountType(value)


class SqlPaymentRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def create_request(
        self,
        user_id: int,
        payment_type: PaymentType,
        amount_usd: Decimal,
        receipt_file_ids_enc: list[str],
        bank_account_id: int | None,
    ) -> dict:
        session = self._session()
        row = PaymentRequest(
            user_id=user_id,
            payment_type=payment_type.value,
            amount_usd=amount_usd,
            status=PaymentStatus.awaiting_review.value,
            receipt_file_ids_enc=json.dumps(receipt_file_ids_enc, ensure_ascii=False),
            bank_account_id=bank_account_id,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return {
            "id": row.id,
            "user_id": row.user_id,
            "payment_type": _as_payment_type(row.payment_type),
            "amount_usd": Decimal(row.amount_usd),
            "status": _as_payment_status(row.status),
            "created_at": row.created_at,
        }

    async def get(self, payment_id: int) -> dict | None:
        session = self._session()
        row = await session.get(PaymentRequest, payment_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "user_id": row.user_id,
            "payment_type": _as_payment_type(row.payment_type),
            "amount_usd": Decimal(row.amount_usd),
            "status": _as_payment_status(row.status),
            "receipt_file_ids_enc": json.loads(row.receipt_file_ids_enc),
            "bank_account_id": row.bank_account_id,
            "reviewer_user_id": row.reviewer_user_id,
            "review_note": row.review_note,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def list_for_user(self, user_id: int, limit: int = 20) -> list[dict]:
        session = self._session()
        res = await session.scalars(
            select(PaymentRequest)
            .where(PaymentRequest.user_id == user_id)
            .order_by(PaymentRequest.created_at.desc())
            .limit(limit)
        )
        items = []
        for row in res.all():
            items.append(
                {
                    "id": row.id,
                    "payment_type": _as_payment_type(row.payment_type),
                    "amount_usd": Decimal(row.amount_usd),
                    "status": _as_payment_status(row.status),
                    "created_at": row.created_at,
                }
            )
        return items

    async def list_pending(self, limit: int = 50) -> list[dict]:
        session = self._session()
        res = await session.scalars(
            select(PaymentRequest)
            .where(PaymentRequest.status.in_([PaymentStatus.uploaded.value, PaymentStatus.awaiting_review.value]))
            .order_by(PaymentRequest.created_at.asc())
            .limit(limit)
        )
        items = []
        for row in res.all():
            items.append(
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "payment_type": _as_payment_type(row.payment_type),
                    "amount_usd": Decimal(row.amount_usd),
                    "status": _as_payment_status(row.status),
                    "created_at": row.created_at,
                }
            )
        return items

    async def set_status(
        self,
        payment_id: int,
        status: PaymentStatus,
        reviewer_user_id: int | None,
        review_note: str | None,
    ) -> dict:
        session = self._session()
        row = await session.get(PaymentRequest, payment_id)
        if row is None:
            raise RuntimeError("Payment not found")
        row.status = status.value
        row.reviewer_user_id = reviewer_user_id
        row.review_note = review_note
        row.updated_at = utcnow()
        await session.flush()
        return {
            "id": row.id,
            "user_id": row.user_id,
            "payment_type": _as_payment_type(row.payment_type),
            "amount_usd": Decimal(row.amount_usd),
            "status": _as_payment_status(row.status),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    async def reconcile(self, payment_id: int, reference_number: str | None = None, reconciled_by_user_id: int | None = None) -> dict:
        session = self._session()
        row = await session.get(PaymentRequest, payment_id)
        if row is None:
            raise RuntimeError("Payment not found")
        session.add(
            PaymentReconciliation(
                payment_request_id=payment_id,
                reference_number=reference_number,
                reconciliation_status="reconciled",
                matched_at=utcnow(),
                created_at=utcnow(),
            )
        )
        await session.flush()
        return {"id": payment_id, "reconciled": True}


class SqlPaymentReconciliationRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def find_duplicate(self, user_id: int, amount_usd: Decimal, receipt_hash: str, window_hours: int = 24) -> dict | None:
        session = self._session()
        cutoff = utcnow() - timedelta(hours=window_hours)
        row = await session.scalar(
            select(PaymentReconciliation)
            .join(PaymentRequest, PaymentRequest.id == PaymentReconciliation.payment_request_id)
            .where(
                PaymentRequest.user_id == user_id,
                PaymentRequest.amount_usd == amount_usd,
                PaymentReconciliation.duplicate_check_hash == receipt_hash,
                PaymentReconciliation.created_at >= cutoff,
            )
        )
        if row is None:
            return None
        return {"id": row.id, "payment_request_id": row.payment_request_id, "is_duplicate": bool(row.is_duplicate)}

    async def find_by_reference(self, reference_number: str) -> dict | None:
        session = self._session()
        row = await session.scalar(select(PaymentReconciliation).where(PaymentReconciliation.reference_number == reference_number))
        if row is None:
            return None
        return {
            "id": row.id,
            "payment_request_id": row.payment_request_id,
            "reference_number": row.reference_number,
            "reconciliation_status": row.reconciliation_status,
        }

    async def record(self, payment_request_id: int, *, reference_number: str | None = None, duplicate_check_hash: str | None = None, is_duplicate: bool = False, matched_payment_request_id: int | None = None) -> dict:
        session = self._session()
        row = PaymentReconciliation(
            payment_request_id=payment_request_id,
            reference_number=reference_number,
            duplicate_check_hash=duplicate_check_hash,
            is_duplicate=is_duplicate,
            matched_payment_request_id=matched_payment_request_id,
            reconciliation_status="pending",
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return {"id": row.id, "payment_request_id": payment_request_id}


class SqlRiskRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    def _serialize_rule(self, row: RiskRule) -> dict:
        return {
            "id": row.id,
            "name": row.name,
            "max_user_exposure_kg": Decimal(row.max_user_exposure_kg),
            "max_order_kg": Decimal(row.max_order_kg),
            "max_daily_loss_usd": Decimal(row.max_daily_loss_usd),
            "max_leverage": Decimal(row.max_leverage),
            "max_concentration_ratio": Decimal(row.max_concentration_ratio),
            "max_drawdown_usd": Decimal(row.max_drawdown_usd),
            "block_trading_on_violation": bool(row.block_trading_on_violation),
            "enabled": bool(row.enabled),
            "created_at": row.created_at,
        }

    async def get_active_rule(self) -> dict | None:
        session = self._session()
        row = await session.scalar(select(RiskRule).where(RiskRule.enabled.is_(True)).order_by(RiskRule.created_at.desc()))
        if row is None:
            return None
        return self._serialize_rule(row)

    async def upsert_rule(
        self,
        name: str,
        max_user_exposure_kg: Decimal,
        max_order_kg: Decimal,
        enabled: bool,
        *,
        max_daily_loss_usd: Decimal = Decimal("0"),
        max_leverage: Decimal = Decimal("0"),
        max_concentration_ratio: Decimal = Decimal("0"),
        max_drawdown_usd: Decimal = Decimal("0"),
        block_trading_on_violation: bool = True,
    ) -> dict:
        session = self._session()
        row = await session.scalar(select(RiskRule).where(RiskRule.name == name))
        if row is None:
            row = RiskRule(
                name=name,
                max_user_exposure_kg=max_user_exposure_kg,
                max_order_kg=max_order_kg,
                max_daily_loss_usd=max_daily_loss_usd,
                max_leverage=max_leverage,
                max_concentration_ratio=max_concentration_ratio,
                max_drawdown_usd=max_drawdown_usd,
                block_trading_on_violation=block_trading_on_violation,
                enabled=enabled,
                created_at=utcnow(),
            )
            session.add(row)
        else:
            row.max_user_exposure_kg = max_user_exposure_kg
            row.max_order_kg = max_order_kg
            row.max_daily_loss_usd = max_daily_loss_usd
            row.max_leverage = max_leverage
            row.max_concentration_ratio = max_concentration_ratio
            row.max_drawdown_usd = max_drawdown_usd
            row.block_trading_on_violation = block_trading_on_violation
            row.enabled = enabled
        await session.flush()
        return self._serialize_rule(row)

    async def create_violation(
        self,
        *,
        user_id: int | None,
        order_id: int | None,
        severity: str,
        violation_type: str,
        message: str,
        payload: dict,
    ) -> dict:
        session = self._session()
        row = RiskViolation(
            user_id=user_id,
            order_id=order_id,
            severity=RiskViolationSeverity(severity).value,
            status=RiskViolationStatus.open.value,
            violation_type=violation_type,
            message=message,
            payload_json=json_dumps(payload),
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return {
            "id": row.id,
            "user_id": row.user_id,
            "order_id": row.order_id,
            "severity": _as_risk_violation_severity(row.severity),
            "status": _as_risk_violation_status(row.status),
            "violation_type": row.violation_type,
            "message": row.message,
            "payload": json.loads(row.payload_json),
            "created_at": row.created_at,
        }

    async def list_open_violations(self, *, user_id: int | None = None, limit: int = 100) -> list[dict]:
        session = self._session()
        stmt = (
            select(RiskViolation)
            .where(RiskViolation.status == RiskViolationStatus.open.value)
            .order_by(RiskViolation.created_at.desc())
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(RiskViolation.user_id == user_id)
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "order_id": row.order_id,
                "severity": _as_risk_violation_severity(row.severity),
                "status": _as_risk_violation_status(row.status),
                "violation_type": row.violation_type,
                "message": row.message,
                "payload": json.loads(row.payload_json),
                "created_at": row.created_at,
            }
            for row in rows
        ]


    async def list_violations(self, user_id: int, *, limit: int = 50) -> list[dict]:
        session = self._session()
        rows = (
            await session.scalars(
                select(RiskViolation)
                .where(RiskViolation.user_id == user_id)
                .order_by(RiskViolation.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "order_id": row.order_id,
                "severity": _as_risk_violation_severity(row.severity),
                "status": _as_risk_violation_status(row.status),
                "violation_type": row.violation_type,
                "message": row.message,
                "payload": json.loads(row.payload_json),
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in rows
        ]

    async def create_snapshot(self, user_id: int, payload: dict) -> dict:
        session = self._session()
        row = RiskSnapshot(
            user_id=user_id,
            exposure_kg=Decimal(payload.get("exposure_kg", "0")),
            daily_pnl_usd=Decimal(payload.get("daily_pnl_usd", "0")),
            daily_loss_usd=Decimal(payload.get("daily_loss_usd", "0")),
            drawdown_usd=Decimal(payload.get("drawdown_usd", "0")),
            concentration_ratio=Decimal(payload.get("concentration_ratio", "0")),
            risk_score=Decimal(payload.get("score", "0")),
            risk_score_level=payload.get("level", RiskScoreLevel.low.value),
            violation_count=int(payload.get("violation_count", 0)),
            payload_json=json_dumps(payload),
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return {"id": row.id, "user_id": row.user_id, "risk_score_level": row.risk_score_level}


class SqlAuditRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def add(self, actor_user_id: int | None, event_type: str, entity_type: str | None, entity_id: str | None, payload: dict) -> None:
        session = self._session()
        session.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                event_type=event_type,
                entity_type=entity_type,
                entity_id=entity_id,
                payload=json_dumps(payload),
                created_at=utcnow(),
            )
        )
        await session.flush()

    async def list_events(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        event_type: str | None = None,
        entity_type: str | None = None,
    ) -> list[dict]:
        session = self._session()
        stmt = select(AuditEvent).order_by(AuditEvent.created_at.desc()).offset(offset).limit(limit)
        if event_type is not None:
            stmt = stmt.where(AuditEvent.event_type == event_type)
        if entity_type is not None:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": row.id,
                "actor_user_id": row.actor_user_id,
                "event_type": row.event_type,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "payload": json.loads(row.payload),
                "created_at": row.created_at,
            }
            for row in rows
        ]


class SqlNotificationRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def enqueue(self, user_id: int, kind: str, payload: dict, channel: str = "telegram") -> dict:
        session = self._session()
        row = Notification(
            user_id=user_id,
            channel=channel,
            kind=kind,
            payload=json_dumps(payload),
            status=NotificationStatus.pending.value,
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return {"id": row.id}

    async def list_pending(self, limit: int = 100) -> list[dict]:
        session = self._session()
        res = await session.scalars(
            select(Notification).where(Notification.status == NotificationStatus.pending.value).order_by(Notification.created_at.asc()).limit(limit)
        )
        items = []
        for row in res.all():
            items.append(
                {
                    "id": row.id,
                    "user_id": row.user_id,
                    "channel": row.channel,
                    "kind": row.kind,
                    "payload": json.loads(row.payload),
                    "status": _as_notification_status(row.status),
                }
            )
        return items

    async def mark(self, notification_id: int, status: NotificationStatus, error: str | None = None) -> None:
        session = self._session()
        row = await session.get(Notification, notification_id)
        if row is None:
            raise RuntimeError("Notification not found")
        row.status = status.value
        if status == NotificationStatus.sent:
            row.sent_at = utcnow()
        if error is not None:
            payload = json.loads(row.payload)
            payload["error"] = error
            row.payload = json_dumps(payload)
        await session.flush()


class SqlAccountingRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    async def ensure_default_chart(self) -> None:
        session = self._session()
        defaults = [
            ("1000", "Cash USD", JournalAccountType.asset),
            ("2000", "Customer Balances", JournalAccountType.liability),
            ("3000", "Equity", JournalAccountType.equity),
            ("4000", "Trading Income", JournalAccountType.income),
            ("5000", "Trading Expense", JournalAccountType.expense),
        ]
        existing = (await session.scalars(select(JournalAccount))).all()
        existing_codes = {a.code for a in existing}
        for code, name, t in defaults:
            if code not in existing_codes:
                session.add(JournalAccount(code=code, name=name, account_type=t.value, parent_id=None, is_active=True, created_at=utcnow()))
        await session.flush()

    async def create_account(self, code: str, name: str, account_type: JournalAccountType, parent_code: str | None) -> dict:
        session = self._session()
        parent_id = None
        if parent_code is not None:
            parent = await session.scalar(select(JournalAccount).where(JournalAccount.code == parent_code))
            if parent is None:
                raise RuntimeError("Parent account not found")
            parent_id = parent.id
        row = JournalAccount(code=code, name=name, account_type=account_type.value, parent_id=parent_id, is_active=True, created_at=utcnow())
        session.add(row)
        await session.flush()
        return {"id": row.id, "code": row.code}

    async def get_account_by_code(self, code: str) -> dict | None:
        session = self._session()
        row = await session.scalar(select(JournalAccount).where(JournalAccount.code == code))
        if row is None:
            return None
        return {"id": row.id, "code": row.code, "name": row.name, "account_type": _as_account_type(row.account_type)}

    async def create_bank_account(self, name: str, account_number_enc: str) -> dict:
        session = self._session()
        row = BankAccount(name=name, account_number_enc=account_number_enc, is_active=True, created_at=utcnow())
        session.add(row)
        await session.flush()
        return {"id": row.id, "name": row.name, "is_active": row.is_active}

    async def list_bank_accounts(self, only_active: bool = True) -> list[dict]:
        session = self._session()
        stmt = select(BankAccount).order_by(BankAccount.created_at.asc())
        if only_active:
            stmt = stmt.where(BankAccount.is_active.is_(True))
        rows = (await session.scalars(stmt)).all()
        return [{"id": row.id, "name": row.name, "is_active": row.is_active, "created_at": row.created_at} for row in rows]

    async def create_payment_card(self, bank_account_id: int, label: str, card_number_enc: str) -> dict:
        session = self._session()
        bank = await session.get(BankAccount, bank_account_id)
        if bank is None:
            raise RuntimeError("Bank account not found")
        row = PaymentCard(
            bank_account_id=bank_account_id,
            label=label,
            card_number_enc=card_number_enc,
            is_active=True,
            created_at=utcnow(),
        )
        session.add(row)
        await session.flush()
        return {"id": row.id, "bank_account_id": row.bank_account_id, "label": row.label, "is_active": row.is_active}

    async def list_payment_cards(self, bank_account_id: int | None = None, only_active: bool = True) -> list[dict]:
        session = self._session()
        stmt = select(PaymentCard).order_by(PaymentCard.created_at.asc())
        if bank_account_id is not None:
            stmt = stmt.where(PaymentCard.bank_account_id == bank_account_id)
        if only_active:
            stmt = stmt.where(PaymentCard.is_active.is_(True))
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": row.id,
                "bank_account_id": row.bank_account_id,
                "label": row.label,
                "is_active": row.is_active,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    async def post_journal_entry(self, reference: str | None, description: str, posted_at: datetime, created_by_user_id: int | None, lines: list[dict]) -> dict:
        session = self._session()
        debit = sum(Decimal(str(l.get("debit_usd", 0))) for l in lines)
        credit = sum(Decimal(str(l.get("credit_usd", 0))) for l in lines)
        if debit != credit:
            raise RuntimeError("Unbalanced journal entry")
        entry = JournalEntry(reference=reference, description=description, posted_at=ensure_utc(posted_at), created_by_user_id=created_by_user_id, created_at=utcnow())
        session.add(entry)
        await session.flush()
        for l in lines:
            session.add(
                JournalLine(
                    entry_id=entry.id,
                    account_id=int(l["account_id"]),
                    user_id=int(l["user_id"]) if l.get("user_id") is not None else None,
                    debit_usd=Decimal(str(l.get("debit_usd", 0))),
                    credit_usd=Decimal(str(l.get("credit_usd", 0))),
                    created_at=utcnow(),
                )
            )
        await session.flush()
        return {"id": entry.id}

    async def trial_balance(self, from_dt: datetime | None, to_dt: datetime | None) -> list[dict]:
        session = self._session()
        q = (
            select(
                JournalAccount.code,
                JournalAccount.name,
                JournalAccount.account_type,
                func.coalesce(func.sum(JournalLine.debit_usd), 0).label("debit"),
                func.coalesce(func.sum(JournalLine.credit_usd), 0).label("credit"),
            )
            .join(JournalLine, JournalLine.account_id == JournalAccount.id)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .group_by(JournalAccount.id)
            .order_by(JournalAccount.code.asc())
        )
        if from_dt is not None:
            q = q.where(JournalEntry.posted_at >= ensure_utc(from_dt))
        if to_dt is not None:
            q = q.where(JournalEntry.posted_at <= ensure_utc(to_dt))
        res = await session.execute(q)
        rows = []
        for code, name, t, debit, credit in res.all():
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "account_type": _as_account_type(t),
                    "debit_usd": Decimal(debit),
                    "credit_usd": Decimal(credit),
                    "balance_usd": Decimal(debit) - Decimal(credit),
                }
            )
        return rows

    async def profit_and_loss(self, from_dt: datetime | None, to_dt: datetime | None) -> dict:
        tb = await self.trial_balance(from_dt, to_dt)
        income = sum((r["credit_usd"] - r["debit_usd"]) for r in tb if r["account_type"] == JournalAccountType.income)
        expense = sum((r["debit_usd"] - r["credit_usd"]) for r in tb if r["account_type"] == JournalAccountType.expense)
        return {"income_usd": income, "expense_usd": expense, "net_profit_usd": income - expense}

    async def balance_sheet(self, at_dt: datetime | None) -> dict:
        tb = await self.trial_balance(None, at_dt)
        assets = sum(r["balance_usd"] for r in tb if r["account_type"] == JournalAccountType.asset)
        liabilities = sum(-r["balance_usd"] for r in tb if r["account_type"] == JournalAccountType.liability)
        equity = sum(-r["balance_usd"] for r in tb if r["account_type"] == JournalAccountType.equity)
        return {"assets_usd": assets, "liabilities_usd": liabilities, "equity_usd": equity}

    async def cash_flow(self, from_dt: datetime | None, to_dt: datetime | None) -> dict:
        session = self._session()
        cash = await session.scalar(select(JournalAccount).where(JournalAccount.code == "1000"))
        if cash is None:
            return {"net_cash_change_usd": Decimal("0")}
        def _balance(at: datetime | None) -> Decimal:
            q = (
                select(
                    func.coalesce(func.sum(JournalLine.debit_usd), 0).label("debit"),
                    func.coalesce(func.sum(JournalLine.credit_usd), 0).label("credit"),
                )
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(JournalLine.account_id == cash.id)
            )
            if at is not None:
                q = q.where(JournalEntry.posted_at <= ensure_utc(at))
            return q
        start = None
        end = None
        if from_dt is not None:
            d, c = (await session.execute(_balance(from_dt))).one()
            start = Decimal(d) - Decimal(c)
        if to_dt is not None:
            d, c = (await session.execute(_balance(to_dt))).one()
            end = Decimal(d) - Decimal(c)
        if start is None:
            start = Decimal("0")
        if end is None:
            d, c = (await session.execute(_balance(None))).one()
            end = Decimal(d) - Decimal(c)
        return {"net_cash_change_usd": end - start}

    async def financial_dashboard(self, from_dt: datetime | None, to_dt: datetime | None) -> dict:
        tb = await self.trial_balance(from_dt, to_dt)
        pnl = await self.profit_and_loss(from_dt, to_dt)
        bs = await self.balance_sheet(to_dt)
        cf = await self.cash_flow(from_dt, to_dt)
        return {
            "trial_balance_rows": len(tb),
            "income_usd": pnl["income_usd"],
            "expense_usd": pnl["expense_usd"],
            "net_profit_usd": pnl["net_profit_usd"],
            "assets_usd": bs["assets_usd"],
            "liabilities_usd": bs["liabilities_usd"],
            "equity_usd": bs["equity_usd"],
            "net_cash_change_usd": cf["net_cash_change_usd"],
        }

    async def close_period(self, period_type: str, label: str, start_date: datetime, end_date: datetime, closed_by_user_id: int) -> dict:
        session = self._session()
        pnl = await self.profit_and_loss(start_date, end_date)
        net_income = pnl["net_profit_usd"]
        equity = await session.scalar(select(JournalAccount).where(JournalAccount.code == "3000"))
        income = await session.scalar(select(JournalAccount).where(JournalAccount.code == "4000"))
        expense = await session.scalar(select(JournalAccount).where(JournalAccount.code == "5000"))
        if equity is None or income is None or expense is None:
            raise RuntimeError("Chart of accounts not ready for period close")
        closing_entry = JournalEntry(
            reference=f"period_close:{period_type}:{label}",
            description=f"Period close {label}",
            posted_at=end_date,
            created_by_user_id=closed_by_user_id,
            created_at=utcnow(),
        )
        session.add(closing_entry)
        await session.flush()
        income_balance = Decimal("0")
        expense_balance = Decimal("0")
        tb = await self.trial_balance(start_date, end_date)
        for r in tb:
            if r["account_type"] == JournalAccountType.income:
                income_balance += r["credit_usd"] - r["debit_usd"]
            elif r["account_type"] == JournalAccountType.expense:
                expense_balance += r["debit_usd"] - r["credit_usd"]
        if income_balance > 0:
            session.add(JournalLine(entry_id=closing_entry.id, account_id=income.id, user_id=None, debit_usd=income_balance, credit_usd=Decimal("0"), created_at=utcnow()))
        if expense_balance > 0:
            session.add(JournalLine(entry_id=closing_entry.id, account_id=expense.id, user_id=None, debit_usd=Decimal("0"), credit_usd=expense_balance, created_at=utcnow()))
        if net_income > 0:
            session.add(JournalLine(entry_id=closing_entry.id, account_id=income.id, user_id=None, debit_usd=Decimal("0"), credit_usd=net_income, created_at=utcnow()))
            session.add(JournalLine(entry_id=closing_entry.id, account_id=equity.id, user_id=None, debit_usd=net_income, credit_usd=Decimal("0"), created_at=utcnow()))
        elif net_income < 0:
            amt = abs(net_income)
            session.add(JournalLine(entry_id=closing_entry.id, account_id=equity.id, user_id=None, debit_usd=Decimal("0"), credit_usd=amt, created_at=utcnow()))
            session.add(JournalLine(entry_id=closing_entry.id, account_id=expense.id, user_id=None, debit_usd=amt, credit_usd=Decimal("0"), created_at=utcnow()))
        period = FinancialPeriod(
            period_type=period_type,
            label=label,
            start_date=ensure_utc(start_date),
            end_date=ensure_utc(end_date),
            is_closed=True,
            closed_by_user_id=closed_by_user_id,
            closed_at=utcnow(),
            retained_earnings_usd=net_income,
            net_income_usd=net_income,
            closing_journal_entry_id=closing_entry.id,
            payload_json=json.dumps({"income_accounts": ["4000"], "expense_accounts": ["5000"]}),
            created_at=utcnow(),
        )
        session.add(period)
        await session.flush()
        return {
            "id": period.id,
            "period_type": period_type,
            "label": label,
            "start_date": period.start_date,
            "end_date": period.end_date,
            "is_closed": True,
            "net_income_usd": net_income,
            "retained_earnings_usd": net_income,
            "closing_journal_entry_id": closing_entry.id,
        }

    async def list_periods(self, period_type: str | None = None, limit: int = 20) -> list[dict]:
        session = self._session()
        stmt = select(FinancialPeriod).order_by(FinancialPeriod.end_date.desc()).limit(limit)
        if period_type is not None:
            stmt = stmt.where(FinancialPeriod.period_type == period_type)
        rows = (await session.scalars(stmt)).all()
        return [
            {
                "id": r.id,
                "period_type": r.period_type,
                "label": r.label,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "is_closed": bool(r.is_closed),
                "closed_at": r.closed_at,
                "closed_by_user_id": r.closed_by_user_id,
                "net_income_usd": Decimal(r.net_income_usd),
                "retained_earnings_usd": Decimal(r.retained_earnings_usd),
            }
            for r in rows
        ]

    async def reopen_period(self, period_id: int, reopened_by_user_id: int) -> dict:
        session = self._session()
        row = await session.get(FinancialPeriod, period_id)
        if row is None:
            raise RuntimeError("Financial period not found")
        if not row.is_closed:
            raise RuntimeError("Period is already open")
        if row.closing_journal_entry_id is not None:
            closing_entry = await session.get(JournalEntry, row.closing_journal_entry_id)
            if closing_entry is not None:
                lines = await session.scalars(select(JournalLine).where(JournalLine.entry_id == closing_entry.id))
                reversal_entry = JournalEntry(
                    reference=f"period_reopen:{row.period_type}:{row.label}",
                    description=f"Reversal of period close {row.label}",
                    posted_at=utcnow(),
                    created_by_user_id=reopened_by_user_id,
                    created_at=utcnow(),
                )
                session.add(reversal_entry)
                await session.flush()
                for line in lines.all():
                    session.add(JournalLine(
                        entry_id=reversal_entry.id,
                        account_id=line.account_id,
                        user_id=line.user_id,
                        debit_usd=line.credit_usd,
                        credit_usd=line.debit_usd,
                        created_at=utcnow(),
                    ))
                row.reversal_journal_entry_id = reversal_entry.id
        row.is_closed = False
        row.closed_at = None
        await session.flush()
        return {
            "id": row.id,
            "period_type": row.period_type,
            "label": row.label,
            "is_closed": False,
            "reversal_journal_entry_id": row.reversal_journal_entry_id,
        }


class SqlBackupRepo:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    def _session(self):
        if self._uow.session is None:
            raise RuntimeError("No active transaction")
        return self._uow.session

    def _serialize_value(self, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, datetime):
            return ensure_utc(value).isoformat()
        if isinstance(value, Enum):
            return value.value
        return value

    def _deserialize_value(self, col, value: object) -> object:
        if value is None:
            return None
        t = col.type
        if isinstance(t, Numeric):
            return Decimal(str(value))
        if isinstance(t, (Integer, BigInteger)):
            return int(value)
        if isinstance(t, Boolean):
            return bool(value)
        if isinstance(t, DateTime):
            dt = datetime.fromisoformat(str(value))
            return ensure_utc(dt)
        return value

    async def create_snapshot(self) -> dict:
        session = self._session()
        tables: dict[str, list[dict]] = {}
        for table in Base.metadata.sorted_tables:
            res = await session.execute(select(table))
            rows: list[dict] = []
            for row in res.mappings().all():
                rows.append({k: self._serialize_value(v) for k, v in row.items()})
            tables[table.name] = rows
        return {"version": 1, "created_at": utcnow().isoformat(), "tables": tables}

    async def restore_snapshot(self, snapshot: dict, *, wipe_existing: bool = True) -> None:
        session = self._session()
        tables: dict[str, list[dict]] = snapshot.get("tables", {})
        if not isinstance(tables, dict):
            raise RuntimeError("Invalid snapshot")

        if wipe_existing:
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(table.delete())

        for table in Base.metadata.sorted_tables:
            name = table.name
            rows = tables.get(name, [])
            if not rows:
                continue
            normalized = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                normalized.append({k: self._deserialize_value(table.c[k], v) for k, v in r.items() if k in table.c})
            if normalized:
                await session.execute(table.insert(), normalized)
