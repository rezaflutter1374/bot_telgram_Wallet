from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select

from domain.enums import NotificationStatus, SettlementMode, SettlementStatus
from infrastructure.db.models import (
    JournalAccount,
    JournalEntry,
    JournalLine,
    LedgerEntry,
    Notification,
    Position,
    Price,
    Role,
    Settlement,
    SettlementBatch,
    SettlementCheckpoint,
    SettlementReconciliation,
    SettlementReport,
    UserRole,
    Wallet,
)
from infrastructure.db.session import Database


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_dumps(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


class SettlementEngineService:
    def __init__(self, db: Database, redis: Redis | None = None) -> None:
        self._db = db
        self._redis = redis
        self._lock_key = "settlement:lock"

    async def execute(
        self,
        *,
        mode: str,
        settlement_at: datetime | None = None,
        actor_user_id: int | None = None,
        user_ids: list[int] | None = None,
        idempotency_key: str | None = None,
        replay_of_settlement_id: int | None = None,
    ) -> dict:
        mode_enum = SettlementMode(mode)
        settlement_at = settlement_at or utcnow()
        target_scope = sorted(set(user_ids or []))
        batch_key = self._build_batch_key(mode_enum, settlement_at, target_scope, replay_of_settlement_id, idempotency_key)
        token = await self._acquire_lock()
        try:
            await self._recover_stale_batches()
            async with self._db.session() as session:
                async with session.begin():
                    existing = await self._find_existing_batch(session, batch_key=batch_key, idempotency_key=idempotency_key)
                    if existing is not None:
                        return await self._build_result(session, existing, idempotent=existing.status == SettlementStatus.completed.value)

                    price = await session.scalar(
                        select(Price)
                        .where(Price.is_verified.is_(True), Price.is_stale.is_(False))
                        .order_by(Price.updated_at.desc())
                    )
                    if price is None:
                        batch = await self._create_batch(
                            session,
                            batch_key=batch_key,
                            idempotency_key=idempotency_key,
                            mode=mode_enum,
                            settlement_at=settlement_at,
                            actor_user_id=actor_user_id,
                            user_ids=target_scope,
                            verification_json={"reason": "no_verified_price"},
                            status=SettlementStatus.skipped,
                        )
                        await self._checkpoint(session, batch, "skipped_no_verified_price", {"target_date": settlement_at.isoformat()})
                        return await self._build_result(session, batch, idempotent=False)

                    verification = await self._verify_preconditions(session, settlement_at, price, target_scope)
                    batch = await self._create_batch(
                        session,
                        batch_key=batch_key,
                        idempotency_key=idempotency_key,
                        mode=mode_enum,
                        settlement_at=settlement_at,
                        actor_user_id=actor_user_id,
                        user_ids=target_scope,
                        verification_json=verification,
                        status=SettlementStatus.running,
                    )
                    await self._checkpoint(session, batch, "verified_inputs", verification)

                    settlement = Settlement(
                        batch_id=batch.id,
                        mode=mode_enum.value,
                        status=SettlementStatus.running.value,
                        replay_of_settlement_id=replay_of_settlement_id,
                        settlement_date=settlement_at,
                        price_usd=Decimal(price.sell_price),
                        verification_json=json_dumps(verification),
                        created_at=utcnow(),
                    )
                    session.add(settlement)
                    await session.flush()

                    summary = await self._apply_settlement(
                        session=session,
                        settlement=settlement,
                        settlement_at=settlement_at,
                        settlement_price=Decimal(price.sell_price),
                        price_source=price.source,
                        user_ids=target_scope,
                    )
                    await self._checkpoint(session, batch, "applied_positions", summary)

                    report_payload = {
                        "batch_key": batch.batch_key,
                        "settlement_id": settlement.id,
                        "mode": settlement.mode,
                        "settlement_date": settlement_at.isoformat(),
                        "price_source": price.source,
                        "price_usd": str(settlement.price_usd),
                        "affected_users": summary["affected_users"],
                        "net_pnl_usd": str(summary["net_pnl_usd"]),
                    }
                    session.add(
                        SettlementReport(
                            settlement_id=settlement.id,
                            summary_json=json_dumps(report_payload),
                            created_at=utcnow(),
                        )
                    )
                    await self._notify_settlement_admins(session, "settlement.report_ready", report_payload)
                    settlement.status = SettlementStatus.completed.value
                    batch.status = SettlementStatus.completed.value
                    batch.completed_at = utcnow()
                    batch.updated_at = utcnow()
                    await self._checkpoint(session, batch, "completed", report_payload)
                    return await self._build_result(session, batch, idempotent=False)
        finally:
            await self._release_lock(token)

    async def rollback(self, *, settlement_id: int, actor_user_id: int | None = None, reason: str | None = None) -> dict:
        token = await self._acquire_lock()
        try:
            async with self._db.session() as session:
                async with session.begin():
                    settlement = await session.get(Settlement, settlement_id)
                    if settlement is None:
                        raise RuntimeError("Settlement not found")
                    if settlement.status != SettlementStatus.completed.value:
                        raise RuntimeError("Only completed settlements can be rolled back")
                    if settlement.rollback_of_settlement_id is not None:
                        raise RuntimeError("Rollback settlements cannot be rolled back again")

                    existing_rollback = await session.scalar(
                        select(Settlement).where(Settlement.rollback_of_settlement_id == settlement.id)
                    )
                    if existing_rollback is not None:
                        batch = await session.scalar(select(SettlementBatch).where(SettlementBatch.id == existing_rollback.batch_id))
                        if batch is None:
                            raise RuntimeError("Rollback batch not found")
                        return await self._build_result(session, batch, idempotent=True)

                    batch = await self._create_batch(
                        session,
                        batch_key=f"rollback:{settlement.id}",
                        idempotency_key=f"rollback:{settlement.id}",
                        mode=SettlementMode.rollback,
                        settlement_at=utcnow(),
                        actor_user_id=actor_user_id,
                        user_ids=[],
                        verification_json={"rollback_of_settlement_id": settlement.id, "reason": reason},
                        status=SettlementStatus.running,
                    )
                    await self._checkpoint(session, batch, "rollback_started", {"rollback_of_settlement_id": settlement.id})

                    customer = await session.scalar(select(JournalAccount).where(JournalAccount.code == "2000"))
                    income = await session.scalar(select(JournalAccount).where(JournalAccount.code == "4000"))
                    expense = await session.scalar(select(JournalAccount).where(JournalAccount.code == "5000"))
                    if customer is None or income is None or expense is None:
                        raise RuntimeError("Accounting chart not ready")

                    rollback_settlement = Settlement(
                        batch_id=batch.id,
                        mode=SettlementMode.rollback.value,
                        status=SettlementStatus.running.value,
                        rollback_of_settlement_id=settlement.id,
                        settlement_date=utcnow(),
                        price_usd=Decimal(settlement.price_usd),
                        verification_json=json_dumps({"rollback_of_settlement_id": settlement.id, "reason": reason}),
                        created_at=utcnow(),
                    )
                    session.add(rollback_settlement)
                    await session.flush()

                    reconciliations = (
                        await session.scalars(
                            select(SettlementReconciliation).where(SettlementReconciliation.settlement_id == settlement.id)
                        )
                    ).all()
                    affected_users = 0
                    net_pnl = Decimal("0")
                    for item in reconciliations:
                        wallet = await session.scalar(select(Wallet).where(Wallet.user_id == item.user_id))
                        position = await session.scalar(select(Position).where(Position.user_id == item.user_id))
                        if wallet is None or position is None:
                            continue
                        affected_users += 1
                        net_pnl -= Decimal(item.pnl_usd)
                        wallet.available_balance_usd = Decimal(item.balance_before_usd)
                        wallet.updated_at = utcnow()
                        position.last_settlement_price_usd = Decimal(item.previous_settlement_price_usd)
                        position.updated_at = utcnow()
                        amt = abs(Decimal(item.pnl_usd)).quantize(Decimal("0.01"))
                        if amt > 0:
                            entry = JournalEntry(
                                reference=f"settlement_rollback:{settlement.id}:{item.user_id}",
                                description="Settlement rollback",
                                posted_at=utcnow(),
                                created_by_user_id=actor_user_id,
                                created_at=utcnow(),
                            )
                            session.add(entry)
                            await session.flush()
                            if Decimal(item.pnl_usd) > 0:
                                session.add(JournalLine(entry_id=entry.id, account_id=customer.id, user_id=item.user_id, debit_usd=amt, credit_usd=Decimal("0"), created_at=utcnow()))
                                session.add(JournalLine(entry_id=entry.id, account_id=expense.id, user_id=None, debit_usd=Decimal("0"), credit_usd=amt, created_at=utcnow()))
                            else:
                                session.add(JournalLine(entry_id=entry.id, account_id=income.id, user_id=None, debit_usd=amt, credit_usd=Decimal("0"), created_at=utcnow()))
                                session.add(JournalLine(entry_id=entry.id, account_id=customer.id, user_id=item.user_id, debit_usd=Decimal("0"), credit_usd=amt, created_at=utcnow()))
                        session.add(
                            LedgerEntry(
                                user_id=item.user_id,
                                entry_type="adjustment",
                                amount_usd=-Decimal(item.pnl_usd),
                                description="Settlement rollback",
                                reference=f"settlement_rollback:{settlement.id}",
                                created_at=utcnow(),
                            )
                        )
                        session.add(
                            SettlementReconciliation(
                                settlement_id=rollback_settlement.id,
                                user_id=item.user_id,
                                pnl_usd=-Decimal(item.pnl_usd),
                                balance_before_usd=Decimal(item.balance_after_usd),
                                balance_after_usd=Decimal(item.balance_before_usd),
                                previous_settlement_price_usd=Decimal(item.new_settlement_price_usd),
                                new_settlement_price_usd=Decimal(item.previous_settlement_price_usd),
                                status=SettlementStatus.rolled_back.value,
                                payload_json=json_dumps({"rollback_of_reconciliation_id": item.id}),
                                created_at=utcnow(),
                            )
                        )

                    report_payload = {
                        "batch_key": batch.batch_key,
                        "settlement_id": rollback_settlement.id,
                        "rollback_of_settlement_id": settlement.id,
                        "affected_users": affected_users,
                        "net_pnl_usd": str(net_pnl.quantize(Decimal("0.01"))),
                        "reason": reason,
                    }
                    session.add(
                        SettlementReport(
                            settlement_id=rollback_settlement.id,
                            summary_json=json_dumps(report_payload),
                            created_at=utcnow(),
                        )
                    )
                    settlement.status = SettlementStatus.rolled_back.value
                    rollback_settlement.status = SettlementStatus.completed.value
                    batch.status = SettlementStatus.completed.value
                    batch.completed_at = utcnow()
                    batch.updated_at = utcnow()
                    await self._checkpoint(session, batch, "rolled_back", report_payload)
                    await self._notify_settlement_admins(session, "settlement.rollback_completed", report_payload)
                    return await self._build_result(session, batch, idempotent=False)
        finally:
            await self._release_lock(token)

    async def replay(self, *, settlement_id: int, actor_user_id: int | None = None, idempotency_key: str | None = None) -> dict:
        async with self._db.session() as session:
            settlement = await session.get(Settlement, settlement_id)
            if settlement is None:
                raise RuntimeError("Settlement not found")
            reconciliations = (
                await session.scalars(
                    select(SettlementReconciliation).where(SettlementReconciliation.settlement_id == settlement_id)
                )
            ).all()
            user_ids = [row.user_id for row in reconciliations]
            settlement_at = settlement.settlement_date
        replay_key = idempotency_key or f"replay:{settlement_id}"
        return await self.execute(
            mode=SettlementMode.replay.value,
            settlement_at=settlement_at,
            actor_user_id=actor_user_id,
            user_ids=user_ids or None,
            idempotency_key=replay_key,
            replay_of_settlement_id=settlement_id,
        )

    async def list_history(self, *, limit: int = 20) -> list[dict]:
        async with self._db.session() as session:
            rows = (
                await session.execute(
                    select(SettlementBatch, Settlement, SettlementReport)
                    .join(Settlement, Settlement.batch_id == SettlementBatch.id, isouter=True)
                    .join(SettlementReport, SettlementReport.settlement_id == Settlement.id, isouter=True)
                    .order_by(SettlementBatch.created_at.desc())
                    .limit(limit)
                )
            ).all()
            return [self._summary_from_rows(batch, settlement, report) for batch, settlement, report in rows]

    async def get_status(self, *, batch_key: str) -> dict | None:
        async with self._db.session() as session:
            batch = await session.scalar(select(SettlementBatch).where(SettlementBatch.batch_key == batch_key))
            if batch is None:
                return None
            settlement = await session.scalar(select(Settlement).where(Settlement.batch_id == batch.id))
            report = None
            if settlement is not None:
                report = await session.scalar(select(SettlementReport).where(SettlementReport.settlement_id == settlement.id))
            return self._summary_from_rows(batch, settlement, report)

    async def _verify_preconditions(self, session, settlement_at: datetime, price: Price, user_ids: list[int]) -> dict:
        customer = await session.scalar(select(JournalAccount).where(JournalAccount.code == "2000"))
        income = await session.scalar(select(JournalAccount).where(JournalAccount.code == "4000"))
        expense = await session.scalar(select(JournalAccount).where(JournalAccount.code == "5000"))
        if customer is None or income is None or expense is None:
            raise RuntimeError("Accounting chart not ready")
        stmt = select(Position).order_by(Position.user_id.asc())
        if user_ids:
            stmt = stmt.where(Position.user_id.in_(user_ids))
        positions = (await session.scalars(stmt)).all()
        missing_wallets: list[int] = []
        for pos in positions:
            if Decimal(pos.net_kg) == 0:
                continue
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == pos.user_id))
            if wallet is None:
                missing_wallets.append(pos.user_id)
        if missing_wallets:
            raise RuntimeError(f"Wallets missing for users: {missing_wallets}")
        return {
            "verified_price_source": price.source,
            "verified_price_updated_at": price.updated_at.isoformat(),
            "verified_price_usd": str(price.sell_price),
            "target_user_count": len(user_ids),
            "settlement_at": settlement_at.isoformat(),
        }

    async def _apply_settlement(
        self,
        *,
        session,
        settlement: Settlement,
        settlement_at: datetime,
        settlement_price: Decimal,
        price_source: str,
        user_ids: list[int],
    ) -> dict:
        customer = await session.scalar(select(JournalAccount).where(JournalAccount.code == "2000"))
        income = await session.scalar(select(JournalAccount).where(JournalAccount.code == "4000"))
        expense = await session.scalar(select(JournalAccount).where(JournalAccount.code == "5000"))
        stmt = select(Position)
        if user_ids:
            stmt = stmt.where(Position.user_id.in_(user_ids))
        positions = (await session.scalars(stmt)).all()
        affected_users = 0
        realized_total = Decimal("0")
        for pos in positions:
            net_kg = Decimal(pos.net_kg)
            if net_kg == 0:
                continue
            wallet = await session.scalar(select(Wallet).where(Wallet.user_id == pos.user_id))
            if wallet is None:
                raise RuntimeError(f"Wallet not found for user {pos.user_id}")
            previous_price = Decimal(pos.last_settlement_price_usd)
            balance_before = Decimal(wallet.available_balance_usd)
            if previous_price == 0:
                pos.last_settlement_price_usd = settlement_price
                pos.updated_at = utcnow()
                session.add(
                    SettlementReconciliation(
                        settlement_id=settlement.id,
                        user_id=pos.user_id,
                        pnl_usd=Decimal("0"),
                        balance_before_usd=balance_before,
                        balance_after_usd=balance_before,
                        previous_settlement_price_usd=previous_price,
                        new_settlement_price_usd=settlement_price,
                        status=SettlementStatus.completed.value,
                        payload_json=json_dumps({"initialized_only": True, "price_source": price_source}),
                        created_at=utcnow(),
                    )
                )
                continue

            pnl = (settlement_price - previous_price) * net_kg
            balance_after = balance_before + pnl
            wallet.available_balance_usd = balance_after
            wallet.updated_at = utcnow()
            pos.last_settlement_price_usd = settlement_price
            pos.updated_at = utcnow()
            affected_users += 1 if pnl != 0 else 0
            realized_total += pnl
            amt = abs(pnl).quantize(Decimal("0.01"))
            if pnl != 0 and amt > 0 and customer is not None and income is not None and expense is not None:
                entry = JournalEntry(
                    reference=f"settlement:{settlement.id}:{pos.user_id}",
                    description="Daily settlement PnL",
                    posted_at=settlement_at,
                    created_by_user_id=None,
                    created_at=utcnow(),
                )
                session.add(entry)
                await session.flush()
                if pnl > 0:
                    session.add(JournalLine(entry_id=entry.id, account_id=expense.id, user_id=None, debit_usd=amt, credit_usd=Decimal("0"), created_at=utcnow()))
                    session.add(JournalLine(entry_id=entry.id, account_id=customer.id, user_id=pos.user_id, debit_usd=Decimal("0"), credit_usd=amt, created_at=utcnow()))
                else:
                    session.add(JournalLine(entry_id=entry.id, account_id=customer.id, user_id=pos.user_id, debit_usd=amt, credit_usd=Decimal("0"), created_at=utcnow()))
                    session.add(JournalLine(entry_id=entry.id, account_id=income.id, user_id=None, debit_usd=Decimal("0"), credit_usd=amt, created_at=utcnow()))
            session.add(
                LedgerEntry(
                    user_id=pos.user_id,
                    entry_type="adjustment",
                    amount_usd=pnl,
                    description="Daily settlement PnL",
                    reference=f"settlement:{settlement.id}",
                    created_at=utcnow(),
                )
            )
            session.add(
                SettlementReconciliation(
                    settlement_id=settlement.id,
                    user_id=pos.user_id,
                    pnl_usd=pnl,
                    balance_before_usd=balance_before,
                    balance_after_usd=balance_after,
                    previous_settlement_price_usd=previous_price,
                    new_settlement_price_usd=settlement_price,
                    status=SettlementStatus.completed.value,
                    payload_json=json_dumps({"price_source": price_source}),
                    created_at=utcnow(),
                )
            )
            session.add(
                Notification(
                    user_id=pos.user_id,
                    channel="telegram",
                    kind="settlement.completed",
                    payload=json_dumps(
                        {
                            "settlement_date": settlement_at.date().isoformat(),
                            "price_usd": str(settlement_price),
                            "pnl_usd": str(pnl.quantize(Decimal("0.01"))),
                        }
                    ),
                    status=NotificationStatus.pending.value,
                    created_at=utcnow(),
                )
            )
        return {
            "affected_users": affected_users,
            "net_pnl_usd": realized_total.quantize(Decimal("0.01")),
        }

    async def _create_batch(
        self,
        session,
        *,
        batch_key: str,
        idempotency_key: str | None,
        mode: SettlementMode,
        settlement_at: datetime,
        actor_user_id: int | None,
        user_ids: list[int],
        verification_json: dict,
        status: SettlementStatus,
    ) -> SettlementBatch:
        batch = SettlementBatch(
            batch_key=batch_key,
            idempotency_key=idempotency_key,
            mode=mode.value,
            status=status.value,
            target_date=settlement_at,
            lock_key=self._lock_key,
            actor_user_id=actor_user_id,
            user_scope_json=json_dumps(user_ids),
            verification_json=json_dumps(verification_json),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        if status in {SettlementStatus.completed, SettlementStatus.failed, SettlementStatus.skipped}:
            batch.completed_at = utcnow()
        session.add(batch)
        await session.flush()
        return batch

    async def _checkpoint(self, session, batch: SettlementBatch, checkpoint_name: str, payload: dict) -> None:
        checkpoint = SettlementCheckpoint(
            batch_id=batch.id,
            checkpoint_name=checkpoint_name,
            payload_json=json_dumps(payload),
            created_at=utcnow(),
        )
        session.add(checkpoint)
        batch.last_checkpoint = checkpoint_name
        batch.updated_at = utcnow()
        await session.flush()

    async def _notify_settlement_admins(self, session, kind: str, payload: dict) -> None:
        admin_user_ids = (
            await session.scalars(
                select(UserRole.user_id)
                .join(Role, Role.id == UserRole.role_id)
                .where(Role.name.in_(["admin", "super_admin", "accountant", "manager"]))
            )
        ).all()
        for user_id in set(admin_user_ids):
            session.add(
                Notification(
                    user_id=user_id,
                    channel="telegram",
                    kind=kind,
                    payload=json_dumps(payload),
                    status=NotificationStatus.pending.value,
                    created_at=utcnow(),
                )
            )

    async def _find_existing_batch(self, session, *, batch_key: str, idempotency_key: str | None) -> SettlementBatch | None:
        batch = await session.scalar(select(SettlementBatch).where(SettlementBatch.batch_key == batch_key))
        if batch is not None:
            return batch
        if idempotency_key is None:
            return None
        return await session.scalar(select(SettlementBatch).where(SettlementBatch.idempotency_key == idempotency_key))

    async def _build_result(self, session, batch: SettlementBatch, *, idempotent: bool) -> dict:
        settlement = await session.scalar(select(Settlement).where(Settlement.batch_id == batch.id))
        report = None
        if settlement is not None:
            report = await session.scalar(select(SettlementReport).where(SettlementReport.settlement_id == settlement.id))
        return {
            "status": batch.status,
            "idempotent": idempotent,
            "summary": self._summary_from_rows(batch, settlement, report),
        }

    def _summary_from_rows(self, batch: SettlementBatch, settlement: Settlement | None, report: SettlementReport | None) -> dict:
        payload = json.loads(report.summary_json) if report is not None else {}
        return {
            "settlement_id": settlement.id if settlement is not None else None,
            "batch_key": batch.batch_key,
            "mode": batch.mode,
            "status": batch.status,
            "target_date": batch.target_date,
            "price_usd": Decimal(settlement.price_usd) if settlement is not None else None,
            "price_source": payload.get("price_source"),
            "affected_users": int(payload.get("affected_users", 0)),
            "net_pnl_usd": Decimal(str(payload.get("net_pnl_usd", "0"))),
            "report_json": report.summary_json if report is not None else None,
            "created_at": batch.created_at,
            "completed_at": batch.completed_at,
            "last_checkpoint": batch.last_checkpoint,
            "error_message": batch.error_message,
            "replay_of_settlement_id": settlement.replay_of_settlement_id if settlement is not None else None,
            "rollback_of_settlement_id": settlement.rollback_of_settlement_id if settlement is not None else None,
        }

    def _build_batch_key(
        self,
        mode: SettlementMode,
        settlement_at: datetime,
        user_ids: list[int],
        replay_of_settlement_id: int | None,
        idempotency_key: str | None,
    ) -> str:
        if idempotency_key:
            return idempotency_key
        scope = ",".join(str(user_id) for user_id in user_ids) if user_ids else "all"
        replay = f":replay_of:{replay_of_settlement_id}" if replay_of_settlement_id is not None else ""
        return f"{mode.value}:{settlement_at.date().isoformat()}:{scope}{replay}"

    async def _recover_stale_batches(self) -> None:
        async with self._db.session() as session:
            async with session.begin():
                threshold = utcnow() - timedelta(minutes=30)
                rows = (
                    await session.scalars(
                        select(SettlementBatch)
                        .where(SettlementBatch.status == SettlementStatus.running.value, SettlementBatch.updated_at < threshold)
                    )
                ).all()
                for batch in rows:
                    batch.status = SettlementStatus.failed.value
                    batch.error_message = "Recovered stale settlement batch after interrupted execution"
                    batch.updated_at = utcnow()
                    batch.completed_at = utcnow()

    async def _acquire_lock(self) -> str:
        token = str(uuid.uuid4())
        if self._redis is None:
            return token
        locked = await self._redis.set(self._lock_key, token, ex=300, nx=True)
        if not locked:
            raise RuntimeError("Settlement engine is locked")
        return token

    async def _release_lock(self, token: str) -> None:
        if self._redis is None:
            return
        current = await self._redis.get(self._lock_key)
        if current == token:
            await self._redis.delete(self._lock_key)
