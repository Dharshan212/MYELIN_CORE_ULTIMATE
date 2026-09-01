"""Pure selected-timezone projection for immutable UTC evidence.

The selected key is supplied by the caller on every operation.  This module
owns no preference, timer, thread, database connection, or mutable timezone
state; ``SettingsController`` remains the sole persisted choice authority.
"""

from __future__ import annotations

from datetime import date, datetime, time as time_of_day, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_NUMERIC_TZNAME_DISPLAY = {
    "Asia/Dubai": "GST",
    "Asia/Singapore": "SGT",
}


class TimezoneProjectionError(ValueError):
    """A requested presentation timezone cannot be resolved truthfully."""


def resolve_timezone(timezone_key: str):
    """Return a real ``ZoneInfo`` or ``None`` for the actual OS-local zone.

    Named historical projection deliberately has no fixed-offset fallback:
    applying today's offset to old evidence would mislabel DST-observing
    zones.  ``local`` remains special because Windows/Python may not expose a
    stable IANA identifier for the configured system zone.
    """

    key = str(timezone_key or "").strip()
    if not key:
        raise TimezoneProjectionError("presentation timezone key is empty")
    if key == "local":
        return None
    try:
        return ZoneInfo(key)
    except ZoneInfoNotFoundError as error:
        raise TimezoneProjectionError(
            f"named presentation timezone is unavailable: {key}"
        ) from error


def parse_utc_timestamp(value: object) -> datetime:
    """Parse one ISO timestamp that names a UTC instant.

    Both MYELIN's canonical ``Z`` form and its historical ``+00:00`` form are
    accepted.  Non-UTC offsets and naive timestamps are rejected rather than
    silently reinterpreted as evidence from another clock.
    """

    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise TimezoneProjectionError("UTC timestamp is unreadable") from error
    if moment.tzinfo is None or moment.utcoffset() != timedelta(0):
        raise TimezoneProjectionError("timestamp does not identify a UTC instant")
    return moment.astimezone(timezone.utc)


def project_utc_datetime(moment: datetime, timezone_key: str) -> datetime:
    """Project one aware instant through the explicitly supplied lens."""

    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise TimezoneProjectionError("projection requires an aware datetime")
    utc_moment = moment.astimezone(timezone.utc)
    zone = resolve_timezone(timezone_key)
    return utc_moment.astimezone() if zone is None else utc_moment.astimezone(zone)


def project_utc_timestamp(value: object, timezone_key: str) -> datetime:
    """Parse canonical UTC evidence and project it to the selected zone."""

    return project_utc_datetime(parse_utc_timestamp(value), timezone_key)


def selected_civil_date(
    timezone_key: str,
    *,
    now_utc: datetime | None = None,
) -> date:
    """Return Today in the selected MYELIN timezone."""

    moment = now_utc or datetime.now(timezone.utc)
    return project_utc_datetime(moment, timezone_key).date()


def civil_day_window_utc(local_date: date, timezone_key: str) -> tuple[datetime, datetime]:
    """Convert independently resolved local midnight boundaries to UTC.

    Resolving both civil boundaries separately preserves 23-hour and 25-hour
    DST days.  The end is never computed by adding 24 hours to the resolved
    start instant.
    """

    if not isinstance(local_date, date):
        raise TypeError("local_date must be a date")
    start_naive = datetime.combine(local_date, time_of_day.min)
    end_naive = datetime.combine(local_date + timedelta(days=1), time_of_day.min)
    zone = resolve_timezone(timezone_key)
    if zone is None:
        start_local = start_naive.astimezone()
        end_local = end_naive.astimezone()
    else:
        start_local = start_naive.replace(tzinfo=zone)
        end_local = end_naive.replace(tzinfo=zone)
    return (
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def timezone_tag(moment: datetime, timezone_key: str) -> str:
    """Return the projected instant's truthful short zone indication."""

    tag = str(moment.tzname() or "").strip()
    if tag.startswith(("+", "-")):
        tag = _NUMERIC_TZNAME_DISPLAY.get(timezone_key, timezone_key)
    if tag:
        return tag
    return "LOCAL" if timezone_key == "local" else str(timezone_key)


__all__ = [
    "TimezoneProjectionError",
    "civil_day_window_utc",
    "parse_utc_timestamp",
    "project_utc_datetime",
    "project_utc_timestamp",
    "resolve_timezone",
    "selected_civil_date",
    "timezone_tag",
]
