"""The single MIRL recovery runtime for MYELIN.

MIRL records what happened after an intervention.  It does not display SINE,
classify browser content, calculate scientific truth, or write dashboard state.

The required order is deliberately small and strict:

1. a durably admitted trigger prepares one short-lived display token;
2. the matching factual ``SINE_DISPLAYED`` event for SINE 1 creates an episode;
3. authoritative focus begins a ten-second initial return confirmation;
4. distraction during those ten seconds rejects that return attempt;
5. confirmed recovery entry opens a sixty-second MIRL stability verification;
6. distraction during stability verification records relapse and resumes the episode; and
7. uninterrupted stability verification closes the episode as ``RETURNED``.

Important truth rules
---------------------
* Preparing a trigger does not create an episode.
* A popup request, schedule or animation does not prove a SINE display.
* Pressing Return records intent only; it does not verify recovery.
* UNCERTAIN, stale and unsupported evidence is neutral.  It never advances a
  timer and never fabricates an interruption.
* Inside a Study block, focus is a fresh Resource Intent ``STUDY_ALIGNED``
  verdict carrying this episode's Study context -- whether Resource Intent
  reached that verdict from factual C4 evidence or from an exact confirmed
  allowance.  MIRL does not re-derive which route was taken.  Outside a Study
  block, MIRL reads the certified resource surface Resource Intent already
  published; unsupported surfaces stay neutral in both modes.
* All elapsed-time decisions use monotonic nanoseconds.  Wall time is carried
  only as display/persistence evidence.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Final


# v2: Study FOCUS now trusts any fresh Resource Intent STUDY_ALIGNED verdict
# instead of requiring an exact manual allowance, and Protected Red no longer
# blocks normal-mode recovery sensing.  A v1 event stream therefore observed a
# strictly narrower set of recoveries than a v2 one.
MIRL_SCHEMA_VERSION: Final = "myelin-mirl-v2"
# v2 changed the MEANING of ``verified_recovery_elapsed_seconds``: it is
# now measured to the behavioural return ONSET, not to the moment the
# verification gate finished proving it.  The bump is deliberate so no
# reader can silently mix v1 and v2 latencies in one lambda estimate.
# v3 does NOT change that equation or any timestamp meaning.  It changes the
# admissible POPULATION: under v2 a Study recovery was in practice reachable
# only through a manual allowance, and no recovery at all could be observed
# while Protected Red was active.  Under v3 both C4 automatic and manual
# STUDY_ALIGNED may enter verification, and Red-time recoveries are visible.
# Mixing v2 and v3 populations would therefore bias a lambda estimate even
# though each individual latency is computed identically.
RECOVERY_EVIDENCE_SCHEMA_VERSION: Final = "myelin-mirl-recovery-evidence-v3"
NANOSECONDS_PER_SECOND: Final = 1_000_000_000


class MirlPhase(str, Enum):
    """The only legal coarse states of one MIRL runtime."""

    IDLE = "IDLE"
    AWAITING_SINE_1 = "AWAITING_SINE_1"
    WAITING_FOR_RETURN = "WAITING_FOR_RETURN"
    RETURN_VERIFICATION = "RETURN_VERIFICATION"
    CLOSURE_CONFIRMATION = "CLOSURE_CONFIRMATION"
    CLOSED = "CLOSED"
    EMERGENCY_STOPPED = "EMERGENCY_STOPPED"


class RecoveryContext(str, Enum):
    """A factual recovery observation supplied by an authority."""

    FOCUS = "FOCUS"
    DISTRACTION = "DISTRACTION"
    NEUTRAL = "NEUTRAL"


class EpisodeOutcome(str, Enum):
    RETURNED = "RETURNED"
    # One explicit non-recovery terminal outcome.  SINE can legitimately end
    # its intervention without the user ever recovering -- approved break,
    # exact study alignment, COSINE precedence, a changed study context, a
    # different distraction resource.  Such an episode must never be reported
    # as RETURNED and must never yield Tr.  The exact SINE terminal reason is
    # carried separately on the event, so one outcome value is enough.
    ABORTED = "ABORTED"
    EMERGENCY = "EMERGENCY"
    SESSION_ENDED = "SESSION_ENDED"


class MirlEventClass(str, Enum):
    """Observed events come from facts; derived events come from MIRL policy."""

    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"


class MirlEventName(str, Enum):
    TRIGGER_PREPARED = "trigger_prepared"
    FIRST_DISPLAY_TIMED_OUT = "first_display_timed_out"
    FIRST_DISPLAY_REJECTED = "first_display_rejected"
    EPISODE_CREATED = "episode_created"
    SINE_DISPLAYED = "sine_displayed"
    SINE_RESPONSE_RECORDED = "sine_response_recorded"
    RETURN_INTENT_RECORDED = "return_intent_recorded"
    SINE_TERMINATED = "sine_terminated"
    RETURN_VERIFICATION_STARTED = "return_verification_started"
    RETURN_UNVERIFIED = "return_unverified"
    RETURN_VERIFICATION_INTERRUPTED = "return_verification_interrupted"
    RETURN_VERIFICATION_COMPLETED = "return_verification_completed"
    RETURN_VERIFIED = "return_verified"
    CLOSURE_CONFIRMATION_STARTED = "closure_confirmation_started"
    CLOSURE_CONFIRMATION_INTERRUPTED = "closure_confirmation_interrupted"
    RELAPSE_DETECTED = "relapse_detected"
    EPISODE_RESUMED = "episode_resumed"
    CLOSURE_CONFIRMATION_COMPLETED = "closure_confirmation_completed"
    EPISODE_CLOSED = "episode_closed"
    EVIDENCE_GAP = "evidence_gap"
    EMERGENCY_STOPPED = "emergency_stopped"


@dataclass(frozen=True, slots=True)
class MirlPolicy:
    """Named MIRL timing rules; tests may inject shorter positive values."""

    first_display_deadline_seconds: float = 45.0
    # Chief's locked recovery contract:
    # 10 s proves the user has actually entered recovery; the following 60 s
    # is an anti-fake/stability gate.  The 60 s gate validates the earlier
    # recovery entry but is not added to the Ebbinghaus recovery duration.
    return_verification_seconds: float = 10.0
    closure_confirmation_seconds: float = 60.0
    maximum_observation_gap_seconds: float = 5.0

    def __post_init__(self) -> None:
        for name in (
            "first_display_deadline_seconds",
            "return_verification_seconds",
            "closure_confirmation_seconds",
            "maximum_observation_gap_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive")


@dataclass(frozen=True, slots=True)
class MirlDisplayToken:
    """Opaque proof that MIRL is waiting for one exact first SINE display."""

    token_id: str
    session_id: int
    candidate_uid: str
    operational_event_id: int
    study_context_token: str
    evidence_digest: str
    issued_monotonic_ns: int
    deadline_monotonic_ns: int
    schema_version: str = MIRL_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class RecoveryObservation:
    """Explicit recovery evidence for integrations that own focus truth.

    ``monitor.py`` already supplies Resource Intent snapshots through
    :meth:`observe`.  A future non-study focus authority can use this contract
    rather than teaching MIRL how to inspect applications or window titles.
    """

    context: RecoveryContext
    observed_monotonic_ns: int
    observed_wall_time_utc: str
    source: str
    observation_token: str
    study_context_token: str = ""
    fresh: bool = True

    def __post_init__(self) -> None:
        if type(self.observed_monotonic_ns) is not int or self.observed_monotonic_ns <= 0:
            raise ValueError("observed_monotonic_ns must be a positive integer")
        if not str(self.source).strip() or not str(self.observation_token).strip():
            raise ValueError("recovery evidence requires a source and observation token")


@dataclass(frozen=True, slots=True)
class VerifiedRecoveryEvidence:
    """One factual recovery package that later phases may learn from.

    MIRL does not calculate lambda.  It only releases this package after the
    recovery entry has survived the ten-second initial confirmation and then
    the sixty-second stability gate without relapse.  For compatibility the
    historical ``RETURN_VERIFIED`` event name marks the confirmed recovery-entry
    anchor after ten seconds.  Final stable recovery is not accepted until the
    episode closes as RETURNED after the sixty-second gate.  The stability gate
    validates the earlier recovery entry and is not added to the measured
    Ebbinghaus recovery time.

    Return ONSET and return PROOF are two different facts and are published as
    two different timestamps:

    ``return_started_monotonic_ns``
        the first authoritative FOCUS observation that went on to survive
        verification.  This is when the user behaviourally came back, and it
        is the anchor for the Ebbinghaus return latency Tr.

    ``return_verified_monotonic_ns``
        when the verification gate finished proving that return.  This is the
        anchor monitor.py hands to ``SineAuthority.confirm_verified_return``,
        because SINE must never be released on an unproven onset.

    Collapsing the two inflates Tr by the whole verification window and would
    push every learned lambda in the wrong direction.
    """

    session_id: int
    profile_type: str
    episode_id: str
    candidate_uid: str
    operational_event_id: int
    attempt_id: str
    attempt_index: int
    first_sine_displayed_monotonic_ns: int
    return_started_monotonic_ns: int
    return_verified_monotonic_ns: int
    episode_closed_monotonic_ns: int
    # Behavioural return latency Tr: return ONSET minus the factual SINE 1
    # display.  ``return_latency_seconds`` below is the clearer name for the
    # same value; the historical field name is kept so monitor.py and the
    # storage lane need no interface change during this surgery.
    verified_recovery_elapsed_seconds: float
    verification_focus_seconds: float
    closure_confirmation_seconds: float
    relapse_count: int
    return_verified_event_id: str
    episode_closed_event_id: str
    schema_version: str = RECOVERY_EVIDENCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("session_id must be a positive integer")
        if type(self.operational_event_id) is not int or self.operational_event_id <= 0:
            raise ValueError("operational_event_id must be a positive integer")
        if type(self.attempt_index) is not int or self.attempt_index <= 0:
            raise ValueError("attempt_index must be a positive integer")
        if type(self.relapse_count) is not int or self.relapse_count < 0:
            raise ValueError("relapse_count must be a non-negative integer")
        for name in (
            "profile_type",
            "episode_id",
            "candidate_uid",
            "attempt_id",
            "return_verified_event_id",
            "episode_closed_event_id",
            "schema_version",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} must not be empty")
        for name in (
            "first_sine_displayed_monotonic_ns",
            "return_started_monotonic_ns",
            "return_verified_monotonic_ns",
            "episode_closed_monotonic_ns",
        ):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not (
            self.first_sine_displayed_monotonic_ns
            < self.return_started_monotonic_ns
            <= self.return_verified_monotonic_ns
            <= self.episode_closed_monotonic_ns
        ):
            raise ValueError("recovery evidence monotonic anchors are out of order")
        for name in (
            "verified_recovery_elapsed_seconds",
            "verification_focus_seconds",
            "closure_confirmation_seconds",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0.0:
                raise ValueError(f"{name} must be finite and positive")
        measured = (
            self.return_started_monotonic_ns
            - self.first_sine_displayed_monotonic_ns
        ) / NANOSECONDS_PER_SECOND
        if not math.isclose(
            measured,
            float(self.verified_recovery_elapsed_seconds),
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            raise ValueError("return latency does not match the monotonic anchors")

    @property
    def return_latency_seconds(self) -> float:
        """Ebbinghaus Tr: behavioural return onset minus the SINE 1 display."""

        return float(self.verified_recovery_elapsed_seconds)

    @property
    def verification_proof_seconds(self) -> float:
        """How long the proof of that return took after the onset."""

        return (
            self.return_verified_monotonic_ns - self.return_started_monotonic_ns
        ) / NANOSECONDS_PER_SECOND


@dataclass(frozen=True, slots=True)
class MirlEvent:
    """One immutable, ordered MIRL fact suitable for telemetry/persistence."""

    kind: str
    event_name: MirlEventName
    event_class: MirlEventClass
    event_id: str
    episode_id: str
    episode_sequence: int
    occurred_monotonic_ns: int
    occurred_wall_time_utc: str
    session_id: int | None
    candidate_uid: str = ""
    operational_event_id: int | None = None
    attempt_id: str = ""
    attempt_index: int = 0
    sine_stage: int = 0
    sine_occurrence: int = 0
    reason: str = ""
    response: str = ""
    elapsed_seconds: float = 0.0
    target_seconds: float = 0.0
    supporting_event_ids: tuple[str, ...] = ()
    detail: str = ""
    schema_version: str = MIRL_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MirlLiveView:
    """Read-only runtime truth for Control Station and dashboards."""

    session_id: int | None
    profile_type: str
    phase: MirlPhase
    pending_display: bool
    pending_candidate_uid: str
    pending_display_seconds: float | None
    episode_id: str
    candidate_uid: str
    operational_event_id: int | None
    attempt_id: str
    attempt_index: int
    return_verification_elapsed_seconds: float
    return_verification_target_seconds: float
    closure_confirmation_elapsed_seconds: float
    closure_confirmation_target_seconds: float
    relapse_count: int
    last_context: RecoveryContext
    last_event: str
    event_count: int
    integrity_ok: bool
    diagnostic: str
    schema_version: str = MIRL_SCHEMA_VERSION


@dataclass(slots=True)
class _PendingTrigger:
    token: MirlDisplayToken
    candidate: object


@dataclass(slots=True)
class _Attempt:
    attempt_id: str
    index: int
    verification_started_ns: int
    verification_elapsed_ns: int = 0
    verified_monotonic_ns: int | None = None
    return_verified_event_id: str = ""
    closure_started_ns: int | None = None
    closure_elapsed_ns: int = 0


@dataclass(slots=True)
class _Episode:
    episode_id: str
    session_id: int
    candidate_uid: str
    operational_event_id: int
    study_context_token: str
    created_monotonic_ns: int
    created_wall_time_utc: str
    sine_episode_uid: str
    first_popup_request_id: str
    first_sine_occurrence: int
    phase: MirlPhase = MirlPhase.WAITING_FOR_RETURN
    next_sequence: int = 1
    attempt_count: int = 0
    attempt: _Attempt | None = None
    relapse_count: int = 0
    last_observation_ns: int | None = None
    last_context: RecoveryContext = RecoveryContext.NEUTRAL
    last_event_ns: int = 0
    events: list[MirlEvent] = field(default_factory=list)
    outcome: EpisodeOutcome | None = None


@dataclass(frozen=True, slots=True)
class _EventContract:
    event_class: MirlEventClass
    requires_episode: bool
    allowed_phases: frozenset[MirlPhase]
    requires_attempt: bool = False


_ACTIVE_PHASES: Final = frozenset(
    {
        MirlPhase.WAITING_FOR_RETURN,
        MirlPhase.RETURN_VERIFICATION,
        MirlPhase.CLOSURE_CONFIRMATION,
    }
)


# INSTRUCTION: outside a Study block Resource Intent deliberately stops at
# UNCERTAIN / ``no_active_study_block``.  That is a statement about study
# alignment only -- the certified ``ResourceIdentity.surface`` built from
# process and browser-route evidence is still present on the same verdict.
# MIRL reads that already-certified surface; it never inspects applications,
# window titles or browser addresses itself, and it does not classify.
#
# These are the boundary *values* of ``CORE_ENGINE.resource_intent``.  They are
# compared as text through ``_enum_value`` so MIRL keeps its pure boundary and
# imports no classifier.
_NORMAL_MODE_REASON: Final = "NO_ACTIVE_STUDY_BLOCK"

# Certified productive surfaces.  These open a *return candidate* only; the
# existing verification and stability gates still decide whether the return
# was factual.
_NORMAL_MODE_FOCUS_SURFACES: Final = frozenset({"DOCUMENT", "LEARNING_APP"})

# Certified distractive surfaces.
_NORMAL_MODE_DISTRACTION_SURFACES: Final = frozenset(
    {"YOUTUBE_WATCH", "YOUTUBE_SHORTS", "SOCIAL", "GAMING"}
)

# INSTRUCTION: everything else -- UNKNOWN, WEB_CONTENT, BROWSER_INTERNAL,
# YOUTUBE_OTHER, MESSAGING, COSINE -- stays NEUTRAL.  Explorer, the desktop,
# settings and unknown web pages must never fabricate recovery evidence,
# because a false Tr would corrupt every later lambda.


# The two factual SINE terminal facts monitor.py routes back into MIRL.  SINE
# owns intervention scope; MIRL only observes that the intervention it was
# measuring has ended, and closes its own episode honestly.
_SINE_TERMINAL_KINDS: Final = frozenset(
    {"SINE_EPISODE_RESOLVED", "SINE_EPISODE_CANCELLED"}
)

# ``SineAuthority._resolve_episode`` is called with this reason prefix only
# from ``confirm_verified_return``, i.e. only when the verified recovery MIRL
# itself published released SINE.  Every other resolve/cancel reason --
# approved_break, exact_study_alignment, cosine_precedence,
# study_context_changed, different_distraction_resource,
# superseded_by_later_durable_trigger -- is non-recovery.
_SINE_VERIFIED_RETURN_PREFIX: Final = "verified_return:"


# INSTRUCTION: every event emitted by MIRL must have one contract here.  This
# prevents a later UI or persistence adapter from inventing lifecycle events.
EVENT_CONTRACTS: Final[dict[MirlEventName, _EventContract]] = {
    MirlEventName.TRIGGER_PREPARED: _EventContract(
        MirlEventClass.OBSERVED, False, frozenset({MirlPhase.AWAITING_SINE_1})
    ),
    MirlEventName.FIRST_DISPLAY_TIMED_OUT: _EventContract(
        MirlEventClass.DERIVED, False, frozenset({MirlPhase.AWAITING_SINE_1})
    ),
    MirlEventName.FIRST_DISPLAY_REJECTED: _EventContract(
        MirlEventClass.OBSERVED, False, frozenset({MirlPhase.AWAITING_SINE_1})
    ),
    MirlEventName.EPISODE_CREATED: _EventContract(
        MirlEventClass.OBSERVED, True, frozenset({MirlPhase.WAITING_FOR_RETURN})
    ),
    MirlEventName.SINE_DISPLAYED: _EventContract(
        MirlEventClass.OBSERVED, True, _ACTIVE_PHASES
    ),
    MirlEventName.SINE_RESPONSE_RECORDED: _EventContract(
        MirlEventClass.OBSERVED, True, _ACTIVE_PHASES
    ),
    MirlEventName.RETURN_INTENT_RECORDED: _EventContract(
        MirlEventClass.OBSERVED, True, _ACTIVE_PHASES
    ),
    MirlEventName.SINE_TERMINATED: _EventContract(
        MirlEventClass.OBSERVED, True, _ACTIVE_PHASES
    ),
    MirlEventName.RETURN_VERIFICATION_STARTED: _EventContract(
        MirlEventClass.OBSERVED,
        True,
        frozenset({MirlPhase.RETURN_VERIFICATION}),
        True,
    ),
    MirlEventName.RETURN_UNVERIFIED: _EventContract(
        MirlEventClass.DERIVED,
        True,
        frozenset({MirlPhase.RETURN_VERIFICATION}),
        True,
    ),
    MirlEventName.RETURN_VERIFICATION_INTERRUPTED: _EventContract(
        MirlEventClass.OBSERVED,
        True,
        frozenset({MirlPhase.RETURN_VERIFICATION}),
        True,
    ),
    MirlEventName.RETURN_VERIFICATION_COMPLETED: _EventContract(
        MirlEventClass.OBSERVED,
        True,
        frozenset({MirlPhase.RETURN_VERIFICATION}),
        True,
    ),
    MirlEventName.RETURN_VERIFIED: _EventContract(
        MirlEventClass.DERIVED,
        True,
        frozenset({MirlPhase.RETURN_VERIFICATION}),
        True,
    ),
    MirlEventName.CLOSURE_CONFIRMATION_STARTED: _EventContract(
        MirlEventClass.OBSERVED,
        True,
        frozenset({MirlPhase.CLOSURE_CONFIRMATION}),
        True,
    ),
    MirlEventName.CLOSURE_CONFIRMATION_INTERRUPTED: _EventContract(
        MirlEventClass.OBSERVED,
        True,
        frozenset({MirlPhase.CLOSURE_CONFIRMATION}),
        True,
    ),
    MirlEventName.RELAPSE_DETECTED: _EventContract(
        MirlEventClass.DERIVED,
        True,
        frozenset({MirlPhase.CLOSURE_CONFIRMATION}),
        True,
    ),
    MirlEventName.EPISODE_RESUMED: _EventContract(
        MirlEventClass.DERIVED, True, _ACTIVE_PHASES
    ),
    MirlEventName.CLOSURE_CONFIRMATION_COMPLETED: _EventContract(
        MirlEventClass.OBSERVED,
        True,
        frozenset({MirlPhase.CLOSURE_CONFIRMATION}),
        True,
    ),
    MirlEventName.EPISODE_CLOSED: _EventContract(
        MirlEventClass.DERIVED, True, frozenset({MirlPhase.CLOSED})
    ),
    MirlEventName.EVIDENCE_GAP: _EventContract(
        MirlEventClass.OBSERVED, True, _ACTIVE_PHASES
    ),
    MirlEventName.EMERGENCY_STOPPED: _EventContract(
        MirlEventClass.OBSERVED,
        True,
        frozenset({MirlPhase.EMERGENCY_STOPPED}),
    ),
}


class MirlAuthority:
    """One thread-safe owner of the MIRL episode lifecycle."""

    def __init__(
        self,
        *,
        storage: object | None = None,
        policy: MirlPolicy | None = None,
    ) -> None:
        # Persistence is intentionally not called from this runtime.  MIRL
        # emits immutable facts; the persistence lane may subscribe to them.
        self._storage = storage
        self._policy = policy or MirlPolicy()
        self._lock = threading.RLock()
        self._session_id: int | None = None
        self._profile_type = ""
        self._phase = MirlPhase.IDLE
        self._pending: _PendingTrigger | None = None
        self._episode: _Episode | None = None
        self._outbox: deque[MirlEvent] = deque()
        self._verified_recovery_outbox: deque[VerifiedRecoveryEvidence] = deque()
        self._history: deque[MirlEvent] = deque(maxlen=4096)
        self._last_event = ""
        self._integrity_ok = True
        self._diagnostic = ""

    def start_session(self, *, session_id: int, profile_type: str) -> None:
        """Start cleanly only after monitor.py has a durable session row."""

        if type(session_id) is not int or session_id <= 0:
            raise ValueError("session_id must be a positive integer")
        profile = str(profile_type or "").strip()
        if not profile:
            raise ValueError("profile_type must not be empty")
        with self._lock:
            self._session_id = session_id
            self._profile_type = profile
            self._phase = MirlPhase.IDLE
            self._pending = None
            self._episode = None
            self._outbox.clear()
            self._verified_recovery_outbox.clear()
            self._history.clear()
            self._last_event = ""
            self._integrity_ok = True
            self._diagnostic = ""

    def prepare_trigger(
        self,
        *,
        candidate: object,
        operational_event_id: int,
    ) -> MirlDisplayToken | None:
        """Prepare one display token without creating a recovery episode."""

        with self._lock:
            if not self._ready() or self._active_episode():
                return None
            if type(operational_event_id) is not int or operational_event_id <= 0:
                return self._reject("operational_event_id must be a positive integer")

            evidence = _field(candidate, "evidence")
            if (
                str(_field(evidence, "study_context_token", "") or "")
                or _enum_value(_field(evidence, "source", "")) == "STUDY_OFF_TASK"
            ):
                return None
            candidate_uid = str(_field(candidate, "candidate_uid", "") or "")
            candidate_session = _field(candidate, "session_id")
            if not candidate_uid or candidate_session != self._session_id:
                return self._reject("trigger candidate identity does not match this session")

            if self._pending is not None:
                token = self._pending.token
                if (
                    token.candidate_uid == candidate_uid
                    and token.operational_event_id == operational_event_id
                ):
                    return token
                return self._reject("another first SINE display is already pending")

            now_ns = time.monotonic_ns()
            token = MirlDisplayToken(
                token_id=f"mirl-display-{secrets.token_hex(16)}",
                session_id=self._session_id,
                candidate_uid=candidate_uid,
                operational_event_id=operational_event_id,
                study_context_token="",
                evidence_digest=str(_field(evidence, "evidence_digest", "") or ""),
                issued_monotonic_ns=now_ns,
                deadline_monotonic_ns=now_ns
                + _seconds_to_ns(self._policy.first_display_deadline_seconds),
            )
            self._pending = _PendingTrigger(token=token, candidate=candidate)
            self._phase = MirlPhase.AWAITING_SINE_1
            self._emit_without_episode(
                MirlEventName.TRIGGER_PREPARED,
                now_ns=now_ns,
                candidate_uid=candidate_uid,
                operational_event_id=operational_event_id,
                detail="MIRL is waiting for the matching factual SINE 1 display.",
            )
            return token

    def prepared_token_current(self, token: object, *, now_ns: int) -> bool:
        """Positive ACK for the exact, still-reserved first-display identity."""
        with self._lock:
            return bool(
                self._ready() and self._pending is not None
                and isinstance(token, MirlDisplayToken)
                and self._pending.token == token
                and token.issued_monotonic_ns <= now_ns < token.deadline_monotonic_ns
                and not self._active_episode()
            )

    def abandon_prepared_token(
        self, *, token: object, reason: str, now_ns: int
    ) -> bool:
        """Retire only a matching preparation; never manufacture an episode."""
        with self._lock:
            if (
                self._pending is None or not isinstance(token, MirlDisplayToken)
                or self._pending.token != token
            ):
                return False
            self._release_pending_display(
                {
                    "session_id": token.session_id,
                    "candidate_uid": token.candidate_uid,
                    "operational_event_id": token.operational_event_id,
                    "reason": str(reason),
                },
                "PREPARED_HANDOFF_ABANDONED",
                max(now_ns, token.issued_monotonic_ns),
            )
            return self._pending is None

    def record_sine_fact(self, fact: object) -> None:
        """Consume factual SINE events; never treat a presentation request as fact."""

        with self._lock:
            if not self._ready():
                return
            kind = str(_field(fact, "kind", "") or "").upper()
            now_ns = _positive_int(_field(fact, "occurred_monotonic_ns"))
            if not kind or now_ns is None:
                self._mark_integrity_error("SINE fact has no kind or monotonic time")
                return

            if kind == "SINE_DISPLAYED" and _field(fact, "stage", 0) == 1:
                self._accept_first_sine_display(fact, now_ns)
                return

            episode = self._episode
            if episode is None or episode.phase is MirlPhase.CLOSED:
                # No episode to close.  A terminal fact may still belong to the
                # trigger MIRL is holding a display token for, which must be
                # released -- see _release_pending_display.
                if kind in _SINE_TERMINAL_KINDS:
                    self._release_pending_display(fact, kind, now_ns)
                return
            if not self._fact_matches_episode(fact, episode):
                return

            if kind == "SINE_DISPLAYED":
                stage = int(_field(fact, "stage", 0) or 0)
                if stage in (2, 3):
                    self._emit(
                        MirlEventName.SINE_DISPLAYED,
                        now_ns=now_ns,
                        wall_time=_wall_time(fact),
                        sine_stage=stage,
                        sine_occurrence=int(_field(fact, "occurrence", 0) or 0),
                        detail=f"Factual SINE {stage} display recorded.",
                    )
                return

            if kind == "SINE_RESPONSE_RECORDED":
                response = str(_field(fact, "response", "") or "").upper()
                self._emit(
                    MirlEventName.SINE_RESPONSE_RECORDED,
                    now_ns=now_ns,
                    wall_time=_wall_time(fact),
                    response=response,
                    sine_stage=int(_field(fact, "stage", 0) or 0),
                    sine_occurrence=int(_field(fact, "occurrence", 0) or 0),
                    detail="SINE user response recorded as intent evidence.",
                )
                return

            if kind == "SINE_RETURN_INTENT_RECORDED":
                self._emit(
                    MirlEventName.RETURN_INTENT_RECORDED,
                    now_ns=now_ns,
                    wall_time=_wall_time(fact),
                    response=str(_field(fact, "response", "") or ""),
                    detail="Return intent recorded; recovery is still unverified.",
                )
                return

            if kind in _SINE_TERMINAL_KINDS:
                self._consume_sine_terminal(fact, episode, kind, now_ns)

    def observe(self, context: object) -> tuple[MirlEvent, ...]:
        """Advance MIRL from one immutable monitor context and drain new facts."""

        with self._lock:
            now_ns = _context_monotonic_ns(context) or time.monotonic_ns()
            self._expire_pending_display(now_ns)
            if self._active_episode():
                observation = self._observation_from_monitor_context(context)
                self._advance(observation)
            return self._drain_outbox()

    def record_recovery_observation(
        self,
        observation: RecoveryObservation,
    ) -> tuple[MirlEvent, ...]:
        """Advance from explicit certified focus evidence outside Resource Intent."""

        if not isinstance(observation, RecoveryObservation):
            raise TypeError("observation must be RecoveryObservation")
        with self._lock:
            self._expire_pending_display(observation.observed_monotonic_ns)
            if self._active_episode():
                self._advance(observation)
            return self._drain_outbox()

    def drain_events(self) -> tuple[MirlEvent, ...]:
        """Drain already-created immutable events without advancing policy.

        monitor.py uses this immediately after command-side facts such as
        trigger preparation or SINE display so durable MIRL truth does not
        wait for the next foreground sample.
        """
        with self._lock:
            return self._drain_outbox()

    def drain_verified_recovery_evidence(
        self,
    ) -> tuple[VerifiedRecoveryEvidence, ...]:
        """Drain only recovery packages that passed MIRL's full validity gate.

        Button responses, popup closure, unverified focus, interrupted return
        attempts, relapse, emergency closure and ordinary session shutdown do
        not create these packages.  MIRL supplies evidence only; lambda math
        and profile persistence remain outside this authority.
        """

        with self._lock:
            evidence = tuple(self._verified_recovery_outbox)
            self._verified_recovery_outbox.clear()
            return evidence

    def live_view(self) -> MirlLiveView:
        with self._lock:
            now_ns = time.monotonic_ns()
            pending = self._pending.token if self._pending else None
            episode = self._episode
            attempt = episode.attempt if episode else None
            return MirlLiveView(
                session_id=self._session_id,
                profile_type=self._profile_type,
                phase=self._phase,
                pending_display=pending is not None,
                pending_candidate_uid=pending.candidate_uid if pending else "",
                pending_display_seconds=(
                    max(0.0, (self._pending_display_effective_deadline(self._pending, now_ns)
                              - now_ns) / NANOSECONDS_PER_SECOND)
                    if pending
                    else None
                ),
                episode_id=episode.episode_id if episode else "",
                candidate_uid=episode.candidate_uid if episode else "",
                operational_event_id=(episode.operational_event_id if episode else None),
                attempt_id=attempt.attempt_id if attempt else "",
                attempt_index=attempt.index if attempt else 0,
                return_verification_elapsed_seconds=(
                    attempt.verification_elapsed_ns / NANOSECONDS_PER_SECOND
                    if attempt
                    else 0.0
                ),
                return_verification_target_seconds=self._policy.return_verification_seconds,
                closure_confirmation_elapsed_seconds=(
                    attempt.closure_elapsed_ns / NANOSECONDS_PER_SECOND
                    if attempt
                    else 0.0
                ),
                closure_confirmation_target_seconds=self._policy.closure_confirmation_seconds,
                relapse_count=episode.relapse_count if episode else 0,
                last_context=(episode.last_context if episode else RecoveryContext.NEUTRAL),
                last_event=self._last_event,
                event_count=len(episode.events) if episode else 0,
                integrity_ok=self._integrity_ok,
                diagnostic=self._diagnostic,
            )

    def events(self) -> tuple[MirlEvent, ...]:
        """Return a read-only bounded history for persistence and diagnostics."""

        with self._lock:
            return tuple(self._history)

    def emergency_stop(self) -> None:
        """Stop timers immediately and record the emergency without waiting."""

        with self._lock:
            self._pending = None
            episode = self._episode
            if episode is not None and episode.phase not in {
                MirlPhase.CLOSED,
                MirlPhase.EMERGENCY_STOPPED,
            }:
                episode.phase = MirlPhase.EMERGENCY_STOPPED
                self._phase = MirlPhase.EMERGENCY_STOPPED
                event = self._emit(
                    MirlEventName.EMERGENCY_STOPPED,
                    now_ns=time.monotonic_ns(),
                    reason="emergency_stop",
                    detail="MIRL episode stopped by the emergency lifecycle authority.",
                )
                episode.outcome = EpisodeOutcome.EMERGENCY
                episode.phase = MirlPhase.CLOSED
                self._phase = MirlPhase.CLOSED
                self._emit(
                    MirlEventName.EPISODE_CLOSED,
                    now_ns=max(time.monotonic_ns(), event.occurred_monotonic_ns),
                    reason=EpisodeOutcome.EMERGENCY.value,
                    supporting_event_ids=(event.event_id,),
                    detail="MIRL episode closed by emergency.",
                )
            else:
                self._phase = MirlPhase.EMERGENCY_STOPPED

    def shutdown(self) -> None:
        """Release runtime state; ordinary shutdown does not fabricate recovery."""

        with self._lock:
            self._pending = None
            self._episode = None
            self._outbox.clear()
            self._verified_recovery_outbox.clear()
            self._session_id = None
            self._profile_type = ""
            self._phase = MirlPhase.IDLE

    # ------------------------------------------------------------------
    # First display and episode creation
    # ------------------------------------------------------------------

    def _accept_first_sine_display(self, fact: object, now_ns: int) -> None:
        pending = self._pending
        if pending is None:
            return
        token = _field(fact, "mirl_display_token")
        candidate_uid = str(_field(fact, "candidate_uid", "") or "")
        operational_event_id = _field(fact, "operational_event_id")
        session_id = _field(fact, "session_id")
        valid = bool(
            isinstance(token, MirlDisplayToken)
            and token == pending.token
            and token.session_id == session_id == self._session_id
            and token.candidate_uid == candidate_uid
            and token.operational_event_id == operational_event_id
            and token.issued_monotonic_ns
            <= now_ns <= self._pending_display_effective_deadline(pending, now_ns)
        )
        if not valid:
            self._emit_without_episode(
                MirlEventName.FIRST_DISPLAY_REJECTED,
                now_ns=now_ns,
                candidate_uid=candidate_uid,
                operational_event_id=(
                    operational_event_id if type(operational_event_id) is int else None
                ),
                reason="identity_or_deadline_mismatch",
                detail="SINE 1 display did not match the prepared MIRL token.",
            )
            return

        occurrence = int(_field(fact, "occurrence", 0) or 0)
        popup_request_id = str(_field(fact, "popup_request_id", "") or "")
        sine_episode_uid = str(_field(fact, "episode_uid", "") or "")
        if occurrence <= 0 or not popup_request_id or not sine_episode_uid:
            self._mark_integrity_error("factual SINE 1 display has incomplete identity")
            return

        episode = _Episode(
            episode_id=f"mirl-episode-{secrets.token_hex(16)}",
            session_id=self._session_id,
            candidate_uid=candidate_uid,
            operational_event_id=operational_event_id,
            study_context_token="",
            created_monotonic_ns=now_ns,
            created_wall_time_utc=_wall_time(fact),
            sine_episode_uid=sine_episode_uid,
            first_popup_request_id=popup_request_id,
            first_sine_occurrence=occurrence,
            last_event_ns=now_ns,
        )
        self._episode = episode
        self._pending = None
        self._phase = MirlPhase.WAITING_FOR_RETURN
        created = self._emit(
            MirlEventName.EPISODE_CREATED,
            now_ns=now_ns,
            wall_time=_wall_time(fact),
            sine_stage=1,
            sine_occurrence=occurrence,
            detail="MIRL episode created after factual SINE 1 display.",
        )
        self._emit(
            MirlEventName.SINE_DISPLAYED,
            now_ns=now_ns,
            wall_time=_wall_time(fact),
            sine_stage=1,
            sine_occurrence=occurrence,
            supporting_event_ids=(created.event_id,),
            detail="Factual first SINE display bound to this MIRL episode.",
        )

    def _consume_sine_terminal(
        self,
        fact: object,
        episode: _Episode,
        kind: str,
        now_ns: int,
    ) -> None:
        """Close this episode when the SINE intervention it measured ends.

        The already-CLOSED case never reaches here: ``record_sine_fact``
        returns early for a closed episode, which is exactly the idempotency
        required when SINE_EPISODE_RESOLVED reflects back the verified recovery
        MIRL itself published.  No second terminal event and no duplicate
        package are produced.

        Reaching here with a ``verified_return:`` reason while the episode is
        still active is not a legal state -- SINE only resolves that way after
        monitor.py has drained a package MIRL could publish only from a CLOSED
        episode.  Closing as ABORTED is the safe reading: it publishes nothing,
        and it stops this stale episode from later producing a second package
        for the same trigger candidate.
        """

        reason = str(_field(fact, "reason", "") or "") or kind.lower()
        if reason.startswith(_SINE_VERIFIED_RETURN_PREFIX):
            self._diagnostic = (
                "SINE resolved by verified return while the MIRL episode was "
                "still active"
            )
        self._close_episode_non_recovery(
            episode,
            reason=reason,
            now_ns=now_ns,
            wall_time=_wall_time(fact),
            sine_stage=int(_field(fact, "stage", 0) or 0),
            sine_occurrence=int(_field(fact, "occurrence", 0) or 0),
            terminal_kind=kind,
        )

    def _close_episode_non_recovery(
        self,
        episode: _Episode,
        *,
        reason: str,
        now_ns: int,
        wall_time: str,
        sine_stage: int = 0,
        sine_occurrence: int = 0,
        terminal_kind: str = "",
    ) -> None:
        """Terminate an episode as ABORTED, publishing no recovery evidence."""

        # A terminal fact may carry a timestamp at or slightly before the last
        # event MIRL recorded.  Causal order inside the MIRL ledger is what
        # matters here, so the close is anchored no earlier than that event
        # rather than rejected outright.
        occurred_ns = max(int(now_ns), episode.last_event_ns)
        observed = self._emit(
            MirlEventName.SINE_TERMINATED,
            now_ns=occurred_ns,
            wall_time=wall_time,
            reason=reason,
            sine_stage=sine_stage,
            sine_occurrence=sine_occurrence,
            detail=(
                f"Factual {terminal_kind or 'SINE terminal'} observed; the "
                "intervention this episode was measuring has ended."
            ),
        )
        episode.outcome = EpisodeOutcome.ABORTED
        episode.phase = MirlPhase.CLOSED
        self._phase = episode.phase
        self._emit(
            MirlEventName.EPISODE_CLOSED,
            now_ns=occurred_ns,
            wall_time=wall_time,
            reason=EpisodeOutcome.ABORTED.value,
            supporting_event_ids=(observed.event_id,),
            detail=(
                "MIRL episode closed without recovery because SINE ended the "
                f"intervention ({reason}). No return latency was measured."
            ),
        )

    def _release_pending_display(
        self,
        fact: object,
        kind: str,
        now_ns: int,
    ) -> None:
        """Free the display token when its SINE episode ends before display.

        SINE can cancel or resolve before the popup is ever shown -- COSINE
        precedence, a changed study context, a different distraction resource,
        a superseding trigger.  The token that trigger reserved would otherwise
        sit here for the whole 45 s display deadline, and ``prepare_trigger``
        refuses to mint a token while another first display is pending.  The
        NEXT durable trigger would then reach SINE with no MIRL token at all,
        so its factual SINE 1 display could never open an episode and that
        whole intervention would produce no recovery evidence and no Tr.

        The token predates the MIRL episode, so episode identity does not exist
        yet; candidate, operational event and session are the available -- and
        sufficient -- identity, since one candidate reserves one token.
        """

        pending = self._pending
        if pending is None:
            return
        token = pending.token
        if not (
            _field(fact, "session_id") == token.session_id
            and str(_field(fact, "candidate_uid", "") or "") == token.candidate_uid
            and _field(fact, "operational_event_id") == token.operational_event_id
        ):
            return
        reason = str(_field(fact, "reason", "") or "") or kind.lower()
        self._emit_without_episode(
            MirlEventName.FIRST_DISPLAY_REJECTED,
            now_ns=now_ns,
            candidate_uid=token.candidate_uid,
            operational_event_id=token.operational_event_id,
            reason=reason,
            elapsed_seconds=max(0, now_ns - token.issued_monotonic_ns)
            / NANOSECONDS_PER_SECOND,
            target_seconds=self._policy.first_display_deadline_seconds,
            detail=(
                f"SINE ended this trigger ({reason}) before any factual SINE 1 "
                "display, so the reserved MIRL display token was released."
            ),
        )
        self._pending = None
        self._phase = MirlPhase.IDLE

    @staticmethod
    def _pending_display_effective_deadline(pending: _PendingTrigger, now_ns: int) -> int:
        return pending.token.deadline_monotonic_ns

    def _expire_pending_display(self, now_ns: int) -> None:
        pending = self._pending
        if pending is None or now_ns < self._pending_display_effective_deadline(pending, now_ns):
            return
        token = pending.token
        self._emit_without_episode(
            MirlEventName.FIRST_DISPLAY_TIMED_OUT,
            now_ns=now_ns,
            candidate_uid=token.candidate_uid,
            operational_event_id=token.operational_event_id,
            reason="first_sine_display_deadline_elapsed",
            elapsed_seconds=(now_ns - token.issued_monotonic_ns)
            / NANOSECONDS_PER_SECOND,
            target_seconds=self._policy.first_display_deadline_seconds,
            detail="No matching factual SINE 1 display arrived before the deadline.",
        )
        self._pending = None
        self._phase = MirlPhase.IDLE

    # ------------------------------------------------------------------
    # Return verification and closure confirmation
    # ------------------------------------------------------------------

    def _advance(self, observation: RecoveryObservation) -> None:
        # INSTRUCTION: fail closed.  Once MIRL has seen an impossible factual
        # condition it must become scientifically inert immediately.  Guarding
        # here covers both entry points -- ``observe()`` and
        # ``record_recovery_observation()`` -- so no later focus evidence can
        # advance a timer, reach RETURN_VERIFIED, close an episode as RETURNED
        # or produce a lambda sample.  This stops MIRL only; monitor.py keeps
        # observing Windows and the UI keeps showing diagnostics.
        if not self._integrity_ok:
            return
        episode = self._episode
        if episode is None or episode.phase not in _ACTIVE_PHASES:
            return
        now_ns = observation.observed_monotonic_ns
        if now_ns < episode.created_monotonic_ns:
            self._mark_integrity_error("recovery observation predates episode creation")
            return
        if episode.last_observation_ns is not None and now_ns <= episode.last_observation_ns:
            return

        if not observation.fresh:
            context = RecoveryContext.NEUTRAL
        else:
            context = observation.context

        previous_ns = episode.last_observation_ns
        previous_context = episode.last_context
        if previous_ns is not None:
            gap_ns = now_ns - previous_ns
            if gap_ns > _seconds_to_ns(self._policy.maximum_observation_gap_seconds):
                self._handle_evidence_gap(now_ns, gap_ns, observation.observed_wall_time_utc)
                previous_context = RecoveryContext.NEUTRAL
            elif previous_context is RecoveryContext.FOCUS:
                self._accumulate_focus(gap_ns)

        episode.last_observation_ns = now_ns
        episode.last_context = context

        if episode.phase is MirlPhase.WAITING_FOR_RETURN:
            if context is RecoveryContext.FOCUS:
                self._start_return_verification(observation)
            return

        if episode.phase is MirlPhase.RETURN_VERIFICATION:
            if context is RecoveryContext.DISTRACTION:
                self._interrupt_verification(observation, reason="distraction_observed")
                return
            attempt = episode.attempt
            if (
                context is RecoveryContext.FOCUS
                and attempt is not None
                and attempt.verification_elapsed_ns
                >= _seconds_to_ns(self._policy.return_verification_seconds)
            ):
                self._complete_verification(observation)
            return

        if episode.phase is MirlPhase.CLOSURE_CONFIRMATION:
            if context is RecoveryContext.DISTRACTION:
                self._interrupt_closure(observation, relapse=True, reason="distraction_observed")
                return
            attempt = episode.attempt
            if (
                context is RecoveryContext.FOCUS
                and attempt is not None
                and attempt.closure_elapsed_ns
                >= _seconds_to_ns(self._policy.closure_confirmation_seconds)
            ):
                self._complete_closure(observation)


    def _start_return_verification(self, observation: RecoveryObservation) -> None:
        episode = self._required_episode(MirlPhase.WAITING_FOR_RETURN)
        episode.attempt_count += 1
        episode.attempt = _Attempt(
            attempt_id=f"mirl-attempt-{secrets.token_hex(16)}",
            index=episode.attempt_count,
            verification_started_ns=observation.observed_monotonic_ns,
        )
        episode.phase = MirlPhase.RETURN_VERIFICATION
        self._phase = episode.phase
        started = self._emit(
            MirlEventName.RETURN_VERIFICATION_STARTED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            target_seconds=self._policy.return_verification_seconds,
            detail="Authoritative focus began the ten-second initial return confirmation.",
        )
        self._emit(
            MirlEventName.RETURN_UNVERIFIED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            supporting_event_ids=(started.event_id,),
            detail="Focus is present; recovery entry is not confirmed yet.",
        )

    def _complete_verification(self, observation: RecoveryObservation) -> None:
        episode = self._required_episode(MirlPhase.RETURN_VERIFICATION)
        attempt = self._required_attempt(episode)
        elapsed = attempt.verification_elapsed_ns / NANOSECONDS_PER_SECOND
        if elapsed < self._policy.return_verification_seconds:
            raise RuntimeError("return verification cannot complete early")
        completed = self._emit(
            MirlEventName.RETURN_VERIFICATION_COMPLETED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            elapsed_seconds=elapsed,
            target_seconds=self._policy.return_verification_seconds,
            detail="The ten-second initial return confirmation completed.",
        )
        verified = self._emit(
            MirlEventName.RETURN_VERIFIED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            supporting_event_ids=(completed.event_id,),
            detail=(
                "Recovery entry was confirmed by continuous focus evidence; "
                "final stability is still unverified."
            ),
        )
        attempt.verified_monotonic_ns = observation.observed_monotonic_ns
        attempt.return_verified_event_id = verified.event_id
        episode.phase = MirlPhase.CLOSURE_CONFIRMATION
        self._phase = episode.phase
        attempt.closure_started_ns = observation.observed_monotonic_ns
        attempt.closure_elapsed_ns = 0
        self._emit(
            MirlEventName.CLOSURE_CONFIRMATION_STARTED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            target_seconds=self._policy.closure_confirmation_seconds,
            supporting_event_ids=(verified.event_id,),
            detail="Sixty-second MIRL stability verification started.",
        )

    def _interrupt_verification(
        self,
        observation: RecoveryObservation,
        *,
        reason: str,
    ) -> None:
        episode = self._required_episode(MirlPhase.RETURN_VERIFICATION)
        attempt = self._required_attempt(episode)
        interrupted = self._emit(
            MirlEventName.RETURN_VERIFICATION_INTERRUPTED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            reason=reason,
            elapsed_seconds=attempt.verification_elapsed_ns / NANOSECONDS_PER_SECOND,
            target_seconds=self._policy.return_verification_seconds,
            detail="Initial return confirmation was interrupted; the episode remains open.",
        )
        episode.phase = MirlPhase.WAITING_FOR_RETURN
        self._phase = episode.phase
        episode.attempt = None
        self._emit(
            MirlEventName.EPISODE_RESUMED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            reason="verification_interruption",
            supporting_event_ids=(interrupted.event_id,),
            detail="Episode resumed and is waiting for a new recovery entry.",
        )

    def _interrupt_closure(
        self,
        observation: RecoveryObservation,
        *,
        relapse: bool,
        reason: str,
    ) -> None:
        episode = self._required_episode(MirlPhase.CLOSURE_CONFIRMATION)
        attempt = self._required_attempt(episode)
        interrupted = self._emit(
            MirlEventName.CLOSURE_CONFIRMATION_INTERRUPTED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            reason=reason,
            elapsed_seconds=attempt.closure_elapsed_ns / NANOSECONDS_PER_SECOND,
            target_seconds=self._policy.closure_confirmation_seconds,
            detail="MIRL stability verification was interrupted; the episode stays open.",
        )
        supporting = (interrupted.event_id,)
        if relapse:
            episode.relapse_count += 1
            relapse_event = self._emit(
                MirlEventName.RELAPSE_DETECTED,
                now_ns=observation.observed_monotonic_ns,
                wall_time=observation.observed_wall_time_utc,
                reason=reason,
                supporting_event_ids=supporting,
                detail="Distraction returned during MIRL stability verification.",
            )
            supporting = (relapse_event.event_id,)
        episode.phase = MirlPhase.WAITING_FOR_RETURN
        self._phase = episode.phase
        episode.attempt = None
        self._emit(
            MirlEventName.EPISODE_RESUMED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            reason="closure_interruption",
            supporting_event_ids=supporting,
            detail="Episode resumed after stability verification was interrupted.",
        )

    def _complete_closure(self, observation: RecoveryObservation) -> None:
        episode = self._required_episode(MirlPhase.CLOSURE_CONFIRMATION)
        attempt = self._required_attempt(episode)
        elapsed = attempt.closure_elapsed_ns / NANOSECONDS_PER_SECOND
        if elapsed < self._policy.closure_confirmation_seconds:
            raise RuntimeError("closure confirmation cannot complete early")
        completed = self._emit(
            MirlEventName.CLOSURE_CONFIRMATION_COMPLETED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            elapsed_seconds=elapsed,
            target_seconds=self._policy.closure_confirmation_seconds,
            detail="MIRL stability verification window completed.",
        )
        episode.outcome = EpisodeOutcome.RETURNED
        episode.phase = MirlPhase.CLOSED
        self._phase = episode.phase
        closed = self._emit(
            MirlEventName.EPISODE_CLOSED,
            now_ns=observation.observed_monotonic_ns,
            wall_time=observation.observed_wall_time_utc,
            reason=EpisodeOutcome.RETURNED.value,
            supporting_event_ids=(completed.event_id,),
            detail=(
                "MIRL episode closed after confirmed recovery entry and "
                "sixty-second stability verification."
            ),
        )
        self._publish_verified_recovery_evidence(episode, attempt, closed)

    def _publish_verified_recovery_evidence(
        self,
        episode: _Episode,
        attempt: _Attempt,
        closed_event: MirlEvent,
    ) -> None:
        """Package one completed behavioural recovery without calculating lambda."""

        # Defence in depth.  _advance() already refuses to run after an
        # integrity failure; if any other path ever reaches publication, no
        # scientific package may leave MIRL.
        if not self._integrity_ok:
            return
        verified_ns = attempt.verified_monotonic_ns
        verified_event_id = attempt.return_verified_event_id
        if verified_ns is None or not verified_event_id:
            self._mark_integrity_error(
                "returned episode closed without a RETURN_VERIFIED anchor"
            )
            return
        if episode.outcome is not EpisodeOutcome.RETURNED or episode.phase is not MirlPhase.CLOSED:
            self._mark_integrity_error(
                "recovery evidence requested before returned episode closure"
            )
            return
        # Behavioural return ONSET.  ``verification_started_ns`` belongs to the
        # attempt that actually survived: every interrupted attempt was
        # discarded and a fresh one opened on the next FOCUS observation, so
        # this is the moment the successful return began -- not the moment it
        # was proven.
        started_ns = attempt.verification_started_ns
        elapsed_seconds = (
            started_ns - episode.created_monotonic_ns
        ) / NANOSECONDS_PER_SECOND
        try:
            evidence = VerifiedRecoveryEvidence(
                session_id=episode.session_id,
                profile_type=self._profile_type,
                episode_id=episode.episode_id,
                candidate_uid=episode.candidate_uid,
                operational_event_id=episode.operational_event_id,
                attempt_id=attempt.attempt_id,
                attempt_index=attempt.index,
                first_sine_displayed_monotonic_ns=episode.created_monotonic_ns,
                return_started_monotonic_ns=started_ns,
                return_verified_monotonic_ns=verified_ns,
                episode_closed_monotonic_ns=closed_event.occurred_monotonic_ns,
                verified_recovery_elapsed_seconds=elapsed_seconds,
                verification_focus_seconds=(
                    attempt.verification_elapsed_ns / NANOSECONDS_PER_SECOND
                ),
                closure_confirmation_seconds=(
                    attempt.closure_elapsed_ns / NANOSECONDS_PER_SECOND
                ),
                relapse_count=episode.relapse_count,
                return_verified_event_id=verified_event_id,
                episode_closed_event_id=closed_event.event_id,
            )
        except ValueError as exc:
            # An unpublishable package is an integrity failure, not a crash.
            # Raising here would travel up through observe() into the monitor
            # cycle; failing closed keeps Windows observation alive and simply
            # stops MIRL from producing any further scientific evidence.
            self._mark_integrity_error(f"recovery evidence rejected: {exc}")
            return
        self._verified_recovery_outbox.append(evidence)

    def _handle_evidence_gap(self, now_ns: int, gap_ns: int, wall_time: str) -> None:
        episode = self._episode
        if episode is None:
            return
        self._emit(
            MirlEventName.EVIDENCE_GAP,
            now_ns=now_ns,
            wall_time=wall_time,
            reason="observation_gap_exceeded",
            elapsed_seconds=gap_ns / NANOSECONDS_PER_SECOND,
            target_seconds=self._policy.maximum_observation_gap_seconds,
            detail="Observation gap was too large to count as continuous focus.",
        )
        synthetic = RecoveryObservation(
            context=RecoveryContext.NEUTRAL,
            observed_monotonic_ns=now_ns,
            observed_wall_time_utc=wall_time,
            source="mirl_gap_guard",
            observation_token=f"gap-{now_ns}",
        )
        if episode.phase is MirlPhase.RETURN_VERIFICATION:
            self._interrupt_verification(synthetic, reason="evidence_gap")
        elif episode.phase is MirlPhase.CLOSURE_CONFIRMATION:
            self._interrupt_closure(synthetic, relapse=False, reason="evidence_gap")

    def _accumulate_focus(self, delta_ns: int) -> None:
        episode = self._episode
        if episode is None or delta_ns <= 0 or episode.attempt is None:
            return
        if episode.phase is MirlPhase.RETURN_VERIFICATION:
            episode.attempt.verification_elapsed_ns += delta_ns
        elif episode.phase is MirlPhase.CLOSURE_CONFIRMATION:
            episode.attempt.closure_elapsed_ns += delta_ns

    # ------------------------------------------------------------------
    # Event construction and contract enforcement
    # ------------------------------------------------------------------

    def _emit(
        self,
        name: MirlEventName,
        *,
        now_ns: int,
        wall_time: str | None = None,
        sine_stage: int = 0,
        sine_occurrence: int = 0,
        reason: str = "",
        response: str = "",
        elapsed_seconds: float = 0.0,
        target_seconds: float = 0.0,
        supporting_event_ids: tuple[str, ...] = (),
        detail: str = "",
    ) -> MirlEvent:
        episode = self._episode
        if episode is None:
            raise RuntimeError(f"{name.value} requires an active episode")
        contract = EVENT_CONTRACTS[name]
        if not contract.requires_episode or episode.phase not in contract.allowed_phases:
            raise RuntimeError(
                f"{name.value} is illegal while MIRL phase is {episode.phase.value}"
            )
        attempt = episode.attempt
        if contract.requires_attempt and attempt is None:
            raise RuntimeError(f"{name.value} requires an open recovery attempt")
        if now_ns < episode.created_monotonic_ns or now_ns < episode.last_event_ns:
            raise RuntimeError(f"{name.value} has non-monotonic event time")
        if elapsed_seconds < 0 or target_seconds < 0:
            raise ValueError("event timing values must be non-negative")
        if any(not event_id for event_id in supporting_event_ids):
            raise ValueError("supporting event IDs must not be empty")

        event = MirlEvent(
            kind=f"MIRL_{name.value.upper()}",
            event_name=name,
            event_class=contract.event_class,
            event_id=f"mirl-event-{secrets.token_hex(16)}",
            episode_id=episode.episode_id,
            episode_sequence=episode.next_sequence,
            occurred_monotonic_ns=now_ns,
            occurred_wall_time_utc=wall_time or _utc_now(),
            session_id=episode.session_id,
            candidate_uid=episode.candidate_uid,
            operational_event_id=episode.operational_event_id,
            attempt_id=attempt.attempt_id if attempt else "",
            attempt_index=attempt.index if attempt else 0,
            sine_stage=sine_stage,
            sine_occurrence=sine_occurrence,
            reason=str(reason or ""),
            response=str(response or ""),
            elapsed_seconds=float(elapsed_seconds),
            target_seconds=float(target_seconds),
            supporting_event_ids=tuple(supporting_event_ids),
            detail=str(detail or ""),
        )
        episode.next_sequence += 1
        episode.last_event_ns = now_ns
        episode.events.append(event)
        self._record_event(event)
        return event

    def _emit_without_episode(
        self,
        name: MirlEventName,
        *,
        now_ns: int,
        candidate_uid: str,
        operational_event_id: int | None,
        reason: str = "",
        elapsed_seconds: float = 0.0,
        target_seconds: float = 0.0,
        detail: str = "",
    ) -> MirlEvent:
        contract = EVENT_CONTRACTS[name]
        if contract.requires_episode or self._phase not in contract.allowed_phases:
            raise RuntimeError(f"{name.value} is illegal while MIRL phase is {self._phase.value}")
        event = MirlEvent(
            kind=f"MIRL_{name.value.upper()}",
            event_name=name,
            event_class=contract.event_class,
            event_id=f"mirl-event-{secrets.token_hex(16)}",
            episode_id="",
            episode_sequence=0,
            occurred_monotonic_ns=now_ns,
            occurred_wall_time_utc=_utc_now(),
            session_id=self._session_id,
            candidate_uid=candidate_uid,
            operational_event_id=operational_event_id,
            reason=reason,
            elapsed_seconds=float(elapsed_seconds),
            target_seconds=float(target_seconds),
            detail=detail,
        )
        self._record_event(event)
        return event

    def _record_event(self, event: MirlEvent) -> None:
        self._outbox.append(event)
        self._history.append(event)
        self._last_event = event.event_name.value

    # ------------------------------------------------------------------
    # Boundary helpers
    # ------------------------------------------------------------------

    def _observation_from_monitor_context(self, context: object) -> RecoveryObservation:
        foreground = _field(context, "foreground")
        snapshot = _field(context, "resource_intent")
        verdict = _field(snapshot, "verdict")
        fresh = bool(_field(snapshot, "fresh", False))

        if (
            fresh
            and not _field(context, "study_owned", False)
            and not _field(verdict, "study_context_token", "")
            and self._normal_mode(snapshot, verdict)
        ):
            # Normal (non-Study) mode.  Resource Intent has said explicitly that
            # no study block exists, so its UNCERTAIN classification carries no
            # recovery meaning.  The certified surface on the same verdict does.
            surface = _enum_value(
                _field(_field(verdict, "resource_identity"), "surface", "")
            )
            if surface in _NORMAL_MODE_FOCUS_SURFACES:
                recovery_context = RecoveryContext.FOCUS
            elif surface in _NORMAL_MODE_DISTRACTION_SURFACES:
                recovery_context = RecoveryContext.DISTRACTION
            else:
                recovery_context = RecoveryContext.NEUTRAL
        else:
            recovery_context = RecoveryContext.NEUTRAL

        return RecoveryObservation(
            context=recovery_context,
            observed_monotonic_ns=(
                _context_monotonic_ns(context) or time.monotonic_ns()
            ),
            observed_wall_time_utc=str(
                _field(foreground, "observed_wall_time_utc", "") or _utc_now()
            ),
            source="resource_intent",
            observation_token=str(_field(verdict, "observation_token", "") or "unknown"),
            study_context_token="",
            fresh=fresh,
        )

    @staticmethod
    def _normal_mode(snapshot: object, verdict: object) -> bool:
        """True only when Resource Intent explicitly reports no study block.

        The absence of an allowance is not normal mode.  ``STUDY_PAUSED``,
        ``APPROVED_BREAK``, ``PROTECTED_RED`` and ``COSINE`` are separate
        explicit Resource Intent states and must keep their own precedence, so
        this reads the published reason code rather than inferring anything.

        ``COSINE`` owns its surface outright, so that snapshot precedence flag
        is re-checked here.  It is not interpreted; it is used exactly as the
        snapshot publishes it.

        Protected Red is deliberately NOT checked.  Red is an intervention
        state, not a sensory one: MIRL is the organ that must witness the
        user's factual return so Monitor can release Red from a verified
        package.  Refusing to interpret recovery while Red was active made Red
        unreleasable.  Red keeps its own suppression elsewhere -- Resource
        Intent still withholds idle permission and SINE contribution, and SINE
        itself still refuses to resolve from any observation.
        """

        if bool(_field(snapshot, "cosine_active", False)):
            return False
        reasons = _field(verdict, "negative_reason_codes", ()) or ()
        if isinstance(reasons, (str, bytes)) or not isinstance(reasons, Iterable):
            return False
        return any(_enum_value(reason) == _NORMAL_MODE_REASON for reason in reasons)

    def _fact_matches_episode(self, fact: object, episode: _Episode) -> bool:
        return bool(
            _field(fact, "session_id") == episode.session_id
            and str(_field(fact, "candidate_uid", "") or "") == episode.candidate_uid
            and _field(fact, "operational_event_id") == episode.operational_event_id
            and str(_field(fact, "episode_uid", "") or "") == episode.sine_episode_uid
        )

    def _drain_outbox(self) -> tuple[MirlEvent, ...]:
        facts = tuple(self._outbox)
        self._outbox.clear()
        return facts

    def _required_episode(self, phase: MirlPhase) -> _Episode:
        episode = self._episode
        if episode is None or episode.phase is not phase:
            raise RuntimeError(f"MIRL episode is not in {phase.value}")
        return episode

    @staticmethod
    def _required_attempt(episode: _Episode) -> _Attempt:
        if episode.attempt is None:
            raise RuntimeError("MIRL episode has no open recovery attempt")
        return episode.attempt

    def _active_episode(self) -> bool:
        return bool(self._episode and self._episode.phase in _ACTIVE_PHASES)

    def _ready(self) -> bool:
        return self._session_id is not None and self._integrity_ok

    def _reject(self, reason: str):
        self._diagnostic = reason
        return None

    def _mark_integrity_error(self, reason: str) -> None:
        # Fail closed for MIRL only.  The main monitor may continue operating.
        self._integrity_ok = False
        self._diagnostic = str(reason)
        # Any package still sitting in the outbox has had no effect yet: it has
        # not been drained by monitor.py, so it has not resolved a SINE episode
        # and has not reached the learning path.  Dropping it therefore
        # destroys no durable fact, while letting it escape would feed a Tr
        # produced under evidence MIRL has just declared untrustworthy.  A
        # package already drained is outside MIRL and is deliberately not
        # retracted -- recovery facts are never withdrawn after release.
        self._verified_recovery_outbox.clear()


def _field(value: object, name: str, default=None):
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip().upper()


def _seconds_to_ns(seconds: float) -> int:
    return int(round(float(seconds) * NANOSECONDS_PER_SECOND))


def _positive_int(value: object) -> int | None:
    return value if type(value) is int and value > 0 else None


def _context_monotonic_ns(context: object) -> int | None:
    foreground = _field(context, "foreground")
    return _positive_int(_field(foreground, "observed_monotonic_ns"))


def _wall_time(fact: object) -> str:
    value = str(_field(fact, "occurred_wall_time_utc", "") or "")
    return value or _utc_now()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


__all__ = [
    "EpisodeOutcome",
    "EVENT_CONTRACTS",
    "MIRL_SCHEMA_VERSION",
    "RECOVERY_EVIDENCE_SCHEMA_VERSION",
    "MirlAuthority",
    "MirlDisplayToken",
    "MirlEvent",
    "MirlEventClass",
    "MirlEventName",
    "MirlLiveView",
    "MirlPhase",
    "MirlPolicy",
    "RecoveryContext",
    "RecoveryObservation",
    "VerifiedRecoveryEvidence",
]
