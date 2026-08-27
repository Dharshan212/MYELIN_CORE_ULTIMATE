"""Isolated Normal SINE break authority.

This module owns only the sanctioned interval selected after a Normal SINE-1
``REQUEST_BREAK`` response.  It deliberately has no knowledge of SINE stages,
MIRL, Trigger, Blacklist, Qt, Study Mode, or COSECANT.  Those integrations are
outside Phase 1.

The authority's clock is monotonic nanoseconds.  A duration request is a
pending user choice; only ``start_break`` creates factual break time.  Terminal
transitions return the runtime to ``IDLE`` after emitting immutable facts, so
constructing a new authority always starts clean and never resurrects a prior
break.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final


NORMAL_BREAK_SCHEMA_VERSION: Final = "myelin-normal-break-v1"
NANOSECONDS_PER_SECOND: Final = 1_000_000_000
SECONDS_PER_MINUTE: Final = 60
MINIMUM_BREAK_MINUTES: Final = 5
MAXIMUM_BREAK_MINUTES: Final = 30


class NormalBreakState(str, Enum):
    """The complete runtime state vocabulary of the isolated mini organ."""

    IDLE = "IDLE"
    AWAITING_DURATION = "AWAITING_DURATION"
    ACTIVE = "ACTIVE"


class NormalBreakFactKind(str, Enum):
    """Immutable authority transitions available to persistence/integration."""

    DURATION_REQUESTED = "NORMAL_BREAK_DURATION_REQUESTED"
    CANCELLED = "NORMAL_BREAK_CANCELLED"
    STARTED = "NORMAL_BREAK_STARTED"
    STOP_REQUESTED = "NORMAL_BREAK_STOP_REQUESTED"
    STOPPED = "NORMAL_BREAK_STOPPED"
    COMPLETED = "NORMAL_BREAK_COMPLETED"
    TERMINATED = "NORMAL_BREAK_TERMINATED"
    START_ROLLED_BACK = "NORMAL_BREAK_START_ROLLED_BACK"


class NormalBreakTerminationReason(str, Enum):
    """Authorized non-resuming runtime exits."""

    EMERGENCY = "emergency"
    SHUTDOWN = "shutdown"
    SESSION_END = "session_end"


@dataclass(frozen=True, slots=True)
class NormalBreakFact:
    """One exact, identity-bound Normal Break lifecycle fact."""

    event_id: str
    sequence: int
    kind: NormalBreakFactKind
    session_id: int | None
    break_id: str
    generation: int
    episode_uid: str
    candidate_uid: str
    source_sine_popup_request_id: str
    from_state: NormalBreakState
    to_state: NormalBreakState
    occurred_monotonic_ns: int
    occurred_wall_time_utc: str
    requested_monotonic_ns: int
    started_monotonic_ns: int | None
    deadline_monotonic_ns: int | None
    selected_minutes: int | None
    reason: str = ""
    schema_version: str = NORMAL_BREAK_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class NormalBreakSnapshot:
    """Immutable state view; it never advances the authority clock."""

    state: NormalBreakState
    generation: int
    session_id: int | None
    break_id: str
    episode_uid: str
    candidate_uid: str
    source_sine_popup_request_id: str
    selected_minutes: int | None
    requested_monotonic_ns: int | None
    started_monotonic_ns: int | None
    deadline_monotonic_ns: int | None
    fact_sequence: int
    schema_version: str = NORMAL_BREAK_SCHEMA_VERSION

    @property
    def active(self) -> bool:
        return self.state is NormalBreakState.ACTIVE

    @property
    def awaiting_duration(self) -> bool:
        return self.state is NormalBreakState.AWAITING_DURATION


@dataclass(frozen=True, slots=True)
class NormalBreakResult:
    """Explicit acceptance and facts returned by one authority operation."""

    accepted: bool
    message: str
    snapshot: NormalBreakSnapshot
    facts: tuple[NormalBreakFact, ...] = ()


class NormalBreakAuthority:
    """Thread-safe owner of one pending or active Normal SINE break.

    ``generation`` advances when a duration-selection branch is admitted.  The
    branch receives its opaque ``break_id`` at that boundary, allowing CANCEL,
    START and later actions to reject stale UI generations before factual break
    time exists.  ``STARTED`` then materializes that same exact identity.
    """

    def __init__(
        self,
        *,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        wall_clock_utc: Callable[[], datetime] | None = None,
        break_id_factory: Callable[[], str] | None = None,
    ) -> None:
        if not callable(monotonic_ns):
            raise TypeError("monotonic_ns must be callable")
        if wall_clock_utc is not None and not callable(wall_clock_utc):
            raise TypeError("wall_clock_utc must be callable")
        if break_id_factory is not None and not callable(break_id_factory):
            raise TypeError("break_id_factory must be callable")

        self._monotonic_ns = monotonic_ns
        self._wall_clock_utc = wall_clock_utc or (
            lambda: datetime.now(timezone.utc)
        )
        self._break_id_factory = break_id_factory or (
            lambda: f"normal-break-{secrets.token_hex(16)}"
        )
        self._lock = threading.RLock()

        self._state = NormalBreakState.IDLE
        self._generation = 0
        self._fact_sequence = 0
        self._used_break_ids: set[str] = set()
        self._pending_facts: list[NormalBreakFact] = []

        self._session_id: int | None = None
        self._break_id = ""
        self._episode_uid = ""
        self._candidate_uid = ""
        self._source_request_id = ""
        self._selected_minutes: int | None = None
        self._requested_ns: int | None = None
        self._started_ns: int | None = None
        self._deadline_ns: int | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            return self._state is NormalBreakState.ACTIVE

    def request_duration(
        self,
        *,
        episode_uid: str,
        candidate_uid: str,
        source_sine_popup_request_id: str,
        requested_monotonic_ns: int | None = None,
        session_id: int | None = None,
    ) -> NormalBreakResult:
        """Open one exact duration-selection branch; no break starts here."""

        episode = self._identity(episode_uid, name="episode_uid")
        candidate = self._identity(candidate_uid, name="candidate_uid")
        source_request = self._identity(
            source_sine_popup_request_id,
            name="source_sine_popup_request_id",
        )
        normalized_session = self._session(session_id)
        with self._lock:
            if self._state is not NormalBreakState.IDLE:
                return self._rejected("Normal Break is not idle")

            requested_ns = self._timestamp(
                requested_monotonic_ns,
                name="requested_monotonic_ns",
            )
            self._generation += 1
            self._session_id = normalized_session
            self._break_id = self._new_break_id()
            self._episode_uid = episode
            self._candidate_uid = candidate
            self._source_request_id = source_request
            self._requested_ns = requested_ns
            self._selected_minutes = None
            self._started_ns = None
            self._deadline_ns = None

            prior = self._state
            self._state = NormalBreakState.AWAITING_DURATION
            fact = self._emit(
                kind=NormalBreakFactKind.DURATION_REQUESTED,
                from_state=prior,
                to_state=self._state,
                occurred_ns=requested_ns,
            )
            return self._accepted("Duration selection requested", (fact,))

    def cancel_duration(
        self,
        *,
        break_id: str,
        generation: int,
        episode_uid: str,
        candidate_uid: str,
        source_sine_popup_request_id: str,
        occurred_monotonic_ns: int | None = None,
    ) -> NormalBreakResult:
        """Cancel a pending branch; factual break time never begins."""

        with self._lock:
            mismatch = self._match(
                required_state=NormalBreakState.AWAITING_DURATION,
                break_id=break_id,
                generation=generation,
                episode_uid=episode_uid,
                candidate_uid=candidate_uid,
                source_sine_popup_request_id=source_sine_popup_request_id,
            )
            if mismatch:
                return self._rejected(mismatch)
            occurred_ns = self._transition_timestamp(
                occurred_monotonic_ns,
                name="occurred_monotonic_ns",
            )
            prior = self._state
            fact = self._emit(
                kind=NormalBreakFactKind.CANCELLED,
                from_state=prior,
                to_state=NormalBreakState.IDLE,
                occurred_ns=occurred_ns,
                reason="cancelled_before_start",
            )
            self._clear_runtime_identity()
            return self._accepted("Duration selection cancelled", (fact,))

    def start_break(
        self,
        *,
        break_id: str,
        generation: int,
        episode_uid: str,
        candidate_uid: str,
        source_sine_popup_request_id: str,
        selected_minutes: object,
        started_monotonic_ns: int | None = None,
    ) -> NormalBreakResult:
        """Start factual break time after strict identity and duration checks."""

        with self._lock:
            mismatch = self._match(
                required_state=NormalBreakState.AWAITING_DURATION,
                break_id=break_id,
                generation=generation,
                episode_uid=episode_uid,
                candidate_uid=candidate_uid,
                source_sine_popup_request_id=source_sine_popup_request_id,
            )
            if mismatch:
                return self._rejected(mismatch)
            try:
                duration = self._duration(selected_minutes)
            except ValueError as exc:
                return self._rejected(str(exc))
            started_ns = self._transition_timestamp(
                started_monotonic_ns,
                name="started_monotonic_ns",
            )
            deadline_ns = (
                started_ns
                + duration * SECONDS_PER_MINUTE * NANOSECONDS_PER_SECOND
            )

            prior = self._state
            self._state = NormalBreakState.ACTIVE
            self._selected_minutes = duration
            self._started_ns = started_ns
            self._deadline_ns = deadline_ns
            fact = self._emit(
                kind=NormalBreakFactKind.STARTED,
                from_state=prior,
                to_state=self._state,
                occurred_ns=started_ns,
            )
            return self._accepted("Normal Break started", (fact,))

    def advance(self, *, now_monotonic_ns: int) -> NormalBreakResult:
        """Complete an active break once, exactly at its stored deadline."""

        now_ns = self._explicit_timestamp(now_monotonic_ns, name="now_monotonic_ns")
        with self._lock:
            if self._state is not NormalBreakState.ACTIVE:
                return self._rejected("No active Normal Break")
            assert self._deadline_ns is not None
            if now_ns < self._deadline_ns:
                return self._accepted("Normal Break remains active")

            prior = self._state
            fact = self._emit(
                kind=NormalBreakFactKind.COMPLETED,
                from_state=prior,
                to_state=NormalBreakState.IDLE,
                occurred_ns=self._deadline_ns,
                reason="deadline_reached",
            )
            self._clear_runtime_identity()
            return self._accepted("Normal Break completed", (fact,))

    def stop_break(
        self,
        *,
        break_id: str,
        generation: int,
        episode_uid: str,
        candidate_uid: str,
        occurred_monotonic_ns: int | None = None,
    ) -> NormalBreakResult:
        """End the exact active break early; integration later resumes SINE 2."""

        with self._lock:
            mismatch = self._match(
                required_state=NormalBreakState.ACTIVE,
                break_id=break_id,
                generation=generation,
                episode_uid=episode_uid,
                candidate_uid=candidate_uid,
                source_sine_popup_request_id=self._source_request_id,
            )
            if mismatch:
                return self._rejected(mismatch)
            occurred_ns = self._transition_timestamp(
                occurred_monotonic_ns,
                name="occurred_monotonic_ns",
            )
            prior = self._state
            requested = self._emit(
                kind=NormalBreakFactKind.STOP_REQUESTED,
                from_state=prior,
                to_state=prior,
                occurred_ns=occurred_ns,
                reason="user_requested_early_stop",
            )
            stopped = self._emit(
                kind=NormalBreakFactKind.STOPPED,
                from_state=prior,
                to_state=NormalBreakState.IDLE,
                occurred_ns=occurred_ns,
                reason="user_stopped_break",
            )
            self._clear_runtime_identity()
            return self._accepted("Normal Break stopped", (requested, stopped))

    def terminate(
        self,
        *,
        reason: NormalBreakTerminationReason,
        occurred_monotonic_ns: int | None = None,
    ) -> NormalBreakResult:
        """End pending/active authority without any future resume instruction."""

        if not isinstance(reason, NormalBreakTerminationReason):
            raise TypeError("reason must be a NormalBreakTerminationReason")
        with self._lock:
            if self._state is NormalBreakState.IDLE:
                return self._rejected("No pending or active Normal Break")
            occurred_ns = self._transition_timestamp(
                occurred_monotonic_ns,
                name="occurred_monotonic_ns",
            )
            prior = self._state
            fact = self._emit(
                kind=NormalBreakFactKind.TERMINATED,
                from_state=prior,
                to_state=NormalBreakState.IDLE,
                occurred_ns=occurred_ns,
                reason=reason.value,
            )
            self._clear_runtime_identity()
            return self._accepted("Normal Break terminated", (fact,))

    def rollback_start(
        self,
        *,
        break_id: str,
        generation: int,
        episode_uid: str,
        candidate_uid: str,
        reason: str,
        occurred_monotonic_ns: int | None = None,
    ) -> NormalBreakResult:
        """Invalidate a factual start if a later ownership handoff refuses it."""

        normalized_reason = self._identity(reason, name="reason")
        with self._lock:
            mismatch = self._match(
                required_state=NormalBreakState.ACTIVE,
                break_id=break_id,
                generation=generation,
                episode_uid=episode_uid,
                candidate_uid=candidate_uid,
                source_sine_popup_request_id=self._source_request_id,
            )
            if mismatch:
                return self._rejected(mismatch)
            occurred_ns = self._transition_timestamp(
                occurred_monotonic_ns,
                name="occurred_monotonic_ns",
            )
            prior = self._state
            fact = self._emit(
                kind=NormalBreakFactKind.START_ROLLED_BACK,
                from_state=prior,
                to_state=NormalBreakState.IDLE,
                occurred_ns=occurred_ns,
                reason=normalized_reason,
            )
            self._clear_runtime_identity()
            return self._accepted("Normal Break start rolled back", (fact,))

    def snapshot(self) -> NormalBreakSnapshot:
        with self._lock:
            return NormalBreakSnapshot(
                state=self._state,
                generation=self._generation,
                session_id=self._session_id,
                break_id=self._break_id,
                episode_uid=self._episode_uid,
                candidate_uid=self._candidate_uid,
                source_sine_popup_request_id=self._source_request_id,
                selected_minutes=self._selected_minutes,
                requested_monotonic_ns=self._requested_ns,
                started_monotonic_ns=self._started_ns,
                deadline_monotonic_ns=self._deadline_ns,
                fact_sequence=self._fact_sequence,
            )

    def drain_facts(self) -> tuple[NormalBreakFact, ...]:
        """Return every undrained fact once, in authority sequence order."""

        with self._lock:
            facts = tuple(self._pending_facts)
            self._pending_facts.clear()
            return facts

    def _accepted(
        self,
        message: str,
        facts: tuple[NormalBreakFact, ...] = (),
    ) -> NormalBreakResult:
        return NormalBreakResult(True, message, self.snapshot(), facts)

    def _rejected(self, message: str) -> NormalBreakResult:
        return NormalBreakResult(False, message, self.snapshot())

    def _emit(
        self,
        *,
        kind: NormalBreakFactKind,
        from_state: NormalBreakState,
        to_state: NormalBreakState,
        occurred_ns: int,
        reason: str = "",
    ) -> NormalBreakFact:
        self._fact_sequence += 1
        fact = NormalBreakFact(
            event_id=f"{self._break_id}:{self._fact_sequence}",
            sequence=self._fact_sequence,
            kind=kind,
            session_id=self._session_id,
            break_id=self._break_id,
            generation=self._generation,
            episode_uid=self._episode_uid,
            candidate_uid=self._candidate_uid,
            source_sine_popup_request_id=self._source_request_id,
            from_state=from_state,
            to_state=to_state,
            occurred_monotonic_ns=occurred_ns,
            occurred_wall_time_utc=self._wall_time_text(),
            requested_monotonic_ns=int(self._requested_ns or 0),
            started_monotonic_ns=self._started_ns,
            deadline_monotonic_ns=self._deadline_ns,
            selected_minutes=self._selected_minutes,
            reason=reason,
        )
        self._pending_facts.append(fact)
        return fact

    def _match(
        self,
        *,
        required_state: NormalBreakState,
        break_id: str,
        generation: int,
        episode_uid: str,
        candidate_uid: str,
        source_sine_popup_request_id: str,
    ) -> str:
        if self._state is not required_state:
            return f"Normal Break is not {required_state.value}"
        if type(generation) is not int or generation <= 0:
            return "generation must be a positive integer"
        identity_values = (
            break_id,
            episode_uid,
            candidate_uid,
            source_sine_popup_request_id,
        )
        if any(type(value) is not str for value in identity_values):
            return "Normal Break identities must be exact strings"
        supplied = (
            break_id,
            generation,
            episode_uid,
            candidate_uid,
            source_sine_popup_request_id,
        )
        expected = (
            self._break_id,
            self._generation,
            self._episode_uid,
            self._candidate_uid,
            self._source_request_id,
        )
        if supplied != expected:
            return "Normal Break identity is stale or mismatched"
        return ""

    def _duration(self, selected_minutes: object) -> int:
        if type(selected_minutes) is not int:
            raise ValueError("selected_minutes must be a whole integer")
        if selected_minutes < MINIMUM_BREAK_MINUTES:
            raise ValueError(
                f"selected_minutes must be at least {MINIMUM_BREAK_MINUTES}"
            )
        if selected_minutes > MAXIMUM_BREAK_MINUTES:
            raise ValueError(
                f"selected_minutes must not exceed {MAXIMUM_BREAK_MINUTES}"
            )
        return selected_minutes

    def _transition_timestamp(self, value: int | None, *, name: str) -> int:
        timestamp = self._timestamp(value, name=name)
        floor = self._started_ns if self._started_ns is not None else self._requested_ns
        if floor is not None and timestamp < floor:
            raise ValueError(f"{name} cannot predate the current Normal Break state")
        return timestamp

    def _timestamp(self, value: int | None, *, name: str) -> int:
        if value is None:
            value = self._monotonic_ns()
        return self._explicit_timestamp(value, name=name)

    @staticmethod
    def _explicit_timestamp(value: object, *, name: str) -> int:
        if type(value) is not int:
            raise TypeError(f"{name} must be an integer")
        if value < 0:
            raise ValueError(f"{name} cannot be negative")
        return value

    @staticmethod
    def _identity(value: object, *, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _session(value: object) -> int | None:
        if value is None:
            return None
        if type(value) is not int or value <= 0:
            raise ValueError("session_id must be a positive integer or None")
        return value

    def _new_break_id(self) -> str:
        for _ in range(8):
            candidate = self._identity(self._break_id_factory(), name="break_id")
            if candidate not in self._used_break_ids:
                self._used_break_ids.add(candidate)
                return candidate
        raise RuntimeError("break_id_factory did not produce a unique identity")

    def _wall_time_text(self) -> str:
        value = self._wall_clock_utc()
        if not isinstance(value, datetime):
            raise TypeError("wall_clock_utc must return datetime")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )

    def _clear_runtime_identity(self) -> None:
        self._state = NormalBreakState.IDLE
        self._session_id = None
        self._break_id = ""
        self._episode_uid = ""
        self._candidate_uid = ""
        self._source_request_id = ""
        self._selected_minutes = None
        self._requested_ns = None
        self._started_ns = None
        self._deadline_ns = None


__all__ = [
    "MAXIMUM_BREAK_MINUTES",
    "MINIMUM_BREAK_MINUTES",
    "NANOSECONDS_PER_SECOND",
    "NORMAL_BREAK_SCHEMA_VERSION",
    "NormalBreakAuthority",
    "NormalBreakFact",
    "NormalBreakFactKind",
    "NormalBreakResult",
    "NormalBreakSnapshot",
    "NormalBreakState",
    "NormalBreakTerminationReason",
]
