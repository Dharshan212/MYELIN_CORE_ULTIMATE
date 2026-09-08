"""Independent, headless MINE scientific/runtime authority.

Phase 1 deliberately has no Monitor, Browser, sibling-organ, persistence, Qt,
or Control Station wiring.  The runtime consumes certified synthetic facts and
emits immutable effects for a presentation adapter.  All behavioural timing
is owned here and uses either explicitly supported observation intervals or an
effective monotonic clock that freezes under Global Pause.
"""
from __future__ import annotations

import json
import math
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Final, Protocol


MINE_SCHEMA_VERSION: Final = "myelin-mine-v1-isolated"
INITIAL_GATE_SECONDS: Final = 600.0
RETURN_INTENT_SECONDS: Final = 795.0
IMPORTANT_MINUTES_MIN: Final = 5
IMPORTANT_MINUTES_MAX: Final = 30
FINAL_CALLBACK_HIDE_SECONDS: Final = 3.0
RETURN_VERIFICATION_SECONDS: Final = 10.0
CLOSURE_CONFIRMATION_SECONDS: Final = 60.0
_NS: Final = 1_000_000_000


class MinePhase(str, Enum):
    IDLE = "IDLE"
    OBSERVING_MESSAGING = "OBSERVING_MESSAGING"
    MINE1_PENDING = "MINE1_PENDING"
    MINE1_ACTIVE = "MINE1_ACTIVE"
    RETURN_INTENT_ACTIVE = "RETURN_INTENT_ACTIVE"
    IMPORTANT_DURATION_ENTRY = "IMPORTANT_DURATION_ENTRY"
    IMPORTANT_COMMIT_PENDING = "IMPORTANT_COMMIT_PENDING"
    IMPORTANT_ALLOWANCE_ACTIVE = "IMPORTANT_ALLOWANCE_ACTIVE"
    MINE2A_PENDING = "MINE2A_PENDING"
    MINE2A_ACTIVE = "MINE2A_ACTIVE"
    MINE2B_PENDING = "MINE2B_PENDING"
    MINE2B_ACTIVE = "MINE2B_ACTIVE"
    RETURN_VISUAL_CONFIRMING = "RETURN_VISUAL_CONFIRMING"
    RETURN_VERIFYING = "RETURN_VERIFYING"
    CLOSURE_CONFIRMING = "CLOSURE_CONFIRMING"
    STUDY_PREEMPTION_PENDING = "STUDY_PREEMPTION_PENDING"
    CLOSED = "CLOSED"
    SHUTDOWN = "SHUTDOWN"


class MineObservationKind(str, Enum):
    MESSAGING = "MESSAGING"
    FOCUS = "FOCUS"
    NEUTRAL = "NEUTRAL"


class MineChoice(str, Enum):
    I_WILL_COME_BACK = "I_WILL_COME_BACK"
    ITS_IMPORTANT = "ITS_IMPORTANT"


class MineCommandKind(str, Enum):
    MINE1_DISPLAYED = "MINE1_DISPLAYED"
    MINE1_ACTION = "MINE1_ACTION"
    IMPORTANT_DURATION_SUBMITTED = "IMPORTANT_DURATION_SUBMITTED"
    MINE2_DISPLAYED = "MINE2_DISPLAYED"
    POPUP_DELIVERY_FAILED = "POPUP_DELIVERY_FAILED"


class MineEffectKind(str, Enum):
    SHOW_MINE1 = "SHOW_MINE1"
    SHOW_IMPORTANT_DURATION = "SHOW_IMPORTANT_DURATION"
    CLOSE_MINE1 = "CLOSE_MINE1"
    SHOW_MINE2 = "SHOW_MINE2"
    UPDATE_RETURN_CONFIRMING = "UPDATE_RETURN_CONFIRMING"
    HIDE_MINE2 = "HIDE_MINE2"
    RESTORE_MINE2 = "RESTORE_MINE2"
    CLOSE_PRESENTATION = "CLOSE_PRESENTATION"


class MineEventClass(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    USER_ACTION = "USER_ACTION"
    PRESENTATION = "PRESENTATION"


class MineClosureReason(str, Enum):
    VERIFIED_RETURN = "VERIFIED_RETURN"
    STUDY_MODE_ACTIVATED = "STUDY_MODE_ACTIVATED"
    STOPPED = "STOPPED"
    EMERGENCY = "EMERGENCY"


class MineClosureOutcome(str, Enum):
    RETURNED_AFTER_INTENT = "RETURNED_AFTER_INTENT"
    EARLY_RETURN_DURING_IMPORTANT_ALLOWANCE = "EARLY_RETURN_DURING_IMPORTANT_ALLOWANCE"
    RETURNED_AFTER_CALLBACK = "RETURNED_AFTER_CALLBACK"
    STUDY_PREEMPTION = "STUDY_PREEMPTION"
    INCOMPLETE = "INCOMPLETE"
    EMERGENCY = "EMERGENCY"


class _RecoveryOrigin(str, Enum):
    NONE = "NONE"
    RETURN_INTENT = "RETURN_INTENT"
    IMPORTANT_ALLOWANCE = "IMPORTANT_ALLOWANCE"
    FINAL_CALLBACK = "FINAL_CALLBACK"


@dataclass(frozen=True, slots=True)
class MinePolicy:
    initial_gate_seconds: float = INITIAL_GATE_SECONDS
    return_intent_seconds: float = RETURN_INTENT_SECONDS
    important_minimum_minutes: int = IMPORTANT_MINUTES_MIN
    important_maximum_minutes: int = IMPORTANT_MINUTES_MAX
    final_callback_hide_seconds: float = FINAL_CALLBACK_HIDE_SECONDS
    return_verification_seconds: float = RETURN_VERIFICATION_SECONDS
    closure_confirmation_seconds: float = CLOSURE_CONFIRMATION_SECONDS

    def __post_init__(self) -> None:
        expected = (
            INITIAL_GATE_SECONDS,
            RETURN_INTENT_SECONDS,
            IMPORTANT_MINUTES_MIN,
            IMPORTANT_MINUTES_MAX,
            FINAL_CALLBACK_HIDE_SECONDS,
            RETURN_VERIFICATION_SECONDS,
            CLOSURE_CONFIRMATION_SECONDS,
        )
        actual = (
            self.initial_gate_seconds,
            self.return_intent_seconds,
            self.important_minimum_minutes,
            self.important_maximum_minutes,
            self.final_callback_hide_seconds,
            self.return_verification_seconds,
            self.closure_confirmation_seconds,
        )
        if any(
            not math.isfinite(float(value)) or float(value) != float(frozen)
            for value, frozen in zip(actual, expected)
        ):
            raise ValueError("MINE timing ledger is frozen")


@dataclass(frozen=True, slots=True)
class MineObservation:
    kind: MineObservationKind
    observed_monotonic_ns: int
    observation_sequence: int
    supported_interval_ns: int = 0
    platform_key: str = ""
    platform_label: str = ""
    evidence_token: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MineObservationKind):
            raise TypeError("kind must be MineObservationKind")
        if self.observed_monotonic_ns <= 0 or self.observation_sequence <= 0:
            raise ValueError("positive monotonic time and observation sequence required")
        if self.supported_interval_ns < 0:
            raise ValueError("supported interval cannot be negative")
        if self.kind is MineObservationKind.MESSAGING and not (
            self.platform_key or self.platform_label
        ):
            raise ValueError("certified messaging requires a factual resource identity")
        if self.kind is not MineObservationKind.MESSAGING and (
            self.platform_key or self.platform_label
        ):
            raise ValueError("only messaging observations carry messaging identity")


@dataclass(frozen=True, slots=True)
class MineCommand:
    kind: MineCommandKind
    generation: int
    request_id: str
    occurred_monotonic_ns: int
    choice: MineChoice | None = None
    duration_minutes: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, MineCommandKind):
            raise TypeError("kind must be MineCommandKind")
        if self.generation < 0 or not self.request_id:
            raise ValueError("command requires generation and request identity")
        if self.occurred_monotonic_ns <= 0:
            raise ValueError("positive command monotonic time required")


