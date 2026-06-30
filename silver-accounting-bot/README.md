# Silver Accounting & Trading Telegram Bot

Enterprise-grade asynchronous Telegram bot (Python + Aiogram) with Clean Architecture/DDD layering, PostgreSQL, Redis, Docker, RBAC, trading engine, margin engine, risk engine, settlement engine, support tickets, pricing cache, production hardening (circuit breakers, retry, DLQ, cleanup jobs), and Prometheus/Grafana monitoring.

## Quick Start (Docker)

1. Copy environment file:

```bash
cp .env.example .env
```

2. Generate encryption key:

```bash
python scripts/generate_fernet_key.py
```

3. Edit `.env` and set:

- `BOT_TOKEN`
- `ENCRYPTION_KEY`
- `SUPER_ADMIN_TELEGRAM_IDS`

4. Run:

```bash
docker compose up --build
```

5. Apply migrations:

```bash
docker compose run --rm migrate
```

## Health & Metrics

- Liveness: `GET /live`
- Readiness: `GET /ready`
- Health: `GET /health`
- Metrics: `GET /metrics`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

## Production Hardening

The bot includes enterprise-grade resilience patterns:

- **Circuit Breaker** — per-service failure tracking with auto-recovery. States: closed → open → half-open → closed.
- **Retry with Exponential Backoff** — configurable retries with jitter for transient failures.
- **Dead Letter Queue** — failed tasks recorded with source, reason, and retry count for forensic analysis.
- **Data Retention & Cleanup** — daily cron job purges old settlement, audit, notification, and execution records based on configurable retention days.
- **Correlation ID** — `X-Correlation-ID` header propagated through all HTTP responses for request tracing.
- **Rate Limiting** — per-user rate limiting with configurable window and limit.
- **Maintenance Mode** — system-wide read-only mode with custom message.
- **Settlement Locking** — Redis-based distributed lock prevents concurrent settlement execution.

## Architecture

```
src/
├── core/              # Settings, DI container, security, logging
├── domain/            # Entities, enums, domain services, event definitions
├── application/       # Use cases (AppServices), DTOs, port interfaces, errors
├── infrastructure/    # DB models/session/repos, Redis, pricing, settlement,
│                      # scheduler, ARQ tasks, monitoring, resilience (CB/DLQ/retry),
│                      # event bus (store/retry/DLQ/tracing)
└── presentation/      # Telegram bot (aiogram) with routers, middlewares, admin panel
```

### Domain Event System

The bot includes a typed domain event abstraction (`domain/events.py`) and an in-memory event bus (`infrastructure/event_bus.py`) with:

- **Event Store** — all published events are persisted to an `event_store` SQL table for audit and replay.
- **Retry Mechanism** — handlers that fail are retried up to `max_retries` with exponential backoff + jitter.
- **Dead Letter Queue (DLQ)** — events exhausting all retries are moved to a `dead_letter_queue` table with failure reason and retry count.
- **Distributed Tracing** — every event carries a unique `event_id`, `correlation_id`, and `causation_id` for full causality chains.
- **Subscriber Registry** — typed subscription via `EventBus.subscribe(EventType, handler)` with async dispatch.

Key domain events: `OrderCreated`, `OrderFilled`, `OrderCancelled`, `PaymentApproved`, `PaymentRejected`, `PaymentReconciled`, `PeriodClosed`, `PeriodReopened`, `PriceChanged`, `PriceAnomalyDetected`, `SettlementExecuted`, `WalletCredited`, `WalletDebited`, `UserRegistered`, `KycUpdated`.

### Settlement Accounting

The settlement engine (`infrastructure/repositories/sql_repos.py:SettlementRepo`) supports:

- **Financial Periods** — open/close/reopen monthly or yearly periods with cross-period balance verification.
- **Structured Snapshots** — periodic snapshots store chart of accounts state (account_id, code, name, type, balance_usd, normal_side, as_of_date).
- **Period-Closing Entries** — close revenue/expense accounts to retained earnings, mark periods as closed.
- **Reconciliation** — matching payments against bank reference numbers with audit trail.
- **Deferred Settlement** — wallet funds can be settled on a deferred schedule (T+1, T+2, etc.) using the `settle_at` column.

