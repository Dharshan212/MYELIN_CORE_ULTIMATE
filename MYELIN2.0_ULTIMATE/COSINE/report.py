"""COSINE two-page PDF report -- NEW read-model presentation layer only.

This module owns none of COSINE's physiology, timing, event validation or
platform certification. Its only input is an already-projected
``CosineAnalysisProjection`` from ``COSINE.read_model``; it never reads
persistence, never touches the runtime, and performs no return-time or
platform-duration mathematics.

The report is a bounded, deterministic projection of durable evidence:

    * exactly two A4 pages, portrait, ``PageBreak()`` between them;
    * the eight most recent episodes (matching the dashboard's own database-
      snapshot framing), never a silent truncation -- a "showing N of M" line
      is printed whenever more exist;
    * a compact key-evidence table (<= 10 rows) for the recent episode only,
      captioned with how many of its total recorded events that represents;
      the full dense ledger stays in the COSINE dashboard, never here;
    * the human-facing ``COS-DDMMYYYY-NN`` episode alias, reimplemented here
      as a pure function against the exact same algorithm the locked
      dashboard uses (UTC start date, chronological within date, stable
      ``(cosine_session_id, generation)`` tie-break) -- never the raw
      internal session identity;
    * Usual Return is always reported exactly as the read model states it
      (``UNAVAILABLE`` today); this module never computes a return-time
      statistic of its own.

Nothing here reconstructs a withheld payload field or prints raw
``payload_display`` wholesale -- evidence detail is extracted from named,
already-sanitized projection fields only.
"""

from __future__ import annotations

import html
import os
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
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

from COSINE.read_model import CosineAnalysisProjection, CosineEpisodeProjection
from time_projection import parse_utc_timestamp, project_utc_timestamp, timezone_tag

REPORT_SCHEMA_VERSION: Final = "myelin-cosine-pdf-v2"

#: Two-page presentation caps -- visual page-capacity rules only. They never
#: modify the read model, the dashboard's full evidence, or event storage.
EPISODE_ROW_CAP: Final = 8
KEY_EVIDENCE_ROW_CAP: Final = 10
HOPPER_MAP_COLLAPSE_THRESHOLD: Final = 6


class CosineReportError(RuntimeError):
    """Raised when the report is refused rather than built on absent evidence."""


@dataclass(frozen=True, slots=True)
class CosinePdfReportRequest:
    output_path: Path
    title: str = "MYELIN COSINE Report"
    subtitle: str = "Choice-Oriented Streaming Insight and Navigation Engine"
    overwrite: bool = True


@dataclass(frozen=True, slots=True)
class CosinePdfReportResult:
    output_path: str
    generated_at_utc: str
    byte_size: int
    episode_count: int
    recent_episode_id: str
    total_recent_event_count: int
    shown_key_evidence_count: int


# ---------------------------------------------------------------------------
# Presentation-only humanizers -- a pure reimplementation of the SAME
# algorithm the locked CONTROL_STATION/launcher.py dashboard uses, kept here
# rather than imported so this module never imports the locked launcher (and
# the launcher is never disturbed to serve the report). Every dict below is
# byte-for-byte the dashboard's own mapping; see
# CONTROL_STATION/launcher.py's COSINE_EVENT_LABELS and neighbours.
# ---------------------------------------------------------------------------

_EVENT_LABELS: Final = {
    "COSINE_SESSION_STARTED": "Episode started",
    "OTT_PLATFORM_ENTERED": "Streaming platform entered",
    "CONTENT_OBSERVED": "Window title observed",
    "HOPPER_TRANSITION": "Platform switch",
    "INTENT_GATE_ELIGIBLE": "Intent gate became eligible",
    "INTENT_GATE_REQUESTED": "Intent gate requested",
    "INTENT_GATE_DISPLAYED": "Intent gate shown",
    "RETURN_INTENT_RECORDED": "You chose to return",
    "BREAK_INTENT_RECORDED": "You chose an intentional break",
    "RETURN_INTENT_WINDOW_STARTED": "Return window started",
    "RETURN_INTENT_CONVERTED_TO_BREAK": "Return intention converted to a break",
    "DURATION_REQUESTED": "Break duration requested",
    "BREAK_DURATION_COMMITTED": "Break duration committed",
    "BREAK_STARTED": "Break started",
    "BREAK_ACK_REQUESTED": "Break acknowledgement requested",
    "BREAK_ACK_DISPLAYED": "Break acknowledgement shown",
    "BREAK_ACKNOWLEDGED": "Break acknowledged",
    "BREAK_DEADLINE_REACHED": "Break deadline reached",
    "RETURN_CANDIDATE_STARTED": "Return candidate started",
    "RETURN_VERIFICATION_INTERRUPTED": "Return verification interrupted",
    "RETURN_VERIFICATION_COMPLETED": "Return verification completed",
    "FINAL_CALLBACK_REQUESTED": "Final callback requested",
    "FINAL_CALLBACK_DISPLAYED": "Final callback shown",
    "FINAL_CALLBACK_HIDDEN_FOR_FOCUS": "Final callback hidden for focus",
    "FINAL_CALLBACK_RESTORED_AFTER_RELAPSE": "Final callback restored",
    "CLOSURE_CONFIRMATION_STARTED": "Closure confirmation started",
    "CLOSURE_CONFIRMATION_INTERRUPTED": "Closure confirmation interrupted",
    "RETURN_CONFIRMED": "Return confirmed",
    "COSINE_SESSION_CLOSED": "Episode closed",
}