@dataclass(frozen=True, slots=True)
class MineEvent:
    event_id: str
    parent_session_id: int
    mine_episode_id: str
    sequence: int
    event_name: str
    event_class: MineEventClass
    occurred_at_utc: str
    monotonic_ns: int
    generation: int
    platform_key: str
    platform_label: str
    request_id: str
    evidence_token: str
    payload_json: str
    schema_version: str = MINE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MineEffect:
    kind: MineEffectKind
    generation: int
    request_id: str
    presentation_variant: str = ""
    platform_key: str = ""
    platform_label: str = ""
    message: str = ""


@dataclass(frozen=True, slots=True)
class MineSnapshot:
    available: bool
    parent_session_id: int | None
    mine_episode_id: str
    generation: int
    phase: MinePhase
    current_platform_key: str
    current_platform_label: str
    messaging_transition_count: int
    initial_gate_remaining_seconds: float
    selected_branch: str
    return_intent_remaining_seconds: float
    important_chosen_minutes: int | None
    important_start_effective_ns: int
    important_deadline_effective_ns: int
    important_remaining_seconds: float
    mine1_request_id: str
    mine1_requested: bool
    mine1_displayed: bool
    mine1_visible: bool
    mine2_variant: str
    mine2_request_id: str
    mine2_requested: bool
    mine2_displayed: bool
    mine2_visible: bool
    return_visual_confirming: bool
    return_visual_remaining_seconds: float
    return_verification_state: str
    return_verification_remaining_seconds: float
    closure_confirmation_remaining_seconds: float
    global_paused: bool
    study_preempted: bool
    closure_reason: str
    closure_outcome: str
    durable_health: bool
    durable_detail: str
    data_quality: str
    schema_version: str = MINE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class MineMonitorStatus:
    """Narrow Mom-facing status with no sibling or handover policy."""

    factual_episode: bool
    source_eligible: bool
    held: bool
    termination_pending: bool
    episode_key: tuple[int, str] | None
    phase: MinePhase


@dataclass(frozen=True, slots=True)
class MineCommandResult:
    accepted: bool
    close_popup: bool
    message: str
    snapshot: MineSnapshot


class MineEventSink(Protocol):
    def append_mine_events(self, events: tuple[MineEvent, ...]) -> bool: ...


@dataclass(slots=True)
class _Request:
    request_id: str
    requested_ns: int
    displayed_ns: int = 0
    visible: bool = False


