from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from core.settings import Settings
from infrastructure.db.base import Base
from infrastructure.db.models import Notification, Price, PriceProviderStatus, Role, User, UserRole
from infrastructure.db.session import Database, SqlAlchemyUnitOfWork
from infrastructure.pricing.service import (
    GoldApiSilverProvider,
    MetalsApiSilverProvider,
    PriceProviderError,
    PriceRefreshService,
    ProviderQuote,
    _ounce_to_kg_price,
    _parse_provider_timestamp,
    _to_decimal,
    build_external_price_providers,
)
from infrastructure.redis.cache import PriceCache
from infrastructure.repositories.cached_price_repo import CachedPriceRepo
from infrastructure.repositories.sql_repos import SqlPriceRepo


class FakeSuccessProvider:
    name = "goldapi"

    async def fetch_quote(self, session) -> ProviderQuote:
        return ProviderQuote(
            provider_name=self.name,
            price_usd_per_kg=Decimal("950"),
            quoted_at=datetime.now(timezone.utc),
            external_id="ok-1",
            raw_payload={"price": "950"},
        )


class FakeFailingProvider:
    name = "metals_api"

    async def fetch_quote(self, session) -> ProviderQuote:
        raise RuntimeError("provider offline")


class FlakyProvider:
    name = "goldapi"

    def __init__(self) -> None:
        self.calls = 0

    async def fetch_quote(self, session) -> ProviderQuote:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary error")
        return ProviderQuote(
            provider_name=self.name,
            price_usd_per_kg=Decimal("975"),
            quoted_at=datetime.now(timezone.utc),
            external_id="retry",
            raw_payload={"price": "975"},
        )


class FakeResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def json(self) -> dict:
        return self._payload


class FakeHttpSession:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response
        self.last_headers: dict | None = None
        self.last_params: dict | None = None

    def get(self, url: str, *, headers: dict | None = None, params: dict | None = None):
        self.last_headers = headers
        self.last_params = params
        return self._response


def build_settings(**overrides) -> Settings:
    data = {
        "bot_token": "123:abc",
        "database_url": "sqlite+aiosqlite:///tmp/test.db",
        "redis_url": "redis://localhost:6379/0",
        "encryption_key": "abcdefghijklmnopqrstuvwxyzABCDEFG1234567890=",
        "price_provider_primary": "goldapi",
    }
    data.update(overrides)
    return Settings(**data)


