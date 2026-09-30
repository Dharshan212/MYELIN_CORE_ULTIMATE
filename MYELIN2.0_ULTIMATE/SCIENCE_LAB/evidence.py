"""Science Lab evidence read/write boundary.

This will become the ONE place that persists and reads Science-Lab-specific
evidence.  Phase 2.1 extends the existing read-only boundary to the seven
durable sources that have certified read paths: SINE, Normal Break, MINE,
COSINE, MIRL, Study, and COSECANT.  It never opens SQLite directly and never
queries an organ's raw event table.

Still future work, not implemented here:

- create a Science Lab experiment record (id form ``MYL-DDMMYYYY-SCI##``,
  e.g. ``MYL-11092026-SCI01``) -- note that merely opening Science Lab,
  attaching to a session, or selecting any chapter including Chapter 3,
  must NOT create one; only an explicit future experiment lifecycle may;
- store experiment metadata;
- link authoritative source-event IDs by durable reference rather than by
  value (this module currently returns the read model's own projection
  rows directly -- linking-by-ID is part of the not-yet-built persistence
  layer);
- store Science-Lab-specific derived evidence that has no other owner;
- read back completed evidence;
- freeze completed evidence where appropriate;
- produce report-ready evidence structures for ``report.py``.

ONE SOURCE OF TRUTH: this module must never duplicate an authoritative organ
event record.  It reads those records through their existing read authorities;
it does not re-record them, and it must never read their tables directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

#: Coverage states.  Deliberately three, not two: a source that was read
#: successfully but has no matching rows for this session (NO_EVIDENCE) is
#: scientifically different from a source with no safe read path at all
#: (UNAVAILABLE) -- collapsing both to "0" would hide that distinction.
COVERAGE_AVAILABLE: Final = "AVAILABLE"
COVERAGE_NO_EVIDENCE: Final = "NO_EVIDENCE"
COVERAGE_UNAVAILABLE: Final = "UNAVAILABLE"

#: Architecturally part of Science Lab but not yet backed by a complete,
#: research-grade durable evidence contract.
_UNAVAILABLE_SOURCES: Final = (
    ("RESOURCE_INTENT", "no_durable_event_identity"),
)


@dataclass(frozen=True, slots=True)
class SourceCoverage:
    """One organ's read-availability for one Science Lab evidence snapshot."""

    source_system: str
    status: str  # AVAILABLE / NO_EVIDENCE / UNAVAILABLE
    reason: str
    item_count: int | None  # None only when status is UNAVAILABLE


@dataclass(frozen=True, slots=True)
class PersistedFactSourceEvidence:
    session_id: int
    records: tuple[object, ...]  # PERSISTENCE.storage.ScienceLabSourceRecord rows


