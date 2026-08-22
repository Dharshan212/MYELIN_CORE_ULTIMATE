"""COSINE read model, dashboard projection and PDF presentation.

This file reads immutable ``CosineEvent`` facts and the optional live runtime
snapshot.  It does not detect streaming, advance timers, accept popup actions,
repair events or write operational persistence.

Data-quality rules
------------------
* missing, duplicate or non-contiguous evidence remains visibly DEGRADED;
* malformed return times are excluded and counted, never converted to zero;
* platform history is limited to the eight authoritative COSINE keys;
* Hopper edges come only from durable HOPPER_TRANSITION events; and
* the PDF is refused when historical evidence is unavailable.
"""

from __future__ import annotations

import html
import json
import math
import os
import secrets
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Final, Protocol

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from COSINE.cosine import (
    COSINE_SCHEMA_VERSION,
    PLATFORM_KEYS,
    PLATFORM_LABELS,
    CosineEvent,
    CosinePhase,
    CosineSnapshot,
)


REPORT_SCHEMA_VERSION: Final = "myelin-cosine-report-v1"
NIL: Final = "NIL"


class IntegrityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class CurrentViewing:
    active: bool
    status: str
    platform_key: str
    platform_name: str
    content_title: str
    current_platform_seconds: float
    overall_ott_seconds: float
    return_confirmation_remaining_seconds: float


@dataclass(frozen=True, slots=True)
class OverviewMetrics:
    completed_sessions: int
    streaming_checkins: int
    returned_to_focus: int
    ten_more_min: int
    finish_my_show: int
    continued_watching: int
    usual_return_time_seconds: float | None


@dataclass(frozen=True, slots=True)
class SessionHistory:
    cosine_session_id: str
    started_at_utc: str
    ended_at_utc: str
    closure_reason: str
    platform_keys: tuple[str, ...]
    platform_names: tuple[str, ...]
    content_titles: tuple[str, ...]
    displayed_checkins: int
    ten_more_min: int
    finish_my_show: int
    continued_watching: int
    confirmed_return_time_seconds: float | None
    foreground_ott_seconds: float | None
    platform_seconds: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class ReturnTimeRecord:
    serial_number: int
    cosine_session_id: str
    platform_names: tuple[str, ...]
    content_titles: tuple[str, ...]
    confirmed_at_utc: str
    return_time_seconds: float
    fastest: bool = False
    longest: bool = False


@dataclass(frozen=True, slots=True)
class PlatformHistory:
    platform_key: str
    platform_name: str
    completed_sessions: int
    displayed_checkins: int
    returned_to_focus: int
    ten_more_min: int
    finish_my_show: int
    continued_watching: int
    active_foreground_seconds: float
    usual_return_time_seconds: float | None


@dataclass(frozen=True, slots=True)
class HopperRecord:
    cosine_session_id: str
    ordinal: int
    from_platform_key: str
    from_platform_name: str
    to_platform_key: str
    to_platform_name: str
    content_title: str
    changed_at_utc: str


@dataclass(frozen=True, slots=True)
class DataQuality:
    status: IntegrityStatus
    accepted_event_count: int
    excluded_event_count: int
    excluded_session_count: int
    return_time_exclusions: int
    diagnostics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CosineReportSnapshot:
    generated_at_utc: str
    current: CurrentViewing
    overview: OverviewMetrics
    history: tuple[SessionHistory, ...]
    return_times: tuple[ReturnTimeRecord, ...]
    platform_history: tuple[PlatformHistory, ...]
    hopper_data: tuple[HopperRecord, ...]
    data_quality: DataQuality
    source_schema_version: str
    schema_version: str = REPORT_SCHEMA_VERSION


class CosineEventReader(Protocol):
    """Read-only persistence boundary used by this projection."""

    def read_cosine_events(self) -> tuple[CosineEvent, ...]: ...


class CosineReportError(RuntimeError):
    pass