@pytest.mark.asyncio
async def test_price_refresh_persists_price_and_detects_duplicates(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'price_refresh.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = build_settings(price_provider_min_interval_seconds=0)
    uow = SqlAlchemyUnitOfWork(db)
    repo = SqlPriceRepo(uow)
    service = PriceRefreshService(settings=settings, db=db, uow=uow, prices=repo)
    service._providers = [FakeSuccessProvider()]  # type: ignore[assignment]

    first = await service.refresh_once()
    second = await service.refresh_once()

    assert first["status"] == "ok"
    assert second["status"] == "duplicate"

    async with db.session() as session:
        prices = (await session.scalars(select(Price))).all()
        assert len(prices) == 1
        provider_status = await session.scalar(select(PriceProviderStatus).where(PriceProviderStatus.provider_name == "goldapi"))
        assert provider_status is not None
        assert provider_status.is_healthy is True

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_price_refresh_falls_back_to_last_good_price(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'price_fallback.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = build_settings(price_provider_primary="metals_api")
    uow = SqlAlchemyUnitOfWork(db)
    repo = SqlPriceRepo(uow)
    async with uow.transaction():
        await repo.upsert(
            buy_price=Decimal("800"),
            sell_price=Decimal("800"),
            spread=Decimal("0"),
            commission=Decimal("0"),
            premium=Decimal("0"),
            discount=Decimal("0"),
            source="manual_admin",
        )

    service = PriceRefreshService(settings=settings, db=db, uow=uow, prices=repo)
    service._providers = [FakeFailingProvider()]  # type: ignore[assignment]

    result = await service.refresh_once()

    assert result["status"] == "fallback"
    assert result["source"] == "manual_admin"

    async with db.session() as session:
        provider_status = await session.scalar(
            select(PriceProviderStatus).where(PriceProviderStatus.provider_name == "metals_api")
        )
        assert provider_status is not None
        assert provider_status.is_healthy is False
        assert provider_status.consecutive_failures == 1

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_price_refresh_without_external_providers_notifies_admins(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'price_notify.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with db.session() as session:
        async with session.begin():
            session.add(User(id=1, telegram_id=111, full_name=None, phone_number=None, verification_docs_file_ids_enc="[]", kyc_status="pending"))
            session.add(Role(id=1, name="admin"))
            session.add(UserRole(user_id=1, role_id=1))

    settings = build_settings(price_provider_primary="manual", price_provider_secondary=None)
    uow = SqlAlchemyUnitOfWork(db)
    repo = SqlPriceRepo(uow)
    service = PriceRefreshService(settings=settings, db=db, uow=uow, prices=repo)

    result = await service.refresh_once()

    assert result["status"] == "failed"
    assert result["reason"] == "no_external_providers"

    async with db.session() as session:
        notifications = (await session.scalars(select(Notification))).all()
        assert len(notifications) == 1
        assert notifications[0].kind == "price.refresh_failed"

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_price_refresh_retry_validation_and_rate_limit(tmp_path) -> None:
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'price_retry.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    settings = build_settings(price_provider_max_retries=1, price_provider_min_interval_seconds=10)
    uow = SqlAlchemyUnitOfWork(db)
    repo = SqlPriceRepo(uow)
    service = PriceRefreshService(settings=settings, db=db, uow=uow, prices=repo)

    quote = await service._fetch_with_retry(FlakyProvider(), session=None)  # type: ignore[arg-type]
    assert quote.external_id == "retry"

    with pytest.raises(PriceProviderError):
        service._validate_quote(
            ProviderQuote("goldapi", Decimal("10"), datetime.now(timezone.utc), None, {})
        )
    with pytest.raises(PriceProviderError):
        service._validate_quote(
            ProviderQuote("goldapi", Decimal("1000001"), datetime.now(timezone.utc), None, {})
        )
    with pytest.raises(PriceProviderError):
        service._validate_quote(
            ProviderQuote("goldapi", Decimal("900"), datetime(2020, 1, 1, tzinfo=timezone.utc), None, {})
        )

    assert service._is_rate_limited("goldapi") is False
    assert service._is_rate_limited("goldapi") is True

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_http_providers_and_builder_helpers() -> None:
    settings = build_settings(goldapi_key="secret", metals_api_key="secret", price_provider_secondary="metals_api")
    providers = build_external_price_providers(settings)
    assert [provider.name for provider in providers] == ["goldapi", "metals_api"]

    gold_provider = GoldApiSilverProvider(settings)
    gold_session = FakeHttpSession(FakeResponse(200, {"price": "30", "timestamp": 1710000000, "metal": "XAG"}))
    gold_quote = await gold_provider.fetch_quote(gold_session)  # type: ignore[arg-type]
    assert gold_quote.provider_name == "goldapi"
    assert gold_quote.price_usd_per_kg == _ounce_to_kg_price(Decimal("30"))
    assert gold_session.last_headers == {"x-access-token": "secret"}

    metals_provider = MetalsApiSilverProvider(settings)
    metals_session = FakeHttpSession(FakeResponse(200, {"rates": {"XAG": "0.04"}, "date": "2026-01-02"}))
    metals_quote = await metals_provider.fetch_quote(metals_session)  # type: ignore[arg-type]
    assert metals_quote.provider_name == "metals_api"
    assert metals_session.last_params == {"access_key": "secret", "base": "USD", "symbols": "XAG"}

    assert _to_decimal("1.5") == Decimal("1.5")
    assert _parse_provider_timestamp(1710000000).tzinfo is not None
    assert _parse_provider_timestamp("1710000000").tzinfo is not None
    assert _parse_provider_timestamp("2026-01-02T00:00:00Z").tzinfo is not None
    assert _parse_provider_timestamp(datetime.now(timezone.utc)).tzinfo is not None
    assert _parse_provider_timestamp(object()).tzinfo is not None

    missing_key_settings = build_settings(price_provider_primary="goldapi", goldapi_key=None)
    with pytest.raises(PriceProviderError):
        await GoldApiSilverProvider(missing_key_settings).fetch_quote(gold_session)  # type: ignore[arg-type]

    bad_gold_session = FakeHttpSession(FakeResponse(500, {"error": "x"}))
    with pytest.raises(PriceProviderError):
        await gold_provider.fetch_quote(bad_gold_session)  # type: ignore[arg-type]

    missing_price_session = FakeHttpSession(FakeResponse(200, {"timestamp": 1710000000}))
    with pytest.raises(PriceProviderError):
        await gold_provider.fetch_quote(missing_price_session)  # type: ignore[arg-type]

    bad_metals_session = FakeHttpSession(FakeResponse(200, {"rates": {"XAG": "0"}}))
    with pytest.raises(PriceProviderError):
        await metals_provider.fetch_quote(bad_metals_session)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cached_price_repo_branches(tmp_path) -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.value: dict | None = None

        async def get(self, key: str):
            return None

        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            return None

        async def expire(self, key: str, ttl: int) -> None:
            return None

    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'cached_price.db'}")
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    uow = SqlAlchemyUnitOfWork(db)
    inner = SqlPriceRepo(uow)
    cache = PriceCache(FakeRedis(), ttl_seconds=5)  # type: ignore[arg-type]
    repo = CachedPriceRepo(inner=inner, cache=cache)

    async with uow.transaction():
        await repo.upsert(
            buy_price=Decimal("700"),
            sell_price=Decimal("700"),
            spread=Decimal("0"),
            commission=Decimal("0"),
            premium=Decimal("0"),
            discount=Decimal("0"),
            source="manual_admin",
        )
        latest = await repo.get_latest()
        assert latest is not None
        assert await repo.is_duplicate(
            source="manual_admin",
            buy_price=Decimal("700"),
            sell_price=Decimal("700"),
            provider_timestamp=None,
        ) is True
        status = await repo.set_provider_status(
            provider_name="goldapi",
            is_healthy=True,
            checked_at=datetime.now(timezone.utc),
            last_price_usd_per_kg=Decimal("700"),
        )
        assert status["provider_name"] == "goldapi"

    await db.engine.dispose()