_OUTCOME_LABELS: Final = {
    "RETURNED_AFTER_INTENT": "Returned after intent",
    "RETURNED_AFTER_CALLBACK": "Returned after callback",
    "EARLY_RETURN": "Early return",
    "STUDY_PREEMPTION": "Study pre-emption",
    "HANDOVER": "Handover",
    "EMERGENCY": "Emergency",
    "INCOMPLETE": "Incomplete",
}

_CLOSURE_REASON_LABELS: Final = {
    "RETURN_CONFIRMED": "Return confirmed",
    "SINE_HANDOFF": "SINE handoff",
    "STUDY_HANDOFF": "Study handoff",
    "STOPPED": "Session stopped",
    "EMERGENCY": "Emergency",
    "SYSTEM_LOCK": "System lock",
    "SYSTEM_SLEEP": "System sleep",
    "NOT_ENOUGH_INFORMATION": "Not enough information",
}

_EVENT_CLASS_LABELS: Final = {
    "OBSERVED": "Observed",
    "DERIVED": "Derived",
    "USER_ACTION": "User action",
    "PRESENTATION": "Presentation",
}

_CHOICE_LABELS: Final = {
    "INTENTIONAL_BREAK": "Intentional break",
    "RETURN_INTENTION": "Return intention",
}

_LABEL_KEEP_WORDS: Final = {"COSINE", "SINE", "OTT", "UTC", "MYELIN"}


def _humanize_token(token: str | None) -> str:
    text = str(token or "")
    words = text.replace("_", " ").split()
    if not words:
        return "—"
    return " ".join(
        word if word.upper() in _LABEL_KEEP_WORDS else word.title() for word in words
    )


def event_label(name: str) -> str:
    return _EVENT_LABELS.get(name, _humanize_token(name))


def outcome_label(outcome: str | None) -> str:
    if not outcome:
        return "—"
    return _OUTCOME_LABELS.get(outcome, _humanize_token(outcome))


def closure_reason_label(reason: str | None) -> str:
    if not reason:
        return "—"
    return _CLOSURE_REASON_LABELS.get(reason, _humanize_token(reason))


def event_class_label(event_class: str) -> str:
    return _EVENT_CLASS_LABELS.get(event_class, _humanize_token(event_class))


def choice_label(choice: str | None) -> str:
    if not choice:
        return "—"
    return _CHOICE_LABELS.get(choice, _humanize_token(choice))


def closure_presentation(episode: CosineEpisodeProjection) -> str:
    """'Session stopped · Incomplete' style, neutral -- never a failure grade."""
    reason = closure_reason_label(episode.closure_reason)
    if episode.closure_outcome:
        return f"{reason} · {outcome_label(episode.closure_outcome)}"
    return reason


def _compact_outcome(episode: CosineEpisodeProjection) -> str:
    """One-line table-cell outcome: prefer the outcome alone (shorter than
    the reason·outcome composite), falling back to the reason when no
    outcome is recorded. Never a failure grade -- same neutral labels as
    ``closure_presentation``, just single-barreled for narrow columns."""

    if not episode.is_closed:
        return "OPEN EVIDENCE"
    if episode.closure_outcome:
        return outcome_label(episode.closure_outcome)
    if episode.closure_reason:
        return closure_reason_label(episode.closure_reason)
    return "—"


def episode_display_ids(
    episodes: "tuple[CosineEpisodeProjection, ...]",
) -> dict[tuple[str, int], str]:
    """Stable ``COS-DDMMYYYY-NN`` mask -- byte-for-byte the SAME algorithm as
    ``CONTROL_STATION/launcher.py``'s ``cosine_episode_display_ids``.

    Derived from each episode's immutable ``started_at_utc``, never from a
    presentation-timezone-dependent display string, so the alias never
    changes when the selected timezone changes. Never persisted, never used
    for selection or database lookup.
    """
    by_date: dict[str, list] = {}
    for spec in episodes:
        try:
            moment = parse_utc_timestamp(spec.started_at_utc)
        except Exception:
            continue
        by_date.setdefault(moment.strftime("%d%m%Y"), []).append((moment, spec))
    aliases: dict[tuple[str, int], str] = {}
    for date_key, entries in by_date.items():
        entries.sort(key=lambda item: (item[0], item[1].cosine_session_id, item[1].generation))
        for index, (_, spec) in enumerate(entries, start=1):
            aliases[(spec.cosine_session_id, spec.generation)] = f"COS-{date_key}-{index:02d}"
    return aliases


