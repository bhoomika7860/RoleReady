from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


def user_today(tz_name: str | None, now: datetime | None = None) -> date:
    """Plan dates are computed in the user's timezone (default Asia/Kolkata); storage stays UTC."""
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    return (now or datetime.now(timezone.utc)).astimezone(tz).date()


def to_user_date(ts: datetime, tz_name: str | None) -> date:
    try:
        tz = ZoneInfo(tz_name or "Asia/Kolkata")
    except Exception:
        tz = ZoneInfo("Asia/Kolkata")
    return ts.astimezone(tz).date()