class CosineReadAuthority:
    """One read authority over one persistence reader."""

    def __init__(self, *, event_reader: CosineEventReader) -> None:
        if event_reader is None:
            raise ValueError("CosineReadAuthority requires an event reader")
        self._reader = event_reader

    def project(self, *, live: CosineSnapshot | None = None) -> CosineReportSnapshot:
        try:
            events = self._reader.read_cosine_events()
        except Exception as exc:
            return _unavailable_snapshot(
                live,
                f"COSINE historical evidence could not be read: {_short_error(exc)}",
            )
        return project_cosine(tuple(events), live=live)


def project_cosine(
    events: Sequence[CosineEvent],
    *,
    live: CosineSnapshot | None = None,
) -> CosineReportSnapshot:
    """Build one deterministic dashboard/report projection."""

    if live is not None and not isinstance(live, CosineSnapshot):
        raise TypeError("live must be a CosineSnapshot")
    diagnostics: list[str] = []
    excluded_events = 0
    accepted: list[CosineEvent] = []
    event_ids: set[str] = set()
    for event in events:
        reason = _event_problem(event, event_ids)
        if reason:
            excluded_events += 1
            diagnostics.append(reason)
            continue
        event_ids.add(event.event_id)
        accepted.append(event)

    grouped: dict[str, list[CosineEvent]] = defaultdict(list)
    for event in accepted:
        grouped[event.cosine_session_id].append(event)

    history: list[SessionHistory] = []
    returns: list[ReturnTimeRecord] = []
    hoppers: list[HopperRecord] = []
    excluded_sessions = 0
    return_exclusions = 0
    for session_id, values in grouped.items():
        values.sort(key=lambda item: (item.sequence, item.monotonic_ns, item.event_id))
        sequences = [event.sequence for event in values]
        if sequences != list(range(1, len(values) + 1)):
            excluded_sessions += 1
            diagnostics.append(
                f"Session {session_id[:8]} has a non-contiguous event sequence and was excluded."
            )
            continue
        generations = {event.generation for event in values}
        if len(generations) != 1:
            excluded_sessions += 1
            diagnostics.append(
                f"Session {session_id[:8]} contains mixed generations and was excluded."
            )
            continue
        session, session_returns, session_hoppers, excluded = _project_session(
            session_id,
            values,
        )
        return_exclusions += excluded
        if session is not None:
            history.append(session)
            returns.extend(session_returns)
            hoppers.extend(session_hoppers)
        elif not (
            any(
                event.event_name == "OTT_QUALIFICATION_CANCELLED"
                for event in values
            )
            or (
                live is not None
                and live.cosine_session_id == session_id
                and live.phase
                not in {CosinePhase.IDLE, CosinePhase.CLOSED, CosinePhase.SHUTDOWN}
            )
        ):
            excluded_sessions += 1
            diagnostics.append(
                f"Session {session_id[:8]} has no durable closure and was excluded."
            )

    history.sort(key=lambda item: (item.ended_at_utc, item.cosine_session_id), reverse=True)
    returns.sort(key=lambda item: (item.confirmed_at_utc, item.cosine_session_id), reverse=True)
    hoppers.sort(key=lambda item: (item.changed_at_utc, item.cosine_session_id, item.ordinal), reverse=True)
    returns = _mark_return_extremes(returns)
    platforms = _platform_projection(history, returns)
    overview = _overview(history, returns)
    status = (
        IntegrityStatus.DEGRADED
        if diagnostics or excluded_events or excluded_sessions or return_exclusions
        else IntegrityStatus.AVAILABLE
    )
    return CosineReportSnapshot(
        generated_at_utc=_utc_now(),
        current=_current_view(live),
        overview=overview,
        history=tuple(history[:100]),
        return_times=tuple(returns[:100]),
        platform_history=tuple(platforms[:3]),
        hopper_data=tuple(hoppers[:200]),
        data_quality=DataQuality(
            status=status,
            accepted_event_count=len(accepted),
            excluded_event_count=excluded_events,
            excluded_session_count=excluded_sessions,
            return_time_exclusions=return_exclusions,
            diagnostics=tuple(dict.fromkeys(diagnostics))[:100],
        ),
        source_schema_version=COSINE_SCHEMA_VERSION,
    )