def display_episode_id(
    episode: CosineEpisodeProjection,
    episodes: "tuple[CosineEpisodeProjection, ...]",
) -> str:
    return episode_display_ids(episodes).get(
        (episode.cosine_session_id, episode.generation), "COS-UNKNOWN"
    )


def _split_display_timestamp(display: str):
    parts = str(display or "").split(" ", 2)
    if len(parts) < 2:
        return None
    try:
        return datetime.fromisoformat(f"{parts[0]} {parts[1]}")
    except ValueError:
        return None


def date_only(display: str) -> str:
    moment = _split_display_timestamp(display)
    return moment.strftime("%d %b %Y") if moment else "—"


def time_only(display: str) -> str:
    moment = _split_display_timestamp(display)
    return moment.strftime("%H:%M:%S") if moment else "—"


def _generated_display(projection: CosineAnalysisProjection) -> tuple[str, str]:
    """Clean human date/time + friendly zone label for the report metadata.

    Projects the report's own generated_at_utc through the certified
    time-projection authority (the same one read_model.py uses for every
    other displayed timestamp) into the selected presentation timezone --
    never a hardcoded zone. Falls back to the raw values only if the
    timestamp is somehow unreadable, so metadata is never silently dropped.
    """

    try:
        moment = project_utc_timestamp(
            projection.generated_at_utc, projection.presentation_timezone
        )
        zone_label = timezone_tag(moment, projection.presentation_timezone)
        return moment.strftime("%d %b %Y · %H:%M:%S"), zone_label
    except Exception:
        return projection.generated_at_utc, projection.presentation_timezone


def _choice_text(episode: CosineEpisodeProjection) -> str:
    """Same composite text the dashboard's ``cosine_choice_text`` builds --
    the recorded choice, plus (only where a conversion event is recorded)
    that the intention lapsed. Never implies the user chose the converted
    minutes."""

    choice = episode.user_choice
    minutes = episode.chosen_break_minutes
    converted = any(e.event_name == "RETURN_INTENT_CONVERTED_TO_BREAK" for e in episode.events)
    if choice == "INTENTIONAL_BREAK":
        return f"Intentional break · {minutes} min" if minutes is not None else "Intentional break"
    if choice == "RETURN_INTENTION":
        if converted:
            return (
                f"Return intention → converted · {minutes} min break"
                if minutes is not None
                else "Return intention → converted"
            )
        return "Return intention"
    return "No choice recorded"


# ---------------------------------------------------------------------------
# Report refusal law
# ---------------------------------------------------------------------------


def _require_evidence(projection: CosineAnalysisProjection | None) -> None:
    if projection is None:
        raise CosineReportError("COSINE evidence is unavailable; report was not created.")
    if not isinstance(projection, CosineAnalysisProjection):
        raise CosineReportError("COSINE projection is malformed; report was not created.")
    if not projection.available:
        raise CosineReportError(
            "COSINE durable evidence is unavailable; report was not created."
        )
    if not projection.episodes:
        raise CosineReportError(
            "No durable COSINE episodes exist; report was not created."
        )


# ---------------------------------------------------------------------------
# Recent-episode map / return pathway / Hopper map construction
# ---------------------------------------------------------------------------

_MAP_MILESTONES: Final = {
    "COSINE_SESSION_STARTED": "Streaming episode started",
    "INTENT_GATE_DISPLAYED": "Intent gate displayed",
    "RETURN_INTENT_RECORDED": "Return intention",
    "BREAK_INTENT_RECORDED": "Intentional break",
    "BREAK_DURATION_COMMITTED": "Break duration chosen",
    "BREAK_STARTED": "Break started",
    "FINAL_CALLBACK_DISPLAYED": "Final callback",
    "RETURN_CANDIDATE_STARTED": "Return candidate",
    "RETURN_VERIFICATION_COMPLETED": "Return verified",
    "RETURN_CONFIRMED": "Return confirmed",
}

_RETURN_CHAIN_NAMES: Final = (
    "RETURN_CANDIDATE_STARTED",
    "RETURN_VERIFICATION_COMPLETED",
    "RETURN_VERIFICATION_INTERRUPTED",
    "CLOSURE_CONFIRMATION_STARTED",
    "CLOSURE_CONFIRMATION_INTERRUPTED",
    "FINAL_CALLBACK_HIDDEN_FOR_FOCUS",
    "FINAL_CALLBACK_RESTORED_AFTER_RELAPSE",
    "RETURN_CONFIRMED",
)

