from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telonyx_cinema_bot.services.dates import local_date_from_datetime


def test_local_date_uses_kyiv_day_not_utc_day() -> None:
    kyiv = ZoneInfo("Europe/Kiev")
    value = datetime(2026, 6, 13, 22, 30, tzinfo=timezone.utc)

    assert str(local_date_from_datetime(value, kyiv)) == "2026-06-14"