@dataclass(frozen=True, slots=True)
class MineSourceEvidence:
    session_id: int
    episodes: tuple[object, ...]  # MINE.read_model.MineEpisodeProjection rows
    # Raw durable MINE.mine.MineEvent rows for this session, read through the
    # same canonical whole-ledger authority SCIENCE_LAB/chapter6_lifetime.py
    # already uses (PERSISTENCE.storage.read_mine_events).  These exist ONLY
    # to correlate each already-projected episode's durable monotonic_ns span
    # against the selected experiment's [start,end) window -- they must never
    # be used to re-derive branch, closure, dwell, or any other MINE meaning,
    # which stays exclusively owned by MineEpisodeProjection above.
    raw_events: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class CosineSourceEvidence:
    session_id: int
    episodes: tuple[object, ...]  # COSINE.read_model.CosineEpisodeProjection rows
    # Raw durable COSINE.cosine.CosineEvent rows for this session, read
    # through the same canonical whole-ledger authority
    # SCIENCE_LAB/chapter6_lifetime.py already uses
    # (PERSISTENCE.storage.read_cosine_events).  Same monotonic-correlation-
    # only purpose and restriction as MineSourceEvidence.raw_events above.
    raw_events: tuple[object, ...] = ()
    # Official ``COS-DDMMYYYY-NN`` display codes for the episodes above,
    # each a ``(cosine_session_id, generation, display_episode_id)`` triple.
    # Computed by COSINE.report.episode_display_ids() over COSINE's own
    # FULL, cross-session episode list (before the per-session filter above
    # is applied) -- the same live, global daily sequence the COSINE
    # dashboard shows -- never recomputed locally against only this
    # session's episodes, which would silently disagree with the dashboard
    # whenever another session has an episode on the same UTC date.
    display_ids: tuple[tuple[str, int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MirlSourceEvidence:
    session_id: int
    events: tuple[object, ...]  # full durable MIRL event history for this session
    # This session's own rows from MIRL's live, globally-masked episode
    # projection (MIRL.read_model's LiveMirlEpisodeRow, via
    # read_mirl_snapshot()'s active_episodes + recently_closed_episodes,
    # already carrying the official cross-session ``EPI-DDMMYYYY-NN``
    # short_display_id).  Filtered to this session only; never recomputed.
    # NOTE: recently_closed_episodes is capped to MIRL's own most-recent 100
    # -- an episode that aged out of that cap will not appear here, and its
    # official display code becomes unresolvable rather than guessed.
    live_mirl_rows: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class ScienceLabEvidenceSnapshot:
    """One read-only, session-scoped evidence gathering result.

    Every included row is an immutable object returned by an approved read
    authority; nothing here is copied into a new Science Lab-owned fact.
    """

    parent_session_id: int
    generated_at_utc: str
    source_coverage: tuple[SourceCoverage, ...]
    sine: PersistedFactSourceEvidence | None
    normal_break: PersistedFactSourceEvidence | None
    mine: MineSourceEvidence | None
    cosine: CosineSourceEvidence | None
    mirl: MirlSourceEvidence | None
    study: PersistedFactSourceEvidence | None
    cosecant: PersistedFactSourceEvidence | None
    resource_intent: None
    limitations: tuple[str, ...]
    secant: object | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _fact_source_evidence(
    *,
    source_system: str,
    session_id: int,
    reader,
    coverage: list[SourceCoverage],
    limitations: list[str],
) -> PersistedFactSourceEvidence | None:
    try:
        records = tuple(reader(session_id))
    except Exception as error:
        reason = f"read_error:{type(error).__name__}"
        coverage.append(
            SourceCoverage(source_system, COVERAGE_UNAVAILABLE, reason, None)
        )
        limitations.append(
            f"{source_system}: unavailable ({reason}) for this snapshot."
        )
        return None

    coverage.append(
        SourceCoverage(
            source_system,
            COVERAGE_AVAILABLE if records else COVERAGE_NO_EVIDENCE,
            "",
            len(records),
        )
    )
    return PersistedFactSourceEvidence(
        session_id=session_id,
        records=records,
    )


def gather_session_evidence(
    parent_session_id: int,
    *,
    presentation_timezone: str = "local",
) -> ScienceLabEvidenceSnapshot:
    """Read all certified durable sources for exactly one parent session.

    Read-only; writes nothing, starts no engine, and creates no experiment.
    """

    from PERSISTENCE.storage import (
        read_control_station_analytics,
        read_cosine_events,
        read_mine_events,
        read_science_lab_cosecant_records,
        read_science_lab_mirl_events,
        read_science_lab_normal_break_records,
        read_science_lab_sine_records,
        read_science_lab_study_records,
    )

    bundle = read_control_station_analytics(presentation_timezone)

    coverage: list[SourceCoverage] = []
    limitations: list[str] = []

    sine_evidence = _fact_source_evidence(
        source_system="SINE",
        session_id=parent_session_id,
        reader=read_science_lab_sine_records,
        coverage=coverage,
        limitations=limitations,
    )
    normal_break_evidence = _fact_source_evidence(
        source_system="NORMAL_BREAK",
        session_id=parent_session_id,
        reader=read_science_lab_normal_break_records,
        coverage=coverage,
        limitations=limitations,
    )

    mine_projection = getattr(bundle, "mine", None)
    mine_evidence: MineSourceEvidence | None = None
    if mine_projection is not None and getattr(mine_projection, "available", False):
        matched = tuple(
            episode
            for episode in getattr(mine_projection, "episodes", ())
            if getattr(episode, "session_id", None) == parent_session_id
        )
        try:
            raw_mine_events = tuple(
                event
                for event in read_mine_events()
                if getattr(event, "parent_session_id", None) == parent_session_id
            )
        except Exception:
            # The projection above remains the certified MINE evidence either
            # way; losing only the raw monotonic correlation source must not
            # fail the whole snapshot.  Chapter 3 sees an empty raw_events
            # tuple and, per its own integrity rule, treats every MINE
            # episode as not provably experiment-scoped rather than guessing.
            raw_mine_events = ()
        mine_evidence = MineSourceEvidence(
            session_id=parent_session_id, episodes=matched, raw_events=raw_mine_events
        )
        coverage.append(
            SourceCoverage(
                "MINE",
                COVERAGE_AVAILABLE if matched else COVERAGE_NO_EVIDENCE,
                "",
                len(matched),
            )
        )
    else:
        reason = "read_error" if mine_projection is not None and getattr(mine_projection, "read_error", None) else "projection_unavailable"
        coverage.append(SourceCoverage("MINE", COVERAGE_UNAVAILABLE, reason, None))
        limitations.append(f"MINE: unavailable ({reason}) for this snapshot.")

    cosine_projection = getattr(bundle, "cosine", None)
    cosine_evidence: CosineSourceEvidence | None = None
    if cosine_projection is not None and getattr(cosine_projection, "available", False):
        # Official display codes are computed over COSINE's FULL, unfiltered
        # episode list -- the same live, cross-session daily sequence the
        # COSINE dashboard already shows -- before narrowing to this session.
        from COSINE.report import episode_display_ids as _cosine_official_display_ids

        all_episodes = tuple(getattr(cosine_projection, "episodes", ()))
        official_display_ids = _cosine_official_display_ids(all_episodes)
        matched = tuple(
            episode
            for episode in all_episodes
            if getattr(episode, "parent_session_id", None) == parent_session_id
        )
        matched_display_ids = tuple(
            (
                str(getattr(episode, "cosine_session_id", "")),
                int(getattr(episode, "generation", 0) or 0),
                official_display_ids.get(
                    (
                        getattr(episode, "cosine_session_id", ""),
                        getattr(episode, "generation", None),
                    ),
                    "",
                ),
            )
            for episode in matched
        )
        try:
            raw_cosine_events = tuple(
                event
                for event in read_cosine_events()
                if getattr(event, "session_id", None) == parent_session_id
            )
        except Exception:
            # Same fallback rationale as MINE above: the projection stays
            # certified; only the monotonic correlation source is lost.
            raw_cosine_events = ()
        cosine_evidence = CosineSourceEvidence(
            session_id=parent_session_id,
            episodes=matched,
            raw_events=raw_cosine_events,
            display_ids=matched_display_ids,
        )
        coverage.append(
            SourceCoverage(
                "COSINE",
                COVERAGE_AVAILABLE if matched else COVERAGE_NO_EVIDENCE,
                "",
                len(matched),
            )
        )
    else:
        reason = "read_error" if cosine_projection is not None and getattr(cosine_projection, "read_error", None) else "projection_unavailable"
        coverage.append(SourceCoverage("COSINE", COVERAGE_UNAVAILABLE, reason, None))
        limitations.append(f"COSINE: unavailable ({reason}) for this snapshot.")

    mirl_evidence: MirlSourceEvidence | None = None
    try:
        mirl_events = tuple(read_science_lab_mirl_events(parent_session_id))
    except Exception as error:
        reason = f"read_error:{type(error).__name__}"
        coverage.append(SourceCoverage("MIRL", COVERAGE_UNAVAILABLE, reason, None))
        limitations.append(f"MIRL: unavailable ({reason}) for this snapshot.")
    else:
        # bundle.live_mirl is MIRL's own live, globally-masked episode
        # projection (already computed across every session by
        # read_mirl_snapshot() inside read_control_station_analytics()
        # above) -- narrowed to this session only here, never recomputed.
        live_mirl = getattr(bundle, "live_mirl", None)
        live_mirl_rows = tuple(
            row
            for row in (
                tuple(getattr(live_mirl, "active_episodes", ()))
                + tuple(getattr(live_mirl, "recently_closed_episodes", ()))
            )
            if getattr(row, "session_id", None) == parent_session_id
        )
        mirl_evidence = MirlSourceEvidence(
            session_id=parent_session_id,
            events=mirl_events,
            live_mirl_rows=live_mirl_rows,
        )
        coverage.append(
            SourceCoverage(
                "MIRL",
                COVERAGE_AVAILABLE if mirl_events else COVERAGE_NO_EVIDENCE,
                "",
                len(mirl_events),
            )
        )

    study_evidence = _fact_source_evidence(
        source_system="STUDY",
        session_id=parent_session_id,
        reader=read_science_lab_study_records,
        coverage=coverage,
        limitations=limitations,
    )
    cosecant_evidence = _fact_source_evidence(
        source_system="COSECANT",
        session_id=parent_session_id,
        reader=read_science_lab_cosecant_records,
        coverage=coverage,
        limitations=limitations,
    )

    from .secant_adapter import read_secant_source
    secant = read_secant_source(parent_session_id)
    coverage.append(SourceCoverage("SECANT", secant.status, secant.reason,
        len(secant.episodes) if secant.status != COVERAGE_UNAVAILABLE else None))
    if secant.status == COVERAGE_UNAVAILABLE:
        limitations.append("SECANT: " + secant.reason)

    for source_system, reason in _UNAVAILABLE_SOURCES:
        coverage.append(SourceCoverage(source_system, COVERAGE_UNAVAILABLE, reason, None))
        limitations.append(
            "RESOURCE_INTENT: unavailable (no_durable_event_identity) until a "
            "complete durable Resource Intent evidence contract is approved."
        )

    return ScienceLabEvidenceSnapshot(
        parent_session_id=parent_session_id,
        generated_at_utc=_utc_now(),
        source_coverage=tuple(coverage),
        secant=secant,
        sine=sine_evidence,
        normal_break=normal_break_evidence,
        mine=mine_evidence,
        cosine=cosine_evidence,
        mirl=mirl_evidence,
        study=study_evidence,
        cosecant=cosecant_evidence,
        resource_intent=None,
        limitations=tuple(limitations),
    )
