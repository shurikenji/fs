"""
Centralized time helpers for the server.

Runtime, persistence, and admin rendering all normalize to GMT+7.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


GMT_PLUS_7 = timezone(timedelta(hours=7), name="GMT+7")
DB_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_now_vn() -> datetime:
    """Return the current timezone-aware datetime in GMT+7."""
    return datetime.now(GMT_PLUS_7)


def to_gmt7(value: str | datetime | None) -> datetime | None:
    """Parse legacy timestamps and normalize them to GMT+7."""
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=GMT_PLUS_7)
        return value.astimezone(GMT_PLUS_7)

    text = str(value).strip()
    if not text:
        return None

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(text[:19].replace("T", " "), DB_TIME_FORMAT)
        except ValueError:
            return None

    if parsed.tzinfo is not None:
        return parsed.astimezone(GMT_PLUS_7)

    if "T" in text:
        return parsed.replace(tzinfo=timezone.utc).astimezone(GMT_PLUS_7)

    return parsed.replace(tzinfo=GMT_PLUS_7)


def to_db_time_string(value: str | datetime | None = None) -> str:
    """Serialize a timestamp to the DB-friendly GMT+7 string format."""
    resolved = to_gmt7(value) if value is not None else get_now_vn()
    if resolved is None:
        resolved = get_now_vn()
    return resolved.astimezone(GMT_PLUS_7).strftime(DB_TIME_FORMAT)
