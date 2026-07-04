from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from arq.connections import RedisSettings, create_pool
from redis.asyncio import Redis

from application.ports.repositories.backup_repo import BackupRepo
from core.security import Encryptor
from core.settings import Settings

logger = logging.getLogger("backup_scheduler")

BACKUP_INDEX_KEY = "backup:index"


class BackupScheduler:
    def __init__(
        self,
        backup_repo: BackupRepo,
        encryptor: Encryptor,
        redis: Redis,
        settings: Settings,
    ) -> None:
        self._backup_repo = backup_repo
        self._encryptor = encryptor
        self._redis = redis
        self._settings = settings
        self._scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self._backup_dir = Path(settings.backup_directory)
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def _backup_path(self, backup_id: str) -> Path:
        return self._backup_dir / f"backup_{backup_id}.enc"

    def _checksum_path(self, backup_id: str) -> Path:
        return self._backup_dir / f"backup_{backup_id}.sha256"

    def _compute_checksum(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def schedule_backup(self, cron_expression: str = "0 3 * * *") -> None:
        parts = cron_expression.split()
        self._scheduler.add_job(
            self.run_backup,
            trigger=CronTrigger(
                minute=parts[0],
                hour=parts[1],
                day=parts[2],
                month=parts[3],
                day_of_week=parts[4],
                timezone=self._settings.timezone,
            ),
            id="auto_backup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("backup_scheduled", extra={"cron": cron_expression})
        self._scheduler.start()

    async def run_backup(self) -> dict:
        backup_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        snapshot = await self._backup_repo.create_snapshot()
        raw = json.dumps(snapshot, ensure_ascii=False, default=str)
        encrypted = self._encryptor.encrypt_text(raw)
        payload = encrypted.encode("utf-8")
        checksum = self._compute_checksum(payload)
        self._backup_path(backup_id).write_bytes(payload)
        self._checksum_path(backup_id).write_text(checksum)
        size = len(payload)
        await self._record_backup(backup_id, checksum, size)
        logger.info("backup_created", extra={"backup_id": backup_id, "size": size})
        return {"backup_id": backup_id, "size": size, "checksum": checksum, "created_at": snapshot["created_at"]}

    async def _record_backup(self, backup_id: str, checksum: str, size: int) -> None:
        index = await self._load_index()
        index[backup_id] = {
            "backup_id": backup_id,
            "checksum": checksum,
            "size": size,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.set(BACKUP_INDEX_KEY, json.dumps(index, ensure_ascii=False))

    async def _load_index(self) -> dict[str, dict]:
        raw = await self._redis.get(BACKUP_INDEX_KEY)
        if raw is None:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}
        return data

    async def list_backups(self) -> list[dict]:
        index = await self._load_index()
        backups = []
        for bid, meta in index.items():
            path = self._backup_path(bid)
            checksum_path = self._checksum_path(bid)
            meta["file_exists"] = path.exists()
            if checksum_path.exists():
                meta["stored_checksum"] = checksum_path.read_text().strip()
            else:
                meta["stored_checksum"] = None
            backups.append(meta)
        backups.sort(key=lambda b: b.get("created_at", ""), reverse=True)
        return backups

    async def restore_from_backup(self, backup_id: str) -> dict:
        path = self._backup_path(backup_id)
        if not path.exists():
            raise FileNotFoundError(f"Backup {backup_id} not found at {path}")
        payload = path.read_bytes()
        expected_checksum = self._compute_checksum(payload)
        checksum_path = self._checksum_path(backup_id)
        if checksum_path.exists():
            stored = checksum_path.read_text().strip()
            if stored != expected_checksum:
                raise ValueError(
                    f"Checksum mismatch for backup {backup_id}: "
                    f"expected {stored}, computed {expected_checksum}"
                )
        encrypted = payload.decode("utf-8")
        raw = self._encryptor.decrypt_text(encrypted)
        snapshot = json.loads(raw)
        await self._backup_repo.restore_snapshot(snapshot, wipe_existing=True)
        logger.info("backup_restored", extra={"backup_id": backup_id})
        return {"backup_id": backup_id, "restored_at": datetime.now(timezone.utc).isoformat()}

    async def prune_old_backups(self, retention_days: int = 30) -> dict:
        cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
        index = await self._load_index()
        pruned = []
        for bid in list(index.keys()):
            created = index[bid].get("created_at", "")
            try:
                created_ts = datetime.fromisoformat(created).timestamp()
            except (ValueError, TypeError):
                created_ts = 0
            if created_ts < cutoff:
                self._backup_path(bid).unlink(missing_ok=True)
                self._checksum_path(bid).unlink(missing_ok=True)
                del index[bid]
                pruned.append(bid)
        await self._redis.set(BACKUP_INDEX_KEY, json.dumps(index, ensure_ascii=False))
        logger.info("backups_pruned", extra={"removed": len(pruned), "retention_days": retention_days})
        return {"pruned": pruned, "count": len(pruned)}

    async def close(self) -> None:
        self._scheduler.shutdown(wait=False)
