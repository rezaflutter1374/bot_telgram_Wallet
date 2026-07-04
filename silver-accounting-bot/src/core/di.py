from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from redis.asyncio import Redis

from application.use_cases.services import AppServices
from core.security import Encryptor
from core.settings import Settings
from domain.services.ledger import LedgerService
from domain.services.margin import MarginCalculator
from domain.services.margin_engine import MarginEngine
from domain.services.matching_engine import MatchingEngine
from domain.services.position_engine import PositionEngine
from domain.services.risk_calc import RiskCalculator
from domain.services.risk_engine import RiskEngine
from domain.services.liquidation_engine import LiquidationEngine
from infrastructure.db.session import Database, SqlAlchemyUnitOfWork
from infrastructure.event_bus.bus import InMemoryEventBus
from infrastructure.event_bus.store import EventStore
from infrastructure.pricing.service import PriceRefreshService
from infrastructure.redis.cache import PriceCache
from infrastructure.redis.client import create_redis
from infrastructure.redis.rate_limiter import RateLimiter
from infrastructure.repositories.cached_price_repo import CachedPriceRepo
from infrastructure.repositories.runtime_state_repo import RedisRuntimeStateRepo
from infrastructure.repositories.sql_repos import (
    SqlAccountingRepo,
    SqlAuditRepo,
    SqlBackupRepo,
    SqlLedgerRepo,
    SqlLiquidationRepo,
    SqlOrderRepo,
    SqlPaymentReconciliationRepo,
    SqlPaymentRepo,
    SqlPositionRepo,
    SqlPriceRepo,
    SqlNotificationRepo,
    SqlRiskRepo,
    SqlRoleRepo,
    SqlTicketRepo,
    SqlUserRepo,
    SqlWalletRepo,
)
from infrastructure.resilience.circuit_breaker import CircuitBreakerConfig, CircuitBreakerRegistry
from infrastructure.resilience.dead_letter import DeadLetterQueue
from infrastructure.resilience.retry import RetryConfig
from infrastructure.settlement.service import SettlementEngineService


@dataclass(frozen=True)
class Container:
    settings: Settings
    db: Database
    uow: SqlAlchemyUnitOfWork
    encryptor: Encryptor
    redis: Redis
    rate_limiter: RateLimiter
    price_cache: PriceCache
    price_refresh: PriceRefreshService
    settlement_engine: SettlementEngineService
    event_bus: InMemoryEventBus
    event_store: EventStore
    circuit_breaker_registry: CircuitBreakerRegistry
    dead_letter_queue: DeadLetterQueue
    risk_calculator: RiskCalculator
    services: AppServices


def build_container(settings: Settings) -> Container:
    db = Database(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout,
        pool_recycle=settings.db_pool_recycle,
    )
    uow = SqlAlchemyUnitOfWork(db)
    encryptor = Encryptor(settings.encryption_key)
    redis = create_redis(settings.redis_url, max_connections=settings.redis_max_connections)
    rate_limiter = RateLimiter(redis)
    price_cache = PriceCache(redis, ttl_seconds=settings.price_cache_ttl_seconds)
    margin_calc = MarginCalculator(
        deposit_requirement_per_kg_usd=Decimal("100"),
        maintenance_ratio_threshold=settings.margin_call_threshold_ratio,
        warning_ratio_threshold=settings.margin_warning_ratio,
        liquidation_ratio_threshold=settings.margin_liquidation_critical_ratio,
    )
    circuit_breaker_registry = CircuitBreakerRegistry()
    dead_letter_queue = DeadLetterQueue(db.session)
    risk_calculator = RiskCalculator()

    users = SqlUserRepo(uow)
    wallets = SqlWalletRepo(uow)
    roles = SqlRoleRepo(uow)
    prices = CachedPriceRepo(SqlPriceRepo(uow), price_cache)
    payments = SqlPaymentRepo(uow)
    accounting = SqlAccountingRepo(uow)
    notifications = SqlNotificationRepo(uow)
    audit = SqlAuditRepo(uow)
    risk = SqlRiskRepo(uow)
    orders = SqlOrderRepo(uow)
    positions = SqlPositionRepo(uow)
    tickets = SqlTicketRepo(uow)
    backup = SqlBackupRepo(uow)
    runtime_state = RedisRuntimeStateRepo(redis)
    price_refresh = PriceRefreshService(settings=settings, db=db, uow=uow, prices=prices)
    settlement_engine = SettlementEngineService(db=db, redis=redis)
    payment_reconciliation = SqlPaymentReconciliationRepo(uow)
    ledger_repo = SqlLedgerRepo(uow)
    liquidation_repo = SqlLiquidationRepo(uow)
    event_bus = InMemoryEventBus()
    event_store = EventStore(uow)

    matching_engine = MatchingEngine()
    ledger_service = LedgerService()
    position_engine = PositionEngine()
    margin_engine = MarginEngine(margin_calc)
    risk_engine = RiskEngine()
    liquidation_engine = LiquidationEngine()

    services = AppServices(
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
        margin_calculator=margin_calc,
        runtime_state=runtime_state,
        settlement_engine=settlement_engine,
        circuit_breaker_repo=circuit_breaker_registry,
        dead_letter_repo=dead_letter_queue,
        risk_calc=risk_calculator,
        event_bus=event_bus,
        event_store=event_store,
        payment_reconciliation=payment_reconciliation,
        ledger_repo=ledger_repo,
        liquidation_repo=liquidation_repo,
        matching_engine=matching_engine,
        ledger_service=ledger_service,
        position_engine=position_engine,
        margin_engine=margin_engine,
        risk_engine=risk_engine,
        liquidation_engine=liquidation_engine,
    )

    return Container(
        settings=settings,
        db=db,
        uow=uow,
        encryptor=encryptor,
        redis=redis,
        rate_limiter=rate_limiter,
        price_cache=price_cache,
        price_refresh=price_refresh,
        settlement_engine=settlement_engine,
        event_bus=event_bus,
        event_store=event_store,
        circuit_breaker_registry=circuit_breaker_registry,
        dead_letter_queue=dead_letter_queue,
        risk_calculator=risk_calculator,
        services=services,
    )