_KEY_EVIDENCE_NAMES: Final = frozenset({
    "COSINE_SESSION_STARTED", "INTENT_GATE_DISPLAYED",
    "RETURN_INTENT_RECORDED", "BREAK_INTENT_RECORDED",
    "RETURN_INTENT_CONVERTED_TO_BREAK", "BREAK_DURATION_COMMITTED",
    "BREAK_STARTED", "HOPPER_TRANSITION", "FINAL_CALLBACK_DISPLAYED",
    "RETURN_CANDIDATE_STARTED", "RETURN_VERIFICATION_COMPLETED",
    "RETURN_VERIFICATION_INTERRUPTED", "CLOSURE_CONFIRMATION_STARTED",
    "CLOSURE_CONFIRMATION_INTERRUPTED", "RETURN_CONFIRMED",
    "FINAL_CALLBACK_RESTORED_AFTER_RELAPSE", "COSINE_SESSION_CLOSED",
})


#: Cap on the number of individual Hopper-switch nodes shown inline in the
#: recent-episode map before they are collapsed to a count marker -- this is
#: a report-map clutter rule (section 18: "avoid clutter... not the full
#: event ledger"), never a change to hopper_count or hopper_transitions.
_MAP_HOPPER_NODE_CAP: Final = 4


def _recent_episode_map_nodes(episode: CosineEpisodeProjection) -> list[str]:
    """Deterministic, compressed milestone chain built ONLY from events that
    actually occurred -- never a generic always-successful pathway."""

    nodes = [episode.starting_platform_label]
    hopper_by_sequence = {hop.sequence: hop for hop in episode.hopper_transitions}
    hop_total = len(episode.hopper_transitions)
    hops_emitted = 0
    collapsed_marker_added = False
    for event in episode.events:
        if event.event_name == "HOPPER_TRANSITION":
            if hop_total > _MAP_HOPPER_NODE_CAP:
                # Preserve the first two and last two switches; collapse the
                # middle run to a truthful count, matching the same
                # collapse principle the Hopper map cap uses.
                if hops_emitted < 2 or hops_emitted >= hop_total - 2:
                    hop = hopper_by_sequence.get(event.sequence)
                    nodes.append(hop.to_platform_label if hop else "Platform switch")
                elif not collapsed_marker_added:
                    nodes.append(f"… {hop_total - 4} recorded switches …")
                    collapsed_marker_added = True
            else:
                hop = hopper_by_sequence.get(event.sequence)
                nodes.append(hop.to_platform_label if hop else "Platform switch")
            hops_emitted += 1
        elif event.event_name in _MAP_MILESTONES:
            nodes.append(_MAP_MILESTONES[event.event_name])
    if episode.is_closed:
        closing_label = closure_reason_label(episode.closure_reason)
        if closing_label != nodes[-1]:
            nodes.append(closing_label)
        if episode.closure_outcome:
            closing_label = outcome_label(episode.closure_outcome)
            if closing_label != nodes[-1]:
                nodes.append(closing_label)
    else:
        nodes.append("OPEN EVIDENCE")
    return nodes


#: Eligibility set for "does this episode contain return-pathway evidence"
#: (Micro Correction 1, finding C) -- a narrower set than _RETURN_CHAIN_NAMES
#: above, which is still used unchanged to build the chain DISPLAY once an
#: episode has been selected. Deliberately excludes
#: FINAL_CALLBACK_HIDDEN_FOR_FOCUS, matching the correction's exact list.
_RETURN_ELIGIBILITY_NAMES: Final = frozenset({
    "RETURN_CANDIDATE_STARTED", "RETURN_VERIFICATION_COMPLETED",
    "RETURN_VERIFICATION_INTERRUPTED", "CLOSURE_CONFIRMATION_STARTED",
    "CLOSURE_CONFIRMATION_INTERRUPTED", "FINAL_CALLBACK_RESTORED_AFTER_RELAPSE",
    "RETURN_CONFIRMED",
})


def _select_return_episode(projection: CosineAnalysisProjection):
    """Most recent durable episode containing return-pathway evidence, using
    the existing (already newest-first) episode ordering -- a deterministic
    specimen rule for the section dedicated to Return, not cherry-picking."""

    for spec in projection.episodes:
        if any(e.event_name in _RETURN_ELIGIBILITY_NAMES for e in spec.events):
            return spec
    return None


def _return_chain(episode: CosineEpisodeProjection) -> list:
    return [e for e in episode.events if e.event_name in _RETURN_CHAIN_NAMES]


def _return_summary(episode: CosineEpisodeProjection) -> str:
    if any(e.event_name == "RETURN_CONFIRMED" for e in episode.events):
        return (
            "This episode contains a return candidate followed by completed "
            "verification and recorded return confirmation."
        )
    if episode.closure_reason or episode.closure_outcome:
        return (
            f"This episode closed with reason {closure_reason_label(episode.closure_reason)} "
            f"and is recorded as {outcome_label(episode.closure_outcome)}; no recorded return "
            "confirmation exists."
        )
    return (
        "This episode contains no recorded return confirmation and is therefore "
        "not presented as a confirmed return."
    )


