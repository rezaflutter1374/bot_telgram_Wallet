from __future__ import annotations

from datetime import datetime
import json

from infrastructure.db.session import Database
from infrastructure.settlement.service import SettlementEngineService


async def run_daily_settlement(db: Database, settlement_at: datetime | None = None) -> dict:
    engine = SettlementEngineService(db=db, redis=None)
    result = await engine.execute(mode="daily", settlement_at=settlement_at)
    summary = result["summary"]
    if result["status"] == "skipped":
        return {"status": "skipped", "reason": "no_price", "summary": summary}
    report = json.loads(summary["report_json"]) if summary.get("report_json") else {}
    return {
        "status": "ok",
        "price_usd": str(summary["price_usd"]) if summary.get("price_usd") is not None else None,
        "report": report,
        "summary": summary,
        "idempotent": result["idempotent"],
    }
