"""Read-only daily projection of Today's Session Health.

This module owns exactly one responsibility: turning already-durable MYELIN
facts (``sessions``, ``triggers``, ``mirl_events``) into one immutable
``TodaySessionHealthSnapshot`` for a caller-supplied UTC window.

It never decides what "today" means. The caller
(``CONTROL_STATION/analytics.py``) resolves the system-local civil day and
converts it to a ``[window_start_utc, window_end_utc)`` UTC pair before
calling in here -- this file only counts durable facts inside that window.

Sessions use a windowed count. Triggers require an exact durable SINE
acceptance and use its factual wall time. Returns use PERSISTENCE.storage
(``read_mirl_events``), which already parses and validates every MIRL
payload, so a malformed record raises instead of being silently miscounted.

This reader FAILS CLOSED. A malformed or duplicate returned-episode closure
raises rather than under- or over-counting -- the Control Station renders
"Unavailable" on any such failure rather than a believable-looking wrong
number.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from PERSISTENCE.database import connect_database
from PERSISTENCE.storage import (
    bootstrap_production_schema, read_mirl_events, _operational_trigger_rows,
)


@dataclass(frozen=True, slots=True)
class TodaySessionHealthSnapshot:
    """Immutable, exact-integer projection. No rate, ratio or score."""

    local_date_iso: str
    window_start_utc: str
    window_end_utc: str
    session_count: int
    returned_episode_count: int
    trigger_count: int
    generated_at_utc: str
    schema_version: str = "myelin-today-session-health-v1"

    def __post_init__(self) -> None:
        for name in ("session_count", "returned_episode_count", "trigger_count"):
            value = getattr(self, name)
            # ``type(value) is not int`` (not ``isinstance``) so ``bool`` --
            # itself an ``int`` subclass -- is rejected too. A research metric
            # card must never coerce True/3.8/"3"/-2 into a believable count.
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"{name} must be an exact non-negative int, got {value!r}"
                )


def _parse_utc(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("expected a non-empty UTC timestamp")
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {value!r} is not timezone-aware")
    return parsed.astimezone(timezone.utc)


def _session_count(connection, window_start_utc: str, window_end_utc: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) FROM sessions "
        "WHERE started_at_utc >= ? AND started_at_utc < ?",
        (window_start_utc, window_end_utc),
    ).fetchone()
    return int(row[0])


def _trigger_count(connection, window_start_utc: str, window_end_utc: str) -> int:
    start, end = _parse_utc(window_start_utc), _parse_utc(window_end_utc)
    return sum(
        start <= _parse_utc(row["accepted_at_utc"]) < end
        for row in _operational_trigger_rows(connection)
    )


def _returned_episode_count(window_start_utc: str, window_end_utc: str) -> int:
    """Count only final stable recoveries: EPISODE_CLOSED with reason RETURNED.

    ``RETURN_VERIFIED`` is a different, earlier event -- confirmed return
    entry, stability still unproven -- and is never counted here, including
    when a verified return is followed by a relapse and the episode later
    closes with a different outcome.

    A duplicate RETURNED closure for the same ``episode_id`` is an integrity
    violation of the episode itself, not a property of any one day's window,
    so it is rejected globally across ALL durable evidence BEFORE window
    membership is even considered -- two duplicate closures that straddle a
    midnight boundary (one just before, one just after) must still fail
    closed, even though each alone would look like a normal single closure
    to whichever day's read happens to see it.
    """

    from MIRL.mirl import EpisodeOutcome, MirlEventName

    start = _parse_utc(window_start_utc)
    end = _parse_utc(window_end_utc)

    seen_episode_ids: set[str] = set()
    count = 0
    for event in read_mirl_events():
        if event.event_name is not MirlEventName.EPISODE_CLOSED:
            continue
        if event.reason != EpisodeOutcome.RETURNED.value:
            continue
        episode_id = str(event.episode_id or "")
        if not episode_id:
            raise ValueError(
                "returned EPISODE_CLOSED event is missing its episode_id"
            )
        if episode_id in seen_episode_ids:
            raise ValueError(
                f"duplicate returned EPISODE_CLOSED for episode {episode_id!r}"
            )
        seen_episode_ids.add(episode_id)

        occurred = _parse_utc(event.occurred_wall_time_utc)
        if start <= occurred < end:
            count += 1
    return count


def read_today_session_health(
    *,
    local_date_iso: str,
    window_start_utc: str,
    window_end_utc: str,
) -> TodaySessionHealthSnapshot:
    """Project today's Sessions / Returns / Triggers from durable facts only.

    Raises on any malformed input or malformed/duplicate MIRL evidence. The
    caller is expected to treat that as a failed read, not a zero snapshot.
    """

    if not str(local_date_iso or "").strip():
        raise ValueError("local_date_iso is required")
    if _parse_utc(window_start_utc) >= _parse_utc(window_end_utc):
        raise ValueError("window_start_utc must precede window_end_utc")

    bootstrap_production_schema()
    connection = connect_database(read_only=True)
    try:
        session_count = _session_count(connection, window_start_utc, window_end_utc)
        trigger_count = _trigger_count(connection, window_start_utc, window_end_utc)
    finally:
        connection.close()

    returned_episode_count = _returned_episode_count(window_start_utc, window_end_utc)

    return TodaySessionHealthSnapshot(
        local_date_iso=local_date_iso,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        session_count=session_count,
        returned_episode_count=returned_episode_count,
        trigger_count=trigger_count,
        generated_at_utc=(
            datetime.now(timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        ),
    )


__all__ = ["TodaySessionHealthSnapshot", "read_today_session_health"]
