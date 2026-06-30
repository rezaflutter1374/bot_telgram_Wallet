from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from domain.enums import DeadLetterReason
from infrastructure.db.models import DeadLetterEntry

logger = logging.getLogger("resilience.dead_letter")


class DeadLetterQueue:
    def __init__(self, db_session_factory) -> None:
        self._session_factory = db_session_factory

    async def enqueue(
        self,
        source: str,
        task_name: str,
        payload: dict,
        error_message: str | None = None,
        reason: DeadLetterReason = DeadLetterReason.max_retries,
        retry_count: int = 0,
    ) -> dict:
        async with self._session_factory() as session:
            async with session.begin():
                entry = DeadLetterEntry(
                    source=source,
                    task_name=task_name,
                    payload_json=json.dumps(payload, ensure_ascii=False),
                    error_message=error_message,
                    reason=reason.value,
                    retry_count=retry_count,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(entry)
                await session.flush()
                logger.warning("dlq_enqueued", extra={"source": source, "task": task_name, "reason": reason.value, "id": entry.id})
                return {"id": entry.id, "source": source, "task_name": task_name}

    async def list_entries(self, limit: int = 50, source: str | None = None) -> list[dict]:
        from sqlalchemy import select

        async with self._session_factory() as session:
            stmt = select(DeadLetterEntry).order_by(DeadLetterEntry.created_at.desc()).limit(limit)
            if source:
                stmt = stmt.where(DeadLetterEntry.source == source)
            rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "source": r.source,
                    "task_name": r.task_name,
                    "error_message": r.error_message,
                    "reason": r.reason,
                    "retry_count": r.retry_count,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    async def count_by_source(self) -> dict[str, int]:
        from sqlalchemy import func, select

        async with self._session_factory() as session:
            stmt = select(DeadLetterEntry.source, func.count(DeadLetterEntry.id)).group_by(DeadLetterEntry.source)
            rows = (await session.execute(stmt)).all()
            return {row[0]: row[1] for row in rows}
