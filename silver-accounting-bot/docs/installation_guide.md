# Installation Guide

## Prerequisites

- Docker and Docker Compose
- Python 3.13+ for local development
- Telegram bot token
- Fernet encryption key

## Docker Installation

1. Copy the environment template:

```bash
cp .env.example .env
```

2. Generate a Fernet key:

```bash
python scripts/generate_fernet_key.py
```

3. Set the required environment variables in `.env`:

- `BOT_TOKEN`
- `ENCRYPTION_KEY`
- `SUPER_ADMIN_TELEGRAM_IDS`

4. Start the stack:

```bash
docker compose up --build
```

5. Run migrations:

```bash
docker compose run --rm migrate
```

## Local Development Installation

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure `.env`.
4. Apply migrations.
5. Start the bot:

```bash
python -m src.main
```