### Wallet Enhancements

The wallet system (`infrastructure/repositories/sql_repos.py:WalletRepo`) adds:

- **Pending Balance** — tracks funds awaiting settlement that are not yet available for trading/withdrawal.
- **Settlement Balance** — the current amount being settled in this cycle.
- **Deferred Settlement** — each wallet transaction carries an optional `settle_at` timestamp for scheduling future settlement.
- **Rich Payment History** — payments returned with type, status timestamps, and reference numbers.

## Telegram Commands (Admin Panel)

Use `/admin` to open the interactive inline-keyboard admin panel with sections for:
- Statistics, Trading, Settlement, Risk, Users, Broadcast, Prices, Scheduler, Maintenance, KYC, Roles

### User Commands

User:

- `/start`
- `/help`
- `/kyc`
- `/price`
- `/wallet`
- `/buy`
- `/sell`
- `/receipt <order_id>`
- `/orders`
- `/cancelorder <order_id>`
- `/confirmcancel <order_id>`
- `/ticket <subject>`
- `/deposit <amount_usd>`
- `/withdraw <amount_usd>`

Support:

- `/replyticket <ticket_id> <message>`
- `/closeticket <ticket_id>`
- `/reopenticket <ticket_id>`
- `/internalticketnote <ticket_id> <message>`
- `/tickets [open|closed] [query]`

Accountant:

- `/approveorder <order_id>`
- `/rejectorder <order_id>`
- `/approvepayment <payment_id> [note]`
- `/rejectpayment <payment_id> [note]`
- `/pendingpayments`
- `/trialbalance`
- `/exporttrialbalance [csv|xlsx|pdf]`
- `/pnl`
- `/exportpnl [csv|xlsx|pdf]`
- `/balancesheet`
- `/exportbalancesheet [csv|xlsx|pdf]`
- `/cashflow`
- `/exportcashflow [csv|xlsx|pdf]`
- `/financialdashboard`
- `/dailyreport`
- `/weeklyreport`
- `/monthlyreport`
- `/yearlyreport`
- `/manualjournal <debit_code> <credit_code> <amount_usd> <description>`
- `/addbankaccount <name>|<account_number>`
- `/listbankaccounts`
- `/addcard <bank_account_id> <label>|<card_number>`
- `/listcards [bank_account_id]`

Admin (also available via `/admin` inline panel):

- `/setprice <buy> <sell>`
- `/grantrole <telegram_id> <role>`
- `/reviewkyc <telegram_id> <status> [note]`
- `/setrisk <name> <max_user_exposure_kg> <max_order_kg> <enabled>`
- `/pendingcancels`
- `/approvecancel <order_id>`
- `/rejectcancel <order_id>`
- `/backup`
- `/restore`
- `/maintenance`
- `/maintenanceon [message]`
- `/maintenanceoff`
- `/broadcast <message>`
- `/broadcastrole <role> <message>`
- `/broadcastlang <language_code> <message>`
- `/broadcastkyc <status> <message>`
- `/broadcastactive <true|false> <message>`
- `/broadcastschedule <ISO-8601 datetime> <message>`
- Reply to a message and use `/broadcastreply` to forward text/media to users

## Database Migrations

Migrations are managed with Alembic under `alembic/versions/`:

| Migration | Description |
|-----------|-------------|
| `0001` – `0008` | Core schema: users, roles, orders, wallets, settlements, payments, tickets, KYC, prices, risk, audit logs |
| `0009_event_store_snapshots_wallet` | Event store table, dead letter queue, settlement snapshots, wallet pending/settlement/deferred columns, financial periods table |

Run pending migrations:
```bash
alembic upgrade head
```

## Documentation

See `docs/` for architecture, ERD, deployment, and sequence diagrams.
