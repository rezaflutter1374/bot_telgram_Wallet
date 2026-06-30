from __future__ import annotations

import asyncio
import os

from alembic import command
from alembic.config import Config


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


async def _upgrade() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")


def main() -> None:
    asyncio.run(_upgrade())


if __name__ == "__main__":
    main()

