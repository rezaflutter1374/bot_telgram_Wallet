from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


class Database:
    def __init__(
        self,
        database_url: str,
        *,
        pool_size: int = 10,
        max_overflow: int = 20,
        pool_timeout: int = 30,
        pool_recycle: int = 1800,
    ) -> None:
        engine_kwargs = {"pool_pre_ping": True}
        if not database_url.startswith("sqlite+"):
            engine_kwargs.update(
                {
                    "pool_size": pool_size,
                    "max_overflow": max_overflow,
                    "pool_timeout": pool_timeout,
                    "pool_recycle": pool_recycle,
                    "pool_use_lifo": True,
                }
            )
        self._engine: AsyncEngine = create_async_engine(database_url, **engine_kwargs)
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    def session(self) -> AsyncSession:
        return self._session_factory()


class SqlAlchemyUnitOfWork:
    def __init__(self, db: Database) -> None:
        self._db = db
        self.session: AsyncSession | None = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self._db.session() as session:
            self.session = session
            async with session.begin():
                yield
            self.session = None