def _project_session(
    session_id: str,
    events: Sequence[CosineEvent],
) -> tuple[SessionHistory | None, list[ReturnTimeRecord], list[HopperRecord], int]:
    started = events[0].occurred_at_utc
    closed = next(
        (event for event in reversed(events) if event.event_name == "COSINE_SESSION_CLOSED"),
        None,
    )
    if closed is None:
        return None, [], [], 0
    close_payload = _payload(closed)
    closure_reason = str(close_payload.get("closure_reason", "NOT_ENOUGH_INFORMATION"))
    platform_order: list[str] = []
    content_titles: list[str] = []
    displayed = ten_more = finish = continued = 0
    return_records: list[ReturnTimeRecord] = []
    hopper_records: list[HopperRecord] = []
    return_exclusions = 0
    hopper_ordinal = 0
    for event in events:
        platform = event.platform_key
        if platform in PLATFORM_KEYS and platform not in platform_order:
            platform_order.append(platform)
        if event.content_title and event.content_title not in content_titles:
            content_titles.append(event.content_title)
        payload = _payload(event)
        if event.event_name == "CHECKIN_DISPLAYED":
            displayed += 1
        elif event.event_name == "CHECKIN_ANSWERED":
            choice = payload.get("choice")
            ten_more += int(choice == "TEN_MORE_MIN")
            finish += int(choice == "FINISH_MY_SHOW")
        elif event.event_name == "CONTINUED_WATCHING":
            continued += 1
        elif event.event_name == "RETURN_CONFIRMED":
            value = payload.get("return_time_seconds")
            if _finite_nonnegative(value):
                return_records.append(
                    ReturnTimeRecord(
                        serial_number=0,
                        cosine_session_id=session_id,
                        platform_names=tuple(PLATFORM_LABELS[key] for key in platform_order),
                        content_titles=tuple(content_titles),
                        confirmed_at_utc=event.occurred_at_utc,
                        return_time_seconds=float(value),
                    )
                )
            else:
                return_exclusions += 1
        elif event.event_name == "HOPPER_TRANSITION":
            previous = str(payload.get("from_platform", ""))
            current = str(payload.get("to_platform", ""))
            if previous in PLATFORM_KEYS and current in PLATFORM_KEYS and previous != current:
                hopper_ordinal += 1
                hopper_records.append(
                    HopperRecord(
                        cosine_session_id=session_id,
                        ordinal=hopper_ordinal,
                        from_platform_key=previous,
                        from_platform_name=PLATFORM_LABELS[previous],
                        to_platform_key=current,
                        to_platform_name=PLATFORM_LABELS[current],
                        content_title=event.content_title,
                        changed_at_utc=event.occurred_at_utc,
                    )
                )
    foreground = close_payload.get("foreground_ott_seconds")
    foreground_seconds = float(foreground) if _finite_nonnegative(foreground) else None
    raw_platform_seconds = close_payload.get("platform_seconds")
    platform_seconds: list[tuple[str, float]] = []
    if isinstance(raw_platform_seconds, dict):
        for key, value in raw_platform_seconds.items():
            if key in PLATFORM_KEYS and _finite_nonnegative(value):
                platform_seconds.append((str(key), float(value)))
    confirmed_return = return_records[-1].return_time_seconds if return_records else None
    session = SessionHistory(
        cosine_session_id=session_id,
        started_at_utc=started,
        ended_at_utc=closed.occurred_at_utc,
        closure_reason=closure_reason,
        platform_keys=tuple(platform_order),
        platform_names=tuple(PLATFORM_LABELS[key] for key in platform_order),
        content_titles=tuple(content_titles),
        displayed_checkins=displayed,
        ten_more_min=ten_more,
        finish_my_show=finish,
        continued_watching=continued,
        confirmed_return_time_seconds=confirmed_return,
        foreground_ott_seconds=foreground_seconds,
        platform_seconds=tuple(sorted(platform_seconds)),
    )
    return session, return_records, hopper_records, return_exclusions


