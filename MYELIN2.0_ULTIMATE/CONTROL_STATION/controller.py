"""Control Station connection to the MYELIN Core Engine.

This file has one job: carry commands from the Control Station to the Core
Engine and carry prepared engine facts back to the user interface.

It owns:

* Start, Pause, Resume, Stop and Emergency command connections;
* exactly one Core Engine worker thread;
* thread-safe telemetry delivery to the Qt user-interface thread;
* the presentation-only engine status and elapsed session time; and
* factual worker-exit and cleanup reporting.

Important boundary
------------------
This controller does not monitor Windows, classify resources, calculate
off-task dwell, choose a SINE stage, change Study Mode, write MIRL events, or
write database rows.  Those decisions belong to the Core Engine and its
specialist authorities.  The controller transports commands and facts only.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from PyQt6.QtCore import QObject, QTimer, Qt, pyqtSignal
from collections import deque
from uuid import uuid4
from CONTROL_STATION.command_delivery import PendingCommand


LOGGER = logging.getLogger(__name__)

TELEMETRY_CAPACITY: Final = 2048
TERMINAL_RESERVE: Final = 32
TELEMETRY_BATCH_SIZE: Final = 25
GUI_POLL_INTERVAL_MS: Final = 250
ELAPSED_INTERVAL_MS: Final = 250
STARTUP_TIMEOUT_SECONDS: Final = 15.0

# These are replace-in-place views, not history rows.  Keeping only the newest
# copy prevents a slow UI from receiving hundreds of obsolete snapshots.
CRITICAL_SECANT_KINDS: Final = frozenset({"secant_popup", "secant_close", "secant_action_result", "pause_ack", "normal_surface_fence", "secant_break_selection"})

LIVE_VIEW_KINDS: Final = frozenset(
    {
        "control_view",
        "secant_projection",
        "pause_eligibility",
        "study_runtime_view",
        "cosecant_view",
        "cosine_live_status",
        "handover_live_status",
        "resource_intent_live_status",
        "sine_watch_status",
        "mine_watch_status",
        "mirl_health_status",
        "protected_red_status",
    }
)

# These facts must survive routine queue pressure because losing them can make
# the visible lifecycle disagree with the engine lifecycle.
TERMINAL_KINDS: Final = frozenset(
    {
        "session",
        "study_start_transition",
        "returned",
        "timeout",
        "trigger_processing_failed",
        "emergency_completed",
        "sine_fact",
        "normal_break_fact",
        "resource_intent_fact",
        "cosine_effect",
        "mine_effect",
        "cosecant_fact",
        # Final MIRL closure must survive queue pressure: losing it could
        # leave the common theme's Amber/Red warning stuck forever.
        "mirl_episode_closed",
    }
)


class EngineStatus(str, Enum):
    """Small UI vocabulary for the Core Engine lifecycle.

    These values never replace SINE, MIRL, COSINE or Study Mode states.
    """

    IDLE = "IDLE"
    STARTING = "STARTING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    EMERGENCY = "EMERGENCY"
    ERROR = "ERROR"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TelemetryEvent:
    """Immutable history row delivered to the Control Station."""

    time: str
    kind: str
    app: str
    title: str
    message: str
    badge: str = ""
    feed_text: str = ""
    tone: str = ""


@dataclass(frozen=True)
class EngineCommand:
    """Immutable command placed on the Core Engine command queue."""

    kind: str
    payload: object | None = None
    response_queue: object | None = None


class _TelemetryInbox(queue.Queue):
    """Bounded non-blocking queue with safe live-view replacement.

    The Core Engine must never wait for the GUI.  Routine telemetry may be
    refused under extreme pressure, while terminal facts retain reserved
    capacity.  A live view replaces its older copy because only its newest
    state is useful to the interface.
    """

    def __init__(self) -> None:
        super().__init__(maxsize=TELEMETRY_CAPACITY)

    def put(self, item, block=False, timeout=None):  # noqa: ANN001
        # Instruction: engine producers always use this as a non-blocking
        # boundary.  Ignore blocking arguments so the monitor cannot freeze
        # while waiting for the Control Station.
        del block, timeout
        kind = item.get("kind") if isinstance(item, Mapping) else None

        with self.not_full:
            if kind in CRITICAL_SECANT_KINDS:
                # Dedicated low-volume lifecycle facts retain custody under
                # queue pressure; only replaceable projections are coalesced.
                self.queue.append(item)
                self.unfinished_tasks += 1
                self.not_empty.notify()
                return True
            if kind in LIVE_VIEW_KINDS:
                for index in range(len(self.queue) - 1, -1, -1):
                    queued = self.queue[index]
                    if isinstance(queued, Mapping) and queued.get("kind") == kind:
                        self.queue[index] = item
                        return True

            is_terminal = kind in TERMINAL_KINDS
            routine_limit = self.maxsize - TERMINAL_RESERVE
            capacity_reached = (
                len(self.queue) >= self.maxsize
                or (not is_terminal and len(self.queue) >= routine_limit)
            )

            if capacity_reached and not self._make_room(is_terminal):
                raise queue.Full

            self.queue.append(item)
            self.unfinished_tasks += 1
            self.not_empty.notify()
            return True

    def _make_room(self, is_terminal: bool) -> bool:
        """Remove one replaceable item without discarding a terminal fact."""

        removable_index: int | None = None
        for index, queued in enumerate(self.queue):
            queued_kind = queued.get("kind") if isinstance(queued, Mapping) else None
            if queued_kind in LIVE_VIEW_KINDS:
                removable_index = index
                break

        if removable_index is None and is_terminal:
            for index, queued in enumerate(self.queue):
                queued_kind = (
                    queued.get("kind") if isinstance(queued, Mapping) else None
                )
                if queued_kind not in TERMINAL_KINDS and queued_kind not in CRITICAL_SECANT_KINDS:
                    removable_index = index
                    break

        if removable_index is None:
            return False

        del self.queue[removable_index]
        self.unfinished_tasks -= 1
        if self.unfinished_tasks == 0:
            self.all_tasks_done.notify_all()
        return True


class ControlStationController(QObject):
    """One Qt-safe bridge between the Control Station and Core Engine."""

    # Lifecycle facts.  Only this controller emits these signals.
    engine_started = pyqtSignal()
    engine_paused = pyqtSignal()
    engine_resumed = pyqtSignal()
    engine_stopped = pyqtSignal()
    engine_failed = pyqtSignal(str)
    engine_status_changed = pyqtSignal(object)  # EngineStatus
    session_time_changed = pyqtSignal(int)
    # Factual mirror of the authoritative persisted session ID (see
    # current_session_id()).  Payload is int | None.  Emitted only when the
    # value actually changes -- narrow and factual, per the Phase C
    # session-identity seam: consumers (e.g. SCIENCE_LAB's coordinator)
    # attach/detach from this, never from a live open-row DB query.
    current_session_id_changed = pyqtSignal(object)

    # Append-only telemetry and replace-in-place prepared views are separate.
    study_prepare_result = pyqtSignal(object)
    study_start_transition_changed = pyqtSignal(object)
    telemetry_received = pyqtSignal(object)  # TelemetryEvent
    control_view_changed = pyqtSignal(object)
    study_view_changed = pyqtSignal(object)
    secant_projection_changed = pyqtSignal(object)
    secant_break_selection_requested = pyqtSignal(object)
    pause_eligibility_changed = pyqtSignal(object)
    normal_surface_fence_requested = pyqtSignal(object)
    cosine_live_status_changed = pyqtSignal(object)
    handover_live_status_changed = pyqtSignal(object)
    handover_family_signal_received = pyqtSignal(object)
    resource_intent_live_status_changed = pyqtSignal(object)
    sine_watch_status_changed = pyqtSignal(object)
    mine_watch_status_changed = pyqtSignal(object)
    mirl_health_status_changed = pyqtSignal(object)
    normal_break_fact_changed = pyqtSignal(object)
    normal_break_command_result = pyqtSignal(object)
    # Raw SineFact transport for presentation coordinators (e.g. the common
    # theme's Normal-SINE atmosphere claims).  Transport only: this signal
    # carries whatever SINE already published and decides nothing itself.
    sine_fact_received = pyqtSignal(object)
    # raw MirlEvent transport only -- same contract as sine_fact_received.
    mirl_fact_received = pyqtSignal(object)
    # raw CosecantFact transport only -- same contract as sine_fact_received.
    cosecant_fact_received = pyqtSignal(object)
    protected_red_changed = pyqtSignal(bool)

    # Emergency is requested here, but lifecycle.py decides application exit.
    emergency_started = pyqtSignal()
    emergency_completed = pyqtSignal(bool)
    normal_stop_requested = pyqtSignal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)

        self._pending_study_prepare = None
        self._pending_commands = {}
        self._secant_presenter = None
        self._secant_visual_projection = None
        self._pending_secant_presentation = deque()
        self._pause_eligibility = None
        self._pause_pending = None
        self._critical_commands = deque()
        self._mine_dispatcher = self._cosine_dispatcher = None
        self.normal_surface_fence_requested.connect(self._ack_normal_surface_fence, Qt.ConnectionType.QueuedConnection)
        self._status = EngineStatus.IDLE
        self._profile_type = "general"
        self._is_monitoring = False
        # Authoritative persisted session ID, mirrored read-only from the
        # Core Engine's own "session" telemetry (see _route_prepared_view) --
        # never a live open-row DB query, never a direct worker reach-in.
        # Cleared only in _finish_worker_exit, once the worker has actually
        # exited (Phase C session-identity seam).
        self._current_session_id: int | None = None
        self._is_shutting_down = False
        self._emergency_latched = False
        self._startup_failure_reported = False
        self._protected_red_active = False

        # The controller creates fresh thread primitives for every session.
        # Old sessions can therefore never leak a set Event into a new one.
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._ready_event = threading.Event()
        self._loop_stopped_event = threading.Event()
        self._cleanup_complete_event = threading.Event()
        self._worker_finished_event = threading.Event()

        self._telemetry_queue = _TelemetryInbox()
        self._command_queue: queue.Queue[EngineCommand] = queue.Queue(maxsize=32)
        self._worker_errors: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._worker_thread: threading.Thread | None = None

        self._startup_deadline: float | None = None
        self._active_seconds = 0.0
        self._last_active_tick: float | None = None
        self._report_session_lease = None
        # Held from the moment a start is admitted until the active-session
        # source is bound and the worker is running (C12-G).
        self._session_start_reservation = None

        # QTimers run on the GUI thread.  Therefore every Qt signal below is
        # emitted on the GUI thread, never from the monitor worker.
        self._worker_timer = QTimer(self)
        self._worker_timer.setInterval(GUI_POLL_INTERVAL_MS)
        self._worker_timer.timeout.connect(self._poll_worker)

        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(GUI_POLL_INTERVAL_MS)
        self._telemetry_timer.timeout.connect(self._drain_telemetry)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(ELAPSED_INTERVAL_MS)
        self._elapsed_timer.timeout.connect(self._update_elapsed_time)

        self._sine_presenter = None
        self._normal_break_presenter = None
        self._study_confirmation_presenter = None
        self._pending_study_confirmation_actions: dict[str, queue.Queue] = {}
        self._popup_dispatchers_installed = False

    @property
    def status(self) -> EngineStatus:
        """Return the current presentation-only lifecycle state."""

        return self._status

    @property
    def report_access(self):
        """Return the one persistence-owned report-access authority."""

        from PERSISTENCE.storage import REPORT_ACCESS_COORDINATOR

        return REPORT_ACCESS_COORDINATOR

    def is_session_active(self) -> bool:
        """Return factual session activity without changing engine state."""

        thread_alive = bool(
            self._worker_thread is not None and self._worker_thread.is_alive()
        )
        return bool(
            self._is_monitoring
            or thread_alive
            or self._status
            in {
                EngineStatus.STARTING,
                EngineStatus.ACTIVE,
                EngineStatus.PAUSED,
                EngineStatus.STOPPING,
                EngineStatus.EMERGENCY,
            }
        )

    def current_session_id(self) -> int | None:
        """Return the authoritative persisted session ID, or ``None``.

        Read-only mirror of the Core Engine's own committed
        ``sessions.id`` row -- sourced from the existing "session"
        telemetry kind (terminal-reserved in ``TERMINAL_KINDS``, so it is
        never dropped under queue pressure), not from a live
        ``SELECT ... WHERE closed_at_utc IS NULL`` query and not from
        reaching into the worker/monitor object directly.

        ``None`` whenever no session is active, including the brief
        ``STARTING`` window before the Core Engine's session-open commit
        has actually returned -- callers must treat that as "not yet
        known" and wait, never substitute a placeholder or a previous
        session's ID.
        """

        return self._current_session_id

    def install_popup_dispatchers(self, app, *, owner=None) -> None:
        """Install the presentation bridges after QApplication exists.

        SINE intentionally has no global compatibility dispatcher.  Its
        presenter is owned here and sends factual callbacks through the same
        bounded engine command queue as every other UI action.
        """

        if self._popup_dispatchers_installed:
            return
        from COSECANT_STUDY_MODE.view import (
            StudyConfirmationPresenter,
            install_popup_dispatcher as install_study,
        )
        from COSINE.popup import install_cosine_dispatcher
        from MINE.popup import install_mine_dispatcher
        from SINE.popup import NormalBreakPresenter, SinePopupPresenter

        self._cosine_dispatcher = install_cosine_dispatcher(app, owner=owner)
        self._mine_dispatcher = install_mine_dispatcher(app, owner=owner)
        study_dispatcher = install_study(app)
        study_dispatcher.popup_withdrawn.connect(self._cosecant_surface_withdrawn)
        from SECANT.popup import create_qt_presenter
        self._secant_presenter = create_qt_presenter(self._send_secant_receipt, parent=owner)
        self._secant_presenter.host.set_projection(self._secant_visual_projection)
        while self._pending_secant_presentation:
            kind, envelope = self._pending_secant_presentation.popleft()
            self._route_prepared_view(kind, envelope)
        presenter = SinePopupPresenter(owner=owner, parent=self)
        presenter.popup_shown.connect(
            lambda request_id, occurred_ns, hwnd: self._send_sine_callback(
                "sine_popup_shown", request_id, occurred_ns, popup_hwnd=hwnd
            )
        )
        presenter.popup_failed.connect(
            lambda request_id, reason, occurred_ns: self._send_sine_callback(
                "sine_popup_failed", request_id, occurred_ns, reason=reason
            )
        )
        presenter.user_action.connect(self._submit_sine_user_action)
        presenter.popup_closed.connect(
            lambda request_id, reason, occurred_ns: self._send_sine_callback(
                "sine_popup_closed", request_id, occurred_ns, reason=reason
            )
        )
        self._sine_presenter = presenter
        normal_break = NormalBreakPresenter(parent=self)
        normal_break.start_requested.connect(
            lambda payload: self._submit_normal_break_command("start", payload)
        )
        normal_break.cancel_requested.connect(
            lambda payload: self._submit_normal_break_command("cancel", payload)
        )
        normal_break.stop_requested.connect(
            lambda payload: self._submit_normal_break_command("stop", payload)
        )
        self._normal_break_presenter = normal_break
        study_confirmation = StudyConfirmationPresenter(owner=owner, parent=self)
        study_confirmation.popup_shown.connect(
            lambda request_id, occurred_ns, hwnd: self._send_study_confirmation_callback(
                "study_confirmation_popup_shown",
                request_id,
                occurred_ns,
                popup_hwnd=hwnd,
            )
        )
        study_confirmation.user_action.connect(
            self._submit_study_confirmation_action
        )
        study_confirmation.popup_closed.connect(
            lambda request_id, reason, occurred_ns: self._send_study_confirmation_callback(
                "study_confirmation_popup_closed",
                request_id,
                occurred_ns,
                reason=reason,
            )
        )
        self._study_confirmation_presenter = study_confirmation
        self._popup_dispatchers_installed = True

    def _enqueue_command(self, kind: str, payload: object | None = None, response_queue=None) -> bool:
        try:
            self._command_queue.put_nowait(
                EngineCommand(kind=kind, payload=payload, response_queue=response_queue)
            )
        except queue.Full:
            return False
        return True

    def _send_critical_command(self, kind, payload):
        self._critical_commands.append((kind, payload))
        self._flush_critical_commands()
        return True  # Controller retains custody until the worker queue accepts.

    def _flush_critical_commands(self):
        while self._critical_commands:
            kind, payload = self._critical_commands[0]
            if payload.get("session_id") != self._current_session_id:
                self._critical_commands.popleft()
                continue
            if not self._enqueue_command(kind, payload):
                break
            self._critical_commands.popleft()

    def _send_secant_receipt(self, receipt):
        from dataclasses import replace
        return self._send_critical_command("secant_receipt", {
            "session_id": self._current_session_id,
            "receipt": replace(receipt, received_at_ns=time.monotonic_ns())})

    def _cosecant_surface_withdrawn(self, value):
        snapshot, occurred_ns = value
        self._send_critical_command("cosecant_popup_closed", {
            "session_id": self._current_session_id, "break_id": snapshot.break_id,
            "study_block_id": snapshot.study_block_id, "generation": snapshot.generation,
            "occurred_monotonic_ns": occurred_ns})

    def _ack_normal_surface_fence(self, raw):
        if raw.get("session_id") != self._current_session_id:
            return
        clear = True
        for dispatcher, names in ((self._mine_dispatcher, ("_mine1_popup", "_mine2_popup")),
                (self._cosine_dispatcher, ("_intent_popup", "_duration_popup", "_break_ack_popup", "_final_popup"))):
            if dispatcher is None:
                clear = False
                continue
            for name in names:
                if not hasattr(dispatcher, name):
                    clear = False
                    continue
                popup = getattr(dispatcher, name)
                if popup is not None and popup.isVisible():
                    clear = False
        self._send_critical_command("normal_surface_clearance", {
            "session_id": self._current_session_id, "request_id": raw.get("request_id"),
            "clear": clear, "occurred_monotonic_ns": time.monotonic_ns()})

    def _send_sine_callback(self, kind: str, request_id: str, occurred_ns: int, **fields) -> bool:
        payload = {
            "request_id": str(request_id),
            "occurred_monotonic_ns": int(occurred_ns),
            **fields,
        }
        return self._enqueue_command(kind, payload)

    def _submit_sine_user_action(
        self,
        request_id: str,
        response: str,
        occurred_ns: int,
    ) -> bool:
        """Send one popup action and surface transport rejection to that popup."""

        payload = {
            "request_id": str(request_id),
            "occurred_monotonic_ns": int(occurred_ns),
            "response": str(response),
        }
        receipt = self._submit_async_command("sine_user_action", payload, (request_id,))
        def completed(reply):
            if reply.error or not reply.value:
                self._show_sine_action_rejection(request_id, reply.error or "ACTION NOT ACCEPTED · TRY AGAIN")
        receipt.add_done_callback(completed)
        return not bool(receipt.error)

    def _show_sine_action_rejection(self, request_id: str, message: str) -> None:
        presenter = self._sine_presenter
        if presenter is not None:
            presenter.show_action_rejection(str(request_id), str(message))

    def _submit_normal_break_command(self, action: str, payload: object) -> bool:
        """Queue one exact Normal Break action; apply backend admission later."""

        presenter = self._normal_break_presenter
        if action not in {"start", "cancel", "stop"} or not isinstance(payload, dict):
            if presenter is not None:
                presenter.show_command_result(
                    payload,
                    action=action,
                    accepted=False,
                    message="INVALID NORMAL BREAK ACTION",
                )
            return False

        identity = tuple(payload.get(name) for name in ("break_id", "generation", "episode_uid", "candidate_uid"))
        receipt = self._submit_async_command(f"normal_break_{action}", dict(payload), identity)
        def completed(reply):
            accepted = not reply.error and bool(reply.value)
            message = reply.error or "NORMAL BREAK ACTION NOT ACCEPTED · TRY AGAIN"
            current = self._normal_break_presenter
            if current is not None:
                current.show_command_result(payload, action=action, accepted=accepted, message=message)
            self.normal_break_command_result.emit({"payload": payload, "action": action,
                                                   "accepted": accepted, "message": message})
        receipt.add_done_callback(completed)
        return not bool(receipt.error)

    def request_normal_break_stop(self, payload: object) -> bool:
        """Expose the existing exact STOP transport to the Control Station card."""

        return self._submit_normal_break_command("stop", payload)

    def _send_study_confirmation_callback(
        self,
        kind: str,
        request_id: str,
        occurred_ns: int,
        **fields,
    ) -> bool:
        return self._enqueue_command(
            kind,
            {
                "request_id": str(request_id),
                "occurred_monotonic_ns": int(occurred_ns),
                **fields,
            },
        )

    def _submit_study_confirmation_action(
        self,
        request_id: str,
        response: str,
        occurred_ns: int,
        expected_study_context_token: str,
        expected_resource_key: str,
    ) -> bool:
        """Queue one exact Case-1 action without blocking the GUI on Monitor."""

        request_id = str(request_id)
        if request_id in self._pending_study_confirmation_actions:
            return True
        acknowledgement: queue.Queue = queue.Queue(maxsize=1)
        payload = {
            "request_id": str(request_id),
            "response": str(response),
            "occurred_monotonic_ns": int(occurred_ns),
            "expected_study_context_token": str(expected_study_context_token),
            "expected_resource_key": str(expected_resource_key),
        }
        queued = self._enqueue_command(
            "study_confirmation_user_action",
            payload,
            acknowledgement,
        )
        if queued:
            self._pending_study_confirmation_actions[request_id] = acknowledgement
        else:
            presenter = self._study_confirmation_presenter
            if presenter is not None:
                presenter.show_action_rejection(
                    str(request_id),
                    "CLARIFICATION NOT ACCEPTED · CHECK THE CURRENT RESOURCE",
                )
        return bool(queued)

    def _drain_study_confirmation_acknowledgements(self) -> None:
        """Resolve backend replies on the GUI timer; never guess from delay."""

        for request_id, acknowledgement in tuple(
            self._pending_study_confirmation_actions.items()
        ):
            try:
                accepted = bool(acknowledgement.get_nowait())
            except queue.Empty:
                continue
            del self._pending_study_confirmation_actions[request_id]
            if not accepted and self._study_confirmation_presenter is not None:
                self._study_confirmation_presenter.show_action_rejection(
                    request_id,
                    "CLARIFICATION NOT ACCEPTED · CHECK THE CURRENT RESOURCE",
                )

    def submit_cosine_command(self, command):
        """Queue once; the GUI receives the exact authoritative result later."""
        return self._submit_async_command("cosine_command", command,
            (command.generation, command.request_id, command.kind))

    def submit_mine_command(self, command):
        """Queue once; no waiting or acceptance inference on the GUI thread."""
        return self._submit_async_command("mine_command", command,
            (command.generation, command.request_id, command.kind))

    def _submit_async_command(self, kind, payload, identity):
        key = (kind, *identity)
        pending = self._pending_commands.get(key)
        if pending is not None:
            return pending[1]
        response = queue.Queue(maxsize=1)
        receipt = PendingCommand()
        if self._enqueue_command(kind, payload, response):
            self._pending_commands[key] = (response, receipt)
        else:
            receipt.finish(error="COMMAND NOT SENT · ENGINE BUSY OR STOPPED · TRY AGAIN")
        return receipt

    def _drain_command_replies(self):
        for key, (response, receipt) in tuple(self._pending_commands.items()):
            try:
                result = response.get_nowait()
            except queue.Empty:
                continue
            del self._pending_commands[key]
            receipt.finish(result)

    def _retire_command_replies(self):
        self._drain_command_replies()
        pending, self._pending_commands = self._pending_commands, {}
        for response, receipt in pending.values():
            receipt.finish(error="ENGINE STOPPED · ACCEPTANCE NOT CONFIRMED")

    # ------------------------------------------------------------------
    # Study / COSECANT requests
    #
    # These carry the identity the user was looking at when they pressed the
    # button.  This controller is TRANSPORT: it copies those fields into the
    # command payload and never decides whether they still match.  Monitor
    # compares them against current authoritative truth immediately before it
    # mutates anything.
    # ------------------------------------------------------------------

    @staticmethod
    def _expected_study_identity(block_id: str, generation: int) -> dict[str, object]:
        return {
            "expected_study_block_id": str(block_id),
            "expected_study_generation": int(generation),
        }

    def prepare_study(
        self,
        subject: str,
        task: str,
        planned_seconds: int,
        break_seconds: int = 0,
        expected_study_block_id: str = "",
        expected_study_generation: int = 0,
        keywords: object = (),
        important_keywords: object = (),
    ) -> bool:
        del break_seconds  # break duration is chosen explicitly when a break starts
        if self._pending_study_prepare is not None:
            return False
        if self._status not in {EngineStatus.ACTIVE, EngineStatus.PAUSED}:
            self.study_prepare_result.emit({
                "accepted": False, "message": "Start the Core Engine before preparing Study."
            })
            return False
        # The expected pair names the Study generation this PREPARE was issued
        # against.  It is deliberately NOT forwarded as ``block_id``: that
        # field is the optional identity OF THE NEW BLOCK, and normal Study
        # preparation must keep letting StudyRuntime mint it.
        payload = {
            "subject": subject,
            "task": task,
            "planned_seconds": planned_seconds,
            "keywords": keywords,
            "important_keywords": important_keywords,
            **self._expected_study_identity(
                expected_study_block_id, expected_study_generation
            ),
        }
        reply = queue.SimpleQueue()
        self._pending_study_prepare = reply
        accepted = self._enqueue_command("study_prepare", payload, response_queue=reply)
        if not accepted:
            self._pending_study_prepare = None
        self.study_prepare_result.emit({
            "pending": accepted,
            "accepted": None if accepted else False,
            "message": "Preparing Study…" if accepted else "PREPARE was not queued. Please try again.",
        })
        return accepted

    def _drain_study_prepare_result(self) -> None:
        reply = self._pending_study_prepare
        if reply is None:
            return
        try:
            result = reply.get_nowait()
        except queue.Empty:
            return
        self._pending_study_prepare = None
        snapshot = result.get("snapshot")
        if snapshot is not None:
            # Also refresh a stale screen after identity rejection. This is
            # authoritative display truth, never an automatic retry.
            self.study_view_changed.emit(snapshot)
        self.study_prepare_result.emit(result)

    def request_study_action(
        self,
        action: str,
        expected_study_block_id: str = "",
        expected_study_generation: int = 0,
    ) -> bool:
        return self._enqueue_command(
            "study_action",
            {
                "action": str(action),
                **self._expected_study_identity(
                    expected_study_block_id, expected_study_generation
                ),
            },
        )

    def request_study_break(
        self,
        selected_break_seconds: int,
        expected_study_block_id: str = "",
        expected_study_generation: int = 0,
    ) -> bool:
        return self._enqueue_command(
            "study_break",
            {
                "selected_break_seconds": int(selected_break_seconds),
                **self._expected_study_identity(
                    expected_study_block_id, expected_study_generation
                ),
            },
        )

    def request_cosecant_return_intent(
        self,
        expected_break_id: str = "",
        expected_cosecant_generation: int = 0,
        expected_study_block_id: str = "",
        expected_study_generation: int = 0,
    ) -> bool:
        return self._enqueue_command(
            "cosecant_return_intent",
            {
                "expected_break_id": str(expected_break_id),
                "expected_cosecant_generation": int(expected_cosecant_generation),
                "expected_study_block_id": str(expected_study_block_id),
                "expected_study_generation": int(expected_study_generation),
            },
        )

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------
    def set_profile_type(self, profile_type: str) -> None:
        value = str(profile_type or "general").strip().lower()
        self._profile_type = value or "general"

    def start_engine(self, profile_type: str | None = None) -> bool:
        """Start exactly one Core Engine worker.

        Instruction: STARTING does not become ACTIVE after ``thread.start``.
        The Core Engine must set ``ready_event`` after its real initialization
        succeeds.  This removes the false-ACTIVE window in the old code.
        """

        if self._is_shutting_down or self.is_session_active():
            return False

        # C12-G.  The start reservation is what makes "a session is starting"
        # visible to report access, and the active-session SOURCE does not
        # exist yet.  Releasing the reservation before that source is bound
        # left a window in which the coordinator could see neither, and a
        # report export was admitted underneath a session that was starting.
        # The reservation is therefore held across the whole handoff and
        # released only once the worker is running -- or, on every failure
        # path, exactly once by ``_release_session_start_reservation``.
        try:
            self._session_start_reservation = self.report_access.begin_session_start()
        except Exception as exc:  # report authority supplies user-safe text
            self._fail_start(f"Engine could not start: {self._safe_error(exc)}")
            return False

        self._set_status(EngineStatus.STARTING)

        try:
            from CORE_ENGINE.monitor import run as run_core_monitor
        except (ImportError, SystemExit) as exc:
            self._release_session_start_reservation()
            self._fail_start(f"Core Engine is unavailable: {self._safe_error(exc)}")
            return False

        self._prepare_new_session()
        self._is_monitoring = True
        self._startup_deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS

        try:
            self._report_session_lease = self.report_access.bind_session_active_source(
                self.is_session_active
            )
            self._worker_thread = threading.Thread(
                target=self._run_worker,
                args=(run_core_monitor, str(profile_type or self._profile_type)),
                daemon=True,
                name="MyelinCoreEngine",
            )
            self._worker_thread.start()
        except Exception as exc:
            self._is_monitoring = False
            self._release_report_lease()
            self._release_session_start_reservation()
            self._fail_start(f"Core Engine could not start: {self._safe_error(exc)}")
            return False

        # Session-start authority is fully established: the active-session
        # source is bound and the worker is running, so the bound source now
        # refuses reports on its own.  Only now may the reservation go.
        self._release_session_start_reservation()

        self._worker_timer.start()
        self._telemetry_timer.start()
        return True

    def _release_session_start_reservation(self) -> None:
        """Release the session-start reservation exactly once, if held.

        Every ``start_engine`` exit -- success or failure -- passes through
        here.  Clearing the attribute before releasing means a second call can
        never evict a reservation belonging to a later start attempt.
        """

        reservation = self._session_start_reservation
        self._session_start_reservation = None
        if reservation is None:
            return
        try:
            reservation.release()
        except Exception:
            # A reservation that is already gone is not a start failure.
            pass

    def _prepare_new_session(self) -> None:
        self._retire_command_replies()
        self._pause_pending = self._pause_eligibility = None
        self._critical_commands.clear()
        self._pending_secant_presentation.clear()
        self._secant_visual_projection = None
        if self._secant_presenter is not None:
            self._secant_presenter.host.set_projection(None)
        self.secant_projection_changed.emit(None)
        self.pause_eligibility_changed.emit(None)
        """Reset transport state before creating the only worker thread."""

        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._ready_event = threading.Event()
        self._loop_stopped_event = threading.Event()
        self._cleanup_complete_event = threading.Event()
        self._worker_finished_event = threading.Event()
        self._telemetry_queue = _TelemetryInbox()
        self._command_queue = queue.Queue(maxsize=32)
        self._worker_errors = queue.SimpleQueue()
        self._pending_study_confirmation_actions.clear()

        self._emergency_latched = False
        self._startup_failure_reported = False
        red_was_active = self._protected_red_active
        self._protected_red_active = False
        self._active_seconds = 0.0
        self._last_active_tick = None

        # Clear old replace-in-place cards immediately.  This is presentation
        # cleanup only; it does not reset any Core Engine state.
        self.cosine_live_status_changed.emit(None)
        self.handover_live_status_changed.emit(None)
        self.resource_intent_live_status_changed.emit(None)
        self.sine_watch_status_changed.emit(None)
        self.mine_watch_status_changed.emit(None)
        self.mirl_health_status_changed.emit(None)
        if self._study_confirmation_presenter is not None:
            self._study_confirmation_presenter.reset_presentation_epoch()
        if self._normal_break_presenter is not None:
            self._normal_break_presenter.reset_presentation_epoch()
        # C11-A-L5.  The Study surface keeps a generation-ordering baseline so a
        # stale snapshot cannot repaint over a newer one.  A new session builds
        # fresh Study and COSECANT authorities whose generations legitimately
        # restart, so that baseline must be dropped at the session boundary or
        # the new session's genuine truth would be refused as stale.
        #
        # ``None`` is a presentation reset SENTINEL.  No snapshot is
        # manufactured here: this controller has no authority to invent one.
        self.study_view_changed.emit(None)
        if red_was_active:
            self.protected_red_changed.emit(False)

    def _run_worker(self, run_core_monitor, profile_type: str) -> None:
        """Run only on the worker thread and never touch a Qt widget."""

        try:
            run_core_monitor(
                profile_type=profile_type,
                stop_event=self._stop_event,
                pause_event=self._pause_event,
                ready_event=self._ready_event,
                loop_stopped_event=self._loop_stopped_event,
                cleanup_complete_event=self._cleanup_complete_event,
                telemetry_queue=self._telemetry_queue,
                command_queue=self._command_queue,
            )
        except BaseException as exc:  # worker failure must reach the GUI safely
            self._worker_errors.put(self._safe_error(exc))
        finally:
            self._worker_finished_event.set()

    # ------------------------------------------------------------------
    # Pause, resume, stop and emergency
    # ------------------------------------------------------------------
    def pause_control_allowed(self) -> bool:
        if self._is_shutting_down or self._pause_pending:
            return False
        if self._status is EngineStatus.PAUSED:
            return True
        value = self._pause_eligibility
        return bool(self._status is EngineStatus.ACTIVE and value is not None
            and value.session_id == self._current_session_id and value.allowed)

    def pause(self) -> bool:
        return self._request_pause(True)

    def resume(self) -> bool:
        return self._request_pause(False)

    def _request_pause(self, paused: bool) -> bool:
        if (not self.pause_control_allowed() or self._current_session_id is None
                or self._status is not (EngineStatus.ACTIVE if paused else EngineStatus.PAUSED)):
            return False
        payload = {"request_id": "global-pause-" + uuid4().hex,
            "session_id": self._current_session_id, "paused": paused,
            "occurred_monotonic_ns": time.monotonic_ns()}
        if not self._enqueue_command("global_pause_request", payload):
            return False
        self._pause_pending = payload
        self.pause_eligibility_changed.emit(self._pause_eligibility)
        return True

    def stop(self) -> bool:
        """Ask the Core Engine to stop; worker polling confirms the result."""

        if self._is_shutting_down:
            return False
        if self._status not in {
            EngineStatus.STARTING,
            EngineStatus.ACTIVE,
            EngineStatus.PAUSED,
        }:
            return False

        self._accumulate_active_time()
        self._pause_event.clear()
        self._stop_event.set()
        self._set_status(EngineStatus.STOPPING)
        return True

    def emergency(self) -> bool:
        """Send one emergency command to the Core Engine.

        The controller does not perform emergency persistence or decide exit.
        Core Engine owns the emergency operation; lifecycle.py receives the
        completion fact and decides whether application exit is allowed.
        """

        if self._is_shutting_down or self._emergency_latched:
            return False
        if not self.is_session_active():
            return False

        if not self._enqueue_command("emergency"):
            self._emit_failure("Emergency command queue is full")
            return False

        self._emergency_latched = True
        self._pause_event.clear()
        self._set_status(EngineStatus.EMERGENCY)
        self.emergency_started.emit()
        return True

    def is_protected_red_active(self) -> bool:
        """Return the latest factual Protected Red status."""

        return self._protected_red_active

    def request_protected_red_restore(self) -> bool:
        """Ask Core Engine to restore its authoritative Red presentation."""

        return self._enqueue_command("restore_protected_red")

    # ------------------------------------------------------------------
    # GUI-thread polling and telemetry routing
    # ------------------------------------------------------------------
    def _poll_worker(self) -> None:
        self._flush_critical_commands()
        if self._secant_presenter is not None:
            self._secant_presenter.flush_receipts()
        """Convert worker Events into factual GUI-thread lifecycle signals."""

        thread = self._worker_thread
        thread_alive = bool(thread is not None and thread.is_alive())

        if self._status is EngineStatus.STARTING and self._ready_event.is_set():
            self._startup_deadline = None
            self._last_active_tick = time.monotonic()
            self._set_status(EngineStatus.ACTIVE)
            self.session_time_changed.emit(0)
            self.engine_started.emit()
            self._elapsed_timer.start()

        if (
            self._status is EngineStatus.STARTING
            and self._startup_deadline is not None
            and time.monotonic() >= self._startup_deadline
            and not self._startup_failure_reported
        ):
            self._startup_failure_reported = True
            self._stop_event.set()
            self._set_status(EngineStatus.ERROR)
            self._emit_failure("Core Engine did not report ready within 15 seconds")

        if thread_alive:
            return

        if self._worker_finished_event.is_set() and self._is_monitoring:
            self._finish_worker_exit()

    def _drain_telemetry(self, *, drain_all: bool = False) -> int:
        """Deliver a bounded telemetry batch on the Qt GUI thread."""

        self._drain_command_replies()
        self._drain_study_confirmation_acknowledgements()
        self._drain_study_prepare_result()
        processed = 0
        limit = None if drain_all else TELEMETRY_BATCH_SIZE

        while limit is None or processed < limit:
            try:
                raw = self._telemetry_queue.get_nowait()
            except queue.Empty:
                break

            processed += 1
            if not isinstance(raw, Mapping):
                continue

            kind = str(raw.get("kind", ""))
            if self._route_prepared_view(kind, raw):
                continue

            event = TelemetryEvent(
                time=str(raw.get("time", "")),
                kind=kind,
                app=str(raw.get("app", "")),
                title=str(raw.get("title", "")),
                message=str(raw.get("message", "")),
                badge=str(raw.get("badge", "")),
                feed_text=str(raw.get("feed_text", "")),
                tone=str(raw.get("tone", "")),
            )
            self.telemetry_received.emit(event)

        self._drain_study_confirmation_acknowledgements()
        return processed

    def _route_prepared_view(self, kind: str, raw: Mapping) -> bool:
        """Route engine-prepared views without interpreting their meaning."""

        if kind in CRITICAL_SECANT_KINDS | {"secant_projection", "pause_eligibility"}:
            if raw.get("session_id") != self._current_session_id or self._current_session_id is None:
                return True
            if kind == "pause_eligibility":
                from SECANT.read_model import PauseEligibility
                value = raw.get("live_view")
                if (isinstance(value, PauseEligibility) and value.session_id == self._current_session_id
                        and (self._pause_eligibility is None or value.revision > self._pause_eligibility.revision)):
                    self._pause_eligibility = value
                    self.pause_eligibility_changed.emit(value)
            elif kind == "pause_ack":
                pending = self._pause_pending
                if pending and raw.get("request_id") == pending["request_id"]:
                    if raw.get("accepted") is True:
                        if pending["paused"]:
                            self._accumulate_active_time()
                            self._set_status(EngineStatus.PAUSED)
                            self.engine_paused.emit()
                        else:
                            self._last_active_tick = time.monotonic()
                            self._set_status(EngineStatus.ACTIVE)
                            self.engine_resumed.emit()
                    self._pause_pending = None
                    self.pause_eligibility_changed.emit(self._pause_eligibility)
            elif kind == "secant_projection":
                self._secant_visual_projection = raw.get("live_view")
                if self._secant_presenter is not None:
                    self._secant_presenter.host.set_projection(self._secant_visual_projection)
                self.secant_projection_changed.emit(raw.get("live_view"))
            elif kind == "secant_break_selection":
                self.secant_break_selection_requested.emit(dict(raw))
            elif kind == "normal_surface_fence":
                self.normal_surface_fence_requested.emit(dict(raw))
            elif self._secant_presenter is None:
                # Retain custody until the GUI host exists; no invented failure
                # or closure acknowledgement for an unobserved surface.
                self._pending_secant_presentation.append((kind, dict(raw)))
            elif self._secant_presenter is not None:
                presenter = self._secant_presenter
                if kind == "secant_popup":
                    presenter.deliver(raw.get("request"))
                elif kind == "secant_close":
                    presenter.request_close(raw.get("request_id"),raw.get("occurred_monotonic_ns"))
                elif kind == "secant_action_result":
                    presenter.host.action_result(raw.get("request_id"),bool(raw.get("accepted")),
                        action_sequence=raw.get("action_sequence"))
            return True

        routes = {
            "control_view": self.control_view_changed,
            "study_runtime_view": self.study_view_changed,
            "study_start_transition": self.study_start_transition_changed,
            "cosecant_view": self.study_view_changed,
            "cosine_live_status": self.cosine_live_status_changed,
            "handover_live_status": self.handover_live_status_changed,
            "resource_intent_live_status": self.resource_intent_live_status_changed,
            "sine_watch_status": self.sine_watch_status_changed,
            "mine_watch_status": self.mine_watch_status_changed,
            "mirl_health_status": self.mirl_health_status_changed,
        }
        signal = routes.get(kind)
        if signal is not None:
            signal.emit(raw.get("live_view"))
            return True

        if kind == "handover_family_signal":
            self.handover_family_signal_received.emit(raw)
            return True

        if kind == "sine_fact":
            presenter = self._sine_presenter
            if presenter is not None:
                presenter.apply_fact(raw.get("fact"))
            self.sine_fact_received.emit(raw.get("fact"))
            # Every SINE fact still reaches the popup presenter, but Phase 2
            # semantic facts also belong in the append-only Live Telemetry
            # feed.  Monitor is the meaning authority: a non-empty badge says
            # it prepared this exact fact for user-visible transport.  Do not
            # swallow that prepared row at the presentation bridge.
            return not bool(str(raw.get("badge", "") or "").strip())

        if kind == "normal_break_fact":
            presenter = self._normal_break_presenter
            fact = raw.get("fact")
            if presenter is not None:
                presenter.apply_fact(fact)
            self.normal_break_fact_changed.emit(fact)
            # Preserve the pre-Phase-3 append-only telemetry row while also
            # delivering the same immutable fact to its presentation surface.
            return False

        if kind == "mirl_episode_closed":
            self.mirl_fact_received.emit(raw.get("fact"))
            # Transport only: no MIRL success/failure decision is made here.
            # Preserve the existing (pre-Phase-2E) Live Telemetry row exactly
            # as before -- this kind was never swallowed here previously.
            return False

        if kind == "cosecant_fact":
            self.cosecant_fact_received.emit(raw.get("fact"))
            # Transport only: no Green/base decision is made here.  Preserve
            # the existing Live Telemetry row exactly as before -- this kind
            # was never swallowed here previously.
            return False

        if kind == "resource_intent_fact":
            presenter = self._study_confirmation_presenter
            if presenter is not None:
                presenter.apply_fact(raw.get("fact"))
            # Monitor alone decides which Resource Intent facts are semantic
            # history. Presentation consumes every fact, while prepared badge
            # rows continue unchanged to Live Telemetry.
            return not bool(str(raw.get("badge", "") or "").strip())

        if kind == "cosine_effect":
            effect = raw.get("effect")
            if effect is None:
                return True
            from COSINE.cosine import EffectKind
            from COSINE.popup import dispatch_cosine_effect
            if getattr(effect, "kind", None) is EffectKind.REQUEST_NORMAL_STOP:
                self.normal_stop_requested.emit()
                return True
            delivered = dispatch_cosine_effect(
                effect, submit_command=self.submit_cosine_command
            )
            if not delivered and getattr(effect, "kind", None) in {
                EffectKind.SHOW_INTENT_GATE,
                EffectKind.SHOW_DURATION_ENTRY,
                EffectKind.SHOW_BREAK_ACK,
                EffectKind.SHOW_FINAL_CALLBACK,
            }:
                self._emit_failure("COSINE popup dispatcher rejected a show effect")
            return True

        if kind == "mine_effect":
            effect = raw.get("effect")
            if effect is None:
                return True
            from MINE.mine import MineEffectKind
            from MINE.popup import dispatch_mine_effect
            delivered = dispatch_mine_effect(
                effect, submit_command=self.submit_mine_command
            )
            if not delivered and getattr(effect, "kind", None) in {
                MineEffectKind.SHOW_MINE1,
                MineEffectKind.SHOW_IMPORTANT_DURATION,
                MineEffectKind.SHOW_MINE2,
            }:
                self._emit_failure("MINE popup dispatcher rejected a show effect")
            return True

        if kind == "protected_red_status":
            active = bool(raw.get("active", False))
            changed = active != self._protected_red_active
            self._protected_red_active = active
            if changed:
                self.protected_red_changed.emit(active)
            return True

        if kind == "emergency_completed":
            self.emergency_completed.emit(bool(raw.get("exit_permitted", False)))
            return True

        if kind == "session":
            # Core Engine emits this kind exactly twice per run (session
            # open, then cleanup complete), always carrying the same
            # authoritative committed session_id.  Mirror it read-only;
            # _finish_worker_exit clears it once the worker has actually
            # exited.  Preserve the existing Live Telemetry row exactly as
            # before -- this kind was never swallowed here previously.
            raw_session_id = raw.get("session_id")
            if isinstance(raw_session_id, int) and raw_session_id != self._current_session_id:
                self._current_session_id = raw_session_id
                self.current_session_id_changed.emit(raw_session_id)
            return False

        return False

    # ------------------------------------------------------------------
    # Presentation timer and factual worker completion
    # ------------------------------------------------------------------
    def _accumulate_active_time(self, now: float | None = None) -> None:
        if self._last_active_tick is None:
            return
        current = time.monotonic() if now is None else now
        if self._status is EngineStatus.ACTIVE:
            self._active_seconds += max(0.0, current - self._last_active_tick)
        self._last_active_tick = current

    def _update_elapsed_time(self) -> None:
        if self._status not in {EngineStatus.ACTIVE, EngineStatus.PAUSED}:
            return
        self._accumulate_active_time()
        self.session_time_changed.emit(int(self._active_seconds))

    def _finish_worker_exit(self) -> None:
        """Publish STOPPED only when Core Engine cleanup is factual."""

        self._drain_telemetry(drain_all=True)
        self._retire_command_replies()
        pending_confirmation_ids = tuple(self._pending_study_confirmation_actions)
        self._pending_study_confirmation_actions.clear()
        if self._study_confirmation_presenter is not None:
            for request_id in pending_confirmation_ids:
                self._study_confirmation_presenter.show_action_rejection(
                    request_id, "CLARIFICATION NOT ACCEPTED · ENGINE STOPPED"
                )
        self.study_start_transition_changed.emit({})
        if self._pending_study_prepare is not None:
            self._pending_study_prepare = None
            self.study_prepare_result.emit({
                "accepted": False, "message": "Engine stopped before PREPARE completed."
            })
        errors = self._drain_worker_errors()
        if self._startup_failure_reported:
            errors = (*errors, "Core Engine startup did not complete")
        cleanup_complete = self._cleanup_complete_event.is_set()

        self._is_monitoring = False
        self._startup_deadline = None
        self._last_active_tick = None
        self._active_seconds = 0.0
        self._worker_thread = None
        # The worker is gone -- clean stop or not -- so there is no valid
        # current session left to expose (Phase C session-identity seam).
        if self._current_session_id is not None:
            self._current_session_id = None
            self.current_session_id_changed.emit(None)
        self._worker_timer.stop()
        self._telemetry_timer.stop()
        self._elapsed_timer.stop()
        self._release_report_lease()

        if errors or not cleanup_complete:
            details = list(errors)
            if not cleanup_complete:
                details.append("Core Engine exited without cleanup confirmation")
            self._set_status(EngineStatus.ERROR)
            self._emit_failure(" | ".join(details))
            return

        self._set_status(EngineStatus.STOPPED)
        self.engine_stopped.emit()

    def shutdown(self) -> None:
        if self._sine_presenter is not None:
            try:
                self._sine_presenter.emergency_close_all("controller_shutdown")
            except Exception:
                pass
        if self._study_confirmation_presenter is not None:
            try:
                self._study_confirmation_presenter.close_all("controller_shutdown")
            except Exception:
                pass
        if self._normal_break_presenter is not None:
            try:
                self._normal_break_presenter.close_all()
            except Exception:
                pass
        try:
            from COSINE.popup import shutdown_cosine_dispatcher
            shutdown_cosine_dispatcher()
        except Exception:
            pass
        try:
            from MINE.popup import shutdown_mine_dispatcher
            shutdown_mine_dispatcher()
        except Exception:
            pass
        """Release Qt resources after lifecycle.py approves shutdown.

        Instruction: this method never joins or waits for a worker on the GUI
        thread.  lifecycle.py must authorize final shutdown only after its
        bounded barrier has received the factual worker completion.
        """

        if self._is_shutting_down:
            return
        self._is_shutting_down = True

        self._stop_event.set()
        self._pause_event.clear()
        self._worker_timer.stop()
        self._telemetry_timer.stop()
        self._elapsed_timer.stop()
        self._pending_study_confirmation_actions.clear()

        thread_alive = bool(
            self._worker_thread is not None and self._worker_thread.is_alive()
        )
        if not thread_alive:
            self._release_report_lease()

    def _set_status(self, status: EngineStatus) -> None:
        if self._status is status:
            return
        self._status = status
        self.engine_status_changed.emit(status)

    def _fail_start(self, message: str) -> None:
        self._set_status(EngineStatus.ERROR)
        self._emit_failure(message)

    def _emit_failure(self, message: str) -> None:
        safe = " ".join(str(message).split())[:400]
        LOGGER.error("MYELIN Core Engine connection failed: %s", safe)
        self.engine_failed.emit(safe)

    def _drain_worker_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        while True:
            try:
                errors.append(self._worker_errors.get_nowait())
            except queue.Empty:
                return tuple(errors)

    def _release_report_lease(self) -> None:
        lease = self._report_session_lease
        self._report_session_lease = None
        if lease is not None:
            try:
                lease.release()
            except Exception as exc:
                LOGGER.error("Could not release report session lease: %s", exc)

    @staticmethod
    def _safe_error(exc: BaseException) -> str:
        """Return bounded one-line diagnostics without exposing payload data."""

        text = " ".join(str(exc).split())
        return f"{type(exc).__name__}: {text}"[:240]