def _select_hopper_episode(projection: CosineAnalysisProjection):
    """Most recent durable episode with recorded Hopper transitions, using
    the existing (already newest-first) episode ordering -- a deterministic
    specimen rule for the section dedicated to Hopper, not cherry-picking."""

    for spec in projection.episodes:
        if spec.hopper_count > 0 and spec.hopper_transitions:
            return spec
    return None


def _hopper_path_nodes(episode: CosineEpisodeProjection) -> list[str]:
    return [episode.starting_platform_label] + [
        hop.to_platform_label for hop in episode.hopper_transitions
    ]


def _select_key_evidence(episode: CosineEpisodeProjection, cap: int = KEY_EVIDENCE_ROW_CAP):
    """Deterministic <= ``cap`` row selection -- never a random sample.

    Always preserves: the first session-started event, the recorded choice,
    the first and last Hopper transition, the break start, the final
    callback, the latest return-verification event, the return-confirmed
    event and the closure event, whichever of those exist -- then fills any
    remaining capacity in sequence order.
    """

    candidates = [e for e in episode.events if e.event_name in _KEY_EVIDENCE_NAMES]
    total = len(candidates)
    if total <= cap:
        return candidates, total

    preserved: dict[str, object] = {}

    def keep_first(name: str) -> None:
        for e in candidates:
            if e.event_name == name:
                preserved[e.event_id] = e
                return

    def keep_last(names) -> None:
        for e in reversed(candidates):
            if e.event_name in names:
                preserved[e.event_id] = e
                return

    keep_first("COSINE_SESSION_STARTED")
    keep_first("RETURN_INTENT_RECORDED")
    keep_first("BREAK_INTENT_RECORDED")
    hoppers = [e for e in candidates if e.event_name == "HOPPER_TRANSITION"]
    if hoppers:
        preserved[hoppers[0].event_id] = hoppers[0]
        preserved[hoppers[-1].event_id] = hoppers[-1]
    keep_first("BREAK_STARTED")
    keep_first("FINAL_CALLBACK_DISPLAYED")
    keep_last({"RETURN_VERIFICATION_COMPLETED", "RETURN_VERIFICATION_INTERRUPTED"})
    keep_first("RETURN_CONFIRMED")
    keep_first("COSINE_SESSION_CLOSED")

    remaining = cap - len(preserved)
    if remaining > 0:
        for e in candidates:
            if len(preserved) >= cap:
                break
            if e.event_id not in preserved:
                preserved[e.event_id] = e

    selected = sorted(preserved.values(), key=lambda e: e.sequence)[:cap]
    return selected, total


def _evidence_detail(event, episode: CosineEpisodeProjection) -> str:
    """Short sanitized factual detail only -- never the raw payload."""

    if event.event_name in ("BREAK_DURATION_COMMITTED", "BREAK_STARTED"):
        return f"{episode.chosen_break_minutes} min break" if episode.chosen_break_minutes else "—"
    if event.event_name == "HOPPER_TRANSITION":
        hop = next((h for h in episode.hopper_transitions if h.sequence == event.sequence), None)
        if hop:
            return f"{hop.from_platform_label} → {hop.to_platform_label}"
        return "—"
    if event.event_name in ("RETURN_INTENT_RECORDED", "BREAK_INTENT_RECORDED"):
        return _choice_text(episode)
    if event.event_name == "RETURN_CONFIRMED":
        return outcome_label(episode.closure_outcome)
    if event.event_name == "COSINE_SESSION_CLOSED":
        return closure_presentation(episode)
    return "—"


# ---------------------------------------------------------------------------
# ReportLab presentation
# ---------------------------------------------------------------------------

_NAVY: Final = colors.HexColor("#0E2439")
_TEAL: Final = colors.HexColor("#0F9C8E")
_MUTED: Final = colors.HexColor("#5B7286")
_HAIRLINE: Final = colors.HexColor("#CBD8E1")
_TABLE_BODY: Final = colors.HexColor("#F6FAFC")


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "Title": ParagraphStyle(
            "CosinePdfTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=20, leading=24, textColor=_NAVY, alignment=TA_LEFT, spaceAfter=2,
        ),
        "Subtitle": ParagraphStyle(
            "CosinePdfSubtitle", parent=base["BodyText"], fontSize=9.5, leading=13,
            textColor=_MUTED, alignment=TA_LEFT,
        ),
        "H1": ParagraphStyle(
            "CosinePdfH1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=11, leading=13, textColor=_NAVY, spaceBefore=5, spaceAfter=2.5,
        ),
        "Body": ParagraphStyle(
            "CosinePdfBody", parent=base["BodyText"], fontSize=8, leading=10.5,
            textColor=colors.HexColor("#233241"),
        ),
        "Muted": ParagraphStyle(
            "CosinePdfMuted", parent=base["BodyText"], fontSize=7, leading=9,
            textColor=_MUTED,
        ),
        "Map": ParagraphStyle(
            "CosinePdfMap", parent=base["BodyText"], fontSize=7.5, leading=10.5,
            textColor=colors.HexColor("#123653"),
        ),
        "Cell": ParagraphStyle("CosinePdfCell", fontName="Helvetica", fontSize=6.5, leading=7.8,
                                textColor=colors.HexColor("#233241")),
        "CellHead": ParagraphStyle("CosinePdfCellHead", fontName="Helvetica-Bold", fontSize=6.5,
                                    leading=7.8, textColor=colors.white),
    }


