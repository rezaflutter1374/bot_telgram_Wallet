from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_tz(dt: datetime, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def tz_now(tz_name: str) -> datetime:
    return to_tz(utc_now(), tz_name)

