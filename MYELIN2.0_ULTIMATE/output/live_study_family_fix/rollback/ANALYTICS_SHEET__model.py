"""Presentation model for the date-specific MYELIN Analytics Sheet.

Four independently selectable organ chapters (MIRL, COSINE, MINE, STUDY MODE)
are built from the projections the Analytics Sheet already receives.  Every
chapter is built from the records whose *recorded start time* falls inside the
selected period; nothing else enters the report:

* the period filter is applied BEFORE any statistic is produced, so counts,
  outcome tables, timelines, findings and the cover/overview all describe the
  same qualifying population;
* lifetime projections (Metric Hub / Science Lab totals, lifetime counters,
  "worst ever" values) are never copied into the report;
* nothing is derived scientifically: tables only group recorded values;
* an organ whose reader works but has no qualifying record shows
  "No episode recorded"; an organ that cannot be read shows "Evidence
  unavailable" (never a zero).

This module is presentation only: no SQLite, no read-model imports.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from enum import Enum
from typing import Final

from .period import Period, make_period, parse_instant, select_by_start

SECTION_KEYS: Final = ("live-mirl", "cosine", "mine", "study-mode")
REPORT_KEYS: Final = (*SECTION_KEYS, "secant", "cosecant")
SECTION_TITLES: Final = {
    "live-mirl": "MIRL",
    "cosine": "COSINE",
    "mine": "MINE",
    "study-mode": "STUDY MODE",
    "secant": "SECANT",
    "cosecant": "COSECANT",
}
SECTION_SUBTITLES: Final = {
    "live-mirl": "Recovery episodes",
    "cosine": "OTT episodes",
    "mine": "Messaging episodes",
    "study-mode": "Study records",
    "secant": "Study off-task recovery evidence",
    "cosecant": "Approved Study-break and return evidence",
}
SECTION_ATTRS: Final = {"live-mirl": "live_mirl", "cosine": "cosine", "mine": "mine"}
INTEGRITY_TITLE: Final = "Evidence Integrity"
UNAVAILABLE: Final = "Unavailable"
DASH: Final = "—"
NO_EPISODE: Final = "No episode recorded"

AVAILABLE_STATE: Final = "AVAILABLE"
NO_DATA_STATE: Final = "NO_DATA"
UNAVAILABLE_STATE: Final = "UNAVAILABLE"

TONES: Final = ("ok", "warn", "bad", "neutral", "accent", "muted")
MIRL_CLOSED_CAP: Final = 100  # MIRL projection keeps at most this many closed episodes


# --------------------------------------------------------------------------
# Structures
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Cell:
    text: str
    tone: str = ""  # "" plain text, else a badge in this tone
    mono: bool = False
    bold: bool = False
    small: bool = False
    tiny: bool = False  # identifiers: smallest legible monospace
    sub: str = ""  # second, smaller line (UTC time, identifier, outside-period flag)
    sub_mono: bool = False


@dataclass(frozen=True, slots=True)
class Table:
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    widths: tuple[float, ...]
    title: str = ""
    note: str = ""
    empty: str = "No records."
    align: tuple[str, ...] = ()
    header: bool = True
    dense: bool = False


@dataclass(frozen=True, slots=True)
class Card:
    label: str
    value: str
    caption: str = ""
    tone: str = ""


@dataclass(frozen=True, slots=True)
class CardRow:
    cards: tuple[Card, ...]


@dataclass(frozen=True, slots=True)
class Note:
    text: str
    tone: str = "info"  # info | warn


@dataclass(frozen=True, slots=True)
class EmptyState:
    """A centred panel: "No episode recorded" or "Evidence unavailable"."""

    title: str
    detail: str
    tone: str = "info"


@dataclass(frozen=True, slots=True)
class Heading:
    text: str
    sub: str = ""


@dataclass(frozen=True, slots=True)
class Record:
    """One episode/block: a header, key facts and its ordered event table."""

    title: str
    badges: tuple[Cell, ...]
    facts: tuple[tuple[str, str], ...]
    ids: tuple[tuple[str, str], ...]
    table: Table
    caption: str = ""
    extra: tuple[Table, ...] = ()


Block = Table | CardRow | Note | Heading | Record | EmptyState


@dataclass(frozen=True, slots=True)
class Section:
    key: str
    title: str
    subtitle: str
    blocks: tuple[Block, ...]
    appendix: bool = False


@dataclass(frozen=True, slots=True)
class ReportModel:
    period: Period
    period_text: str
    generated_label: str
    generated_iso: str
    tz_label: str
    sections: tuple[Section, ...]
    cover_items: tuple[str, ...]
    scope_note: str
    #: organ key -> AVAILABLE | NO_DATA | UNAVAILABLE
    states: Mapping[str, str]
    #: organ key -> identities of the records actually included in the report
    included: Mapping[str, tuple[str, ...]]
    sample_banner: str = ""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def g(obj: object, name: str, default=None):
    """Read one field from a dataclass, object or mapping (never raises)."""

    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def enum_text(value: object):
    return value.value if isinstance(value, Enum) else value


def txt(value: object, empty: str = DASH) -> str:
    """Whitespace-normalised display text; identifiers are never altered."""

    value = enum_text(value)
    if value is None:
        return empty
    cleaned = " ".join(str(value).split())
    return cleaned if cleaned else empty


def fmt_int(value: object) -> str:
    if value is None or type(value) is bool:
        return DASH
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return txt(value)


def fmt_seconds(value: object) -> str:
    if value is None or type(value) is bool or not isinstance(value, (int, float)):
        return DASH
    return f"{value:,.2f} s"


_ACRONYMS: Final = frozenset({"MIRL", "SINE", "MINE", "COSINE", "COSECANT", "UTC", "OTT", "ID", "UID"})


def humanize(name: object) -> str:
    """'native_mirl_events' -> 'Native MIRL events' (wording is never invented)."""

    text = txt(name)
    if text == DASH:
        return text
    words = text.replace("_", " ").split()
    out = []
    for i, word in enumerate(words):
        if word.upper() in _ACRONYMS:
            out.append(word.upper())
        elif word.isupper() and len(word) > 1:
            out.append(word.lower() if i else word.capitalize())
        else:
            out.append(word if i else word[:1].upper() + word[1:])
    return " ".join(out)


parse_ts = parse_instant


def tz_label(moment: datetime) -> str:
    offset = moment.utcoffset() or timedelta(0)
    minutes = int(offset.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{rest:02d}"


def local_dt(value: object, zone: tzinfo | None) -> datetime | None:
    parsed = parse_instant(value)
    if parsed is None:
        return None
    return parsed.astimezone(zone) if zone is not None else parsed.astimezone()


def fmt_dt(value: object, zone: tzinfo | None, *, ms: bool = False, date_part: bool = True) -> str:
    """Local wall time; a value that cannot be parsed is shown exactly as recorded."""

    moment = local_dt(value, zone)
    if moment is None:
        return txt(value)
    text = moment.strftime("%d %b %Y %H:%M:%S" if date_part else "%H:%M:%S")
    if ms:
        text += f".{moment.microsecond // 1000:03d}"
    return text


def status_tone(value: object) -> str:
    text = txt(value).upper()
    if text in {"AVAILABLE", "CONFIRMED", "RETURNED", "CLOSED_RETURNED", "OK", "OBSERVED", "COMPLETED", "COMPLETE"}:
        return "ok"
    if text in {"DEGRADED", "PENDING", "WAITING_FOR_RETURN", "PARTIAL", "WARNING", "DERIVED", "PAUSED"}:
        return "warn"
    if text in {"ERROR"}:
        return "bad"
    if text in {"UNAVAILABLE", "NOT AVAILABLE", "NO"}:
        return "muted"
    return "neutral"


def badge(value: object, *, text: str | None = None) -> Cell:
    return Cell(text if text is not None else txt(value), tone=status_tone(value))


def _rows(items) -> tuple[tuple[Cell, ...], ...]:
    return tuple(tuple(c if isinstance(c, Cell) else Cell(txt(c)) for c in row) for row in items)


def _table(columns, rows, widths, **kw) -> Table:
    return Table(tuple(columns), _rows(rows), tuple(widths), **kw)


def group_repeats(detail: object) -> str:
    """'A; A; B' -> 'A ×2; B ×1' (same tokens, same order of first use)."""

    parts = [p.strip() for p in txt(detail, "").split(";") if p.strip()]
    if not parts:
        return txt(detail)
    counts: dict[str, int] = {}
    for part in parts:
        counts[part] = counts.get(part, 0) + 1
    return "; ".join(f"{name} ×{n}" for name, n in counts.items())


def _grouped(title: str, label: str, values, *, note: str = "", empty: str = "No records.", unit: str = "Episodes") -> Table:
    counts = Counter(values)
    rows = [(humanize(k) if k is not None else "Not recorded", fmt_int(n)) for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))]
    return _table((label, unit), rows, (3.5, 1.2), title=title, note=note, align=("l", "r"), empty=empty)


def _outside_flag(period: Period, value: object) -> str:
    """'' inside the period, else a plain-language marker for the event row."""

    state = period.classify(value)
    if state == "in":
        return ""
    return "outside selected period" if state == "out" else "time not readable"


# --------------------------------------------------------------------------
# State classification (NO DATA versus UNAVAILABLE)
# --------------------------------------------------------------------------


def organ_state(key: str, projection: object) -> tuple[str, str]:
    """Return (state, detail) for one organ projection.

    UNAVAILABLE means the evidence could not be read or validated.  NO_DATA
    means the reader works but nothing has been recorded at all.
    """

    if projection is None:
        return UNAVAILABLE_STATE, "This organ's evidence was not supplied to the report."
    read_error = g(projection, "read_error")
    status = txt(g(projection, "status"), "").upper()
    if read_error or status in {"READ_ERROR", "TIMEZONE_ERROR", "STRUCTURAL_ERROR"}:
        return UNAVAILABLE_STATE, txt(g(projection, "status_message"), "The evidence source could not be read or validated.")
    if g(projection, "available") is False:
        reason = txt(g(projection, "empty_state_reason"), "")
        if key == "live-mirl" and reason.lower().startswith("no factual mirl"):
            return NO_DATA_STATE, reason
        return UNAVAILABLE_STATE, reason or txt(g(projection, "status_message"), "The evidence is unavailable.")
    if status == "EMPTY":
        return NO_DATA_STATE, txt(g(projection, "status_message"), "")
    return AVAILABLE_STATE, ""


def _empty_blocks(period_text: str, unit: str, *, unplaceable: int = 0) -> list[Block]:
    blocks: list[Block] = [
        EmptyState(NO_EPISODE, f"No {unit} has a recorded start time inside the selected period ({period_text}). Records outside the period are not shown."),
    ]
    if unplaceable:
        blocks.append(Note(f"{unplaceable:,} {unit}(s) have no readable recorded start time and cannot be assigned to any period; they are not included.", "warn"))
    return blocks


def _unavailable_blocks(detail: str) -> list[Block]:
    return [EmptyState("Evidence unavailable", "The evidence for this report section could not be read or validated, so no statement is made about the selected period. " + txt(detail, "")[:240], "warn")]


# --------------------------------------------------------------------------
# MIRL
# --------------------------------------------------------------------------


def _mirl_started(e: object):
    return g(e, "started_at")


def _mirl_section(projection: object, period: Period, zone) -> tuple[Section, str, tuple[str, ...], tuple]:
    key = "live-mirl"
    state, detail = organ_state(key, projection)
    subtitle = SECTION_SUBTITLES[key]
    if state == UNAVAILABLE_STATE:
        return Section(key, SECTION_TITLES[key], subtitle, tuple(_unavailable_blocks(detail))), state, (), ()
    active = tuple(g(projection, "active_episodes", ()) or ())
    closed = tuple(g(projection, "recently_closed_episodes", ()) or ())
    active_ids = {g(e, "episode_id") for e in active}
    selection = select_by_start(active + closed, _mirl_started, period)
    cap_note = Note(f"The MIRL projection keeps at most {MIRL_CLOSED_CAP} closed episodes, so older episodes may be missing from it; completeness for this period cannot be guaranteed.", "warn")
    if not selection.inside:
        blocks = _empty_blocks(period.label, "MIRL episode", unplaceable=selection.unplaceable)
        if len(closed) >= MIRL_CLOSED_CAP:
            blocks.append(cap_note)
        return Section(key, SECTION_TITLES[key], subtitle, tuple(blocks)), NO_DATA_STATE, (), ()
    episodes = selection.inside
    n_active = sum(1 for e in episodes if g(e, "episode_id") in active_ids)
    degraded = sum(1 for e in episodes if txt(g(e, "integrity_status")).upper() == "DEGRADED")
    blocks: list[Block] = [
        CardRow(
            (
                Card("MIRL episodes", fmt_int(len(episodes)), "started in the selected period"),
                Card("Active", fmt_int(n_active), "not yet closed"),
                Card("Closed", fmt_int(len(episodes) - n_active), "closed in the source"),
                Card("Degraded evidence", fmt_int(degraded), "integrity status DEGRADED", "warn" if degraded else ""),
            )
        ),
        Note(f"Episodes are assigned to the period by their recorded start time ({period.label}). Return intent is not verified recovery."),
        _grouped("Recorded episode status", "Status", [g(e, "episode_status") for e in episodes], note="Grouped from the recorded status of the episodes in this report."),
        _grouped("Recorded final outcome", "Outcome", [g(e, "final_outcome") for e in episodes]),
        _grouped("Integrity status", "Status", [txt(g(e, "integrity_status")) for e in episodes]),
    ]
    index_rows = [
        (
            Cell(txt(g(e, "short_display_id")), bold=True),
            badge(g(e, "episode_status")),
            humanize(g(e, "application")),
            Cell(fmt_dt(g(e, "started_at"), zone)),
            humanize(g(e, "final_outcome")) if g(e, "final_outcome") else "Not closed",
            fmt_seconds(g(e, "return_intent_latency_seconds")),
            fmt_seconds(g(e, "verified_return_latency_seconds")),
            badge(g(e, "integrity_status")),
        )
        for e in episodes
    ]
    blocks.append(
        _table(
            ("Episode", "Status", "App", "Started", "Final outcome", "Return intent", "Verified return", "Integrity"),
            index_rows,
            (1.35, 1.35, 0.85, 1.55, 1.05, 0.95, 0.95, 1.05),
            title="Episode index",
            note="One row per episode in the selected period; each episode's ordered timeline follows below.",
        )
    )
    blocks.append(Heading("Episode records", "Ordered event timelines. Basis shows whether the source marks an event observed or derived. Events outside the selected dates are marked."))
    for e in episodes:
        blocks.append(_mirl_record(e, period, zone))
    if selection.unplaceable:
        blocks.append(Note(f"{selection.unplaceable:,} MIRL episode(s) have no readable recorded start time and cannot be assigned to any period; they are not included.", "warn"))
    if len(closed) >= MIRL_CLOSED_CAP:
        blocks.append(cap_note)
    prov = g(g(projection, "metadata"), "research_provenance") or g(projection, "research_provenance")
    if g(prov, "limitation"):
        blocks.append(Note(txt(g(prov, "limitation"))))
    return (
        Section(key, SECTION_TITLES[key], subtitle, tuple(blocks)),
        AVAILABLE_STATE,
        tuple(txt(g(e, "episode_id")) for e in episodes),
        episodes,
    )


def _mirl_record(e: object, period: Period, zone) -> Record:
    rows = []
    previous_day = None
    outside = 0
    for t in g(e, "timeline", ()) or ():
        moment = local_dt(g(t, "occurred_at"), zone)
        day = moment.date() if moment else None
        show_date = day != previous_day
        previous_day = day
        flag = _outside_flag(period, g(t, "occurred_at"))
        outside += bool(flag)
        rows.append(
            (
                Cell(fmt_int(g(t, "episode_seq"))),
                Cell(fmt_dt(g(t, "occurred_at"), zone, ms=True, date_part=show_date), sub=flag),
                Cell(humanize(g(t, "event_name")), sub=txt(g(t, "reference"), ""), sub_mono=True),
                badge(g(t, "observed_or_derived")),
                Cell(txt(g(t, "reason_or_outcome_code")), mono=True, tiny=True),
                badge(g(t, "integrity_status")),
            )
        )
    stages = ", ".join(str(s) for s in (g(e, "sine_stages_exposed", ()) or ())) or DASH
    responses = ", ".join(humanize(r) for r in (g(e, "sine_responses", ()) or ())) or DASH
    issues = tuple(g(e, "integrity_issues", ()) or ())
    facts = (
        ("Started", fmt_dt(g(e, "started_at"), zone)),
        ("Trigger fired", fmt_dt(g(e, "trigger_fired_at"), zone)),
        ("Application", humanize(g(e, "application"))),
        ("Session", fmt_int(g(e, "session_id"))),
        ("Return intent", fmt_seconds(g(e, "return_intent_latency_seconds"))),
        ("Verified return", fmt_seconds(g(e, "verified_return_latency_seconds"))),
        ("Stable recovery", fmt_seconds(g(e, "stable_recovery_latency_seconds"))),
        ("Final outcome", humanize(g(e, "final_outcome")) if g(e, "final_outcome") else "Not closed"),
        ("Recovery attempts", fmt_int(g(e, "recovery_attempt_count"))),
        ("Relapses", fmt_int(g(e, "relapse_count"))),
        ("SINE stages exposed", stages),
        ("SINE responses", responses),
    )
    captions = []
    if issues:
        captions.append(f"{len(issues):,} integrity finding(s) recorded for this episode; see the Evidence Integrity appendix.")
    if outside:
        captions.append(f"{outside:,} event(s) of this episode fall outside the selected dates and are marked.")
    return Record(
        title=txt(g(e, "short_display_id")),
        badges=(badge(g(e, "episode_status")), badge(g(e, "integrity_status"), text=f"Integrity {txt(g(e, 'integrity_status')).title()}")),
        facts=facts,
        ids=(("Episode", txt(g(e, "episode_id"))), ("Candidate", txt(g(e, "candidate_uid")))),
        table=_table(
            ("#", "Time", "Event", "Basis", "Reason / outcome code", "Integrity"),
            rows,
            (0.45, 2.2, 2.9, 1.0, 1.8, 1.0),
            empty="No timeline events were recorded for this episode.",
            align=("r", "l", "l", "l", "l", "l"),
            dense=True,
        ),
        caption=" ".join(captions),
    )


# --------------------------------------------------------------------------
# COSINE
# --------------------------------------------------------------------------


def _payload_text(payload: object) -> str:
    if not isinstance(payload, Mapping) or not payload:
        return ""
    return "; ".join(f"{k}: {txt(v)}" for k, v in payload.items())


def _cosine_event_row(ev: object, period: Period, zone) -> tuple[Cell, ...]:
    detail = _payload_text(g(ev, "payload_display"))
    title = txt(g(ev, "content_title"), "")
    parts = []
    if title:
        parts.append(f"Title: {title}")
    if detail:
        parts.append(detail)
    withheld = g(ev, "withheld_payload_field_count")
    if isinstance(withheld, int) and withheld > 0:
        parts.append(f"{withheld} payload field(s) withheld by the source")
    utc = txt(g(ev, "occurred_at_utc"), "")
    flag = _outside_flag(period, g(ev, "occurred_at_utc"))
    return (
        Cell(fmt_int(g(ev, "sequence"))),
        Cell(fmt_dt(g(ev, "occurred_at_utc"), zone, ms=True), sub=(utc + (f"  ·  {flag}" if flag else "")), sub_mono=True),
        Cell(humanize(g(ev, "event_name")), sub=txt(g(ev, "event_name"), ""), sub_mono=True),
        badge(g(ev, "event_class")),
        Cell(txt(g(ev, "platform_label"))),
        Cell(" · ".join(parts) if parts else DASH, small=True),
    )


def _cosine_section(projection: object, period: Period, zone) -> tuple[Section, str, tuple[str, ...]]:
    key = "cosine"
    state, detail = organ_state(key, projection)
    subtitle = SECTION_SUBTITLES[key]
    if state == UNAVAILABLE_STATE:
        return Section(key, SECTION_TITLES[key], subtitle, tuple(_unavailable_blocks(detail))), state, ()
    selection = select_by_start(g(projection, "episodes", ()) or (), lambda e: g(e, "started_at_utc"), period)
    if not selection.inside:
        return Section(key, SECTION_TITLES[key], subtitle, tuple(_empty_blocks(period.label, "COSINE episode", unplaceable=selection.unplaceable))), NO_DATA_STATE, ()
    episodes = selection.inside
    events_total = sum(len(g(e, "events", ()) or ()) for e in episodes)
    blocks: list[Block] = [
        CardRow(
            (
                Card("COSINE episodes", fmt_int(len(episodes)), "started in the selected period"),
                Card("Recorded events", fmt_int(events_total), "in these episodes"),
                Card("Closed", fmt_int(sum(1 for e in episodes if g(e, "is_closed"))), "closed in the source"),
                Card("Platform switches", fmt_int(sum(int(g(e, "hopper_count") or 0) for e in episodes)), "recorded"),
            )
        ),
        Note("Events are recorded timestamps; no continuous viewing duration is inferred from them. Events outside the selected dates are marked."),
        _grouped("Recorded closure outcome", "Outcome", [g(e, "closure_outcome") for e in episodes]),
    ]
    structural = tuple(g(projection, "structural_issues", ()) or ())
    if structural:
        blocks.append(Note("The COSINE source reported structural issues that cannot be attributed to a period; see the source status.", "warn"))
    index_rows = [
        (
            Cell(str(i)),
            Cell(fmt_dt(g(e, "started_at_utc"), zone), sub=txt(g(e, "started_at_utc"), ""), sub_mono=True),
            txt(g(e, "starting_platform_label")),
            fmt_int(g(e, "event_count")),
            badge(g(e, "closure_outcome")) if g(e, "closure_outcome") else Cell("Not closed", tone="warn"),
            Cell(txt(g(e, "closure_reason")), mono=True, tiny=True),
            Cell(txt(g(e, "user_choice")), mono=True, tiny=True),
            fmt_int(g(e, "chosen_break_minutes")),
        )
        for i, e in enumerate(episodes, 1)
    ]
    blocks.append(
        _table(
            ("#", "Started", "Platform", "Events", "Outcome", "Closure reason", "Choice", "Break min"),
            index_rows,
            (0.6, 2.9, 1.25, 0.85, 1.9, 1.9, 1.6, 0.85),
            title="Episode index",
            note="Times are local; the recorded UTC instant is shown beneath.",
            align=("r", "l", "l", "r", "l", "l", "l", "r"),
        )
    )
    blocks.append(Heading("Episode records", "Recorded events in sequence, with platform and recorded choices"))
    for i, e in enumerate(episodes, 1):
        outside = 0
        rows = []
        for ev in g(e, "events", ()) or ():
            outside += period.classify(g(ev, "occurred_at_utc")) != "in"
            rows.append(_cosine_event_row(ev, period, zone))
        facts = (
            ("Started", fmt_dt(g(e, "started_at_utc"), zone)),
            ("Ended", fmt_dt(g(e, "ended_at_utc"), zone) if g(e, "ended_at_utc") else "Not closed"),
            ("Starting platform", txt(g(e, "starting_platform_label"))),
            ("Events", fmt_int(g(e, "event_count"))),
            ("Recorded choice", txt(g(e, "user_choice"))),
            ("Chosen break (min)", fmt_int(g(e, "chosen_break_minutes"))),
            ("Platform switches", fmt_int(g(e, "hopper_count"))),
            ("Closure", f"{txt(g(e, 'closure_outcome'), 'Not closed')} / {txt(g(e, 'closure_reason'))}"),
            ("Parent session", fmt_int(g(e, "parent_session_id"))),
            ("Hold context", "Yes" if g(e, "hold_context") else "No"),
        )
        blocks.append(
            Record(
                title=f"Episode {i} · {fmt_dt(g(e, 'started_at_utc'), zone)}",
                badges=(badge(g(e, "closure_outcome")) if g(e, "closure_outcome") else Cell("Not closed", tone="warn"),),
                facts=facts,
                ids=(("COSINE session", txt(g(e, "cosine_session_id"))),),
                table=_table(
                    ("#", "Time (local / UTC)", "Event", "Class", "Platform", "Recorded details"),
                    rows,
                    (0.45, 2.2, 2.6, 1.1, 1.05, 2.1),
                    empty="No events were recorded for this episode.",
                    align=("r", "l", "l", "l", "l", "l"),
                    dense=True,
                ),
                caption=(f"{outside:,} event(s) of this episode fall outside the selected dates and are marked." if outside else ""),
            )
        )
    if selection.unplaceable:
        blocks.append(Note(f"{selection.unplaceable:,} COSINE episode(s) have no readable recorded start time and cannot be assigned to any period; they are not included.", "warn"))
    return (
        Section(key, SECTION_TITLES[key], subtitle, tuple(blocks)),
        AVAILABLE_STATE,
        tuple(f"{txt(g(e, 'cosine_session_id'))}#{txt(g(e, 'generation'))}" for e in episodes),
    )


# --------------------------------------------------------------------------
# MINE
# --------------------------------------------------------------------------

_MINE_CHOICES: Final = {"I_WILL_COME_BACK": "I will come back", "ITS_IMPORTANT": "It's important"}


def _mine_choice(value: object) -> str:
    if value is None or txt(value) == DASH:
        return "No choice recorded"
    return _MINE_CHOICES.get(str(enum_text(value)), humanize(value))


def _mine_section(projection: object, period: Period, zone) -> tuple[Section, str, tuple[str, ...]]:
    key = "mine"
    state, detail = organ_state(key, projection)
    subtitle = SECTION_SUBTITLES[key]
    if state == UNAVAILABLE_STATE:
        return Section(key, SECTION_TITLES[key], subtitle, tuple(_unavailable_blocks(detail))), state, ()
    selection = select_by_start(g(projection, "episodes", ()) or (), lambda e: g(e, "started_at_utc"), period)
    if not selection.inside:
        return Section(key, SECTION_TITLES[key], subtitle, tuple(_empty_blocks(period.label, "MINE episode", unplaceable=selection.unplaceable))), NO_DATA_STATE, ()
    episodes = selection.inside
    blocks: list[Block] = [
        CardRow(
            (
                Card("MINE episodes", fmt_int(len(episodes)), "started in the selected period"),
                Card("Closed", fmt_int(sum(1 for e in episodes if g(e, "is_closed"))), "closed in the source"),
                Card("Return verified", fmt_int(sum(1 for e in episodes if g(e, "return_verified") is True)), "as recorded by the source"),
                Card("Choice recorded", fmt_int(sum(1 for e in episodes if g(e, "branch"))), "MINE-1 choices"),
            )
        ),
        Note("A recorded MINE-1 choice (“I will come back” or “It's important”) is a decision, not a verified return. Return verification and closure are shown as the source records them."),
    ]
    choice_counts = Counter((_mine_choice(g(e, "branch")), humanize(g(e, "closure_outcome")) if g(e, "closure_outcome") else "No documented outcome") for e in episodes)
    blocks.append(
        _table(
            ("MINE-1 choice", "Documented outcome", "Episodes"),
            [(c, o, fmt_int(n)) for (c, o), n in sorted(choice_counts.items())],
            (2.4, 3.0, 1.0),
            title="Choices and documented outcomes",
            note="Each row groups the episodes in this report by their recorded choice and recorded closure outcome.",
            align=("l", "l", "r"),
        )
    )
    index_rows = [
        (
            Cell(txt(g(e, "display_episode_id")), bold=True),
            Cell(fmt_dt(g(e, "started_at_utc"), zone), sub=txt(g(e, "started_at_utc"), ""), sub_mono=True),
            txt(g(e, "starting_platform_label")),
            _mine_choice(g(e, "branch")),
            badge(g(e, "closure_outcome")) if g(e, "closure_outcome") else Cell("Not closed", tone="warn"),
            Cell("Yes" if g(e, "return_verified") else "No", tone="ok" if g(e, "return_verified") else "muted"),
            fmt_int(g(e, "event_count")),
        )
        for e in episodes
    ]
    blocks.append(
        _table(
            ("Episode", "Started", "Platform", "MINE-1 choice", "Closure outcome", "Return verified", "Events"),
            index_rows,
            (2.3, 2.9, 1.2, 1.6, 2.2, 1.0, 0.9),
            title="Episode index",
            note="Times are local; the recorded UTC instant is shown beneath.",
            align=("l", "l", "l", "l", "l", "l", "r"),
        )
    )
    blocks.append(Heading("Episode records", "Recorded events in sequence. Events outside the selected dates are marked."))
    for e in episodes:
        rows = []
        outside = 0
        for ev in g(e, "events", ()) or ():
            flag = _outside_flag(period, g(ev, "occurred_at_utc"))
            outside += bool(flag)
            facts_text = _payload_text(g(ev, "payload_facts"))
            elapsed = g(ev, "elapsed_from_previous_seconds")
            parts = [p for p in (facts_text, f"+{elapsed:,.2f} s since previous" if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) else "") if p]
            withheld = g(ev, "withheld_payload_field_count")
            if isinstance(withheld, int) and withheld > 0:
                parts.append(f"{withheld} payload field(s) withheld by the source")
            utc = txt(g(ev, "occurred_at_utc"), "")
            rows.append(
                (
                    Cell(fmt_int(g(ev, "sequence"))),
                    Cell(fmt_dt(g(ev, "occurred_at_utc"), zone, ms=True), sub=(utc + (f"  ·  {flag}" if flag else "")), sub_mono=True),
                    Cell(humanize(g(ev, "event_name")), sub=txt(g(ev, "event_name"), ""), sub_mono=True),
                    badge(g(ev, "event_class")),
                    Cell(txt(g(ev, "platform_label"))),
                    Cell(" · ".join(parts) if parts else DASH, small=True),
                )
            )
        dwell = tuple(g(e, "dwell_records", ()) or ())
        extra: tuple[Table, ...] = ()
        if dwell:
            extra = (
                _table(
                    ("Segment", "Platform", "Dwell", "Recorded band", "Completed"),
                    [(fmt_int(g(d, "segment_order")), txt(g(d, "platform_label")), fmt_seconds(g(d, "dwell_seconds")), txt(g(d, "mbi_band")), Cell(fmt_dt(g(d, "completed_at_utc"), zone))) for d in dwell],
                    (0.8, 1.6, 1.2, 1.4, 2.6),
                    title="Recorded messaging dwell segments",
                    dense=True,
                    align=("r", "l", "r", "l", "l"),
                ),
            )
        facts = (
            ("Started", fmt_dt(g(e, "started_at_utc"), zone)),
            ("Ended", fmt_dt(g(e, "ended_at_utc"), zone) if g(e, "ended_at_utc") else "Not closed"),
            ("Starting platform", txt(g(e, "starting_platform_label"))),
            ("MINE-1 choice", _mine_choice(g(e, "branch"))),
            ("Important duration (min)", fmt_int(g(e, "important_duration_minutes"))),
            ("Closure outcome", txt(g(e, "closure_outcome"), "Not closed")),
            ("Closure reason", txt(g(e, "closure_reason"))),
            ("Return verified", "Yes" if g(e, "return_verified") else "No"),
            ("Closure confirmed", "Yes" if g(e, "closure_confirmed") else "No"),
            ("Session / generation", f"{fmt_int(g(e, 'session_id'))} / {fmt_int(g(e, 'generation'))}"),
            ("Events", fmt_int(g(e, "event_count"))),
            ("Messenger hops", fmt_int(len(tuple(g(e, "messenger_hops", ()) or ())))),
        )
        blocks.append(
            Record(
                title=txt(g(e, "display_episode_id")),
                badges=(badge(g(e, "closure_outcome")) if g(e, "closure_outcome") else Cell("Not closed", tone="warn"),),
                facts=facts,
                ids=(("MINE episode", txt(g(e, "mine_episode_id"))),),
                table=_table(
                    ("#", "Time (local / UTC)", "Event", "Class", "Platform", "Recorded details"),
                    rows,
                    (0.45, 2.2, 2.6, 1.1, 1.05, 2.1),
                    empty="No events were recorded for this episode.",
                    align=("r", "l", "l", "l", "l", "l"),
                    dense=True,
                ),
                caption=(f"{outside:,} event(s) of this episode fall outside the selected dates and are marked." if outside else ""),
                extra=extra,
            )
        )
    blocks.append(Note("Candidate-only records that never became a formal MINE episode are not episodes and are not listed."))
    if selection.unplaceable:
        blocks.append(Note(f"{selection.unplaceable:,} MINE episode(s) have no readable recorded start time and cannot be assigned to any period; they are not included.", "warn"))
    return (
        Section(key, SECTION_TITLES[key], subtitle, tuple(blocks)),
        AVAILABLE_STATE,
        tuple(txt(g(e, "mine_episode_id")) for e in episodes),
    )


# --------------------------------------------------------------------------
# STUDY MODE (recorded unit: the study block)
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _StudySnapshot:
    recorded_at: str  # created_at_utc of the durable row
    action: str
    payload: Mapping
    session_id: object
    source_id: str


def _study_blocks(records) -> tuple[dict[tuple[object, str, object], list[_StudySnapshot]], int]:
    """Group durable Study Mode snapshots by study block (shutdown markers with no block are skipped)."""

    blocks: dict[tuple[object, str, object], list[_StudySnapshot]] = {}
    malformed = 0
    for row in records:
        try:
            payload = json.loads(str(g(row, "payload_json")))
            if not isinstance(payload, dict):
                raise ValueError
        except (TypeError, ValueError):
            malformed += 1
            continue
        block_id = txt(payload.get("block_id"), "")
        if not block_id:
            continue
        generation = payload.get("generation", 1)
        if type(generation) is not int or generation <= 0:
            malformed += 1
            continue
        identity = (g(row, "session_id"), block_id, generation)
        blocks.setdefault(identity, []).append(
            _StudySnapshot(txt(g(row, "created_at_utc"), ""), txt(g(row, "kind"), ""), payload, g(row, "session_id"), txt(g(row, "source_event_id"), ""))
        )
    for snapshots in blocks.values():
        snapshots.sort(key=lambda s: (s.recorded_at, s.source_id))
    return blocks, malformed


def _study_start(snapshots: list[_StudySnapshot]):
    for s in snapshots:
        value = s.payload.get("started_wall_time_utc")
        if isinstance(value, str) and value.strip():
            return value
    return None


def _fmt_planned(seconds: object) -> str:
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or seconds <= 0:
        return DASH
    minutes, rest = divmod(int(seconds), 60)
    return f"{minutes} min" + (f" {rest} s" if rest else "") + f" ({int(seconds):,} s)"


def _study_section(records, error: str | None, period: Period, zone, family=None) -> tuple[Section, str, tuple[str, ...]]:
    key = "study-mode"
    subtitle = SECTION_SUBTITLES[key]
    if records is None:
        detail = "Study Mode evidence could not be read." if error else "Study Mode evidence was not supplied to the report."
        return Section(key, SECTION_TITLES[key], subtitle, tuple(_unavailable_blocks(detail))), UNAVAILABLE_STATE, ()
    blocks_by_id, malformed = _study_blocks(records)
    selection = select_by_start(blocks_by_id.items(), lambda item: _study_start(item[1]), period)
    unit_note = Note(
        "Recorded unit: the study block. A block belongs to the period in which its recorded start time falls. Blocks that were prepared but never started have no start time and are not assigned to a period. "
        "Shutdown markers that carry no study block are not study blocks and are not listed."
    )
    if not selection.inside:
        blocks: list[Block] = _empty_blocks(period.label, "study block", unplaceable=selection.unplaceable)
        blocks.append(unit_note)
        if malformed:
            blocks.append(Note(f"{malformed:,} durable Study Mode row(s) could not be read and are not part of any block.", "warn"))
        return Section(key, SECTION_TITLES[key], subtitle, tuple(blocks)), NO_DATA_STATE, ()
    chosen = sorted(selection.inside, key=lambda item: (_study_start(item[1]) or "", str(item[0])))
    total_snaps = sum(len(s) for _b, s in chosen)
    completed = sum(1 for _b, s in chosen if any(x.action.upper() == "COMPLETE" for x in s))
    blocks = [
        CardRow(
            (
                Card("Study blocks", fmt_int(len(chosen)), "started in the selected period"),
                Card("Snapshots", fmt_int(total_snaps), "recorded for these blocks"),
                Card("COMPLETE recorded", fmt_int(completed), "blocks with a COMPLETE snapshot"),
                Card("Recorded unit", "Study block", "as recorded by Study Mode"),
            )
        ),
        unit_note,
        _grouped("Last recorded state", "State", [(s[-1].payload.get("state")) for _b, s in chosen], note="Grouped from each block's final recorded snapshot.", unit="Blocks"),
    ]
    rows = []
    for identity, snaps in chosen:
        block_id = identity[1]
        last = snaps[-1].payload
        rows.append(
            (
                Cell(fmt_dt(_study_start(snaps), zone), sub=txt(_study_start(snaps), ""), sub_mono=True),
                Cell(txt(last.get("subject")), bold=True, sub=txt(last.get("task"), "")),
                _fmt_planned(last.get("planned_seconds")),
                fmt_seconds(last.get("elapsed_seconds")),
                badge(last.get("state")),
                fmt_int(len(snaps)),
            )
        )
    blocks.append(
        _table(
            ("Started", "Subject / task", "Planned", "Elapsed", "Last state", "Snapshots"),
            rows,
            (3.0, 3.4, 1.6, 1.1, 1.3, 1.1),
            title="Study block index",
            note="Subject and task are the text recorded by the user for each block.",
            align=("l", "l", "l", "r", "l", "r"),
        )
    )
    blocks.append(Heading("Study block records", "Durable snapshots in recorded order. Snapshots recorded outside the selected dates are marked."))
    for identity, snaps in chosen:
        block_id = identity[1]
        last = snaps[-1].payload
        event_rows = []
        outside = 0
        for i, s in enumerate(snaps, 1):
            flag = _outside_flag(period, s.recorded_at)
            outside += bool(flag)
            event_rows.append(
                (
                    Cell(str(i)),
                    Cell(fmt_dt(s.recorded_at, zone, ms=True), sub=(s.recorded_at + (f"  ·  {flag}" if flag else "")), sub_mono=True),
                    Cell(humanize(s.action), sub=s.action, sub_mono=True),
                    badge(s.payload.get("state")),
                    fmt_seconds(s.payload.get("elapsed_seconds")),
                    Cell(txt(s.payload.get("last_action")), small=True),
                )
            )
        sessions = sorted({txt(s.session_id) for s in snaps})
        facts = (
            ("Started", fmt_dt(_study_start(snaps), zone)),
            ("Completed", fmt_dt(last.get("completed_wall_time_utc"), zone) if txt(last.get("completed_wall_time_utc"), "") else "Not recorded"),
            ("Subject", txt(last.get("subject"))),
            ("Task", txt(last.get("task"))),
            ("Planned", _fmt_planned(last.get("planned_seconds"))),
            ("Elapsed (last snapshot)", fmt_seconds(last.get("elapsed_seconds"))),
            ("Last state", txt(last.get("state"))),
            ("Completion reason", txt(last.get("completion_reason"))),
            ("Session(s)", ", ".join(sessions)),
            ("Snapshots", fmt_int(len(snaps))),
            ("Schema", txt(last.get("schema_version"))),
        )
        blocks.append(
            Record(
                title=f"Study block · {fmt_dt(_study_start(snaps), zone)}",
                badges=(badge(last.get("state")),),
                facts=facts,
                ids=(("Study block", block_id),),
                table=_table(
                    ("#", "Recorded (local / UTC)", "Action", "State", "Elapsed", "Recorded note"),
                    event_rows,
                    (0.45, 2.3, 2.0, 1.2, 1.1, 2.6),
                    empty="No snapshots were recorded for this block.",
                    align=("r", "l", "l", "l", "r", "l"),
                    dense=True,
                ),
                caption=(f"{outside:,} snapshot(s) of this block were recorded outside the selected dates and are marked." if outside else ""),
            )
        )
    if family is not None:
        blocks.extend(_study_resource_blocks(family, {identity for identity, _snaps in chosen}))
    if selection.unplaceable:
        blocks.append(Note(f"{selection.unplaceable:,} Study block(s) have no readable start time and are unplaceable.", "warn"))
    if malformed:
        blocks.append(Note(f"{malformed:,} durable Study Mode row(s) could not be read and are not part of any block.", "warn"))
    return Section(key, SECTION_TITLES[key], subtitle, tuple(blocks)), AVAILABLE_STATE, tuple(identity[1] for identity, _s in chosen)


def _study_resource_blocks(family, chosen: set[tuple]) -> list[Block]:
    """Show only validated observations belonging to selected Study blocks."""
    if g(family, "errors", {}).get("study"):
        return [Note("Additional Study resource evidence is unavailable; timer records above remain separate.", "warn")]
    resources, visits, jumps = [], [], []
    for _sid, study in g(family, "studies", ()):
        def selected(row):
            return (row.get("session_id"), row.get("study_block_id"), row.get("study_generation")) in chosen

        resources.extend(row for row in study.get("resources", ()) if selected(row))
        visits.extend(row for row in study.get("visits", ()) if selected(row))
        jumps.extend(item for item in study.get("jumps", ()) if selected(item["visit"]))
    blocks: list[Block] = [Heading("Recorded Study resource evidence",
        "Observed spans only. Gaps are not counted as focused time or silently joined.")]
    blocks.append(_table(("Role", "Resource", "Qualified (UTC)"),
        [(r.get("role"), r.get("title", "Title not recorded"), r.get("qualified_at_utc")) for r in resources],
        (1.3, 4.6, 3.0), title="PRIMARY / LATER qualified resources",
        empty="No qualified Study resource was recorded for the selected blocks."))
    blocks.append(_table(("Resource", "Supported foreground", "Classification", "Confirmation"),
        [(v.get("title", "Title not recorded"), fmt_seconds(v.get("supported_duration_ns", 0) / 1e9),
          v.get("effective", {}).get("classification", "Not recorded"),
          v.get("effective", {}).get("user_confirmation", "Not recorded")) for v in visits],
        (3.2, 1.8, 2.2, 2.0), title="Study visits and observation evidence",
        note="Duration is supported only within each validated visit. Classification and confirmation come from that visit's own evidence.",
        empty="No validated Study visit was recorded for the selected blocks."))
    jump_rows = []
    for left, right in zip(jumps, jumps[1:]):
        if (left["visit"].get("session_id"), left["visit"].get("study_block_id"),
                left["visit"].get("study_generation")) != (
                right["visit"].get("session_id"), right["visit"].get("study_block_id"),
                right["visit"].get("study_generation")):
            continue
        jump_rows.append((left["visit"].get("title", "Title not recorded"),
                          left.get("connector") or "Evidence gap",
                          right["visit"].get("title", "Title not recorded")))
    if jump_rows:
        blocks.append(_table(("From visit", "Recorded connector", "To visit"), jump_rows,
            (3.0, 2.7, 3.0), title="Study Jump",
            note="A direct jump is shown only when the exact observed boundary chain supports it."))
    else:
        blocks.append(Note("Study Jump: no validated connector was recorded for the selected blocks."))
    return blocks


def _secant_section(family, error: str | None, period: Period, zone) -> tuple[Section, str, tuple[str, ...]]:
    key = "secant"
    if family is None or error or g(family, "errors", {}).get(key):
        detail = "SECANT history could not be read or validated."
        return Section(key, "SECANT", SECTION_SUBTITLES[key], tuple(_unavailable_blocks(detail))), UNAVAILABLE_STATE, ()
    selection = select_by_start(g(family, "secant", ()), lambda item: item.get("start_utc"), period)
    if not selection.inside:
        return Section(key, "SECANT", SECTION_SUBTITLES[key],
                       tuple(_empty_blocks(period.label, "SECANT episode", unplaceable=selection.unplaceable))), NO_DATA_STATE, ()
    chosen = sorted(selection.inside, key=lambda item: (item["start_utc"], item["alias"]))
    counts = Counter(row["highest_stage"] for row in chosen)
    events = tuple(event for row in chosen for event in row["events"])
    count_event = lambda name: sum(e["event_name"] == name for e in events)
    blocks: list[Block] = [
        CardRow((Card("Founded episodes", fmt_int(len(chosen)), "started in the selected period"),
                 Card("Recovered episodes", fmt_int(sum(row["recovered"] for row in chosen)), "validated recovered closure"),
                 Card("Open / incomplete", fmt_int(sum(not row["closed"] for row in chosen)), "not a failed recovery"))),
        Note("SECANT verified-return events, recovered episodes and COSECANT return confirmations are distinct evidence units."),
        _table(("Highest displayed stage", "Episodes"),
               [(f"SECANT-{stage}", counts[stage]) for stage in (1, 2, 3)], (3.2, 1.2),
               title="Exclusive stage distribution", note="Each validated episode is counted once, at its highest displayed stage."),
        _table(("Recorded event", "Events"),
               [(label, count_event(name)) for name, label in (
                   ("SECANT_ACTION_INTENT", "Action intents"),
                   ("SECANT_RETURN_STARTED", "Return attempts"),
                   ("SECANT_RETURN_VERIFIED", "Verified-return events"),
                   ("SECANT_RECOVERY_INTERRUPTED", "Recovery interruptions"))],
               (3.2, 1.2), title="Recovery event counts"),
        _grouped("Episode closure reasons", "Reason",
                 [row["terminal_reason"] for row in chosen], unit="Episodes"),
        Heading("SECANT episode records", "Native identities are not used as display aliases."),
    ]
    for row in chosen:
        founded_ns = row["events"][0]["occurred_monotonic_ns"]
        start = parse_instant(row["start_utc"])
        event_rows, outside = [], 0
        for index, event in enumerate(row["events"], 1):
            at = start + timedelta(microseconds=(event["occurred_monotonic_ns"] - founded_ns) // 1000)
            at_iso = at.isoformat()
            flag = _outside_flag(period, at_iso)
            outside += bool(flag)
            event_rows.append((str(index), Cell(fmt_dt(at_iso, zone), sub=flag),
                               event["event_name"], event["stage"] or DASH,
                               event.get("reason") or DASH))
        alias = row["alias"] if row["alias"] != "Unavailable" else "Alias unavailable"
        blocks.append(Record(
            title=f"{alias} · {fmt_dt(row['start_utc'], zone)}",
            badges=(badge("Recovered" if row["recovered"] else "Closed" if row["closed"] else "Open / incomplete"),),
            facts=(("Study context", txt(row["context_id"])),
                   ("Highest displayed", f"SECANT-{row['highest_stage']}"),
                   ("Terminal reason", txt(row["terminal_reason"])),
                   ("Founding source", txt(row["source_kind"])),
                   ("Recorded source caption", txt(row["source_caption"])),
                   ("Verified-return events", fmt_int(sum(e["event_name"] == "SECANT_RETURN_VERIFIED" for e in row["events"])))),
            ids=(("Display alias", alias),),
            table=_table(("#", "Event time", "Recorded fact", "Stage", "Reason"), event_rows,
                         (0.5, 2.1, 3.0, 0.8, 2.0), dense=True),
            caption=f"{outside} event(s) outside the selected dates are marked." if outside else ""))
    if selection.unplaceable:
        blocks.append(Note(f"{selection.unplaceable} SECANT episode(s) have no readable founding time.", "warn"))
    return Section(key, "SECANT", SECTION_SUBTITLES[key], tuple(blocks)), AVAILABLE_STATE, tuple(row["alias"] for row in chosen)


def _cosecant_section(family, error: str | None, period: Period, zone) -> tuple[Section, str, tuple[str, ...]]:
    key = "cosecant"
    if family is None or error or g(family, "errors", {}).get(key):
        return Section(key, "COSECANT", SECTION_SUBTITLES[key],
                       tuple(_unavailable_blocks("COSECANT history could not be read or validated."))), UNAVAILABLE_STATE, ()
    selection = select_by_start(g(family, "cosecant", ()), lambda item: item.get("start_utc"), period)
    if not selection.inside:
        return Section(key, "COSECANT", SECTION_SUBTITLES[key],
                       tuple(_empty_blocks(period.label, "COSECANT break", unplaceable=selection.unplaceable))), NO_DATA_STATE, ()
    chosen = sorted(selection.inside, key=lambda item: (item["start_utc"], item["alias"]))
    milestone_names = ("BREAK_STARTED", "BREAK_COMPLETE", "FINAL_LOCKED", "RETURN_INTENT_RECORDED",
                       "RETURN_CONFIRMATION_STARTED", "RETURN_CONFIRMED")
    blocks: list[Block] = [
        CardRow((Card("Breaks started", fmt_int(len(chosen)), "recorded starts in the selected period"),
                 Card("Allowance complete", fmt_int(sum(row["complete"] for row in chosen)), "deadline state reached"),
                 Card("Confirmed returns", fmt_int(sum(row["confirmed"] for row in chosen)), "same-break resource proof"),
                 Card("Cancelled breaks", fmt_int(sum(row["cancelled"] for row in chosen)), "recorded cancellation"))),
        Note("No return confirmation recorded is not a failed return. Reminder stages reached do not prove popup paint."),
        _table(("Recorded milestone", "Breaks reaching it"),
               [(name.replace("_", " ").title(), sum(any(e["kind"] == name for e in row["events"]) for row in chosen))
                for name in milestone_names], (3.5, 1.3), title="COSECANT recorded progression"),
        Heading("COSECANT break records", "Each break retains its own target and return evidence."),
    ]
    for row in chosen:
        event_rows, outside = [], 0
        for index, event in enumerate(row["events"], 1):
            at = event["payload"].get("occurred_wall_time_utc")
            flag = _outside_flag(period, at)
            outside += bool(flag)
            event_rows.append((str(index), Cell(fmt_dt(at, zone), sub=flag),
                               event["kind"],
                               "Recorded" if event["kind"] == "RETURN_CONFIRMED" and event["payload"].get("evidence_token") else DASH))
        alias = row["alias"] if row["alias"] != "Unavailable" else "Alias unavailable"
        blocks.append(Record(
            title=f"{alias} · {fmt_dt(row['start_utc'], zone)}",
            badges=(badge("Return confirmed" if row["confirmed"] else "Cancelled" if row["cancelled"] else "Open / no confirmation recorded"),),
            facts=(("Study block", txt(row["study_block_id"])),
                   ("Selected allowance", _fmt_planned(row["allowance"])),
                   ("Return target", txt(row["target_kind"])),
                   ("Recorded target caption", txt(row["target_caption"])),
                   ("Allowance deadline", "Reached" if row["complete"] else "Not recorded"),
                   ("Return confirmation", "Recorded with evidence" if row["confirmed"] else "Not recorded")),
            ids=(("Display alias", alias),),
            table=_table(("#", "Event time", "Recorded fact", "Return proof"), event_rows,
                         (0.5, 2.2, 3.5, 1.7), dense=True),
            caption=f"{outside} event(s) outside the selected dates are marked." if outside else ""))
    if selection.unplaceable:
        blocks.append(Note(f"{selection.unplaceable} COSECANT break(s) have no readable start time.", "warn"))
    return Section(key, "COSECANT", SECTION_SUBTITLES[key], tuple(blocks)), AVAILABLE_STATE, tuple(row["alias"] for row in chosen)


# --------------------------------------------------------------------------
# Evidence Integrity (only findings attributable to the selected episodes)
# --------------------------------------------------------------------------


def _integrity_sections(projection: object, episodes: tuple, zone) -> list[Section]:
    if not episodes or projection is None:
        return []
    selected_ids = {txt(g(e, "episode_id"), "") for e in episodes}
    seen: set[tuple[str, str, str]] = set()
    findings: list[tuple[str, str, str, str, str]] = []
    sources = list(g(projection, "integrity_issues", ()) or ())
    for e in episodes:
        sources += list(g(e, "integrity_issues", ()) or ())
    for i in sources:
        ep = txt(g(i, "episode_id"), "")
        if ep not in selected_ids:
            continue
        key = (txt(g(i, "code")), ep, txt(g(i, "event_id"), ""))
        if key in seen:
            continue
        seen.add(key)
        findings.append((txt(g(i, "severity")), txt(g(i, "code")), ep, txt(g(i, "event_id"), ""), txt(g(i, "detail"), "")))
    findings.sort(key=lambda f: (f[0], f[1], f[2], f[3]))
    exclusions = []
    for x in g(g(projection, "metadata"), "exclusions", ()) or ():
        ep = txt(g(x, "episode_id"), "")
        if ep in selected_ids:
            exclusions.append((txt(g(x, "metric")), txt(g(x, "reason")), ep, txt(g(x, "detail"), "")))
    if not findings and not exclusions:
        return []

    short = {txt(g(e, "episode_id"), ""): txt(g(e, "short_display_id"), "") for e in episodes}
    groups: dict[tuple[str, str], list[tuple]] = {}
    for f in findings:
        groups.setdefault((f[0], f[1]), []).append(f)
    blocks: list[Block] = [
        CardRow(
            (
                Card("Findings", fmt_int(len(findings)), "attributed to the selected episodes", "bad" if findings else ""),
                Card("Distinct codes", fmt_int(len(groups)), "severity and code pairs"),
                Card("Affected episodes", fmt_int(len({f[2] for f in findings})), "of the selected episodes"),
                Card("Excluded episodes", fmt_int(len({x[2] for x in exclusions})), "excluded from rates", "warn" if exclusions else ""),
            )
        ),
        Note(
            "Only findings that name one of the episodes in this report are included, with their recorded codes and identities unchanged. "
            "Findings that cannot be attributed to a selected episode (global findings) are not part of this report and are not counted as belonging to the period."
        ),
    ]
    summary_rows = []
    for (sev, code), items in sorted(groups.items()):
        details = {r[4] for r in items}
        summary_rows.append(
            (
                badge(sev),
                Cell(code, mono=True, bold=True),
                Cell(fmt_int(len(items))),
                Cell(fmt_int(len({r[2] for r in items}))),
                Cell(fmt_int(len({r[3] for r in items if r[3]}))),
                Cell(next(iter(details)) if len(details) == 1 else f"{len(details)} distinct descriptions; see appendix", small=True),
            )
        )
    blocks.append(
        _table(
            ("Severity", "Recorded code", "Occurrences", "Episodes", "Events", "Recorded description"),
            summary_rows,
            (0.9, 2.5, 1.0, 0.9, 0.9, 3.3),
            title="Findings by code and severity",
            empty="No findings name a selected episode.",
            align=("l", "l", "r", "r", "r", "l"),
        )
    )
    if exclusions:
        counts = Counter((x[0], x[1]) for x in exclusions)
        blocks.append(
            _table(
                ("Excluded from", "Reason", "Episodes"),
                [(Cell(m, mono=True), Cell(r, mono=True), fmt_int(n)) for (m, r), n in sorted(counts.items())],
                (2.4, 2.6, 1.0),
                title="Exclusions",
                note="Excluded episodes are not counted in any rate; each is listed in Appendix B.",
                align=("l", "l", "r"),
            )
        )
    sections = [Section("integrity", INTEGRITY_TITLE, "Findings attributed to the selected episodes", tuple(blocks))]
    if findings:
        counter = 0
        app: list[Block] = [Note("Every finding attributed to the selected episodes is reproduced unchanged: severity, code, description, episode and event identity.")]
        for (sev, code), items in sorted(groups.items()):
            rows = []
            for r in items:
                counter += 1
                s = short.get(r[2], "")
                rows.append((Cell(str(counter)), Cell(s or DASH, bold=bool(s), sub=r[2], sub_mono=True), Cell(r[3] or DASH, mono=True, tiny=True), Cell(r[4] or DASH, small=True)))
            app.append(
                _table(
                    ("#", "Episode", "Event", "Recorded description"),
                    rows,
                    (0.5, 3.6, 3.5, 2.8),
                    title=f"{sev} · {code} · {len(items):,} occurrence(s)",
                    align=("r", "l", "l", "l"),
                    dense=True,
                )
            )
        sections.append(Section("appendix-findings-1", "Appendix A · Findings for the selected episodes", "Complete, unchanged", tuple(app), appendix=True))
    if exclusions:
        rows = [
            (Cell(short.get(ep, "") or DASH, bold=bool(short.get(ep)), sub=ep, sub_mono=True), Cell(m, mono=True, tiny=True), Cell(r, mono=True, tiny=True), Cell(group_repeats(d), small=True))
            for m, r, ep, d in exclusions
        ]
        sections.append(
            Section(
                "appendix-exclusions-1",
                "Appendix B · Excluded episodes",
                "Selected episodes excluded from rates",
                (
                    Note("The recorded detail string is grouped as “code ×N” for legibility; the codes and their counts are exactly those recorded."),
                    _table(("Episode", "Excluded from", "Reason", "Recorded detail"), rows, (3.9, 2.3, 2.6, 2.8), dense=True),
                ),
                appendix=True,
            )
        )
    return sections


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------


def _overview_section(selected, period: Period, zone, states, included, details, integrity_present: bool) -> Section:
    unit = {"live-mirl": "episodes", "cosine": "episodes", "mine": "episodes",
            "study-mode": "study blocks", "secant": "SECANT episodes", "cosecant": "COSECANT breaks"}
    cards = []
    for key in selected:
        state = states[key]
        if state == UNAVAILABLE_STATE:
            cards.append(Card(("Study / " if key in {"secant", "cosecant"} else "") + SECTION_TITLES[key], UNAVAILABLE, "evidence unavailable", "muted"))
        else:
            n = len(included[key])
            cards.append(Card(("Study / " if key in {"secant", "cosecant"} else "") + SECTION_TITLES[key], fmt_int(n), (f"{unit[key]} in the selected period" if n else NO_EPISODE), "" if n else "muted"))
    blocks: list[Block] = [CardRow(tuple(cards[i : i + 4])) for i in range(0, len(cards), 4)]
    start_local = period.start_utc.astimezone(zone) if zone is not None else period.start_utc.astimezone()
    blocks.append(
        Note(
            f"Selected period: {period.label}, inclusive, in local time ({tz_label(start_local)}). Records are included when their recorded start time is on or after "
            f"{start_local:%d %b %Y} 00:00 and before 00:00 on the day after the last date. Only records belonging to this period enter the report: counts, outcome tables, "
            "timelines, findings and this overview are all built from those records. Events of an included record that fall outside these dates are shown and marked."
        )
    )
    rows = []
    for key in selected:
        state = states[key]
        n = len(included[key])
        rows.append(
            (
                Cell(("  / " if key in {"secant", "cosecant"} else "") + SECTION_TITLES[key], bold=True),
                Cell({AVAILABLE_STATE: "Available", NO_DATA_STATE: "Available (no data)", UNAVAILABLE_STATE: "Unavailable"}[state], tone={AVAILABLE_STATE: "ok", NO_DATA_STATE: "muted", UNAVAILABLE_STATE: "warn"}[state]),
                Cell(UNAVAILABLE if state == UNAVAILABLE_STATE else (fmt_int(n) if n else NO_EPISODE)),
                Cell(SECTION_SUBTITLES[key], small=True),
                Cell(details.get(key, ""), small=True),
            )
        )
    blocks.append(
        _table(
            ("Section", "Evidence", "Records in period", "Recorded unit", "Note"),
            rows,
            (1.4, 1.5, 1.6, 1.6, 3.6),
            title="Report sections and evidence",
            align=("l", "l", "l", "l", "l"),
        )
    )
    contents = []
    chapter = child = 0
    for key in selected:
        if key in {"secant", "cosecant"}:
            child += 1
            contents.append((f"Chapter {chapter}.{child}", f"STUDY MODE / {SECTION_TITLES[key]}"))
        else:
            chapter += 1
            contents.append((f"Chapter {chapter}", "STUDY MODE / Study Context" if key == "study-mode" and any(k in selected for k in ("secant", "cosecant")) else SECTION_TITLES[key]))
    if integrity_present:
        contents.append((f"Chapter {chapter + 1}", INTEGRITY_TITLE))
    blocks.append(_table(("Chapter", "Title"), contents, (1.0, 3.0), title="Contents", header=False))
    return Section("overview", "Report overview", f"Reporting period {period.label}", tuple(blocks))


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def build_report(
    snapshot: object,
    request: object,
    *,
    generated_at: datetime | None = None,
    tz: tzinfo | None = None,
    sample_banner: str = "",
    study_records=None,
    study_error: str | None = None,
    study_family=None,
    study_family_error: str | None = None,
) -> ReportModel:
    requested = tuple(request.selected_sections())
    if not requested:
        raise ValueError("at least one analytics section is required")
    unknown = [k for k in requested if k not in REPORT_KEYS]
    if unknown:
        raise ValueError(f"unknown analytics section: {unknown[0]}")
    selected = tuple(k for k in REPORT_KEYS if k in requested)
    if any(key in selected for key in ("secant", "cosecant")) and "study-mode" not in selected:
        raise ValueError("SECANT and COSECANT Analytics Sheet sections require Study Mode selection")

    timezone_key = str(getattr(request, "presentation_timezone", "local") or "local")
    if tz is None:
        period = make_period(request.range_start, request.range_end, timezone_key=timezone_key)
    else:
        period = make_period(request.range_start, request.range_end, timezone_key=timezone_key, zone=tz)
    zone = period.zone
    now = generated_at or datetime.now(timezone.utc)
    local_now = now.astimezone(zone) if zone is not None else now.astimezone()

    chapters: list[Section] = []
    states: dict[str, str] = {}
    included: dict[str, tuple[str, ...]] = {}
    details: dict[str, str] = {}
    mirl_episodes: tuple = ()
    for key in selected:
        if key == "live-mirl":
            projection = g(snapshot, "live_mirl")
            section, state, ids, mirl_episodes = _mirl_section(projection, period, zone)
            details[key] = organ_state(key, projection)[1]
        elif key == "cosine":
            projection = g(snapshot, "cosine")
            section, state, ids = _cosine_section(projection, period, zone)
            details[key] = organ_state(key, projection)[1]
        elif key == "mine":
            projection = g(snapshot, "mine")
            section, state, ids = _mine_section(projection, period, zone)
            details[key] = organ_state(key, projection)[1]
        elif key == "study-mode":
            section, state, ids = _study_section(study_records, study_error, period, zone, study_family)
            if any(child in selected for child in ("secant", "cosecant")):
                section = Section(section.key, "STUDY MODE / Study Context", section.subtitle, section.blocks)
            details[key] = "Study Mode evidence could not be read." if state == UNAVAILABLE_STATE else ""
        elif key == "secant":
            section, state, ids = _secant_section(study_family, study_family_error, period, zone)
            details[key] = "Separate SECANT episode authority."
        else:
            section, state, ids = _cosecant_section(study_family, study_family_error, period, zone)
            details[key] = "Separate COSECANT break authority."
        chapters.append(section)
        states[key] = state
        included[key] = ids
    integrity = _integrity_sections(g(snapshot, "live_mirl"), mirl_episodes, zone) if "live-mirl" in selected else []
    overview = _overview_section(selected, period, zone, states, included, details, bool(integrity))
    return ReportModel(
        period=period,
        period_text=period.label,
        generated_label=f"{local_now:%d %b %Y · %H:%M} {tz_label(local_now)}",
        generated_iso=now.astimezone(timezone.utc).isoformat(timespec="seconds"),
        tz_label=tz_label(local_now),
        sections=(overview, *chapters, *integrity),
        cover_items=tuple(SECTION_TITLES[k] for k in selected if k not in {"secant", "cosecant"}),
        scope_note="Only records inside the selected period are included.",
        states=states,
        included=included,
        sample_banner=sample_banner,
    )
