"""Selected-period membership for the Analytics Sheet (pure, no I/O).

Policy
------
* FROM and TO are inclusive local calendar dates.
* They become one half-open interval of UTC instants:
  ``[FROM at local 00:00, (TO + 1 day) at local 00:00)``.
* Each boundary is resolved independently from its own local midnight (never by
  adding 24 hours), exactly like ``time_projection.civil_day_window_utc``, so
  23- and 25-hour DST days are honoured.
* A record's timestamp is parsed to an aware instant and compared as an
  instant.  UTC date strings are never compared with local calendar dates.
* A timestamp that cannot be parsed is *unplaceable*: it belongs to no period
  and is never silently included.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Final

from time_projection import resolve_timezone

IN: Final = "in"
OUT: Final = "out"
UNPLACEABLE: Final = "unplaceable"

_UNSET: Final = object()


def parse_instant(value: object) -> datetime | None:
    """Parse a recorded ISO timestamp to an aware instant (naive means UTC)."""

    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _boundary_utc(local_date: date, zone: tzinfo | None) -> datetime:
    naive = datetime.combine(local_date, time.min)
    local = naive.astimezone() if zone is None else naive.replace(tzinfo=zone)
    return local.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Period:
    start: date  # inclusive local calendar date
    end: date  # inclusive local calendar date
    zone: tzinfo | None  # None means the machine's local zone
    timezone_key: str
    start_utc: datetime  # inclusive
    end_utc: datetime  # exclusive

    def classify(self, value: object) -> str:
        instant = parse_instant(value)
        if instant is None:
            return UNPLACEABLE
        return IN if self.start_utc <= instant < self.end_utc else OUT

    def contains(self, value: object) -> bool:
        return self.classify(value) == IN

    @property
    def label(self) -> str:
        return f"{self.start:%d %b %Y} – {self.end:%d %b %Y}"


def make_period(
    start: date,
    end: date,
    *,
    timezone_key: str = "local",
    zone: tzinfo | None | object = _UNSET,
) -> Period:
    """Validate the dates and build the half-open UTC interval."""

    if not isinstance(start, date) or not isinstance(end, date):
        raise TypeError("FROM and TO must be dates")
    if start > end:
        raise ValueError("The From date must not be later than the To date.")
    resolved = resolve_timezone(timezone_key) if zone is _UNSET else zone
    return Period(
        start,
        end,
        resolved,  # type: ignore[arg-type]
        timezone_key,
        _boundary_utc(start, resolved),  # type: ignore[arg-type]
        _boundary_utc(end + timedelta(days=1), resolved),  # type: ignore[arg-type]
    )


@dataclass(frozen=True, slots=True)
class Selection:
    """Records of one organ split by membership; ``inside`` is what is reported."""

    inside: tuple
    outside: int
    unplaceable: int

    @property
    def source_total(self) -> int:
        return len(self.inside) + self.outside + self.unplaceable


def select_by_start(items: Iterable, start_of: Callable[[object], object], period: Period) -> Selection:
    inside: list = []
    outside = unplaceable = 0
    for item in items:
        state = period.classify(start_of(item))
        if state == IN:
            inside.append(item)
        elif state == OUT:
            outside += 1
        else:
            unplaceable += 1
    return Selection(tuple(inside), outside, unplaceable)