class MineRuntime:
    """Thread-safe owner of one independent MINE candidate/episode at a time."""

    def __init__(
        self,
        *,
        event_sink: MineEventSink,
        policy: MinePolicy = MinePolicy(),
        wall_clock_utc: Callable[[], datetime] | None = None,
    ) -> None:
        if event_sink is None:
            raise ValueError("durable event sink required")
        self._sink = event_sink
        self._policy = policy
        self._wall = wall_clock_utc or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._phase = MinePhase.IDLE
        self._generation = 0
        self._parent_session_id: int | None = None
        self._episode_id = ""
        self._event_sequence = 0
        self._effects: list[MineEffect] = []
        self._mine1: _Request | None = None
        self._mine2: _Request | None = None
        self._mine2_variant = ""
        self._branch = ""
        self._current_platform_key = ""
        self._current_platform_label = ""
        self._last_evidence_token = ""
        self._messaging_transitions = 0
        self._initial_ns = 0
        self._return_intent_ns = 0
        self._important_minutes: int | None = None
        self._important_start = 0
        self._important_deadline = 0
        self._recovery_origin = _RecoveryOrigin.NONE
        self._recovery_resume_phase = MinePhase.IDLE
        self._focus_active = False
        self._visual_ns = 0
        self._verify_ns = 0
        self._closure_ns = 0
        self._last_obs_ns = 0
        self._last_obs_seq = 0
        self._last_kind: MineObservationKind | None = None
        self._last_platform_key = ""
        self._paused = False
        self._pause_started = 0
        self._paused_total = 0
        self._pending_pause_events: list[tuple[str, int]] = []
        self._study_preempted = False
        # Phase 2C Mom artery only: no sibling identity, target, or 120-second timer.
        self._monitor_held = False
        self._monitor_hold_started_effective = 0
        self._monitor_restore_request_id = ""
        self._monitor_restore_variant = ""
        self._monitor_restore_was_visible = False
        self._monitor_termination_pending = False
        self._closure_reason = ""
        self._closure_outcome = ""
        self._quality = "NO_EVIDENCE"
        self._durable_health = True
        self._durable_detail = ""

    def bind_parent_session(self, session_id: int) -> bool:
        if isinstance(session_id, bool) or not isinstance(session_id, int) or session_id <= 0:
            raise ValueError("MINE parent session_id must be a positive integer")
        with self._lock:
            if self._parent_session_id is None:
                if self._event_sequence or self._generation:
                    raise RuntimeError("MINE parent session cannot be bound after events begin")
                self._parent_session_id = session_id
                return True
            if self._parent_session_id == session_id:
                return True
            raise RuntimeError("MINE parent session is immutable")

    def snapshot(self, *, now_ns: int | None = None) -> MineSnapshot:
        with self._lock:
            raw = _now_ns(now_ns)
            effective = self._effective(raw)
            initial_active = self._phase is MinePhase.OBSERVING_MESSAGING
            return_active = self._phase is MinePhase.RETURN_INTENT_ACTIVE
            important_active = bool(
                self._important_deadline
                and self._phase not in {MinePhase.CLOSED, MinePhase.SHUTDOWN}
            )
            visual_remaining = (
                max(0.0, self._policy.final_callback_hide_seconds - self._visual_ns / _NS)
                if self._phase is MinePhase.RETURN_VISUAL_CONFIRMING
                else 0.0
            )
            verifying = self._phase is MinePhase.RETURN_VERIFYING
            closing = self._phase is MinePhase.CLOSURE_CONFIRMING
            return MineSnapshot(
                available=self._phase is not MinePhase.SHUTDOWN,
                parent_session_id=self._parent_session_id,
                mine_episode_id=self._episode_id,
                generation=self._generation,
                phase=self._phase,
                current_platform_key=self._current_platform_key,
                current_platform_label=self._current_platform_label,
                messaging_transition_count=self._messaging_transitions,
                initial_gate_remaining_seconds=(
                    max(0.0, self._policy.initial_gate_seconds - self._initial_ns / _NS)
                    if initial_active
                    else 0.0
                ),
                selected_branch=self._branch,
                return_intent_remaining_seconds=(
                    max(0.0, self._policy.return_intent_seconds - self._return_intent_ns / _NS)
                    if return_active
                    else 0.0
                ),
                important_chosen_minutes=self._important_minutes,
                important_start_effective_ns=self._important_start,
                important_deadline_effective_ns=self._important_deadline,
                important_remaining_seconds=(
                    max(0.0, (self._important_deadline - effective) / _NS)
                    if important_active
                    else 0.0
                ),
                mine1_request_id=self._mine1.request_id if self._mine1 else "",
                mine1_requested=self._mine1 is not None,
                mine1_displayed=bool(self._mine1 and self._mine1.displayed_ns),
                mine1_visible=bool(self._mine1 and self._mine1.visible),
                mine2_variant=self._mine2_variant,
                mine2_request_id=self._mine2.request_id if self._mine2 else "",
                mine2_requested=self._mine2 is not None,
                mine2_displayed=bool(self._mine2 and self._mine2.displayed_ns),
                mine2_visible=bool(self._mine2 and self._mine2.visible),
                return_visual_confirming=self._phase is MinePhase.RETURN_VISUAL_CONFIRMING,
                return_visual_remaining_seconds=visual_remaining,
                return_verification_state=(
                    "CLOSURE_CONFIRMING"
                    if closing
                    else "RETURN_VERIFYING"
                    if verifying
                    else "RETURN_VISUAL_CONFIRMING"
                    if self._phase is MinePhase.RETURN_VISUAL_CONFIRMING
                    else "INACTIVE"
                ),
                return_verification_remaining_seconds=(
                    max(0.0, self._policy.return_verification_seconds - self._verify_ns / _NS)
                    if verifying
                    else 0.0
                ),
                closure_confirmation_remaining_seconds=(
                    max(0.0, self._policy.closure_confirmation_seconds - self._closure_ns / _NS)
                    if closing
                    else 0.0
                ),
                global_paused=self._paused,
                study_preempted=self._study_preempted,
                closure_reason=self._closure_reason,
                closure_outcome=self._closure_outcome,
                durable_health=self._durable_health,
                durable_detail=self._durable_detail,
                data_quality="PAUSED" if self._paused else self._quality,
            )

    def observe(self, observation: MineObservation) -> tuple[MineEffect, ...]:
        with self._lock:
            if self._phase is MinePhase.SHUTDOWN:
                return ()
            if self._paused:
                self._break_continuity()
                return ()
            if self._monitor_held:
                return ()
            now = observation.observed_monotonic_ns
            if self._last_obs_ns and now < self._last_obs_ns:
                self._gap(now, "REGRESSED_MONOTONIC_TIME")
                return self.drain_effects()
            started_closed = self._phase is MinePhase.CLOSED
            self._advance_deadlines(now)
            if self._study_preempted and self._phase in {
                MinePhase.IDLE,
                MinePhase.CLOSED,
            }:
                self._remember(observation)
                return self.drain_effects()
            if started_closed:
                if (
                    self._phase is MinePhase.CLOSED
                    and observation.kind is MineObservationKind.MESSAGING
                ):
                    self._observe_messaging(observation, now)
                self._remember(observation)
                return self.drain_effects()
            if self._phase in {
                MinePhase.CLOSED,
                MinePhase.SHUTDOWN,
                MinePhase.STUDY_PREEMPTION_PENDING,
            }:
                self._remember(observation)
                return self.drain_effects()
            elapsed = self._supported_interval(observation)
            if elapsed:
                self._credit(elapsed, observation.kind)
            if observation.kind is MineObservationKind.MESSAGING:
                self._observe_messaging(observation, now)
            elif observation.kind is MineObservationKind.FOCUS:
                self._observe_focus(now)
            else:
                self._observe_neutral(now)
            self._thresholds(now)
            self._remember(observation)
            return self.drain_effects()

    def advance(self, *, now_ns: int | None = None) -> tuple[MineEffect, ...]:
        with self._lock:
            if self._phase is MinePhase.SHUTDOWN or self._paused:
                return ()
            now = _now_ns(now_ns)
            if self._monitor_held:
                if self._monitor_termination_pending:
                    self._attempt_monitor_termination(now)
                return self.drain_effects()
            self._advance_deadlines(now)
            return self.drain_effects()

    def set_global_paused(self, paused: bool, now_ns: int | None = None) -> bool:
        with self._lock:
            now = _now_ns(now_ns)
            requested = bool(paused)
            if requested != self._paused:
                if requested:
                    self._paused = True
                    self._pause_started = now
                else:
                    if self._pause_started and now > self._pause_started:
                        self._paused_total += now - self._pause_started
                    self._paused = False
                    self._pause_started = 0
                self._break_continuity()
                if self._generation and self._phase not in {
                    MinePhase.CLOSED,
                    MinePhase.SHUTDOWN,
                }:
                    self._pending_pause_events.append(
                        ("GLOBAL_PAUSE_ENTERED" if requested else "GLOBAL_PAUSE_EXITED", now)
                    )
            return self._flush_pause_events()

    def submit_command(self, command: MineCommand) -> MineCommandResult:
        with self._lock:
            now = command.occurred_monotonic_ns
            if self._study_preempted:
                # M3.  Study outranks MINE.  Once suppression is latched no
                # specialist command may be accepted, even while the durable
                # preemption transition is still unresolved -- otherwise an
                # old popup button could act inside Study ownership.
                return self._reject("Study owns this moment", now)
            if command.generation != self._generation:
                return self._reject("MINE generation changed", now)
            if self._monitor_held:
                return self._reject("Monitor temporarily owns this episode", now)
            if command.kind is MineCommandKind.MINE1_DISPLAYED:
                return self._display_mine1(command)
            if command.kind is MineCommandKind.MINE1_ACTION:
                return self._mine1_action(command)
            if command.kind is MineCommandKind.IMPORTANT_DURATION_SUBMITTED:
                return self._submit_important_duration(command)
            if command.kind is MineCommandKind.MINE2_DISPLAYED:
                return self._display_mine2(command)
            if command.kind is MineCommandKind.POPUP_DELIVERY_FAILED:
                return self._popup_delivery_failed(command)
            return self._reject("Unsupported MINE command", now)

    def monitor_status(self, *, now_ns: int | None = None) -> MineMonitorStatus:
        del now_ns
        with self._lock:
            factual = bool(
                self._episode_id
                and self._phase not in {MinePhase.IDLE, MinePhase.CLOSED, MinePhase.SHUTDOWN}
            )
            recovery_phases = {
                MinePhase.RETURN_VISUAL_CONFIRMING,
                MinePhase.RETURN_VERIFYING,
                MinePhase.CLOSURE_CONFIRMING,
            }
            eligible = bool(
                factual
                and self._phase not in recovery_phases
                and self._phase is not MinePhase.STUDY_PREEMPTION_PENDING
                and not self._study_preempted
                and not self._monitor_termination_pending
            )
            key = (self._generation, self._episode_id) if factual else None
            return MineMonitorStatus(
                factual, eligible, self._monitor_held, self._monitor_termination_pending, key, self._phase
            )

    def monitor_hold(self, *, episode_key: object, now_ns: int) -> bool:
        with self._lock:
            status = self.monitor_status(now_ns=now_ns)
            if not status.source_eligible or status.episode_key != episode_key:
                return False
            if self._monitor_held:
                return True
            now = _now_ns(now_ns)
            self._monitor_held = True
            self._monitor_hold_started_effective = self._effective(now)
            request, variant = self._monitor_current_presentation()
            self._monitor_restore_request_id = request.request_id if request else ""
            self._monitor_restore_variant = variant
            self._monitor_restore_was_visible = bool(request and request.visible)
            if request is not None:
                request.visible = False
                self._effects.append(
                    MineEffect(
                        MineEffectKind.CLOSE_PRESENTATION,
                        self._generation,
                        request.request_id,
                        presentation_variant=variant,
                        message="Monitor temporarily withdrew this presentation",
                    )
                )
            self._break_continuity()
            return True

    def monitor_resume(self, *, episode_key: object, now_ns: int) -> bool:
        with self._lock:
            status = self.monitor_status(now_ns=now_ns)
            if (
                not self._monitor_held
                or self._monitor_termination_pending
                or status.episode_key != episode_key
            ):
                return False
            now = _now_ns(now_ns)
            held_effective = max(0, self._effective(now) - self._monitor_hold_started_effective)
            if self._important_start:
                self._important_start += held_effective
            if self._important_deadline:
                self._important_deadline += held_effective
            request, variant = self._monitor_current_presentation()
            if request is not None and request.request_id == self._monitor_restore_request_id:
                effect = self._monitor_restore_effect(request, variant)
                if effect is not None:
                    request.visible = self._monitor_restore_was_visible
                    self._effects.append(effect)
            self._clear_monitor_control()
            self._break_continuity()
            return True

    def monitor_terminate(self, *, episode_key: object, now_ns: int) -> bool:
        with self._lock:
            status = self.monitor_status(now_ns=now_ns)
            if not self._monitor_held or status.episode_key != episode_key:
                return False
            self._monitor_termination_pending = True
            self._attempt_monitor_termination(_now_ns(now_ns))
            return self._phase is MinePhase.CLOSED

    def _attempt_monitor_termination(self, now: int) -> None:
        if not self._monitor_termination_pending:
            return
        self.close(MineClosureReason.STOPPED, now_ns=now)
        if self._phase is MinePhase.CLOSED:
            self._clear_monitor_control()

    def _monitor_current_presentation(self) -> tuple[_Request | None, str]:
        if self._phase in {MinePhase.MINE1_PENDING, MinePhase.MINE1_ACTIVE}:
            return self._mine1, "MINE1"
        if self._phase in {MinePhase.IMPORTANT_DURATION_ENTRY, MinePhase.IMPORTANT_COMMIT_PENDING}:
            return self._mine1, "MINE1_IMPORTANT_DURATION"
        if self._phase in {
            MinePhase.MINE2A_PENDING, MinePhase.MINE2A_ACTIVE,
            MinePhase.MINE2B_PENDING, MinePhase.MINE2B_ACTIVE,
        }:
            return self._mine2, self._mine2_variant
        return None, ""

    def _monitor_restore_effect(self, request: _Request, variant: str) -> MineEffect | None:
        if variant == "MINE1":
            return MineEffect(
                MineEffectKind.SHOW_MINE1, self._generation, request.request_id,
                presentation_variant="MINE1", platform_key=self._current_platform_key,
                platform_label=self._current_platform_label,
                message="Return to your important work if this messaging is not important.",
            )
        if variant == "MINE1_IMPORTANT_DURATION":
            return MineEffect(
                MineEffectKind.SHOW_IMPORTANT_DURATION, self._generation, request.request_id,
                presentation_variant=variant, platform_key=self._current_platform_key,
                platform_label=self._current_platform_label,
                message="Choose a whole number of minutes from 5 through 30",
            )
        if variant in {"MINE2A", "MINE2B"}:
            return self._show_mine2_effect()
        return None

    def _clear_monitor_control(self) -> None:
        self._monitor_held = False
        self._monitor_hold_started_effective = 0
        self._monitor_restore_request_id = ""
        self._monitor_restore_variant = ""
        self._monitor_restore_was_visible = False
        self._monitor_termination_pending = False

    def preempt_for_study(self, *, now_ns: int | None = None) -> tuple[MineEffect, ...]:
        """Immediately end current MINE authority when Dad/Study owns the moment.

        Study is stronger than MINE and is not a sibling.  The Study latch and
        presentation withdrawal therefore happen before durable bookkeeping.
        A formal MINE episode is closed in the same call with the canonical
        STUDY_MODE_ACTIVATED reason; if persistence rejects that close, the
        episode remains non-actionable and the same close is retried without
        starting the old delayed Study-preemption timer.
        """
        with self._lock:
            now = _now_ns(now_ns)
            if self._phase in {MinePhase.IDLE, MinePhase.CLOSED, MinePhase.SHUTDOWN}:
                return ()

            if self._phase is MinePhase.STUDY_PREEMPTION_PENDING:
                self.close(MineClosureReason.STUDY_MODE_ACTIVATED, now_ns=now)
                if self._phase is MinePhase.CLOSED:
                    self._quality = "STUDY_PREEMPTED"
                return self.drain_effects()

            # Study authority is withdrawn immediately; durability may retry.
            if not self._study_preempted:
                self._study_preempted = True
                self._close_presentations()
                self._important_deadline = 0
                self._clear_recovery()
                self._break_continuity()

            if not self._commit(
                "STUDY_PREEMPTED_MINE",
                MineEventClass.OBSERVED,
                now,
                payload={"formal_episode": bool(self._episode_id)},
            ):
                return self.drain_effects()

            if not self._episode_id:
                self._phase = MinePhase.IDLE
                self._quality = "STUDY_SUPPRESSED_CANDIDATE"
                return self.drain_effects()

            self._phase = MinePhase.STUDY_PREEMPTION_PENDING
            self._quality = "STUDY_PREEMPTION_PENDING_DURABILITY"
            self.close(MineClosureReason.STUDY_MODE_ACTIVATED, now_ns=now)
            if self._phase is MinePhase.CLOSED:
                self._quality = "STUDY_PREEMPTED"
            return self.drain_effects()

    def release_study_preemption(self, *, now_ns: int | None = None) -> bool:
        """Release Study's latch for future admission without reopening old MINE state.

        The lifecycle owner may call this only after Study ownership has ended.  A
        formal episode must finish its Study-preemption closure first; a discarded
        pre-MINE candidate is already safely IDLE.  The release is durable before
        eligibility changes and never starts a candidate itself.
        """

        with self._lock:
            if self._phase is MinePhase.SHUTDOWN:
                return False
            if not self._study_preempted:
                return True
            if self._phase not in {MinePhase.IDLE, MinePhase.CLOSED}:
                return False
            now = _now_ns(now_ns)
            if not self._commit_many(
                (
                    (
                        "STUDY_PREEMPTION_RELEASED",
                        MineEventClass.OBSERVED,
                        {"future_mine_eligibility_only": True},
                    ),
                ),
                now,
                episode_id="",
            ):
                return False
            self._study_preempted = False
            self._quality = "STUDY_PREEMPTION_RELEASED"
            self._break_continuity()
            return True

    def close(
        self, reason: MineClosureReason, *, now_ns: int | None = None
    ) -> tuple[MineEffect, ...]:
        if not isinstance(reason, MineClosureReason):
            raise TypeError("reason must be MineClosureReason")
        with self._lock:
            if self._phase in {MinePhase.IDLE, MinePhase.CLOSED, MinePhase.SHUTDOWN}:
                return ()
            now = _now_ns(now_ns)
            outcome = {
                MineClosureReason.STUDY_MODE_ACTIVATED: MineClosureOutcome.STUDY_PREEMPTION,
                MineClosureReason.EMERGENCY: MineClosureOutcome.EMERGENCY,
            }.get(reason, MineClosureOutcome.INCOMPLETE)
            terminal_name = (
                "EMERGENCY_STOPPED"
                if reason is MineClosureReason.EMERGENCY
                else "MINE_RUNTIME_STOPPED"
            )
            specs: list[tuple[str, MineEventClass, Mapping[str, object]]] = [
                (
                    terminal_name,
                    MineEventClass.OBSERVED,
                    {"closure_reason": reason.value, "closure_outcome": outcome.value},
                )
            ]
            if self._episode_id:
                specs.append(
                    (
                        "MINE_SESSION_CLOSED",
                        MineEventClass.DERIVED,
                        {"closure_reason": reason.value, "closure_outcome": outcome.value},
                    )
                )
            if not self._commit_many(tuple(specs), now):
                return self.drain_effects()
            self._closure_reason = reason.value
            self._closure_outcome = outcome.value
            self._phase = MinePhase.CLOSED
            self._close_presentations()
            self._clear_recovery()
            self._clear_monitor_control()
            self._break_continuity()
            return self.drain_effects()

    def shutdown(self, *, now_ns: int | None = None) -> bool:
        with self._lock:
            if self._phase is MinePhase.SHUTDOWN:
                return True
            now = _now_ns(now_ns)
            if self._phase not in {MinePhase.IDLE, MinePhase.CLOSED}:
                self.close(MineClosureReason.STOPPED, now_ns=now)
                if self._phase is not MinePhase.CLOSED:
                    return False
            self._phase = MinePhase.SHUTDOWN
            self._closure_outcome = self._closure_outcome or MineClosureOutcome.INCOMPLETE.value
            return True

    def drain_effects(self) -> tuple[MineEffect, ...]:
        effects = tuple(self._effects)
        self._effects.clear()
        return effects

    # ------------------------------------------------------------------ input

    def _observe_messaging(self, observation: MineObservation, now: int) -> None:
        if self._phase in {MinePhase.IDLE, MinePhase.CLOSED}:
            self._start_candidate(observation, now)
            return
        if observation.platform_key != self._current_platform_key:
            if not self._commit(
                "MESSAGING_PLATFORM_TRANSITION",
                MineEventClass.OBSERVED,
                now,
                platform_key=observation.platform_key,
                platform_label=observation.platform_label,
                evidence_token=observation.evidence_token,
                payload={
                    "from_platform": self._current_platform_key,
                    "to_platform": observation.platform_key,
                },
            ):
                return
            self._messaging_transitions += 1
        self._current_platform_key = observation.platform_key
        self._current_platform_label = observation.platform_label
        self._last_evidence_token = observation.evidence_token
        if self._phase in {
            MinePhase.RETURN_VISUAL_CONFIRMING,
            MinePhase.RETURN_VERIFYING,
            MinePhase.CLOSURE_CONFIRMING,
        }:
            self._relapse(now)

    def _observe_focus(self, now: int) -> None:
        if self._phase is MinePhase.OBSERVING_MESSAGING:
            if self._commit(
                "MINE_CANDIDATE_ENDED_BEFORE_INTERVENTION",
                MineEventClass.OBSERVED,
                now,
                payload={"outcome": "FOCUS_BEFORE_MINE1"},
            ):
                self._reset_to_idle()
            return
        if self._phase is MinePhase.RETURN_INTENT_ACTIVE:
            self._start_early_recovery(_RecoveryOrigin.RETURN_INTENT, now)
        elif self._phase is MinePhase.IMPORTANT_ALLOWANCE_ACTIVE:
            self._start_early_recovery(_RecoveryOrigin.IMPORTANT_ALLOWANCE, now)
        elif self._phase in {MinePhase.MINE2A_ACTIVE, MinePhase.MINE2B_ACTIVE}:
            self._start_final_visual(now)
        elif self._phase in {
            MinePhase.RETURN_VISUAL_CONFIRMING,
            MinePhase.RETURN_VERIFYING,
            MinePhase.CLOSURE_CONFIRMING,
        }:
            self._focus_active = True

    def _observe_neutral(self, now: int) -> None:
        if self._phase is MinePhase.OBSERVING_MESSAGING:
            if self._commit(
                "MINE_CANDIDATE_RESET",
                MineEventClass.OBSERVED,
                now,
                payload={"outcome": "NEUTRAL_RESET_BEFORE_MINE1"},
            ):
                self._reset_to_idle()
        elif self._phase is MinePhase.RETURN_VISUAL_CONFIRMING:
            self._interrupt_visual(now, "FOCUS_NOT_CONTINUOUS")
        elif self._phase in {MinePhase.RETURN_VERIFYING, MinePhase.CLOSURE_CONFIRMING}:
            self._interrupt_focus_without_relapse(now)

    def _supported_interval(self, observation: MineObservation) -> int:
        if not self._last_obs_ns:
            return 0
        if (
            observation.observation_sequence != self._last_obs_seq + 1
            or self._last_obs_seq <= 0
        ):
            self._gap(observation.observed_monotonic_ns, "NON_ADJACENT_OBSERVATION_SEQUENCE")
            return 0
        if observation.kind is not self._last_kind:
            return 0
        if observation.kind not in {
            MineObservationKind.MESSAGING,
            MineObservationKind.FOCUS,
        }:
            return 0
        raw_delta = max(0, observation.observed_monotonic_ns - self._last_obs_ns)
        if observation.supported_interval_ns <= 0:
            if raw_delta:
                self._gap(observation.observed_monotonic_ns, "UNSUPPORTED_OBSERVATION_INTERVAL")
            return 0
        return min(raw_delta, observation.supported_interval_ns)

    def _credit(self, elapsed: int, kind: MineObservationKind) -> None:
        if kind is MineObservationKind.MESSAGING:
            if self._phase is MinePhase.OBSERVING_MESSAGING:
                self._initial_ns += elapsed
            elif self._phase is MinePhase.RETURN_INTENT_ACTIVE:
                self._return_intent_ns += elapsed
        elif kind is MineObservationKind.FOCUS and self._focus_active:
            if self._phase is MinePhase.RETURN_VISUAL_CONFIRMING:
                self._visual_ns += elapsed
            elif self._phase is MinePhase.RETURN_VERIFYING:
                self._verify_ns += elapsed
            elif self._phase is MinePhase.CLOSURE_CONFIRMING:
                self._closure_ns += elapsed

    def _remember(self, observation: MineObservation) -> None:
        self._last_obs_ns = observation.observed_monotonic_ns
        self._last_obs_seq = observation.observation_sequence
        self._last_kind = observation.kind
        self._last_platform_key = observation.platform_key
        self._quality = "OBSERVED"

    # -------------------------------------------------------------- thresholds

    def _thresholds(self, now: int) -> None:
        if (
            self._phase is MinePhase.OBSERVING_MESSAGING
            and self._initial_ns >= _to_ns(self._policy.initial_gate_seconds)
        ):
            self._request_mine1(now)
        elif (
            self._phase is MinePhase.RETURN_INTENT_ACTIVE
            and self._return_intent_ns >= _to_ns(self._policy.return_intent_seconds)
        ):
            self._request_mine2("MINE2A", now)
        if (
            self._phase is MinePhase.RETURN_VISUAL_CONFIRMING
            and self._visual_ns >= _to_ns(self._policy.final_callback_hide_seconds)
        ):
            self._hide_final_and_verify(now)
        elif (
            self._phase is MinePhase.RETURN_VERIFYING
            and self._focus_active
            and self._verify_ns >= _to_ns(self._policy.return_verification_seconds)
        ):
            self._verification_complete(now)
        elif (
            self._phase is MinePhase.CLOSURE_CONFIRMING
            and self._focus_active
            and self._closure_ns >= _to_ns(self._policy.closure_confirmation_seconds)
        ):
            self._confirm_return(now)

    def _advance_deadlines(self, now: int) -> None:
        if self._paused:
            return
        effective = self._effective(now)
        if self._phase is MinePhase.STUDY_PREEMPTION_PENDING:
            self.close(MineClosureReason.STUDY_MODE_ACTIVATED, now_ns=now)
            if self._phase is MinePhase.CLOSED:
                self._quality = "STUDY_PREEMPTED"
            return
        if (
            self._phase is MinePhase.IMPORTANT_ALLOWANCE_ACTIVE
            and self._important_deadline
            and effective >= self._important_deadline
        ):
            self._request_mine2("MINE2B", now)

    # --------------------------------------------------------------- commands

    def _display_mine1(self, command: MineCommand) -> MineCommandResult:
        request = self._mine1
        if not request or command.request_id != request.request_id:
            return self._reject("MINE-1 request is no longer current", command.occurred_monotonic_ns)
        if request.displayed_ns:
            return MineCommandResult(
                True,
                False,
                "MINE-1 already displayed",
                self.snapshot(now_ns=command.occurred_monotonic_ns),
            )
        if self._phase is not MinePhase.MINE1_PENDING:
            return self._reject("MINE-1 is not awaiting display", command.occurred_monotonic_ns)
        episode_id = secrets.token_hex(16)
        specs = (
            ("MINE1_DISPLAYED", MineEventClass.PRESENTATION, {"request_id": request.request_id}),
            ("MINE_EPISODE_STARTED", MineEventClass.DERIVED, {"request_id": request.request_id}),
        )
        if not self._commit_many(
            specs,
            command.occurred_monotonic_ns,
            request_id=request.request_id,
            episode_id=episode_id,
        ):
            return self._reject(
                "MINE-1 display acknowledgement was not durably accepted",
                command.occurred_monotonic_ns,
            )
        self._episode_id = episode_id
        request.displayed_ns = command.occurred_monotonic_ns
        request.visible = True
        self._phase = MinePhase.MINE1_ACTIVE
        return MineCommandResult(
            True,
            False,
            "MINE-1 display accepted; formal episode started",
            self.snapshot(now_ns=command.occurred_monotonic_ns),
        )

    def _mine1_action(self, command: MineCommand) -> MineCommandResult:
        request = self._mine1
        if (
            self._phase is not MinePhase.MINE1_ACTIVE
            or not request
            or not request.displayed_ns
            or command.request_id != request.request_id
        ):
            return self._reject("Displayed MINE-1 is not current", command.occurred_monotonic_ns)
        if command.choice is MineChoice.I_WILL_COME_BACK:
            if not self._commit_many(
                (
                    ("RETURN_INTENT_RECORDED", MineEventClass.USER_ACTION, {"choice": command.choice.value}),
                    ("RETURN_INTENT_WINDOW_STARTED", MineEventClass.DERIVED, {}),
                ),
                command.occurred_monotonic_ns,
                request_id=request.request_id,
            ):
                return self._reject("Return intent was not durably accepted", command.occurred_monotonic_ns)
            self._branch = command.choice.value
            self._return_intent_ns = 0
            self._phase = MinePhase.RETURN_INTENT_ACTIVE
            request.visible = False
            self._effects.append(
                MineEffect(MineEffectKind.CLOSE_MINE1, self._generation, request.request_id)
            )
            self._break_continuity()
            return MineCommandResult(
                True,
                True,
                "I WILL COME BACK accepted; new 13:15 clock started",
                self.snapshot(now_ns=command.occurred_monotonic_ns),
            )
        if command.choice is MineChoice.ITS_IMPORTANT:
            if not self._commit_many(
                (
                    ("IMPORTANT_INTENT_RECORDED", MineEventClass.USER_ACTION, {"choice": command.choice.value}),
                    ("IMPORTANT_DURATION_REQUESTED", MineEventClass.DERIVED, {"request_id": request.request_id}),
                ),
                command.occurred_monotonic_ns,
                request_id=request.request_id,
            ):
                return self._reject("Important intent was not durably accepted", command.occurred_monotonic_ns)
            self._branch = command.choice.value
            self._phase = MinePhase.IMPORTANT_DURATION_ENTRY
            self._effects.append(
                MineEffect(
                    MineEffectKind.SHOW_IMPORTANT_DURATION,
                    self._generation,
                    request.request_id,
                    presentation_variant="MINE1_IMPORTANT_DURATION",
                    platform_key=self._current_platform_key,
                    platform_label=self._current_platform_label,
                    message="Choose a whole number of minutes from 5 through 30",
                )
            )
            return MineCommandResult(
                True,
                False,
                "IT'S IMPORTANT accepted; duration required",
                self.snapshot(now_ns=command.occurred_monotonic_ns),
            )
        return self._reject("MINE-1 action is invalid", command.occurred_monotonic_ns)

    def _submit_important_duration(self, command: MineCommand) -> MineCommandResult:
        request = self._mine1
        minutes = command.duration_minutes
        if (
            self._phase is not MinePhase.IMPORTANT_DURATION_ENTRY
            or not request
            or command.request_id != request.request_id
        ):
            return self._reject("Important duration request is no longer current", command.occurred_monotonic_ns)
        if (
            isinstance(minutes, bool)
            or not isinstance(minutes, int)
            or not self._policy.important_minimum_minutes
            <= minutes
            <= self._policy.important_maximum_minutes
        ):
            return self._reject(
                "Important duration must be an integer from 5 through 30",
                command.occurred_monotonic_ns,
            )
        start = self._effective(command.occurred_monotonic_ns)
        deadline = start + _to_ns(minutes * 60)
        self._phase = MinePhase.IMPORTANT_COMMIT_PENDING
        if not self._commit_many(
            (
                ("IMPORTANT_DURATION_COMMITTED", MineEventClass.USER_ACTION, {"duration_minutes": minutes}),
                (
                    "IMPORTANT_ALLOWANCE_STARTED",
                    MineEventClass.DERIVED,
                    {
                        "duration_minutes": minutes,
                        "start_effective_ns": start,
                        "deadline_effective_ns": deadline,
                    },
                ),
            ),
            command.occurred_monotonic_ns,
            request_id=request.request_id,
        ):
            self._phase = MinePhase.IMPORTANT_DURATION_ENTRY
            return self._reject("Important duration was not durably accepted", command.occurred_monotonic_ns)
        self._important_minutes = minutes
        self._important_start = start
        self._important_deadline = deadline
        self._phase = MinePhase.IMPORTANT_ALLOWANCE_ACTIVE
        request.visible = False
        self._effects.append(
            MineEffect(MineEffectKind.CLOSE_MINE1, self._generation, request.request_id)
        )
        self._break_continuity()
        return MineCommandResult(
            True,
            True,
            "Important allowance committed",
            self.snapshot(now_ns=command.occurred_monotonic_ns),
        )

    def _display_mine2(self, command: MineCommand) -> MineCommandResult:
        request = self._mine2
        pending = {MinePhase.MINE2A_PENDING, MinePhase.MINE2B_PENDING}
        active = {MinePhase.MINE2A_ACTIVE, MinePhase.MINE2B_ACTIVE}
        if not request or command.request_id != request.request_id:
            return self._reject("MINE-2 request is no longer current", command.occurred_monotonic_ns)
        if request.displayed_ns and self._phase in active:
            return MineCommandResult(
                True,
                False,
                "MINE-2 already displayed",
                self.snapshot(now_ns=command.occurred_monotonic_ns),
            )
        if self._phase not in pending:
            return self._reject("MINE-2 is not awaiting display", command.occurred_monotonic_ns)
        event = f"{self._mine2_variant}_DISPLAYED"
        if not self._commit(
            event,
            MineEventClass.PRESENTATION,
            command.occurred_monotonic_ns,
            request_id=request.request_id,
        ):
            return self._reject("MINE-2 display was not durably accepted", command.occurred_monotonic_ns)
        request.displayed_ns = command.occurred_monotonic_ns
        request.visible = True
        self._phase = (
            MinePhase.MINE2A_ACTIVE
            if self._mine2_variant == "MINE2A"
            else MinePhase.MINE2B_ACTIVE
        )
        return MineCommandResult(
            True,
            False,
            "MINE-2 display accepted",
            self.snapshot(now_ns=command.occurred_monotonic_ns),
        )

    def _popup_delivery_failed(self, command: MineCommand) -> MineCommandResult:
        current_ids = {
            request.request_id for request in (self._mine1, self._mine2) if request is not None
        }
        if command.request_id not in current_ids:
            return self._reject("Popup failure request is stale", command.occurred_monotonic_ns)
        accepted = self._commit(
            "POPUP_DELIVERY_FAILED",
            MineEventClass.PRESENTATION,
            command.occurred_monotonic_ns,
            request_id=command.request_id,
        )
        return MineCommandResult(
            accepted,
            False,
            "Popup delivery failure recorded" if accepted else "Popup failure was not durable",
            self.snapshot(now_ns=command.occurred_monotonic_ns),
        )

    # --------------------------------------------------------------- requests

    def _start_candidate(self, observation: MineObservation, now: int) -> None:
        if self._parent_session_id is None:
            self._durable_health = False
            self._durable_detail = "MINE parent session is not durably bound"
            return
        generation = self._generation + 1
        event = self._event(
            "MINE_CANDIDATE_STARTED",
            MineEventClass.OBSERVED,
            now,
            platform_key=observation.platform_key,
            platform_label=observation.platform_label,
            evidence_token=observation.evidence_token,
            generation=generation,
            sequence=1,
            episode_id="",
        )
        entered = self._event(
            "MESSAGING_PLATFORM_ENTERED",
            MineEventClass.OBSERVED,
            now,
            platform_key=observation.platform_key,
            platform_label=observation.platform_label,
            evidence_token=observation.evidence_token,
            generation=generation,
            sequence=2,
            episode_id="",
        )
        if not self._write((event, entered)):
            return
        self._reset_episode_state()
        self._generation = generation
        self._event_sequence = 2
        self._phase = MinePhase.OBSERVING_MESSAGING
        self._current_platform_key = observation.platform_key
        self._current_platform_label = observation.platform_label
        self._last_evidence_token = observation.evidence_token
        self._quality = "OBSERVED"

    def _request_mine1(self, now: int) -> None:
        if self._mine1 is not None:
            return
        request_id = self._request_id("mine1")
        if not self._commit_many(
            (
                ("MINE_INITIAL_GATE_ELIGIBLE", MineEventClass.DERIVED, {}),
                ("MINE1_REQUESTED", MineEventClass.DERIVED, {"request_id": request_id}),
            ),
            now,
            request_id=request_id,
        ):
            return
        self._mine1 = _Request(request_id, now)
        self._phase = MinePhase.MINE1_PENDING
        self._effects.append(
            MineEffect(
                MineEffectKind.SHOW_MINE1,
                self._generation,
                request_id,
                presentation_variant="MINE1",
                platform_key=self._current_platform_key,
                platform_label=self._current_platform_label,
                message="Return to your important work if this messaging is not important.",
            )
        )

    def _request_mine2(self, variant: str, now: int) -> None:
        if self._mine2 is not None:
            return
        request_id = self._request_id(variant.casefold())
        deadline_event = (
            "NORMAL_FINAL_DEADLINE_REACHED"
            if variant == "MINE2A"
            else "IMPORTANT_ALLOWANCE_DEADLINE_REACHED"
        )
        if not self._commit_many(
            (
                (deadline_event, MineEventClass.DERIVED, {}),
                (f"{variant}_REQUESTED", MineEventClass.DERIVED, {"request_id": request_id}),
            ),
            now,
            request_id=request_id,
        ):
            return
        self._mine2_variant = variant
        self._mine2 = _Request(request_id, now)
        pending = MinePhase.MINE2A_PENDING if variant == "MINE2A" else MinePhase.MINE2B_PENDING
        self._phase = pending
        self._effects.append(self._show_mine2_effect())

    def _show_mine2_effect(self) -> MineEffect:
        assert self._mine2 is not None
        message = (
            "You intended to return. Your important work is waiting."
            if self._mine2_variant == "MINE2A"
            else "Your chosen messaging time is over. It is time to return."
        )
        return MineEffect(
            MineEffectKind.SHOW_MINE2,
            self._generation,
            self._mine2.request_id,
            presentation_variant=self._mine2_variant,
            platform_key=self._current_platform_key,
            platform_label=self._current_platform_label,
            message=message,
        )

    # --------------------------------------------------------------- recovery

    def _start_early_recovery(self, origin: _RecoveryOrigin, now: int) -> None:
        if not self._commit(
            "RETURN_VERIFICATION_STARTED",
            MineEventClass.OBSERVED,
            now,
            payload={"branch": origin.value, "visual_stage": False},
        ):
            return
        self._recovery_origin = origin
        self._recovery_resume_phase = self._phase
        self._focus_active = True
        self._verify_ns = 0
        self._closure_ns = 0
        self._phase = MinePhase.RETURN_VERIFYING
        self._break_continuity()

    def _start_final_visual(self, now: int) -> None:
        request = self._mine2
        if not request or not request.displayed_ns or not request.visible:
            return
        if not self._commit(
            "RETURN_VISUAL_CONFIRMING_STARTED",
            MineEventClass.OBSERVED,
            now,
            request_id=request.request_id,
            payload={"variant": self._mine2_variant},
        ):
            return
        self._recovery_origin = _RecoveryOrigin.FINAL_CALLBACK
        self._recovery_resume_phase = self._phase
        self._focus_active = True
        self._visual_ns = 0
        self._verify_ns = 0
        self._closure_ns = 0
        self._phase = MinePhase.RETURN_VISUAL_CONFIRMING
        self._effects.append(
            MineEffect(
                MineEffectKind.UPDATE_RETURN_CONFIRMING,
                self._generation,
                request.request_id,
                presentation_variant=self._mine2_variant,
                message="RETURN CONFIRMING",
            )
        )
        self._break_continuity()

    def _hide_final_and_verify(self, now: int) -> None:
        request = self._mine2
        if not request or not request.visible:
            return
        if not self._commit_many(
            (
                ("FINAL_CALLBACK_HIDDEN_FOR_FOCUS", MineEventClass.DERIVED, {"request_id": request.request_id}),
                ("RETURN_VERIFICATION_STARTED", MineEventClass.DERIVED, {"branch": self._mine2_variant, "visual_stage": True}),
            ),
            now,
            request_id=request.request_id,
        ):
            return
        request.visible = False
        self._phase = MinePhase.RETURN_VERIFYING
        self._focus_active = True
        self._verify_ns = 0
        self._visual_ns = 0
        self._effects.append(
            MineEffect(
                MineEffectKind.HIDE_MINE2,
                self._generation,
                request.request_id,
                presentation_variant=self._mine2_variant,
                message="Hide the same callback; recovery continues",
            )
        )

    def _verification_complete(self, now: int) -> None:
        if not self._commit_many(
            (
                ("RETURN_VERIFICATION_COMPLETED", MineEventClass.DERIVED, {"branch": self._recovery_origin.value}),
                ("CLOSURE_CONFIRMATION_STARTED", MineEventClass.DERIVED, {"branch": self._recovery_origin.value}),
            ),
            now,
            request_id=self._mine2.request_id if self._mine2 else "",
        ):
            return
        self._phase = MinePhase.CLOSURE_CONFIRMING
        self._closure_ns = 0

    def _confirm_return(self, now: int) -> None:
        outcome = {
            _RecoveryOrigin.RETURN_INTENT: MineClosureOutcome.RETURNED_AFTER_INTENT,
            _RecoveryOrigin.IMPORTANT_ALLOWANCE: MineClosureOutcome.EARLY_RETURN_DURING_IMPORTANT_ALLOWANCE,
            _RecoveryOrigin.FINAL_CALLBACK: MineClosureOutcome.RETURNED_AFTER_CALLBACK,
        }.get(self._recovery_origin)
        if outcome is None:
            return
        if not self._flush_pause_events():
            return
        if not self._commit_many(
            (
                ("CLOSURE_CONFIRMATION_COMPLETED", MineEventClass.DERIVED, {"closure_outcome": outcome.value}),
                ("RETURN_CONFIRMED", MineEventClass.DERIVED, {"closure_outcome": outcome.value}),
                (
                    "MINE_SESSION_CLOSED",
                    MineEventClass.DERIVED,
                    {
                        "closure_reason": MineClosureReason.VERIFIED_RETURN.value,
                        "closure_outcome": outcome.value,
                    },
                ),
            ),
            now,
            request_id=self._mine2.request_id if self._mine2 else "",
        ):
            return
        self._closure_reason = MineClosureReason.VERIFIED_RETURN.value
        self._closure_outcome = outcome.value
        self._phase = MinePhase.CLOSED
        self._important_deadline = 0
        self._close_presentations()
        self._clear_recovery()
        self._clear_monitor_control()
        self._break_continuity()

    def _relapse(self, now: int) -> None:
        previous_phase = self._phase
        event = (
            "CLOSURE_CONFIRMATION_INTERRUPTED"
            if previous_phase is MinePhase.CLOSURE_CONFIRMING
            else "RETURN_VERIFICATION_INTERRUPTED"
        )
        if self._recovery_origin is _RecoveryOrigin.FINAL_CALLBACK:
            request = self._mine2
            if request is None:
                return
            hidden = not request.visible
            specs: list[tuple[str, MineEventClass, Mapping[str, object]]] = [
                (event, MineEventClass.OBSERVED, {"reason": "MESSAGING_RELAPSE"})
            ]
            if hidden:
                specs.append(
                    (
                        "FINAL_CALLBACK_RESTORED_AFTER_RELAPSE",
                        MineEventClass.DERIVED,
                        {"request_id": request.request_id},
                    )
                )
            if not self._commit_many(tuple(specs), now, request_id=request.request_id):
                return
            self._phase = (
                MinePhase.MINE2A_ACTIVE
                if self._mine2_variant == "MINE2A"
                else MinePhase.MINE2B_ACTIVE
            )
            if hidden:
                request.visible = True
                self._effects.append(
                    MineEffect(
                        MineEffectKind.RESTORE_MINE2,
                        self._generation,
                        request.request_id,
                        presentation_variant=self._mine2_variant,
                        message="Restore same logical MINE-2 after relapse",
                    )
                )
            self._clear_recovery()
            return
        origin = self._recovery_origin
        if origin is _RecoveryOrigin.NONE:
            return
        if not self._commit(
            event,
            MineEventClass.OBSERVED,
            now,
            payload={"reason": "MESSAGING_RELAPSE", "branch": origin.value},
        ):
            return
        self._phase = self._recovery_resume_phase
        self._clear_recovery()
        self._advance_deadlines(now)

    def _interrupt_visual(self, now: int, reason: str) -> None:
        if not self._commit(
            "RETURN_VERIFICATION_INTERRUPTED",
            MineEventClass.OBSERVED,
            now,
            request_id=self._mine2.request_id if self._mine2 else "",
            payload={"reason": reason, "stage": "VISUAL"},
        ):
            return
        self._phase = self._recovery_resume_phase
        self._clear_recovery()

    def _interrupt_focus_without_relapse(self, now: int) -> None:
        event = (
            "CLOSURE_CONFIRMATION_INTERRUPTED"
            if self._phase is MinePhase.CLOSURE_CONFIRMING
            else "RETURN_VERIFICATION_INTERRUPTED"
        )
        if not self._commit(
            event,
            MineEventClass.OBSERVED,
            now,
            request_id=self._mine2.request_id if self._mine2 else "",
            payload={"reason": "FOCUS_NOT_CONFIRMED"},
        ):
            return
        self._focus_active = False
        self._verify_ns = 0
        self._closure_ns = 0
        self._phase = MinePhase.RETURN_VERIFYING

    # -------------------------------------------------------------- persistence

    def _commit_many(
        self,
        specs: tuple[tuple[str, MineEventClass, Mapping[str, object]], ...],
        now: int,
        *,
        request_id: str = "",
        episode_id: str | None = None,
    ) -> bool:
        events = tuple(
            self._event(
                name,
                event_class,
                now,
                request_id=request_id,
                payload=payload,
                sequence=self._event_sequence + index + 1,
                episode_id=episode_id,
            )
            for index, (name, event_class, payload) in enumerate(specs)
        )
        if not self._write(events):
            return False
        self._event_sequence += len(events)
        return True

    def _commit(
        self,
        name: str,
        event_class: MineEventClass,
        now: int,
        *,
        platform_key: str = "",
        platform_label: str = "",
        request_id: str = "",
        evidence_token: str = "",
        payload: Mapping[str, object] | None = None,
    ) -> bool:
        event = self._event(
            name,
            event_class,
            now,
            platform_key=platform_key,
            platform_label=platform_label,
            request_id=request_id,
            evidence_token=evidence_token,
            payload=payload,
            sequence=self._event_sequence + 1,
        )
        if not self._write((event,)):
            return False
        self._event_sequence += 1
        return True

    def _event(
        self,
        name: str,
        event_class: MineEventClass,
        now: int,
        *,
        platform_key: str = "",
        platform_label: str = "",
        request_id: str = "",
        evidence_token: str = "",
        payload: Mapping[str, object] | None = None,
        generation: int | None = None,
        sequence: int | None = None,
        episode_id: str | None = None,
    ) -> MineEvent:
        if self._parent_session_id is None:
            raise RuntimeError("MINE parent session is not durably bound")
        wall = self._wall()
        if wall.tzinfo is None or wall.utcoffset() is None:
            raise RuntimeError("MINE wall clock must be timezone-aware")
        return MineEvent(
            event_id=secrets.token_hex(16),
            parent_session_id=self._parent_session_id,
            mine_episode_id=self._episode_id if episode_id is None else episode_id,
            sequence=self._event_sequence + 1 if sequence is None else sequence,
            event_name=name,
            event_class=event_class,
            occurred_at_utc=wall.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            monotonic_ns=now,
            generation=self._generation if generation is None else generation,
            platform_key=platform_key,
            platform_label=_bounded(platform_label),
            request_id=request_id,
            evidence_token=evidence_token,
            payload_json=json.dumps(
                dict(payload or {}),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )

    def _write(self, events: tuple[MineEvent, ...]) -> bool:
        try:
            accepted = bool(self._sink.append_mine_events(events))
            detail = "durable event sink rejected transition"
        except Exception as exc:  # noqa: BLE001 - sink boundary must fail closed
            accepted = False
            detail = str(exc)
        self._durable_health = accepted
        self._durable_detail = "" if accepted else " ".join(detail.split())[:240]
        return accepted

    def _flush_pause_events(self) -> bool:
        while self._pending_pause_events:
            name, occurred = self._pending_pause_events[0]
            if not self._commit(name, MineEventClass.OBSERVED, occurred):
                return False
            self._pending_pause_events.pop(0)
        return True

    # ---------------------------------------------------------------- helpers

    def _gap(self, now: int, reason: str) -> None:
        self._quality = "EVIDENCE_GAP"
        if self._generation and self._phase not in {MinePhase.CLOSED, MinePhase.SHUTDOWN}:
            self._commit(
                "EVIDENCE_GAP",
                MineEventClass.OBSERVED,
                now,
                payload={"reason": reason},
            )

    def _effective(self, raw: int) -> int:
        current_pause = (
            raw - self._pause_started
            if self._paused and self._pause_started and raw > self._pause_started
            else 0
        )
        return raw - self._paused_total - current_pause

    def _hide_request(self, request: _Request, variant: str) -> None:
        request.visible = False
        self._effects.append(
            MineEffect(
                MineEffectKind.CLOSE_PRESENTATION,
                self._generation,
                request.request_id,
                presentation_variant=variant,
            )
        )

    def _close_presentations(self) -> None:
        if self._mine1:
            self._hide_request(self._mine1, "MINE1")
        if self._mine2:
            self._hide_request(self._mine2, self._mine2_variant)

    def _clear_recovery(self) -> None:
        self._recovery_origin = _RecoveryOrigin.NONE
        self._recovery_resume_phase = MinePhase.IDLE
        self._focus_active = False
        self._visual_ns = 0
        self._verify_ns = 0
        self._closure_ns = 0

    def _break_continuity(self) -> None:
        self._last_obs_ns = 0
        self._last_obs_seq = 0
        self._last_kind = None
        self._last_platform_key = ""

    def _reset_to_idle(self) -> None:
        self._phase = MinePhase.IDLE
        self._episode_id = ""
        self._mine1 = None
        self._mine2 = None
        self._mine2_variant = ""
        self._branch = ""
        self._current_platform_key = ""
        self._current_platform_label = ""
        self._initial_ns = 0
        self._return_intent_ns = 0
        self._important_minutes = None
        self._important_start = 0
        self._important_deadline = 0
        self._clear_recovery()
        self._break_continuity()

    def _reset_episode_state(self) -> None:
        self._episode_id = ""
        self._event_sequence = 0
        self._effects.clear()
        self._mine1 = None
        self._mine2 = None
        self._mine2_variant = ""
        self._branch = ""
        self._current_platform_key = ""
        self._current_platform_label = ""
        self._last_evidence_token = ""
        self._messaging_transitions = 0
        self._initial_ns = 0
        self._return_intent_ns = 0
        self._important_minutes = None
        self._important_start = 0
        self._important_deadline = 0
        self._study_preempted = False
        self._clear_monitor_control()
        self._closure_reason = ""
        self._closure_outcome = ""
        self._quality = "NO_EVIDENCE"
        self._clear_recovery()
        self._break_continuity()

    def _request_id(self, purpose: str) -> str:
        return f"mine-{purpose}-{self._generation}-{secrets.token_hex(6)}"

    def _reject(self, message: str, now: int) -> MineCommandResult:
        return MineCommandResult(False, False, message, self.snapshot(now_ns=now))


def _now_ns(value: int | None) -> int:
    current = time.monotonic_ns() if value is None else int(value)
    if current <= 0:
        raise ValueError("positive monotonic time required")
    return current


def _to_ns(seconds: float) -> int:
    return int(float(seconds) * _NS)


def _bounded(value: object) -> str:
    return " ".join(str(value or "").split())[:300]


__all__ = [
    "CLOSURE_CONFIRMATION_SECONDS",
    "FINAL_CALLBACK_HIDE_SECONDS",
    "IMPORTANT_MINUTES_MAX",
    "IMPORTANT_MINUTES_MIN",
    "INITIAL_GATE_SECONDS",
    "MINE_SCHEMA_VERSION",
    "RETURN_INTENT_SECONDS",
    "RETURN_VERIFICATION_SECONDS",
    "MineChoice",
    "MineClosureOutcome",
    "MineClosureReason",
    "MineCommand",
    "MineCommandKind",
    "MineCommandResult",
    "MineEffect",
    "MineEffectKind",
    "MineEvent",
    "MineEventClass",
    "MineEventSink",
    "MineObservation",
    "MineObservationKind",
    "MinePhase",
    "MinePolicy",
    "MineRuntime",
    "MineSnapshot",
]
