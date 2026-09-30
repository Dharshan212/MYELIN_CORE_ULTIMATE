"""The single Windows monitoring coordinator for MYELIN.

This file owns the order of one monitoring cycle.  It does not contain the
specialist rules used by Browser Evidence, Resource Intent, Executive
Blacklist, Trigger, SINE, COSINE or MIRL.

The required order is:

1. observe the foreground window;
2. obtain certified browser evidence;
3. classify Resource Intent;
4. hand the observation to COSINE and MIRL;
5. advance the Executive Blacklist watch;
6. ask Trigger whether one candidate is ready;
7. persist that exact candidate;
8. wait until persistence is COMMITTED;
9. confirm durable trigger admission;
10. prepare MIRL and request SINE; and
11. publish factual telemetry.

Important durability rule
-------------------------
``RUNNING`` means unfinished.  A RUNNING persistence receipt is retained as a
pending workflow.  No cooldown, MIRL preparation or SINE request occurs until
that same receipt becomes COMMITTED.  A failed receipt rejects the candidate
and produces no intervention.

Important ownership rule
------------------------
This is the only foreground monitor in final MYELIN.  ``URL_Monitor.py`` is a
reference source only and ``windows_monitor.py`` is not part of production.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import math
import os
import queue
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from CORE_ENGINE.app_identity import ForegroundAppIdentity, read_foreground_app_identity
from ME.handover import HandoverLayer, HandoverResult


DEFAULT_POLL_SECONDS: Final = 1.5
STUDY_CONTINUITY_MAX_GAP_NS: Final = 5_000_000_000
# The recovery-evidence semantic generation THIS monitor implementation knows
# how to interpret for learning.
#
# This is deliberately a literal owned by monitor, NOT an import from
# MIRL.mirl.  MIRL is the producer: it declares what it produced.  Monitor is
# the learning consumer: it declares what it can safely interpret.  Importing
# the producer's constant would make those the same statement, and MYELIN is
# reconstructed organ by organ -- pairing this monitor with an older MIRL whose
# module declared v1 would then silently move monitor's own expectation to v1,
# the v1 comparison would pass, and proof-based Tr would be written to storage
# under the onset-based v2 label.  That is precisely the mislabelling the
# provenance work exists to prevent.
#
# So: changing MIRL cannot change this value.  A new recovery-evidence
# generation requires an explicit review of THIS learning implementation, in
# this file, because the meaning of ``verified_recovery_elapsed_seconds`` is
# what is being asserted here.
#
# Note this is a different contract from
# ``PERSISTENCE.storage.PROFILE_LEARNING_MODEL_VERSION``, which records the
# generation of durable learning state.  The two are separately owned; neither
# aliases the other, and monitor translates between them.
#
# v3 REVIEW (C8.2/C8.3 freeze correction).  v3 keeps the v2 behavioural-return
# ONSET meaning of ``verified_recovery_elapsed_seconds``: the latency equation
# and every timestamp anchor are unchanged.  What v3 changes is the admissible
# recovery POPULATION -- automatic as well as manual Study alignment may now
# enter MIRL verification, and a recovery observed while Protected Red is
# running is visible at all.  This monitor's Tr/lambda interpretation is
# therefore mathematically applicable to v3 exactly as it was to v2, and THIS
# implementation has explicitly reviewed that change and accepts v3.
#
# Storage's PROFILE_LEARNING_MODEL_VERSION deliberately does NOT move with
# this.  It names the semantic generation of Tr itself -- behavioural return
# onset -- which v3 did not touch.  Bumping it would falsely imply a new Tr
# equation or a new anchor.
LEARNABLE_MIRL_RECOVERY_EVIDENCE_VERSION: Final = (
    "myelin-mirl-recovery-evidence-v3"
)

STARTUP_PERSISTENCE_TIMEOUT_SECONDS: Final = 10.0
SHUTDOWN_PERSISTENCE_TIMEOUT_SECONDS: Final = 8.0
MAX_TELEMETRY_TEXT: Final = 500
MAX_COMMANDS_PER_CYCLE: Final = 16
NANOSECONDS_PER_SECOND: Final = 1_000_000_000
STUDY_APP_CATEGORY_SCHEMA_VERSION: Final = "myelin-study-app-category-v1-prototype"
MESSAGING_PROCESS_LABELS: Final = {
    "whatsapp": "WhatsApp",
    "discord": "Discord",
    "telegram": "Telegram",
    "slack": "Slack",
    "teams": "Microsoft Teams",
    "ms-teams": "Microsoft Teams",
    "signal": "Signal",
    "viber": "Viber",
    "weixin": "WeChat",
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "x": "X",
    "reddit": "Reddit",
}

#: Phase 4 Case B locked badge system.  MINE (red) = escalation/messaging-
#: lock/organ-owned phases.  RETURN (green) = genuine recovery/return
#: phases only.  MESSAGING (a separate, pre-existing foreground-identity
#: badge from Phase 4 Case A) is never touched by this table.
MINE_TRANSITION_RETURN_PHASES: Final = frozenset(
    {
        "RETURN_INTENT_ACTIVE",
        "RETURN_VISUAL_CONFIRMING",
        "RETURN_VERIFYING",
        "CLOSURE_CONFIRMING",
    }
)

#: A CLOSED row only earns the RETURN badge when the factual closure
#: evidence proves a verified return -- never for Study preemption, an
#: incomplete session or an emergency stop.
MINE_VERIFIED_RETURN_OUTCOMES: Final = frozenset(
    {
        "RETURNED_AFTER_INTENT",
        "EARLY_RETURN_DURING_IMPORTANT_ALLOWANCE",
        "RETURNED_AFTER_CALLBACK",
    }
)

COMMITTED_STATE: Final = "COMMITTED"
RUNNING_STATE: Final = "RUNNING"


@dataclass(frozen=True, slots=True)
class ForegroundObservation:
    """One factual Windows observation with no behavioral interpretation."""

    sequence: int
    hwnd: int
    process_id: int
    process_name: str
    window_title: str
    observed_monotonic_ns: int
    observed_wall_time_utc: str
    idle_seconds: float
    app_identity: ForegroundAppIdentity | None = None


@dataclass(frozen=True, slots=True)
class MonitorContext:
    """One cycle's immutable facts passed between specialist authorities."""

    foreground: ForegroundObservation
    browser_evidence: object
    resource_intent: object
    cosine_platform: object | None = None
    cosine_owned: bool = False
    study_owned: bool = False


@dataclass(frozen=True, slots=True)
class BreakEligibleStudyTarget:
    """One exact Study resource already certified for managed-break return."""

    study_block_id: str
    study_generation: int
    study_context_token: str
    platform_key: str
    resource_token: str
    observed_monotonic_ns: int


@dataclass(frozen=True, slots=True)
class PendingTriggerWorkflow:
    """Exact trigger candidate waiting for one durable transaction result."""

    candidate_uid: str
    candidate: object
    receipt_id: str
    submitted_monotonic_ns: int
    superseded_by_break_id: str = ""
    superseded_monotonic_ns: int = 0
    committed_seen_monotonic_ns: int = 0


@runtime_checkable
class BrowserAuthority(Protocol):
    def start_session(self) -> None: ...

    def observe(self, foreground: ForegroundObservation) -> object: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class ResourceIntentAuthority(Protocol):
    def start_session(self, *, profile_type: str) -> None: ...


    def observe(
        self,
        *,
        foreground: ForegroundObservation,
        browser_evidence: object,
        certified_ott_platform_key: str = "",
    ) -> object: ...

    def live_view(self) -> object: ...


    def set_certified_ott_platform_key(self, platform_key: str) -> None: ...

    def drain_facts(self) -> tuple[object, ...]: ...

    def record_study_confirmation_popup_shown(
        self, *, request_id: str, shown_monotonic_ns: int, popup_hwnd: int
    ) -> bool: ...

    def record_study_confirmation_popup_closed(
        self, *, request_id: str, occurred_monotonic_ns: int, reason: str
    ) -> bool: ...

    def record_study_confirmation_response(
        self,
        *,
        request_id: str,
        response: str,
        occurred_monotonic_ns: int,
        expected_study_context_token: str,
        expected_resource_key: str,
    ) -> bool: ...

    def record_study_material_allowance(
        self,
        *,
        study_context_token: str,
        resource_key: str,
        granted_monotonic_ns: int,
    ) -> object: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class BlacklistAuthority(Protocol):
    def start_session(self, *, personalization_factor: float = 1.0) -> None: ...

    def stage_one_target_seconds(self) -> float: ...

    def observe(self, context: MonitorContext) -> object: ...

    def live_view(self) -> object: ...

    def set_paused(self, paused: bool) -> None: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class TriggerAuthority(Protocol):
    def start_session(
        self,
        *,
        session_id: int,
        profile_type: str,
        decay_rate_per_minute: float | None = None,
    ) -> None: ...

    def evaluate(self, *, context: MonitorContext, blacklist: object) -> object | None: ...

    def candidate_uid(self, candidate: object) -> str: ...

    def confirm_durable_admission(
        self,
        *,
        candidate_uid: str,
        operational_event_id: int,
    ) -> bool: ...

    def reject_candidate(self, *, candidate_uid: str, reason: str) -> bool: ...

    def record_intervention_fact(self, fact: object) -> None: ...

    def live_view(self) -> object: ...

    def estimate_observed_lambda(
        self,
        *,
        candidate_uid: str,
        verified_recovery_minutes: float,
    ) -> object | None: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class SineAuthority(Protocol):
    def start_session(
        self,
        *,
        session_id: int,
        profile_type: str,
        timing: object | None = None,
    ) -> None: ...

    def observe(self, context: MonitorContext) -> None: ...

    def request_trigger(
        self,
        *,
        candidate: object,
        operational_event_id: int,
        mirl_display_token: object | None,
    ) -> bool: ...

    def advance(self, *, now_monotonic_ns: int) -> tuple[object, ...]: ...


    def confirm_verified_return(
        self,
        *,
        candidate_uid: str,
        verified_monotonic_ns: int,
        evidence_source: str,
    ) -> bool: ...

    def withhold_presentation_for_verified_return_entry(
        self,
        *,
        candidate_uid: str,
        verified_monotonic_ns: int,
        evidence_source: str,
    ) -> bool: ...

    def resume_presentation_after_recovery_relapse(
        self,
        *,
        candidate_uid: str,
        occurred_monotonic_ns: int,
        evidence_source: str,
    ) -> bool: ...

    def pause_escalation_for_activity(
        self,
        *,
        candidate_uid: str,
        occurred_monotonic_ns: int,
        evidence_source: str,
    ) -> bool: ...

    def resume_escalation_after_activity(
        self,
        *,
        candidate_uid: str,
        occurred_monotonic_ns: int,
        evidence_source: str,
    ) -> bool: ...

    def confirm_break_started(
        self,
        *,
        candidate_uid: str,
        occurred_monotonic_ns: int,
    ) -> bool: ...

    def hold_for_normal_break(
        self,
        *,
        candidate_uid: str,
        episode_uid: str,
        break_id: str,
        break_generation: int,
        started_monotonic_ns: int,
        source_popup_request_id: str,
    ) -> bool: ...

    def cancel_normal_break_hold(
        self,
        *,
        candidate_uid: str,
        episode_uid: str,
        break_id: str,
        break_generation: int,
        occurred_monotonic_ns: int,
        reason: str,
    ) -> bool: ...

    def enter_post_normal_break_return_gate(
        self,
        *,
        candidate_uid: str,
        episode_uid: str,
        break_id: str,
        break_generation: int,
        occurred_monotonic_ns: int,
        completion_kind: str,
    ) -> bool: ...

    def restore_protected_red(self) -> bool: ...

    def monitor_status(self, *, now_ns: int | None = None) -> object: ...

    def monitor_hold(self, *, episode_key: object, now_ns: int) -> bool: ...

    def monitor_resume(self, *, episode_key: object, now_ns: int) -> bool: ...

    def monitor_terminate(self, *, episode_key: object, now_ns: int) -> bool: ...

    def preempt_for_study(self, *, now_ns: int | None = None) -> bool: ...

    def live_view(self) -> object: ...

    def protected_red_active(self) -> bool: ...

    def emergency_stop(self) -> None: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class CosineAuthority(Protocol):
    def bind_parent_session(self, session_id: int) -> bool: ...

    def observe(self, observation: object) -> tuple[object, ...]: ...

    def advance(self, *, now_ns: int | None = None) -> tuple[object, ...]: ...

    def set_global_paused(self, paused: bool, now_ns: int | None = None) -> bool: ...

    def submit_command(self, command: object) -> object: ...

    def drain_effects(self) -> tuple[object, ...]: ...

    def snapshot(self, *, now_ns: int | None = None) -> object: ...

    def monitor_status(self, *, now_ns: int | None = None) -> object: ...
    def monitor_hold(self, *, episode_key: object, now_ns: int) -> bool: ...
    def monitor_resume(self, *, episode_key: object, now_ns: int) -> bool: ...
    def monitor_terminate(self, *, episode_key: object, now_ns: int) -> bool: ...

    def close(self, reason: object, *, now_ns: int | None = None) -> tuple[object, ...]: ...

    def preempt_for_study(self, *, now_ns: int | None = None) -> tuple[object, ...]: ...

    def shutdown(self, *, now_ns: int | None = None) -> bool: ...


@runtime_checkable
class MineAuthority(Protocol):
    def bind_parent_session(self, session_id: int) -> bool: ...
    def observe(self, observation: object) -> tuple[object, ...]: ...
    def advance(self, *, now_ns: int | None = None) -> tuple[object, ...]: ...
    def set_global_paused(self, paused: bool, now_ns: int | None = None) -> bool: ...
    def submit_command(self, command: object) -> object: ...
    def drain_effects(self) -> tuple[object, ...]: ...
    def snapshot(self, *, now_ns: int | None = None) -> object: ...
    def monitor_status(self, *, now_ns: int | None = None) -> object: ...
    def monitor_hold(self, *, episode_key: object, now_ns: int) -> bool: ...
    def monitor_resume(self, *, episode_key: object, now_ns: int) -> bool: ...
    def monitor_terminate(self, *, episode_key: object, now_ns: int) -> bool: ...
    def preempt_for_study(self, *, now_ns: int | None = None) -> tuple[object, ...]: ...
    def release_study_preemption(self, *, now_ns: int | None = None) -> bool: ...
    def close(self, reason: object, *, now_ns: int | None = None) -> tuple[object, ...]: ...
    def shutdown(self, *, now_ns: int | None = None) -> bool: ...


@runtime_checkable
class StudyAuthority(Protocol):
    def prepare(self, *, subject: str, task: str, planned_seconds: int, block_id: str = "") -> object: ...
    def start(self) -> object: ...
    def pause(self) -> object: ...
    def resume(self) -> object: ...
    def complete(self) -> object: ...
    def advance(self) -> object: ...
    def shutdown(self) -> object: ...
    def snapshot(self) -> object: ...


@runtime_checkable
class CosecantAuthority(Protocol):
    def start_break(
        self,
        *,
        study: object,
        selected_break_seconds: int,
        intended_return_target: object,
    ) -> object: ...
    def advance(self) -> object: ...
    def record_return_intent(self) -> object: ...
    def observe_return(self, observation: object) -> object: ...
    def cancel_for_session_end(self) -> object: ...
    def shutdown(self) -> object: ...
    def snapshot(self) -> object: ...


@runtime_checkable
class MirlAuthority(Protocol):
    def start_session(self, *, session_id: int, profile_type: str) -> None: ...

    def observe(self, context: MonitorContext) -> tuple[object, ...]: ...

    def record_recovery_observation(
        self,
        observation: object,
    ) -> tuple[object, ...]: ...

    def prepare_trigger(
        self,
        *,
        candidate: object,
        operational_event_id: int,
    ) -> object | None: ...

    def record_sine_fact(self, fact: object) -> None: ...

    def drain_events(self) -> tuple[object, ...]: ...

    def drain_verified_recovery_evidence(self) -> tuple[object, ...]: ...

    def live_view(self) -> object: ...

    def emergency_stop(self) -> None: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class StorageAuthority(Protocol):
    def open_monitor_session(self, *, profile_type: str) -> object: ...

    def load_profile_learning(self, *, profile_key: str) -> object: ...

    def update_profile_learning_session(
        self,
        *,
        profile_key: str,
        session_id: int,
        session_lambda: float,
        session_return_latency_seconds: float,
        valid_episode_count: int,
    ) -> object: ...

    def persist_trigger(
        self,
        *,
        session_id: int,
        candidate: object,
    ) -> object: ...

    def receipt(self, receipt_id: str) -> object | None: ...

    def wait(self, receipt_id: str, *, timeout_seconds: float) -> object | None: ...

    def forget_receipt(self, receipt_id: str) -> bool: ...

    def close_monitor_session(
        self,
        *,
        session_id: int,
        reason: str,
    ) -> object: ...

    def record_emergency(self, *, session_id: int) -> object: ...

    def append_sine_facts(self, facts: tuple[object, ...]) -> bool: ...

    def append_mine_events(self, events: tuple[object, ...]) -> bool: ...

    def append_normal_break_facts(self, facts: tuple[object, ...]) -> bool: ...

    def append_mirl_events(self, events: tuple[object, ...]) -> bool: ...

    def append_cosecant_facts(self, *, session_id: int | None, facts: tuple[object, ...]) -> bool: ...

    def record_study_snapshot(self, *, session_id: int | None, action: str, snapshot: object) -> bool: ...

    def shutdown(self) -> None: ...


@runtime_checkable
class NormalBreakAuthority(Protocol):
    @property
    def active(self) -> bool: ...

    def request_duration(self, **kwargs) -> object: ...

    def cancel_duration(self, **kwargs) -> object: ...

    def start_break(self, **kwargs) -> object: ...

    def stop_break(self, **kwargs) -> object: ...

    def advance(self, *, now_monotonic_ns: int) -> object: ...

    def terminate(self, **kwargs) -> object: ...

    def rollback_start(self, **kwargs) -> object: ...

    def snapshot(self) -> object: ...

    def drain_facts(self) -> tuple[object, ...]: ...


@dataclass(frozen=True, slots=True)
class MonitorServices:
    """Real production authorities composed once for one monitor session."""

    browser: BrowserAuthority
    resource_intent: ResourceIntentAuthority
    blacklist: BlacklistAuthority
    trigger: TriggerAuthority
    sine: SineAuthority
    cosine: CosineAuthority
    mirl: MirlAuthority
    study: StudyAuthority
    cosecant: CosecantAuthority
    normal_break: NormalBreakAuthority
    storage: StorageAuthority
    mine: MineAuthority | None = None


class WindowsForegroundReader:
    """Small passive Win32 reader; it performs no classification."""

    PROCESS_QUERY_LIMITED_INFORMATION: Final = 0x1000

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = (
            ("cbSize", ctypes.wintypes.UINT),
            ("dwTime", ctypes.wintypes.DWORD),
        )

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("MYELIN Core Engine requires Windows")
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._configure_win32_signatures()
        self._sequence = 0

    def _configure_win32_signatures(self) -> None:
        """Declare 64-bit-safe Win32 signatures before reading any handle."""

        self._user32.GetForegroundWindow.argtypes = ()
        self._user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        self._user32.GetWindowThreadProcessId.argtypes = (
            ctypes.wintypes.HWND,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        )
        self._user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
        self._user32.GetWindowTextLengthW.argtypes = (ctypes.wintypes.HWND,)
        self._user32.GetWindowTextLengthW.restype = ctypes.c_int
        self._user32.GetWindowTextW.argtypes = (
            ctypes.wintypes.HWND,
            ctypes.wintypes.LPWSTR,
            ctypes.c_int,
        )
        self._user32.GetWindowTextW.restype = ctypes.c_int
        self._user32.GetLastInputInfo.argtypes = (
            ctypes.POINTER(self.LASTINPUTINFO),
        )
        self._user32.GetLastInputInfo.restype = ctypes.wintypes.BOOL
        self._kernel32.OpenProcess.argtypes = (
            ctypes.wintypes.DWORD,
            ctypes.wintypes.BOOL,
            ctypes.wintypes.DWORD,
        )
        self._kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = (
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.DWORD,
            ctypes.wintypes.LPWSTR,
            ctypes.POINTER(ctypes.wintypes.DWORD),
        )
        self._kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (ctypes.wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
        self._kernel32.GetTickCount.argtypes = ()
        self._kernel32.GetTickCount.restype = ctypes.wintypes.DWORD

    def observe(self) -> ForegroundObservation:
        self._sequence += 1
        now_ns = time.monotonic_ns()
        raw_hwnd = self._user32.GetForegroundWindow()
        hwnd = 0 if raw_hwnd is None else int(raw_hwnd)
        if hwnd <= 0:
            return ForegroundObservation(
                sequence=self._sequence,
                hwnd=0,
                process_id=0,
                process_name="unknown",
                window_title="",
                observed_monotonic_ns=now_ns,
                observed_wall_time_utc=_utc_now(),
                idle_seconds=self._idle_seconds(),
            )

        process_id = ctypes.wintypes.DWORD()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        process_name = self._process_name(int(process_id.value))
        app_identity = read_foreground_app_identity(
            hwnd=hwnd,
            process_id=int(process_id.value),
            process_name=process_name,
            observed_monotonic_ns=now_ns,
        )
        return ForegroundObservation(
            sequence=self._sequence,
            hwnd=hwnd,
            process_id=int(process_id.value),
            process_name=process_name,
            window_title=self._window_title(hwnd),
            observed_monotonic_ns=now_ns,
            observed_wall_time_utc=_utc_now(),
            idle_seconds=self._idle_seconds(),
            app_identity=app_identity,
        )

    def _window_title(self, hwnd: int) -> str:
        length = max(0, int(self._user32.GetWindowTextLengthW(hwnd)))
        buffer = ctypes.create_unicode_buffer(min(length + 1, 32_768))
        self._user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return " ".join(buffer.value.split())[:4_096]

    def _process_name(self, process_id: int) -> str:
        if process_id <= 0:
            return "unknown"
        handle = self._kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id,
        )
        if not handle:
            return "unknown"
        try:
            capacity = ctypes.wintypes.DWORD(32_768)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            success = self._kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(capacity),
            )
            if not success:
                return "unknown"
            name = Path(buffer.value).name.lower()
            return name.removesuffix(".exe") or "unknown"
        finally:
            self._kernel32.CloseHandle(handle)

    def _idle_seconds(self) -> float:
        information = self.LASTINPUTINFO()
        information.cbSize = ctypes.sizeof(information)
        if not self._user32.GetLastInputInfo(ctypes.byref(information)):
            return 0.0
        # DWORD input ticks wrap about every 49.7 days. Masking preserves the
        # correct unsigned elapsed value across that boundary.
        current = int(self._kernel32.GetTickCount())
        elapsed_ms = (current - int(information.dwTime)) & 0xFFFFFFFF
        return elapsed_ms / 1_000.0


def _utc_now() -> str:
    """One UTC wall stamp in MYELIN's canonical ``...Z`` form.

    The trailing ``Z`` is not cosmetic.  ``observed_wall_time_utc`` produced
    here rides the foreground observation into MIRL and is stored verbatim as
    every return-verification and closure event's ``occurred_wall_time_utc``
    (MIRL/mirl.py passes ``wall_time=observation.observed_wall_time_utc``).
    MIRL's read model validates it with ``_valid_utc_timestamp``, which
    REQUIRES a ``Z`` suffix -- a bare ``+00:00`` offset was rejected as
    INVALID_WALL_TIMESTAMP, degrading the whole episode and suppressing its
    verified-return and stable-recovery latencies.  Every other wall-stamp
    helper in the tree (mirl.py, read_model.py, storage.py, cosecant.py)
    already normalises this way; this one did not.
    """

    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _field(value: object, name: str, default=None):
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


#: One command carried an absent, partial or unreadable expected-identity
#: group.  A command that cannot name the generation it was issued against
#: cannot be checked against current authority, so it is refused (C12-F).
#:
#: This used to distinguish "absent entirely" as a LEGACY exemption that
#: returned admitted=True unconditionally, which meant simply omitting the
#: fields walked a command straight past the C11-A stale-generation fence.
#: The production caller matrix proved no live sender can produce such a
#: command -- every Study/COSECANT request goes through the Control Station
#: controller, which copies the identity in unconditionally -- so the
#: exemption was dead authority protecting nothing but historical LAB calls.
MALFORMED_IDENTITY: Final = object()


def _expected_identity(payload: object, text_names, number_names):
    """Read one expected-identity group off a command payload.

    Returns ``MALFORMED_IDENTITY`` when the group is absent, partly supplied
    or unreadable, and otherwise a tuple of the declared values in
    ``text_names + number_names`` order.

    Empty text with a zero number is a COMPLETE identity, not an absent one:
    it is exactly what a Study runtime that has never prepared a block
    publishes, so the caller can compare it like any other.
    """

    names = tuple(text_names) + tuple(number_names)
    values = [_field(payload, name, None) for name in names]
    if any(value is None for value in values):
        return MALFORMED_IDENTITY
    resolved: list[object] = []
    for name, value in zip(names, values):
        if name in tuple(number_names):
            try:
                resolved.append(int(value))
            except (TypeError, ValueError):
                return MALFORMED_IDENTITY
        else:
            resolved.append(str(value))
    return tuple(resolved)


def _declared_keywords(payload: object, name: str):
    """Read one declared keyword collection from a command payload.

    Deliberately does NOT coerce.  An absent or null field means "none
    declared" and becomes an empty tuple, which is the current UI's behaviour.
    Anything else is handed to ``StudyRuntime.prepare`` exactly as supplied so
    that its own fail-closed validation -- in particular its refusal to split
    a bare string into single characters -- remains the single authority on
    what a valid keyword collection is.  Monitor is a nerve, not a validator.
    """

    value = _field(payload, name, None)
    return () if value is None else value


def _receipt_state(receipt: object | None) -> str:
    if receipt is None:
        return "MISSING"
    state = _field(receipt, "state", "")
    return str(getattr(state, "value", state) or "").upper()


def _receipt_id(receipt: object) -> str:
    receipt_id = str(
        _field(receipt, "receipt_id", _field(receipt, "request_id", "")) or ""
    )
    if not receipt_id:
        raise RuntimeError("persistence returned a receipt without receipt_id")
    return receipt_id


def _receipt_error(receipt: object | None) -> str:
    direct = str(_field(receipt, "error", "") or "")
    if direct:
        return " ".join(direct.split())[:240]
    error_type = str(_field(receipt, "error_type", "") or "")
    error_text = str(_field(receipt, "error_text", "") or "")
    return " ".join(f"{error_type}: {error_text}".split())[:240]


def _receipt_result_id(receipt: object) -> int:
    direct = _field(receipt, "result_id")
    if type(direct) is int and direct > 0:
        return direct
    result = _field(receipt, "result")
    if isinstance(result, Mapping):
        result = result.get("event_id", result.get("operational_event_id"))
    elif hasattr(result, "event_id"):
        result = getattr(result, "event_id")
    if type(result) is not int or result <= 0:
        raise RuntimeError("committed trigger receipt has no operational event id")
    return result


def _receipt_session_id(receipt: object) -> int:
    direct = _field(receipt, "session_id")
    if type(direct) is int and direct > 0:
        return direct
    result = _field(receipt, "result")
    if isinstance(result, Mapping):
        result = result.get("session_id")
    elif isinstance(result, tuple) and result:
        result = result[0]
    elif hasattr(result, "session_id"):
        result = getattr(result, "session_id")
    if type(result) is not int or result <= 0:
        raise RuntimeError("committed session receipt has no session id")
    return result


def _fact_kind(fact: object) -> str:
    return str(_field(fact, "kind", _field(fact, "event", "")) or "").upper()


def _safe_telemetry_text(value: object) -> str:
    return " ".join(str(value or "").split())[:MAX_TELEMETRY_TEXT]


def _publish(queue_target, payload: Mapping[str, object]) -> bool:
    """Never let the monitor wait for the Control Station."""

    if queue_target is None:
        return False
    try:
        queue_target.put_nowait(dict(payload))
        return True
    except AttributeError:
        try:
            queue_target.put(dict(payload), block=False)
            return True
        except (AttributeError, queue.Full):
            return False
    except queue.Full:
        return False


def _telemetry(
    queue_target,
    kind: str,
    *,
    observation: ForegroundObservation | None = None,
    message: object = "",
    app_override: str = "",
    **facts: object,
) -> bool:
    """Publish one telemetry item without changing domain truth.

    ``app_override`` is presentation metadata only.  Activity telemetry may use
    a platform label already proved by certified browser evidence (for example
    ``YouTube``) instead of exposing only the browser process name (``chrome``).
    It never participates in classification, Resource Intent, Trigger or SINE.
    """

    display_app = str(app_override or "").strip()
    if not display_app:
        display_app = observation.process_name if observation else "MYELIN"
    payload: dict[str, object] = {
        "time": _utc_now(),
        "kind": str(kind),
        "app": display_app,
        "title": observation.window_title if observation else "",
        "message": _safe_telemetry_text(message),
    }
    payload.update(facts)
    return _publish(queue_target, payload)


def _activity_display_app(context: MonitorContext) -> str:
    """Return a human-readable factual foreground label for telemetry only.

    A certified same-sample Windows app fact takes precedence, regardless
    of which organ owns the moment.  No episode memory is consulted.
    Browser platform names are used only when the exact foreground browser
    sample has an authoritative host read.  Window-title text is deliberately
    not used to decide platform identity.  A certified same-sample native
    Messaging identity (Resource Intent's canonical process, not the raw
    Windows variant) is used next, so "whatsapp.root" still projects as
    "WhatsApp" here even though it never becomes a second alias table.  If no
    certified platform label is available, this falls back to the observed
    process identity.
    """

    from COSINE.cosine import EvidenceSource, PLATFORM_LABELS

    platform = _field(context, "cosine_platform")
    if _field(platform, "source") is EvidenceSource.WINDOWS_APP:
        label = PLATFORM_LABELS.get(_field(platform, "platform_key", ""), "")
        if label:
            return label

    browser_snapshot = context.browser_evidence
    browser_evidence = _field(browser_snapshot, "evidence")
    if bool(_field(browser_snapshot, "host_authoritative", False)):
        label = str(_field(browser_evidence, "platform_label", "") or "").strip()
        if label:
            return label
        host = str(_field(browser_evidence, "certified_host", "") or "").strip().casefold()
        if host:
            return host.removeprefix("www.")

    from CORE_ENGINE.resource_intent import ResourceSurface

    verdict = _field(context.resource_intent, "verdict")
    resource_identity = _field(verdict, "resource_identity")
    if _field(resource_identity, "surface", None) is ResourceSurface.MESSAGING:
        canonical_process = str(
            _field(resource_identity, "process_name", "") or ""
        ).strip().casefold()
        label = MESSAGING_PROCESS_LABELS.get(canonical_process, "")
        if label:
            return label

    process = str(context.foreground.process_name or "").strip().casefold()
    if process.endswith(".exe"):
        process = process[:-4]
    friendly = {
        "code": "VS Code",
        "winword": "Word",
        "excel": "Excel",
        "powerpnt": "PowerPoint",
        "chrome": "Chrome",
        "msedge": "Edge",
        "firefox": "Firefox",
        "python": "Python",
        "searchhost": "Windows Search",
    }
    return friendly.get(process, process or "Unknown")


