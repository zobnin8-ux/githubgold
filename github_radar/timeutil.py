"""Timezone-aware dates for slides and daily stats."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Europe/Moscow"


def resolve_timezone(name: str | None = None) -> ZoneInfo:
    key = (name or os.getenv("TIMEZONE") or DEFAULT_TIMEZONE).strip()
    try:
        return ZoneInfo(key)
    except Exception:
        return ZoneInfo("UTC")


def to_local(dt: datetime | None, tz: ZoneInfo) -> datetime:
    if dt is None:
        dt = datetime.now(timezone.utc)
    elif dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz)


def day_bounds_utc(tz: ZoneInfo, *, on: datetime | None = None) -> tuple[str, str]:
    """Return (start_utc_iso, end_utc_iso) for the local calendar day."""
    local = to_local(on, tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return (
        start.astimezone(timezone.utc).isoformat(),
        end.astimezone(timezone.utc).isoformat(),
    )


def slide_folder_parts(when: datetime | None, tz: ZoneInfo) -> tuple[str, str]:
    """Local date and time parts for slide directories: YYYY-MM-DD / HH-MM."""
    local = to_local(when, tz)
    return local.strftime("%Y-%m-%d"), local.strftime("%H-%M")


def slide_folder_label(when: datetime | None, tz: ZoneInfo) -> str:
    date_part, time_part = slide_folder_parts(when, tz)
    return f"{date_part}/{time_part}"
