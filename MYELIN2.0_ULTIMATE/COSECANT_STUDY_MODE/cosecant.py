"""The single COSECANT break-return authority for MYELIN.

COSECANT owns one approved break and the overdue return sequence.  It does not
draw a popup, inspect Windows, classify a browser, or resume Study Mode itself.

The final order is fixed:

    selected break duration
        -> BREAK COMPLETE
        -> five minutes
        -> BREAK ALREADY OVER
        -> one minute
        -> COME BACK PLEASE
        -> authoritative matching-study presence
        -> three continuous seconds
        -> RETURN CONFIRMED

Safety rules
------------
* Every deadline uses monotonic nanoseconds.
* A button click is return intent only.  It is never return evidence.
* UNCERTAIN, stale, mismatched or non-exact evidence breaks confirmation.
* The final lock has no Resume action and cannot be dismissed.
* COSECANT retires its BREAK context before reporting a confirmed return.
  The coordinator may then ask ``StudyRuntime`` to resume.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final, Protocol

from CORE_ENGINE.resource_intent import StudyContext
from COSECANT_STUDY_MODE.study import ContextDelivery, StudySnapshot, StudyState


COSECANT_SCHEMA_VERSION: Final = "myelin-cosecant-v2"
NANOSECONDS_PER_SECOND: Final = 1_000_000_000
MINIMUM_BREAK_SECONDS: Final = 60
MAXIMUM_BREAK_SECONDS: Final = 24 * 60 * 60


class CosecantState(str, Enum):
    """The only legal states of one break-return episode."""

    INACTIVE = "INACTIVE"
    BREAK_ACTIVE = "BREAK_ACTIVE"
    BREAK_COMPLETE = "BREAK_COMPLETE"
    BREAK_ALREADY_OVER = "BREAK_ALREADY_OVER"
    FINAL_LOCK = "FINAL_LOCK"
    RETURN_CONFIRMING = "RETURN_CONFIRMING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    SHUTDOWN = "SHUTDOWN"


class CosecantMessage(str, Enum):
    """Presentation meaning selected by policy, not wording invented by UI."""

    NONE = ""
    BREAK_COMPLETE = "BREAK COMPLETE"
    BREAK_ALREADY_OVER = "BREAK ALREADY OVER"
    COME_BACK_PLEASE = "COME BACK PLEASE"
    RETURN_CONFIRMING = "RETURN CONFIRMING"
    RETURN_CONFIRMED = "RETURN CONFIRMED"


class CosecantUiAction(str, Enum):
    """Intent actions an earlier reminder may present."""

    RETURN_TO_STUDY = "RETURN_TO_STUDY"


class StudyPresence(str, Enum):
    """Authoritative return evidence supplied by the engine monitor."""

    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNCERTAIN = "UNCERTAIN"


class CosecantFactKind(str, Enum):
    BREAK_STARTED = "BREAK_STARTED"
    BREAK_COMPLETE = "BREAK_COMPLETE"
    BREAK_ALREADY_OVER = "BREAK_ALREADY_OVER"
    FINAL_LOCKED = "FINAL_LOCKED"
    RETURN_INTENT_RECORDED = "RETURN_INTENT_RECORDED"
    RETURN_CONFIRMATION_STARTED = "RETURN_CONFIRMATION_STARTED"
    RETURN_CONFIRMATION_RESTARTED = "RETURN_CONFIRMATION_RESTARTED"
    RETURN_CONFIRMATION_LOST = "RETURN_CONFIRMATION_LOST"
    RETURN_CONFIRMED = "RETURN_CONFIRMED"
    BREAK_CANCELLED = "BREAK_CANCELLED"
    SAFE_SHUTDOWN = "SAFE_SHUTDOWN"


class StudyContextAuthority(Protocol):
    """The narrow Resource Intent connection required by COSECANT."""

    def publish_study_context(self, context: StudyContext) -> bool: ...

    def retire_study_context(self, expected_context_token: str = "") -> bool: ...


@dataclass(frozen=True, slots=True)
class CosecantPolicy:
    """Visible timing rules; only tests should normally shorten them."""

    already_over_delay_seconds: float = 5 * 60
    final_lock_delay_seconds: float = 60
    return_confirmation_seconds: float = 3
    # W-7 / C9-B.  Measured, not guessed.  C9-A recorded 1600 real intervals of
    # E = A(i) - O(i-1) at production cadence -- the gap COSECANT actually gates
    # on, which is the observation cadence PLUS the sensing/integration latency
    # that lands before advance() checks freshness.
    #
    # Monitor's 1.5 s cadence was stable through conditions A-D (largest dO
    # there was 1.6232 s).  C9-A also observed one break-admission transient in
    # condition E with dO = 2.4169 s, while COSECANT was still INACTIVE; that
    # transient is not steady-state BREAK_ACTIVE continuity.  The major B/D tail
    # excursions were dominated by Browser/UIA processing latency.
    #
    # 2.2 s sits above the slowest ordinary successful observation measured
    # (2.0824 s) with ~118 ms headroom.  It remains below the observed
    # non-steady/failure tail events:
    #   2.5383 s  break-admission transient, COSECANT still INACTIVE
    #   2.6531 s  resource/identity transition
    #   2.6767 s  address_value_invalid
    #   2.8283 s  window_not_found
    #
    # G is sized for timing space between successive valid confirmation
    # observations.  It is not enlarged to absorb pre-gate admission work,
    # Browser/UIA failures, or identity changes -- those SHOULD break continuous
    # presence, and they have their own evidence rules.
    #
    # G < return_confirmation_seconds is load-bearing and leaves 0.8 s of
    # separation here.  A G at or above C would make the continuous 3-second
    # proof meaningless.
    maximum_presence_gap_seconds: float = 2.2

    def __post_init__(self) -> None:
        for name in (
            "already_over_delay_seconds",
            "final_lock_delay_seconds",
            "return_confirmation_seconds",
            "maximum_presence_gap_seconds",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{name} must be a number")
            if not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive")

        # C10.1.  The G < C relationship documented above is load-bearing, so
        # it is enforced here rather than merely described.  Both runtime gates
        # compare with a strict ``>``, which means a gap of exactly G is legal.
        # If G were allowed to reach C, then a presence observation at t=0 and
        # the next one at t=C would produce a legal gap that ALSO satisfies the
        # confirmation deadline -- two isolated observations C seconds apart
        # would become indistinguishable from C seconds of continuous observed
        # presence, which is the one thing the return proof exists to
        # establish.  An unhealthy policy must therefore be impossible to
        # construct, not merely discouraged.
        if (
            float(self.maximum_presence_gap_seconds)
            >= float(self.return_confirmation_seconds)
        ):
            raise ValueError(
                "maximum_presence_gap_seconds must be strictly less than "
                "return_confirmation_seconds"
            )


@dataclass(frozen=True, slots=True)
class CosecantReturnTarget:
    """The exact Study resource this break expects the user to return to.

    Frozen at break admission from one normal Monitor observation, and never
    recomputed afterwards.  It answers exactly one question:

        "What resource releases this lock?"

    Deliberately opaque.  It carries no title, no URL, no content id, no HWND
    or PID, no Resource Intent stable_key, and no score or lifecycle state.
    ``resource_token`` is Browser's session-private keyed identity, which is
    the only exact-resource primitive in MYELIN that survives a tab switch, a
    window change and a browser restart within one session.

    ``resource_token`` and ``platform_key`` must be non-empty.  That is the
    fail-closed rule expressed in the type itself: a break whose return could
    never be proved must be impossible to construct, not merely impolite.

    This class only REMEMBERS the target.  Deciding whether a current
    observation matches it is a separate authority and deliberately does not
    live here yet.
    """

    study_context_token: str
    platform_key: str
    resource_token: str
    observed_monotonic_ns: int

    def __post_init__(self) -> None:
        for name in ("study_context_token", "platform_key", "resource_token"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"{name} must be a non-empty string for an exact return target"
                )
        if type(self.observed_monotonic_ns) is not int:
            raise TypeError("observed_monotonic_ns must be an integer")
        if self.observed_monotonic_ns < 0:
            raise ValueError("observed_monotonic_ns cannot be negative")


@dataclass(frozen=True, slots=True)
class StudyReturnObservation:
    """One exact return observation; generic foreground focus is insufficient."""

    presence: StudyPresence
    study_block_id: str
    break_id: str
    context_token: str
    observed_monotonic_ns: int
    source: str
    evidence_token: str
    fresh: bool
    exact_resource_confirmed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.presence, StudyPresence):
            raise TypeError("presence must be a StudyPresence")
        for name in (
            "study_block_id",
            "break_id",
            "context_token",
            "source",
            "evidence_token",
        ):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} cannot be empty")
        if type(self.observed_monotonic_ns) is not int:
            raise TypeError("observed_monotonic_ns must be an integer")
        if self.observed_monotonic_ns < 0:
            raise ValueError("observed_monotonic_ns cannot be negative")
        if type(self.fresh) is not bool:
            raise TypeError("fresh must be a boolean")
        if type(self.exact_resource_confirmed) is not bool:
            raise TypeError("exact_resource_confirmed must be a boolean")

    @property
    def proves_presence(self) -> bool:
        return (
            self.presence is StudyPresence.PRESENT
            and self.fresh
            and self.exact_resource_confirmed
        )


@dataclass(frozen=True, slots=True)
class CosecantFact:
    """One immutable COSECANT fact for telemetry, popup routing or storage."""

    sequence: int
    kind: CosecantFactKind
    break_id: str
    study_block_id: str
    from_state: CosecantState
    to_state: CosecantState
    effective_monotonic_ns: int
    observed_monotonic_ns: int
    occurred_wall_time_utc: str
    message: str
    evidence_token: str = ""
    schema_version: str = COSECANT_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CosecantSnapshot:
    """The one immutable COSECANT view for the engine and presentation UI."""

    state: CosecantState
    generation: int
    break_id: str
    study_block_id: str
    study_generation: int
    study_context_token: str
    intended_return_target: CosecantReturnTarget | None
    subject: str
    task: str
    selected_break_seconds: int
    break_started_monotonic_ns: int | None
    break_ends_monotonic_ns: int | None
    already_over_due_monotonic_ns: int | None
    final_lock_due_monotonic_ns: int | None
    confirmation_started_monotonic_ns: int | None
    confirmation_due_monotonic_ns: int | None
    seconds_to_next_stage: int | None
    overdue_seconds: float
    confirmation_elapsed_seconds: float
    message: CosecantMessage
    popup_required: bool
    popup_must_remain_open: bool
    allowed_actions: tuple[CosecantUiAction, ...]
    final_locked: bool
    return_confirmed: bool
    context_delivery: ContextDelivery
    last_action: str
    fact_sequence: int
    schema_version: str = COSECANT_SCHEMA_VERSION

    @property
    def resume_button_allowed(self) -> bool:
        """The final lock can never expose a Resume button."""

        return CosecantUiAction.RETURN_TO_STUDY in self.allowed_actions


@dataclass(frozen=True, slots=True)
class CosecantResult:
    """Truth returned after each command or observation."""

    accepted: bool
    message: str
    snapshot: CosecantSnapshot
    facts: tuple[CosecantFact, ...] = ()


_ACTIVE_STATES: Final = frozenset(
    {
        CosecantState.BREAK_ACTIVE,
        CosecantState.BREAK_COMPLETE,
        CosecantState.BREAK_ALREADY_OVER,
        CosecantState.FINAL_LOCK,
        CosecantState.RETURN_CONFIRMING,
    }
)


class CosecantRuntime:
    """Thread-safe owner of one approved break and its return confirmation."""

    def __init__(
        self,
        *,
        context_authority: StudyContextAuthority,
        policy: CosecantPolicy | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_clock_utc: Callable[[], datetime] | None = None,
    ) -> None:
        if context_authority is None:
            raise ValueError("CosecantRuntime requires a Resource Intent authority")
        self._context_authority = context_authority
        self._policy = policy or CosecantPolicy()
        self._monotonic_ns = monotonic_ns
        self._wall_clock_utc = wall_clock_utc or (
            lambda: datetime.now(timezone.utc)
        )
        self._lock = threading.RLock()

        self._state = CosecantState.INACTIVE
        self._generation = 0
        self._fact_sequence = 0
        self._break_id = ""
        self._study_block_id = ""
        self._study_generation = 0
        self._study_context_token = ""
        self._intended_return_target: CosecantReturnTarget | None = None
        self._subject = ""
        self._task = ""
        self._selected_break_seconds = 0

        self._break_started_ns: int | None = None
        self._break_ends_ns: int | None = None
        self._already_over_due_ns: int | None = None
        self._final_lock_due_ns: int | None = None
        self._confirmation_started_ns: int | None = None
        self._confirmation_due_ns: int | None = None
        self._last_presence_ns: int | None = None
        self._confirmation_origin: CosecantState | None = None
        # Two independent time domains that must never write each other.
        # ``_last_monotonic_ns`` is COSECANT's own clock progression, owned by
        # ``_read_monotonic``.  ``_last_observation_ns`` is the ordering of
        # incoming return evidence, owned by ``observe_return``.  The monitor
        # legitimately samples the foreground BEFORE calling ``advance()``, so
        # a valid observation is normally older than the current clock reading.
        self._last_monotonic_ns = -1
        self._last_observation_ns = -1
        self._terminal_overdue_seconds: float | None = None
        self._context_delivery = ContextDelivery.NOT_PUBLISHED
        self._last_action = "COSECANT is inactive"

        self._snapshot = self._make_snapshot(now_ns=None)

    # ------------------------------------------------------------------
    # Public commands.  Presentation code receives facts; it owns no state.
    # ------------------------------------------------------------------

    def start_break(
        self,
        *,
        study: StudySnapshot,
        selected_break_seconds: int,
        intended_return_target: CosecantReturnTarget,
    ) -> CosecantResult:
        """Start an approved break from one exact paused Study snapshot.

        ``intended_return_target`` is REQUIRED.  A managed break escalates to a
        FINAL_LOCK that only factual return evidence can release, so admitting
        one without knowing which resource releases it would create a lock with
        no key.  The parameter is mandatory rather than optional so that
        omission is a loud TypeError instead of a quietly unreleasable break.
        """

        if not isinstance(study, StudySnapshot):
            raise TypeError("study must be a StudySnapshot")
        if type(selected_break_seconds) is not int:
            raise TypeError("selected_break_seconds must be an integer")
        if not MINIMUM_BREAK_SECONDS <= selected_break_seconds <= MAXIMUM_BREAK_SECONDS:
            raise ValueError(
                "selected_break_seconds must be between 60 seconds and 24 hours"
            )
        if not isinstance(intended_return_target, CosecantReturnTarget):
            raise TypeError(
                "intended_return_target must be a CosecantReturnTarget"
            )

        with self._lock:
            if self._state in _ACTIVE_STATES:
                return self._reject("Another COSECANT break is already active")
            if self._state is CosecantState.SHUTDOWN:
                return self._reject("COSECANT has already shut down")
            if study.state is not StudyState.PAUSED:
                return self._reject("Study Mode must be PAUSED before a break")
            if not study.block_id or not study.context_token:
                return self._reject("The Study snapshot has no exact identity")
            if intended_return_target.study_context_token != study.context_token:
                return self._reject(
                    "The return target belongs to a different Study block"
                )

            now_ns = self._read_monotonic()
            now_wall = self._read_wall_clock()

            # The target must have been observed inside THIS Study session and
            # not after the break began.  ``_StudyActiveEpoch.end`` deliberately
            # keeps the last ACTIVE boundary when Study pauses, so the paused
            # snapshot still carries the epoch the evidence must belong to.
            # Together these reject stale pre-Study evidence and any
            # future-dated observation without inventing a freshness constant.
            if intended_return_target.observed_monotonic_ns < study.active_epoch_monotonic_ns:
                return self._reject(
                    "The return target predates this Study session"
                )
            if intended_return_target.observed_monotonic_ns > now_ns:
                return self._reject("The return target is dated in the future")

            self._generation += 1
            self._break_id = secrets.token_hex(12)
            self._study_block_id = study.block_id
            self._study_generation = study.generation
            self._study_context_token = study.context_token
            self._intended_return_target = intended_return_target
            self._subject = study.subject
            self._task = study.task
            self._selected_break_seconds = selected_break_seconds
            self._break_started_ns = now_ns
            self._break_ends_ns = now_ns + selected_break_seconds * NANOSECONDS_PER_SECOND
            self._already_over_due_ns = (
                self._break_ends_ns
                + _seconds_to_ns(self._policy.already_over_delay_seconds)
            )
            self._final_lock_due_ns = (
                self._already_over_due_ns
                + _seconds_to_ns(self._policy.final_lock_delay_seconds)
            )
            self._clear_confirmation()
            self._terminal_overdue_seconds = None

            previous = self._state
            self._state = CosecantState.BREAK_ACTIVE
            if not self._publish_break_context(now_ns):
                # A failed start must not leave a hidden BREAK authority.
                self._retire_break_context()
                self._state = previous
                self._clear_episode()
                self._snapshot = self._make_snapshot(now_ns=now_ns)
                return self._reject("Resource Intent rejected the approved break")

            self._last_action = "Approved break started"
            fact = self._new_fact(
                CosecantFactKind.BREAK_STARTED,
                from_state=previous,
                to_state=self._state,
                effective_ns=now_ns,
                observed_ns=now_ns,
                now_wall=now_wall,
                message="Approved break started",
            )
            self._snapshot = self._make_snapshot(now_ns=now_ns)
            return self._accept("Approved break started", (fact,))

    def advance(self) -> CosecantResult:
        """Apply every due break deadline in chronological order."""

        with self._lock:
            if self._state not in _ACTIVE_STATES:
                return self._accept("No active COSECANT deadline", ())
            now_ns = self._read_monotonic()
            now_wall = self._read_wall_clock()
            facts: list[CosecantFact] = []

            # A delayed engine cycle may cross several deadlines.  Catch up in
            # exact deadline order so telemetry does not lose factual stages.
            if (
                self._state is CosecantState.BREAK_ACTIVE
                and self._break_ends_ns is not None
                and now_ns >= self._break_ends_ns
            ):
                facts.append(
                    self._transition(
                        CosecantState.BREAK_COMPLETE,
                        CosecantFactKind.BREAK_COMPLETE,
                        effective_ns=self._break_ends_ns,
                        observed_ns=now_ns,
                        now_wall=now_wall,
                        message=CosecantMessage.BREAK_COMPLETE.value,
                    )
                )

            if (
                self._state is CosecantState.BREAK_COMPLETE
                and self._already_over_due_ns is not None
                and now_ns >= self._already_over_due_ns
            ):
                facts.append(
                    self._transition(
                        CosecantState.BREAK_ALREADY_OVER,
                        CosecantFactKind.BREAK_ALREADY_OVER,
                        effective_ns=self._already_over_due_ns,
                        observed_ns=now_ns,
                        now_wall=now_wall,
                        message=CosecantMessage.BREAK_ALREADY_OVER.value,
                    )
                )

            if (
                self._state is CosecantState.BREAK_ALREADY_OVER
                and self._final_lock_due_ns is not None
                and now_ns >= self._final_lock_due_ns
            ):
                facts.append(
                    self._transition(
                        CosecantState.FINAL_LOCK,
                        CosecantFactKind.FINAL_LOCKED,
                        effective_ns=self._final_lock_due_ns,
                        observed_ns=now_ns,
                        now_wall=now_wall,
                        message=CosecantMessage.COME_BACK_PLEASE.value,
                    )
                )

            if self._state is CosecantState.RETURN_CONFIRMING:
                maximum_gap_ns = _seconds_to_ns(
                    self._policy.maximum_presence_gap_seconds
                )
                if (
                    self._last_presence_ns is None
                    or now_ns - self._last_presence_ns > maximum_gap_ns
                ):
                    facts.append(
                        self._lose_confirmation(
                            now_ns=now_ns,
                            now_wall=now_wall,
                            evidence_token="",
                            message="Continuous return evidence became stale",
                        )
                    )

            if self._state in _ACTIVE_STATES:
                self._publish_break_context(now_ns)
            self._snapshot = self._make_snapshot(now_ns=now_ns)
            return self._accept("COSECANT time advanced", tuple(facts))

    def record_return_intent(self) -> CosecantResult:
        """Record an earlier reminder click without treating it as evidence."""

        with self._lock:
            if self._state not in {
                CosecantState.BREAK_COMPLETE,
                CosecantState.BREAK_ALREADY_OVER,
            }:
                return self._reject("Return intent is unavailable in this state")
            now_ns = self._read_monotonic()
            now_wall = self._read_wall_clock()
            fact = self._new_fact(
                CosecantFactKind.RETURN_INTENT_RECORDED,
                from_state=self._state,
                to_state=self._state,
                effective_ns=now_ns,
                observed_ns=now_ns,
                now_wall=now_wall,
                message="Return intent recorded; waiting for observed study presence",
            )
            self._last_action = fact.message
            self._snapshot = self._make_snapshot(now_ns=now_ns)
            return self._accept(fact.message, (fact,))

    def observe_return(self, observation: StudyReturnObservation) -> CosecantResult:
        """Apply exact evidence and confirm only three continuous seconds."""

        if not isinstance(observation, StudyReturnObservation):
            raise TypeError("observation must be a StudyReturnObservation")
        with self._lock:
            if self._state not in _ACTIVE_STATES:
                return self._reject("There is no active break-return episode")
            if not self._observation_matches(observation):
                return self._reject("Return observation identity does not match")
            # Evidence ordering only.  Comparing against the internal clock
            # here rejected every observation the monitor captured before its
            # own ``advance()`` call, which is the normal cycle order.
            if observation.observed_monotonic_ns < self._last_observation_ns:
                return self._reject("Return observation arrived out of order")

            now_ns = observation.observed_monotonic_ns
            self._last_observation_ns = now_ns
            now_wall = self._read_wall_clock()
            facts: list[CosecantFact] = []

            # Return confirmation starts only after the selected break ends.
            if self._break_ends_ns is None or now_ns < self._break_ends_ns:
                self._snapshot = self._make_snapshot(now_ns=now_ns)
                return self._accept("Selected break is still active", ())

            facts.extend(self._apply_due_stages(now_ns, now_wall))

            if not observation.proves_presence:
                if self._state is CosecantState.RETURN_CONFIRMING:
                    facts.append(
                        self._lose_confirmation(
                            now_ns=now_ns,
                            now_wall=now_wall,
                            evidence_token=observation.evidence_token,
                            message="Continuous return evidence was lost",
                        )
                    )
                self._snapshot = self._make_snapshot(now_ns=now_ns)
                return self._accept("Observation does not prove a Study return", tuple(facts))

            if self._state is not CosecantState.RETURN_CONFIRMING:
                origin = self._state
                self._confirmation_origin = origin
                self._confirmation_started_ns = now_ns
                self._confirmation_due_ns = now_ns + _seconds_to_ns(
                    self._policy.return_confirmation_seconds
                )
                self._last_presence_ns = now_ns
                self._state = CosecantState.RETURN_CONFIRMING
                self._last_action = "Three-second return confirmation started"
                facts.append(
                    self._new_fact(
                        CosecantFactKind.RETURN_CONFIRMATION_STARTED,
                        from_state=origin,
                        to_state=self._state,
                        effective_ns=now_ns,
                        observed_ns=now_ns,
                        now_wall=now_wall,
                        message=self._last_action,
                        evidence_token=observation.evidence_token,
                    )
                )
                self._snapshot = self._make_snapshot(now_ns=now_ns)
                return self._accept(self._last_action, tuple(facts))

            maximum_gap_ns = _seconds_to_ns(
                self._policy.maximum_presence_gap_seconds
            )
            if (
                self._last_presence_ns is None
                or now_ns - self._last_presence_ns > maximum_gap_ns
            ):
                # A large evidence gap cannot be silently counted as presence.
                self._confirmation_started_ns = now_ns
                self._confirmation_due_ns = now_ns + _seconds_to_ns(
                    self._policy.return_confirmation_seconds
                )
                self._last_presence_ns = now_ns
                self._last_action = "Return confirmation restarted after an evidence gap"
                facts.append(
                    self._new_fact(
                        CosecantFactKind.RETURN_CONFIRMATION_RESTARTED,
                        from_state=self._state,
                        to_state=self._state,
                        effective_ns=now_ns,
                        observed_ns=now_ns,
                        now_wall=now_wall,
                        message=self._last_action,
                        evidence_token=observation.evidence_token,
                    )
                )
                self._snapshot = self._make_snapshot(now_ns=now_ns)
                return self._accept(self._last_action, tuple(facts))

            self._last_presence_ns = now_ns
            if self._confirmation_due_ns is not None and now_ns >= self._confirmation_due_ns:
                previous = self._state
                self._terminal_overdue_seconds = self._overdue_seconds(now_ns)
                self._state = CosecantState.CONFIRMED
                self._last_action = "Study return confirmed"
                self._retire_break_context()
                fact = self._new_fact(
                    CosecantFactKind.RETURN_CONFIRMED,
                    from_state=previous,
                    to_state=self._state,
                    effective_ns=self._confirmation_due_ns,
                    observed_ns=now_ns,
                    now_wall=now_wall,
                    message=self._last_action,
                    evidence_token=observation.evidence_token,
                )
                facts.append(fact)

            self._snapshot = self._make_snapshot(now_ns=now_ns)
            return self._accept(self._last_action, tuple(facts))

    def cancel_for_session_end(self) -> CosecantResult:
        """Cancel only when the owning Study/lifecycle authority ends."""

        with self._lock:
            if self._state not in _ACTIVE_STATES:
                return self._reject("There is no active break to cancel")
            now_ns = self._read_monotonic()
            now_wall = self._read_wall_clock()
            previous = self._state
            self._terminal_overdue_seconds = self._overdue_seconds(now_ns)
            self._state = CosecantState.CANCELLED
            self._clear_confirmation()
            self._retire_break_context()
            self._last_action = "Break cancelled because the Study session ended"
            fact = self._new_fact(
                CosecantFactKind.BREAK_CANCELLED,
                from_state=previous,
                to_state=self._state,
                effective_ns=now_ns,
                observed_ns=now_ns,
                now_wall=now_wall,
                message=self._last_action,
            )
            self._snapshot = self._make_snapshot(now_ns=now_ns)
            return self._accept(self._last_action, (fact,))

    def shutdown(self) -> CosecantResult:
        """Retire BREAK authority and make this runtime permanently inert."""

        with self._lock:
            if self._state is CosecantState.SHUTDOWN:
                return self._accept("COSECANT is already shut down", ())
            now_ns = self._read_monotonic()
            now_wall = self._read_wall_clock()
            previous = self._state

            # No break ever existed in this runtime.  Shutting down an
            # inactive COSECANT authority is a lifecycle operation, not a
            # factual break event.  Emitting SAFE_SHUTDOWN here would create
            # a durable row with an empty break_id and sequence 1 on every
            # engine session, causing false cross-session identity collisions.
            if previous is CosecantState.INACTIVE:
                self._state = CosecantState.SHUTDOWN
                self._clear_confirmation()
                self._last_action = "COSECANT shut down safely"
                self._snapshot = self._make_snapshot(now_ns=now_ns)
                return self._accept(self._last_action, ())

            if self._state in _ACTIVE_STATES:
                self._terminal_overdue_seconds = self._overdue_seconds(now_ns)
            self._retire_break_context()
            self._state = CosecantState.SHUTDOWN
            self._clear_confirmation()
            self._last_action = "COSECANT shut down safely"
            fact = self._new_fact(
                CosecantFactKind.SAFE_SHUTDOWN,
                from_state=previous,
                to_state=self._state,
                effective_ns=now_ns,
                observed_ns=now_ns,
                now_wall=now_wall,
                message=self._last_action,
            )
            self._snapshot = self._make_snapshot(now_ns=now_ns)
            return self._accept(self._last_action, (fact,))

    def snapshot(self) -> CosecantSnapshot:
        """Return cached truth without advancing any deadline."""

        with self._lock:
            return self._snapshot

    # ------------------------------------------------------------------
    # Internal state, evidence and Resource Intent helpers.
    # ------------------------------------------------------------------

    def _apply_due_stages(
        self,
        now_ns: int,
        now_wall: datetime,
    ) -> list[CosecantFact]:
        """Catch up reminder stages for an observation arriving after a gap."""

        facts: list[CosecantFact] = []
        if (
            self._state is CosecantState.BREAK_ACTIVE
            and self._break_ends_ns is not None
            and now_ns >= self._break_ends_ns
        ):
            facts.append(
                self._transition(
                    CosecantState.BREAK_COMPLETE,
                    CosecantFactKind.BREAK_COMPLETE,
                    effective_ns=self._break_ends_ns,
                    observed_ns=now_ns,
                    now_wall=now_wall,
                    message=CosecantMessage.BREAK_COMPLETE.value,
                )
            )
        if (
            self._state is CosecantState.BREAK_COMPLETE
            and self._already_over_due_ns is not None
            and now_ns >= self._already_over_due_ns
        ):
            facts.append(
                self._transition(
                    CosecantState.BREAK_ALREADY_OVER,
                    CosecantFactKind.BREAK_ALREADY_OVER,
                    effective_ns=self._already_over_due_ns,
                    observed_ns=now_ns,
                    now_wall=now_wall,
                    message=CosecantMessage.BREAK_ALREADY_OVER.value,
                )
            )
        if (
            self._state is CosecantState.BREAK_ALREADY_OVER
            and self._final_lock_due_ns is not None
            and now_ns >= self._final_lock_due_ns
        ):
            facts.append(
                self._transition(
                    CosecantState.FINAL_LOCK,
                    CosecantFactKind.FINAL_LOCKED,
                    effective_ns=self._final_lock_due_ns,
                    observed_ns=now_ns,
                    now_wall=now_wall,
                    message=CosecantMessage.COME_BACK_PLEASE.value,
                )
            )
        return facts

    def _observation_matches(self, observation: StudyReturnObservation) -> bool:
        return (
            observation.study_block_id == self._study_block_id
            and observation.break_id == self._break_id
            and observation.context_token == self._study_context_token
        )

    def _lose_confirmation(
        self,
        *,
        now_ns: int,
        now_wall: datetime,
        evidence_token: str,
        message: str,
    ) -> CosecantFact:
        previous = self._state
        restored = self._stage_for_time(now_ns)
        self._state = restored
        self._clear_confirmation()
        self._last_action = message
        return self._new_fact(
            CosecantFactKind.RETURN_CONFIRMATION_LOST,
            from_state=previous,
            to_state=restored,
            effective_ns=now_ns,
            observed_ns=now_ns,
            now_wall=now_wall,
            message=message,
            evidence_token=evidence_token,
        )

    def _stage_for_time(self, now_ns: int) -> CosecantState:
        if self._final_lock_due_ns is not None and now_ns >= self._final_lock_due_ns:
            return CosecantState.FINAL_LOCK
        if self._already_over_due_ns is not None and now_ns >= self._already_over_due_ns:
            return CosecantState.BREAK_ALREADY_OVER
        if self._break_ends_ns is not None and now_ns >= self._break_ends_ns:
            return CosecantState.BREAK_COMPLETE
        return CosecantState.BREAK_ACTIVE

    def _transition(
        self,
        new_state: CosecantState,
        kind: CosecantFactKind,
        *,
        effective_ns: int,
        observed_ns: int,
        now_wall: datetime,
        message: str,
    ) -> CosecantFact:
        previous = self._state
        self._state = new_state
        self._last_action = message
        return self._new_fact(
            kind,
            from_state=previous,
            to_state=new_state,
            effective_ns=effective_ns,
            observed_ns=observed_ns,
            now_wall=now_wall,
            message=message,
        )

    def _new_fact(
        self,
        kind: CosecantFactKind,
        *,
        from_state: CosecantState,
        to_state: CosecantState,
        effective_ns: int,
        observed_ns: int,
        now_wall: datetime,
        message: str,
        evidence_token: str = "",
    ) -> CosecantFact:
        self._fact_sequence += 1
        return CosecantFact(
            sequence=self._fact_sequence,
            kind=kind,
            break_id=self._break_id,
            study_block_id=self._study_block_id,
            from_state=from_state,
            to_state=to_state,
            effective_monotonic_ns=effective_ns,
            observed_monotonic_ns=observed_ns,
            occurred_wall_time_utc=_wall_text(now_wall),
            message=message,
            evidence_token=evidence_token,
        )

    def _build_break_context(self, now_ns: int) -> StudyContext:
        if not self._study_block_id or not self._study_context_token:
            raise RuntimeError("An exact Study identity is required for a break")
        remaining = 0
        if self._break_ends_ns is not None:
            remaining = max(
                0,
                math.ceil((self._break_ends_ns - now_ns) / NANOSECONDS_PER_SECOND),
            )
        return StudyContext(
            block_id=self._study_block_id,
            generation=self._study_generation,
            display_state="BREAK",
            subject=self._subject,
            task=self._task,
            protection_active=False,
            planned_break_active=True,
            remaining_seconds=remaining,
            published_monotonic_ns=now_ns,
            context_token=self._study_context_token,
        )

    def _publish_break_context(self, now_ns: int) -> bool:
        try:
            accepted = bool(
                self._context_authority.publish_study_context(
                    self._build_break_context(now_ns)
                )
            )
        except Exception:
            accepted = False
        self._context_delivery = (
            ContextDelivery.CONFIRMED if accepted else ContextDelivery.DEGRADED
        )
        return accepted

    def _retire_break_context(self) -> bool:
        if not self._study_context_token:
            self._context_delivery = ContextDelivery.RETIRED
            return True
        try:
            retired = bool(
                self._context_authority.retire_study_context(
                    expected_context_token=self._study_context_token
                )
            )
        except Exception:
            retired = False
        if retired or self._context_delivery is ContextDelivery.RETIRED:
            self._context_delivery = ContextDelivery.RETIRED
            return True
        self._context_delivery = ContextDelivery.DEGRADED
        return False

    def _read_monotonic(self) -> int:
        value = self._monotonic_ns()
        if type(value) is not int or value < 0:
            raise RuntimeError("The monotonic clock returned an invalid value")
        if value < self._last_monotonic_ns:
            raise RuntimeError("The monotonic clock moved backwards")
        self._last_monotonic_ns = value
        return value

    def _read_wall_clock(self) -> datetime:
        value = self._wall_clock_utc()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise RuntimeError("The wall clock must return a timezone-aware datetime")
        return value.astimezone(timezone.utc)

    def _overdue_seconds(self, now_ns: int) -> float:
        if self._terminal_overdue_seconds is not None:
            return self._terminal_overdue_seconds
        if self._break_ends_ns is None:
            return 0.0
        return max(0, now_ns - self._break_ends_ns) / NANOSECONDS_PER_SECOND

    def _make_snapshot(self, *, now_ns: int | None) -> CosecantSnapshot:
        seconds_to_next: int | None = None
        if now_ns is not None:
            deadline = self._next_deadline()
            if deadline is not None:
                seconds_to_next = max(
                    0, math.ceil((deadline - now_ns) / NANOSECONDS_PER_SECOND)
                )

        confirmation_elapsed = 0.0
        if now_ns is not None and self._confirmation_started_ns is not None:
            confirmation_elapsed = max(
                0.0,
                (now_ns - self._confirmation_started_ns) / NANOSECONDS_PER_SECOND,
            )

        final_locked = (
            self._state is CosecantState.FINAL_LOCK
            or (
                self._state is CosecantState.RETURN_CONFIRMING
                and self._confirmation_origin is CosecantState.FINAL_LOCK
            )
        )
        allowed_actions: tuple[CosecantUiAction, ...] = ()
        if self._state in {
            CosecantState.BREAK_COMPLETE,
            CosecantState.BREAK_ALREADY_OVER,
        }:
            allowed_actions = (CosecantUiAction.RETURN_TO_STUDY,)

        return CosecantSnapshot(
            state=self._state,
            generation=self._generation,
            break_id=self._break_id,
            study_block_id=self._study_block_id,
            study_generation=self._study_generation,
            study_context_token=self._study_context_token,
            intended_return_target=self._intended_return_target,
            subject=self._subject,
            task=self._task,
            selected_break_seconds=self._selected_break_seconds,
            break_started_monotonic_ns=self._break_started_ns,
            break_ends_monotonic_ns=self._break_ends_ns,
            already_over_due_monotonic_ns=self._already_over_due_ns,
            final_lock_due_monotonic_ns=self._final_lock_due_ns,
            confirmation_started_monotonic_ns=self._confirmation_started_ns,
            confirmation_due_monotonic_ns=self._confirmation_due_ns,
            seconds_to_next_stage=seconds_to_next,
            overdue_seconds=round(
                self._overdue_seconds(now_ns) if now_ns is not None else 0.0, 3
            ),
            confirmation_elapsed_seconds=round(confirmation_elapsed, 3),
            message=self._current_message(),
            popup_required=self._state
            in {
                CosecantState.BREAK_COMPLETE,
                CosecantState.BREAK_ALREADY_OVER,
                CosecantState.FINAL_LOCK,
                CosecantState.RETURN_CONFIRMING,
            },
            popup_must_remain_open=final_locked,
            allowed_actions=allowed_actions,
            final_locked=final_locked,
            return_confirmed=self._state is CosecantState.CONFIRMED,
            context_delivery=self._context_delivery,
            last_action=self._last_action,
            fact_sequence=self._fact_sequence,
        )

    def _next_deadline(self) -> int | None:
        if self._state is CosecantState.BREAK_ACTIVE:
            return self._break_ends_ns
        if self._state is CosecantState.BREAK_COMPLETE:
            return self._already_over_due_ns
        if self._state is CosecantState.BREAK_ALREADY_OVER:
            return self._final_lock_due_ns
        if self._state is CosecantState.RETURN_CONFIRMING:
            return self._confirmation_due_ns
        return None

    def _current_message(self) -> CosecantMessage:
        if self._state is CosecantState.BREAK_COMPLETE:
            return CosecantMessage.BREAK_COMPLETE
        if self._state is CosecantState.BREAK_ALREADY_OVER:
            return CosecantMessage.BREAK_ALREADY_OVER
        if self._state is CosecantState.FINAL_LOCK:
            return CosecantMessage.COME_BACK_PLEASE
        if self._state is CosecantState.RETURN_CONFIRMING:
            return CosecantMessage.RETURN_CONFIRMING
        if self._state is CosecantState.CONFIRMED:
            return CosecantMessage.RETURN_CONFIRMED
        return CosecantMessage.NONE

    def _clear_confirmation(self) -> None:
        self._confirmation_started_ns = None
        self._confirmation_due_ns = None
        self._last_presence_ns = None
        self._confirmation_origin = None

    def _clear_episode(self) -> None:
        self._break_id = ""
        self._study_block_id = ""
        self._study_generation = 0
        self._study_context_token = ""
        self._intended_return_target = None
        self._subject = ""
        self._task = ""
        self._selected_break_seconds = 0
        self._break_started_ns = None
        self._break_ends_ns = None
        self._already_over_due_ns = None
        self._final_lock_due_ns = None
        self._clear_confirmation()
        self._terminal_overdue_seconds = None

    def _accept(
        self,
        message: str,
        facts: tuple[CosecantFact, ...],
    ) -> CosecantResult:
        return CosecantResult(True, message, self._snapshot, facts)

    def _reject(self, message: str) -> CosecantResult:
        return CosecantResult(False, message, self._snapshot, ())


def _seconds_to_ns(seconds: float) -> int:
    return int(round(float(seconds) * NANOSECONDS_PER_SECOND))


def _wall_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


__all__ = [
    "COSECANT_SCHEMA_VERSION",
    "ContextDelivery",
    "CosecantFact",
    "CosecantFactKind",
    "CosecantMessage",
    "CosecantPolicy",
    "CosecantResult",
    "CosecantReturnTarget",
    "CosecantRuntime",
    "CosecantSnapshot",
    "CosecantState",
    "CosecantUiAction",
    "StudyPresence",
    "StudyReturnObservation",
]