def _escape(value: object) -> str:
    return html.escape(" ".join(str(value or "").split())[:400])


def _table(rows: list[list[str]], widths: list[float], styles: dict) -> Table:
    data = []
    for row_index, row in enumerate(rows):
        style = styles["CellHead"] if row_index == 0 else styles["Cell"]
        data.append([Paragraph(_escape(cell), style) for cell in row])
    table = Table(data, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), _NAVY),
            ("BACKGROUND", (0, 1), (-1, -1), _TABLE_BODY),
            ("GRID", (0, 0), (-1, -1), 0.35, _HAIRLINE),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3.5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3.5),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])
    )
    return table


def _map_card(nodes: list[str], styles: dict, empty_text: str) -> Table:
    """A compact single-cell 'map' card: bold platform/milestone chips joined
    by arrows, built from real event evidence only. Rendered as one wrapping
    Paragraph inside a light bordered card, so it can never overflow a page
    regardless of node count -- unlike a fixed-column node table."""

    if not nodes:
        text = f"<i>{_escape(empty_text)}</i>"
    else:
        text = "&nbsp;&nbsp;→&nbsp;&nbsp;".join(f"<b>{_escape(node)}</b>" for node in nodes)
    para = Paragraph(text, styles["Map"])
    card = Table([[para]], colWidths=[180 * mm])
    card.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EFF6F8")),
            ("BOX", (0, 0), (-1, -1), 0.6, _TEAL),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 4.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ])
    )
    return card


def _section_title(text: str, styles: dict) -> Paragraph:
    return Paragraph(_escape(text), styles["H1"])


def _footer(canvas, document) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(_MUTED)
    canvas.drawString(16 * mm, 9 * mm, "MYELIN · COSINE behavioral evidence")
    canvas.drawRightString(A4[0] - 16 * mm, 9 * mm, f"Page {document.page} of 2")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Page content
# ---------------------------------------------------------------------------

_PRINCIPLE_TEXT: Final = (
    "COSINE observes supported OTT streaming behaviour and records factual "
    "interaction, user-choice, platform-transition, break and return evidence. "
    "It regulates streaming through explicit choice-oriented interventions while "
    "preserving durable event evidence for later analysis."
)
_PRINCIPLE_BOUNDARY_TEXT: Final = (
    "COSINE describes observed software behaviour only and does not infer "
    "attention, emotion, motivation or neurological state."
)
_INTENT_DESCRIPTION_TEXT: Final = (
    "Intent records represent explicit durable user-choice events captured by "
    "COSINE. A later conversion from return intention to break is reported only "
    "when a corresponding conversion event exists; it is not inferred from "
    "elapsed time or final outcome."
)
_SCIENTIFIC_BOUNDARY_TEXT: Final = (
    "COSINE records observable supported-OTT interaction, explicit user-choice "
    "events, platform transitions, intervention presentation, break events and "
    "return-related evidence. The report describes durable software evidence "
    "only. It does not infer attention, emotion, motivation, health, dopamine, "
    "cognition or neurological state."
)
_SEQUENCE_NOTE_TEXT: Final = "Event ordering within an episode follows durable sequence."
_TIMESTAMP_NOTE_TEXT: Final = (
    "Displayed timestamps are presentation labels and do not replace sequence "
    "as the episode ordering authority."
)


def _overview_summary(projection: CosineAnalysisProjection) -> str:
    overview = projection.overview
    captured = overview.captured_episode_count
    returns = overview.confirmed_return_count
    breaks = overview.break_started_count
    if captured is None or returns is None or breaks is None:
        return "The analysed database snapshot does not supply a certified overview count."
    return (
        f"The analysed database snapshot contains {captured} captured COSINE "
        f"episode{'s' if captured != 1 else ''}. {returns} contain a recorded "
        f"return confirmation and {breaks} contain a recorded break start. "
        f"Usual Return remains {overview.usual_return_status} because its "
        f"Phase-2 definition is not certified."
    )