def _enum_text(value: object) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _study_app_category_metadata(
    context: MonitorContext,
    blacklist_result: object | None,
    *,
    session_id: object,
) -> dict[str, object]:
    """Project a display-only app category from one coherent monitor sample.

    The projection is deliberately downstream of Resource Intent, Blacklist and
    certified COSINE identity.  It never changes those authorities and fails
    closed when their resource/session/observation identities do not agree.
    Window-title text and prior telemetry rows are never consulted.
    """

    from CORE_ENGINE.blacklist import SurfaceClass
    from CORE_ENGINE.resource_intent import (
        IntentReason,
        NORMAL_FOCUS_SURFACES,
        ResourceSurface,
        ResourceObservation,
        build_observation,
        observation_token as source_observation_token,
    )

    foreground = context.foreground
    resource_snapshot = context.resource_intent
    verdict = _field(resource_snapshot, "verdict")
    resource_identity = _field(verdict, "resource_identity")

    try:
        parent_session_id = int(session_id)
        observation_sequence = int(_field(foreground, "sequence", 0) or 0)
        observed_monotonic_ns = int(
            _field(foreground, "observed_monotonic_ns", 0) or 0
        )
        process_id = int(_field(foreground, "process_id", 0) or 0)
        hwnd = int(_field(foreground, "hwnd", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        parent_session_id = 0
        observation_sequence = 0
        observed_monotonic_ns = 0
        process_id = 0
        hwnd = 0

    process_name = str(_field(foreground, "process_name", "") or "").strip().casefold()
    process_name = process_name.removesuffix(".exe")
    resource_key = str(_field(resource_identity, "stable_key", "") or "")
    study_context = str(_field(verdict, "study_context_token", "") or "")
    observation_token = str(_field(verdict, "observation_token", "") or "")
    canonical_process = str(_field(resource_identity, "process_name", "") or "")
    source_observation = _field(resource_snapshot, "observation")
    # Rejoin existing facts with the original identity authority. This does not
    # sample foreground/browser or classify again and does not copy an alias map.
    coherent_source = bool(
        isinstance(source_observation, ResourceObservation)
        and source_observation == build_observation(
            foreground, context.browser_evidence,
            cosine_owned=context.cosine_owned,
            certified_ott_platform_key=str(
                _field(_field(context, "cosine_platform"), "platform_key", "") or ""
            ),
        )
        and source_observation_token(source_observation) == observation_token
        and source_observation.process_name == canonical_process
        and _field(resource_identity, "hwnd") == hwnd
    )
    surface = _field(resource_identity, "surface", ResourceSurface.UNKNOWN)
    reasons = frozenset(_field(verdict, "positive_reason_codes", ()) or ()) | frozenset(
        _field(verdict, "negative_reason_codes", ()) or ()
    )

    def result(
        category: str = "",
        label: str = "",
        *,
        source: str,
        reason: str,
        evidence_available: bool,
    ) -> dict[str, object]:
        return {
            "schema_version": STUDY_APP_CATEGORY_SCHEMA_VERSION,
            "session_id": parent_session_id,
            "resource_key": resource_key,
            "study_context_token": study_context,
            "observation_token": observation_token,
            "observation_sequence": observation_sequence,
            "observed_monotonic_ns": observed_monotonic_ns,
            "process_name": process_name,
            "canonical_process_name": canonical_process,
            "source_observation": source_observation if coherent_source else None,
            "process_id": process_id,
            "hwnd": hwnd,
            "category": category,
            "label": label,
            "source": source,
            "reason": reason,
            "evidence_available": bool(evidence_available),
        }

    blacklist_verdict = _field(blacklist_result, "verdict")
    blacklist_source = _field(blacklist_result, "source_identity")
    try:
        blacklist_sequence = int(
            _field(blacklist_result, "observation_sequence", -1)
        )
        blacklist_process_id = int(_field(blacklist_source, "process_id", 0) or 0)
        blacklist_hwnd = int(_field(blacklist_source, "hwnd", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        blacklist_sequence = -1
        blacklist_process_id = 0
        blacklist_hwnd = 0
    blacklist_process = str(
        _field(blacklist_source, "process_name", "") or ""
    ).strip().casefold().removesuffix(".exe")
    blacklist_resource_key = str(
        _field(blacklist_result, "resource_key", "") or ""
    )

    identity_complete = bool(
        coherent_source
        and parent_session_id > 0
        and observation_sequence > 0
        and observed_monotonic_ns > 0
        and process_id > 0
        and hwnd > 0
        and process_name
        and resource_key
        and observation_token
        and bool(_field(resource_snapshot, "fresh", False))
        and blacklist_result is not None
        and blacklist_sequence == observation_sequence
        and blacklist_resource_key == resource_key
        and blacklist_process == process_name
        and blacklist_process_id == process_id
        and blacklist_hwnd == hwnd
    )
    if not identity_complete:
        return result(
            source="identity_guard",
            reason="incomplete_or_mismatched_observation",
            evidence_available=False,
        )
    if reasons.intersection(
        {
            IntentReason.STALE_OBSERVATION.value,
            IntentReason.EMPTY_OBSERVATION.value,
        }
    ):
        return result(
            source="resource_intent",
            reason="stale_or_empty_observation",
            evidence_available=False,
        )

    active_study = bool(
        context.study_owned
        and study_context
        and not reasons.intersection(
            {
                IntentReason.NO_ACTIVE_STUDY_BLOCK.value,
                IntentReason.STUDY_PAUSED.value,
                IntentReason.APPROVED_BREAK.value,
            }
        )
    )
    if active_study and _enum_text(_field(verdict, "classification", "")).upper() == "STUDY_ALIGNED":
        return result(
            "STUDY", "[STUDY]", source="resource_intent",
            reason="current_study_alignment", evidence_available=True,
        )

    cosine_platform = _field(context, "cosine_platform")
    if cosine_platform is not None:
        cosine_process = str(
            _field(cosine_platform, "process_name", "") or ""
        ).strip().casefold().removesuffix(".exe")
        try:
            cosine_process_id = int(
                _field(cosine_platform, "process_id", 0) or 0
            )
            cosine_hwnd = int(_field(cosine_platform, "hwnd", 0) or 0)
            cosine_observed_ns = int(
                _field(cosine_platform, "observed_monotonic_ns", 0) or 0
            )
        except (TypeError, ValueError, OverflowError):
            cosine_process_id = 0
            cosine_hwnd = 0
            cosine_observed_ns = 0
        cosine_matches = bool(
            str(_field(cosine_platform, "platform_key", "") or "")
            and cosine_process == process_name
            and cosine_process_id == process_id
            and cosine_hwnd == hwnd
            and cosine_observed_ns == observed_monotonic_ns
        )
        if not cosine_matches:
            return result(
                source="cosine",
                reason="certified_ott_identity_mismatch",
                evidence_available=False,
            )
        return result(
            "OTT",
            "[OTT]",
            source="cosine",
            reason="certified_current_ott_platform",
            evidence_available=True,
        )

    blacklist_surface = _field(blacklist_verdict, "surface_class")
    if (
        surface is ResourceSurface.MESSAGING
        or blacklist_surface is SurfaceClass.MESSAGING
    ):
        return result(
            "MESSAGING",
            "[MESSAGING]",
            source="resource_intent_blacklist",
            reason="current_messaging_authority",
            evidence_available=True,
        )

    managed_platform_key = str(
        _field(blacklist_verdict, "platform_key", "") or ""
    )
    if managed_platform_key:
        return result(
            "SOCIAL",
            "[SOCIAL]",
            source="blacklist",
            reason="current_managed_platform_identity",
            evidence_available=True,
        )

    if surface in {
        ResourceSurface.SOCIAL,
        ResourceSurface.YOUTUBE_WATCH,
        ResourceSurface.YOUTUBE_OTHER,
        ResourceSurface.YOUTUBE_SHORTS,
    }:
        return result(
            "SOCIAL",
            "[SOCIAL]",
            source="resource_intent",
            reason="current_managed_social_surface",
            evidence_available=True,
        )
    if surface is ResourceSurface.GAMING:
        return result(
            "GAMING",
            "[GAMING]",
            source="resource_intent",
            reason="current_gaming_surface",
            evidence_available=True,
        )
    if surface is ResourceSurface.COSINE:
        return result(
            source="resource_intent",
            reason="ott_surface_without_matching_current_certification",
            evidence_available=False,
        )

    if surface in NORMAL_FOCUS_SURFACES:
        focus_web_certified = bool(
            surface is not ResourceSurface.FOCUS_WEB
            or _field(resource_identity, "browser_evidence_certified", False)
        )
        if active_study and focus_web_certified:
            return result(
                "STUDY_FOCUS",
                "[STUDY FOCUS]",
                source="resource_intent_focus_catalog",
                reason="certified_focus_resource_during_active_study",
                evidence_available=True,
            )
        return result(
            source="resource_intent_focus_catalog",
            reason="focus_resource_outside_active_certified_study",
            evidence_available=False,
        )

    browser_snapshot = context.browser_evidence
    if bool(_field(browser_snapshot, "supported_browser", False)) and (
        IntentReason.BROWSER_EVIDENCE_UNAVAILABLE.value in reasons
        or not bool(_field(resource_identity, "browser_evidence_certified", False))
    ):
        return result(
            source="browser",
            reason="unresolved_or_uncertified_browser_surface",
            evidence_available=False,
        )

    return result(
        "ACTIVITY",
        "[ACTIVITY]",
        source="observed_foreground",
        reason="fresh_ordinary_resource_after_special_category_checks",
        evidence_available=True,
    )


def _duration_mmss(seconds: object) -> str:
    try:
        value = max(0, int(float(seconds)))
    except (TypeError, ValueError, OverflowError):
        return "--:--"
    minutes, secs = divmod(value, 60)
    return f"{minutes:02d}:{secs:02d}"


def _duration_human(seconds: object) -> str:
    try:
        value = max(0, int(float(seconds)))
    except (TypeError, ValueError, OverflowError):
        value = 0
    minutes, secs = divmod(value, 60)
    return f"{minutes:02d}m {secs:02d}s"


def _authoritative_seconds(seconds: object) -> str:
    """Format an authority-supplied interval without inventing a fallback."""

    try:
        value = float(seconds)
    except (TypeError, ValueError, OverflowError):
        return "authoritative interval unavailable"
    if not math.isfinite(value) or value < 0.0:
        return "authoritative interval unavailable"
    return f"{value:g} s"


def _short_episode_id(value: object) -> str:
    episode = str(value or "").strip()
    if not episode:
        return "MIRL-UNKNOWN"
    tail = episode.rsplit("-", 1)[-1][:8].upper()
    return f"MIRL-{tail}" if tail else "MIRL-UNKNOWN"


def _build_services(*, profile_type: str) -> MonitorServices:
    """Compose the eight real authorities once.

    INSTRUCTION: these imports are intentionally local.  Importing
    ``CORE_ENGINE.monitor`` must never create a database, popup or runtime.
    The named constructors are the contracts the remaining clean files will
    implement.
    """

    from COSECANT_STUDY_MODE.cosecant import CosecantRuntime
    from COSECANT_STUDY_MODE.study import StudyRuntime
    from CORE_ENGINE.blacklist import BlacklistAuthority as Blacklist
    from CORE_ENGINE.browser import BrowserEvidenceAuthority
    from CORE_ENGINE.resource_intent import ResourceIntentAuthority as Intent
    from CORE_ENGINE.trigger import TriggerAuthority as Trigger
    from COSINE.cosine import CosineRuntime
    from MINE.mine import MineRuntime
    from MIRL.mirl import MirlAuthority as Mirl
    from PERSISTENCE.storage import EngineStorage
    from SINE.normal_break import NormalBreakAuthority as NormalBreak
    from SINE.sine import SineAuthority as Sine

    storage = EngineStorage()
    intent = Intent()
    return MonitorServices(
        browser=BrowserEvidenceAuthority(),
        resource_intent=intent,
        blacklist=Blacklist(),
        trigger=Trigger(profile_type=profile_type),
        sine=Sine(storage=storage),
        cosine=CosineRuntime(event_sink=storage),
        mine=MineRuntime(event_sink=storage),
        mirl=Mirl(),
        study=StudyRuntime(),
        cosecant=CosecantRuntime(context_authority=intent),
        normal_break=NormalBreak(),
        storage=storage,
    )


class WindowsMonitorCoordinator:
    """One ordered, interruptible monitoring session."""

    def __init__(
        self,
        *,
        profile_type: str,
        services: MonitorServices,
        foreground_reader: WindowsForegroundReader,
        stop_event,
        pause_event,
        ready_event,
        loop_stopped_event,
        cleanup_complete_event,
        telemetry_queue,
        command_queue,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
    ) -> None:
        if not str(profile_type).strip():
            raise ValueError("profile_type must not be empty")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.profile_type = str(profile_type)
        self.services = services
        self._mine_authority = getattr(services, "mine", None)
        self.foreground_reader = foreground_reader
        self.stop_event = stop_event
        self.pause_event = pause_event
        self.ready_event = ready_event
        self.loop_stopped_event = loop_stopped_event
        self.cleanup_complete_event = cleanup_complete_event
        self.telemetry_queue = telemetry_queue
        self.command_queue = command_queue
        self.poll_seconds = float(poll_seconds)
        # Backend command admission and SINE deadline precedence must read one
        # monotonic authority.  Kept as an instance seam for deterministic
        # external physiology tests; production resolves to time.monotonic_ns.
        self._monotonic_ns = time.monotonic_ns
        self._init_secant_connection()

        # Phase 2B: Mom owns exactly one legal relationship with the thin
        # sibling-continuity layer.  The layer owns its 120-second clock;
        # Monitor must never mirror that timer, source, target, or pause state.
        self._handover = HandoverLayer()

        self.session_id: int | None = None
        self._pending_trigger: PendingTriggerWorkflow | None = None
        self._pending_study_start: dict | None = None
        self._uncommitted_mirl_events: tuple[object, ...] = ()
        self._uncommitted_sine_facts: list[object] = []
        self._durable_mirl_closes: dict[tuple, str] = {}
        self._durable_sine_terminals: dict[str, str] = {}
        self._durable_sine_admissions: set[tuple[str, int]] = set()
        self._durable_popup_closes: set[tuple[str, str]] = set()
        self._durable_sine_fact_keys: set[tuple] = set()
        self._mirl_consumed_sine_keys: set[tuple] = set()
        # One parked break request awaiting a real observation (C5).
        self._pending_break_seconds: int | None = None
        #: Expected (Study block_id, generation) carried by a parked GUI break
        #: request, re-checked at admission.  None for identity-free commands.
        self._pending_break_study_identity: tuple[str, int] | None = None
        # A Control Station click necessarily foregrounds MYELIN before the
        # worker consumes the command.  Preserve only the last exact Study
        # resource which already passed Browser + Resource Intent authority;
        # this is evidence memory, never a second classifier.
        self._myelin_process_id = os.getpid()
        self._break_eligible_study_target: BreakEligibleStudyTarget | None = None
        self._last_foreground_identity: tuple[object, ...] | None = None
        self._last_red_state: bool | None = None
        self._last_blacklist_console_signature: tuple[object, ...] | None = None
        self._last_cosecant_intent_mismatch_signature: tuple[object, ...] | None = None
        self._last_browser_diagnostic_signature: tuple[object, ...] | None = None
        self._last_activity_classification_signature: tuple[object, ...] | None = None
        self._pending_dwell_telemetry: dict[str, object] | None = None
        self._messaging_dwell_key: str = ""
        self._messaging_dwell_started_ns: int = -1
        self._messaging_dwell_last_ns: int = -1
        self._cosine_study_preemption_pending = False
        self._last_study_completion_signature: tuple[str, int] | None = None
        self._last_mirl_console_signature: tuple[object, ...] | None = None
        # Phase 1I.  The COSINE live view is published every cycle and replaced
        # in place, so it never spams the UI.  Meaningful COSINE transitions,
        # however, belong in the append-only Live Telemetry feed exactly once
        # each -- this remembers the last published transition signature so a
        # countdown that merely ticks cannot become a hundred history rows.
        self._last_cosine_transition_signature: tuple[object, ...] | None = None
        # Same presentation principle for MINE (Phase 4 Case A): remember the
        # last published MINE transition signature so a countdown-only poll
        # cannot become a Live Telemetry row.
        self._last_mine_transition_signature: tuple[object, ...] | None = None
        self._emergency_requested = False
        self._emergency_durable = False
        self._cleanup_errors: list[str] = []

        # Phase-6 profile-learning state is session-local.  The exact lambda
        # loaded at Start is frozen for this session; verified recovery may
        # create new observations, but those observations can update only the
        # NEXT session after this session row has durably closed.
        self._profile_learning_key = ""
        self._session_decay_rate_per_minute: float | None = None
        self._session_personalization_factor: float = 1.0
        self._observed_lambda_estimates: list[object] = []
        self._learned_candidate_uids: set[str] = set()
        self._normal_break_learning_ineligible_candidate_uids: set[str] = set()
        self._normal_break_resume_fault = False

    def run(self) -> None:
        """Initialize, monitor, and always perform ordered cleanup."""

        try:
            self._start_session()
            if self.stop_event.is_set():
                return
            self.ready_event.set()
            _telemetry(
                self.telemetry_queue,
                "session",
                message="Core Engine monitoring started",
                session_id=self.session_id,
            )
            self._monitor_loop()
        finally:
            self.loop_stopped_event.set()
            cleanup_ok = self._cleanup()
            if cleanup_ok:
                self.cleanup_complete_event.set()
            if self._emergency_requested:
                _telemetry(
                    self.telemetry_queue,
                    "emergency_completed",
                    message=(
                        "Emergency shutdown completed"
                        if cleanup_ok and self._emergency_durable
                        else "Emergency shutdown could not be fully confirmed"
                    ),
                    exit_permitted=bool(cleanup_ok and self._emergency_durable),
                )

    def _start_session(self) -> None:
        from PROFILES.profiles import PROFILE_KEYS

        learning_key = str(self.profile_type or "").strip().lower()
        if learning_key not in PROFILE_KEYS:
            raise RuntimeError("monitor profile has no canonical learning identity")

        receipt = self.services.storage.open_monitor_session(
            profile_type=self.profile_type
        )
        committed = self._wait_for_commit(
            receipt,
            timeout_seconds=STARTUP_PERSISTENCE_TIMEOUT_SECONDS,
            operation="session open",
        )
        self.session_id = _receipt_session_id(committed)
        if not self.services.cosine.bind_parent_session(self.session_id):
            raise RuntimeError("COSINE rejected the durable Monitor parent session")
        if self._mine_authority is None:
            from MINE.mine import MineRuntime
            self._mine_authority = MineRuntime(event_sink=self.services.storage)
        if not self._mine_authority.bind_parent_session(self.session_id):
            raise RuntimeError("MINE rejected the durable Monitor parent session")

        # Load only committed learning after the new session row is durable.
        # Missing learning remains None; monitor never manufactures a fallback.
        learning_state = self.services.storage.load_profile_learning(
            profile_key=learning_key
        )
        stored_key = str(_field(learning_state, "profile_key", "") or "").strip().lower()
        if stored_key != learning_key:
            raise RuntimeError("profile learning state identity does not match active profile")

        # PROVENANCE GATE -- session composition decides eligibility.
        #
        # Storage reports what is stored; MBRM does maths on already-valid
        # evidence; deciding whether a stored generation may drive THIS session
        # is a composition question and belongs here.
        #
        # A stored row only adapts SINE when its model_version is exactly the
        # generation whose Tr semantics this code understands.  Anything else --
        # the legacy v1 default, an empty string, an unknown or malformed marker
        # from a future or hand-edited row -- is scientifically ineligible and
        # falls back to the static baseline (F = 1.0), the same state a fresh
        # profile is in.  MYELIN never guesses a generation, never reinterprets
        # a v1 latency as v2, and never tries to reconstruct an onset by
        # subtracting the verification window.
        #
        # This is deliberately NON-DESTRUCTIVE: the old row is left exactly as
        # it is. Historical evidence stays readable, it simply stops driving
        # future timing. The first completed session that produces real
        # onset-based evidence re-stamps the row through
        # update_profile_learning_session and the profile becomes eligible
        # again on the session after that.
        from PERSISTENCE.storage import PROFILE_LEARNING_MODEL_VERSION

        stored_model_version = str(
            _field(learning_state, "model_version", "") or ""
        ).strip()
        learned_lambda = _field(learning_state, "learned_lambda", None)
        learning_ineligible_reason = ""
        if (
            learned_lambda is not None
            and stored_model_version != PROFILE_LEARNING_MODEL_VERSION
        ):
            learning_ineligible_reason = (
                "incompatible_learning_model_version"
                if stored_model_version
                else "missing_learning_model_version"
            )
            learned_lambda = None
        if learned_lambda is not None:
            learned_lambda = float(learned_lambda)
            if not math.isfinite(learned_lambda) or learned_lambda <= 0.0:
                raise RuntimeError("stored profile lambda is not finite and positive")

        self._profile_learning_key = learning_key
        self._session_decay_rate_per_minute = learned_lambda
        self._observed_lambda_estimates.clear()
        self._learned_candidate_uids.clear()
        self._normal_break_learning_ineligible_candidate_uids.clear()
        self._normal_break_resume_fault = False

        # MBRM / Ebbinghaus policy boundary. ``learned_lambda`` remains the
        # previous eligible session's factual learned recovery-rate parameter.
        # It is retained for Ebbinghaus/MBRM learning and telemetry.
        #
        # No implementation authority may invent a reference return time, a
        # reference lambda, or fixed F bounds. Unapproved calibration values
        # were removed. Therefore a learned
        # lambda is NOT enough by itself to authorize personalized runtime
        # timing. Until policy supplies an explicitly authorized reference,
        # SINE must fail closed to the exact static baseline (F = 1.0).
        #
        # The factor mathematics remains available in
        # CORE_ENGINE.trigger.mbrm_session_personalization as
        # F = lambda_user / lambda_ref. This monitor deliberately does not call
        # it without an authorized lambda_ref.
        session_timing = None
        if learned_lambda is not None:
            source_session_id = _field(learning_state, "last_learning_session_id", None)
            if (
                type(source_session_id) is not int
                or source_session_id <= 0
                or source_session_id >= self.session_id
            ):
                raise RuntimeError(
                    "learned profile lambda has no valid prior session provenance"
                )
            learned_return_latency_seconds = _field(
                learning_state, "learned_return_latency_seconds", None
            )
            if learned_return_latency_seconds is None:
                raise RuntimeError(
                    "learned profile lambda has no matching return-latency evidence"
                )
            learned_return_latency_seconds = float(learned_return_latency_seconds)
            if (
                not math.isfinite(learned_return_latency_seconds)
                or learned_return_latency_seconds <= 0.0
            ):
                raise RuntimeError(
                    "stored profile return latency is not finite and positive"
                )

        self._session_personalization_factor = 1.0

        # Initialize downstream authorities only after the session row and the
        # profile-learning snapshot are known.  Trigger freezes this exact value
        # for the whole session; later recovery cannot mutate it in-place.
        # With no policy-authorized reference, the frozen factor is exactly 1.0
        # for Blacklist and SINE. Learned Ebbinghaus state remains available but
        # cannot change timing until an authorized reference exists.
        self.services.browser.start_session()
        self.services.resource_intent.start_session(profile_type=self.profile_type)
        self.services.blacklist.start_session(
            personalization_factor=self._session_personalization_factor,
        )
        self.services.trigger.start_session(
            session_id=self.session_id,
            profile_type=self.profile_type,
            decay_rate_per_minute=learned_lambda,
        )
        self.services.mirl.start_session(
            session_id=self.session_id,
            profile_type=self.profile_type,
        )
        self.services.sine.start_session(
            session_id=self.session_id,
            profile_type=self.profile_type,
            timing=session_timing,
        )
        _telemetry(
            self.telemetry_queue,
            "profile_learning_loaded",
            message=(
                "Profile learning loaded; Ebbinghaus lambda retained, but SINE personalization is withheld because no policy-authorized reference exists"
                if learned_lambda is not None
                else (
                    "Stored profile learning was produced by an incompatible Tr "
                    "generation and is ignored; static SINE baseline (F = 1.0)"
                    if learning_ineligible_reason
                    else "Profile has no learned lambda yet; static/default timing remains eligible"
                )
            ),
            profile_key=learning_key,
            learned=learned_lambda is not None,
            lambda_snapshot=learned_lambda,
            learning_model_version=stored_model_version,
            expected_learning_model_version=PROFILE_LEARNING_MODEL_VERSION,
            learning_ineligible_reason=learning_ineligible_reason,
            valid_sessions=int(_field(learning_state, "valid_session_count", 0) or 0),
            valid_episodes=int(_field(learning_state, "valid_episode_count", 0) or 0),
            personalization_factor=self._session_personalization_factor,
        )
        self._publish_startup_banner(learning_state, learned_lambda)


    def _console_banner(self, line: object) -> None:
        _telemetry(self.telemetry_queue, "console_banner", message=line)

    def _console_history(
        self,
        line: object,
        observation: ForegroundObservation | None = None,
    ) -> None:
        _telemetry(
            self.telemetry_queue,
            "console_history",
            observation=observation,
            message=line,
        )

    def _publish_startup_banner(self, learning_state: object, learned_lambda: float | None) -> None:
        from PERSISTENCE.database import database_path

        lambda_text = f"{learned_lambda:.6f}" if learned_lambda is not None else "NOT LEARNED"
        factor_text = f"{self._session_personalization_factor:.4f}"
        lines = (
            "========================================================",
            "  PROJECT MYELIN - CORE MONITOR",
            "========================================================",
            f"  Profile  : {self.profile_type.upper()}",
            f"  Lambda   : {lambda_text}",
            f"  SINE F   : {factor_text}",
            f"  Session  : {self.session_id}",
            f"  Database : {database_path()}",
            f"  Learning : {int(_field(learning_state, 'valid_session_count', 0) or 0)} sessions / "
            f"{int(_field(learning_state, 'valid_episode_count', 0) or 0)} episodes",
            "========================================================",
            "  Watching for distraction patterns...",
            "",
        )
        for line in lines:
            self._console_banner(line)

    def _finish_handover_for_study(self, now_ns: int) -> HandoverResult:
        """Terminate Mr Hand because factual Dad/Study owns the moment."""

        # Mr Hand owns a processing-time timeline, not observation occurrence time.
        # Keep caller evidence timestamps intact; never clamp or relabel them.
        return self._handover.finish("STUDY_MODE_ACTIVATED", self._monotonic_ns())

    def _publish_handover_result_telemetry(
        self,
        result: HandoverResult,
        observation: ForegroundObservation | None,
    ) -> None:
        """Project an existing Mr Hand result into the two presentation feeds."""

        action = str(_field(result, "action", "") or "").upper()
        if not action or action == "NOOP":
            return

        source = str(_field(result, "source", "") or "")
        target = str(_field(result, "target", "") or "")
        reason = str(_field(result, "reason", "") or "")
        telemetry_queue = getattr(self, "telemetry_queue", None)
        if telemetry_queue is None:
            return

        if action == "STARTED":
            _telemetry(
                telemetry_queue,
                "handover_lifecycle",
                observation=observation,
                feed_text=f"Handing over from {source} to {target}",
                badge="HANDOVER",
                tone="muted",
            )
            _telemetry(
                telemetry_queue,
                "handover_family_signal",
                observation=observation,
                feed_text=f"START · {source} -> {target}",
                badge="MONITOR",
                tone="cyan",
            )
            _telemetry(
                telemetry_queue,
                "handover_family_signal",
                observation=observation,
                feed_text="STARTED",
                badge="HANDOVER",
                tone="muted",
            )
            return

        if action in {"FINISHED", "EXPIRED", "SOURCE_RETURNED"}:
            _telemetry(
                telemetry_queue,
                "handover_lifecycle",
                observation=observation,
                feed_text="Handover finished",
                badge="HANDOVER",
                tone="muted",
            )

        if action == "TARGET_SWITCHED":
            detail_rows = (("HANDOVER", "muted", f"TARGET SWITCHED · {source} -> {target}"),)
        elif action == "FROZEN":
            detail_rows = (("HANDOVER", "muted", "FROZEN · GLOBAL PAUSE"),)
        elif action == "RESUMED":
            detail_rows = (("HANDOVER", "muted", "RESUMED · GLOBAL PAUSE RELEASED"),)
        elif action == "SOURCE_RETURNED":
            detail_rows = (("HANDOVER", "muted", "SOURCE RETURNED"),)
        elif action == "EXPIRED":
            detail_rows = (("HANDOVER", "muted", "EXPIRED"),)
        elif action == "FINISHED" and reason == "STUDY_MODE_ACTIVATED":
            detail_rows = (
                ("STUDY", "green", "STUDY OWNERSHIP ACTIVE"),
                ("HANDOVER", "muted", "FINISHED · STUDY MODE ACTIVATED"),
            )
        elif action == "FINISHED":
            detail_rows = (
                ("HANDOVER", "muted", f"FINISHED · {reason.replace('_', ' ').upper()}"),
            )
        else:
            detail_rows = ()

        for badge, tone, feed_text in detail_rows:
            _telemetry(
                telemetry_queue,
                "handover_family_signal",
                observation=observation,
                feed_text=feed_text,
                badge=badge,
                tone=tone,
            )

    def _publish_handover_live_status(
        self,
        *,
        now_ns: int,
        observation: ForegroundObservation | None,
        territory: str | None,
        study_authority: bool,
        global_pause: bool,
    ) -> None:
        """Publish one replace-in-place view made only from existing facts."""

        handover = getattr(self, "_handover", None)
        if handover is None:
            return
        authority_now_ns = self._monotonic_ns()
        _telemetry(
            self.telemetry_queue,
            "handover_live_status",
            observation=observation,
            live_view={
                "territory": territory,
                "handover": handover.snapshot(authority_now_ns),
                "authority_monotonic_ns": authority_now_ns,
                "observed_monotonic_ns": (
                    observation.observed_monotonic_ns if observation is not None else None
                ),
                "study_authority": bool(study_authority),
                "global_pause": bool(global_pause),
            },
        )

    def _sync_handover_clock(
        self,
        *,
        now_ns: int,
        global_paused: bool,
    ) -> HandoverResult:
        """Give Dad first refusal, then synchronize Mr Hand's ordinary clock.

        Study/COSECANT ownership is stronger than sibling continuity.  If Dad
        already owns the moment, Mom terminates the one Mr Hand relationship
        before Global Pause or the ordinary 120-second clock can advance.
        Otherwise the existing pause/advance physiology is unchanged.
        """

        if self._study_owns_moment():
            return self._finish_handover_for_study(now_ns)

        pause_result = self._handover.set_paused(global_paused, self._monotonic_ns())
        if pause_result.action != "NOOP":
            return pause_result
        if global_paused:
            return pause_result
        return self._handover.advance(self._monotonic_ns())

    def _monitor_loop(self) -> None:
        next_cycle = time.monotonic()
        while not self.stop_event.is_set():
            self._drain_commands()
            if self.stop_event.is_set():
                break
            self._advance_pending_study_start()
            self._connection_tick()
            if self.pause_event.is_set():
                self._capture_study_boundary(gap_reason="GLOBAL_PAUSE")
                # Global Pause inhibits ordinary monitoring cycles, but it is
                # not authority to extend a factual Normal Break deadline.
                # Advance only the independent break clock; no sensing occurs.
                paused_now_ns = time.monotonic_ns()
                handover_clock_result = self._sync_handover_clock(
                    now_ns=paused_now_ns,
                    global_paused=True,
                )
                self._apply_handover_clock_result(
                    handover_clock_result, now_ns=paused_now_ns, observation=None
                )
                self._publish_handover_result_telemetry(
                    handover_clock_result, observation=None
                )
                paused_study_authority = self._study_owns_moment()
                self._publish_handover_live_status(
                    now_ns=paused_now_ns,
                    observation=None,
                    territory=None,
                    study_authority=paused_study_authority,
                    global_pause=True,
                )
                self.services.cosine.set_global_paused(True, paused_now_ns)
                mine_authority = getattr(self, "_mine_authority", None)
                if mine_authority is not None:
                    mine_authority.set_global_paused(True, paused_now_ns)
                # I-062.  Publish COSINE PRESENTATION TRUTH while paused.  This
                # is a projection of the already-paused CosineRuntime and
                # nothing else.  No sensing of any kind happens here: the
                # foreground is not sampled, the browser is not read, no
                # resource is classified, Trigger and SINE do not run, and no
                # second clock is created -- the snapshot is taken at the
                # paused_now_ns this branch already established.  Without this
                # the live card and the transition feed could never observe
                # global_paused=True, because the paused branch deliberately
                # never reaches the full live-view publication.
                paused_cosine_snapshot = self.services.cosine.snapshot(
                    now_ns=paused_now_ns
                )
                _telemetry(
                    self.telemetry_queue,
                    "cosine_live_status",
                    observation=None,
                    live_view=paused_cosine_snapshot,
                )
                self._publish_cosine_transition(paused_cosine_snapshot, None)
                if mine_authority is not None:
                    _telemetry(
                        self.telemetry_queue,
                        "mine_watch_status",
                        observation=None,
                        live_view=mine_authority.snapshot(now_ns=paused_now_ns),
                    )
                self._advance_normal_break(paused_now_ns, None)
                self.stop_event.wait(min(self.poll_seconds, 0.25))
                next_cycle = time.monotonic()
                continue

            resumed_now_ns = time.monotonic_ns()
            handover_clock_result = self._sync_handover_clock(
                now_ns=resumed_now_ns,
                global_paused=False,
            )
            self._apply_handover_clock_result(
                handover_clock_result, now_ns=resumed_now_ns, observation=None
            )
            self._publish_handover_result_telemetry(
                handover_clock_result, observation=None
            )
            self.services.cosine.set_global_paused(False, resumed_now_ns)
            mine_authority = getattr(self, "_mine_authority", None)
            if mine_authority is not None:
                mine_authority.set_global_paused(False, resumed_now_ns)
            observation = self.foreground_reader.observe()
            context = self._classify_observation(observation)
            blacklist_result = self.services.blacklist.observe(context)
            self._reconcile_handover_before_routing(context, blacklist_result)
            self._route_context(context, blacklist_result)
            self._reconcile_handover_after_routing(context)
            self._publish_handover_live_status(
                now_ns=context.foreground.observed_monotonic_ns,
                observation=context.foreground,
                territory=self._sibling_territory(context, blacklist_result),
                study_authority=context.study_owned,
                global_pause=False,
            )
            self._publish_live_views(context, blacklist_result)

            next_cycle += self.poll_seconds
            remaining = next_cycle - time.monotonic()
            if remaining <= 0:
                # A slow cycle does not cause a rapid catch-up loop.
                next_cycle = time.monotonic()
                continue
            while remaining > 0:
                # Service popup actions and their acknowledgements between
                # sensing polls. A 1.5-second command wait against a
                # 1.5-second GUI timeout could falsely reject a clarification
                # that Monitor accepted on its next pass. Sensing itself stays
                # on its original schedule.
                self.stop_event.wait(min(remaining, 0.1))
                if self.stop_event.is_set():
                    break
                self._drain_commands()
                if self._pending_study_start is not None:
                    self._advance_pending_study_start()
                remaining = next_cycle - time.monotonic()

    def _classify_observation(
        self,
        observation: ForegroundObservation,
    ) -> MonitorContext:
        # Browser owns the exact HWND/process/host read. COSINE receives that
        # certified host directly; no downstream title re-detection occurs.
        from COSINE.cosine import certify_platform_evidence

        browser_evidence = self.services.browser.observe(observation)
        cosine_platform = certify_platform_evidence(
            process_name=observation.process_name,
            process_id=observation.process_id,
            hwnd=observation.hwnd,
            observed_monotonic_ns=observation.observed_monotonic_ns,
            browser_authoritative=bool(
                _field(browser_evidence, "host_authoritative", False)
            ),
            certified_host=str(
                _field(browser_evidence, "certified_host", "") or ""
            ),
            window_title=observation.window_title,
            app_identity=_field(observation, "app_identity", None),
        )

        study_owned = self._study_owns_moment()
        preemption_settled = self._settle_study_son_preemption(
            study_owned=study_owned,
            observation=observation,
            cosine_platform=cosine_platform,
        )

        sine_monitor = self.services.sine.monitor_status(
            now_ns=observation.observed_monotonic_ns
        )
        cosine_monitor = self.services.cosine.monitor_status(
            now_ns=observation.observed_monotonic_ns
        )
        protected_red_active = bool(
            self.services.sine.protected_red_active()
            and not bool(_field(sine_monitor, "held", False))
        )
        cosine_owned = bool(
            cosine_platform is not None
            and not study_owned
            and preemption_settled
            and not protected_red_active
        )
        cosine_snapshot = self.services.cosine.snapshot(
            now_ns=observation.observed_monotonic_ns
        )
        cosine_phase = _enum_text(_field(cosine_snapshot, "phase", ""))
        cosine_active = bool(
            not study_owned
            and preemption_settled
            and not protected_red_active
            and not bool(_field(cosine_monitor, "held", False))
            and cosine_phase not in {"", "IDLE", "CLOSED", "SHUTDOWN"}
        )

        # Resource Intent owns Study/idle classification, but it must know
        # when higher-precedence SINE/COSINE authorities currently own the
        # observed surface. These setters do not perform classification.
        self.services.resource_intent.set_protected_red(
            protected_red_active
        )
        self.services.resource_intent.set_cosine_active(cosine_active)
        self.services.resource_intent.set_cosine_resource_owned(
            cosine_owned
        )
        set_ott_identity = getattr(
            self.services.resource_intent,
            "set_certified_ott_platform_key",
            None,
        )
        if callable(set_ott_identity):
            set_ott_identity(
                str(_field(cosine_platform, "platform_key", "") or "")
            )

        intent = self.services.resource_intent.observe(
            foreground=observation,
            browser_evidence=browser_evidence,
        )
        # Capture this exact observation before any replaceable live view exists.
        self._capture_study_boundary(observation)
        self._capture_study_observation_evidence(observation)
        return MonitorContext(
            foreground=observation,
            browser_evidence=browser_evidence,
            resource_intent=intent,
            cosine_platform=cosine_platform,
            cosine_owned=cosine_owned,
            study_owned=study_owned,
        )

    def _capture_study_observation_evidence(self, observation=None, *, accepted=False, request_id="", applied_ns=None):
        """Transport authority history before UI replacement, without making decisions."""
        try:
            read = getattr(self.services.resource_intent, "study_observation_evidence", None)
            capture = getattr(self.services.storage, "capture_study_observation_evidence", None)
            if not callable(read) or not callable(capture):
                return
            if observation is not None:
                if self._study_world != "STUDY" or self._study_break or self.pause_event.is_set():
                    return
                evidence = read(expected_observation_ns=observation.observed_monotonic_ns,
                    expected_sequence=observation.sequence)
            elif accepted and request_id:
                evidence = read()
            else:
                return
            if evidence is not None:
                capture(session_id=self.session_id, authority_json=evidence,
                    request_id=request_id, applied_ns=applied_ns)
        except Exception:
            pass  # Missing extension evidence stays unresolved; authority is unaffected.

    def _end_study_foreground_span(self, reason):
        """Observation-only lifecycle fence; never supplies a duration endpoint."""
        try:
            close = getattr(self.services.storage, "end_study_resource_interval", None)
            if callable(close):
                close(reason)
        except Exception:
            pass  # An evidence extension cannot influence organ decisions.

    def _capture_study_boundary(self, observation=None, *, gap_reason=""):
        """Publish existing factual evidence only; never participate in routing."""
        try:
            capture = getattr(self.services.storage, "capture_study_resource_observation", None)
            if not callable(capture):
                return
            sample = None
            if observation is not None:
                if self._study_world == "STUDY" and not self._study_break and not self.pause_event.is_set():
                    sample = self.services.resource_intent.study_sample(
                        expected_observation_ns=observation.observed_monotonic_ns,
                        expected_sequence=observation.sequence)
                else:
                    gap_reason = "INACTIVE_STUDY"
            capture(session_id=self.session_id, sample=sample,
                observed_at_utc=observation.observed_wall_time_utc if observation is not None else "",
                max_interval_ns=STUDY_CONTINUITY_MAX_GAP_NS, gap_reason=gap_reason)
        except Exception:
            # A failed sample read is an evidence gap, never an organ decision.
            try:
                capture(session_id=self.session_id, sample=None, gap_reason="CAPTURE_ERROR")
            except Exception:
                pass

    def _son_authority(self, son: str):
        if son == "SINE":
            return self.services.sine
        if son == "COSINE":
            return self.services.cosine
        if son == "MINE":
            return getattr(self, "_mine_authority", None)
        raise ValueError("son must be SINE, COSINE, or MINE")

    def _son_status(self, son: str, now_ns: int):
        authority = self._son_authority(son)
        if authority is None:
            return None
        return authority.monitor_status(now_ns=now_ns)

    def _drain_monitor_son_outputs(
        self,
        son: str,
        *,
        now_ns: int,
        observation: ForegroundObservation | None,
    ) -> None:
        if son == "SINE":
            self._route_sine_batch(
                self.services.sine.advance(now_monotonic_ns=now_ns), observation
            )
            return
        authority = self._son_authority(son)
        if authority is None:
            return
        for effect in tuple(authority.drain_effects() or ()):
            if son == "COSINE":
                self._route_cosine_effect(effect, observation)
            else:
                self._route_mine_effect(effect, observation)

    def _monitor_hold_son(
        self,
        son: str,
        episode_key: object,
        *,
        now_ns: int,
        observation: ForegroundObservation | None,
    ) -> bool:
        authority = self._son_authority(son)
        if authority is None:
            return False
        accepted = bool(authority.monitor_hold(episode_key=episode_key, now_ns=now_ns))
        self._drain_monitor_son_outputs(
            son, now_ns=now_ns, observation=observation
        )
        return accepted

    def _monitor_resume_son(
        self,
        son: str,
        episode_key: object,
        *,
        now_ns: int,
        observation: ForegroundObservation | None,
    ) -> bool:
        authority = self._son_authority(son)
        if authority is None:
            return False
        accepted = bool(authority.monitor_resume(episode_key=episode_key, now_ns=now_ns))
        self._drain_monitor_son_outputs(
            son, now_ns=now_ns, observation=observation
        )
        return accepted

    def _monitor_terminate_son(
        self,
        son: str,
        episode_key: object,
        *,
        now_ns: int,
        observation: ForegroundObservation | None,
    ) -> bool:
        authority = self._son_authority(son)
        if authority is None:
            return False
        accepted = bool(authority.monitor_terminate(episode_key=episode_key, now_ns=now_ns))
        self._drain_monitor_son_outputs(
            son, now_ns=now_ns, observation=observation
        )
        return accepted

    def _apply_handover_clock_result(
        self,
        result: HandoverResult,
        *,
        now_ns: int,
        observation: ForegroundObservation | None,
    ) -> None:
        """Apply only terminal clock outcomes; Mr Hand still owns the clock."""

        if result.action != "EXPIRED":
            return
        if result.source is None or result.source_episode_key is None:
            raise RuntimeError("expired handover lost its protected source identity")
        self._monitor_terminate_son(
            result.source,
            result.source_episode_key,
            now_ns=now_ns,
            observation=observation,
        )

    @staticmethod
    def _sibling_territory(
        context: MonitorContext,
        blacklist_result: object,
    ) -> str | None:
        """Map Mom's already-certified current fact to one son, or no sibling."""

        if context.study_owned:
            return None
        from CORE_ENGINE.resource_intent import ResourceSurface

        verdict = _field(context.resource_intent, "verdict")
        identity = _field(verdict, "resource_identity")
        surface = _field(identity, "surface")
        if surface is ResourceSurface.MESSAGING:
            return "MINE"
        if context.cosine_platform is not None:
            return "COSINE"
        blacklist_verdict = _field(blacklist_result, "verdict")
        if bool(_field(blacklist_verdict, "actionable", False)):
            return "SINE"
        return None

    @staticmethod
    def _handover_exit_reason(context: MonitorContext) -> str:
        from CORE_ENGINE.resource_intent import NORMAL_FOCUS_SURFACES

        verdict = _field(context.resource_intent, "verdict")
        identity = _field(verdict, "resource_identity")
        surface = _field(identity, "surface")
        if surface in NORMAL_FOCUS_SURFACES:
            return "FOCUS"
        return "NEUTRAL"

    def _reconcile_handover_before_routing(
        self,
        context: MonitorContext,
        blacklist_result: object = None,
    ) -> None:
        """Start/return/retarget the one relationship before sons consume this fact."""

        if context.study_owned:
            # Observation-level second fence: sons are already preempted by
            # Dad through _settle_study_son_preemption(); this factual
            # ownership also ends Mr Hand, idempotently if the earlier
            # clock-junction fence already did so this cycle.
            result = self._finish_handover_for_study(
                context.foreground.observed_monotonic_ns
            )
            self._publish_handover_result_telemetry(result, context.foreground)
            return
        now_ns = context.foreground.observed_monotonic_ns
        clock_result = self._handover.advance(self._monotonic_ns())
        self._apply_handover_clock_result(
            clock_result, now_ns=now_ns, observation=context.foreground
        )
        self._publish_handover_result_telemetry(clock_result, context.foreground)
        snapshot = self._handover.snapshot(self._monotonic_ns())
        territory = self._sibling_territory(context, blacklist_result)

        if snapshot.active:
            source = str(snapshot.source or "")
            target = str(snapshot.target or "")
            key = snapshot.source_episode_key
            source_status = self._son_status(source, now_ns)
            if (
                source_status is None
                or not bool(_field(source_status, "factual_episode", False))
                or _field(source_status, "episode_key") != key
            ):
                result = self._handover.finish("SOURCE_NO_LONGER_FACTUAL", self._monotonic_ns())
                self._publish_handover_result_telemetry(result, context.foreground)
                return
            if bool(_field(source_status, "termination_pending", False)):
                return
            if territory == source:
                result = self._handover.source_returned(self._monotonic_ns())
                if result.action == "EXPIRED":
                    self._apply_handover_clock_result(
                        result, now_ns=now_ns, observation=context.foreground
                    )
                    self._publish_handover_result_telemetry(
                        result, context.foreground
                    )
                    return
                if result.action == "SOURCE_RETURNED":
                    self._monitor_resume_son(
                        source, key, now_ns=now_ns, observation=context.foreground
                    )
                    self._publish_handover_result_telemetry(
                        result, context.foreground
                    )
                return
            if territory is None:
                if self._monitor_resume_son(
                    source, key, now_ns=now_ns, observation=context.foreground
                ):
                    result = self._handover.finish(
                        self._handover_exit_reason(context), self._monotonic_ns()
                    )
                    self._publish_handover_result_telemetry(
                        result, context.foreground
                    )
                return
            if territory != target:
                result = self._handover.switch_target(territory, self._monotonic_ns())
                self._publish_handover_result_telemetry(result, context.foreground)
            return

        if territory is None:
            return
        statuses = {
            son: self._son_status(son, now_ns)
            for son in ("SINE", "COSINE", "MINE")
        }
        target_status = statuses.get(territory)
        if bool(_field(target_status, "factual_episode", False)):
            return
        candidates = [
            (son, status)
            for son, status in statuses.items()
            if son != territory
            and status is not None
            and bool(_field(status, "source_eligible", False))
            and not bool(_field(status, "held", False))
        ]
        if len(candidates) != 1:
            return
        source, status = candidates[0]
        key = _field(status, "episode_key")
        if key is None:
            return
        if not self._monitor_hold_son(
            source, key, now_ns=now_ns, observation=context.foreground
        ):
            return
        try:
            result = self._handover.start(source, territory, key, self._monotonic_ns())
        except Exception:
            self._monitor_resume_son(
                source, key, now_ns=now_ns, observation=context.foreground
            )
            raise
        self._publish_handover_result_telemetry(result, context.foreground)

    def _reconcile_handover_after_routing(self, context: MonitorContext) -> None:
        """Close the protected source when the target becomes factually real."""

        if context.study_owned:
            return
        now_ns = context.foreground.observed_monotonic_ns
        snapshot = self._handover.snapshot(self._monotonic_ns())
        if not snapshot.active:
            return
        source = str(snapshot.source or "")
        target = str(snapshot.target or "")
        key = snapshot.source_episode_key
        source_status = self._son_status(source, now_ns)
        target_status = self._son_status(target, now_ns)
        if (
            source_status is None
            or not bool(_field(source_status, "factual_episode", False))
            or _field(source_status, "episode_key") != key
        ):
            result = self._handover.finish("SOURCE_NO_LONGER_FACTUAL", self._monotonic_ns())
            self._publish_handover_result_telemetry(result, context.foreground)
            return
        if not bool(_field(target_status, "factual_episode", False)):
            return
        if self._monitor_terminate_son(
            source, key, now_ns=now_ns, observation=context.foreground
        ):
            result = self._handover.finish("TARGET_ACTIVATED", self._monotonic_ns())
            self._publish_handover_result_telemetry(result, context.foreground)

    # Phase 3B: Mom transports facts and owns cross-organ transactions only.
    def _init_secant_connection(self):
        from SECANT.secant import SecantAuthority
        self._secant = SecantAuthority()
        self._study_world = "NORMAL"
        self._study_entry = None
        self._study_exit = None
        self._study_break = None
        self._study_last_sample = None
        self._study_return_target = None
        self._pending_secant_break_action = None
        self._study_resource_receipts = {}
        self._secant_transport = []
        self._pause_requests = {}
        self._pause_revision = 0
        self._pause_signature = None
        self._global_hold_id = ""
        self._cosecant_durable = set()
        self._cosecant_withdrawn = set()
        self._cosecant_pending_facts = []

    def _queue_secant_transport(self, kind, **payload):
        self._secant_transport.append((kind, dict(payload, session_id=self.session_id)))
        self._flush_secant_transport()

    def _flush_secant_transport(self):
        while self._secant_transport:
            kind, payload = self._secant_transport[0]
            if not _telemetry(self.telemetry_queue, kind, **payload):
                break
            self._secant_transport.pop(0)

    def _drain_secant(self):
        from SECANT.popup import PopupRequest
        # Applied behavioral outcomes, never the ordered-inbox receipt boolean.
        # Publish before withdrawal so the existing presenter can match the action.
        for result in self._secant.drain_return_action_results():
            self._queue_secant_transport("secant_action_result",
                request_id=result.request_id, display_id=result.display_id,
                action_sequence=result.action_sequence, episode_id=result.episode_id,
                accepted=result.accepted, occurred_monotonic_ns=result.at_ns,
                message="RETURN accepted" if result.accepted else "RETURN rejected")
        for fact in self._secant.drain():
            if isinstance(fact, PopupRequest):
                self._queue_secant_transport("secant_popup", request=fact)
            elif fact.name == "SECANT_POPUP_CLOSE_REQUESTED":
                self._queue_secant_transport("secant_close", request_id=fact.request_id,
                    occurred_monotonic_ns=fact.at_ns)
            elif fact.name=="SECANT_ACTION_INTENT" and fact.reason=="NEED BREAK":
                projection=self._secant.snapshot()
                action=(fact.request_id,projection.presentation.sequence)
                self._pending_secant_break_action=action
                self._queue_secant_transport("secant_break_selection",request_id=fact.request_id)
            else:
                _telemetry(self.telemetry_queue,"secant_fact",session_id=self.session_id,fact=fact)
        projection = self._secant.snapshot()
        self.services.study.set_connection_state(
            secant_episode_active=bool(projection.episode_id and not projection.terminal_reason),
            break_pause_id=self._study_break["id"] if self._study_break else "")
        _telemetry(self.telemetry_queue,"secant_projection",session_id=self.session_id,live_view=projection)

    def _pause_veto(self):
        if self.stop_event.is_set() or self._emergency_requested:
            return "Session is stopping"
        if self._study_world in {"ENTERING_STUDY", "EXITING_STUDY", "TERMINATING"}:
            return "Study authority transfer is unresolved"
        if self._normal_break_owns_pause():
            return "Normal SINE break owns the moment"
        if self._study_break or self._cosecant_owns_break_return() or self._cosecant_pending_facts:
            return "COSECANT break transaction owns the moment"
        mine = self._mine_authority.snapshot(now_ns=self._monotonic_ns()) if self._mine_authority else None
        if mine is None:
            return "MINE ownership is unknown"
        phase = _enum_text(_field(mine,"phase",""))
        if not phase or phase == "IMPORTANT_COMMIT_PENDING":
            return "MINE allowance commitment is unresolved"
        # A recovery phase may return to the same allowance. Only the native
        # MINE2B deadline transition or an episode terminal ends this veto.
        if (_field(mine,"important_deadline_effective_ns",0)
                and phase not in {"IDLE","CLOSED","SHUTDOWN"}
                and _field(mine,"mine2_variant","") != "MINE2B"):
            return "MINE important allowance owns the moment"
        return ""  # COSINE deliberately creates no new break veto.

    def _publish_pause_eligibility(self):
        from SECANT.read_model import PauseEligibility
        if self.session_id is None:
            return
        reason = self._pause_veto()
        signature = (self.session_id,not bool(reason),reason,self.pause_event.is_set())
        if signature != self._pause_signature:
            self._pause_signature=signature; self._pause_revision += 1
            _telemetry(self.telemetry_queue,"pause_eligibility",session_id=self.session_id,
                live_view=PauseEligibility(self.session_id,self._pause_revision,not bool(reason),reason))

    def _global_pause_request(self,payload):
        if _field(payload,"session_id") != self.session_id:
            return False
        request_id=_field(payload,"request_id",""); paused=_field(payload,"paused")
        if not request_id or type(paused) is not bool:
            return False
        if request_id in self._pause_requests:
            old_paused,accepted,reason=self._pause_requests[request_id]
            if old_paused != paused:
                return False
        else:
            reason=self._pause_veto() if paused else ""
            accepted=not bool(reason)
            now=self._monotonic_ns()
            if accepted and paused != self.pause_event.is_set():
                hold=request_id if paused else self._global_hold_id
                scope=self._secant.snapshot().scope
                if scope and not self._secant.set_global_paused(hold,paused,now):
                    accepted=False;reason="SECANT global hold is unresolved"
                if accepted and self._study_world == "STUDY":
                    if not self.services.study.set_global_paused(hold,paused):
                        if scope:self._secant.set_global_paused(hold,not paused,now)
                        accepted=False;reason="Study global hold is unresolved"
                if accepted:
                    if paused:self.pause_event.set();self._global_hold_id=hold
                    else:self.pause_event.clear();self._global_hold_id=""
                    self._study_last_sample=None
                    self._end_study_foreground_span("GLOBAL_PAUSE")
                    self._drain_secant()
            self._pause_requests[request_id]=(paused,accepted,reason)
        self._queue_secant_transport("pause_ack",request_id=request_id,accepted=accepted,reason=reason)
        self._publish_pause_eligibility()
        return accepted

    def _handle_secant_connection_command(self,kind,payload):
        from dataclasses import replace
        from SECANT.popup import PopupReceipt,Action
        if kind == "global_pause_request":
            self._global_pause_request(payload);return True
        if kind not in {"secant_receipt","normal_surface_clearance","cosecant_popup_closed"}:
            return False
        if _field(payload,"session_id") != self.session_id:
            return True
        if kind == "normal_surface_clearance":
            pending=self._study_entry
            if pending and _field(payload,"request_id")==pending.get("fence"):
                pending["surfaces_clear"]=_field(payload,"clear") is True
                if not pending["surfaces_clear"]:pending["fence"]=""
        elif kind == "cosecant_popup_closed":
            snap=self.services.cosecant.snapshot()
            key=(_field(payload,"break_id"),_field(payload,"generation"))
            if (key==(_field(snap,"break_id"),_field(snap,"generation"))
                    and _field(payload,"study_block_id")==_field(snap,"study_block_id")
                    and not _field(snap,"popup_required",True)):
                self._cosecant_withdrawn.add(key)
        else:
            receipt=_field(payload,"receipt")
            if isinstance(receipt,PopupReceipt):
                receipt=replace(receipt,received_at_ns=self._monotonic_ns())
                accepted=self._secant.receipt(receipt)
                self._drain_secant()
        return True

    def _supported_study_interval(self,sample,epoch):
        previous=self._study_last_sample
        self._study_last_sample=(sample,epoch)
        if previous is None:return None
        old,old_epoch=previous
        delta=sample.observed_monotonic_ns-old.observed_monotonic_ns
        if (old_epoch==epoch and sample.study_context_token==old.study_context_token
                and sample.resource==old.resource and sample.observation_sequence>old.observation_sequence
                and 0 < delta <= STUDY_CONTINUITY_MAX_GAP_NS):
            return old.observed_monotonic_ns
        return None

    def _reconcile_study_resources(self):
        for fact in self.services.study.snapshot().pending_resources:
            pending=self._study_resource_receipts.get(fact.resource_fact_id)
            receipt=self.services.storage.receipt(pending) if pending else None
            if pending and receipt is None:
                continue  # Unknown is not failed and cannot acquire a new write.
            if receipt is None:
                receipt=self.services.storage.record_study_resource(fact)
                self._study_resource_receipts[fact.resource_fact_id]=_receipt_id(receipt)
            state=_receipt_state(receipt)
            if state==COMMITTED_STATE:
                self.services.study.resource_committed(fact.resource_fact_id)
                self._consume_receipt(_receipt_id(receipt))
                self._study_resource_receipts.pop(fact.resource_fact_id,None)
            elif state in {"FAILED","CANCELLED"}:
                self._consume_receipt(_receipt_id(receipt))
                self._study_resource_receipts.pop(fact.resource_fact_id,None)
        self._secant.set_resources(self.services.study.snapshot().resources)

    def _route_study_evidence(self,context):
        from SECANT.read_model import StudyScope, FoundingSourceEvidence
        from SECANT.secant import StudyEvidence,Meaning,Territory
        from SECANT.recovery import AcceptedResourceEvidence
        from COSECANT_STUDY_MODE.study import StudyState
        study=self.services.study.snapshot()
        if (self._study_world!="STUDY" or study.state is not StudyState.ACTIVE
                or self.pause_event.is_set() or self._study_break):
            self._study_last_sample=None;return
        try:
            sample=self.services.resource_intent.study_sample(
                expected_observation_ns=context.foreground.observed_monotonic_ns,
                expected_sequence=context.foreground.sequence)
        except Exception as error:
            # Contain only the read-only RI -> SECANT adapter. Normal organs,
            # runtime mutations and persistence remain outside this boundary.
            self._study_last_sample=None
            _telemetry(self.telemetry_queue,"study_evidence_unavailable",
                observation=context.foreground,session_id=self.session_id,
                reason="adapter_exception",error_type=type(error).__name__,
                message="Study exact-resource adapter failed; continuity interrupted")
            return
        if sample is None:
            self._study_last_sample=None
            _telemetry(self.telemetry_queue,"study_evidence_unavailable",
                observation=context.foreground,session_id=self.session_id,
                reason="unsupported_sample",
                message="No usable Study exact-resource sample; continuity interrupted")
            return
        supported=self._supported_study_interval(sample,study.active_epoch_monotonic_ns)
        self.services.study.observe_resource(sample,supported_since_ns=supported)
        self._reconcile_study_resources()
        resources=self.services.study.snapshot().resources
        primary=next((f for f in resources if f.role=="PRIMARY"),None)
        if primary is None:return
        if (sample.effective_state=="STUDY_ALIGNED"
                and any(f.resource==sample.resource for f in resources)):
            from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget
            exact=sample.resource
            self._study_return_target=CosecantReturnTarget(study.context_token,exact.platform_key,exact.resource_token,
                sample.observed_monotonic_ns,exact.kind,exact.key,exact.process_name,exact.process_id,
                exact.hwnd,exact.normalized_title,exact.version,display_metadata=getattr(sample,"display_metadata",None))
        projection=self._secant.snapshot()
        scope=StudyScope(str(self.session_id)+":"+study.context_token,primary.resource.key)
        if projection.scope is None:
            if not self._secant.open_scope(scope,sample.observed_monotonic_ns):return
        elif projection.scope!=scope:return
        meaning=Meaning.STUDY_ALIGNED if sample.effective_state=="STUDY_ALIGNED" else (Meaning.OFF_TASK if sample.classification=="DISTRACTION" else Meaning.ACTIVITY)
        if sample.classification=="UNCERTAIN":meaning=Meaning.UNCERTAIN
        if sample.confirmed_off_task:meaning=Meaning.OFF_TASK
        identity=_field(_field(context.resource_intent,"verdict"),"resource_identity")
        surface=_enum_text(_field(identity,"surface","")).upper()
        territory={"SOCIAL":Territory.SOCIAL,"MESSAGING":Territory.MESSAGING,"GAMING":Territory.GAMING,
            "YOUTUBE_WATCH":Territory.VIDEO,"YOUTUBE_SHORTS":Territory.SHORT_VIDEO}.get(surface,Territory.ORDINARY)
        evidence=None;accepted=sample.accepted;projection=self._secant.snapshot()
        if (accepted and accepted.study_context_token==sample.study_context_token
                and accepted.resource_key==sample.resource.key
                and projection.episode_id and not projection.terminal_reason):
            evidence=AcceptedResourceEvidence(projection.episode_id,scope,sample.resource.key,sample.observed_monotonic_ns,
                accepted.request_id,sample.observation_id,accepted_at_ns=accepted.accepted_monotonic_ns,
                source_observation_id=accepted.source_observation_id,source_request_id=accepted.request_id,
                provenance=accepted.source)
        self._secant.observe(StudyEvidence(scope,sample.resource.key,meaning,sample.observed_monotonic_ns,
            sample.observation_id,territory,sample.confirmed_off_task,sample.certified_ott,supported,True,evidence,
            FoundingSourceEvidence(sample.resource,sample.observation_id,sample.observed_monotonic_ns,
                meaning.value,sample.classification,territory.value,sample.confirmed_off_task,sample.certified_ott,
                display_metadata=getattr(sample,"display_metadata",None))))
        self._drain_secant()

    def _begin_study_entry(self):
        """Internal barrier contract. Public START remains locked in Phase 3B."""
        from uuid import uuid4
        from COSECANT_STUDY_MODE.study import StudyState
        if (self._study_world!="NORMAL" or self.pause_event.is_set() or self.stop_event.is_set()
                or self.services.study.snapshot().state is not StudyState.READY
                or self._normal_break_owns_pause()):return False
        self._study_world="ENTERING_STUDY"
        sine=self.services.sine.live_view();mirl=self.services.mirl.live_view()
        self._study_entry={"identity":(self.services.study.snapshot().block_id,self.services.study.snapshot().generation),
            "sine_uid":_field(sine,"episode_uid",""),"candidate_uid":_field(sine,"candidate_uid",""),
            "event_id":_field(sine,"operational_event_id"),"mirl_episode_id":_field(mirl,"episode_id"),
            "popup_request_id":_field(sine,"popup_request_id",""),"fence":"","surfaces_clear":False}
        self._advance_study_entry();return True

    def _advance_study_entry(self):
        from uuid import uuid4
        from COSECANT_STUDY_MODE.study import StudyState
        pending=self._study_entry
        if pending is None:return
        now=self._monotonic_ns();study=self.services.study.snapshot()
        if (self.pause_event.is_set() or self.stop_event.is_set() or self._normal_break_owns_pause()
                or (study.block_id,study.generation)!=pending["identity"] or study.state is not StudyState.READY):return
        result=self._finish_handover_for_study(now)
        self._apply_handover_clock_result(result,now_ns=now,observation=None)
        if _field(_field(result,"snapshot"),"active",True):return
        mirl=self.services.mirl.live_view()
        if pending["sine_uid"]:
            if (not pending["mirl_episode_id"] or _field(mirl,"candidate_uid")!=pending["candidate_uid"]
                    or _field(mirl,"operational_event_id")!=pending["event_id"]):return
            live=self.services.sine.live_view()
            if _enum_text(_field(live,"phase")).upper() not in {"RESOLVED","CANCELLED","EMERGENCY_STOPPED"}:
                self.services.sine.close_for_study_transition(episode_uid=pending["sine_uid"],
                    candidate_uid=pending["candidate_uid"],operational_event_id=pending["event_id"],now_ns=now)
                self._route_sine_batch(self.services.sine.advance(now_monotonic_ns=now))
            key=(pending["mirl_episode_id"],pending["candidate_uid"],pending["event_id"])
            reason=self._durable_sine_terminals.get(pending["sine_uid"],"")
            outcome=self._durable_mirl_closes.get(key)
            if not ((outcome=="ABORTED" and reason=="STUDY_MODE_ACTIVATED")
                    or (outcome=="RETURNED" and reason.startswith("verified_return:"))):return
            popup=pending["popup_request_id"]
            if popup and (pending["sine_uid"],popup) not in self._durable_popup_closes:return
        elif _enum_text(_field(self.services.sine.live_view(),"phase","")).upper() not in {"IDLE","RESOLVED","CANCELLED","EMERGENCY_STOPPED"}:
            return
        if not pending["sine_uid"] and _enum_text(_field(mirl,"phase","")).upper() not in {"IDLE","CLOSED","EMERGENCY_STOPPED"}:return
        for authority,route in ((self._mine_authority,self._route_mine_effect),(self.services.cosine,self._route_cosine_effect)):
            if authority is None:return
            for effect in authority.preempt_for_study(now_ns=now):route(effect)
            if _enum_text(_field(authority.snapshot(now_ns=now),"phase","")) not in {"IDLE","CLOSED","SHUTDOWN"}:return
        if self._pending_trigger is not None:return
        if not pending["surfaces_clear"]:
            if not pending["fence"]:
                pending["fence"]="normal-fence-"+uuid4().hex
                self._queue_secant_transport("normal_surface_fence",request_id=pending["fence"])
            return
        if not self.services.study.bind_session(self.session_id):return
        result=self.services.study.start()
        if not _field(result,"accepted",False):return
        self._handle_study_result("START",result)
        self._study_entry=None;self._study_world="STUDY";self._study_last_sample=None

    def _begin_study_exit(self,reason="study_complete"):
        self._end_study_foreground_span("STUDY_EXIT")
        if self._study_exit is None:
            self._study_exit={"reason":reason,"context":self.services.study.snapshot().context_token,"finalized":False}
        elif reason in {"emergency","session_end"}:
            self._study_exit["reason"]=reason
        self._study_world="EXITING_STUDY" if reason=="study_complete" else "TERMINATING"
        self._study_last_sample=None
        self._advance_study_exit()

    def _advance_study_exit(self):
        from COSECANT_STUDY_MODE.study import StudyState
        pending=self._study_exit
        if pending is None:return
        now=self._monotonic_ns();scope=self._secant.snapshot().scope
        if scope:self._secant.complete(scope,now,pending["reason"])
        self._drain_secant()
        if self._study_break and not self._study_break.get("owned"):
            if not self.services.cosecant.abort_reservation(self._study_break["id"]):return
            self._study_break=None
        self._route_cosecant_result(self.services.cosecant.cancel_for_session_end(reason=pending["reason"]))
        cosecant=self.services.cosecant.snapshot()
        _telemetry(self.telemetry_queue,"cosecant_view",live_view=cosecant)
        secant=self._secant.snapshot()
        if secant.cleanup_pending or secant.popup_state in {"REQUESTED","DISPLAYED","CLOSE_REQUESTED"}:return
        if self._cosecant_pending_facts or not self.services.cosecant.retry_cleanup():return
        if cosecant.break_id and (cosecant.break_id,cosecant.generation) not in self._cosecant_withdrawn:return
        token=pending["context"]
        if token and not self.services.resource_intent.context_retirement_proven(token):
            self.services.resource_intent.retire_study_context(expected_context_token=token)
            if not self.services.resource_intent.context_retirement_proven(token):return
        if not pending["finalized"]:
            study=self.services.study.snapshot()
            if study.state not in {StudyState.COMPLETED,StudyState.SHUTDOWN}:
                result=self.services.study.complete()
                if not result.accepted:return
                study=result.snapshot
            if not self.services.storage.record_study_snapshot(session_id=self.session_id,action="COMPLETE" if pending["reason"]=="study_complete" else pending["reason"].upper(),snapshot=study):return
            pending["finalized"]=True
        self._study_break=None;self._study_entry=None;self._study_exit=None
        self._study_world="NORMAL" if pending["reason"]=="study_complete" and not self.stop_event.is_set() and not self._emergency_requested else "TERMINATING"
        self._drain_secant()

    def _connection_tick(self):
        from COSECANT_STUDY_MODE.study import StudyState
        if self._study_world=="STUDY" and self.services.study.snapshot().state is StudyState.COMPLETED:
            self._begin_study_exit("study_complete")
        self._flush_secant_transport()
        self._advance_study_entry()
        self._advance_study_exit()
        if self._study_world=="STUDY":self._advance_study_break()
        self._publish_pause_eligibility()
    def _reject_secant_break_action(self,action,message):
        request_id,sequence=action
        self._secant.action_result(request_id,False,self._monotonic_ns(),action_sequence=sequence)
        self._queue_secant_transport("secant_action_result",request_id=request_id,
            accepted=False,action_sequence=sequence,message=message)

    def _begin_study_break(self,seconds,target,*,request_id="",action_sequence=None):
        from uuid import uuid4
        from COSECANT_STUDY_MODE.study import StudyState
        study=self.services.study.snapshot();secant=self._secant.snapshot()
        if (self._study_world!="STUDY" or self.pause_event.is_set() or self._study_break
                or study.state is not StudyState.ACTIVE or int(secant.stage)>=2):return False
        pause_id="study-break-pause-"+uuid4().hex
        reservation=self.services.cosecant.reserve_break(pause_id=pause_id,study=study,
            selected_break_seconds=seconds,intended_return_target=target,secant_stage=int(secant.stage))
        if reservation is None:return False
        self._end_study_foreground_span("BREAK_PENDING")
        self._study_break={"id":pause_id,"scope":secant.scope,"episode":secant.episode_id,
            "owned":False,"paused_study":False,"held":False,"request_id":request_id,
            "action_sequence":action_sequence,"abort":False,"identity":(study.block_id,study.generation)}
        self._study_last_sample=None;self._advance_study_break();return True

    def _abort_study_break(self):
        pending=self._study_break
        if pending is None:return True
        if pending["owned"]:return False
        if not pending.get("reservation_aborted"):
            if not self.services.cosecant.abort_reservation(pending["id"]):return False
            pending["reservation_aborted"]=True
        if pending["paused_study"] and not pending.get("abort_resumed"):
            result=self.services.study.resume(break_pause_id=pending["id"])
            if not result.accepted:return False
            self._handle_study_result("BREAK_ABORT_RESUME",result)
            pending["abort_resumed"]=True
        if pending["held"]:
            if not self._secant.release_break(pending["scope"],pending["episode"],pending["id"],self._monotonic_ns()):return False
        if pending["request_id"]:
            self._secant.action_result(pending["request_id"],False,self._monotonic_ns(),action_sequence=pending["action_sequence"])
            self._queue_secant_transport("secant_action_result",request_id=pending["request_id"],accepted=False,action_sequence=pending["action_sequence"])
        self._study_break=None;self._drain_secant();return True

    def _advance_study_break(self):
        from COSECANT_STUDY_MODE.study import StudyState
        pending=self._study_break
        if pending is None:return
        if pending["abort"]:
            self._abort_study_break();return
        study=self.services.study.snapshot();projection=self._secant.snapshot();now=self._monotonic_ns()
        if (study.block_id,study.generation)!=pending["identity"]:
            pending["abort"]=True;self._abort_study_break();return
        if pending["owned"]:
            snap=self.services.cosecant.snapshot()
            terminal=any(k[0]==snap.break_id and k[2]=="RETURN_CONFIRMED" for k in self._cosecant_durable)
            if (not terminal or self._cosecant_pending_facts or not snap.return_confirmed
                    or not self.services.cosecant.transaction_clear(pending["id"])
                    or (snap.break_id,snap.generation) not in self._cosecant_withdrawn):return
            result=self.services.study.resume(break_pause_id=pending["id"])
            if not result.accepted:return
            self._handle_study_result("RETURN_CONFIRMED_RESUME",result)
            if pending["held"] and not self._secant.release_break(pending["scope"],pending["episode"],pending["id"],now):return
            self._study_break=None;self._study_last_sample=None;self._drain_secant();return
        # A possible founding display is not the pre-episode branch. Ask the
        # native authority to withdraw and reconcile it before choosing.
        if projection.presentation.unresolved_display:
            self._secant.reset_pre_episode(projection.scope,now);self._drain_secant();return
        if projection.episode_id and not projection.terminal_reason:
            if int(projection.stage)!=1:
                pending["abort"]=True;self._abort_study_break();return
            pending["episode"]=projection.episode_id;pending["scope"]=projection.scope
            if not pending["held"]:
                if not self._secant.yield_break(projection.scope,projection.episode_id,pending["id"],now):
                    pending["abort"]=True;self._abort_study_break();return
                pending["held"]=True;self._drain_secant()
            if self._secant.snapshot().popup_state in {"REQUESTED","DISPLAYED","CLOSE_REQUESTED"}:return
        elif projection.scope and not self._secant.reset_pre_episode(projection.scope,now):
            self._drain_secant();return
        self.services.study.set_connection_state(secant_episode_active=bool(pending["episode"]),break_pause_id=pending["id"])
        if not pending["paused_study"]:
            result=self.services.study.pause(break_pause_id=pending["id"])
            if not result.accepted:
                pending["abort"]=True;self._abort_study_break();return
            pending["paused_study"]=True
            self._handle_study_result("BREAK_PAUSE",result)
        paused=self.services.study.snapshot()
        if paused.state is not StudyState.PAUSED:return
        result=self.services.cosecant.commit_reserved_break(pause_id=pending["id"],study=paused)
        pending["owned"]=self._cosecant_owns_break_return(result.snapshot)
        self._route_cosecant_result(result)
        if pending["owned"]:
            if pending["held"]:self._secant.confirm_break(pending["id"],result.snapshot.break_id)
            self._drain_secant()
        else:
            pending["abort"]=True;self._abort_study_break()

    def _apply_internal_study_action(self,action):
        """Native action contract behind the public Phase-3B lock."""
        if self._study_world!="STUDY" or self._study_exit:return False
        key=action.upper()
        if key=="COMPLETE":self._begin_study_exit();return True
        if key not in {"PAUSE","RESUME"} or self._study_break or self.pause_event.is_set():return False
        projection=self._secant.snapshot()
        if projection.episode_id and not projection.terminal_reason:return False
        if key=="PAUSE" and projection.scope:
            if not self._secant.reset_pre_episode(projection.scope,self._monotonic_ns()):
                self._drain_secant();return False
        result=getattr(self.services.study,key.lower())()
        self._handle_study_result(key,result);self._study_last_sample=None
        return result.accepted


    def _study_owns_moment(self) -> bool:
        """Read the two existing lifecycle authorities; detect nothing anew."""

        from COSECANT_STUDY_MODE.study import StudyState

        study = self.services.study.snapshot()
        projection=self._secant.snapshot()
        return bool(self._study_world!="NORMAL" or self._study_entry or self._study_exit or self._study_break
            or _field(study,"state") in {StudyState.ACTIVE,StudyState.PAUSED}
            or (projection.episode_id and not projection.terminal_reason)
            or projection.cleanup_pending or projection.frozen_reasons
            or self._cosecant_owns_break_return())

    def _cosecant_owns_break_return(self, snapshot: object | None = None) -> bool:
        """Read whether the existing COSECANT lifecycle owns this moment."""

        from COSECANT_STUDY_MODE.cosecant import CosecantState

        current = self.services.cosecant.snapshot() if snapshot is None else snapshot
        return _field(current, "state", None) in {
            CosecantState.BREAK_ACTIVE,
            CosecantState.BREAK_COMPLETE,
            CosecantState.BREAK_ALREADY_OVER,
            CosecantState.FINAL_LOCK,
            CosecantState.RETURN_CONFIRMING,
        }

    def _settle_study_son_preemption(
        self,
        *,
        study_owned: bool,
        observation: ForegroundObservation,
        cosine_platform: object | None = None,
    ) -> bool:
        """Route Dad's factual ownership through Mom to all three sons.

        Study is stronger than SINE, COSINE and MINE, but it is not a sibling.
        This junction therefore invokes only each son's native Dad artery.  It
        never starts, settles, pauses or otherwise mutates Mr Hand; Mr Hand's
        own Dad-preemption is handled independently by Mom's established
        _finish_handover_for_study() / _sync_handover_clock() boundary.

        SINE settles its existing Normal episode at the ownership boundary.
        COSINE preserves the
        exact first Study-owned boundary sample before terminal preemption, and
        its private pending flag remains only a durability-retry latch.  MINE
        keeps its native Study latch and retries terminal durability through its
        own preempt_for_study() implementation.
        """

        now_ns = observation.observed_monotonic_ns
        if self._study_world != "NORMAL":
            # The explicit entry/exit barrier owns positive settlement.
            return self._study_world == "STUDY"

        if study_owned:
            sine_view = self.services.sine.live_view()
            if (
                str(_field(sine_view, "episode_uid", "") or "").strip()
            ):
                try:
                    sine_preempted = bool(
                        self.services.sine.preempt_for_study(now_ns=now_ns)
                    )
                except Exception as exc:
                    sine_preempted = False
                    _telemetry(
                        self.telemetry_queue,
                        "sine_study_preemption_pending",
                        observation=observation,
                        message=(
                            "SINE Study preemption could not complete: "
                            f"{_safe_telemetry_text(exc)}"
                        ),
                    )
                self._drain_monitor_son_outputs(
                    "SINE", now_ns=now_ns, observation=observation
                )
                if not sine_preempted:
                    _telemetry(
                        self.telemetry_queue,
                        "sine_study_preemption_pending",
                        observation=observation,
                        message=(
                            "SINE still owns a pre-Study episode; Dad preemption "
                            "will retry on the next factual Study sample."
                        ),
                    )
                    raise RuntimeError("Normal SINE refused Study ownership; routing stopped")

        cosine_snapshot = self.services.cosine.snapshot(now_ns=now_ns)
        cosine_phase = _enum_text(_field(cosine_snapshot, "phase", ""))
        cosine_active = cosine_phase not in {"", "IDLE", "CLOSED", "SHUTDOWN"}
        entering_cosine_preemption = bool(
            study_owned
            and cosine_active
            and not self._cosine_study_preemption_pending
        )
        if study_owned and cosine_active:
            self._cosine_study_preemption_pending = True

        if entering_cosine_preemption and cosine_platform is not None:
            # Preserve only the supported interval ending exactly at Dad's
            # ownership boundary.  Retry cycles must never credit Study time.
            from COSINE.cosine import CosineObservation

            for effect in self.services.cosine.observe(
                CosineObservation(
                    platform=cosine_platform,
                    focus_confirmed=False,
                    sine_popup_displayed=False,
                    observed_monotonic_ns=now_ns,
                    observation_sequence=observation.sequence,
                    supported_interval_ns=int(
                        float(getattr(self, "poll_seconds", DEFAULT_POLL_SECONDS))
                        * NANOSECONDS_PER_SECOND
                    ),
                )
            ):
                self._route_cosine_effect(effect, observation)

        cosine_settled = True
        if self._cosine_study_preemption_pending:
            if not cosine_active:
                self._cosine_study_preemption_pending = False
            else:
                try:
                    effects = self.services.cosine.preempt_for_study(now_ns=now_ns)
                except Exception as exc:
                    cosine_settled = False
                    _telemetry(
                        self.telemetry_queue,
                        "cosine_study_preemption_pending",
                        observation=observation,
                        message=(
                            "COSINE Study preemption remains suppressed: "
                            f"{_safe_telemetry_text(exc)}"
                        ),
                    )
                else:
                    for effect in effects:
                        self._route_cosine_effect(effect, observation)
                    after = self.services.cosine.snapshot(now_ns=now_ns)
                    after_phase = _enum_text(_field(after, "phase", ""))
                    cosine_settled = after_phase in {
                        "",
                        "IDLE",
                        "CLOSED",
                        "SHUTDOWN",
                    }
                    self._cosine_study_preemption_pending = not cosine_settled
                    if not cosine_settled:
                        _telemetry(
                            self.telemetry_queue,
                            "cosine_study_preemption_pending",
                            observation=observation,
                            message=(
                                "COSINE Dad preemption was not durably accepted; "
                                "specialist authority remains suppressed and "
                                "closure will retry."
                            ),
                        )

        if study_owned:
            mine_authority = getattr(self, "_mine_authority", None)
            if mine_authority is not None:
                try:
                    effects = mine_authority.preempt_for_study(now_ns=now_ns)
                except Exception as exc:
                    _telemetry(
                        self.telemetry_queue,
                        "mine_study_preemption_pending",
                        observation=observation,
                        message=(
                            "MINE Study preemption could not complete: "
                            f"{_safe_telemetry_text(exc)}"
                        ),
                    )
                else:
                    for effect in effects:
                        self._route_mine_effect(effect, observation)

        return cosine_settled

    def _route_context(
        self,
        context: MonitorContext,
        blacklist_result: object,
    ) -> None:
        from COSINE.cosine import CosineObservation
        from CORE_ENGINE.resource_intent import NORMAL_FOCUS_SURFACES

        now_ns = context.foreground.observed_monotonic_ns
        self._drain_resource_intent_facts(context.foreground)
        verdict = _field(context.resource_intent, "verdict")
        resource_identity = _field(verdict, "resource_identity")
        resource_surface = _field(resource_identity, "surface")
        # NEW COSINE recovery uses the two already-published normal-mode
        # productive surfaces. Unknown/neutral context is deliberately false.
        focus_confirmed = bool(
            not context.study_owned
            and resource_surface
            in NORMAL_FOCUS_SURFACES
        )

        cosine_observation = CosineObservation(
            platform=(context.cosine_platform if context.cosine_owned else None),
            focus_confirmed=focus_confirmed,
            # Retained constructor field is staged compatibility only.  SINE
            # popup presentation no longer drives COSINE physiology.
            sine_popup_displayed=False,
            observed_monotonic_ns=now_ns,
            observation_sequence=context.foreground.sequence,
            supported_interval_ns=int(
                float(getattr(self, "poll_seconds", DEFAULT_POLL_SECONDS))
                * 1_000_000_000
            ),
        )
        if not context.study_owned and not self._cosine_study_preemption_pending:
            for effect in self.services.cosine.observe(cosine_observation):
                self._route_cosine_effect(effect, context.foreground)
            for effect in self.services.cosine.advance(now_ns=now_ns):
                self._route_cosine_effect(effect, context.foreground)

        self._route_mine_context(
            context,
            resource_surface=resource_surface,
            resource_identity=resource_identity,
        )

        # Break completion is decided before MIRL interprets this observation.
        # If the break remains active, one explicit NEUTRAL observation replaces
        # (never supplements) MIRL's ordinary context route.
        self._advance_normal_break(now_ns, context.foreground)
        mirl_events = self._observe_mirl_for_context(context)
        self._persist_mirl_events(tuple(mirl_events), context.foreground)

        self.services.sine.observe(context)
        self._prepare_dwell_telemetry(blacklist_result)
        self._sync_sine_activity_clock(context, blacklist_result)

        self._refresh_break_eligible_study_target(context)
        # A parked break request is decided here, on the same observation the
        # other organs are consuming, so admission never performs its own
        # foreground or browser read.
        self._admit_pending_break(context)

        # Study and COSECANT consume the same Resource Intent fact. No second
        # foreground/browser read is permitted inside either runtime.
        self._sync_study_context_after_advance(self.services.study.advance())
        self._route_study_evidence(context)
        cosecant_result = self.services.cosecant.advance()
        self._route_cosecant_result(cosecant_result, context.foreground)
        self._observe_cosecant_return(context)
        self._reconcile_pending_trigger(context, blacklist_result)
        self._connection_tick()

        # One unresolved candidate at a time. A RUNNING database transaction
        # cannot be replaced by a later foreground observation. Once SINE has
        # accepted a durable candidate, its live episode owns intervention
        # until an authoritative terminal transition releases it; popup
        # visibility is presentation state and must not found another SINE 1.
        if (
            self._pending_trigger is None
            and self._pending_study_start is None
            and not self._sine_owns_intervention()
            and not self._mine_owns_intervention()
            and not self._normal_break_owns_pause()
            and self._study_trigger_admission_open(context)
        ):
            candidate = self.services.trigger.evaluate(
                context=context,
                blacklist=blacklist_result,
            )
            if candidate is not None:
                self._begin_trigger_persistence(candidate, context, blacklist_result)

        self._route_sine_batch(
            self.services.sine.advance(now_monotonic_ns=now_ns), context.foreground
        )
        self._reconcile_pending_normal_break_selector(
            occurred_monotonic_ns=now_ns,
            observation=context.foreground,
        )

    def _route_mine_context(
        self,
        context: MonitorContext,
        *,
        resource_surface: object,
        resource_identity: object,
    ) -> None:
        """Coordinate siblings, then give MINE the one current certified fact."""

        from CORE_ENGINE.resource_intent import NORMAL_FOCUS_SURFACES, ResourceSurface
        from MINE.mine import MineObservation, MineObservationKind

        if getattr(self, "_mine_authority", None) is None:
            return
        now_ns = context.foreground.observed_monotonic_ns
        if context.study_owned:
            # Dad preemption was already routed centrally by
            # _settle_study_son_preemption() before Resource Intent routing.
            return

        mine_before = self._mine_authority.snapshot(now_ns=now_ns)
        if bool(_field(mine_before, "study_preempted", False)):
            if not self._mine_authority.release_study_preemption(now_ns=now_ns):
                for effect in self._mine_authority.advance(now_ns=now_ns):
                    self._route_mine_effect(effect, context.foreground)
                return

        messaging = resource_surface is ResourceSurface.MESSAGING

        mine = self._mine_authority.snapshot(now_ns=now_ns)
        phase = _enum_text(_field(mine, "phase", ""))
        formal = bool(str(_field(mine, "mine_episode_id", "") or ""))

        if messaging:
            process = str(_field(resource_identity, "process_name", "") or "").casefold()
            platform_key = str(_field(resource_identity, "platform_key", "") or "").strip()
            if not platform_key:
                platform_key = process.removesuffix(".exe")
            platform_label = MESSAGING_PROCESS_LABELS.get(
                platform_key,
                MESSAGING_PROCESS_LABELS.get(process.removesuffix(".exe"), platform_key),
            )
            kind = MineObservationKind.MESSAGING
            evidence_token = str(_field(resource_identity, "stable_key", "") or "")
        elif resource_surface in NORMAL_FOCUS_SURFACES:
            kind = MineObservationKind.FOCUS
            platform_key = platform_label = evidence_token = ""
        else:
            kind = MineObservationKind.NEUTRAL
            platform_key = platform_label = evidence_token = ""

        observation = MineObservation(
            kind=kind,
            observed_monotonic_ns=now_ns,
            observation_sequence=context.foreground.sequence,
            supported_interval_ns=int(self.poll_seconds * NANOSECONDS_PER_SECOND),
            platform_key=platform_key,
            platform_label=platform_label,
            evidence_token=evidence_token,
        )
        for effect in self._mine_authority.observe(observation):
            self._route_mine_effect(effect, context.foreground)
        for effect in self._mine_authority.advance(now_ns=now_ns):
            self._route_mine_effect(effect, context.foreground)

    def _mine_owns_intervention(self) -> bool:
        if getattr(self, "_mine_authority", None) is None:
            return False
        now_ns = max(1, self._monotonic_ns())
        status = self._mine_authority.monitor_status(now_ns=now_ns)
        return bool(
            _field(status, "factual_episode", False)
            and not _field(status, "held", False)
        )

    def _study_trigger_admission_open(self, context: MonitorContext) -> bool:
        """Exclude Study and COSECANT ownership from Normal Trigger admission."""

        from CORE_ENGINE.resource_intent import ResourceIntent, SineContribution
        from COSECANT_STUDY_MODE.study import StudyState

        if self._study_owns_moment():
            return False
        verdict = _field(context.resource_intent, "verdict")
        cosecant = self.services.cosecant.snapshot()
        if self._cosecant_owns_break_return(cosecant):
            classification = _field(verdict, "classification")
            contribution = _field(verdict, "sine_contribution")
            verdict_token = str(_field(verdict, "study_context_token", "") or "")
            expected_token = str(_field(cosecant, "study_context_token", "") or "")
            fresh = bool(_field(context.resource_intent, "fresh", False))
            context_delivery = _enum_text(_field(cosecant, "context_delivery", ""))
            mismatch = bool(
                not fresh
                or not verdict_token
                or verdict_token != expected_token
                or classification is not ResourceIntent.APPROVED_BREAK
                or contribution is not SineContribution.NONE
                or context_delivery != "CONFIRMED"
            )
            if mismatch:
                signature = (
                    str(_field(cosecant, "break_id", "") or ""),
                    _enum_text(_field(cosecant, "state", "")),
                    verdict_token,
                    _enum_text(classification),
                    _enum_text(contribution),
                    fresh,
                    context_delivery,
                )
                if signature != getattr(
                    self, "_last_cosecant_intent_mismatch_signature", None
                ):
                    _telemetry(
                        self.telemetry_queue,
                        "cosecant_resource_intent_mismatch",
                        observation=context.foreground,
                        message=(
                            "Live COSECANT ownership overruled stale or missing "
                            "Resource Intent trigger evidence"
                        ),
                        break_id=signature[0],
                        cosecant_state=signature[1],
                        study_context_token=verdict_token,
                        expected_study_context_token=expected_token,
                        resource_intent_classification=signature[3],
                        sine_contribution=signature[4],
                        resource_intent_fresh=fresh,
                        context_delivery=signature[6],
                    )
                self._last_cosecant_intent_mismatch_signature = signature
            else:
                self._last_cosecant_intent_mismatch_signature = None
            return False
        self._last_cosecant_intent_mismatch_signature = None
        study = self.services.study.snapshot()
        verdict_token = str(_field(verdict, "study_context_token", "") or "")
        return bool(
            _field(study, "state") is not StudyState.ACTIVE
            and not verdict_token
            and not context.study_owned
        )

    def _sine_owns_intervention(self) -> bool:
        """Return whether one live SINE episode blocks a new founding trigger."""

        from SINE.sine import SinePhase

        live_view = self.services.sine.live_view()
        episode_uid = str(_field(live_view, "episode_uid", "") or "").strip()
        phase = _field(live_view, "phase")
        status = self.services.sine.monitor_status(
            now_ns=max(1, self._monotonic_ns())
        )
        return bool(
            episode_uid
            and phase in {
                SinePhase.WAITING_FOR_DISPLAY,
                SinePhase.ACTIVE,
                SinePhase.PROTECTED_RED,
            }
        )

    def _normal_break_owns_pause(self) -> bool:
        """Defence-in-depth gate for active or failed-close break ownership."""

        sine_view = self.services.sine.live_view()
        normal_break = getattr(self.services, "normal_break", None)
        return bool(
            bool(getattr(normal_break, "active", False))
            or self._normal_break_resume_fault
            or _field(sine_view, "normal_break_held", False)
        )

    def _sync_sine_activity_clock(
        self,
        context: MonitorContext,
        blacklist_result: object,
    ) -> bool:
        """Map current authoritative Normal-mode evidence to SINE RUN/PAUSE.

        This consumes the same-cycle Resource Intent, COSINE and Executive
        Blacklist facts already produced by the monitor. It never reads the
        dashboard label, Windows, browser state or title text independently.
        """

        from CORE_ENGINE.blacklist import Disposition
        from CORE_ENGINE.resource_intent import ResourceSurface
        from SINE.sine import SinePhase

        sine = self.services.sine.live_view()
        candidate_uid = str(_field(sine, "candidate_uid", "") or "")
        if (
            not candidate_uid
            or _field(sine, "phase") is not SinePhase.ACTIVE
            or bool(_field(sine, "study_mode", False))
            or bool(_field(sine, "protected_red_active", False))
            or bool(_field(sine, "presentation_withheld_for_recovery", False))
            or self._normal_break_owns_pause()
        ):
            return True

        now_ns = int(context.foreground.observed_monotonic_ns or 0)
        if now_ns <= 0:
            return False

        normal_break = getattr(self.services, "normal_break", None)
        break_view = normal_break.snapshot() if normal_break is not None else None
        break_state = _enum_text(_field(break_view, "state", "")).upper()

        cosine = self.services.cosine.snapshot(now_ns=now_ns)
        cosine_phase = _enum_text(_field(cosine, "phase", "")).upper()
        cosine_active = cosine_phase not in {"", "IDLE", "CLOSED", "SHUTDOWN"}

        intent_verdict = _field(context.resource_intent, "verdict")
        resource_identity = _field(intent_verdict, "resource_identity")
        resource_surface = _field(resource_identity, "surface")

        blacklist_verdict = _field(blacklist_result, "verdict")
        blacklist_disposition = _field(blacklist_verdict, "disposition")
        blacklist_actionable = bool(_field(blacklist_verdict, "actionable", False))

        # A pending TAKE A BREAK selector must never freeze the deadline it is
        # bounded by. Messaging and COSINE retain their existing specialist
        # policy, while genuine SINE-driving Blacklist evidence keeps RUN.
        keep_running = bool(
            break_state == "AWAITING_DURATION"
            or cosine_active
            or resource_surface is ResourceSurface.MESSAGING
            or blacklist_disposition is Disposition.HANDOFF
            or blacklist_actionable
        )
        if keep_running:
            return bool(
                self.services.sine.resume_escalation_after_activity(
                    candidate_uid=candidate_uid,
                    occurred_monotonic_ns=now_ns,
                    evidence_source=(
                        "normal_break_selector_pending"
                        if break_state == "AWAITING_DURATION"
                        else "monitor_non_activity_policy"
                    ),
                )
            )

        return bool(
            self.services.sine.pause_escalation_for_activity(
                candidate_uid=candidate_uid,
                occurred_monotonic_ns=now_ns,
                evidence_source="monitor_ordinary_activity",
            )
        )


    def _observe_mirl_for_context(self, context: MonitorContext) -> tuple[object, ...]:
        """Route exactly one MIRL path, including fail-closed break ownership."""

        if not self._normal_break_owns_pause():
            return tuple(self.services.mirl.observe(context) or ())

        from MIRL.mirl import RecoveryContext, RecoveryObservation

        normal_break = getattr(self.services, "normal_break", None)
        break_view = normal_break.snapshot() if normal_break is not None else None
        now_ns = context.foreground.observed_monotonic_ns
        return tuple(
            self.services.mirl.record_recovery_observation(
                RecoveryObservation(
                    context=RecoveryContext.NEUTRAL,
                    observed_monotonic_ns=now_ns,
                    observed_wall_time_utc=context.foreground.observed_wall_time_utc,
                    source="normal_break",
                    observation_token=(
                        f"normal-break:{_field(break_view, 'break_id', '')}:"
                        f"{context.foreground.sequence}:{now_ns}"
                    ),
                )
            )
            or ()
        )

    @staticmethod
    def _normal_break_fact_kind(fact: object) -> str:
        value = _field(fact, "kind", "")
        return str(getattr(value, "value", value) or "").upper()

    def _persist_normal_break_result(
        self,
        result: object,
        observation: ForegroundObservation | None = None,
    ) -> bool:
        """Drain and durably route exactly the facts returned by one operation."""

        result_facts = tuple(_field(result, "facts", ()) or ())
        drained = tuple(self.services.normal_break.drain_facts() or ())
        if drained != result_facts:
            raise RuntimeError(
                "Normal Break result facts did not match the authority outbox"
            )
        if not drained:
            return True
        if not self.services.storage.append_normal_break_facts(drained):
            return False
        for fact in drained:
            _telemetry(
                self.telemetry_queue,
                "normal_break_fact",
                observation=observation,
                message=_field(fact, "reason", "")
                or self._normal_break_fact_kind(fact),
                domain="normal_break",
                fact=fact,
            )
            self._console_history(
                f"[NORMAL BREAK] {self._normal_break_fact_kind(fact)}",
                observation,
            )
        return True

    def _advance_normal_break(
        self,
        now_ns: int,
        observation: ForegroundObservation | None,
    ) -> bool:
        """Advance a factual break and perform persistence-first SINE resume."""

        normal_break = getattr(self.services, "normal_break", None)
        if normal_break is None or not normal_break.active:
            return True
        result = normal_break.advance(now_monotonic_ns=now_ns)
        facts = tuple(_field(result, "facts", ()) or ())
        if not facts:
            return bool(_field(result, "accepted", False))
        terminal = facts[-1]
        if not self._persist_normal_break_result(result, observation):
            self._normal_break_resume_fault = True
            self.services.blacklist.set_paused(False)
            _telemetry(
                self.telemetry_queue,
                "normal_break_integrity_failure",
                observation=observation,
                message=(
                    "Normal Break ended but its terminal fact was not durable; "
                    "SINE resume is blocked fail-closed"
                ),
            )
            return False
        return self._resume_normal_break_terminal(terminal, observation)

    def _resume_normal_break_terminal(
        self,
        fact: object,
        observation: ForegroundObservation | None,
    ) -> bool:
        """Hand one durable completion back to the same SINE episode.

        The terminal fact opens the post-break acknowledgement gate; it does
        NOT request SINE 2.  Only the user's I'M BACK on that gate does.
        """

        kind = self._normal_break_fact_kind(fact)
        occurred_ns = int(_field(fact, "occurred_monotonic_ns", 0) or 0)
        accepted = bool(
            self.services.sine.enter_post_normal_break_return_gate(
                candidate_uid=_field(fact, "candidate_uid", ""),
                episode_uid=_field(fact, "episode_uid", ""),
                break_id=_field(fact, "break_id", ""),
                break_generation=_field(fact, "generation", 0),
                occurred_monotonic_ns=occurred_ns,
                completion_kind=kind,
            )
        )
        if not accepted:
            self._normal_break_resume_fault = True
            self.services.blacklist.set_paused(False)
            _telemetry(
                self.telemetry_queue,
                "normal_break_integrity_failure",
                observation=observation,
                message=(
                    "SINE refused the exact Normal Break completion; new "
                    "trigger founding remains blocked"
                ),
                break_id=_field(fact, "break_id", ""),
                generation=_field(fact, "generation", 0),
                completion_kind=kind,
            )
            return False

        try:
            for sine_fact in self.services.sine.advance(
                now_monotonic_ns=occurred_ns
            ):
                self._route_sine_fact(sine_fact, observation)
        finally:
            # Completion/STOP always unwinds the Blacklist pause, even if a
            # later telemetry/persistence route raises.
            self.services.blacklist.set_paused(False)
        self._normal_break_resume_fault = False
        _telemetry(
            self.telemetry_queue,
            "normal_break_resumed",
            observation=observation,
            message=(
                "The same SINE episode entered the post-break return gate; "
                "SINE 2 waits for the user's acknowledgement"
            ),
            break_id=_field(fact, "break_id", ""),
            generation=_field(fact, "generation", 0),
            episode_uid=_field(fact, "episode_uid", ""),
            candidate_uid=_field(fact, "candidate_uid", ""),
            occurred_monotonic_ns=occurred_ns,
            completion_kind=kind,
        )
        return True

    def _normal_break_selector_is_eligible(
        self,
        pending: object,
        sine: object,
        *,
        occurred_monotonic_ns: int,
    ) -> bool:
        """Validate the exact SINE-1 T-joint at one backend admission time."""

        from SINE.sine import SinePhase, SineStage

        state = _field(pending, "state", None)
        state_text = str(getattr(state, "value", state) or "").upper()
        deadline_ns = _field(sine, "stage_2_deadline_monotonic_ns", None)
        return bool(
            state_text == "AWAITING_DURATION"
            and type(occurred_monotonic_ns) is int
            and occurred_monotonic_ns > 0
            and type(deadline_ns) is int
            and occurred_monotonic_ns < deadline_ns
            and _field(sine, "episode_uid", "")
            == _field(pending, "episode_uid", "")
            and _field(sine, "candidate_uid", "")
            == _field(pending, "candidate_uid", "")
            and _field(sine, "popup_request_id", "")
            == _field(pending, "source_sine_popup_request_id", "")
            and _field(sine, "phase") is SinePhase.ACTIVE
            and _field(sine, "stage") is SineStage.SINE_1
            and _field(sine, "last_response", "") == "request_break"
            and not _field(sine, "study_mode", False)
            and not _field(sine, "protected_red_active", False)
            and not _field(sine, "normal_break_held", False)
        )

    def _cancel_pending_normal_break_selector(
        self,
        pending: object,
        *,
        occurred_monotonic_ns: int,
        observation: ForegroundObservation | None,
        reason: str,
    ) -> bool:
        """Retire one exact obsolete selector through its frozen authority API."""

        result = self.services.normal_break.cancel_duration(
            break_id=_field(pending, "break_id", ""),
            generation=_field(pending, "generation", 0),
            episode_uid=_field(pending, "episode_uid", ""),
            candidate_uid=_field(pending, "candidate_uid", ""),
            source_sine_popup_request_id=_field(
                pending, "source_sine_popup_request_id", ""
            ),
            occurred_monotonic_ns=occurred_monotonic_ns,
        )
        if not bool(_field(result, "accepted", False)):
            raise RuntimeError(
                "Normal Break refused cancellation of its exact obsolete selector"
            )
        if not self._persist_normal_break_result(result, observation):
            raise RuntimeError("Obsolete Normal Break selector cancellation was not durable")
        _telemetry(
            self.telemetry_queue,
            "normal_break_selector_retired",
            observation=observation,
            message="An obsolete Normal SINE-1 break selector was retired",
            reason=reason,
            episode_uid=_field(pending, "episode_uid", ""),
            candidate_uid=_field(pending, "candidate_uid", ""),
        )
        return True

    def _reconcile_pending_normal_break_selector(
        self,
        *,
        occurred_monotonic_ns: int,
        observation: ForegroundObservation | None,
    ) -> bool:
        """Cancel an abandoned selector as soon as its exact SINE-1 dies."""

        normal_break = getattr(self.services, "normal_break", None)
        if normal_break is None or normal_break.active:
            return True
        pending = normal_break.snapshot()
        state = _field(pending, "state", None)
        if str(getattr(state, "value", state) or "").upper() != "AWAITING_DURATION":
            return True
        sine = self.services.sine.live_view()
        if self._normal_break_selector_is_eligible(
            pending,
            sine,
            occurred_monotonic_ns=occurred_monotonic_ns,
        ):
            return True
        return self._cancel_pending_normal_break_selector(
            pending,
            occurred_monotonic_ns=occurred_monotonic_ns,
            observation=observation,
            reason="source_sine1_no_longer_eligible",
        )

    def _route_cosine_effect(
        self,
        effect: object,
        observation: ForegroundObservation | None = None,
    ) -> None:
        _telemetry(
            self.telemetry_queue,
            "cosine_effect",
            observation=observation,
            message=_field(effect, "message", "COSINE presentation effect"),
            effect=effect,
        )

    def _route_mine_effect(
        self,
        effect: object,
        observation: ForegroundObservation | None = None,
    ) -> None:
        _telemetry(
            self.telemetry_queue,
            "mine_effect",
            observation=observation,
            message=_field(effect, "message", "MINE presentation effect"),
            effect=effect,
        )

    def _route_cosecant_result(self,result,observation=None) -> None:
        for fact in tuple(_field(result,"facts",()) or ()):
            key=(fact.break_id,fact.sequence,_enum_text(fact.kind))
            if key not in self._cosecant_durable and fact not in self._cosecant_pending_facts:
                self._cosecant_pending_facts.append(fact)
        if self._cosecant_pending_facts:
            facts=tuple(self._cosecant_pending_facts)
            if self.services.storage.append_cosecant_facts(session_id=self.session_id,facts=facts):
                for fact in facts:
                    self._cosecant_durable.add((fact.break_id,fact.sequence,_enum_text(fact.kind)))
                    self._publish_domain_fact("cosecant",fact,observation)
                self._cosecant_pending_facts.clear()
        if self._cosecant_owns_break_return(_field(result,"snapshot")):
            self.services.blacklist.inhibit_normal_sine_watch()

    def _observe_cosecant_return(self, context: MonitorContext) -> None:
        from COSECANT_STUDY_MODE.cosecant import (
            CosecantFactKind,
            CosecantState,
            StudyReturnObservation,
        )

        snapshot = self.services.cosecant.snapshot()
        if _field(snapshot, "state") not in {
            CosecantState.BREAK_ACTIVE,
            CosecantState.BREAK_COMPLETE,
            CosecantState.BREAK_ALREADY_OVER,
            CosecantState.FINAL_LOCK,
            CosecantState.RETURN_CONFIRMING,
        }:
            return
        verdict = _field(context.resource_intent, "verdict")
        exact = self._exact_return_confirmed(
            context, _field(snapshot, "intended_return_target")
        )
        presence = self._presence_for(context, exact=exact)
        evidence_token = str(_field(verdict, "observation_token", "") or "")
        if not evidence_token:
            evidence_token = f"resource-intent-{context.foreground.sequence}"
        observation = StudyReturnObservation(
            presence=presence,
            study_block_id=str(_field(snapshot, "study_block_id", "")),
            break_id=str(_field(snapshot, "break_id", "")),
            context_token=str(_field(snapshot, "study_context_token", "")),
            observed_monotonic_ns=context.foreground.observed_monotonic_ns,
            source="RESOURCE_INTENT",
            evidence_token=evidence_token,
            fresh=bool(_field(context.resource_intent, "fresh", False)),
            exact_resource_confirmed=exact,
        )
        result = self.services.cosecant.observe_return(observation)
        self._route_cosecant_result(result, context.foreground)
        if any(
            _field(fact, "kind") is CosecantFactKind.RETURN_CONFIRMED
            for fact in tuple(_field(result, "facts", ()) or ())
        ):
            # The durable COSECANT handoff retires break-owned Blacklist dwell;
            # the next eligible observation starts a fresh intervention visit.
            self.services.blacklist.set_paused(False)
        self._advance_study_break()

    def _exact_return_confirmed(self,context,target) -> bool:
        if target is None:return False
        snapshot=context.resource_intent
        observation=_field(snapshot,"observation")
        if (not _field(snapshot,"fresh",False)
                or _field(observation,"observed_monotonic_ns")!=context.foreground.observed_monotonic_ns
                or _field(observation,"sequence")!=context.foreground.sequence):return False
        exact=self.services.resource_intent._study_exact_identity(snapshot)
        return bool(exact and target.matches_resource(exact))

    def _presence_for(self, context: MonitorContext, *, exact: bool) -> object:
        """Map one exact-return fact onto COSECANT's presence vocabulary.

        Only a proven exact resource is PRESENT.  Resource Intent keeps sole
        ownership of uncertainty, so an uncertain read stays UNCERTAIN rather
        than being reported as a definite absence.
        """

        from COSECANT_STUDY_MODE.cosecant import StudyPresence
        from CORE_ENGINE.resource_intent import ResourceIntent

        if exact:
            return StudyPresence.PRESENT
        verdict = _field(context.resource_intent, "verdict")
        if _field(verdict, "classification") is ResourceIntent.UNCERTAIN:
            return StudyPresence.UNCERTAIN
        return StudyPresence.ABSENT

    def _begin_trigger_persistence(self, candidate: object, context, blacklist_result) -> None:
        if self.session_id is None:
            raise RuntimeError("trigger candidate appeared before session start")
        candidate_uid = self.services.trigger.candidate_uid(candidate)
        if not candidate_uid:
            raise RuntimeError("trigger authority returned a candidate without UID")
        if not self._candidate_authority_current(candidate, context, blacklist_result):
            self.services.trigger.reject_candidate(
                candidate_uid=candidate_uid, reason="source_or_authority_lost_before_persistence"
            )
            return
        receipt = self.services.storage.persist_trigger(
            session_id=self.session_id,
            candidate=candidate,
        )
        receipt_id = _receipt_id(receipt)
        self._pending_trigger = PendingTriggerWorkflow(
            candidate_uid=candidate_uid,
            candidate=candidate,
            receipt_id=receipt_id,
            submitted_monotonic_ns=time.monotonic_ns(),
        )
        reason = str(_field(candidate, "reason", "trigger_candidate") or "trigger_candidate")
        self._console_history(
            f"[TRIGGER] candidate created | reason={reason} | uid={candidate_uid[:20]}... | persistence=PENDING"
        )
        self._apply_trigger_receipt(receipt, context, blacklist_result)

    # ------------------------------------------------------------------
    # Receipt consumption.  C12-D2.
    # ------------------------------------------------------------------
    #
    # A receipt exists so its OWNER can learn one transaction's fate.  Storage
    # consumes the receipts it owns end to end; the lifecycle receipts handed
    # back raw -- session open/close, emergency, profile learning, trigger
    # persistence -- belong to this coordinator, so only this coordinator can
    # say when it has finished reading one.  Without that, a long MYELIN
    # process accumulated one permanent in-memory record per session and per
    # trigger, all of them long since terminal and long since consumed.
    #
    # The rule is strict: release ONLY after the terminal state has been
    # observed AND its result fully processed.  Storage independently refuses
    # to forget a RUNNING receipt, so an outstanding transaction can never be
    # dropped through this path even by mistake.

    def _consume_receipt(self, receipt_id: str) -> None:
        """Release one terminal receipt this coordinator has finished with."""

        if not receipt_id:
            return
        try:
            self.services.storage.forget_receipt(receipt_id)
        except Exception:
            # Receipt bookkeeping is not domain truth.  A failure to release
            # an already-consumed record must never change a commit into an
            # error, so this deliberately does not touch cleanup errors.
            pass

    def _clear_pending_trigger(self) -> None:
        """Drop the pending workflow and consume its now-terminal receipt.

        Clearing and consuming are done together so the two can never drift:
        the receipt is released at exactly the moment nothing in Monitor
        refers to it any more.  While ``_pending_trigger`` still points at a
        workflow -- including a RUNNING one that a later ordered write may yet
        settle -- the receipt stays observable.
        """

        pending = self._pending_trigger
        self._pending_trigger = None
        if pending is not None:
            self._consume_receipt(pending.receipt_id)

    def _reconcile_pending_trigger(self, context, blacklist_result) -> None:
        pending = self._pending_trigger
        if pending is None:
            return
        receipt = self.services.storage.receipt(pending.receipt_id)
        if receipt is not None:
            self._apply_trigger_receipt(receipt, context, blacklist_result)

    def _candidate_authority_current(self, candidate, context, blacklist_result) -> bool:
        if self._study_owns_moment():
            return False
        from CORE_ENGINE.trigger import TriggerSource
        from CORE_ENGINE.resource_intent import OBSERVATION_FRESHNESS_NS
        if (
            context is None or self.stop_event.is_set() or self.pause_event.is_set()
            or self._emergency_requested or self._pending_study_start is not None
            or self._cosecant_owns_break_return()
            or self._sine_owns_intervention() or self._mine_owns_intervention()
            or self._normal_break_owns_pause()
            or not self._study_trigger_admission_open(context)
        ):
            return False
        now_ns = self._monotonic_ns()
        observed_ns = context.foreground.observed_monotonic_ns
        if not 0 <= now_ns - observed_ns <= OBSERVATION_FRESHNESS_NS:
            return False
        evidence = _field(candidate, "evidence")
        if _field(evidence, "source") is not TriggerSource.EXECUTIVE_BLACKLIST:
            return False
        return self.services.trigger.candidate_still_current(
            candidate=candidate, context=context, blacklist=blacklist_result
        )

    def _settle_trigger_without_intervention(self, pending, event_id, reason) -> None:
        if not self.services.trigger.settle_without_intervention(
            candidate_uid=pending.candidate_uid,
            operational_event_id=event_id, reason=reason,
        ):
            raise RuntimeError("Exact committed candidate settlement failed")
        self._clear_pending_trigger()
        _telemetry(
            self.telemetry_queue, "trigger_settled_without_intervention",
            candidate_uid=pending.candidate_uid, operational_event_id=event_id,
            message=reason,
        )

    def _apply_trigger_receipt(self, receipt: object, context, blacklist_result) -> None:
        pending = self._pending_trigger
        if pending is None:
            return
        if _receipt_id(receipt) != pending.receipt_id:
            raise RuntimeError("persistence receipt does not match pending trigger")

        state = _receipt_state(receipt)
        if state == RUNNING_STATE:
            return
        if state == COMMITTED_STATE:
            event_id = _receipt_result_id(receipt)
            if not pending.committed_seen_monotonic_ns:
                self._pending_trigger = replace(
                    pending, committed_seen_monotonic_ns=self._monotonic_ns()
                )
                return
            if context.foreground.observed_monotonic_ns <= pending.committed_seen_monotonic_ns:
                return
            if pending.superseded_by_break_id or not self._candidate_authority_current(
                pending.candidate, context, blacklist_result
            ):
                self._settle_trigger_without_intervention(
                    pending, event_id, "authority_lost_after_candidate_commit"
                )
                return
            token = self.services.mirl.prepare_trigger(
                candidate=pending.candidate, operational_event_id=event_id,
            )
            if token is None:
                self._settle_trigger_without_intervention(
                    pending, event_id, "mirl_prepare_refused"
                )
                return
            accepted_key = (pending.candidate_uid, event_id)
            try:
                if not self.services.mirl.prepared_token_current(
                    token, now_ns=self._monotonic_ns()
                ):
                    raise RuntimeError("MIRL preparation identity is not current")
                self._persist_mirl_events(self.services.mirl.drain_events())
                if not self._candidate_authority_current(
                    pending.candidate, context, blacklist_result
                ) or not self.services.mirl.prepared_token_current(
                    token, now_ns=self._monotonic_ns()
                ):
                    raise RuntimeError("Authority or MIRL token expired before handoff")
                if not self.services.trigger.confirm_durable_admission(
                    candidate_uid=pending.candidate_uid, operational_event_id=event_id
                ):
                    raise RuntimeError("Exact Trigger admission failed")
                accepted = self.services.sine.request_trigger(
                    candidate=pending.candidate, operational_event_id=event_id,
                    mirl_display_token=token,
                )
                sine = self.services.sine.live_view()
                facts = self.services.sine.advance(now_monotonic_ns=self._monotonic_ns())
                exact = bool(
                    accepted and _field(sine, "candidate_uid") == pending.candidate_uid
                    and _field(sine, "operational_event_id") == event_id
                    and any(
                        _fact_kind(fact) == "SINE_TRIGGER_ACCEPTED"
                        and _field(fact, "candidate_uid") == pending.candidate_uid
                        and _field(fact, "operational_event_id") == event_id
                        for fact in facts
                    )
                )
                if not exact:
                    raise RuntimeError("SINE did not accept the exact prepared handoff")
                self._route_sine_batch(facts, context.foreground)
                self._clear_pending_trigger()
            except Exception:
                self.services.sine.cancel_exact_candidate(
                    candidate_uid=pending.candidate_uid, operational_event_id=event_id,
                    reason="prepared_handoff_failed", now_ns=self._monotonic_ns(),
                )
                self.services.mirl.abandon_prepared_token(
                    token=token, reason="prepared_handoff_failed", now_ns=self._monotonic_ns()
                )
                if accepted_key not in self._durable_sine_admissions:
                    # No surface was dispatched: keep failed facts for diagnosis,
                    # but never replay an abandoned acceptance as a real admission.
                    self._failed_handoff_sine_facts = tuple(self._uncommitted_sine_facts)
                    self._uncommitted_sine_facts.clear()
                    self._settle_trigger_without_intervention(
                        pending, event_id, "prepared_handoff_failed"
                    )
                else:
                    self._clear_pending_trigger()
                raise
            _telemetry(
                self.telemetry_queue, "trigger",
                message="Exact SINE operational admission committed; display pending",
                badge="TRIGGER", feed_text="SINE admission accepted — display pending",
                tone="red", candidate_uid=pending.candidate_uid,
                operational_event_id=event_id,
            )
            return

        reason = _receipt_error(receipt) or f"persistence ended as {state}"
        rejected = self.services.trigger.reject_candidate(
            candidate_uid=pending.candidate_uid,
            reason="trigger_persistence_failed",
        )
        self._clear_pending_trigger()
        if not rejected:
            raise RuntimeError("failed trigger candidate could not be rejected")
        _telemetry(
            self.telemetry_queue,
            "trigger_processing_failed",
            message=reason,
            candidate_uid=pending.candidate_uid,
        )
        self._console_history(f"[TRIGGER] REJECTED | {reason}")


    def _persist_mirl_events(
        self,
        events: tuple[object, ...],
        observation: ForegroundObservation | None = None,
    ) -> None:
        events = tuple(dict(
            (str(_field(event, "event_id")), event)
            for event in (*self._uncommitted_mirl_events, *events)
        ).values())
        if not events:
            return
        self._uncommitted_mirl_events = events
        if not self.services.storage.append_mirl_events(events):
            raise RuntimeError("MIRL event batch was not durably accepted")
        self._uncommitted_mirl_events = ()
        for event in events:
            if _enum_text(_field(event, "event_name")).lower() == "episode_closed":
                self._durable_mirl_closes[(
                    _field(event, "episode_id"), _field(event, "candidate_uid"),
                    _field(event, "operational_event_id"),
                )] = str(_field(event, "reason", ""))
            self._route_mirl_sine_presentation(event, observation)
            self._publish_domain_fact("mirl", event, observation)

        # Phase 5 packages recovery only after RETURN_VERIFIED + closure.  Learn
        # from that package only after the matching MIRL event batch is durable.
        self._collect_verified_recovery_learning(observation)

    def _route_mirl_sine_presentation(
        self,
        event: object,
        observation: ForegroundObservation | None = None,
    ) -> None:
        """Coordinate presentation from durable MIRL entry/relapse facts only."""

        kind = str(_field(event, "kind", "") or "").strip().upper()
        candidate_uid = str(_field(event, "candidate_uid", "") or "").strip()
        if kind in {"MIRL_FIRST_DISPLAY_TIMED_OUT", "MIRL_FIRST_DISPLAY_REJECTED"}:
            self.services.sine.cancel_exact_candidate(
                candidate_uid=candidate_uid,
                operational_event_id=_field(event, "operational_event_id"),
                reason=kind.lower(),
                now_ns=max(1, int(_field(event, "occurred_monotonic_ns", 0))),
            )
        occurred_ns = int(_field(event, "occurred_monotonic_ns", 0) or 0)
        if not candidate_uid or occurred_ns <= 0:
            return

        accepted: bool | None = None
        action = ""
        if kind == "MIRL_RETURN_VERIFIED":
            action = "withheld"
            accepted = bool(
                self.services.sine.withhold_presentation_for_verified_return_entry(
                    candidate_uid=candidate_uid,
                    verified_monotonic_ns=occurred_ns,
                    evidence_source="mirl_return_verified",
                )
            )
        elif kind == "MIRL_RELAPSE_DETECTED":
            action = "resumed"
            accepted = bool(
                self.services.sine.resume_presentation_after_recovery_relapse(
                    candidate_uid=candidate_uid,
                    occurred_monotonic_ns=occurred_ns,
                    evidence_source="mirl_relapse_detected",
                )
            )

        if accepted is not None:
            _telemetry(
                self.telemetry_queue,
                "sine_recovery_presentation",
                observation=observation,
                message=(
                    f"SINE presentation {action} from durable MIRL fact"
                    if accepted
                    else f"SINE declined MIRL presentation action: {action}"
                ),
                mirl_event_kind=kind,
                candidate_uid=candidate_uid,
                accepted=accepted,
            )

    def _collect_verified_recovery_learning(
        self,
        observation: ForegroundObservation | None = None,
    ) -> None:
        packages = tuple(self.services.mirl.drain_verified_recovery_evidence() or ())
        if not packages:
            return
        if self.session_id is None or not self._profile_learning_key:
            raise RuntimeError("verified recovery arrived before profile-learning startup")

        for package in packages:
            package_session = int(_field(package, "session_id", 0) or 0)
            package_profile = str(_field(package, "profile_type", "") or "").strip().lower()
            candidate_uid = str(_field(package, "candidate_uid", "") or "").strip()
            if package_session != self.session_id:
                raise RuntimeError("MIRL recovery package belongs to another session")
            if package_profile != self._profile_learning_key:
                raise RuntimeError("MIRL recovery package belongs to another profile")
            if not candidate_uid:
                raise RuntimeError("MIRL recovery package has no candidate identity")
            if candidate_uid in self._learned_candidate_uids:
                raise RuntimeError("duplicate MIRL recovery package for one trigger candidate")

            # NOTE: ``verified_recovery_elapsed_seconds`` is NOT read here.
            # That field is part of one specific evidence generation's contract,
            # and its meaning is exactly what the version gate below decides
            # whether this monitor understands.  Enforcing it before that gate
            # would let a package from an unsupported generation fail the run on
            # a field contract that does not apply to it -- and would do so
            # before the factual recovery had even been released.  Identity
            # first, then release, then compatibility, then interpretation.

            # Factual recovery release.  MIRL is the recovery authority; this
            # is the only path allowed to end a SINE episode by verified
            # return.  A button press never reaches here -- MIRL refuses to
            # package a response, an unverified focus window, an interrupted
            # attempt or a relapse.  SINE independently re-validates the
            # timing and may still decline, which is not an error here.
            #
            # This deliberately runs BEFORE any lambda work.  Recovery and
            # learning are separate organs: a defect in the learning path must
            # never be able to retract a recovery fact MIRL already verified.
            verified_ns = int(
                _field(package, "return_verified_monotonic_ns", 0) or 0
            )
            released = False
            if verified_ns > 0:
                released = bool(
                    self.services.sine.confirm_verified_return(
                        candidate_uid=candidate_uid,
                        verified_monotonic_ns=verified_ns,
                        evidence_source="mirl",
                    )
                )
            _telemetry(
                self.telemetry_queue,
                "sine_verified_return",
                observation=observation,
                message=(
                    "SINE released by verified MIRL recovery"
                    if released
                    else "SINE did not accept the verified recovery release"
                ),
                candidate_uid=candidate_uid,
                episode_id=str(_field(package, "episode_id", "") or ""),
                verified_monotonic_ns=verified_ns,
                released=released,
            )

            # ---- learning path (independent of the release above) ----------

            # A user-selected sanctioned break contaminates Tr with policy
            # time. The behavioural recovery still releases SINE normally,
            # but this exact candidate can never contribute a lambda sample.
            if candidate_uid in self._normal_break_learning_ineligible_candidate_uids:
                _telemetry(
                    self.telemetry_queue,
                    "profile_learning_evidence_rejected",
                    observation=observation,
                    message=(
                        "Verified recovery was released, but this episode "
                        "contained a factual Normal Break; no Tr or lambda "
                        "sample was taken"
                    ),
                    reason="normal_break_present",
                    profile_key=self._profile_learning_key,
                    candidate_uid=candidate_uid,
                    episode_id=str(_field(package, "episode_id", "") or ""),
                    released=released,
                )
                continue

            # EVIDENCE-GENERATION GATE.
            #
            # The release above already happened, deliberately: an incompatible
            # LEARNING schema does not make the recovery any less factual, and
            # recovery must never be retracted by a learning-side decision.
            # Only the lambda/Tr contribution is gated here.
            #
            # ``verified_recovery_elapsed_seconds`` means different things in
            # different MIRL generations -- v1 anchored it at the verification
            # PROOF, v2 anchors it at the behavioural return ONSET.  Because
            # MYELIN is reconstructed by selecting files across generations, a
            # new monitor could be paired with an older MIRL and would then
            # feed a proof-based latency into lambda while storage stamped the
            # result as onset-based v2 -- data labelled with a generation it
            # did not come from, which is exactly what the provenance repair
            # exists to prevent.  So the version the package DECLARES is
            # checked against the version this monitor INDEPENDENTLY supports
            # (see LEARNABLE_MIRL_RECOVERY_EVIDENCE_VERSION) before it is
            # allowed to teach anything.  The producer never gets to answer
            # the consumer's question.
            package_schema_version = str(
                _field(package, "schema_version", "") or ""
            ).strip()
            if package_schema_version != LEARNABLE_MIRL_RECOVERY_EVIDENCE_VERSION:
                _telemetry(
                    self.telemetry_queue,
                    "profile_learning_evidence_rejected",
                    observation=observation,
                    message=(
                        "Verified MIRL recovery was released but its evidence "
                        "generation cannot be learned from; no Tr or lambda "
                        "sample was taken"
                    ),
                    reason="incompatible_mirl_recovery_evidence_version",
                    profile_key=self._profile_learning_key,
                    candidate_uid=candidate_uid,
                    episode_id=str(_field(package, "episode_id", "") or ""),
                    received_version=package_schema_version,
                    expected_version=LEARNABLE_MIRL_RECOVERY_EVIDENCE_VERSION,
                    released=released,
                )
                # No estimate, no sample, no learned-candidate mark, and
                # therefore no contribution to the session learning commit.
                # The latency is NOT reinterpreted and NOT corrected.
                continue

            # Only now is the Tr field contract known to apply: this package
            # declares the generation whose ``verified_recovery_elapsed_seconds``
            # means behavioural return ONSET.  A malformed value in a package we
            # DO understand is a real integrity failure and still raises -- but
            # the factual recovery above has already been released, so that
            # failure cannot retract it.
            recovery_seconds = float(
                _field(package, "verified_recovery_elapsed_seconds", 0.0) or 0.0
            )
            if not math.isfinite(recovery_seconds) or recovery_seconds <= 0.0:
                raise RuntimeError("MIRL recovery duration is not finite and positive")

            estimate = self.services.trigger.estimate_observed_lambda(
                candidate_uid=candidate_uid,
                verified_recovery_minutes=recovery_seconds / 60.0,
            )
            if estimate is None:
                raise RuntimeError(
                    "verified MIRL recovery could not be matched to a durably admitted trigger"
                )
            estimate_uid = str(_field(estimate, "candidate_uid", "") or "").strip()
            estimate_profile = str(_field(estimate, "profile_type", "") or "").strip().lower()
            observed_lambda = float(
                _field(estimate, "observed_decay_rate_per_minute", 0.0) or 0.0
            )
            if estimate_uid != candidate_uid:
                raise RuntimeError("observed lambda estimate changed candidate identity")
            if estimate_profile != self._profile_learning_key:
                raise RuntimeError("observed lambda estimate changed profile identity")
            if not math.isfinite(observed_lambda) or observed_lambda <= 0.0:
                raise RuntimeError("observed lambda estimate is not finite and positive")

            self._observed_lambda_estimates.append(estimate)
            self._learned_candidate_uids.add(candidate_uid)
            episode_id = str(_field(package, "episode_id", "") or "")
            _telemetry(
                self.telemetry_queue,
                "profile_learning_observation",
                observation=observation,
                message="Verified MIRL recovery produced one observed lambda sample",
                profile_key=self._profile_learning_key,
                candidate_uid=candidate_uid,
                episode_id=episode_id,
                verified_recovery_seconds=recovery_seconds,
                observed_lambda=observed_lambda,
            )
            self._console_history(
                f"[LEARNING] {_short_episode_id(episode_id)} | recovery={_duration_mmss(recovery_seconds)} "
                f"| observed lambda={observed_lambda:.6f}",
                observation,
            )

    def _commit_profile_learning_after_session_close(self) -> None:
        """Commit one session-average lambda and return latency for the NEXT session only.

        Return-latency and learned-lambda means are stored together as factual
        MBRM/Ebbinghaus evidence for the next session. Runtime personalization
        remains unauthorized until policy supplies a valid reference. Both are
        the mean of this exact
        session's evidence -- neither blends across sessions (that replace
        happens in ``PERSISTENCE.storage.update_profile_learning_session``).
        """

        if not self._observed_lambda_estimates:
            return
        if self.session_id is None or not self._profile_learning_key:
            raise RuntimeError("profile learning cannot commit without session identity")

        lambda_values = [
            float(_field(item, "observed_decay_rate_per_minute", 0.0) or 0.0)
            for item in self._observed_lambda_estimates
        ]
        if any((not math.isfinite(value) or value <= 0.0) for value in lambda_values):
            raise RuntimeError("session contains an invalid observed lambda")
        session_lambda = math.fsum(lambda_values) / len(lambda_values)
        if not math.isfinite(session_lambda) or session_lambda <= 0.0:
            raise RuntimeError("session lambda mean became invalid")

        # Actual verified MIRL return latency, not reconstructed through any
        # category-specific D0 -- see the MBRM correction note in trigger.py.
        recovery_minutes_values = [
            float(_field(item, "verified_recovery_minutes", 0.0) or 0.0)
            for item in self._observed_lambda_estimates
        ]
        if any(
            (not math.isfinite(value) or value <= 0.0)
            for value in recovery_minutes_values
        ):
            raise RuntimeError("session contains an invalid verified return latency")
        session_return_latency_seconds = (
            math.fsum(recovery_minutes_values) / len(recovery_minutes_values) * 60.0
        )
        if (
            not math.isfinite(session_return_latency_seconds)
            or session_return_latency_seconds <= 0.0
        ):
            raise RuntimeError("session return latency mean became invalid")

        receipt = self.services.storage.update_profile_learning_session(
            profile_key=self._profile_learning_key,
            session_id=self.session_id,
            session_lambda=session_lambda,
            session_return_latency_seconds=session_return_latency_seconds,
            valid_episode_count=len(lambda_values),
        )
        self._wait_for_commit(
            receipt,
            timeout_seconds=SHUTDOWN_PERSISTENCE_TIMEOUT_SECONDS,
            operation="profile learning update",
        )
        learned_state = self.services.storage.load_profile_learning(
            profile_key=self._profile_learning_key
        )
        next_lambda = _field(learned_state, "learned_lambda", None)
        next_return_latency_seconds = _field(
            learned_state, "learned_return_latency_seconds", None
        )
        valid_sessions = int(_field(learned_state, "valid_session_count", 0) or 0)
        valid_episodes = int(_field(learned_state, "valid_episode_count", 0) or 0)
        _telemetry(
            self.telemetry_queue,
            "profile_learning_committed",
            message="Completed-session recovery learning committed for the next session",
            profile_key=self._profile_learning_key,
            session_lambda=session_lambda,
            session_return_latency_seconds=session_return_latency_seconds,
            valid_episode_count=len(lambda_values),
            learned_lambda=next_lambda,
            learned_return_latency_seconds=next_return_latency_seconds,
            valid_sessions=valid_sessions,
            valid_episodes=valid_episodes,
            session_lambda_snapshot=self._session_decay_rate_per_minute,
        )
        self._console_history(
            f"[LEARNING] SESSION COMMITTED | session lambda={session_lambda:.6f} "
            f"| session Tr={session_return_latency_seconds:.1f}s "
            f"| next {self._profile_learning_key.upper()} lambda={float(next_lambda):.6f} "
            f"| next Tr={float(next_return_latency_seconds):.1f}s "
            f"| history={valid_sessions} sessions/{valid_episodes} episodes"
        )

    def _drain_resource_intent_facts(
        self,
        observation: ForegroundObservation | None,
    ) -> None:
        authority = getattr(self.services, "resource_intent", None)
        drain = getattr(authority, "drain_facts", None)
        if not callable(drain):
            return
        for fact in tuple(drain() or ()):
            self._publish_domain_fact("resource_intent", fact, observation)

    def _route_sine_batch(self, facts, observation=None) -> bool:
        self._uncommitted_sine_facts.extend(tuple(facts))
        accepted = True
        while self._uncommitted_sine_facts:
            fact = self._uncommitted_sine_facts[0]
            accepted = self._route_sine_fact(fact, observation) and accepted
            self._uncommitted_sine_facts.pop(0)
        return accepted

    def _route_sine_fact(
        self,
        fact: object,
        observation: ForegroundObservation | None,
    ) -> bool:
        kind = _fact_kind(fact).upper()
        occurred_ns = int(_field(fact, "occurred_monotonic_ns", 0) or 0)
        action_result_recorded = True

        fact_key = (
            _field(fact, "session_id"), _field(fact, "episode_uid"), kind,
            _field(fact, "popup_request_id"), _field(fact, "occurrence"), occurred_ns,
        )
        already_durable = fact_key in self._durable_sine_fact_keys
        if not already_durable:
            if not self.services.storage.append_sine_facts((fact,)):
                raise RuntimeError(f"SINE fact was not durably accepted: {kind}")
            self._durable_sine_fact_keys.add(fact_key)
        if kind == "SINE_TRIGGER_ACCEPTED" and not already_durable:
            key = (_field(fact, "candidate_uid"), _field(fact, "operational_event_id"))
            self._durable_sine_admissions.add(key)
            if not self.services.trigger.complete_operational_handoff(
                candidate_uid=key[0], operational_event_id=key[1]
            ):
                raise RuntimeError("Durable SINE acceptance did not match Trigger admission")
        if kind in {"SINE_EPISODE_CANCELLED", "SINE_EPISODE_RESOLVED", "SINE_EMERGENCY_STOPPED"}:
            self._durable_sine_terminals[str(_field(fact, "episode_uid", ""))] = str(
                _field(fact, "reason", "") or kind
            )
        if kind == "SINE_POPUP_CLOSED":
            self._durable_popup_closes.add((
                str(_field(fact, "episode_uid", "")),
                str(_field(fact, "popup_request_id", "")),
            ))

        if kind == "SINE_BREAK_REQUESTED":
            result = self.services.normal_break.request_duration(
                session_id=self.session_id,
                episode_uid=_field(fact, "episode_uid", ""),
                candidate_uid=_field(fact, "candidate_uid", ""),
                source_sine_popup_request_id=_field(
                    fact, "popup_request_id", ""
                ),
                requested_monotonic_ns=occurred_ns,
            )
            if not bool(_field(result, "accepted", False)):
                action_result_recorded = False
                _telemetry(
                    self.telemetry_queue,
                    "engine_command_rejected",
                    message=(
                        "Normal Break refused the exact SINE break request: "
                        f"{_field(result, 'message', 'unknown refusal')}"
                    ),
                    episode_uid=_field(fact, "episode_uid", ""),
                    candidate_uid=_field(fact, "candidate_uid", ""),
                )
            elif not self._persist_normal_break_result(result, observation):
                # The request never became durable and must not leave an
                # operable selector branch behind.
                pending = self.services.normal_break.snapshot()
                cancelled = self.services.normal_break.cancel_duration(
                    break_id=_field(pending, "break_id", ""),
                    generation=_field(pending, "generation", 0),
                    episode_uid=_field(pending, "episode_uid", ""),
                    candidate_uid=_field(pending, "candidate_uid", ""),
                    source_sine_popup_request_id=_field(
                        pending, "source_sine_popup_request_id", ""
                    ),
                    occurred_monotonic_ns=max(1, occurred_ns),
                )
                # The first write failed, so this is runtime cleanup rather
                # than a claim that cancellation became durable.
                self.services.normal_break.drain_facts()
                del cancelled
                raise RuntimeError(
                    "Normal Break duration request was not durably accepted"
                )


        # The popup's factual DISPLAYED event—not a schedule request—creates
        # MIRL episode evidence. Trigger also receives the exact same fact.
        if fact_key not in self._mirl_consumed_sine_keys:
            self.services.trigger.record_intervention_fact(fact)
            self.services.mirl.record_sine_fact(fact)
            self._mirl_consumed_sine_keys.add(fact_key)
        self._persist_mirl_events(self.services.mirl.drain_events(), observation)
        self._publish_domain_fact("sine", fact, observation)

        if kind == "SINE_STUDY_MATERIAL_REQUESTED":
            for generated in self.services.sine.advance(
                now_monotonic_ns=max(1, occurred_ns)
            ):
                self._route_sine_fact(generated, observation)
        return action_result_recorded

    def _publish_domain_fact(
        self,
        domain: str,
        fact: object,
        observation: ForegroundObservation | None,
    ) -> None:
        kind = (
            "sine_fact"
            if domain == "sine"
            else "cosecant_fact"
            if domain == "cosecant"
            else "resource_intent_fact"
            if domain == "resource_intent"
            else _fact_kind(fact).lower() or domain
        )
        semantic_fields = self._semantic_domain_telemetry(domain, fact)
        _telemetry(
            self.telemetry_queue,
            kind,
            observation=observation,
            message=_field(fact, "message", _field(fact, "detail", domain)),
            domain=domain,
            fact=fact,
            **semantic_fields,
        )
        self._publish_domain_console_fact(domain, fact, observation)

    def _semantic_domain_telemetry(
        self,
        domain: str,
        fact: object,
    ) -> dict[str, object]:
        """Map authoritative fact kinds to presentation-only feed semantics."""

        kind = _fact_kind(fact).upper()
        if domain == "resource_intent":
            if kind == "STUDY_UNCERTAINTY_STARTED":
                return {
                    "badge": "UNCERTAIN",
                    "feed_text": "50% UNCERTAIN — clarification clock started",
                    "tone": "amber",
                }
            if kind == "STUDY_CONFIRMATION_POPUP_DISPLAYED":
                prompt = int(_field(fact, "prompt_number", 0) or 0)
                return {
                    "badge": "STUDY CONFIRM",
                    "feed_text": f"5-minute clarification displayed — prompt {prompt}",
                    "tone": "amber",
                }
            if kind == "USER_CONFIRMED_STUDY":
                return {
                    "badge": "USER CONFIRM",
                    "feed_text": "THIS IS STUDY MATERIAL — SINE withheld",
                    "tone": "green",
                }
            if kind == "USER_CONFIRMED_OFF_TASK":
                return {
                    "badge": "USER CONFIRM",
                    "feed_text": "I'M COMING BACK — fresh SINE watch started",
                    "tone": "red",
                }

        if domain == "sine":
            if kind == "SINE_RETURN_INTENT_RECORDED":
                return {
                    "badge": "MONITOR",
                    "feed_text": "USER PRESSED — I'M BACK",
                    "tone": "cyan",
                }
            if kind == "SINE_POST_NORMAL_BREAK_RETURN_PENDING":
                return {
                    "badge": "RETURN GATE",
                    "feed_text": "BREAK ENDED — waiting for I'M BACK, SINE 2 not started",
                    "tone": "green",
                }
            if kind == "SINE_POST_BREAK_RETURN_ACKNOWLEDGED":
                return {
                    "badge": "RETURN GATE",
                    "feed_text": "I'M BACK acknowledged — same episode stays at SINE 1",
                    "tone": "green",
                }
            if kind == "SINE_STAGE_2_REARMED_AFTER_POST_BREAK_RETURN":
                live = self.services.sine.live_view()
                interval = _field(live, "stage_2_delay_seconds_applied", None)
                return {
                    "badge": "SINE",
                    "feed_text": (
                        "SINE 2 — window re-armed from I'M BACK for "
                        f"{_authoritative_seconds(interval)}"
                    ),
                    "tone": "amber",
                }
            if kind in {"SINE_STAGE_2_SCHEDULED", "SINE_STAGE_3_SCHEDULED"}:
                stage = 2 if kind == "SINE_STAGE_2_SCHEDULED" else 3
                live = self.services.sine.live_view()
                interval = _field(
                    live,
                    "stage_2_delay_seconds_applied"
                    if stage == 2
                    else "stage_3_delay_seconds_applied",
                    None,
                )
                return {
                    "badge": "SINE",
                    "feed_text": (
                        f"SINE {stage} — stage scheduled for "
                        f"{_authoritative_seconds(interval)}"
                    ),
                    "tone": "amber",
                }

        if domain == "mirl":
            if kind == "MIRL_RETURN_VERIFICATION_STARTED":
                return {
                    "badge": "RETURN INTENT",
                    "feed_text": "RETURN UNVERIFIED — verification started",
                    "tone": "amber",
                }
            if kind == "MIRL_RETURN_VERIFIED":
                return {
                    "badge": "RETURNED",
                    "feed_text": "USER RETURNED — WELCOME BACK TO FOCUS",
                    "tone": "green",
                }
            if kind == "MIRL_CLOSURE_CONFIRMATION_STARTED":
                return {
                    "badge": "MIRL",
                    "feed_text": (
                        "RETURN CONFIRMED — CLOSURE INITIATED FOR "
                        f"{_authoritative_seconds(_field(fact, 'target_seconds', None))}"
                    ),
                    "tone": "cyan",
                }
            if kind == "MIRL_SINE_TERMINATED" and _field(fact, "reason") == "STUDY_MODE_ACTIVATED":
                return {
                    "badge": "MIRL", "feed_text": "Study Mode started", "tone": "cyan",
                }
            if kind == "MIRL_EPISODE_CLOSED":
                outcome = str(_field(fact, "reason", "") or "")
                return {
                    "badge": "MIRL",
                    "feed_text": f"EPISODE CLOSED — {outcome}" if outcome else "EPISODE CLOSED",
                    "tone": "green" if outcome == "RETURNED" else "cyan",
                }
        return {}

    def _prepare_dwell_telemetry(self, snapshot: object) -> None:
        """Prepare one bounded DWELL row when Blacklist starts a fresh visit."""

        self._pending_dwell_telemetry = None
        if not bool(_field(snapshot, "restarted", False)):
            return
        if bool(_field(snapshot, "sine_watch_inhibited", False)) or bool(
            _field(snapshot, "study_context_active", False)
        ):
            return
        verdict = _field(snapshot, "verdict")
        if _enum_text(_field(verdict, "disposition", "")).lower() not in {
            "accused",
            "unknown",
        }:
            return
        label = str(
            _field(verdict, "display_label", "")
            or _field(verdict, "platform_key", "")
            or "Social resource"
        ).strip()
        self._pending_dwell_telemetry = {
            "app_override": label,
            "message": "Fresh actionable resource dwell began",
            "badge": "DWELL",
            "feed_text": f"{label.upper()} — person is dwelling",
            "tone": "violet",
        }

    def _publish_domain_console_fact(
        self,
        domain: str,
        fact: object,
        observation: ForegroundObservation | None,
    ) -> None:
        kind = _fact_kind(fact).upper()
        stage = int(_field(fact, "stage", _field(fact, "sine_stage", 0)) or 0)
        occurrence = int(_field(fact, "occurrence", _field(fact, "sine_occurrence", 0)) or 0)
        episode_id = str(_field(fact, "episode_id", "") or "")
        short_episode = _short_episode_id(episode_id)
        elapsed = float(_field(fact, "elapsed_seconds", 0.0) or 0.0)
        target = float(_field(fact, "target_seconds", 0.0) or 0.0)
        reason = str(_field(fact, "reason", "") or "")
        response = str(_field(fact, "response", "") or "")

        if domain == "mirl":
            # Internal trigger preparation is intentionally silent.  Chief's
            # contract says MIRL becomes visible only after factual SINE 1.
            if kind == "MIRL_TRIGGER_PREPARED":
                return
            if kind == "MIRL_EPISODE_CREATED":
                line = f"[MIRL] EPISODE STARTED | {short_episode} | factual SINE 1 display"
            elif kind == "MIRL_RETURN_INTENT_RECORDED":
                line = f"[MIRL] {short_episode} | I'M BACK intent recorded | recovery UNVERIFIED"
            elif kind == "MIRL_RETURN_VERIFICATION_STARTED":
                line = (
                    f"[RETURN] recovery detected | {short_episode} | initial confirmation "
                    f"00:00 / {_duration_mmss(target)}"
                )
            elif kind == "MIRL_RETURN_UNVERIFIED":
                line = f"[RETURN] {short_episode} | focus present | recovery entry UNVERIFIED"
            elif kind == "MIRL_RETURN_VERIFICATION_INTERRUPTED":
                line = (
                    f"[RETURN] initial confirmation FAILED | {short_episode} | "
                    f"{_duration_mmss(elapsed)} / {_duration_mmss(target)}"
                )
            elif kind == "MIRL_RETURN_VERIFICATION_COMPLETED":
                line = (
                    f"[RETURN] initial confirmation PASSED | {short_episode} | "
                    f"{_duration_mmss(elapsed)} / {_duration_mmss(target)}"
                )
            elif kind == "MIRL_RETURN_VERIFIED":
                line = (
                    f"[RETURNED] RECOVERY ENTRY CONFIRMED | {short_episode} | "
                    "STABILITY UNVERIFIED"
                )
            elif kind == "MIRL_CLOSURE_CONFIRMATION_STARTED":
                line = (
                    f"[MIRL] stability verification STARTED | {short_episode} | "
                    f"target={_duration_mmss(target)}"
                )
            elif kind == "MIRL_CLOSURE_CONFIRMATION_INTERRUPTED":
                line = (
                    f"[MIRL] stability verification FAILED | {short_episode} | "
                    f"{_duration_mmss(elapsed)} / {_duration_mmss(target)}"
                )
            elif kind == "MIRL_RELAPSE_DETECTED":
                line = f"[MIRL] RELAPSE DETECTED | {short_episode} | reason={reason or 'distraction'}"
            elif kind == "MIRL_EPISODE_RESUMED":
                line = f"[MIRL] EPISODE RESUMED | {short_episode} | waiting for a new recovery entry"
            elif kind == "MIRL_CLOSURE_CONFIRMATION_COMPLETED":
                line = (
                    f"[MIRL] stability verification PASSED | {short_episode} | "
                    f"{_duration_mmss(elapsed)} / {_duration_mmss(target)}"
                )
            elif kind == "MIRL_EPISODE_CLOSED":
                line = f"[MIRL] RETURN VERIFIED | {short_episode} | EPISODE CLOSED | outcome={reason or 'RETURNED'}"
            elif kind == "MIRL_EVIDENCE_GAP":
                line = f"[MIRL] EVIDENCE GAP | {short_episode} | elapsed={_duration_mmss(elapsed)}"
            elif kind == "MIRL_EMERGENCY_STOPPED":
                line = f"[MIRL] EMERGENCY STOPPED | {short_episode}"
            else:
                return
            self._console_history(line, observation)
            return

        if domain == "sine":
            if kind == "SINE_TRIGGER_ACCEPTED":
                line = f"[SINE] trigger accepted | next=SINE 1"
            elif kind == "SINE_POPUP_REQUESTED":
                line = f"[SINE] SINE {stage} REQUESTED | occurrence={occurrence or 1}"
            elif kind == "SINE_DISPLAYED":
                line = f"[SINE] SINE {stage} DISPLAYED | occurrence={occurrence or 1}"
            elif kind == "SINE_RESPONSE_RECORDED":
                line = f"[SINE] SINE {stage} response={response or 'UNKNOWN'}"
            elif kind == "SINE_RETURN_INTENT_RECORDED":
                line = f"[SINE] I'M BACK received | SINE {stage} | waiting for factual recovery"
            elif kind == "SINE_POST_NORMAL_BREAK_RETURN_PENDING":
                line = (
                    "[SINE] POST-BREAK RETURN PENDING | "
                    f"{reason or 'normal_break_ended'} | NO SINE 2 REQUESTED"
                )
            elif kind == "SINE_POST_BREAK_RETURN_GATE_REQUESTED":
                line = f"[SINE] WELCOME BACK REQUESTED | occurrence={occurrence or 1}"
            elif kind == "SINE_POST_BREAK_RETURN_GATE_DISPLAYED":
                line = (
                    f"[SINE] WELCOME BACK DISPLAYED | occurrence={occurrence or 1} | "
                    "NO SINE STAGE CONSUMED | NO SINE 3 DEADLINE"
                )
            elif kind == "SINE_POST_BREAK_RETURN_GATE_SURFACE_LOST":
                line = "[SINE] WELCOME BACK surface lost | restoring acknowledgement gate"
            elif kind == "SINE_POST_BREAK_RETURN_ACKNOWLEDGED":
                line = (
                    "[SINE] I'M BACK ACKNOWLEDGED | same episode stays at SINE 1"
                )
            elif kind == "SINE_STAGE_2_REARMED_AFTER_POST_BREAK_RETURN":
                live = self.services.sine.live_view()
                interval = _field(live, "stage_2_delay_seconds_applied", None)
                line = (
                    "[SINE] NEXT=SINE 2 | window re-armed from I'M BACK for "
                    f"{_authoritative_seconds(interval)}"
                )
            elif kind == "SINE_STAGE_2_TIMING_BOUND":
                line = f"[SINE] SINE 2 timing bound | source={reason or 'policy'}"
            elif kind == "SINE_STAGE_2_SCHEDULED":
                line = "[SINE] NEXT=SINE 2 | deadline armed"
            elif kind == "SINE_STAGE_3_SCHEDULED":
                line = "[SINE] NEXT=SINE 3 | deadline armed"
            elif kind in {"SINE_POPUP_CLOSED", "SINE_POPUP_EXPIRED"}:
                what = kind.removeprefix("SINE_POPUP_").lower()
                # The acknowledgement gate carries SineStage.NONE, so naming it
                # by stage ordinal would print a "SINE 0" that does not exist.
                line = (
                    f"[SINE] WELCOME BACK popup {what}"
                    if stage == 0
                    else f"[SINE] SINE {stage} popup {what}"
                )
            elif kind == "SINE_PROTECTED_RED_ACTIVATED":
                line = "[SINE] SINE 3 PROTECTED RED ACTIVE"
            elif kind == "SINE_EPISODE_RESOLVED":
                line = "[SINE] intervention episode resolved"
            elif kind == "SINE_EPISODE_CANCELLED":
                line = f"[SINE] intervention episode cancelled | reason={reason or 'unknown'}"
            else:
                return
            self._console_history(line, observation)

    def _diagnose_browser_evidence(self, context: MonitorContext) -> None:
        """Surface WHY a browser tab never becomes a certified SINE candidate.

        ``[SINE WATCH]`` only ever prints once dwell tracking is actually
        watching (see ``_publish_console_live_status`` above), so an
        uncertified browser address bar -- Executive Blacklist's platform
        identity requires certified URL evidence, never the window title,
        per ``CORE_ENGINE/blacklist.py`` -- is otherwise completely silent
        at the console: indistinguishable from "nothing is happening" even
        while a distraction site sits in the foreground the whole time.
        This exposes the real UIA read failure (or its absence) instead.
        """

        from CORE_ENGINE.browser import BrowserUrlReadStatus

        evidence = context.browser_evidence
        if not bool(_field(evidence, "supported_browser", False)):
            self._last_browser_diagnostic_signature = None
            return
        status = _field(evidence, "status", None)
        if status is BrowserUrlReadStatus.OK:
            self._last_browser_diagnostic_signature = None
            return
        process_name = str(_field(context.foreground, "process_name", "") or "")
        status_text = status.value if hasattr(status, "value") else str(status or "")
        reason = str(_field(evidence, "reason", "") or "")
        label = str(_field(evidence, "browser_label", "") or process_name)
        signature = (process_name, status_text, reason)
        if signature == self._last_browser_diagnostic_signature:
            return
        self._last_browser_diagnostic_signature = signature
        self._console_history(
            f"[BROWSER EVIDENCE] {label} address bar not certified | "
            f"status={status_text} | reason={reason or 'no reason supplied'}",
            context.foreground,
        )

    def _console_classification(
        self,
        category: str,
        content: str,
        seconds: float,
        observation: ForegroundObservation | None,
    ) -> None:
        signature = (category, content, int(max(0.0, float(seconds))))
        if signature == self._last_activity_classification_signature:
            return
        self._last_activity_classification_signature = signature
        self._console_history(
            f"[ MYELIN ] [ {category} ] - {content} [ {_duration_human(seconds)} ]",
            observation,
        )

    def _publish_activity_classification(self, context: MonitorContext) -> None:
        """Emit the locked ``[ MYELIN ] [ CATEGORY ] - <content> [ TIME ]`` line.

        Presentation only: reads already-computed verdicts from Resource
        Intent, COSINE and Executive Blacklist and formats them for the
        console. It reclassifies nothing and does not touch SINE/COSINE/
        MIRL/Resource Intent truth.

        Precedence -- exact resource, not platform, drives STUDY:
        1. Resource Intent confirmed STUDY_ALIGNED (exact resource, not
           just "Study Mode is on") -> STUDY, exempt from SINE.
        2. This sample's certified OTT platform (not episode memory) -> OTT.
        3. Resource Intent's MESSAGING surface (native WhatsApp/Discord/
           Telegram/Slack/Teams by process, or a certified browser
           messaging route such as Instagram/Facebook/LinkedIn/X Direct
           Messages) -> MESSAGING (display only; messaging dwell/SINE
           policy is a separate, not-yet-built organ).
        4. Executive Blacklist ACCUSED/UNKNOWN (actionable) -> SOCIAL,
           including YouTube long-form and Shorts alike.
        A changed resource invalidates a prior STUDY line on the very next
        poll, because Resource Intent re-derives ``classification`` from
        the current observation every cycle -- it is never sticky here.
        """

        from CORE_ENGINE.resource_intent import ResourceIntent, ResourceSurface
        from COSINE.cosine import PLATFORM_LABELS

        resource_view = self.services.resource_intent.live_view()

        if (
            resource_view is not None
            and _field(resource_view, "classification", None) is ResourceIntent.STUDY_ALIGNED
        ):
            title = str(_field(resource_view, "display_title", "") or "").strip()
            # Total current Study-session time (StudyRuntime.elapsed_seconds),
            # not off-task dwell: ResourceIntentLiveView.dwell_elapsed_seconds
            # is verdict.off_task_dwell_seconds, which Resource Intent forces
            # to 0.0 whenever allowance_match is True -- exactly the STUDY_
            # ALIGNED case, so it would always read 00m 00s here.
            study_snapshot = self.services.study.snapshot()
            elapsed = float(_field(study_snapshot, "elapsed_seconds", 0.0) or 0.0)
            self._console_classification(
                "STUDY",
                f"{title or 'Study resource'} - EXEMPTED FROM SINE",
                elapsed,
                context.foreground,
            )
            self._messaging_dwell_key = ""
            return

        platform = _field(context, "cosine_platform")
        if platform is not None:
            platform_key = _field(platform, "platform_key", "")
            label = PLATFORM_LABELS.get(platform_key, "")
            if label:
                title = str(_field(platform, "content_title", "") or "").strip()
                # The snapshot supplies duration only AFTER current identity
                # is proved. Never borrow another platform's label or time.
                cosine_snapshot = self.services.cosine.snapshot(
                    now_ns=context.foreground.observed_monotonic_ns
                )
                elapsed = 0.0
                if _field(cosine_snapshot, "current_platform_key", "") == platform_key:
                    elapsed = float(_field(cosine_snapshot, "current_platform_seconds", 0.0) or 0.0)
                self._console_classification(
                    "OTT", f"{label}: {title}" if title else label, elapsed, context.foreground
                )
                self._messaging_dwell_key = ""
                return

        # MESSAGING evidence comes from Resource Intent's identity.surface
        # (native process recognition for whatsapp/discord/telegram/slack/
        # teams -- see CORE_ENGINE.resource_intent._MESSAGING_PROCESSES --
        # or a certified browser CONFIRMED_MESSAGING_PAGE route), not from
        # Executive Blacklist: blacklist.py's PLATFORM_REGISTRY has no
        # messaging entries at all, so native messaging apps could never
        # produce this line through blacklist. Resource Intent's identity.
        # surface is populated independently of ``classification`` (it is
        # computed before the "no active Study block" early return), so it
        # stays correct with or without Study Mode.
        if (
            resource_view is not None
            and _field(resource_view, "resource_surface", None) is ResourceSurface.MESSAGING
        ):
            process = str(_field(resource_view, "process_name", "") or "").strip().casefold()
            label = self._messaging_platform_label(context, process)
            if label:
                # Keyed on the resolved display label, not the raw process:
                # for browser messaging, ``process`` is always the browser
                # itself (chrome/msedge), so keying on it would keep one
                # timer running across a switch from Instagram Direct to
                # Facebook Messages in the same browser instead of resetting
                # it -- [TIME] means continuous time on the displayed
                # platform shown in [content name], not "any messaging app".
                now_ns = context.foreground.observed_monotonic_ns
                elapsed = self._messaging_dwell_seconds(key=label, now_ns=now_ns)
                self._console_classification("MESSAGING", label, elapsed, context.foreground)
                return

        self._messaging_dwell_key = ""

        blacklist = self.services.blacklist.live_view()
        if blacklist is not None:
            label = str(_field(blacklist, "resource_label", "") or "").strip()
            if label:
                title = str(_field(blacklist, "resource_title", "") or "").strip()
                elapsed = float(_field(blacklist, "dwell_elapsed_seconds", 0.0) or 0.0)
                content = f"{label}: {title}" if title else label
                disposition = _enum_text(_field(blacklist, "disposition", "")).lower()
                if disposition in {"accused", "unknown"}:
                    self._console_classification("SOCIAL", content, elapsed, context.foreground)
                    return

        self._last_activity_classification_signature = None

    def _messaging_platform_label(self, context: MonitorContext, process: str) -> str:
        """Return the correct messaging platform label -- never the browser.

        ``ResourceIntentLiveView`` exposes only ``process_name`` (chrome/
        msedge for a browser tab), not the certified platform, so using it
        alone for a browser messaging route (Instagram/Facebook/LinkedIn/X
        Direct Messages, certified via CORE_ENGINE.browser's
        CONFIRMED_MESSAGING_PAGE) would print "Chrome" as the messaging
        platform. Resource Intent's own identity.surface for that exact
        case is set from the same certified evidence this reads here (see
        ``resource_intent.build_resource_identity`` /
        ``_surface_from_browser``), so the two stay in agreement. Native
        messaging apps (WhatsApp/Discord/Telegram/Slack/Teams) have no
        browser evidence at all and fall through to the process-name label.
        """

        browser_snapshot = context.browser_evidence
        if bool(_field(browser_snapshot, "host_authoritative", False)):
            evidence = _field(browser_snapshot, "evidence")
            label = str(_field(evidence, "platform_label", "") or "").strip()
            if label:
                return label
        stripped = process[:-4] if process.endswith(".exe") else process
        return MESSAGING_PROCESS_LABELS.get(stripped, stripped)

    def _messaging_dwell_seconds(self, *, key: str, now_ns: int) -> float:
        """Presentation-only continuous-messaging timer for the console line.

        Neither Resource Intent nor Executive Blacklist track a messaging
        dwell duration (messaging has its own future, not-yet-built policy
        organ -- see the canonical mapping's excluded "MINE family"). This
        is a local display timer only: it feeds no SINE/trigger/MIRL
        authority, mirroring Executive Blacklist's own continuity-gap
        pattern at a much smaller scope.
        """

        gap_ns = now_ns - self._messaging_dwell_last_ns if self._messaging_dwell_last_ns >= 0 else 0
        continuity_broken = bool(
            self._messaging_dwell_started_ns < 0
            or key != self._messaging_dwell_key
            or gap_ns > 6 * NANOSECONDS_PER_SECOND
            or gap_ns < 0
        )
        if continuity_broken:
            self._messaging_dwell_key = key
            self._messaging_dwell_started_ns = now_ns
        self._messaging_dwell_last_ns = now_ns
        return max(0.0, (now_ns - self._messaging_dwell_started_ns) / NANOSECONDS_PER_SECOND)

    def _publish_console_live_status(self, context: MonitorContext) -> None:
        blacklist = self.services.blacklist.live_view()
        if blacklist is not None:
            state = _enum_text(_field(blacklist, "state", "")).lower()
            elapsed = float(_field(blacklist, "dwell_elapsed_seconds", 0.0) or 0.0)
            target = float(_field(blacklist, "dwell_target_seconds", 0.0) or 0.0)
            label = str(_field(blacklist, "resource_label", "") or "").strip()
            title = str(_field(blacklist, "resource_title", "") or "").strip()
            confidence = _enum_text(_field(blacklist, "confidence", "")).upper() or "NONE"
            next_stage = _field(blacklist, "next_sine_stage", None)
            if label and state in {"watching", "threshold_reached", "submitted"} and target > 0:
                cosecant = self.services.cosecant.snapshot()
                cosecant_owned = self._cosecant_owns_break_return(cosecant)
                cosecant_state = _enum_text(_field(cosecant, "state", "")).upper()
                signature = (
                    label,
                    state,
                    int(elapsed),
                    int(target),
                    next_stage,
                    title,
                    cosecant_owned,
                    cosecant_state,
                    context.study_owned,
                )
                if signature != self._last_blacklist_console_signature:
                    self._last_blacklist_console_signature = signature
                    next_text = f"SINE {int(next_stage)}" if type(next_stage) is int else (
                        "TRIGGER" if state in {"threshold_reached", "submitted"} else "—"
                    )
                    resource = label if not title else f"{label} - {title[:70]}"
                    if cosecant_owned:
                        owner_label = "BREAK" if cosecant_state == "BREAK_ACTIVE" else "RETURN"
                        self._console_history(
                            f"[COSECANT {owner_label}] {resource} | STATE={cosecant_state} | "
                            f"BLACKLIST={confidence} (DESCRIPTIVE) | "
                            "NEXT=RETURN CONTROL",
                            context.foreground,
                        )
                    elif context.study_owned:
                        verdict = _field(context.resource_intent, "verdict")
                        self._console_history(
                            f"[STUDY WATCH] {resource} | BLACKLIST={confidence} (DESCRIPTIVE) | "
                            f"STUDY={_enum_text(_field(verdict, 'classification', ''))}",
                            context.foreground,
                        )
                    else:
                        self._console_history(
                            f"[SINE WATCH] {resource} | BLACKLIST={confidence} | "
                            f"{_duration_mmss(elapsed)} / {_duration_mmss(target)} | NEXT={next_text}",
                            context.foreground,
                        )
            else:
                self._last_blacklist_console_signature = None
        else:
            self._last_blacklist_console_signature = None

        self._diagnose_browser_evidence(context)
        self._publish_activity_classification(context)

        mirl = self.services.mirl.live_view()
        phase = _enum_text(_field(mirl, "phase", "")).upper()
        episode_id = str(_field(mirl, "episode_id", "") or "")
        if phase == "RETURN_VERIFICATION" and episode_id:
            elapsed = float(_field(mirl, "return_verification_elapsed_seconds", 0.0) or 0.0)
            target = float(_field(mirl, "return_verification_target_seconds", 0.0) or 0.0)
            signature = (phase, episode_id, int(elapsed), int(target))
            if signature != self._last_mirl_console_signature:
                self._last_mirl_console_signature = signature
                self._console_history(
                    f"[RETURN] initial confirmation {_duration_mmss(elapsed)} / {_duration_mmss(target)} "
                    f"| {_short_episode_id(episode_id)}",
                    context.foreground,
                )
        elif phase == "CLOSURE_CONFIRMATION" and episode_id:
            elapsed = float(_field(mirl, "closure_confirmation_elapsed_seconds", 0.0) or 0.0)
            target = float(_field(mirl, "closure_confirmation_target_seconds", 0.0) or 0.0)
            signature = (phase, episode_id, int(elapsed), int(target))
            if signature != self._last_mirl_console_signature:
                self._last_mirl_console_signature = signature
                self._console_history(
                    f"[MIRL] stability {_duration_mmss(elapsed)} / {_duration_mmss(target)} "
                    f"| {_short_episode_id(episode_id)} | final return UNVERIFIED",
                    context.foreground,
                )
        else:
            self._last_mirl_console_signature = None

    def _publish_live_views(
        self,
        context: MonitorContext,
        blacklist_result: object | None = None,
    ) -> None:
        foreground = context.foreground
        # One immutable Resource Intent projection is shared by its dedicated
        # signal and the control bundle.  Some presentation-only uncertainty
        # fields are clock-derived, so two reads could otherwise differ within
        # one observation and defeat the category identity guard.
        resource_live_view = self.services.resource_intent.live_view()
        display_app = _activity_display_app(context)
        badge, tone = self._activity_telemetry_semantics(
            context,
            resource_view=resource_live_view,
        )
        identity = (
            foreground.hwnd,
            foreground.process_name,
            foreground.window_title,
            display_app,
            badge,
            tone,
        )
        if identity != self._last_foreground_identity:
            self._last_foreground_identity = identity
            _telemetry(
                self.telemetry_queue,
                "activity",
                observation=foreground,
                app_override=display_app,
                message="Foreground activity observed",
                badge=badge,
                tone=tone,
            )

        pending_dwell = self._pending_dwell_telemetry
        self._pending_dwell_telemetry = None
        if pending_dwell is not None:
            _telemetry(
                self.telemetry_queue,
                "dwell",
                observation=foreground,
                **pending_dwell,
            )

        _telemetry(
            self.telemetry_queue,
            "resource_intent_live_status",
            observation=foreground,
            live_view=resource_live_view,
        )
        _telemetry(
            self.telemetry_queue,
            "sine_watch_status",
            observation=foreground,
            live_view=self.services.sine.live_view(),
        )
        # Phase 1I.  Take ONE immutable COSINE snapshot for this cycle and
        # reuse it for the live view, the transition signature and the prepared
        # control view.  Reading the runtime once means those three consumers
        # can never disagree with each other by a few hundred nanoseconds.
        cosine_snapshot = self.services.cosine.snapshot(
            now_ns=foreground.observed_monotonic_ns
        )
        _telemetry(
            self.telemetry_queue,
            "cosine_live_status",
            observation=foreground,
            live_view=cosine_snapshot,
        )
        self._publish_cosine_transition(cosine_snapshot, foreground)
        mine_authority = getattr(self, "_mine_authority", None)
        mine_snapshot = (
            mine_authority.snapshot(now_ns=foreground.observed_monotonic_ns)
            if mine_authority is not None
            else None
        )
        if mine_snapshot is not None:
            _telemetry(
                self.telemetry_queue,
                "mine_watch_status",
                observation=foreground,
                live_view=mine_snapshot,
            )
            self._publish_mine_transition(mine_snapshot, foreground)
        _telemetry(
            self.telemetry_queue,
            "mirl_health_status",
            observation=foreground,
            live_view=self.services.mirl.live_view(),
        )
        _telemetry(
            self.telemetry_queue,
            "study_runtime_view",
            observation=foreground,
            live_view=self.services.study.snapshot(),
        )
        _telemetry(
            self.telemetry_queue,
            "cosecant_view",
            observation=foreground,
            live_view=self.services.cosecant.snapshot(),
        )
        red_active = bool(self.services.sine.protected_red_active())
        if red_active != self._last_red_state:
            self._last_red_state = red_active
            _telemetry(
                self.telemetry_queue,
                "protected_red_status",
                observation=foreground,
                active=red_active,
            )

        _telemetry(
            self.telemetry_queue,
            "control_view",
            observation=foreground,
            live_view={
                "session_id": self.session_id,
                "foreground": foreground,
                "resource_intent": resource_live_view,
                "study_app_category": _study_app_category_metadata(
                    context,
                    blacklist_result,
                    session_id=self.session_id,
                ),
                "blacklist": self.services.blacklist.live_view(),
                "trigger": self.services.trigger.live_view(),
                "sine": self.services.sine.live_view(),
                "cosine": cosine_snapshot,
                "mine": mine_snapshot,
                "mirl": self.services.mirl.live_view(),
            },
        )
        self._publish_console_live_status(context)

    def _publish_cosine_transition(
        self,
        snapshot: object,
        observation: ForegroundObservation | None,
    ) -> None:
        """Publish one append-only COSINE row per MEANINGFUL transition.

        Monitor stays the semantics/preparation boundary: this reads the
        snapshot COSINE already produced and decides nothing about physiology.
        It starts no timer, changes no phase and calls nothing on the runtime.

        The signature deliberately contains only facts whose change is an
        actual event -- phase, certified platform, Hopper count, the committed
        break length, Global Pause, final-callback visibility, closure outcome
        and durable health.  Every high-frequency value is excluded on purpose:
        the countdowns (initial gate, return intent, break, return
        verification, closure confirmation), ``foreground_ott_seconds``,
        ``current_platform_seconds``, ``qualification_seconds`` and the content
        title all change on almost every poll, and including any one of them
        would turn this feed into one row per monitor cycle.

        The private ``current_content_title`` never reaches the feed text.
        """

        signature = (
            _field(snapshot, "generation", None),
            _enum_text(_field(snapshot, "phase", "")).upper(),
            str(_field(snapshot, "current_platform_key", "") or ""),
            _field(snapshot, "hopper_count", None),
            _field(snapshot, "chosen_break_minutes", None),
            bool(_field(snapshot, "global_paused", False)),
            bool(_field(snapshot, "final_callback_visible", False)),
            str(_field(snapshot, "closure_outcome", "") or ""),
            bool(_field(snapshot, "durable_health", True)),
        )
        if signature == self._last_cosine_transition_signature:
            return

        self._last_cosine_transition_signature = signature

        phase = signature[1]
        # An IDLE COSINE is never an event, and it is skipped EVERY time rather
        # than only on the first signature (I-062 2A).  Once Global Pause
        # publishes a paused snapshot, pausing an idle session would otherwise
        # change the signature and emit "COSINE - IDLE - PAUSED" for a session
        # that never had an episode at all.  The newest IDLE signature is still
        # remembered above, so a later real transition compares against current
        # truth rather than a stale one.
        if phase in {"", "IDLE"}:
            return

        _telemetry(
            self.telemetry_queue,
            "cosine_transition",
            observation=observation,
            message="COSINE state transition",
            badge="COSINE",
            tone="cyan",
            feed_text=self._cosine_transition_text(snapshot, signature),
        )

    @staticmethod
    def _cosine_transition_text(
        snapshot: object,
        signature: tuple[object, ...],
    ) -> str:
        """Compose the factual transition line; no clinical claim is derived."""

        phase = str(signature[1])
        parts = ["COSINE \u2014 " + (phase.replace("_", " ") or "UNKNOWN")]

        minutes = _field(snapshot, "chosen_break_minutes", None)
        if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
            parts.append(f"{minutes} min")

        platform = str(_field(snapshot, "current_platform_label", "") or "").strip()
        if platform:
            parts.append(platform)

        outcome = str(_field(snapshot, "closure_outcome", "") or "").strip()
        if outcome:
            parts.append(outcome.replace("_", " "))

        # Section 5 ruling, option B.  Three signature components were invisible
        # in this text, so two different signatures could render two identical
        # rows.  hopper_count is safe -- COSINE increments it only on a
        # HOPPER_TRANSITION, which changes current_platform_key and therefore
        # the platform word above.  The other two are made explicit here.  This
        # is telemetry readability only: no state is invented and no recovery
        # physiology is implied.
        if bool(_field(snapshot, "final_callback_visible", False)):
            parts.append("CALLBACK VISIBLE")

        if bool(_field(snapshot, "global_paused", False)):
            parts.append("PAUSED")

        if not bool(_field(snapshot, "durable_health", True)):
            parts.append("DURABILITY DEGRADED")

        return " \u00b7 ".join(parts)

    def _publish_mine_transition(
        self,
        snapshot: object,
        observation: ForegroundObservation | None,
    ) -> None:
        """Publish one append-only MINE row per MEANINGFUL transition.

        Structural donor: ``_publish_cosine_transition``.  Monitor prepares
        this row from the immutable MineSnapshot MINE already produced this
        cycle; it starts no timer, changes no phase and calls nothing on the
        runtime.  MESSAGING identity and MINE organ state stay two separate
        rows -- this never replaces the foreground activity/MESSAGING row.

        Every countdown (initial gate, return intent, important allowance,
        return visual, return verification, closure confirmation) is
        excluded on purpose: those change on almost every poll and would
        turn this feed into one row per monitor cycle.
        """

        signature = (
            _field(snapshot, "generation", None),
            _enum_text(_field(snapshot, "phase", "")).upper(),
            str(_field(snapshot, "current_platform_key", "") or ""),
            str(_field(snapshot, "selected_branch", "") or ""),
            _field(snapshot, "important_chosen_minutes", None),
            bool(_field(snapshot, "mine1_requested", False)),
            bool(_field(snapshot, "mine1_displayed", False)),
            bool(_field(snapshot, "mine1_visible", False)),
            str(_field(snapshot, "mine2_variant", "") or ""),
            bool(_field(snapshot, "mine2_requested", False)),
            bool(_field(snapshot, "mine2_displayed", False)),
            bool(_field(snapshot, "mine2_visible", False)),
            bool(_field(snapshot, "global_paused", False)),
            bool(_field(snapshot, "study_preempted", False)),
            str(_field(snapshot, "closure_outcome", "") or ""),
            bool(_field(snapshot, "durable_health", True)),
        )
        if signature == self._last_mine_transition_signature:
            return

        self._last_mine_transition_signature = signature

        phase = signature[1]
        # A MINE that never opened a candidate/episode is not an
        # intervention event.  Skipped every time, not only on the first
        # signature, mirroring the COSINE IDLE-skip-every-time rule: a later
        # unrelated meaningful change (e.g. Global Pause) must not fabricate
        # a "MINE -- IDLE -- PAUSED" row for an organ that never started.
        if phase in {"", "IDLE"}:
            return

        badge, tone = self._mine_transition_badge(snapshot, phase)
        _telemetry(
            self.telemetry_queue,
            "mine_transition",
            observation=observation,
            message="MINE state transition",
            badge=badge,
            tone=tone,
            feed_text=self._mine_transition_text(snapshot, signature),
        )

    @staticmethod
    def _mine_transition_badge(snapshot: object, phase: str) -> tuple[str, str]:
        """Return (badge, tone) for one MINE transition row.

        MINE/red is escalation pressure: the organ is holding/observing/
        requesting.  RETURN/green is a genuine recovery phase.  A CLOSED row
        earns RETURN only when the factual closure evidence -- reason or
        outcome -- proves a verified return; every other closure (Study
        preemption, incomplete, emergency) stays MINE/red.  ``feed_text``
        keeps its existing "MINE — ..." organ prefix
        either way (section 19): RETURN is a Live Telemetry badge, not a
        rename of the organ.
        """

        if phase == "CLOSED":
            reason = _enum_text(_field(snapshot, "closure_reason", "")).upper()
            outcome = _enum_text(_field(snapshot, "closure_outcome", "")).upper()
            if reason == "VERIFIED_RETURN" or outcome in MINE_VERIFIED_RETURN_OUTCOMES:
                return "RETURN", "green"
            return "MINE", "red"
        if phase in MINE_TRANSITION_RETURN_PHASES:
            return "RETURN", "green"
        return "MINE", "red"

    @staticmethod
    def _mine_transition_text(
        snapshot: object,
        signature: tuple[object, ...],
    ) -> str:
        """Compose the factual transition line; no clinical claim is derived."""

        phase = str(signature[1])
        parts = ["MINE \u2014 " + (phase.replace("_", " ") or "UNKNOWN")]

        platform = str(_field(snapshot, "current_platform_label", "") or "").strip()
        if platform:
            parts.append(platform)

        branch = str(_field(snapshot, "selected_branch", "") or "").strip()
        if branch:
            parts.append(branch.replace("_", " "))

        minutes = _field(snapshot, "important_chosen_minutes", None)
        if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
            parts.append(f"{minutes} min")

        variant = str(_field(snapshot, "mine2_variant", "") or "").strip()
        if variant and variant not in phase:
            parts.append(variant)

        if bool(_field(snapshot, "mine1_visible", False)) or bool(
            _field(snapshot, "mine2_visible", False)
        ):
            parts.append("POPUP VISIBLE")

        outcome = str(_field(snapshot, "closure_outcome", "") or "").strip()
        if outcome:
            parts.append(outcome.replace("_", " "))

        if bool(_field(snapshot, "study_preempted", False)):
            parts.append("STUDY PREEMPTED")

        if bool(_field(snapshot, "global_paused", False)):
            parts.append("PAUSED")

        if not bool(_field(snapshot, "durable_health", True)):
            parts.append("DURABILITY DEGRADED")

        return " \u00b7 ".join(parts)

    def _activity_telemetry_semantics(
        self,
        context: MonitorContext,
        *,
        resource_view: object | None = None,
    ) -> tuple[str, str]:
        """Return the badge/tone from already-authoritative current facts."""

        from COSECANT_STUDY_MODE.study import StudyState
        from CORE_ENGINE.resource_intent import (
            NORMAL_FOCUS_SURFACES,
            ResourceIntent,
            ResourceSurface,
        )

        if resource_view is None:
            resource_view = self.services.resource_intent.live_view()
        classification = _field(resource_view, "classification", None)
        surface = _field(resource_view, "resource_surface", None)
        study_snapshot = self.services.study.snapshot()
        active_study = _field(study_snapshot, "state", None) is StudyState.ACTIVE

        if active_study:
            if classification is ResourceIntent.STUDY_ALIGNED:
                return "STUDY", "green"

            if surface in NORMAL_FOCUS_SURFACES:
                return "STUDY FOCUS", "violet"

            if classification is ResourceIntent.DISTRACTION:
                if surface is ResourceSurface.GAMING:
                    return "GAMING", "red"

                if _field(context, "cosine_platform") is not None:
                    return "OTT", "study-yellow"

                if surface is ResourceSurface.MESSAGING:
                    return "MESSAGING", "study-orange"

                blacklist = self.services.blacklist.live_view()
                if (
                    surface
                    in {
                        ResourceSurface.SOCIAL,
                        ResourceSurface.YOUTUBE_WATCH,
                        ResourceSurface.YOUTUBE_OTHER,
                        ResourceSurface.YOUTUBE_SHORTS,
                    }
                    or (
                        blacklist is not None
                        and _enum_text(_field(blacklist, "disposition", "")).lower()
                        in {"accused", "unknown"}
                    )
                ):
                    return "SOCIAL", "red"

            # Uncertain evidence remains neutral and never appears as confirmed
            # green Study or bright-red distraction.  Resource Intent retains
            # the unchanged clarification authority behind this presentation.
            return "STUDY ACTIVITY", "cyan"

        if _field(context, "cosine_platform") is not None:
            return "OTT", "cyan"

        if (
            resource_view is not None
            and _field(resource_view, "resource_surface", None)
            is ResourceSurface.MESSAGING
        ):
            return "MESSAGING", "cyan"

        if surface is ResourceSurface.GAMING:
            return "GAMING", "amber"

        blacklist = self.services.blacklist.live_view()
        if (
            blacklist is not None
            and _enum_text(_field(blacklist, "disposition", "")).lower()
            in {"accused", "unknown"}
        ):
            return "SOCIAL", "amber"

        if (
            not bool(_field(context, "study_owned", False))
            and resource_view is not None
            and surface in NORMAL_FOCUS_SURFACES
        ):
            return "FOCUS", "cyan"

        return "ACTIVITY", "cyan"

    def _drain_commands(self) -> None:
        for _ in range(MAX_COMMANDS_PER_CYCLE):
            try:
                command = self.command_queue.get_nowait()
            except queue.Empty:
                return
            kind = str(_field(command, "kind", "") or "").lower()
            payload = _field(command, "payload")
            response_queue = _field(command, "response_queue")

            if self._handle_secant_connection_command(kind,payload):
                continue
            if kind == "emergency":
                self._perform_emergency()
                return
            if kind == "restore_protected_red":
                restored = self.services.sine.restore_protected_red()
                _telemetry(
                    self.telemetry_queue,
                    "protected_red_status",
                    message="Protected Red restore requested",
                    active=bool(restored or self.services.sine.protected_red_active()),
                )
                continue
            if kind == "cosine_command":
                if (self._study_owns_moment() and _enum_text(_field(payload,"kind","")) in
                        {"INTENT_ACTION","DURATION_SUBMITTED","CHECKIN_ACTION","WELCOME_ACTION"}):
                    self._reject_command("Study world owns admission")
                    self._answer_command(response_queue,False)
                    continue
                result = self.services.cosine.submit_command(payload)
                for effect in self.services.cosine.drain_effects():
                    self._route_cosine_effect(effect)
                self._answer_command(response_queue, result)
                continue
            if kind == "mine_command":
                if (self._study_owns_moment() and _enum_text(_field(payload,"kind","")) in
                        {"MINE1_ACTION","IMPORTANT_DURATION_SUBMITTED"}):
                    self._reject_command("Study world owns admission")
                    self._answer_command(response_queue,False)
                    continue
                if (self.pause_event.is_set() and _enum_text(_field(payload,"kind",""))=="IMPORTANT_DURATION_SUBMITTED"):
                    self._reject_command("Resume before starting a MINE allowance")
                    self._answer_command(response_queue,False)
                    continue
                result = self._mine_authority.submit_command(payload)
                for effect in self._mine_authority.drain_effects():
                    self._route_mine_effect(effect)
                self._answer_command(response_queue, result)
                continue
            if kind.startswith("normal_break_"):
                accepted = self._handle_normal_break_command(kind, payload)
                self._answer_command(response_queue, accepted)
                continue
            if kind.startswith("sine_"):
                accepted = self._handle_sine_command(kind, payload)
                self._answer_command(response_queue, accepted)
                continue
            if kind.startswith("study_confirmation_"):
                accepted = self._handle_study_confirmation_command(kind, payload)
                self._answer_command(response_queue, accepted)
                continue
            if kind == "study_prepare":
                if self._pending_study_start is not None:
                    self._answer_command(response_queue, {
                        "accepted": False, "message": "Study START transfer is in progress.",
                        "snapshot": self.services.study.snapshot(),
                    })
                    continue
                if not self._study_command_identity_admits(payload, "PREPARE"):
                    self._answer_command(response_queue, {
                        "accepted": False,
                        "message": "Study changed since it was displayed. Review the current block and press PREPARE again.",
                        "snapshot": self.services.study.snapshot(),
                    })
                    continue
                # Keyword collections are forwarded EXACTLY as supplied, never
                # coerced.  StudyRuntime.prepare owns the fail-closed rule that
                # a bare string is not an iterable of keywords; re-wrapping the
                # value here would defeat that guard.  Absent means "none
                # declared", which is the current UI's behaviour.
                #
                # ``block_id`` below is the optional identity OF THE NEW BLOCK
                # and is unrelated to the expected identity checked above.
                from COSECANT_STUDY_MODE.study import StudyPlan

                # Validate with Study's own immutable contract BEFORE prepare
                # can mutate runtime truth. Invalid user input is a rejected
                # command, not a reason to end the parent monitoring session.
                try:
                    plan = StudyPlan(
                        subject=str(_field(payload, "subject", "")),
                        task=str(_field(payload, "task", "")),
                        planned_seconds=int(_field(payload, "planned_seconds", 0) or 0),
                        keywords=_declared_keywords(payload, "keywords"),
                        important_keywords=_declared_keywords(
                            payload, "important_keywords"
                        ),
                    )
                except (TypeError, ValueError, OverflowError) as exc:
                    self._reject_command(f"PREPARE rejected: {exc}")
                    self._answer_command(response_queue, {
                        "accepted": False,
                        "message": f"PREPARE rejected: {exc}",
                        "snapshot": self.services.study.snapshot(),
                    })
                    continue
                # Runtime and durability failures remain fatal: neither is
                # inside the input-validation exception boundary above.
                result = self.services.study.prepare(
                    subject=plan.subject,
                    task=plan.task,
                    planned_seconds=plan.planned_seconds,
                    keywords=plan.keywords,
                    important_keywords=plan.important_keywords,
                    block_id=str(_field(payload, "block_id", "") or ""),
                )
                self._handle_study_result("PREPARE", result)
                # Acknowledge only AFTER the existing durability and context
                # gates. The dedicated reply cannot be lost to telemetry load.
                self._answer_command(response_queue, {
                    "accepted": bool(_field(result, "accepted", False)),
                    "message": str(_field(result, "message", "Study command processed")),
                    "snapshot": _field(result, "snapshot"),
                })
                continue
            if kind == "study_action":
                if not self._study_command_identity_admits(payload, "study action"):
                    continue
                self._handle_study_action(str(_field(payload, "action", "") or ""))
                continue
            if kind == "study_break":
                expected = _expected_identity(
                    payload,
                    ("expected_study_block_id",),
                    ("expected_study_generation",),
                )
                if not self._study_command_identity_admits(payload, "break request"):
                    continue
                self._request_cosecant_break(
                    int(_field(payload, "selected_break_seconds", 0) or 0),
                    # Admission above already refused a malformed identity,
                    # so this is always a complete declared pair (C12-F).
                    expected_study_identity=expected,
                )
                continue
            if kind == "cosecant_return_intent":
                if not self._return_intent_identity_admits(payload):
                    continue
                result = self.services.cosecant.record_return_intent()
                self._route_cosecant_result(result)
                self._publish_study_views()
                continue

            _telemetry(
                self.telemetry_queue,
                "engine_command_rejected",
                message=f"Unsupported Core Engine command: {kind or 'empty'}",
            )

    @staticmethod
    def _answer_command(response_queue: object, result: object) -> None:
        if response_queue is None:
            return
        try:
            response_queue.put_nowait(result)
        except (AttributeError, queue.Full):
            return

    def _handle_normal_break_command(self, kind: str, payload: object) -> bool:
        """Direct Phase-2 command seam; Controller/UI work remains Phase 3."""

        if kind == "normal_break_start":
            if self.pause_event.is_set() or self._study_owns_moment():
                return self._reject_command("Normal Break cannot start during Pause or Study ownership")
            return self._start_normal_break(payload)
        if kind == "normal_break_cancel":
            result = self.services.normal_break.cancel_duration(
                break_id=_field(payload, "break_id"),
                generation=_field(payload, "generation"),
                episode_uid=_field(payload, "episode_uid"),
                candidate_uid=_field(payload, "candidate_uid"),
                source_sine_popup_request_id=_field(
                    payload, "source_sine_popup_request_id"
                ),
            )
            if not bool(_field(result, "accepted", False)):
                return self._reject_command(
                    f"Normal Break CANCEL rejected: {_field(result, 'message', '')}"
                )
            if not self._persist_normal_break_result(result):
                raise RuntimeError("Normal Break cancellation was not durable")
            return True
        if kind == "normal_break_stop":
            result = self.services.normal_break.stop_break(
                break_id=_field(payload, "break_id"),
                generation=_field(payload, "generation"),
                episode_uid=_field(payload, "episode_uid"),
                candidate_uid=_field(payload, "candidate_uid"),
            )
            if not bool(_field(result, "accepted", False)):
                return self._reject_command(
                    f"Normal Break STOP rejected: {_field(result, 'message', '')}"
                )
            facts = tuple(_field(result, "facts", ()) or ())
            if not facts or not self._persist_normal_break_result(result):
                self._normal_break_resume_fault = True
                self.services.blacklist.set_paused(False)
                return self._reject_command(
                    "Normal Break STOP was not durable; SINE resume remains fail-closed"
                )
            return self._resume_normal_break_terminal(facts[-1], None)
        return self._reject_command(f"Unsupported Normal Break command: {kind}")

    def _start_normal_break(self, payload: object) -> bool:
        """Persistence-first Normal Break start and exact SINE hold handoff."""

        if self.pause_event.is_set() or self._study_owns_moment():
            return False
        pending = self.services.normal_break.snapshot()
        declared = (
            _field(payload, "break_id"),
            _field(payload, "generation"),
            _field(payload, "episode_uid"),
            _field(payload, "candidate_uid"),
            _field(payload, "source_sine_popup_request_id"),
        )
        current = (
            _field(pending, "break_id", ""),
            _field(pending, "generation", 0),
            _field(pending, "episode_uid", ""),
            _field(pending, "candidate_uid", ""),
            _field(pending, "source_sine_popup_request_id", ""),
        )
        if (
            any(type(value) is not str for value in (declared[0], *declared[2:]))
            or type(declared[1]) is not int
            or declared != current
        ):
            return self._reject_command(
                "Normal Break START carried a stale or mistyped authority identity"
            )

        state = _field(pending, "state", None)
        state_text = str(getattr(state, "value", state) or "").upper()
        if state_text == "ACTIVE":
            return self._reject_command(
                "Normal Break START rejected because this break is already ACTIVE"
            )

        sine = self.services.sine.live_view()
        admission_ns = self._monotonic_ns()
        sine_eligible = self._normal_break_selector_is_eligible(
            pending,
            sine,
            occurred_monotonic_ns=admission_ns,
        )
        if not sine_eligible:
            self._cancel_pending_normal_break_selector(
                pending,
                occurred_monotonic_ns=admission_ns,
                observation=None,
                reason="start_admission_source_sine1_no_longer_eligible",
            )
            return self._reject_command(
                "Normal Break START was stale because Normal SINE 1 is no longer eligible"
            )

        result = self.services.normal_break.start_break(
            break_id=declared[0],
            generation=declared[1],
            episode_uid=declared[2],
            candidate_uid=declared[3],
            source_sine_popup_request_id=declared[4],
            selected_minutes=_field(payload, "selected_minutes"),
            started_monotonic_ns=admission_ns,
        )
        if not bool(_field(result, "accepted", False)):
            return self._reject_command(
                f"Normal Break START rejected: {_field(result, 'message', '')}"
            )
        start_facts = tuple(_field(result, "facts", ()) or ())
        if len(start_facts) != 1:
            raise RuntimeError("Normal Break START did not produce one exact fact")
        start_fact = start_facts[0]
        if not self._persist_normal_break_result(result):
            rollback = self.services.normal_break.rollback_start(
                break_id=_field(start_fact, "break_id", ""),
                generation=_field(start_fact, "generation", 0),
                episode_uid=_field(start_fact, "episode_uid", ""),
                candidate_uid=_field(start_fact, "candidate_uid", ""),
                reason="break_started_persistence_failed",
                occurred_monotonic_ns=_field(
                    start_fact, "occurred_monotonic_ns", 0
                ),
            )
            self.services.normal_break.drain_facts()
            del rollback
            self.services.blacklist.set_paused(False)
            return self._reject_command(
                "Normal Break START was not durable; SINE remained unchanged"
            )

        started_ns = int(_field(start_fact, "occurred_monotonic_ns", 0) or 0)
        held = bool(
            self.services.sine.hold_for_normal_break(
                candidate_uid=_field(start_fact, "candidate_uid", ""),
                episode_uid=_field(start_fact, "episode_uid", ""),
                break_id=_field(start_fact, "break_id", ""),
                break_generation=_field(start_fact, "generation", 0),
                started_monotonic_ns=started_ns,
                source_popup_request_id=_field(
                    start_fact, "source_sine_popup_request_id", ""
                ),
            )
        )
        if not held:
            rollback = self.services.normal_break.rollback_start(
                break_id=_field(start_fact, "break_id", ""),
                generation=_field(start_fact, "generation", 0),
                episode_uid=_field(start_fact, "episode_uid", ""),
                candidate_uid=_field(start_fact, "candidate_uid", ""),
                reason="sine_hold_refused",
                occurred_monotonic_ns=started_ns,
            )
            if not self._persist_normal_break_result(rollback):
                raise RuntimeError(
                    "SINE refused Normal Break hold and rollback was not durable"
                )
            self.services.blacklist.set_paused(False)
            return self._reject_command(
                "SINE refused the exact Normal Break ownership handoff"
            )

        try:
            self.services.blacklist.set_paused(True)
        except Exception:
            rollback_ns = max(started_ns, time.monotonic_ns())
            released = self.services.sine.cancel_normal_break_hold(
                candidate_uid=_field(start_fact, "candidate_uid", ""),
                episode_uid=_field(start_fact, "episode_uid", ""),
                break_id=_field(start_fact, "break_id", ""),
                break_generation=_field(start_fact, "generation", 0),
                occurred_monotonic_ns=rollback_ns,
                reason="blacklist_pause_failed",
            )
            rollback = self.services.normal_break.rollback_start(
                break_id=_field(start_fact, "break_id", ""),
                generation=_field(start_fact, "generation", 0),
                episode_uid=_field(start_fact, "episode_uid", ""),
                candidate_uid=_field(start_fact, "candidate_uid", ""),
                reason="blacklist_pause_failed",
                occurred_monotonic_ns=rollback_ns,
            )
            rollback_durable = self._persist_normal_break_result(rollback)
            for sine_fact in self.services.sine.advance(
                now_monotonic_ns=rollback_ns
            ):
                self._route_sine_fact(sine_fact, None)
            self.services.blacklist.set_paused(False)
            if not released or not rollback_durable:
                raise RuntimeError(
                    "Normal Break failed to roll back after Blacklist pause failure"
                )
            return self._reject_command(
                "Normal Break ownership rolled back because Blacklist could not pause"
            )

        self._normal_break_learning_ineligible_candidate_uids.add(
            _field(start_fact, "candidate_uid", "")
        )
        for sine_fact in self.services.sine.advance(now_monotonic_ns=started_ns):
            self._route_sine_fact(sine_fact, None)
        _telemetry(
            self.telemetry_queue,
            "normal_break_started",
            message="Normal Break durably started and the same SINE episode is held",
            break_id=_field(start_fact, "break_id", ""),
            generation=_field(start_fact, "generation", 0),
            episode_uid=_field(start_fact, "episode_uid", ""),
            candidate_uid=_field(start_fact, "candidate_uid", ""),
            started_monotonic_ns=started_ns,
            deadline_monotonic_ns=_field(
                start_fact, "deadline_monotonic_ns", None
            ),
        )
        return True

    def _handle_study_confirmation_command(self, kind: str, payload: object) -> bool:
        request_id = str(_field(payload, "request_id", "") or "")
        occurred_ns = int(_field(payload, "occurred_monotonic_ns", 0) or 0)
        if not request_id or occurred_ns <= 0:
            return False
        authority = self.services.resource_intent
        if kind == "study_confirmation_popup_shown":
            accepted = authority.record_study_confirmation_popup_shown(
                request_id=request_id,
                shown_monotonic_ns=occurred_ns,
                popup_hwnd=int(_field(payload, "popup_hwnd", 0) or 0),
            )
        elif kind == "study_confirmation_popup_closed":
            accepted = authority.record_study_confirmation_popup_closed(
                request_id=request_id,
                occurred_monotonic_ns=occurred_ns,
                reason=str(_field(payload, "reason", "presentation_closed") or "presentation_closed"),
            )
        elif kind == "study_confirmation_user_action":
            accepted = authority.record_study_confirmation_response(
                request_id=request_id,
                response=str(_field(payload, "response", "") or ""),
                occurred_monotonic_ns=occurred_ns,
                expected_study_context_token=str(
                    _field(payload, "expected_study_context_token", "") or ""
                ),
                expected_resource_key=str(
                    _field(payload, "expected_resource_key", "") or ""
                ),
            )
            self._capture_study_observation_evidence(accepted=accepted, request_id=request_id, applied_ns=occurred_ns)
        else:
            accepted = False
        if not accepted:
            _telemetry(
                self.telemetry_queue,
                "engine_command_rejected",
                message=f"Study confirmation callback rejected: {kind}",
                request_id=request_id,
            )
        self._drain_resource_intent_facts(None)
        return bool(accepted)

    def _handle_sine_command(self, kind: str, payload: object) -> bool:
        request_id = str(_field(payload, "request_id", "") or "")
        occurred_ns = int(_field(payload, "occurred_monotonic_ns", 0) or 0)
        if not request_id or occurred_ns <= 0:
            return False
        accepted = False
        if kind == "sine_popup_shown":
            accepted = self.services.sine.popup_shown(
                request_id=request_id,
                shown_monotonic_ns=occurred_ns,
                popup_hwnd=int(_field(payload, "popup_hwnd", 0) or 0),
            )
        elif kind == "sine_popup_failed":
            accepted = self.services.sine.popup_failed(
                request_id=request_id,
                reason=str(_field(payload, "reason", "display_failed")),
                occurred_monotonic_ns=occurred_ns,
            )
        elif kind == "sine_user_action":
            accepted = self.services.sine.popup_response(
                request_id=request_id,
                response=str(_field(payload, "response", "")),
                occurred_monotonic_ns=occurred_ns,
            )
        elif kind == "sine_popup_closed":
            accepted = self.services.sine.popup_closed(
                request_id=request_id,
                reason=str(_field(payload, "reason", "authority_close")),
                occurred_monotonic_ns=occurred_ns,
            )
        if not accepted:
            _telemetry(
                self.telemetry_queue,
                "engine_command_rejected",
                message=f"SINE callback rejected: {kind}",
                request_id=request_id,
            )
        action_result_recorded = self._route_sine_batch(self.services.sine.advance(now_monotonic_ns=occurred_ns))
        self._advance_pending_study_start()
        return accepted and action_result_recorded

    # ------------------------------------------------------------------
    # C11-A command-identity boundary
    #
    # A visible UI is always slightly behind the engine.  These guards let a
    # request name the generation it was issued against and refuse it if that
    # generation is no longer current.  They compare only; they own no
    # physiology, and a refusal mutates nothing.
    # ------------------------------------------------------------------

    def _reject_command(self, reason: str) -> bool:
        _telemetry(self.telemetry_queue, "engine_command_rejected", message=reason)
        return False

    def _study_command_identity_admits(self, payload: object, label: str) -> bool:
        """Compare a supplied Study identity against current authority."""

        expected = _expected_identity(
            payload,
            ("expected_study_block_id",),
            ("expected_study_generation",),
        )
        if expected is MALFORMED_IDENTITY:
            return self._reject_command(
                f"{label} carried an absent or incomplete expected Study identity"
            )
        return self._study_identity_matches(expected, label)

    def _study_identity_matches(self, expected, label: str) -> bool:
        block_id, generation = expected
        study = self.services.study.snapshot()
        current = (
            str(_field(study, "block_id", "") or ""),
            int(_field(study, "generation", 0) or 0),
        )
        if (block_id, generation) == current:
            return True
        return self._reject_command(
            f"{label} named Study block {block_id or '<none>'}"
            f" generation {generation}, but the current Study block is"
            f" {current[0] or '<none>'} generation {current[1]}"
        )

    def _return_intent_identity_admits(self, payload: object) -> bool:
        """Compare a supplied COSECANT episode identity against current truth.

        The break-return button is the one presentation control that can reach
        a durable fact, so a supplied identity must name the exact episode that
        displayed it AND that episode must still be offering the action.
        """

        from COSECANT_STUDY_MODE.cosecant import CosecantUiAction

        expected = _expected_identity(
            payload,
            ("expected_break_id", "expected_study_block_id"),
            ("expected_cosecant_generation", "expected_study_generation"),
        )
        if expected is MALFORMED_IDENTITY:
            return self._reject_command(
                "return intent carried an absent or incomplete expected identity"
            )

        break_id, study_block_id, generation, study_generation = expected
        snapshot = self.services.cosecant.snapshot()
        current = (
            str(_field(snapshot, "break_id", "") or ""),
            str(_field(snapshot, "study_block_id", "") or ""),
            int(_field(snapshot, "generation", 0) or 0),
            int(_field(snapshot, "study_generation", 0) or 0),
        )
        if (break_id, study_block_id, generation, study_generation) != current:
            return self._reject_command(
                f"return intent named break {break_id or '<none>'}"
                f" generation {generation}, but the current break is"
                f" {current[0] or '<none>'} generation {current[2]}"
            )
        # Current truth must still be offering the action.  Presentation may
        # have shown the button a moment ago; only the authority decides now.
        allowed = _field(snapshot, "allowed_actions", ()) or ()
        if CosecantUiAction.RETURN_TO_STUDY not in tuple(allowed):
            return self._reject_command(
                "return intent is not currently an allowed COSECANT action"
            )
        if bool(_field(snapshot, "final_locked", False)):
            return self._reject_command(
                "return intent cannot be recorded while FINAL_LOCK holds the break"
            )
        return True

    def _publish_study_transition(self, pending, state, message="") -> None:
        _telemetry(
            self.telemetry_queue, "study_start_transition",
            live_view={
                "block_id": pending["study_identity"][0],
                "generation": pending["study_identity"][1],
                "deadline_monotonic_ns": pending["deadline"],
                "state": state, "message": message,
            },
            message=message or "Study Mode will be starting in 5",
        )

    def _begin_study_start_transition(self) -> bool:
        return self._begin_study_entry()

    def _advance_pending_study_start(self) -> None:
        if self._pending_study_start is not None:
            self._pending_study_start=None

    def _handle_study_action(self,action: str) -> None:
        if action.upper()=="START":self._begin_study_entry()
        else:self._apply_internal_study_action(action)

    def _handle_study_result(self, action: str, result: object) -> None:
        snapshot = _field(result, "snapshot")
        if bool(_field(result, "accepted", False)) and snapshot is not None:
            if not self.services.storage.record_study_snapshot(
                session_id=self.session_id,
                action=action,
                snapshot=snapshot,
            ):
                raise RuntimeError("Study snapshot was not durably accepted")
            self._sync_study_context_with_resource_intent(snapshot)
            from COSECANT_STUDY_MODE.study import StudyState

            if _field(snapshot, "state", None) is StudyState.ACTIVE:
                self.services.blacklist.inhibit_normal_sine_watch()

            if _field(snapshot, "state", None) is StudyState.COMPLETED:
                # This command already durably recorded the terminal snapshot
                # under its own correct action label (e.g. "COMPLETE"). Mark
                # this block/generation handled so the periodic
                # advance()-driven path (_sync_study_context_after_advance)
                # never re-records it as TARGET_REACHED on the next poll --
                # including the edge case where a manual complete() lands
                # exactly on a TARGET_REACHED completion_reason.
                self._last_study_completion_signature = (
                    str(_field(snapshot, "block_id", "") or ""),
                    int(_field(snapshot, "generation", 0) or 0),
                )
        _telemetry(
            self.telemetry_queue,
            "study_runtime_view",
            message=_field(result, "message", "Study command processed"),
            live_view=snapshot,
        )

    def _sync_study_context_with_resource_intent(self, snapshot: object) -> None:
        """Keep Resource Intent's exact Study context in step with StudyRuntime.

        This is the wiring Resource Intent's STUDY_ALIGNED/off-task
        classification depends on entirely -- Resource Intent has no other
        way to learn a Study block exists (``StudyRuntime`` owns Study
        session truth but never talks to Resource Intent itself; see its own
        docstring). This never existed before: the previous ``StudyRuntime(
        context_authority=intent)`` construction predates a real
        ``context_authority`` parameter on ``StudyRuntime.__init__`` and
        would have raised ``TypeError`` on every attempted launch, so there
        was no working connection to preserve, only a crash to fix. This
        builds the connection for the first time.

        COSECANT publishes its own BREAK-shaped ``StudyContext`` while a
        break is active (``CosecantRuntime._publish_break_context``); this
        method only owns the ACTIVE-Study side and retires cleanly whenever
        Study is not genuinely ACTIVE (PAUSED for a break, COMPLETED,
        SHUTDOWN, or never prepared), so the two publishers never contend
        for the same Resource Intent context slot. Existing call order
        already guarantees this: Study is paused (retiring here) strictly
        before COSECANT starts a break and publishes its own context, and
        COSECANT retires its own context before Study resumes and
        republishes here.
        """

        from COSECANT_STUDY_MODE.study import StudyState

        state = _field(snapshot, "state", None)
        self._reconcile_break_target_with_study(snapshot)
        if state is not StudyState.ACTIVE:
            self._end_study_foreground_span("STUDY_INACTIVE")
            self.services.resource_intent.retire_study_context()
            return

        from CORE_ENGINE.resource_intent import StudyContext

        # The declared Study target travels with the lifecycle facts. Monitor
        # transports them and calculates nothing: keyword scoring belongs to
        # the calculator, and the Study verdict belongs to Resource Intent.
        # StudySnapshot already holds validated, normalised tuples, so these
        # are forwarded unchanged.
        context = StudyContext(
            block_id=str(_field(snapshot, "block_id", "") or ""),
            generation=int(_field(snapshot, "generation", 0) or 0),
            display_state="ACTIVE",
            subject=str(_field(snapshot, "subject", "") or ""),
            task=str(_field(snapshot, "task", "") or ""),
            protection_active=True,
            planned_break_active=False,
            remaining_seconds=max(0, int(_field(snapshot, "remaining_seconds", 0) or 0)),
            published_monotonic_ns=time.monotonic_ns(),
            keywords=_field(snapshot, "keywords", ()),
            important_keywords=_field(snapshot, "important_keywords", ()),
        )
        self.services.resource_intent.publish_study_context(context)

    def _sync_study_context_after_advance(self,snapshot) -> None:
        from COSECANT_STUDY_MODE.study import StudyState
        if self._study_exit:return
        if snapshot.state is StudyState.ACTIVE:
            self._sync_study_context_with_resource_intent(snapshot)
        elif snapshot.state is StudyState.COMPLETED and self._study_world=="STUDY":
            self._begin_study_exit("study_complete")

    def _reconcile_break_target_with_study(self, study: object) -> None:
        """Clear remembered evidence when its owning Study identity retires."""

        target = self._break_eligible_study_target
        if target is None:
            return
        from COSECANT_STUDY_MODE.study import StudyState

        if (
            _field(study, "state", None) is not StudyState.ACTIVE
            or str(_field(study, "block_id", "") or "") != target.study_block_id
            or int(_field(study, "generation", 0) or 0)
            != target.study_generation
            or str(_field(study, "context_token", "") or "")
            != target.study_context_token
        ):
            self._break_eligible_study_target = None

    def _certified_break_target_from_context(
        self,
        context: MonitorContext,
        *,
        study: object | None = None,
    ) -> tuple[BreakEligibleStudyTarget | None, str]:
        """Extract one exact target only from current certified Study facts."""

        from CORE_ENGINE.resource_intent import ResourceIntent
        from COSECANT_STUDY_MODE.study import StudyState

        study = self.services.study.snapshot() if study is None else study
        if _field(study, "state") is not StudyState.ACTIVE:
            return None, "Study Mode is not ACTIVE"

        snapshot = context.resource_intent
        verdict = _field(snapshot, "verdict")
        if _field(verdict, "classification") is not ResourceIntent.STUDY_ALIGNED:
            return None, "the current resource is not verified Study material"
        if not bool(_field(snapshot, "fresh", False)):
            return None, "the current observation is not fresh"

        study_block_id = str(_field(study, "block_id", "") or "")
        study_generation = int(_field(study, "generation", 0) or 0)
        study_context_token = str(_field(study, "context_token", "") or "")
        if str(_field(verdict, "study_context_token", "") or "") != study_context_token:
            return None, "the verdict belongs to a different Study block"
        if not study_block_id or study_generation <= 0 or not study_context_token:
            return None, "the active Study block has no exact identity"

        browser = context.browser_evidence
        if not bool(_field(browser, "authoritative", False)):
            return None, "browser evidence is not authoritative"
        if bool(_field(browser, "holding_previous_strong_evidence", False)):
            return None, "browser evidence is a held previous read"

        evidence = _field(browser, "evidence")
        browser_platform = str(_field(evidence, "platform_key", "") or "")
        browser_token = str(_field(evidence, "resource_token", "") or "")
        if not browser_platform:
            return None, "browser evidence has no certified platform"
        if not browser_token:
            return None, "this resource has no exact identity to return to"

        identity = _field(verdict, "resource_identity")
        if not bool(_field(identity, "browser_evidence_certified", False)):
            return None, "the resource identity is not certified"
        if str(_field(identity, "platform_key", "") or "") != browser_platform:
            return None, "Resource Intent and Browser disagree about the platform"
        if str(_field(identity, "opaque_resource_token", "") or "") != browser_token:
            return None, "Resource Intent and Browser disagree about the resource"

        observed_ns = int(context.foreground.observed_monotonic_ns)
        if observed_ns <= 0:
            return None, "the Study resource observation has no valid timestamp"
        return (
            BreakEligibleStudyTarget(
                study_block_id=study_block_id,
                study_generation=study_generation,
                study_context_token=study_context_token,
                platform_key=browser_platform,
                resource_token=browser_token,
                observed_monotonic_ns=observed_ns,
            ),
            "",
        )

    def _refresh_break_eligible_study_target(self, context: MonitorContext) -> None:
        """Refresh from external Study truth; preserve only across MYELIN UI."""

        study = self.services.study.snapshot()
        self._reconcile_break_target_with_study(study)
        if int(context.foreground.process_id or 0) == self._myelin_process_id:
            return

        target, _refusal = self._certified_break_target_from_context(
            context,
            study=study,
        )
        # Any genuinely observed external surface replaces or invalidates the
        # prior memory. Unknown/uncertified evidence fails closed to no target.
        self._break_eligible_study_target = target

    def _remembered_break_admission_refusal(
        self,
        context: MonitorContext,
        target: BreakEligibleStudyTarget | None,
    ) -> str:
        """Recheck live lifecycle guards around an already-certified target."""

        from COSECANT_STUDY_MODE.study import StudyState

        study = self.services.study.snapshot()
        if _field(study, "state") is not StudyState.ACTIVE:
            return "Study Mode is not ACTIVE"
        if bool(_field(context.resource_intent, "protected_red_active", False)):
            return "Protected Red must be resolved before starting a managed break"
        if target is None:
            return "no fresh certified Study return target was preserved"
        if (
            str(_field(study, "block_id", "") or "") != target.study_block_id
            or int(_field(study, "generation", 0) or 0)
            != target.study_generation
            or str(_field(study, "context_token", "") or "")
            != target.study_context_token
        ):
            return "the remembered target belongs to a different Study block"
        return ""

    def _request_cosecant_break(self,selected_break_seconds: int,*,expected_study_identity=None) -> None:
        study=self.services.study.snapshot()
        current=(study.block_id,study.generation)
        action=self._pending_secant_break_action
        target=self._study_return_target
        accepted=False
        if (expected_study_identity in {None,current} and target is not None
                and target.study_context_token==study.context_token
                and target.observed_monotonic_ns>=study.active_epoch_monotonic_ns):
            accepted=self._begin_study_break(selected_break_seconds,target,
                request_id=action[0] if action else "",action_sequence=action[1] if action else None)
        if not accepted and action:self._reject_secant_break_action(action,"Break admission rejected")
        self._pending_secant_break_action=None

    def _admit_pending_break(self,context: MonitorContext) -> None:
        if self._pending_break_seconds is not None:
            self._pending_break_seconds=None;self._pending_break_study_identity=None

    def _break_started_monotonic_ns(self, result: object) -> int:
        """Read the factual break-start instant out of an accepted result."""

        from COSECANT_STUDY_MODE.cosecant import CosecantFactKind

        for fact in tuple(_field(result, "facts", ()) or ()):
            if _field(fact, "kind") is CosecantFactKind.BREAK_STARTED:
                started_ns = int(_field(fact, "effective_monotonic_ns", 0) or 0)
                if started_ns > 0:
                    return started_ns
                break
        # An accepted break without its own BREAK_STARTED fact is an impossible
        # state. Manufacturing a timestamp here would hide that, so refuse.
        raise RuntimeError(
            "an accepted COSECANT break carried no factual BREAK_STARTED "
            "timestamp; refusing to invent one"
        )

    def _break_admission_refusal(self, context: MonitorContext) -> str:
        """Return why this observation cannot found a break, or "" to admit.

        Deliberately does NOT require ``allowance_match`` or
        ``study_idle_allowed``: a resource aligned by factual C4 evidence is a
        legitimate place to start a break, and idle permission is a separate
        policy that must not become an admission gate.
        """

        from COSECANT_STUDY_MODE.study import StudyState

        study = self.services.study.snapshot()
        if _field(study, "state") is not StudyState.ACTIVE:
            return "Study Mode is not ACTIVE"

        snapshot = context.resource_intent
        if bool(_field(snapshot, "protected_red_active", False)):
            # Protected Red used to make this unreachable by masking every
            # verdict as UNCERTAIN.  Now that Resource Intent reports facts
            # during Red, a genuine Study resource would otherwise satisfy the
            # test below and let the user start a break straight out of the
            # strongest intervention MYELIN has.  This is a lifecycle gate, not
            # a second Study classifier.
            return "Protected Red must be resolved before starting a managed break"
        _target, refusal = self._certified_break_target_from_context(
            context,
            study=study,
        )
        return refusal

    def _publish_study_views(self) -> None:
        _telemetry(
            self.telemetry_queue,
            "study_runtime_view",
            live_view=self.services.study.snapshot(),
        )
        _telemetry(
            self.telemetry_queue,
            "cosecant_view",
            live_view=self.services.cosecant.snapshot(),
        )

    def _perform_emergency(self) -> None:
        if self._emergency_requested:
            return
        if self.session_id is None:
            raise RuntimeError("emergency requested before session became durable")
        self._emergency_requested = True
        if self._study_owns_moment():self._begin_study_exit("emergency")
        self._break_eligible_study_target = None

        # Stop presentation/runtime activity first, then record the emergency
        # before permitting application exit.
        from SINE.normal_break import NormalBreakTerminationReason

        if not self._terminate_normal_break(
            NormalBreakTerminationReason.EMERGENCY
        ):
            _telemetry(
                self.telemetry_queue,
                "normal_break_integrity_failure",
                message="Normal Break emergency termination was not durable",
            )
        self.services.sine.emergency_stop()
        from COSINE.cosine import ClosureReason
        for effect in self.services.cosine.close(
            ClosureReason.EMERGENCY, now_ns=time.monotonic_ns()
        ):
            self._route_cosine_effect(effect)
        from MINE.mine import MineClosureReason
        for effect in self._mine_authority.close(
            MineClosureReason.EMERGENCY, now_ns=time.monotonic_ns()
        ):
            self._route_mine_effect(effect)
        self._route_cosecant_result(self.services.cosecant.cancel_for_session_end(reason="emergency"))
        self.services.mirl.emergency_stop()
        self._persist_mirl_events(self.services.mirl.drain_events())
        receipt = self.services.storage.record_emergency(session_id=self.session_id)
        committed = self._wait_for_commit(
            receipt,
            timeout_seconds=SHUTDOWN_PERSISTENCE_TIMEOUT_SECONDS,
            operation="emergency record",
        )
        self._emergency_durable = _receipt_state(committed) == COMMITTED_STATE
        self.stop_event.set()

    def _terminate_normal_break(self, reason: object) -> bool:
        """Terminate pending/active Normal Break without resuming SINE 2."""

        try:
            snapshot = self.services.normal_break.snapshot()
            state = _field(snapshot, "state", None)
            state_text = str(getattr(state, "value", state) or "").upper()
            if state_text == "IDLE":
                self.services.normal_break.drain_facts()
                return True
            result = self.services.normal_break.terminate(reason=reason)
            if not bool(_field(result, "accepted", False)):
                return False
            return self._persist_normal_break_result(result)
        finally:
            self.services.blacklist.set_paused(False)
            self._normal_break_resume_fault = False

    def _wait_for_commit(
        self,
        receipt: object,
        *,
        timeout_seconds: float,
        operation: str,
    ) -> object:
        receipt_id = _receipt_id(receipt)
        current = receipt
        if _receipt_state(current) == RUNNING_STATE:
            waited = self.services.storage.wait(
                receipt_id,
                timeout_seconds=timeout_seconds,
            )
            if waited is not None:
                current = waited
        state = _receipt_state(current)
        if state != COMMITTED_STATE:
            detail = _receipt_error(current) or state
            # The failure has now been read off the captured receipt, so the
            # registry copy has no remaining reader.  A still-RUNNING receipt
            # is refused by storage and stays observable for reconciliation.
            self._consume_receipt(receipt_id)
            raise RuntimeError(f"{operation} was not committed: {detail}")
        # This helper is the FINAL consumer for session open, session close,
        # emergency record and profile learning update: every caller uses the
        # returned receipt and never looks the id up again (C12-D2).
        self._consume_receipt(receipt_id)
        return current

    def _cleanup(self) -> bool:
        """Stop authorities in dependency order and close durable session."""

        self._end_study_foreground_span("SESSION_STOP")
        if self._study_owns_moment():
            self._begin_study_exit("emergency" if self._emergency_requested else "session_end")
            # Cleanup uses the existing bounded shutdown wait. Expiry reports
            # unresolved cleanup; it never fabricates presentation clearance.
            until=time.monotonic()+SHUTDOWN_PERSISTENCE_TIMEOUT_SECONDS
            while self._study_exit and time.monotonic()<until:
                self._drain_commands();self._connection_tick()
                if self._study_exit:time.sleep(0.01)
            if self._study_exit:self._cleanup_errors.append("Study world cleanup remains unresolved")
        self._break_eligible_study_target = None
        try:
            from SINE.normal_break import NormalBreakTerminationReason

            reason = (
                NormalBreakTerminationReason.EMERGENCY
                if self._emergency_requested
                else NormalBreakTerminationReason.SESSION_END
            )
            if not self._terminate_normal_break(reason):
                self._cleanup_errors.append(
                    "Normal Break: terminal fact was not durable"
                )
        except Exception as error:
            self._cleanup_errors.append(f"Normal Break: {error}")
        # First try to settle a live trigger transaction. Never reject a
        # RUNNING transaction: it may still commit a moment later.
        try:
            self._settle_pending_trigger_for_shutdown()
        except Exception as error:
            self._cleanup_errors.append(f"Pending trigger settlement: {error}")
        # Study and COSECANT are real authorities too. Retire them before
        # Resource Intent so their exact contexts can be withdrawn safely.
        try:
            self._route_cosecant_result(self.services.cosecant.shutdown())
        except Exception as error:
            self._cleanup_errors.append(f"COSECANT: {error}")
        try:
            study_result = self.services.study.shutdown()
            snapshot = _field(study_result, "snapshot")
            if snapshot is not None and self.session_id is not None:
                if not self.services.storage.record_study_snapshot(
                    session_id=self.session_id, action="SAFE_SHUTDOWN", snapshot=snapshot
                ):
                    raise RuntimeError("Study shutdown snapshot was not durable")
            self._sync_study_context_with_resource_intent(snapshot)
        except Exception as error:
            self._cleanup_errors.append(f"Study: {error}")

        try:
            self._persist_mirl_events(self.services.mirl.drain_events())
        except Exception as error:
            self._cleanup_errors.append(f"MIRL event drain: {error}")

        for name, action in (
            ("SINE", self.services.sine.shutdown),
            ("MIRL", self.services.mirl.shutdown),
        ):
            try:
                action()
            except Exception as error:
                self._cleanup_errors.append(f"{name}: {error}")
        try:
            if not self.services.cosine.shutdown():
                self._cleanup_errors.append("COSINE: durable shutdown was rejected")
        except Exception as error:
            self._cleanup_errors.append(f"COSINE: {error}")
        try:
            if self._mine_authority is not None and not self._mine_authority.shutdown():
                self._cleanup_errors.append("MINE: durable shutdown was rejected")
            if self._mine_authority is not None:
                for effect in self._mine_authority.drain_effects():
                    self._route_mine_effect(effect)
        except Exception as error:
            self._cleanup_errors.append(f"MINE: {error}")

        if self.session_id is not None:
            try:
                close_receipt = self.services.storage.close_monitor_session(
                    session_id=self.session_id,
                    reason="EMERGENCY" if self._emergency_requested else "STOPPED",
                )
                self._wait_for_commit(
                    close_receipt,
                    timeout_seconds=SHUTDOWN_PERSISTENCE_TIMEOUT_SECONDS,
                    operation="session close",
                )
                # Storage deliberately refuses learning from an open session.
                # Only after the close commit may this session teach the next
                # session.  The lambda frozen at Start remains unchanged.
                self._commit_profile_learning_after_session_close()
            except Exception as error:
                self._cleanup_errors.append(f"Session close/profile learning: {error}")

        # The storage lane is ordered. If session-close committed, any trigger
        # write submitted before it is now terminal too. Reconcile it before
        # destroying Trigger authority so a committed row is never reported as
        # rejected merely because Stop arrived during the write.
        try:
            self._settle_pending_trigger_for_shutdown(wait_seconds=0.0)
        except Exception as error:
            self._cleanup_errors.append(f"Pending trigger reconciliation: {error}")
        if self._pending_trigger is not None:
            self._cleanup_errors.append(
                "Trigger persistence remained unresolved during shutdown"
            )

        for name, action in (
            ("Trigger", self.services.trigger.shutdown),
            ("Blacklist", self.services.blacklist.shutdown),
            ("Resource Intent", self.services.resource_intent.shutdown),
            ("Browser", self.services.browser.shutdown),
        ):
            try:
                action()
            except Exception as error:
                self._cleanup_errors.append(f"{name}: {error}")

        try:
            self.services.storage.shutdown()
        except Exception as error:
            self._cleanup_errors.append(f"Storage: {error}")

        if self._cleanup_errors:
            _telemetry(
                self.telemetry_queue,
                "trigger_processing_failed",
                message=" | ".join(self._cleanup_errors),
            )
            return False
        _telemetry(
            self.telemetry_queue,
            "session",
            message="Core Engine cleanup completed",
            session_id=self.session_id,
        )

        return True

    def _settle_pending_trigger_for_shutdown(
        self,
        *,
        wait_seconds: float = SHUTDOWN_PERSISTENCE_TIMEOUT_SECONDS,
    ) -> None:
        """Resolve one pending candidate without starting an intervention."""

        pending = self._pending_trigger
        if pending is None:
            return
        receipt = self.services.storage.receipt(pending.receipt_id)
        if receipt is None:
            self._cleanup_errors.append("Pending trigger receipt disappeared")
            return
        if _receipt_state(receipt) == RUNNING_STATE and wait_seconds > 0:
            waited = self.services.storage.wait(
                pending.receipt_id,
                timeout_seconds=wait_seconds,
            )
            if waited is not None:
                receipt = waited

        state = _receipt_state(receipt)
        if state == RUNNING_STATE:
            # Keep the workflow identity intact. A later ordered session-close
            # may settle it, after which cleanup calls this method again.
            return
        if state == COMMITTED_STATE:
            self._settle_trigger_without_intervention(
                pending, _receipt_result_id(receipt), "monitor_stopped_before_sine"
            )
            return

        rejected = self.services.trigger.reject_candidate(
            candidate_uid=pending.candidate_uid,
            reason="trigger_persistence_failed_during_shutdown",
        )
        if not rejected:
            self._cleanup_errors.append(
                "Failed pending trigger could not be rejected"
            )
            return
        self._clear_pending_trigger()


def run(
    *,
    profile_type: str,
    stop_event,
    pause_event,
    ready_event,
    loop_stopped_event,
    cleanup_complete_event,
    telemetry_queue,
    command_queue,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
) -> None:
    """Production entry point used by ``CONTROL_STATION.controller``.

    All runtime objects are created inside the worker thread that calls this
    function. No Qt object is created or touched here.
    """

    services = _build_services(profile_type=str(profile_type))
    coordinator = WindowsMonitorCoordinator(
        profile_type=str(profile_type),
        services=services,
        foreground_reader=WindowsForegroundReader(),
        stop_event=stop_event,
        pause_event=pause_event,
        ready_event=ready_event,
        loop_stopped_event=loop_stopped_event,
        cleanup_complete_event=cleanup_complete_event,
        telemetry_queue=telemetry_queue,
        command_queue=command_queue,
        poll_seconds=poll_seconds,
    )
    coordinator.run()
