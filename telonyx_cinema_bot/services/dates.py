from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo


def local_date_now(timezone: ZoneInfo) -> date:
    return datetime.now(timezone).date()


def local_date_from_datetime(value: datetime, timezone: ZoneInfo) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone)
    return value.astimezone(timezone).date()

