from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from time import monotonic
from typing import Protocol

from aiohttp import ClientSession, ClientTimeout
from prometheus_client import Counter, Gauge
from sqlalchemy import select

from core.settings import Settings
from infrastructure.db.models import Notification, NotificationStatus, Role, UserRole
from infrastructure.db.session import Database, SqlAlchemyUnitOfWork


logger = logging.getLogger("pricing")

TROY_OUNCES_PER_KG = Decimal("32.150746568627")

PRICE_REFRESH_TOTAL = Counter(
    "silver_price_refresh_total",
    "Total price refresh attempts by provider and status.",
    ["provider", "status"],
)
PRICE_PROVIDER_HEALTH = Gauge(
    "silver_price_provider_health",
    "Health of configured silver price providers.",
    ["provider"],
)
PRICE_LAST_GOOD_AGE_SECONDS = Gauge(
    "silver_price_last_good_age_seconds",
    "Age of the latest verified silver price in seconds.",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class PriceProviderError(RuntimeError):
    __slots__ = ()


@dataclass(frozen=True)
class ProviderQuote:
    provider_name: str
    price_usd_per_kg: Decimal
    quoted_at: datetime
    external_id: str | None
    raw_payload: dict


class ExternalPriceProvider(Protocol):
    name: str

    async def fetch_quote(self, session: ClientSession) -> ProviderQuote: ...


def _to_decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _ounce_to_kg_price(price_usd_per_ounce: Decimal) -> Decimal:
    return (price_usd_per_ounce * TROY_OUNCES_PER_KG).quantize(Decimal("0.000001"))


class GoldApiSilverProvider:
    name = "goldapi"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch_quote(self, session: ClientSession) -> ProviderQuote:
        if not self._settings.goldapi_key:
            raise PriceProviderError("GOLDAPI_KEY is not configured")
        async with session.get(
            self._settings.goldapi_url,
            headers={"x-access-token": self._settings.goldapi_key},
        ) as response:
            if response.status >= 400:
                raise PriceProviderError(f"goldapi http status {response.status}")
            payload = await response.json()
        if "price" not in payload:
            raise PriceProviderError("goldapi payload does not contain price")
        price_per_ounce = _to_decimal(payload["price"])
        quoted_at_raw = payload.get("timestamp") or payload.get("updatedAt") or utcnow().isoformat()
        quoted_at = _parse_provider_timestamp(quoted_at_raw)
        external_id = str(payload.get("metal") or "XAG/USD")
        return ProviderQuote(
            provider_name=self.name,
            price_usd_per_kg=_ounce_to_kg_price(price_per_ounce),
            quoted_at=quoted_at,
            external_id=external_id,
            raw_payload=payload,
        )


class MetalsApiSilverProvider:
    name = "metals_api"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def fetch_quote(self, session: ClientSession) -> ProviderQuote:
        if not self._settings.metals_api_key:
            raise PriceProviderError("METALS_API_KEY is not configured")
        params = {"access_key": self._settings.metals_api_key, "base": "USD", "symbols": "XAG"}
        async with session.get(self._settings.metals_api_url, params=params) as response:
            if response.status >= 400:
                raise PriceProviderError(f"metals_api http status {response.status}")
            payload = await response.json()
        rates = payload.get("rates")
        if not isinstance(rates, dict) or "XAG" not in rates:
            raise PriceProviderError("metals_api payload does not contain rates.XAG")
        xag_value = _to_decimal(rates["XAG"])
        if xag_value <= 0:
            raise PriceProviderError("metals_api returned non-positive XAG value")
        # Some APIs return XAG ounces per USD while others return USD per XAG.
        price_per_ounce = (Decimal("1") / xag_value) if xag_value < 1 else xag_value
        quoted_at_raw = payload.get("timestamp") or payload.get("date") or utcnow().isoformat()
        quoted_at = _parse_provider_timestamp(quoted_at_raw)
        external_id = str(payload.get("base") or "USD/XAG")
        return ProviderQuote(
            provider_name=self.name,
            price_usd_per_kg=_ounce_to_kg_price(price_per_ounce),
            quoted_at=quoted_at,
            external_id=external_id,
            raw_payload=payload,
        )


def _parse_provider_timestamp(value: object) -> datetime:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            return datetime.fromtimestamp(int(normalized), tz=timezone.utc)
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
        return ensure_utc(parsed)
    if isinstance(value, datetime):
        return ensure_utc(value)
    return utcnow()


def build_external_price_providers(settings: Settings) -> list[ExternalPriceProvider]:
    ordered_names = [settings.price_provider_primary, settings.price_provider_secondary]
    providers: list[ExternalPriceProvider] = []
    seen: set[str] = set()
    for provider_name in ordered_names:
        if provider_name is None or provider_name == "manual" or provider_name in seen:
            continue
        if provider_name == "goldapi":
            providers.append(GoldApiSilverProvider(settings))
        elif provider_name == "metals_api":
            providers.append(MetalsApiSilverProvider(settings))
        seen.add(provider_name)
    return providers


class PriceRefreshService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        uow: SqlAlchemyUnitOfWork,
        prices,
    ) -> None:
        self._settings = settings
        self._db = db
        self._uow = uow
        self._prices = prices
        self._providers = build_external_price_providers(settings)
        self._last_provider_attempt: dict[str, float] = {}

    async def refresh_once(self) -> dict:
        if not self._providers:
            async with self._uow.transaction():
                last_good = await self._prices.get_last_good()
            if last_good is None:
                await self._notify_admins(
                    "price.refresh_failed",
                    {"reason": "no_external_providers", "configured_primary": self._settings.price_provider_primary},
                )
                return {"status": "failed", "reason": "no_external_providers"}
            self._update_last_good_metric(last_good["updated_at"])
            return {"status": "fallback", "source": last_good["source"], "price_usd": str(last_good["sell_price"])}

        timeout = ClientTimeout(total=self._settings.price_provider_timeout_seconds)
        errors: list[dict[str, str]] = []
        async with ClientSession(timeout=timeout) as session:
            for provider in self._providers:
                if self._is_rate_limited(provider.name):
                    logger.info("price_provider_rate_limited", extra={"provider": provider.name})
                    continue
                try:
                    quote = await self._fetch_with_retry(provider, session)
                    self._validate_quote(quote)
                    async with self._uow.transaction():
                        duplicate = await self._prices.is_duplicate(
                            source=quote.provider_name,
                            buy_price=quote.price_usd_per_kg,
                            sell_price=quote.price_usd_per_kg,
                            provider_timestamp=quote.quoted_at,
                        )
                        await self._prices.set_provider_status(
                            provider_name=quote.provider_name,
                            is_healthy=True,
                            checked_at=utcnow(),
                            last_price_usd_per_kg=quote.price_usd_per_kg,
                        )
                        if duplicate:
                            row = await self._prices.get_last_good()
                        else:
                            row = await self._prices.upsert(
                                buy_price=quote.price_usd_per_kg,
                                sell_price=quote.price_usd_per_kg,
                                spread=Decimal("0"),
                                commission=Decimal("0"),
                                premium=Decimal("0"),
                                discount=Decimal("0"),
                                source=quote.provider_name,
                                external_id=quote.external_id,
                                provider_timestamp=quote.quoted_at,
                                is_verified=True,
                                is_stale=False,
                                raw_payload=json.dumps(quote.raw_payload, ensure_ascii=False),
                            )
                    PRICE_REFRESH_TOTAL.labels(provider=quote.provider_name, status="success").inc()
                    PRICE_PROVIDER_HEALTH.labels(provider=quote.provider_name).set(1)
                    self._update_last_good_metric(row["updated_at"] if row is not None else utcnow())
                    logger.info(
                        "price_refresh_success",
                        extra={"provider": quote.provider_name, "price_usd_per_kg": str(quote.price_usd_per_kg), "duplicate": duplicate},
                    )
                    return {
                        "status": "duplicate" if duplicate else "ok",
                        "provider": quote.provider_name,
                        "price_usd": str(quote.price_usd_per_kg),
                    }
                except Exception as exc:
                    checked_at = utcnow()
                    async with self._uow.transaction():
                        await self._prices.set_provider_status(
                            provider_name=provider.name,
                            is_healthy=False,
                            checked_at=checked_at,
                            error=str(exc),
                        )
                        last_good = await self._prices.get_last_good()
                    PRICE_REFRESH_TOTAL.labels(provider=provider.name, status="failure").inc()
                    PRICE_PROVIDER_HEALTH.labels(provider=provider.name).set(0)
                    errors.append({"provider": provider.name, "error": str(exc)})
                    logger.warning("price_refresh_failed", extra={"provider": provider.name, "error": str(exc)})
                    if last_good is not None:
                        self._update_last_good_metric(last_good["updated_at"])
                    continue

        async with self._uow.transaction():
            last_good = await self._prices.get_last_good()
        if last_good is not None:
            self._update_last_good_metric(last_good["updated_at"])
            logger.warning("price_refresh_fallback", extra={"source": last_good["source"], "errors": errors})
            return {
                "status": "fallback",
                "source": last_good["source"],
                "price_usd": str(last_good["sell_price"]),
                "errors": errors,
            }
        await self._notify_admins("price.refresh_failed", {"errors": errors})
        return {"status": "failed", "reason": "all_providers_failed", "errors": errors}

    async def _fetch_with_retry(self, provider: ExternalPriceProvider, session: ClientSession) -> ProviderQuote:
        attempts = self._settings.price_provider_max_retries + 1
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                return await provider.fetch_quote(session)
            except Exception as exc:
                last_error = exc
        raise PriceProviderError(str(last_error) if last_error is not None else f"{provider.name} failed")

    def _validate_quote(self, quote: ProviderQuote) -> None:
        price = quote.price_usd_per_kg
        if price < self._settings.price_provider_min_price_usd_per_kg:
            raise PriceProviderError("provider price is below the allowed minimum")
        if price > self._settings.price_provider_max_price_usd_per_kg:
            raise PriceProviderError("provider price is above the allowed maximum")
        age_seconds = (utcnow() - ensure_utc(quote.quoted_at)).total_seconds()
        if age_seconds > self._settings.price_provider_stale_after_seconds:
            raise PriceProviderError("provider quote is stale")

    def _is_rate_limited(self, provider_name: str) -> bool:
        if self._settings.price_provider_min_interval_seconds <= 0:
            return False
        now = monotonic()
        previous = self._last_provider_attempt.get(provider_name)
        if previous is not None and now - previous < self._settings.price_provider_min_interval_seconds:
            return True
        self._last_provider_attempt[provider_name] = now
        return False

    def _update_last_good_metric(self, updated_at: datetime) -> None:
        age_seconds = max(0.0, (utcnow() - ensure_utc(updated_at)).total_seconds())
        PRICE_LAST_GOOD_AGE_SECONDS.set(age_seconds)

    async def _notify_admins(self, kind: str, payload: dict) -> None:
        async with self._db.session() as session:
            async with session.begin():
                admin_user_ids = (
                    await session.scalars(
                        select(UserRole.user_id)
                        .join(Role, Role.id == UserRole.role_id)
                        .where(Role.name.in_(["admin", "super_admin", "manager"]))
                    )
                ).all()
                for user_id in set(admin_user_ids):
                    session.add(
                        Notification(
                            user_id=user_id,
                            channel="telegram",
                            kind=kind,
                            payload=json.dumps(payload, ensure_ascii=False),
                            status=NotificationStatus.pending.value,
                            created_at=utcnow(),
                        )
                    )