def _platform_projection(
    history: Sequence[SessionHistory],
    returns: Sequence[ReturnTimeRecord],
) -> list[PlatformHistory]:
    records: list[PlatformHistory] = []
    for key in PLATFORM_KEYS:
        sessions = [item for item in history if key in item.platform_keys]
        if not sessions:
            continue
        return_values = [
            item.return_time_seconds
            for item in returns
            if PLATFORM_LABELS[key] in item.platform_names
        ]
        active_seconds = sum(
            seconds
            for session in sessions
            for platform, seconds in session.platform_seconds
            if platform == key
        )
        records.append(
            PlatformHistory(
                platform_key=key,
                platform_name=PLATFORM_LABELS[key],
                completed_sessions=len(sessions),
                displayed_checkins=sum(item.displayed_checkins for item in sessions),
                returned_to_focus=sum(item.closure_reason == "RETURNED_TO_FOCUS" for item in sessions),
                ten_more_min=sum(item.ten_more_min for item in sessions),
                finish_my_show=sum(item.finish_my_show for item in sessions),
                continued_watching=sum(item.continued_watching for item in sessions),
                active_foreground_seconds=active_seconds,
                usual_return_time_seconds=(median(return_values) if return_values else None),
            )
        )
    return sorted(
        records,
        key=lambda item: (
            item.active_foreground_seconds,
            item.completed_sessions,
            item.displayed_checkins,
            item.platform_name,
        ),
        reverse=True,
    )


def _overview(
    history: Sequence[SessionHistory],
    returns: Sequence[ReturnTimeRecord],
) -> OverviewMetrics:
    values = [item.return_time_seconds for item in returns]
    return OverviewMetrics(
        completed_sessions=len(history),
        streaming_checkins=sum(item.displayed_checkins for item in history),
        returned_to_focus=sum(item.closure_reason == "RETURNED_TO_FOCUS" for item in history),
        ten_more_min=sum(item.ten_more_min for item in history),
        finish_my_show=sum(item.finish_my_show for item in history),
        continued_watching=sum(item.continued_watching for item in history),
        usual_return_time_seconds=median(values) if values else None,
    )


def _current_view(live: CosineSnapshot | None) -> CurrentViewing:
    active = bool(
        live is not None
        and live.phase not in {CosinePhase.IDLE, CosinePhase.CLOSED, CosinePhase.SHUTDOWN}
    )
    if not active or live is None:
        return CurrentViewing(False, "NO ACTIVE STREAMING SESSION", "", NIL, NIL, 0.0, 0.0, 0.0)
    return CurrentViewing(
        True,
        live.phase.value,
        live.current_platform_key,
        live.current_platform_label or NIL,
        live.current_content_title or "Content title unavailable",
        live.current_platform_seconds,
        live.foreground_ott_seconds,
        live.return_confirmation_remaining_seconds,
    )


def _mark_return_extremes(values: list[ReturnTimeRecord]) -> list[ReturnTimeRecord]:
    if not values:
        return values
    fastest = min(item.return_time_seconds for item in values)
    longest = max(item.return_time_seconds for item in values)
    output: list[ReturnTimeRecord] = []
    for index, item in enumerate(values, start=1):
        output.append(
            ReturnTimeRecord(
                serial_number=index,
                cosine_session_id=item.cosine_session_id,
                platform_names=item.platform_names,
                content_titles=item.content_titles,
                confirmed_at_utc=item.confirmed_at_utc,
                return_time_seconds=item.return_time_seconds,
                fastest=item.return_time_seconds == fastest,
                longest=item.return_time_seconds == longest,
            )
        )
    return output


