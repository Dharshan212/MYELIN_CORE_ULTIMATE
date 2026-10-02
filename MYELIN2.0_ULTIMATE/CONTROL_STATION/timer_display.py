"""Read-only clock faces. No authority calls, sensing, evidence, or persistence.

Deadline clocks read absolute monotonic anchors. Evidence displays interpolate
only BETWEEN already-confirmed values, never beyond the newest supported value.
Their presentation can lag a healthy sample by one interval. A stalled GUI,
changed attempt, hold, reset, or overdue publication snaps to factual progress.
"""
from __future__ import annotations

import math
import time

FRAME_MS = 200
NS = 1_000_000_000


def field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def enum_text(value):
    return str(getattr(value, "value", value) or "")


def countdown(seconds):
    if seconds is None:
        return "—"
    total = math.ceil(max(0.0, float(seconds)))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    return (f"{hours:02d}:" if hours else "") + f"{minutes:02d}:{seconds:02d}"


def remaining(deadline_ns, *, now_ns=None):
    if deadline_ns is None:
        return None
    now = time.monotonic_ns() if now_ns is None else now_ns
    return max(0, int(deadline_ns) - now) / NS


def start_frames(owner, callback):
    from PyQt6.QtCore import QTimer
    timer = QTimer(owner)
    timer.setInterval(FRAME_MS)
    timer.timeout.connect(callback)
    timer.start()
    return timer


class EvidenceCountdown:
    """Animate confirmed progress only; never infer continued qualifying input."""
    def __init__(self, clock=time.monotonic_ns):
        self.clock = clock
        self.key = None
        self.target = self.start = None
        self.arrival = self.last_frame = None
        self.span = 0

    def update(self, key, value, *, held=False):
        now = self.clock()
        value = None if value is None else max(0.0, float(value))
        previous_frame = self.last_frame
        previous = self.value(now_ns=now)
        gap = 0 if self.arrival is None else now - self.arrival
        # Bounds below govern cosmetic interpolation, never physiological time.
        healthy = (key == self.key and not held and previous is not None
                   and value is not None and 0 < gap <= 2 * NS
                   and 0 <= previous - value <= 2.1
                   and previous_frame is not None and now - previous_frame <= NS)
        self.key, self.target = key, value
        self.start = previous if healthy else value
        self.arrival, self.span = now, gap if healthy else 0

    def value(self, *, now_ns=None):
        now = self.clock() if now_ns is None else now_ns
        stalled = self.last_frame is not None and now - self.last_frame > NS
        self.last_frame = now
        if stalled:
            self.start, self.span = self.target, 0
        if self.target is None or not self.span:
            return self.target
        fraction = min(1.0, max(0.0, (now - self.arrival) / self.span))
        return max(self.target, self.start + (self.target - self.start) * fraction)


def cosecant_remaining(snapshot, *, now_ns=None):
    state = enum_text(field(snapshot, "state"))
    deadline_field = {
        "BREAK_ACTIVE": "break_ends_monotonic_ns",
        "BREAK_COMPLETE": "already_over_due_monotonic_ns",
        "BREAK_ALREADY_OVER": "final_lock_due_monotonic_ns",
    }.get(state)
    if deadline_field:
        return remaining(field(snapshot, deadline_field), now_ns=now_ns)
    # Return confirmation is supported evidence. It never runs from this clock.
    return field(snapshot, "seconds_to_next_stage")


def secant_remaining(projection, *, now_ns=None):
    held = (field(projection, "frozen_reasons", ()) or field(projection, "global_hold_id")
            or field(projection, "uncertainty_hold_id")
            or field(field(projection, "break_pause"), "pause_id")
            or field(projection, "cleanup_pending") or field(projection, "terminal_reason"))
    deadline = field(projection, "escalation_deadline_monotonic_ns")
    if deadline is not None and not held:
        return remaining(deadline, now_ns=now_ns)
    ns = field(projection, "escalation_remaining_ns")
    return None if ns is None else ns / NS


class SnapshotCountdown:
    """One card's clock; phase and stage always remain backend-owned."""
    def __init__(self):
        self.evidence = EvidenceCountdown()
        self.deadline = None
        self.frozen = None

    def update(self, snapshot, name, *, deadline_name=None):
        phase = enum_text(field(snapshot, "phase"))
        paused = bool(field(snapshot, "global_paused", False) or field(snapshot, "study_preempted", False))
        value = field(snapshot, name) if name else None
        self.deadline = field(snapshot, deadline_name) if deadline_name and not paused else None
        self.frozen = value if deadline_name and paused else None
        identity = (field(snapshot, "parent_session_id", field(snapshot, "session_id")),
                    field(snapshot, "mine_episode_id", field(snapshot, "cosine_session_id")),
                    field(snapshot, "generation"), phase, name, paused)
        self.evidence.update(identity, value, held=paused)

    def text(self):
        if self.deadline:
            return countdown(remaining(self.deadline))
        if self.frozen is not None:
            return countdown(self.frozen)
        return countdown(self.evidence.value())
