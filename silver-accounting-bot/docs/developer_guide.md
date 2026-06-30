# Developer Guide

## Local Run (without Docker)

1. Create venv and install:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Export environment variables (or create `.env`):

- `BOT_TOKEN`
- `DATABASE_URL`
- `REDIS_URL`
- `ENCRYPTION_KEY`

3. Run migrations:

```bash
python -m infrastructure.db.migrate
```

4. Run bot:

```bash
python -m main bot
```

## Tests

```bash
pytest
```

