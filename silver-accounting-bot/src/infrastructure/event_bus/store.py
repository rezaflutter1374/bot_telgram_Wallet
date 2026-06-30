from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import DeclarativeMeta

from domain.events import DomainEvent
from infrastructure.db.base import Base
from infrastructure.db.session import SqlAlchemyUnitOfWork


class StoredEvent(Base):
    __tablename__ = "stored_events"

    id: int = Column(Integer, primary_key=True)  # type: ignore[assignment]
    event_id: str = Column(String(64), nullable=False, unique=True, index=True)
    event_type: str = Column(String(128), nullable=False, index=True)
    category: str = Column(String(32), nullable=False, index=True)
    version: str = Column(String(8), nullable=False, default="1")
    aggregate_id: str | None = Column(String(64), nullable=True, index=True)
    aggregate_type: str | None = Column(String(64), nullable=True, index=True)
    actor_user_id: int | None = Column(Integer, nullable=True, index=True)
    payload_json: str = Column(Text, nullable=False, default="{}")
    metadata_json: str = Column(Text, nullable=False, default="{}")
    correlation_id: str | None = Column(String(64), nullable=True, index=True)
    causation_id: str | None = Column(String(64), nullable=True)
    occurred_at: datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    stored_at: datetime = Column(DateTime(timezone=True), nullable=False)


class EventStore:
    def __init__(self, uow: SqlAlchemyUnitOfWork) -> None:
        self._uow = uow

    async def append(self, event: DomainEvent) -> None:
        async with self._uow.transaction() as session:
            session.add(
                StoredEvent(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    category=event.category.value,
                    version=event.version.value,
                    aggregate_id=event.aggregate_id,
                    aggregate_type=event.aggregate_type,
                    actor_user_id=event.actor_user_id,
                    payload_json=json.dumps(event.payload, default=str),
                    metadata_json=json.dumps(event.metadata, default=str),
                    correlation_id=event.correlation_id,
                    causation_id=event.causation_id,
                    occurred_at=event.occurred_at,
                    stored_at=datetime.now(timezone.utc),
                )
            )

    async def list_events(
        self,
        *,
        event_type: str | None = None,
        aggregate_id: str | None = None,
        aggregate_type: str | None = None,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        async with self._uow.transaction() as session:
            stmt = select(StoredEvent).order_by(StoredEvent.occurred_at.desc())
            if event_type:
                stmt = stmt.where(StoredEvent.event_type == event_type)
            if aggregate_id:
                stmt = stmt.where(StoredEvent.aggregate_id == aggregate_id)
            if aggregate_type:
                stmt = stmt.where(StoredEvent.aggregate_type == aggregate_type)
            if category:
                stmt = stmt.where(StoredEvent.category == category)
            stmt = stmt.offset(offset).limit(limit)
            rows = (await session.scalars(stmt)).all()
            return [
                {
                    "id": r.id,
                    "event_id": r.event_id,
                    "event_type": r.event_type,
                    "category": r.category,
                    "version": r.version,
                    "aggregate_id": r.aggregate_id,
                    "aggregate_type": r.aggregate_type,
                    "actor_user_id": r.actor_user_id,
                    "payload": json.loads(r.payload_json),
                    "metadata": json.loads(r.metadata_json),
                    "correlation_id": r.correlation_id,
                    "causation_id": r.causation_id,
                    "occurred_at": r.occurred_at,
                    "stored_at": r.stored_at,
                }
                for r in rows
            ]

    async def count_events(
        self,
        *,
        event_type: str | None = None,
        category: str | None = None,
    ) -> int:
        async with self._uow.transaction() as session:
            stmt = select(StoredEvent.id)
            if event_type:
                stmt = stmt.where(StoredEvent.event_type == event_type)
            if category:
                stmt = stmt.where(StoredEvent.category == category)
            result = await session.execute(stmt)
            return len(result.all())
