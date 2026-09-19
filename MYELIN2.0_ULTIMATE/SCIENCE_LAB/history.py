"""SCIENCE_LAB/history.py -- read-only Chapter 5 experiment-history adapter.

Chief's Chapter 5 history correction (20260917): reconstructs one SPECIFIC,
already-completed Science Lab experiment's certified Chapter 3 result
package from durable evidence, for read-only historical review and export --
entirely independent of the live in-process
``ScienceLabCoordinator``/``Chapter3TransferReceipt`` state that resets on
every MYELIN restart.

This module is Qt-free and touches no live organ runtime.  It reuses, never
duplicates, the existing certification pipeline:

    PERSISTENCE.storage read authorities (durable experiment metadata)
            |
            v
    SCIENCE_LAB.evidence.gather_session_evidence (read-only snapshot)
            |
            v
    SCIENCE_LAB.analysis.analyze_finalized_session (the SAME certification
    the live post-STOP flow uses)

The tuple passed to ``analyze_finalized_session`` contains ONLY the one
selected experiment record -- never a session's full history -- so the
existing "pick the latest completed experiment" selection rule can never
silently substitute a different experiment than the one actually chosen.

It performs no writes and calls none of:
    ScienceLabCoordinator.finalize_clean_stop  (experiment lifecycle write)
    ScienceLabExperimentLifecycle.start / end  (lifecycle writes)
    Chapter3ResultHandoff.transfer             (mints a new LIVE receipt)

A reconstructed package is never claimed to be a byte-for-byte restoration
of an original in-memory receipt -- the original ``finalized_at_utc`` value
used by a past process run was never itself persisted.  Instead, the
parent MYELIN session's own durable closure timestamp
(``PERSISTENCE.storage.read_session_closed_at_utc``) is used as the
authoritative session-finalization time, and every successful result is
labelled RECONSTRUCTION_LABEL below rather than TRANSFERRED.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from PERSISTENCE.storage import (
    ScienceLabExperimentRecord,
    read_all_science_lab_experiments,
    read_science_lab_experiment,
    read_session_closed_at_utc,
)

from .analysis import CERTIFIED, Chapter3ResultPackage, analyze_finalized_session
from .engine import ScienceLabFinalizedSession
from .evidence import gather_session_evidence

#: This module's own outcome vocabulary -- deliberately distinct from
#: ``SCIENCE_LAB.analysis``'s ``Chapter3AnalysisOutcome.status`` values,
#: since a reconstruction can fail for reasons analysis.py never sees
#: (unknown experiment id, unreadable session closure, etc).
HISTORY_CERTIFIED: Final = "CERTIFIED"
HISTORY_UNAVAILABLE: Final = "UNAVAILABLE"

#: Shown next to every successfully reconstructed historical result --
#: never "TRANSFERRED", which remains reserved for the live receipt path.
RECONSTRUCTION_LABEL: Final = "HISTORICAL RECONSTRUCTION"


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """One durable Science Lab experiment row for the SHOW HISTORY list.

    Listing never attempts certification for every row (that would mean
    gathering full session evidence for every row on every open of the
    panel) -- ``eligible`` reflects only structural completeness (status
    and a valid durable end boundary).  Full certification is attempted
    only once, when the user actually selects a row, in
    ``reconstruct_historical_experiment``.
    """

    experiment_id: str
    parent_session_id: int
    status: str
    started_at_utc: str
    ended_at_utc: str | None
    end_reason: str
    eligible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class HistoryReconstruction:
    """Outcome of reconstructing one specific historical experiment."""

    status: str  # HISTORY_CERTIFIED or HISTORY_UNAVAILABLE
    experiment_id: str
    package: Chapter3ResultPackage | None
    reason: str


def _listing_eligibility(record: ScienceLabExperimentRecord) -> tuple[bool, str]:
    if record.status != "COMPLETED":
        return False, f"status is {record.status}, not COMPLETED"
    if record.ended_monotonic_ns is None or record.ended_at_utc is None:
        return False, "completed record is missing its durable end boundary"
    return True, ""


def list_experiment_history() -> tuple[HistoryEntry, ...]:
    """Every durable Science Lab experiment, across every parent session,
    newest-first.  Read-only."""

    records = read_all_science_lab_experiments()
    entries = []
    for record in records:
        eligible, reason = _listing_eligibility(record)
        entries.append(
            HistoryEntry(
                experiment_id=record.experiment_id,
                parent_session_id=record.parent_session_id,
                status=record.status,
                started_at_utc=record.started_at_utc,
                ended_at_utc=record.ended_at_utc,
                end_reason=record.end_reason,
                eligible=eligible,
                reason=reason,
            )
        )
    return tuple(entries)


def reconstruct_historical_experiment(experiment_id: str) -> HistoryReconstruction:
    """Read-only reconstruction of ONE named, already-completed experiment's
    certified package.

    Fails closed (HISTORY_UNAVAILABLE, package=None, factual reason) at the
    first unmet requirement -- never a partial package, never an invented
    finalization time, never a fallback to a different experiment.
    """

    if type(experiment_id) is not str or not experiment_id.strip():
        return HistoryReconstruction(HISTORY_UNAVAILABLE, str(experiment_id), None, "no experiment id was given")

    try:
        selected = read_science_lab_experiment(experiment_id)
    except Exception as exc:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            f"could not read the durable experiment record: {type(exc).__name__}",
        )
    if selected is None:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            "no durable experiment record exists with this exact id",
        )
    if selected.status != "COMPLETED":
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            f"experiment status is {selected.status}, not COMPLETED",
        )
    if selected.ended_monotonic_ns is None or selected.ended_at_utc is None:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            "completed experiment is missing its durable end boundary",
        )

    try:
        finalized_at_utc = read_session_closed_at_utc(selected.parent_session_id)
    except Exception as exc:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            f"could not read the parent session's closure record: {type(exc).__name__}",
        )
    if not finalized_at_utc:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            "the parent MYELIN session has no durable closure timestamp; historical "
            "reconstruction requires an authoritative finalization time and will not "
            "invent one",
        )

    try:
        snapshot = gather_session_evidence(selected.parent_session_id)
    except Exception as exc:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            f"evidence snapshot read failed: {type(exc).__name__}",
        )
    if snapshot.parent_session_id != selected.parent_session_id:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            "evidence snapshot belongs to a different session than the selected experiment",
        )

    finalized = ScienceLabFinalizedSession(
        parent_session_id=selected.parent_session_id,
        evidence_snapshot=snapshot,
        completed_experiment_id=selected.experiment_id,
        finalized_at_utc=finalized_at_utc,
    )

    # analyze_finalized_session never raises -- it converts any internal
    # failure into an ANALYSIS_UNAVAILABLE outcome itself.  The tuple below
    # contains ONLY the selected record: analysis.py's own "pick the latest
    # completed experiment" rule then has exactly one candidate, which is
    # always this one -- it can never silently choose a different real
    # experiment from the same session.
    outcome = analyze_finalized_session(finalized=finalized, experiments=(selected,))
    if outcome.status != CERTIFIED or outcome.package is None:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            outcome.reason or f"analysis outcome was {outcome.status}",
        )

    package = outcome.package
    if package.experiment_id != selected.experiment_id:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            "reconstructed package experiment id does not match the selected experiment",
        )
    if package.parent_session_id != selected.parent_session_id:
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            "reconstructed package session does not match the selected experiment",
        )
    if (
        package.experiment_start_monotonic_ns != selected.started_monotonic_ns
        or package.experiment_end_monotonic_ns != selected.ended_monotonic_ns
    ):
        return HistoryReconstruction(
            HISTORY_UNAVAILABLE, experiment_id, None,
            "reconstructed package window does not match the selected experiment's "
            "durable bounds",
        )

    return HistoryReconstruction(
        HISTORY_CERTIFIED, experiment_id, package,
        "reconstructed and certified from durable evidence",
    )


__all__ = [
    "HISTORY_CERTIFIED",
    "HISTORY_UNAVAILABLE",
    "RECONSTRUCTION_LABEL",
    "HistoryEntry",
    "HistoryReconstruction",
    "list_experiment_history",
    "reconstruct_historical_experiment",
]
