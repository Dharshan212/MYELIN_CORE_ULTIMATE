"""Science Lab analysis / orchestration.

THIS IS NOT A SECOND MYELIN MONITORING ENGINE.

``engine.py`` must never independently observe the foreground window,
browser URL, process identity, OS activity, input activity, or phone/
sensor state.  Existing MYELIN authorities (Monitor, SINE, MIRL, MINE,
COSINE) already provide that factual evidence; this module only ever reads
what they have already produced, through ``evidence.py``.

For now (Phase C: connect the current MYELIN session to Science Lab), this
module gains MINIMAL real behaviour via ``ScienceLabCoordinator``: it
tracks which single MYELIN session Science Lab is currently attached to,
and can ask ``evidence.py`` for one read-only evidence snapshot of that
session.  It owns no timer, starts no engine, writes no organ event, and
allocates no experiment identity -- that belongs to the persistence layer
once designed.

Future intended flow (not fully wired yet):

    SCIENCE_LAB/evidence.py
            |
            v
    SCIENCE_LAB/engine.py
        |           |
        v           v
    lab.py      report.py

When built out further, ``engine.py`` may additionally:

- organise experiment evidence handed to it by ``evidence.py``;
- compare before/during/after behavioural periods;
- calculate user-approved, clearly-labelled measures;
- produce structured, immutable result objects;
- label each value OBSERVED / DERIVED / HYPOTHESIS -- never a biological
  or psychological diagnosis.

It may not invent biological truth: no dopamine, motivation, boredom,
stress, fatigue, brain activation, mind-wandering, or addiction claims,
ever, from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Final

from .analysis import (
    Chapter3AnalysisOutcome,
    analyze_finalized_session,
    unavailable_outcome,
)
from .evidence import ScienceLabEvidenceSnapshot, gather_session_evidence
from .experiment import ScienceLabExperimentLifecycle

#: Temporary UAT diagnostic prefix.  Prints only on meaningful state
#: changes (attach / snapshot / detach) -- never a per-tick/per-second
#: loop.  Remove once Chapter 3 has its own real presentation of this
#: data and the architecture owner no longer needs console proof.
_UAT_PREFIX: Final = "[MYELIN][SCIENCE-LAB-UAT]"


@dataclass(frozen=True, slots=True)
class ScienceLabFinalizedSession:
    """One immutable clean-stop handoff for later Chapter 3 analysis."""

    parent_session_id: int
    evidence_snapshot: ScienceLabEvidenceSnapshot
    completed_experiment_id: str | None
    finalized_at_utc: str


class ScienceLabCoordinator:
    """Owns Science Lab's current session attachment.

    Deliberately NOT owned by the page widget (``SCIENCE_LAB/lab.py``):
    the attachment must survive the user navigating away from Science Lab,
    so this belongs to a long-lived object wired at the application/
    controller level (``CONTROL_STATION/launcher.py``), not to a
    QWidget's lifetime.  This class itself has no Qt dependency at all --
    the host wires it to Qt signals from the outside.
    """

    def __init__(self) -> None:
        self._attached_session_id: int | None = None
        self._latest_snapshot: ScienceLabEvidenceSnapshot | None = None
        self._last_finalized_session: ScienceLabFinalizedSession | None = None
        self._latest_chapter3_analysis: Chapter3AnalysisOutcome | None = None

    @property
    def attached_session_id(self) -> int | None:
        return self._attached_session_id

    @property
    def latest_snapshot(self) -> ScienceLabEvidenceSnapshot | None:
        return self._latest_snapshot

    @property
    def last_finalized_session(self) -> ScienceLabFinalizedSession | None:
        return self._last_finalized_session

    @property
    def latest_chapter3_analysis(self) -> Chapter3AnalysisOutcome | None:
        """The last immutable analysis outcome; reading never reruns analysis."""

        return self._latest_chapter3_analysis

    def attach_session(self, session_id: int) -> None:
        """Attach to the given authoritative MYELIN session ID.

        The caller (the Control Station host) is responsible for only
        calling this once ``ControlStationController.current_session_id()``
        has actually returned a real, persisted ID -- never a placeholder,
        never a guess, never the previous session's ID.
        """

        if session_id == self._attached_session_id:
            return
        self._attached_session_id = session_id
        self._latest_snapshot = None
        print(f"{_UAT_PREFIX} attached session={session_id}")
        self.refresh_snapshot()

    def detach_session(self) -> None:
        """Detach from the current session, e.g. once it has ended.

        The last gathered snapshot is kept in memory (for UAT/manual
        inspection) but the coordinator no longer claims an active
        session.
        """

        if self._attached_session_id is None:
            return
        detached_id = self._attached_session_id
        self._attached_session_id = None
        print(f"{_UAT_PREFIX} detached session={detached_id}")

    def refresh_snapshot(self) -> ScienceLabEvidenceSnapshot | None:
        """Gather one fresh read-only evidence snapshot for the attached
        session.  Does nothing (and returns ``None``) if not attached.
        """

        if self._attached_session_id is None:
            print(f"{_UAT_PREFIX} no active parent session")
            return None

        snapshot = gather_session_evidence(self._attached_session_id)
        self._latest_snapshot = snapshot

        coverage_text = " ".join(
            f"{row.source_system}={row.status.lower()}"
            + (f"({row.item_count})" if row.item_count is not None else "")
            for row in snapshot.source_coverage
        )
        print(
            f"{_UAT_PREFIX} snapshot session={snapshot.parent_session_id} "
            f"{coverage_text}"
        )
        for row in snapshot.source_coverage:
            if row.status == "UNAVAILABLE":
                print(
                    f"{_UAT_PREFIX} source={row.source_system} "
                    f"status=UNAVAILABLE reason={row.reason}"
                )
        return snapshot

    def finalize_clean_stop(
        self,
        *,
        parent_session_id: int,
        experiments: ScienceLabExperimentLifecycle,
    ) -> ScienceLabFinalizedSession:
        """Finalize Science Lab only after the host reports factual cleanup.

        Experiment completion precedes the one final evidence read.  A failed
        step never creates a finalized-session object; the application host
        owns bounded error presentation and forced detachment in that case.
        """

        if type(parent_session_id) is not int or parent_session_id <= 0:
            raise ValueError("parent_session_id must be a positive integer")
        if self._attached_session_id != parent_session_id:
            raise RuntimeError(
                "Science Lab is not attached to the ending parent session"
            )

        completed = experiments.end_for_parent_session(parent_session_id)
        snapshot = gather_session_evidence(parent_session_id)
        if snapshot.parent_session_id != parent_session_id:
            raise RuntimeError("final evidence snapshot belongs to another session")

        finalized = ScienceLabFinalizedSession(
            parent_session_id=parent_session_id,
            evidence_snapshot=snapshot,
            completed_experiment_id=(
                completed.experiment_id if completed is not None else None
            ),
            finalized_at_utc=(
                datetime.now(timezone.utc)
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            ),
        )
        self._last_finalized_session = finalized
        self._latest_chapter3_analysis = None
        self._latest_snapshot = snapshot
        self.detach_session()
        return finalized

    def analyze_last_finalized_session(
        self,
        *,
        experiments: ScienceLabExperimentLifecycle,
    ) -> Chapter3AnalysisOutcome:
        """Analyze the retained final snapshot once, without recapturing it."""

        finalized = self._last_finalized_session
        if finalized is None:
            raise RuntimeError("Science Lab has no finalized session to analyze")
        try:
            history = experiments.history(finalized.parent_session_id)
            outcome = analyze_finalized_session(
                finalized=finalized,
                experiments=tuple(history),
            )
        except Exception as exc:
            clean = " ".join(str(exc).split())[:240] or exc.__class__.__name__
            outcome = unavailable_outcome(
                f"{exc.__class__.__name__}: {clean}",
                finalized=finalized,
            )
        self._latest_chapter3_analysis = outcome
        return outcome


__all__ = ["ScienceLabCoordinator", "ScienceLabFinalizedSession"]
