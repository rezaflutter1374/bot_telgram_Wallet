# Deployment Guide

## Docker Compose

1. Create `.env` from `.env.example`.
2. Run services:

```bash
docker compose up --build
```

3. Apply migrations:

```bash
docker compose run --rm migrate
```

## Containers

- `bot`: Telegram long-polling + health/metrics HTTP server
- `worker`: ARQ worker (background jobs)
- `scheduler`: APScheduler (01:25 Asia/Kabul, Mon–Fri) enqueues daily settlement
- `postgres`: PostgreSQL
- `redis`: Redis
- `prometheus`/`grafana`: monitoring

