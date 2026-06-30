# Configuration Guide

## Core Environment Variables

- `BOT_TOKEN`: Telegram bot token
- `DATABASE_URL`: Async SQLAlchemy database URL
- `REDIS_URL`: Redis connection URL
- `ENCRYPTION_KEY`: Fernet key used for sensitive value encryption
- `SUPER_ADMIN_TELEGRAM_IDS`: Comma-separated Telegram IDs promoted to super admin on first start

## HTTP and Monitoring

- `BOT_MODE`: `auto`, `polling`, or `webhook`
- `WEBHOOK_BASE_URL`
- `WEBHOOK_PATH`
- `WEBHOOK_SECRET`
- `WEBHOOK_TIMEOUT_SECONDS`
- `WEB_HOST`
- `WEB_PORT`
- `METRICS_PATH`
- `HEALTH_PATH`
- `TIMEZONE`
- `LOG_LEVEL`

## Database Pooling

- `DB_POOL_SIZE`
- `DB_MAX_OVERFLOW`
- `DB_POOL_TIMEOUT`
- `DB_POOL_RECYCLE`

## Redis and Cache

- `REDIS_MAX_CONNECTIONS`
- `PRICE_CACHE_TTL_SECONDS`
- `PRICE_REFRESH_INTERVAL_SECONDS`
- `PRICE_PROVIDER_PRIMARY`
- `PRICE_PROVIDER_SECONDARY`
- `PRICE_PROVIDER_TIMEOUT_SECONDS`
- `PRICE_PROVIDER_MAX_RETRIES`
- `PRICE_PROVIDER_STALE_AFTER_SECONDS`
- `PRICE_PROVIDER_MIN_INTERVAL_SECONDS`
- `PRICE_PROVIDER_MIN_PRICE_USD_PER_KG`
- `PRICE_PROVIDER_MAX_PRICE_USD_PER_KG`
- `METALS_API_URL`
- `METALS_API_KEY`
- `GOLDAPI_URL`
- `GOLDAPI_KEY`
- `NOTIFICATION_BATCH_SIZE`
- `WALLET_SCAN_BATCH_SIZE`

## Telegram Protection

- `RATE_LIMIT_LIMIT`
- `RATE_LIMIT_WINDOW_SECONDS`

## Notes

- Production deployment requires a real `.env`; `.env.example` is only a template.
- Health checks depend on both PostgreSQL and Redis being reachable.
- Scheduler timezone is configured through `TIMEZONE` and defaults to `Asia/Kabul`.
- External price refresh stores verified historical prices, provider health, and last-known-good fallback state in the database.
- When external providers are disabled or unavailable, the system falls back to the latest verified cached/manual price instead of using an unverified quote.
