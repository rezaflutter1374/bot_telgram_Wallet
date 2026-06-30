from __future__ import annotations

from decimal import Decimal
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str
    database_url: str
    redis_url: str
    encryption_key: str

    super_admin_telegram_ids: str = ""
    web_host: str = "0.0.0.0"
    web_port: int = 8080
    metrics_path: str = "/metrics"
    health_path: str = "/health"
    timezone: str = "Asia/Kabul"
    log_level: str = "INFO"

    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)
    db_pool_timeout: int = Field(default=30, ge=1, le=300)
    db_pool_recycle: int = Field(default=1800, ge=30, le=86400)

    redis_max_connections: int = Field(default=100, ge=1, le=1000)
    price_cache_ttl_seconds: int = Field(default=5, ge=1, le=300)
    notification_batch_size: int = Field(default=100, ge=1, le=1000)
    wallet_scan_batch_size: int = Field(default=500, ge=1, le=5000)

    rate_limit_limit: int = Field(default=30, ge=1, le=1000)
    rate_limit_window_seconds: int = Field(default=10, ge=1, le=3600)

    bot_mode: str = "auto"
    webhook_base_url: str | None = None
    webhook_path: str = "/telegram/webhook"
    webhook_secret: str | None = None
    webhook_timeout_seconds: int = Field(default=10, ge=1, le=120)

    price_refresh_interval_seconds: int = Field(default=30, ge=5, le=3600)
    price_provider_primary: str = "manual"
    price_provider_secondary: str | None = None
    price_provider_timeout_seconds: int = Field(default=10, ge=1, le=120)
    price_provider_max_retries: int = Field(default=2, ge=0, le=10)
    price_provider_stale_after_seconds: int = Field(default=300, ge=5, le=86400)
    price_provider_min_interval_seconds: int = Field(default=10, ge=0, le=3600)
    price_provider_min_price_usd_per_kg: Decimal = Decimal("100")
    price_provider_max_price_usd_per_kg: Decimal = Decimal("1000000")
    metals_api_url: str = "https://metals-api.com/api/latest"
    metals_api_key: str | None = None
    goldapi_url: str = "https://www.goldapi.io/api/XAG/USD"
    goldapi_key: str | None = None

    retention_days_settlement: int = Field(default=365, ge=30, le=3650)
    retention_days_audit: int = Field(default=730, ge=30, le=3650)
    retention_days_notifications: int = Field(default=90, ge=7, le=365)
    retention_days_execution_reports: int = Field(default=180, ge=30, le=3650)
    retention_days_margin_snapshots: int = Field(default=90, ge=7, le=365)
    cleanup_batch_size: int = Field(default=1000, ge=100, le=10000)
    dlq_max_retries: int = Field(default=3, ge=0, le=10)
    cb_error_threshold: int = Field(default=5, ge=1, le=100)
    cb_recovery_timeout_seconds: int = Field(default=60, ge=10, le=3600)
    cb_half_open_max_calls: int = Field(default=3, ge=1, le=20)
    settlement_lock_ttl_seconds: int = Field(default=300, ge=30, le=3600)
    margin_liquidation_critical_ratio: Decimal = Decimal("0.50")
    margin_call_threshold_ratio: Decimal = Decimal("1")
    margin_warning_ratio: Decimal = Decimal("1.25")

    @property
    def super_admin_ids(self) -> set[int]:
        if not self.super_admin_telegram_ids.strip():
            return set()
        return {int(x.strip()) for x in self.super_admin_telegram_ids.split(",") if x.strip()}

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: str) -> str:
        value = value.strip()
        if not value or value == "CHANGE_ME":
            raise ValueError("BOT_TOKEN must be configured")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg:// or sqlite+aiosqlite://")
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            raise ValueError("REDIS_URL must use redis:// or rediss://")
        return value

    @field_validator("encryption_key")
    @classmethod
    def validate_encryption_key(cls, value: str) -> str:
        value = value.strip()
        if not value or value == "CHANGE_ME_32_BYTES_BASE64_URLSAFE":
            raise ValueError("ENCRYPTION_KEY must be configured")
        if len(value) < 40:
            raise ValueError("ENCRYPTION_KEY must be a valid Fernet key")
        return value

    @field_validator("metrics_path", "health_path")
    @classmethod
    def validate_http_path(cls, value: str) -> str:
        path = value.strip()
        if not path.startswith("/"):
            raise ValueError("HTTP paths must start with '/'")
        if str(PurePosixPath(path)) != path:
            raise ValueError("HTTP paths must be normalized")
        return path

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        normalized = value.strip().upper()
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return normalized

    @field_validator("bot_mode")
    @classmethod
    def validate_bot_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        allowed = {"auto", "polling", "webhook"}
        if normalized not in allowed:
            raise ValueError(f"BOT_MODE must be one of {sorted(allowed)}")
        return normalized

    @field_validator("webhook_path")
    @classmethod
    def validate_webhook_path(cls, value: str) -> str:
        path = value.strip()
        if not path.startswith("/"):
            raise ValueError("WEBHOOK_PATH must start with '/'")
        return path

    @field_validator("price_provider_primary", "price_provider_secondary")
    @classmethod
    def validate_price_provider_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        allowed = {"manual", "metals_api", "goldapi"}
        if normalized not in allowed:
            raise ValueError(f"Price provider must be one of {sorted(allowed)}")
        return normalized
