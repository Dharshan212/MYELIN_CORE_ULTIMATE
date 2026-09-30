"""Read-only live timeline projection for Science Lab Chapter 3.

This module is deliberately presentation-only.  It accepts immutable views
and facts already published by the Control Station, normalises their factual
stage/timing fields, and never imports or calls a MYELIN runtime authority.
Unknown-duration stages remain indeterminate instead of acquiring a UI-owned
percentage.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Final


MODE_IDLE: Final = "IDLE"
MODE_LIVE: Final = "LIVE"
MODE_FINALIZING: Final = "FINALIZING"
MODE_EXPERIMENT_ENDED: Final = "EXPERIMENT_ENDED"
MODE_INTERRUPTED: Final = "INTERRUPTED"

STATUS_PENDING: Final = "PENDING"
STATUS_ACTIVE: Final = "ACTIVE"
STATUS_PAUSED: Final = "PAUSED"
STATUS_COMPLETE: Final = "COMPLETE"

STAGES: Final = (
    "OFF_TASK_DWELL",
    "TRIGGER",
    "RETURN",
    "VERIFIED_RETURN",
    "EPISODE_CLOSURE",
)
ORGANS: Final = ("SINE", "MINE", "COSINE", "SECANT", "COSECANT")


@dataclass(frozen=True, slots=True)
class LiveStageProgress:
    stage: str
    status: str
    progress: float | None
    elapsed_seconds: float | None
    total_seconds: float | None
    reason: str


@dataclass(frozen=True, slots=True)
class LiveOrganTimelineState:
    parent_session_id: int
    experiment_id: str
    organ: str | None
    mode: str
    stage: str
    stages: tuple[LiveStageProgress, ...]
    episode_identity: str | None
    updated_monotonic_ns: int
    break_progress: LiveStageProgress | None = None


def _value(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip().upper()


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _progress(elapsed: object, total: object) -> tuple[float | None, float | None, float | None]:
    elapsed_value = _number(elapsed)
    total_value = _number(total)
    if elapsed_value is None or total_value is None or total_value <= 0.0:
        return None, elapsed_value, total_value
    elapsed_value = max(0.0, elapsed_value)
    return min(1.0, elapsed_value / total_value), elapsed_value, total_value


def _stages(
    values: Mapping[str, tuple[str, float | None, float | None, float | None, str]]
) -> tuple[LiveStageProgress, ...]:
    rows: list[LiveStageProgress] = []
    for stage in STAGES:
        status, progress, elapsed, total, reason = values.get(
            stage, (STATUS_PENDING, None, None, None, "Awaiting factual stage evidence.")
        )
        rows.append(LiveStageProgress(stage, status, progress, elapsed, total, reason))
    return tuple(rows)


def _pending() -> dict[str, tuple[str, float | None, float | None, float | None, str]]:
    return {
        stage: (STATUS_PENDING, None, None, None, "Awaiting factual stage evidence.")
        for stage in STAGES
    }


def _complete(values: dict, *stage_names: str, reason: str) -> None:
    for stage in stage_names:
        values[stage] = (STATUS_COMPLETE, 1.0, None, None, reason)


def _active(
    values: dict,
    stage: str,
    *,
    progress: float | None = None,
    elapsed: float | None = None,
    total: float | None = None,
    paused: bool = False,
    reason: str,
) -> None:
    values[stage] = (
        STATUS_PAUSED if paused else STATUS_ACTIVE,
        progress,
        elapsed,
        total,
        reason,
    )


class LiveOrganTimelineProjector:
    """Normalise existing runtime publications into view-only live state."""

    def __init__(self, *, monotonic_ns: Callable[[], int] = time.monotonic_ns) -> None:
        self._monotonic_ns = monotonic_ns
        self._mode = MODE_IDLE
        self._parent_session_id = 0
        self._experiment_id = ""
        self._states: dict[str, LiveOrganTimelineState] = {}
        self._control: Mapping[str, object] = {}
        self._cosecant: object | None = None
        self._sine_events: dict[str, set[str]] = {}
        self._mirl_events: dict[str, set[str]] = {}
        self._mirl_last_event: dict[str, str] = {}
        self._cosecant_events: dict[str, set[str]] = {}
        self._last_sine_fact_episode = ""
        self._last_mirl_fact_episode = ""
        self._last_cosecant_fact_break = ""
        self._cosecant_fact_state = ""

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def parent_session_id(self) -> int:
        return self._parent_session_id

    @property
    def experiment_id(self) -> str:
        return self._experiment_id

    def begin_experiment(self, parent_session_id: int, experiment_id: str) -> LiveOrganTimelineState:
        identity = (int(parent_session_id), str(experiment_id))
        if self._mode != MODE_LIVE or identity != (
            self._parent_session_id,
            self._experiment_id,
        ):
            self._parent_session_id, self._experiment_id = identity
            self._states.clear()
            self._control = {}
            self._cosecant = None
            self._sine_events.clear()
            self._mirl_events.clear()
            self._mirl_last_event.clear()
            self._cosecant_events.clear()
            self._last_sine_fact_episode = ""
            self._last_mirl_fact_episode = ""
            self._last_cosecant_fact_break = ""
            self._cosecant_fact_state = ""
        self._mode = MODE_LIVE
        return self.waiting_state()

    def idle(self) -> LiveOrganTimelineState:
        self._mode = MODE_IDLE
        self._parent_session_id = 0
        self._experiment_id = ""
        self._states.clear()
        self._control = {}
        self._cosecant = None
        return self.waiting_state()

    def finalizing(self) -> tuple[LiveOrganTimelineState, ...]:
        return self._freeze(MODE_FINALIZING)

    def experiment_ended(self) -> tuple[LiveOrganTimelineState, ...]:
        return self._freeze(MODE_EXPERIMENT_ENDED)

    def interrupted(self) -> tuple[LiveOrganTimelineState, ...]:
        return self._freeze(MODE_INTERRUPTED)

    def _freeze(self, mode: str) -> tuple[LiveOrganTimelineState, ...]:
        self._mode = mode
        stamp = self._stamp()
        self._states = {
            organ: replace(state, mode=mode, updated_monotonic_ns=stamp)
            for organ, state in self._states.items()
        }
        return self.states()

    def waiting_state(self) -> LiveOrganTimelineState:
        return LiveOrganTimelineState(
            parent_session_id=self._parent_session_id,
            experiment_id=self._experiment_id,
            organ=None,
            mode=self._mode,
            stage="",
            stages=_stages({}),
            episode_identity=None,
            updated_monotonic_ns=self._stamp(),
        )

    def states(self) -> tuple[LiveOrganTimelineState, ...]:
        return tuple(self._states[organ] for organ in ORGANS if organ in self._states)

    def receive_control_view(self, view: object) -> tuple[LiveOrganTimelineState, ...]:
        if self._mode != MODE_LIVE or not isinstance(view, Mapping):
            return ()
        session_id = _field(view, "session_id")
        if session_id != self._parent_session_id:
            return ()
        self._control = view
        candidates = (
            self._project_sine(),
            self._project_mine(_field(view, "mine")),
            self._project_cosine(_field(view, "cosine")),
        )
        changed: list[LiveOrganTimelineState] = []
        for state in candidates:
            if state is not None:
                changed.append(self._store(state))
        return tuple(changed)

    def receive_study_view(self, view: object) -> tuple[LiveOrganTimelineState, ...]:
        if self._mode != MODE_LIVE:
            return ()
        if not hasattr(view, "break_id") or not hasattr(view, "confirmation_elapsed_seconds"):
            return ()
        self._cosecant = view
        state = self._project_cosecant(view)
        return (self._store(state),) if state is not None else ()

    def receive_sine_fact(self, fact: object) -> tuple[LiveOrganTimelineState, ...]:
        if self._mode != MODE_LIVE or _field(fact, "session_id") != self._parent_session_id:
            return ()
        episode = str(_field(fact, "episode_uid", "") or "")
        kind = _value(_field(fact, "kind", ""))
        if episode and kind:
            self._sine_events.setdefault(episode, set()).add(kind)
            self._last_sine_fact_episode = episode
        state = self._project_sine()
        return (self._store(state),) if state is not None else ()

    def receive_mirl_fact(self, fact: object) -> tuple[LiveOrganTimelineState, ...]:
        if self._mode != MODE_LIVE or _field(fact, "session_id") != self._parent_session_id:
            return ()
        episode = str(_field(fact, "episode_id", "") or "")
        event = _value(_field(fact, "event_name", _field(fact, "kind", "")))
        if episode and event:
            self._mirl_events.setdefault(episode, set()).add(event)
            self._mirl_last_event[episode] = event
            self._last_mirl_fact_episode = episode
        state = self._project_sine()
        return (self._store(state),) if state is not None else ()

    def receive_cosecant_fact(self, fact: object) -> tuple[LiveOrganTimelineState, ...]:
        if self._mode != MODE_LIVE:
            return ()
        break_id = str(_field(fact, "break_id", "") or "")
        kind = _value(_field(fact, "kind", ""))
        if break_id and kind:
            self._cosecant_events.setdefault(break_id, set()).add(kind)
            self._last_cosecant_fact_break = break_id
            self._cosecant_fact_state = _value(_field(fact, "to_state", ""))
        state = self._project_cosecant(self._cosecant)
        return (self._store(state),) if state is not None else ()

    def _project_sine(self) -> LiveOrganTimelineState | None:
        blacklist = _field(self._control, "blacklist")
        sine = _field(self._control, "sine")
        mirl = _field(self._control, "mirl")
        sine_phase = _value(_field(sine, "phase"))
        mirl_phase = _value(_field(mirl, "phase"))
        watch_state = _value(_field(blacklist, "state"))
        sine_episode = str(_field(sine, "episode_uid", "") or "") or self._last_sine_fact_episode
        mirl_episode = str(_field(mirl, "episode_id", "") or "") or self._last_mirl_fact_episode
        factual = bool(sine_episode or mirl_episode) or sine_phase not in {
            "", "IDLE", "RESOLVED", "CANCELLED", "EMERGENCY_STOPPED"
        } or watch_state in {"WATCHING", "PAUSED", "THRESHOLD_REACHED", "SUBMITTED"}
        if not factual:
            return None

        values = _pending()
        episode = mirl_episode or sine_episode or str(_field(blacklist, "platform_key", "") or "")
        sine_events = self._sine_events.get(sine_episode, set())
        mirl_events = self._mirl_events.get(mirl_episode, set())
        last_mirl = self._mirl_last_event.get(mirl_episode, _value(_field(mirl, "last_event")))
        displayed = (
            "SINE_DISPLAYED" in sine_events
            or _value(_field(sine, "last_fact")) == "SINE_DISPLAYED"
            or mirl_phase in {
                "WAITING_FOR_RETURN", "RETURN_VERIFICATION", "CLOSURE_CONFIRMATION", "CLOSED"
            }
        )
        verified = "RETURN_VERIFIED" in mirl_events or mirl_phase in {
            "CLOSURE_CONFIRMATION", "CLOSED"
        }
        closed = "EPISODE_CLOSED" in mirl_events or mirl_phase == "CLOSED"
        relapse = last_mirl in {"RELAPSE_DETECTED", "EPISODE_RESUMED"}
        return_started = last_mirl in {
            "RETURN_VERIFICATION_STARTED", "RELAPSE_DETECTED", "EPISODE_RESUMED"
        }
        closure_started = last_mirl == "CLOSURE_CONFIRMATION_STARTED"
        paused = watch_state == "PAUSED" or bool(_field(sine, "activity_clock_paused", False))

        stage = ""
        if watch_state in {"WATCHING", "PAUSED", "THRESHOLD_REACHED", "SUBMITTED"} and not displayed:
            fraction, elapsed, total = _progress(
                _field(blacklist, "dwell_elapsed_seconds"),
                _field(blacklist, "dwell_target_seconds"),
            )
            _active(
                values,
                "OFF_TASK_DWELL",
                progress=fraction,
                elapsed=elapsed,
                total=total,
                paused=paused,
                reason="Canonical eligible dwell from the Blacklist live view.",
            )
            stage = "OFF_TASK_DWELL"
        elif sine_episode and not displayed:
            _active(
                values,
                "TRIGGER",
                paused=paused,
                reason="SINE intervention is pending factual display; duration is not asserted.",
            )
            stage = "TRIGGER"

        if displayed:
            _complete(values, "OFF_TASK_DWELL", "TRIGGER", reason="Factual SINE display observed.")
            stage = "TRIGGER"
        if mirl_phase == "RETURN_VERIFICATION" or return_started or relapse:
            fraction, elapsed, total = _progress(
                _field(mirl, "return_verification_elapsed_seconds"),
                _field(mirl, "return_verification_target_seconds"),
            )
            _active(
                values,
                "RETURN",
                progress=fraction,
                elapsed=elapsed,
                total=total,
                reason=(
                    "Factual MIRL relapse/resume returned the same episode to verification."
                    if relapse
                    else "Canonical MIRL return verification progress."
                ),
            )
            stage = "RETURN"
            if verified:
                _complete(values, "VERIFIED_RETURN", reason="A factual MIRL return_verified event exists.")
            values["EPISODE_CLOSURE"] = (
                STATUS_PENDING, None, None, None, "Closure was cleared by factual relapse/resume."
            )
        elif verified:
            _complete(values, "RETURN", "VERIFIED_RETURN", reason="Factual MIRL verified return.")
            stage = "VERIFIED_RETURN"
        if (mirl_phase == "CLOSURE_CONFIRMATION" or closure_started) and not relapse:
            fraction, elapsed, total = _progress(
                _field(mirl, "closure_confirmation_elapsed_seconds"),
                _field(mirl, "closure_confirmation_target_seconds"),
            )
            _active(
                values,
                "EPISODE_CLOSURE",
                progress=fraction,
                elapsed=elapsed,
                total=total,
                reason="Canonical MIRL closure-confirmation progress.",
            )
            stage = "EPISODE_CLOSURE"
        if closed:
            _complete(
                values,
                "OFF_TASK_DWELL", "TRIGGER", "RETURN", "VERIFIED_RETURN", "EPISODE_CLOSURE",
                reason="Factual MIRL episode_closed event.",
            )
            stage = "EPISODE_CLOSURE"

        return self._state("SINE", stage, episode or None, values)

    def _project_mine(self, snapshot: object) -> LiveOrganTimelineState | None:
        if snapshot is None or _field(snapshot, "parent_session_id") != self._parent_session_id:
            return None
        phase = _value(_field(snapshot, "phase"))
        episode = str(_field(snapshot, "mine_episode_id", "") or "")
        if phase in {"", "IDLE", "SHUTDOWN"} and not episode:
            return None
        values = _pending()
        paused = bool(_field(snapshot, "global_paused", False))
        stage = ""
        if phase == "OBSERVING_MESSAGING":
            fraction, elapsed, total = _progress(
                _field(snapshot, "initial_gate_elapsed_seconds"),
                _field(snapshot, "initial_gate_seconds"),
            )
            _active(
                values,
                "OFF_TASK_DWELL",
                progress=fraction,
                elapsed=elapsed,
                total=total,
                paused=paused,
                reason="Canonical MINE initial-gate elapsed/total before MINE-1 escalation.",
            )
            stage = "OFF_TASK_DWELL"

        after_trigger = {
            "RETURN_INTENT_ACTIVE", "IMPORTANT_DURATION_ENTRY", "IMPORTANT_COMMIT_PENDING",
            "IMPORTANT_ALLOWANCE_ACTIVE", "MINE2A_PENDING", "MINE2A_ACTIVE", "MINE2B_PENDING",
            "MINE2B_ACTIVE", "RETURN_VISUAL_CONFIRMING", "RETURN_VERIFYING",
            "CLOSURE_CONFIRMING", "CLOSED",
        }
        trigger_displayed = bool(_field(snapshot, "mine1_displayed", False)) or phase in after_trigger
        if phase in {"MINE1_PENDING", "MINE1_ACTIVE"} and not trigger_displayed:
            _active(values, "TRIGGER", paused=paused, reason="MINE-1 awaits factual display.")
            stage = "TRIGGER"
        if trigger_displayed:
            _complete(values, "OFF_TASK_DWELL", "TRIGGER", reason="Factual MINE intervention state.")
            stage = "TRIGGER"

        if phase in {"RETURN_VISUAL_CONFIRMING", "RETURN_VERIFYING"}:
            _active(
                values,
                "RETURN",
                paused=paused,
                reason="Factual MINE return verification; no authoritative total is exposed.",
            )
            stage = "RETURN"
        verification = _value(_field(snapshot, "return_verification_state"))
        if verification in {"VERIFIED", "COMPLETE", "CONFIRMED"} or phase in {
            "CLOSURE_CONFIRMING", "CLOSED"
        }:
            _complete(values, "RETURN", "VERIFIED_RETURN", reason="Factual MINE verified-return state.")
            stage = "VERIFIED_RETURN"
        if phase == "CLOSURE_CONFIRMING":
            _active(
                values,
                "EPISODE_CLOSURE",
                paused=paused,
                reason="MINE closure is factual but has no exposed elapsed/total pair.",
            )
            stage = "EPISODE_CLOSURE"
        elif phase == "CLOSED":
            _complete(values, "EPISODE_CLOSURE", reason="Factual MINE closed state.")
            stage = "EPISODE_CLOSURE"
        return self._state("MINE", stage, episode or None, values)

    def _project_cosine(self, snapshot: object) -> LiveOrganTimelineState | None:
        if snapshot is None or _field(snapshot, "session_id") != self._parent_session_id:
            return None
        phase = _value(_field(snapshot, "phase"))
        episode = str(_field(snapshot, "cosine_session_id", "") or "")
        if phase in {"", "IDLE", "SHUTDOWN"} and not episode:
            return None
        values = _pending()
        paused = bool(_field(snapshot, "global_paused", False))
        stage = ""
        if phase == "OBSERVING_OTT":
            elapsed = _number(_field(snapshot, "qualification_seconds"))
            remaining = _number(_field(snapshot, "initial_gate_remaining_seconds"))
            total = None if elapsed is None or remaining is None else max(0.0, elapsed) + max(0.0, remaining)
            fraction, elapsed, total = _progress(elapsed, total)
            _active(
                values,
                "OFF_TASK_DWELL",
                progress=fraction,
                elapsed=elapsed,
                total=total,
                paused=paused,
                reason="Canonical COSINE qualification elapsed plus remaining time.",
            )
            stage = "OFF_TASK_DWELL"

        after_trigger = {
            "RETURN_INTENT_OBSERVING", "DURATION_ENTRY", "BREAK_COMMIT_PENDING", "BREAK_ACTIVE",
            "RETURN_VERIFYING", "CLOSURE_CONFIRMING", "FINAL_CALLBACK_PENDING",
            "FINAL_CALLBACK_ACTIVE", "FINAL_CALLBACK_HIDDEN_VERIFYING", "CLOSED",
        }
        trigger_displayed = bool(_field(snapshot, "checkin_displayed", False)) or phase in after_trigger
        if phase in {"INTENT_GATE_PENDING", "INTENT_GATE_ACTIVE"} and not trigger_displayed:
            _active(values, "TRIGGER", paused=paused, reason="COSINE intent gate awaits factual display.")
            stage = "TRIGGER"
        if trigger_displayed:
            _complete(values, "OFF_TASK_DWELL", "TRIGGER", reason="Factual COSINE intervention state.")
            stage = "TRIGGER"

        break_progress = None
        if phase == "BREAK_ACTIVE":
            start = _number(_field(snapshot, "break_start_effective_ns"))
            deadline = _number(_field(snapshot, "break_deadline_effective_ns"))
            remaining = _number(_field(snapshot, "break_remaining_seconds"))
            total = None if start is None or deadline is None or deadline <= start else (deadline - start) / 1_000_000_000
            elapsed = None if total is None or remaining is None else max(0.0, total - remaining)
            fraction, elapsed, total = _progress(elapsed, total)
            break_progress = LiveStageProgress(
                "BREAK", STATUS_PAUSED if paused else STATUS_ACTIVE,
                fraction, elapsed, total, "Canonical COSINE break timing.",
            )
        if phase in {"RETURN_VERIFYING", "FINAL_CALLBACK_HIDDEN_VERIFYING"}:
            _active(
                values,
                "RETURN",
                paused=paused,
                reason="Factual COSINE return verification; no authoritative total is exposed.",
            )
            stage = "RETURN"
        verification = _value(_field(snapshot, "return_verification_state"))
        if verification in {"VERIFIED", "COMPLETE", "CONFIRMED"} or phase in {
            "CLOSURE_CONFIRMING", "CLOSED"
        }:
            _complete(values, "RETURN", "VERIFIED_RETURN", reason="Factual COSINE verified-return state.")
            stage = "VERIFIED_RETURN"
        if phase == "CLOSURE_CONFIRMING":
            _active(
                values,
                "EPISODE_CLOSURE",
                paused=paused,
                reason="COSINE closure is factual but has no exposed elapsed/total pair.",
            )
            stage = "EPISODE_CLOSURE"
        elif phase == "CLOSED":
            _complete(values, "EPISODE_CLOSURE", reason="Factual COSINE closed state.")
            stage = "EPISODE_CLOSURE"
        return self._state("COSINE", stage, episode or None, values, break_progress)

    def receive_secant_projection(self, snapshot: object) -> tuple[LiveOrganTimelineState, ...]:
        if self._mode != MODE_LIVE or snapshot is None:
            return ()
        scope = _field(snapshot, "scope")
        context = str(_field(scope, "context_id", ""))
        if not context.startswith(str(self._parent_session_id) + ":"):
            return ()
        episode = str(_field(snapshot, "episode_id", ""))
        facts = tuple(_field(snapshot, "timeline", ()))
        names = {_field(f, "name") for f in facts if _field(f, "episode_id") == episode}
        values = _pending()
        frozen = bool(_field(snapshot, "frozen_reasons", ()))
        stage = "OFF_TASK_DWELL"
        if not episode:
            _active(values, stage, paused=frozen, reason="SECANT qualification; no factual episode display yet.")
        else:
            if "SECANT_EPISODE_FOUNDED" in names:
                _complete(values, "OFF_TASK_DWELL", "TRIGGER", reason="SECANT-1 factual display founded this Study episode.")
            stage = "TRIGGER"
            recovery = _field(snapshot, "recovery")
            phase = _value(_field(recovery, "phase"))
            paused = frozen or bool(_field(recovery, "global_hold_id"))
            if phase in {"VERIFYING", "CONFIRMING"}:
                stage = "RETURN" if phase == "VERIFYING" else "VERIFIED_RETURN"
                if phase == "CONFIRMING":
                    _complete(values, "RETURN", reason="Native SECANT return verification completed.")
                elapsed_key, target_key = (("verification_elapsed_ns", "verification_target_ns") if phase == "VERIFYING"
                                          else ("closure_elapsed_ns", "closure_target_ns"))
                elapsed, total = _number(_field(recovery, elapsed_key)), _number(_field(recovery, target_key))
                progress, elapsed, total = _progress(None if elapsed is None else elapsed / 1e9,
                                                     None if total is None else total / 1e9)
                _active(values, stage, progress=progress, elapsed=elapsed, total=total, paused=paused,
                        reason="Native SECANT supported verification / confirmation; independent of MIRL.")
            elif phase == "CLOSED":
                stage = "EPISODE_CLOSURE"
                _complete(values, "RETURN", "VERIFIED_RETURN", "EPISODE_CLOSURE", reason="Native SECANT recovery closure.")
            elif _field(snapshot, "terminal_reason"):
                stage = "EPISODE_CLOSURE"
                _complete(values, stage, reason="Episode terminated: " + str(_field(snapshot, "terminal_reason")))
            elif "SECANT_RECOVERY_INTERRUPTED" in names:
                stage = "RETURN"
                interrupted = next((f for f in reversed(facts) if _field(f, "name") == "SECANT_RECOVERY_INTERRUPTED"), None)
                _active(values, stage, paused=True, reason="Recovery interrupted: " + str(_field(interrupted, "reason", "")))
        state = self._state("SECANT", stage, episode or None, values)
        return (self._store(state),)

    def _project_cosecant(self, snapshot: object) -> LiveOrganTimelineState | None:
        if snapshot is None and not self._last_cosecant_fact_break:
            return None
        state_name = _value(_field(snapshot, "state")) or self._cosecant_fact_state
        break_id = str(_field(snapshot, "break_id", "") or "") or self._last_cosecant_fact_break
        if state_name in {"", "INACTIVE", "SHUTDOWN"} and not break_id:
            return None
        values = _pending()
        stage = ""
        break_progress = None
        events = self._cosecant_events.get(break_id, set())
        if "RETURN_CONFIRMATION_STARTED" in events or "RETURN_CONFIRMATION_RESTARTED" in events:
            state_name = "RETURN_CONFIRMING"
        if "RETURN_CONFIRMED" in events:
            state_name = "CONFIRMED"
        if state_name == "BREAK_ACTIVE":
            start = _number(_field(snapshot, "break_started_monotonic_ns"))
            end = _number(_field(snapshot, "break_ends_monotonic_ns"))
            remaining = _number(_field(snapshot, "seconds_to_next_stage"))
            total = None if start is None or end is None or end <= start else (end - start) / 1_000_000_000
            elapsed = None if total is None or remaining is None else max(0.0, total - remaining)
            fraction, elapsed, total = _progress(elapsed, total)
            break_progress = LiveStageProgress(
                "BREAK", STATUS_ACTIVE, fraction, elapsed, total,
                "Canonical COSECANT break start/end and remaining time.",
            )
        if state_name in {"BREAK_COMPLETE", "BREAK_ALREADY_OVER", "FINAL_LOCK"}:
            values["TRIGGER"] = (
                STATUS_COMPLETE, 1.0, None, None, "Factual COSECANT break escalation state."
            )
            stage = "TRIGGER"
            break_progress = LiveStageProgress(
                "BREAK", STATUS_COMPLETE, 1.0, None, None, "Factual COSECANT break completion."
            )
        if state_name == "RETURN_CONFIRMING":
            _complete(values, "TRIGGER", reason="Factual COSECANT return confirmation started.")
            started = _number(_field(snapshot, "confirmation_started_monotonic_ns"))
            due = _number(_field(snapshot, "confirmation_due_monotonic_ns"))
            total = None if started is None or due is None or due <= started else (due - started) / 1_000_000_000
            fraction, elapsed, total = _progress(
                _field(snapshot, "confirmation_elapsed_seconds"), total
            )
            _active(
                values,
                "RETURN",
                progress=fraction,
                elapsed=elapsed,
                total=total,
                reason="Canonical COSECANT exact-resource return confirmation.",
            )
            stage = "RETURN"
        if state_name == "CONFIRMED" or bool(_field(snapshot, "return_confirmed", False)):
            _complete(values, "TRIGGER", "RETURN", "VERIFIED_RETURN", reason="Factual COSECANT RETURN_CONFIRMED.")
            stage = "VERIFIED_RETURN"
        return self._state("COSECANT", stage, break_id or None, values, break_progress)

    def _state(
        self,
        organ: str,
        stage: str,
        episode: str | None,
        values: Mapping,
        break_progress: LiveStageProgress | None = None,
    ) -> LiveOrganTimelineState:
        return LiveOrganTimelineState(
            parent_session_id=self._parent_session_id,
            experiment_id=self._experiment_id,
            organ=organ,
            mode=MODE_LIVE,
            stage=stage,
            stages=_stages(values),
            episode_identity=episode,
            updated_monotonic_ns=self._stamp(),
            break_progress=break_progress,
        )

    def _store(self, state: LiveOrganTimelineState) -> LiveOrganTimelineState:
        previous = self._states.get(str(state.organ))
        if previous is not None and previous.episode_identity == state.episode_identity:
            old_by_stage = {row.stage: row for row in previous.stages}
            merged: list[LiveStageProgress] = []
            for row in state.stages:
                old = old_by_stage.get(row.stage)
                if (
                    old is not None
                    and row.status in {STATUS_ACTIVE, STATUS_PAUSED}
                    and old.status in {STATUS_ACTIVE, STATUS_PAUSED}
                    and row.progress is not None
                    and old.progress is not None
                    and row.elapsed_seconds is not None
                    and old.elapsed_seconds is not None
                    and row.elapsed_seconds >= old.elapsed_seconds
                ):
                    row = replace(row, progress=max(row.progress, old.progress))
                merged.append(row)
            state = replace(state, stages=tuple(merged))
        self._states[str(state.organ)] = state
        return state

    def _stamp(self) -> int:
        value = self._monotonic_ns()
        return int(value) if type(value) is int and value >= 0 else 0


__all__ = [
    "LiveOrganTimelineProjector",
    "LiveOrganTimelineState",
    "LiveStageProgress",
    "MODE_EXPERIMENT_ENDED",
    "MODE_FINALIZING",
    "MODE_IDLE",
    "MODE_INTERRUPTED",
    "MODE_LIVE",
    "ORGANS",
    "STAGES",
    "STATUS_ACTIVE",
    "STATUS_COMPLETE",
    "STATUS_PAUSED",
    "STATUS_PENDING",
]