def _page_one(
    projection: CosineAnalysisProjection,
    episodes_window: tuple,
    recent: CosineEpisodeProjection,
    aliases: dict,
    styles: dict,
) -> list:
    story: list = []
    story.append(_section_title("1. COSINE principle", styles))
    story.append(Paragraph(_PRINCIPLE_TEXT, styles["Body"]))
    story.append(Paragraph(_PRINCIPLE_BOUNDARY_TEXT, styles["Muted"]))

    story.append(_section_title("2. Total overview", styles))
    story.append(Paragraph(_escape(_overview_summary(projection)), styles["Body"]))

    story.append(_section_title("3. Episodes", styles))
    story.append(Paragraph(
        "Episode IDs use the UTC episode-start date; displayed dates and times use "
        "the selected report time zone.",
        styles["Muted"],
    ))
    total_episodes = len(projection.episodes)
    if total_episodes > EPISODE_ROW_CAP:
        story.append(Paragraph(
            f"Showing {EPISODE_ROW_CAP} most recent of {total_episodes} captured episodes.",
            styles["Muted"],
        ))
    rows = [["EPISODE", "DATE", "PLATFORM", "CHOICE", "HOPPER", "OUTCOME"]]
    for spec in episodes_window:
        rows.append([
            aliases.get((spec.cosine_session_id, spec.generation), "COS-UNKNOWN"),
            date_only(spec.started_at_display),
            spec.starting_platform_label,
            _choice_text(spec),
            str(spec.hopper_count),
            _compact_outcome(spec),
        ])
    story.append(_table(rows, [24 * mm, 22 * mm, 28 * mm, 42 * mm, 14 * mm, 48 * mm], styles))

    story.append(_section_title("4. Recent episode map", styles))
    recent_id = aliases.get((recent.cosine_session_id, recent.generation), "COS-UNKNOWN")
    story.append(Paragraph(f"Episode {_escape(recent_id)}", styles["Muted"]))
    story.append(_map_card(
        _recent_episode_map_nodes(recent), styles,
        "No evidence is available for the recent episode.",
    ))

    story.append(_section_title("5. Intent", styles))
    intent_rows = [["EPISODE", "PLATFORM", "RECORDED CHOICE", "OUTCOME"]]
    for spec in episodes_window:
        if not spec.user_choice:
            continue
        intent_rows.append([
            aliases.get((spec.cosine_session_id, spec.generation), "COS-UNKNOWN"),
            spec.starting_platform_label,
            _choice_text(spec),
            _compact_outcome(spec),
        ])
    if len(intent_rows) > 1:
        story.append(_table(intent_rows, [26 * mm, 34 * mm, 68 * mm, 50 * mm], styles))
    else:
        story.append(Paragraph("No episode in this window recorded a durable choice.", styles["Muted"]))
    story.append(Paragraph(_INTENT_DESCRIPTION_TEXT, styles["Muted"]))

    story.append(_section_title("6. Return pathway", styles))
    return_episode = _select_return_episode(projection)
    if return_episode is None:
        story.append(Paragraph(
            "No recorded return pathway exists in the analysed episodes.", styles["Muted"],
        ))
    else:
        return_id = aliases.get(
            (return_episode.cosine_session_id, return_episode.generation), "COS-UNKNOWN"
        )
        story.append(Paragraph(f"Episode {_escape(return_id)}", styles["Muted"]))
        chain = _return_chain(return_episode)
        if chain:
            story.append(_map_card([event_label(e.event_name) for e in chain], styles, ""))
        else:
            story.append(Paragraph(
                "No confirmed return pathway was recorded for this episode.", styles["Muted"],
            ))
        story.append(Paragraph(_escape(_return_summary(return_episode)), styles["Body"]))
    return story


def _page_two(
    projection: CosineAnalysisProjection,
    episodes_window: tuple,
    recent: CosineEpisodeProjection,
    aliases: dict,
    styles: dict,
    total_episode_count: int,
) -> list:
    story: list = [PageBreak()]
    story.append(_section_title("7. Overall Hopper", styles))
    if total_episode_count > EPISODE_ROW_CAP:
        story.append(Paragraph(
            f"Showing {EPISODE_ROW_CAP} most recent of {total_episode_count} captured episodes.",
            styles["Muted"],
        ))
    story.append(Paragraph(
        "Observed platform transitions recorded within each episode. Hopper is a "
        "chronology of switches, not a causal or effectiveness measure.",
        styles["Muted"],
    ))
    rows = [["EPISODE", "START PLATFORM", "PLATFORM PATH", "SWITCHES", "OUTCOME"]]
    for spec in episodes_window:
        path = " → ".join(_hopper_path_nodes(spec))
        rows.append([
            aliases.get((spec.cosine_session_id, spec.generation), "COS-UNKNOWN"),
            spec.starting_platform_label,
            path,
            str(spec.hopper_count),
            _compact_outcome(spec),
        ])
    story.append(_table(rows, [24 * mm, 30 * mm, 66 * mm, 18 * mm, 40 * mm], styles))

    story.append(_section_title("8. Recent Hopper map", styles))
    hopper_episode = _select_hopper_episode(projection)
    if hopper_episode is None:
        story.append(_map_card(
            [], styles, "No Hopper transition was recorded in the analysed episodes.",
        ))
    else:
        hopper_id = aliases.get(
            (hopper_episode.cosine_session_id, hopper_episode.generation), "COS-UNKNOWN"
        )
        story.append(Paragraph(f"Episode {_escape(hopper_id)}", styles["Muted"]))
        story.append(_map_card(_hopper_collapsed_nodes(hopper_episode), styles, ""))

    story.append(_section_title("9. Key evidence", styles))
    selected, total = _select_key_evidence(recent)
    story.append(Paragraph(
        f"{len(selected)} key milestones shown · {recent.event_count} total recorded events",
        styles["Muted"],
    ))
    evidence_rows = [["SEQ", "TIME", "EVENT", "CLASS", "PLATFORM", "EVIDENCE"]]
    for event in selected:
        evidence_rows.append([
            str(event.sequence),
            time_only(event.occurred_at_display),
            event_label(event.event_name),
            event_class_label(event.event_class),
            event.platform_label,
            _evidence_detail(event, recent),
        ])
    story.append(_table(evidence_rows, [8 * mm, 20 * mm, 42 * mm, 22 * mm, 30 * mm, 56 * mm], styles))
    if recent.hold_context:
        story.append(Paragraph(
            "SINE handoff context recorded · mechanism interpretation deferred.",
            styles["Muted"],
        ))

    story.append(_section_title("10. Scientific description", styles))
    story.append(Paragraph(_SCIENTIFIC_BOUNDARY_TEXT, styles["Body"]))
    story.append(Paragraph(_SEQUENCE_NOTE_TEXT, styles["Muted"]))
    story.append(Paragraph(_TIMESTAMP_NOTE_TEXT, styles["Muted"]))
    return story