def _event_problem(event: object, seen: set[str]) -> str:
    if not isinstance(event, CosineEvent):
        return "A non-COSINE event object was excluded."
    if event.schema_version != COSINE_SCHEMA_VERSION:
        return f"Event {event.event_id[:8]} uses an unsupported schema."
    if not event.event_id or event.event_id in seen:
        return "A COSINE event has a missing or duplicate identity."
    if not event.cosine_session_id or event.sequence <= 0 or event.monotonic_ns <= 0:
        return f"Event {event.event_id[:8]} has incomplete ordering evidence."
    if event.platform_key and event.platform_key not in PLATFORM_KEYS:
        return f"Event {event.event_id[:8]} has an unknown platform key."
    try:
        parsed = datetime.fromisoformat(event.occurred_at_utc)
        json.loads(event.payload_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return f"Event {event.event_id[:8]} has malformed time or payload evidence."
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return f"Event {event.event_id[:8]} has no UTC offset."
    return ""


def _payload(event: CosineEvent) -> dict[str, object]:
    try:
        value = json.loads(event.payload_json)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _finite_nonnegative(value: object) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0


def _unavailable_snapshot(
    live: CosineSnapshot | None,
    diagnostic: str,
) -> CosineReportSnapshot:
    return CosineReportSnapshot(
        generated_at_utc=_utc_now(),
        current=_current_view(live),
        overview=OverviewMetrics(0, 0, 0, 0, 0, 0, None),
        history=(),
        return_times=(),
        platform_history=(),
        hopper_data=(),
        data_quality=DataQuality(
            IntegrityStatus.UNAVAILABLE,
            0,
            0,
            0,
            0,
            (diagnostic,),
        ),
        source_schema_version=COSINE_SCHEMA_VERSION,
    )


# ---------------------------------------------------------------------------
# ReportLab presentation over the exact read-model snapshot above.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CosineReportRequest:
    output_path: str | Path
    title: str = "MYELIN COSINE Report"
    subtitle: str = "Choice-oriented streaming history and return evidence"
    maximum_sessions: int = 25
    maximum_returns: int = 50
    overwrite: bool = False

    def __post_init__(self) -> None:
        path = Path(self.output_path).expanduser()
        if path.suffix.casefold() != ".pdf":
            raise ValueError("COSINE report output must end with .pdf")
        if not str(self.title).strip():
            raise ValueError("report title cannot be empty")
        if type(self.maximum_sessions) is not int or not 1 <= self.maximum_sessions <= 200:
            raise ValueError("maximum_sessions must be between 1 and 200")
        if type(self.maximum_returns) is not int or not 1 <= self.maximum_returns <= 500:
            raise ValueError("maximum_returns must be between 1 and 500")


@dataclass(frozen=True, slots=True)
class CosineReportResult:
    output_path: str
    generated_at_utc: str
    byte_size: int
    integrity_status: IntegrityStatus
    session_count: int
    return_record_count: int


class CosineReportPresenter:
    """A4 report presentation; no database or runtime access is reachable."""

    def build(
        self,
        snapshot: CosineReportSnapshot,
        request: CosineReportRequest,
    ) -> CosineReportResult:
        if not isinstance(snapshot, CosineReportSnapshot):
            raise TypeError("snapshot must be CosineReportSnapshot")
        if not isinstance(request, CosineReportRequest):
            raise TypeError("request must be CosineReportRequest")
        if snapshot.data_quality.status is IntegrityStatus.UNAVAILABLE:
            raise CosineReportError("COSINE evidence is unavailable; report was not created")
        output = Path(request.output_path).expanduser().resolve()
        if output.exists() and not request.overwrite:
            raise FileExistsError(f"report already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(f".{output.stem}-{secrets.token_hex(6)}.tmp.pdf")
        styles = _styles()
        try:
            document = SimpleDocTemplate(
                str(temporary),
                pagesize=A4,
                leftMargin=16 * mm,
                rightMargin=16 * mm,
                topMargin=17 * mm,
                bottomMargin=17 * mm,
                title=request.title,
                author="",
                subject="COSINE behavioral streaming report",
            )
            document.build(
                _story(snapshot, request, styles),
                onFirstPage=_footer,
                onLaterPages=_footer,
            )
            if request.overwrite:
                os.replace(temporary, output)
            else:
                # Same-directory hard-link commit is atomic and fails if the
                # destination appeared after the initial validation.
                os.link(temporary, output)
                temporary.unlink(missing_ok=True)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        return CosineReportResult(
            output_path=str(output),
            generated_at_utc=snapshot.generated_at_utc,
            byte_size=output.stat().st_size,
            integrity_status=snapshot.data_quality.status,
            session_count=min(len(snapshot.history), request.maximum_sessions),
            return_record_count=min(len(snapshot.return_times), request.maximum_returns),
        )


def _story(snapshot, request, styles) -> list:
    story: list = [
        Paragraph(_escape(request.title), styles["Title"]),
        Paragraph(_escape(request.subtitle), styles["Subtitle"]),
        Spacer(1, 6 * mm),
        _metric_table(snapshot, styles),
        Spacer(1, 6 * mm),
        Paragraph("Evidence quality", styles["H2"]),
        Paragraph(
            f"Status: <b>{snapshot.data_quality.status.value}</b> · "
            f"Accepted events: {snapshot.data_quality.accepted_event_count} · "
            f"Excluded events: {snapshot.data_quality.excluded_event_count} · "
            f"Excluded return times: {snapshot.data_quality.return_time_exclusions}",
            styles["Body"],
        ),
    ]
    for diagnostic in snapshot.data_quality.diagnostics[:10]:
        story.append(Paragraph(f"• {_escape(diagnostic)}", styles["Muted"]))
    story.extend([PageBreak(), Paragraph("Session history", styles["H1"])])
    sessions = snapshot.history[: request.maximum_sessions]
    if not sessions:
        story.append(Paragraph("No completed COSINE sessions are available.", styles["Muted"]))
    else:
        rows = [["Ended", "Platforms", "Outcome", "Check-ins", "OTT time"]]
        for item in sessions:
            rows.append(
                [
                    _compact_time(item.ended_at_utc),
                    ", ".join(item.platform_names) or NIL,
                    item.closure_reason.replace("_", " ").title(),
                    str(item.displayed_checkins),
                    _duration(item.foreground_ott_seconds),
                ]
            )
        story.append(_table(rows, [31 * mm, 48 * mm, 43 * mm, 22 * mm, 27 * mm]))
    story.extend([Spacer(1, 7 * mm), Paragraph("Return-time data", styles["H1"])])
    returns = snapshot.return_times[: request.maximum_returns]
    if not returns:
        story.append(Paragraph("No eligible confirmed return-time evidence is available.", styles["Muted"]))
    else:
        rows = [["#", "Confirmed", "Platforms", "Return time", "Flag"]]
        for item in returns:
            flag = "FASTEST" if item.fastest else "LONGEST" if item.longest else ""
            rows.append(
                [
                    str(item.serial_number),
                    _compact_time(item.confirmed_at_utc),
                    ", ".join(item.platform_names) or NIL,
                    _duration(item.return_time_seconds),
                    flag,
                ]
            )
        story.append(_table(rows, [10 * mm, 38 * mm, 62 * mm, 33 * mm, 28 * mm]))
    story.extend([PageBreak(), Paragraph("Top streaming platforms", styles["H1"])])
    if snapshot.platform_history:
        rows = [["Platform", "Sessions", "Check-ins", "Returned", "Usual return"]]
        for item in snapshot.platform_history:
            rows.append(
                [
                    item.platform_name,
                    str(item.completed_sessions),
                    str(item.displayed_checkins),
                    str(item.returned_to_focus),
                    _duration(item.usual_return_time_seconds),
                ]
            )
        story.append(_table(rows, [45 * mm, 28 * mm, 31 * mm, 30 * mm, 37 * mm]))
    else:
        story.append(Paragraph("No platform history is available.", styles["Muted"]))
    story.extend([Spacer(1, 7 * mm), Paragraph("Hopper data", styles["H1"])])
    if snapshot.hopper_data:
        rows = [["Changed", "From", "To", "Content"]]
        for item in snapshot.hopper_data[:50]:
            rows.append(
                [
                    _compact_time(item.changed_at_utc),
                    item.from_platform_name,
                    item.to_platform_name,
                    item.content_title or "Content title unavailable",
                ]
            )
        story.append(_table(rows, [38 * mm, 35 * mm, 35 * mm, 63 * mm]))
    else:
        story.append(Paragraph("No certified OTT-to-OTT transitions were recorded.", styles["Muted"]))
    story.extend(
        [
            Spacer(1, 8 * mm),
            Paragraph("Interpretation boundary", styles["H2"]),
            Paragraph(
                "This report describes observed software activity, COSINE choices and return timing. "
                "It does not infer attention, health, emotion, dopamine or neurological state.",
                styles["Body"],
            ),
        ]
    )
    return story


def _metric_table(snapshot, styles) -> Table:
    overview = snapshot.overview
    rows = [
        ["Completed sessions", "Streaming check-ins", "Returned to focus"],
        [str(overview.completed_sessions), str(overview.streaming_checkins), str(overview.returned_to_focus)],
        ["10 More Min", "Finish My Show", "Usual return time"],
        [str(overview.ten_more_min), str(overview.finish_my_show), _duration(overview.usual_return_time_seconds)],
    ]
    table = Table(rows, colWidths=[57 * mm] * 3, rowHeights=[9 * mm, 13 * mm, 9 * mm, 13 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#10253A")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#8DCDF2")),
                ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#8DCDF2")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ("FONTSIZE", (0, 1), (-1, 1), 16),
                ("FONTSIZE", (0, 3), (-1, 3), 16),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#294963")),
            ]
        )
    )
    return table


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle("CosineTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.HexColor("#123653"), alignment=TA_CENTER, spaceAfter=5),
        "Subtitle": ParagraphStyle("CosineSubtitle", parent=base["BodyText"], fontSize=10, leading=14, textColor=colors.HexColor("#567083"), alignment=TA_CENTER),
        "H1": ParagraphStyle("CosineH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=colors.HexColor("#123653"), spaceAfter=7),
        "H2": ParagraphStyle("CosineH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=colors.HexColor("#1F6D91"), spaceBefore=4, spaceAfter=4),
        "Body": ParagraphStyle("CosineBody", parent=base["BodyText"], fontSize=9, leading=13, textColor=colors.HexColor("#263746")),
        "Muted": ParagraphStyle("CosineMuted", parent=base["BodyText"], fontSize=8, leading=11, textColor=colors.HexColor("#667987")),
    }


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    data = [[Paragraph(_escape(cell), ParagraphStyle("cell", fontName="Helvetica", fontSize=7.5, leading=9)) for cell in row] for row in rows]
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123653")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#F4F8FB")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CCD9E2")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#718492"))
    canvas.drawString(16 * mm, 9 * mm, "MYELIN · COSINE behavioral evidence")
    canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {document.page}")
    canvas.restoreState()


def _duration(value: object) -> str:
    if not _finite_nonnegative(value):
        return NIL
    seconds = int(round(float(value)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _compact_time(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return NIL
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _escape(value: object) -> str:
    return html.escape(" ".join(str(value or "").split())[:1_000])


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _short_error(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:240] or type(exc).__name__


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "CosineEventReader",
    "CosineReadAuthority",
    "CosineReportError",
    "CosineReportPresenter",
    "CosineReportRequest",
    "CosineReportResult",
    "CosineReportSnapshot",
    "CurrentViewing",
    "DataQuality",
    "HopperRecord",
    "IntegrityStatus",
    "OverviewMetrics",
    "PlatformHistory",
    "ReturnTimeRecord",
    "SessionHistory",
    "project_cosine",
]