def _hopper_collapsed_nodes(episode: CosineEpisodeProjection) -> list[str]:
    hops = episode.hopper_transitions
    nodes = [episode.starting_platform_label]
    if len(hops) <= HOPPER_MAP_COLLAPSE_THRESHOLD:
        nodes.extend(hop.to_platform_label for hop in hops)
        return nodes
    first_two, last_two = hops[:2], hops[-2:]
    nodes.extend(hop.to_platform_label for hop in first_two)
    nodes.append(f"… {len(hops) - 4} recorded switches …")
    nodes.extend(hop.to_platform_label for hop in last_two)
    return nodes


def build_cosine_report_pdf(
    projection: CosineAnalysisProjection,
    request: CosinePdfReportRequest,
) -> CosinePdfReportResult:
    _require_evidence(projection)

    episodes_window = tuple(projection.episodes[:EPISODE_ROW_CAP])
    recent = projection.latest_or_selected_recent_episode
    if recent is None:
        recent = projection.episodes[0]
    aliases = episode_display_ids(projection.episodes)
    styles = _styles()

    output = Path(request.output_path).expanduser().resolve()
    if output.exists() and not request.overwrite:
        raise FileExistsError(f"report already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}-{secrets.token_hex(6)}.tmp.pdf")

    generated_text, zone_label = _generated_display(projection)
    zone_line = f"Time zone: {zone_label}"
    generated_line = f"Generated: {generated_text}"

    story: list = [
        Paragraph(_escape("MYELIN"), styles["Subtitle"]),
        Paragraph(_escape(request.title), styles["Title"]),
        Paragraph(_escape(request.subtitle), styles["Subtitle"]),
        Spacer(1, 1 * mm),
        Paragraph(_escape(f"{generated_line}  ·  {zone_line}"), styles["Muted"]),
        Spacer(1, 2 * mm),
    ]
    story.extend(_page_one(projection, episodes_window, recent, aliases, styles))
    story.extend(_page_two(projection, episodes_window, recent, aliases, styles, len(projection.episodes)))

    try:
        document = SimpleDocTemplate(
            str(temporary),
            pagesize=A4,
            leftMargin=15 * mm,
            rightMargin=15 * mm,
            topMargin=12 * mm,
            bottomMargin=13 * mm,
            title=request.title,
            author="",
            subject="MYELIN COSINE behavioral evidence report",
        )
        document.build(story, onFirstPage=_footer, onLaterPages=_footer)
        if request.overwrite:
            os.replace(temporary, output)
        else:
            os.link(temporary, output)
            temporary.unlink(missing_ok=True)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise

    recent_id = aliases.get((recent.cosine_session_id, recent.generation), "COS-UNKNOWN")
    selected, _ = _select_key_evidence(recent)
    return CosinePdfReportResult(
        output_path=str(output),
        generated_at_utc=projection.generated_at_utc,
        byte_size=output.stat().st_size,
        episode_count=len(projection.episodes),
        recent_episode_id=recent_id,
        total_recent_event_count=recent.event_count,
        shown_key_evidence_count=len(selected),
    )


__all__ = [
    "REPORT_SCHEMA_VERSION",
    "CosineReportError",
    "CosinePdfReportRequest",
    "CosinePdfReportResult",
    "build_cosine_report_pdf",
    "episode_display_ids",
    "display_episode_id",
]
