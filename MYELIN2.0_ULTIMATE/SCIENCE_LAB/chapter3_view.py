"""Chapter 3 -- Data Analysis: the common behavioural episode bar, its
separate break lane, and the Key Metrics panel beneath it.

DUMMY-FIRST VISUAL FOUNDATION (Chapter 3 Phase 1 spec, 2026-09-12 section
48; Phase 2 spec, 2026-09-12 section 0), now with a post-freeze live
presentation seam: this module builds visual anatomy, renders immutable
host-supplied live projections, and exposes presentation-only experiment
request signals. It does not attach to an experiment itself, query MINE /
COSINE / MIRL / SINE, or create any experiment table.
The Behavioural Timeline's PLAY / SIMULATE BREAK / REPLAY controls drive a
local, bounded QTimer sequence -- they never reach any MYELIN organ,
session, or timer, exactly like Chapter 2's schematic demo controls.  All
example timings and proportions are DEMO SPEED / EXAMPLE ONLY and must
never be read as production policy or as real evidence.  The Key Metrics
panel's eight cards render only: every value defaults to the frozen
no-fake-telemetry placeholder ("--" / an honest qualifier such as
"Awaiting evidence") and this module never computes a metric -- no summed
duration, no derived rate, no inferred relapse (Phase 2 spec section 33).

Phase 1 built ONE continuous common bar (Off-task dwell -> Trigger ->
Return -> Verified return -> Episode closure) whose structure never
changes across organs, plus a break that is never a colour segment inside
that bar but a completely separate lane below it -- this is the protected
baseline (Phase 2 spec section 1) and Phase 2 does not redesign it.  Phase
2 adds the Key Metrics panel directly beneath it: eight frozen research
cards (spec section 4) summarising the same behavioural story the timeline
shows, in the frozen order task-aligned time / off-task dwell / return
latency / verified returns / relapses / post-return persistence / context
switches / experiment duration.  The remaining Chapter 3 panels (Live
Evidence Feed, Derived Findings, Limitations, Controls) are a later phase
and are intentionally not built here.

Import boundary (same one-directional composition every Science Lab
chapter module already uses): this module may import PyQt6 and
UI_THEMES.theme.  It must NOT import CORE_ENGINE, SINE, MINE, COSINE, MIRL,
COSECANT_STUDY_MODE, PERSISTENCE, sqlite3, or SCIENCE_LAB.lab (lab.py hosts
this module; this module never reaches back into lab.py).  It also does not
import SCIENCE_LAB.schematics: each chapter module stays independent, so a
Chapter 2 change can never silently move Chapter 3's floor.
"""

from __future__ import annotations

import math
from typing import Callable, Final

from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from UI_THEMES.theme import STAGE_BLUE, STAGE_PURPLE, make_font
from .live_timeline import (
    LiveOrganTimelineState,
    MODE_EXPERIMENT_ENDED,
    MODE_FINALIZING,
    MODE_INTERRUPTED,
    MODE_LIVE,
    STATUS_ACTIVE,
    STATUS_COMPLETE,
    STATUS_PAUSED,
)

# Metric-card accents reuse the Phase-1 protected stage colours (spec
# section 43: Phase 2 does not own the timeline palette) plus the two
# theme-invariant semantic tokens (green/cyan keep the same hex on every
# base-theme world -- see UI_THEMES.theme's per-world ThemeTokens; only
# cyan's own dominant-accent slot would vary, and Episode Closure already
# claims that behaviour, so metric icons fix their own hex exactly like
# every other organ-identity icon in this codebase, e.g. SINE's #3DDCFF).
_ACCENT_GREEN: Final = "#22C55E"
_ACCENT_CYAN: Final = "#38BDF8"
_ICON_MUTED: Final = "#94A3B8"

# Normalised stage contract (spec section 9).  Order and keys are frozen --
# only the demo's position within this order ever animates.
_STAGE_KEYS: Final = (
    "OFF_TASK_DWELL",
    "TRIGGER",
    "RETURN",
    "VERIFIED_RETURN",
    "EPISODE_CLOSURE",
)
_STAGE_LABELS: Final = {
    "OFF_TASK_DWELL": "Off-task dwell",
    "TRIGGER": "Trigger",
    "RETURN": "Return",
    "VERIFIED_RETURN": "Verified return",
    "EPISODE_CLOSURE": "Episode closure",
}
_STAGE_OBJECT_NAMES: Final = {
    "OFF_TASK_DWELL": "chapter3StageOffTaskDwell",
    "TRIGGER": "chapter3StageTrigger",
    "RETURN": "chapter3StageReturn",
    "VERIFIED_RETURN": "chapter3StageVerifiedReturn",
    "EPISODE_CLOSURE": "chapter3StageEpisodeClosure",
}
# Demo-only relative widths -- EXAMPLE ONLY (spec sections 33/48: no fake
# production numbers).  Trigger is a point event (section 37) so it keeps a
# narrow boundary width rather than a fabricated duration.
_STAGE_WEIGHTS: Final = {
    "OFF_TASK_DWELL": 5,
    "TRIGGER": 1,
    "RETURN": 3,
    "VERIFIED_RETURN": 2,
    "EPISODE_CLOSURE": 1,
}

# Chapter 3's four-organ presentation selector (spec section 26) -- a
# filter over which example annotation is shown, never a runtime control.
_ORGANS: Final = ("SINE", "MINE", "COSINE", "COSECANT")

# Organ-specific EXAMPLE annotation for the Trigger boundary (spec sections
# 16/19/21/23) -- demonstration copy only, never imported from the organ
# runtime.  The bar's structure above never changes; only this line does.
_ORGAN_TRIGGER_NOTES: Final = {
    "SINE": "EXAMPLE: durable trigger admission -- first factual SINE display boundary.",
    "MINE": "EXAMPLE: MINE-1 factual display -- initial messaging-gate boundary.",
    "COSINE": "EXAMPLE: COSINE intention-gate display, or the final callback on break re-entry.",
    "COSECANT": "EXAMPLE: BREAK_COMPLETE -- the approved Study break deadline has ended.",
}

_STEP_MS: Final = 900

#: Stationary fallback fill fraction for a live stage/break whose authoritative
#: elapsed/total pair is not exposed (spec: calm stationary active state, never
#: an oscillating/bidirectional sweep implying an unearned percentage).
_INDETERMINATE_FILL_RATIO: Final = 0.28

# Phase-2 frozen metric set (spec sections 4, 29, 96) -- exactly these eight
# cards, in exactly this order.  Every field here is presentation copy: the
# dummy ``qualifier`` strings are the spec's own no-data wording (section
# 34), and ``type_badge`` is the spec's measurement-type vocabulary
# (section 12) -- MEASURED / DERIVED / COUNT / DURATION only, never AI
# ESTIMATE / NEURAL / COGNITIVE SCORE.  Nothing here is ever computed by
# this module (section 33): nothing derives a value, sums a duration, or
# infers a relapse.
_METRIC_DEFINITIONS: Final = (
    {
        "key": "task_aligned_time",
        "title": "Task-aligned time",
        "icon": "target",
        "accent": None,
        "type_badge": "MEASURED · DURATION",
        "qualifier": "Awaiting experiment evidence",
        "tooltip": "Duration supported as aligned with the intended task.",
        "accessible_name": "Task-aligned time metric",
    },
    {
        "key": "off_task_dwell",
        "title": "Off-task dwell",
        "icon": "diverge",
        "accent": STAGE_BLUE,
        "type_badge": "MEASURED · DURATION",
        "qualifier": "Awaiting off-task evidence",
        "tooltip": "Duration represented as off-task in the approved behavioural timeline.",
        "accessible_name": "Off-task dwell metric",
    },
    {
        "key": "return_latency",
        "title": "Return latency",
        "icon": "return_clock",
        "accent": STAGE_PURPLE,
        "type_badge": "DERIVED · DURATION",
        "qualifier": "Awaiting approved return evidence",
        "tooltip": "Time associated with the approved return pathway.",
        "accessible_name": "Return latency metric",
    },
    {
        "key": "verified_returns",
        "title": "Verified returns",
        "icon": "check_return",
        "accent": _ACCENT_GREEN,
        "type_badge": "COUNT",
        "qualifier": "Awaiting verified-return evidence",
        "tooltip": "Returns confirmed by the relevant MYELIN recovery authority.",
        "accessible_name": "Verified returns metric",
    },
    {
        "key": "relapses",
        "title": "Relapses",
        "icon": "loop",
        "accent": None,
        "type_badge": "COUNT",
        "qualifier": "Awaiting relapse evidence",
        "tooltip": "Approved recovery interruptions after return.",
        "accessible_name": "Relapses metric",
    },
    {
        "key": "post_return_persistence",
        "title": "Post-return persistence",
        "icon": "wave",
        "accent": None,
        "type_badge": "DERIVED · DURATION",
        "qualifier": "Awaiting post-return evidence",
        "tooltip": "Aligned duration maintained after verified return.",
        "accessible_name": "Post-return persistence metric",
    },
    {
        "key": "context_switches",
        "title": "Context switches",
        "icon": "swap",
        "accent": None,
        "type_badge": "COUNT",
        "qualifier": "Awaiting context evidence",
        "tooltip": "Meaningful behavioural context transitions.",
        "accessible_name": "Context switches metric",
    },
    {
        "key": "experiment_duration",
        "title": "Experiment duration",
        "icon": "hourglass",
        "accent": _ACCENT_CYAN,
        "type_badge": "MEASURED · DURATION",
        "qualifier": "No active experiment",
        "tooltip": "Elapsed duration of the Science Lab experiment window.",
        "accessible_name": "Experiment duration metric",
    },
)


# Phase-3 event stage-kind vocabulary (spec section 17) -- reuses the
# exact Phase-1 stage semantics plus "break" and a neutral fallback for an
# event that is not yet one of the six recognised stages.  Nothing here is
# a new colour system (section 50): QSS resolves each kind to
# STAGE_BLUE/red/STAGE_PURPLE/green/cyan/amber, the same tokens the
# timeline itself already uses.
_EVENT_STAGE_KINDS: Final = (
    "off_task_dwell",
    "trigger",
    "return",
    "verified_return",
    "episode_closure",
    "break",
    "neutral",
)

# Phase-4 frozen source roster (spec section 35) -- presentation order
# only, not a coverage ranking.
_SOURCE_COVERAGE_ROSTER: Final = (
    "MINE",
    "COSINE",
    "MIRL",
    "SINE",
    "NORMAL BREAK",
    "STUDY",
    "COSECANT",
    "RESOURCE INTENT",
)

# Canonical Science Lab source-status vocabulary (spec section 28) --
# exactly these three, plus "pending" for this dummy page's honest
# not-yet-sampled default.  Never a fourth status invented here.
_COVERAGE_STATUS_KINDS: Final = ("available", "no_evidence", "unavailable", "pending")

# Coverage legend copy (spec section 34) -- static explanatory text, safe
# to show even with no live snapshot.
_COVERAGE_LEGEND: Final = (
    ("AVAILABLE", "Safe read authority + matching evidence."),
    ("NO EVIDENCE", "Safe read authority + no matching evidence."),
    ("UNAVAILABLE", "Source cannot currently be read safely."),
)

# Static measurement-boundary text (spec section 102) -- exact approved
# wording, scientifically aligned with Chapter 1.
_MEASUREMENT_BOUNDARY_TEXT: Final = (
    "Science Lab measures behavioral/software evidence around task alignment, "
    "divergence, intervention, return, and recovery. It does not directly measure "
    "dopamine, neural firing, brain-network activity, motivation, boredom, stress, "
    "fatigue, or subjective effort."
)


def _allow_shrink(widget: QWidget) -> None:
    """Let a widget shrink below its natural width instead of forcing the
    ancestor layout's minimum width up with it (same technique as Chapter
    1/2)."""

    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)


def _small_caption(text: str, *, role: str = "muted") -> QLabel:
    caption = QLabel(text)
    caption.setWordWrap(True)
    caption.setProperty("role", role)
    caption.setFont(make_font(9.5, 400))
    _allow_shrink(caption)
    return caption


class _DemoButton(QPushButton):
    """A demo-only button -- wired exclusively to local animation state in
    this module, never to any MYELIN authority (same convention as
    SCIENCE_LAB.schematics._DemoButton)."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("chapter3DemoButton")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(make_font(10.5, 700, spacing=0.4))


class _LiveStageSegment(QFrame):
    """One themed stage shell with a left-to-right live fill child."""

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setProperty("segmentState", "pending")
        self._fill = QFrame(self)
        self._fill.setObjectName(object_name)
        self._fill.setProperty("segmentState", "active")
        self._fill.hide()
        self._live_status = "PENDING"
        self._live_progress: float | None = None

    def set_static_state(self, state: str) -> None:
        self._live_status = "STATIC"
        self._fill.hide()
        self.setProperty("segmentState", state)
        self._repolish(self)

    def set_live_state(
        self,
        status: str,
        progress: float | None,
    ) -> None:
        self._live_status = status
        self._live_progress = progress
        if status == STATUS_COMPLETE:
            self._fill.hide()
            self.setProperty("segmentState", "historical")
        elif status in {STATUS_ACTIVE, STATUS_PAUSED}:
            self.setProperty("segmentState", "pending")
            self._fill.setProperty(
                "segmentState", "active" if status == STATUS_ACTIVE else "historical"
            )
            self._repolish(self._fill)
            self._fill.show()
            self._layout_fill()
        else:
            self._fill.hide()
            self.setProperty("segmentState", "pending")
        self._repolish(self)

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt API
        super().resizeEvent(event)
        self._layout_fill()

    def _layout_fill(self) -> None:
        if self._live_status not in {STATUS_ACTIVE, STATUS_PAUSED}:
            return
        width = max(0, self.width())
        height = max(0, self.height())
        if self._live_progress is not None:
            fill_width = max(0, min(width, round(width * self._live_progress)))
            self._fill.setGeometry(0, 0, fill_width, height)
            self._fill.setVisible(fill_width > 0)
            return
        # Authoritative duration is not exposed for this stage: hold a calm,
        # stationary highlight rather than implying a percentage or moving it
        # back and forth.
        chunk = max(8, min(width, round(width * _INDETERMINATE_FILL_RATIO)))
        self._fill.setGeometry(0, 0, chunk, height)
        self._fill.setVisible(True)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class _EpisodeBar(QFrame):
    """The one common, continuous behavioural episode bar (spec section 7).

    The five stages are always present in the same fixed order and never
    change identity or position -- only ``set_active_stage``/``set_frozen``
    move.  A not-yet-reached stage is rendered ``pending`` (muted grey) --
    it must never borrow a semantic colour it has not earned; a stage the
    episode has already passed through is ``historical`` (calm, same hue);
    the current stage is ``active`` (full-strength fill).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3TimelineTrack")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)

        self._segments: dict[str, _LiveStageSegment] = {}
        self._labels: dict[str, QLabel] = {}
        for key in _STAGE_KEYS:
            column = QVBoxLayout()
            column.setSpacing(6)

            segment = _LiveStageSegment(_STAGE_OBJECT_NAMES[key])
            segment.setFixedHeight(40)
            segment.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            column.addWidget(segment)
            self._segments[key] = segment

            stage_label = QLabel(_STAGE_LABELS[key].upper())
            stage_label.setObjectName("chapter3StageLabel")
            stage_label.setProperty("segmentState", "pending")
            stage_label.setFont(make_font(9.5, 700, spacing=0.4))
            stage_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            stage_label.setWordWrap(True)
            _allow_shrink(stage_label)
            column.addWidget(stage_label)
            self._labels[key] = stage_label

            row.addLayout(column, _STAGE_WEIGHTS[key])

        self._active_index = -1
        self._frozen = False

    def set_active_stage(self, stage_key: str | None) -> None:
        """Advance the leading edge.  ``None`` resets every segment back to
        pending (episode not yet started)."""

        index = _STAGE_KEYS.index(stage_key) if stage_key is not None else -1
        if index == self._active_index:
            return
        self._active_index = index
        for position, key in enumerate(_STAGE_KEYS):
            if position < index:
                state = "historical"
            elif position == index:
                state = "active" if not self._frozen else "historical"
            else:
                state = "pending"
            self._apply_state(key, state)

    def set_frozen(self, frozen: bool) -> None:
        """Break-pause visual (spec section 40): the active edge stops
        reading as live while the break lane owns the clock, but every
        segment stays exactly as it was -- never a blank gap."""

        if frozen == self._frozen:
            return
        self._frozen = frozen
        if self._active_index < 0:
            return
        key = _STAGE_KEYS[self._active_index]
        self._apply_state(key, "historical" if frozen else "active")

    def reset(self) -> None:
        self._frozen = False
        self.set_active_stage(None)

    def render_certified_stages(self, stage_keys: tuple[str, ...]) -> None:
        """Show only stages present in an already-certified event tuple."""

        self._active_index = -1
        self._frozen = False
        present = set(stage_keys)
        for key in _STAGE_KEYS:
            self._apply_state(key, "historical" if key in present else "pending")

    def render_live_stages(
        self,
        stages: tuple[object, ...],
        visual_progress: dict[str, float],
    ) -> None:
        """Render host-normalised live rows; derive no timing here."""

        by_stage = {str(getattr(row, "stage", "")): row for row in stages}
        self._active_index = -1
        self._frozen = False
        for position, key in enumerate(_STAGE_KEYS):
            row = by_stage.get(key)
            status = str(getattr(row, "status", "PENDING"))
            if status in {STATUS_ACTIVE, STATUS_PAUSED}:
                self._active_index = position
            progress = visual_progress.get(key)
            if getattr(row, "progress", None) is None:
                progress = None
            self._segments[key].set_live_state(status, progress)
            label_state = (
                "active"
                if status == STATUS_ACTIVE
                else "historical"
                if status in {STATUS_COMPLETE, STATUS_PAUSED}
                else "pending"
            )
            self._labels[key].setProperty("segmentState", label_state)
            self._labels[key].style().unpolish(self._labels[key])
            self._labels[key].style().polish(self._labels[key])

    def _apply_state(self, key: str, state: str) -> None:
        self._segments[key].set_static_state(state)
        widget = self._labels[key]
        widget.setProperty("segmentState", state)
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class _BreakLane(QFrame):
    """The separate lower break lane (spec sections 12-14, 39-41).

    Hidden until an approved break becomes active.  It never consumes a
    colour segment inside the upper bar -- it is a physically separate
    frame with its own start/end markers and its own amber identity.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3BreakLane")
        self.setVisible(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        self._badge = QLabel("BREAK ACTIVE")
        self._badge.setObjectName("chapter3BreakBadge")
        self._badge.setFont(make_font(9.5, 800, spacing=0.6))
        header.addWidget(self._badge)
        self._caption = _small_caption("Approved break running (DEMO). Main bar is paused, not deleted.")
        header.addWidget(self._caption, 1)
        outer.addLayout(header)

        track = QFrame()
        track.setObjectName("chapter3BreakTrack")
        track.setFixedHeight(12)
        self._track_layout = QHBoxLayout(track)
        self._track_layout.setContentsMargins(2, 2, 2, 2)
        self._track_layout.setSpacing(0)
        self._fill = QFrame()
        self._fill.setObjectName("chapter3BreakFill")
        self._track_layout.addWidget(self._fill, 1)
        self._track_layout.addStretch(0)
        outer.addWidget(track)
        self.set_progress(0.0)

    def start(self) -> None:
        self.set_progress(0.0)
        self._badge.setText("BREAK ACTIVE")
        self._caption.setText("Approved break running (DEMO). Main bar is paused, not deleted.")
        self.setVisible(True)

    def set_progress(self, fraction: float) -> None:
        fraction = max(0.0, min(1.0, fraction))
        filled = max(round(fraction * 100), 0)
        remainder = max(100 - filled, 0)
        self._track_layout.setStretch(0, filled)
        self._track_layout.setStretch(1, remainder)
        self._fill.setVisible(filled > 0)

    def render_live(self, row: object) -> None:
        """Render one already-normalised break row without owning its clock."""

        status = str(getattr(row, "status", STATUS_ACTIVE))
        progress = getattr(row, "progress", None)
        if progress is None:
            # No authoritative total is exposed for this break: hold a calm,
            # stationary fraction instead of implying a moving percentage.
            progress = _INDETERMINATE_FILL_RATIO
        self.set_progress(float(progress))
        self._badge.setText("BREAK PAUSED" if status == STATUS_PAUSED else "BREAK ACTIVE")
        self._caption.setText(str(getattr(row, "reason", "Authoritative break state.")))
        self.setVisible(True)

    def complete(self) -> None:
        self.set_progress(1.0)
        self._badge.setText("BREAK COMPLETE")
        self._caption.setText("Break finished (DEMO). Returning to the Trigger / recovery pathway.")

    def hide_lane(self) -> None:
        self.setVisible(False)

    def render_final(self, event_count: int) -> None:
        """Render the factual final break lane without implying live state."""

        if event_count <= 0:
            self.hide_lane()
            return
        self.set_progress(1.0)
        self._badge.setText("BREAK EVIDENCE")
        self._caption.setText(
            f"{event_count} approved break-lane event(s) in the selected experiment."
        )
        self.setVisible(True)


class _MetricIcon(QWidget):
    """One deterministic, Qt-drawn metric glyph (spec section 30).

    Always static -- no active/inactive state, no continuous animation
    (spec section 47): metric cards provide a stable quantitative reading,
    not a living visual like the timeline.  ``accent`` is a fixed hex,
    same convention as every other organ-identity icon in this codebase
    (e.g. SINE's ``_Node`` accent="#3DDCFF"): it does not react to the
    active theme world.
    """

    def __init__(self, kind: str, *, accent: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._color = QColor(accent or _ICON_MUTED)
        self.setFixedSize(26, 26)

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(self._color)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        w, h = float(self.width()), float(self.height())
        drawer = getattr(self, f"_draw_{self._kind}", None)
        if drawer is not None:
            drawer(painter, w, h)
        painter.end()

    def _draw_target(self, painter: QPainter, w: float, h: float) -> None:
        # TASK-ALIGNED TIME: bullseye / aligned path.
        cx, cy = w / 2, h / 2
        painter.drawEllipse(QPointF(cx, cy), w * 0.40, h * 0.40)
        painter.drawEllipse(QPointF(cx, cy), w * 0.22, h * 0.22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QPointF(cx, cy), w * 0.07, h * 0.07)

    def _draw_diverge(self, painter: QPainter, w: float, h: float) -> None:
        # OFF-TASK DWELL: one path forking away from the intended line.
        painter.drawLine(QPointF(w * 0.5, h * 0.86), QPointF(w * 0.5, h * 0.5))
        painter.drawLine(QPointF(w * 0.5, h * 0.5), QPointF(w * 0.18, h * 0.16))
        painter.drawLine(QPointF(w * 0.5, h * 0.5), QPointF(w * 0.82, h * 0.30))

    def _draw_return_clock(self, painter: QPainter, w: float, h: float) -> None:
        # RETURN LATENCY: clock arc + return arrow.
        rect = QRectF(w * 0.14, h * 0.14, w * 0.72, h * 0.72)
        painter.drawArc(rect, 40 * 16, 260 * 16)
        end_angle_rad = math.radians(40)  # matches the arc's start point
        ex = rect.center().x() + (rect.width() / 2) * math.cos(end_angle_rad)
        ey = rect.center().y() - (rect.height() / 2) * math.sin(end_angle_rad)
        painter.drawLine(QPointF(ex, ey), QPointF(ex - w * 0.12, ey - h * 0.02))
        painter.drawLine(QPointF(ex, ey), QPointF(ex - w * 0.02, ey + h * 0.12))

    def _draw_check_return(self, painter: QPainter, w: float, h: float) -> None:
        # VERIFIED RETURNS: check mark.
        painter.drawLine(QPointF(w * 0.22, h * 0.52), QPointF(w * 0.42, h * 0.72))
        painter.drawLine(QPointF(w * 0.42, h * 0.72), QPointF(w * 0.80, h * 0.28))

    def _draw_loop(self, painter: QPainter, w: float, h: float) -> None:
        # RELAPSES: loop arrow -- a behavioural event, not a moral failure
        # (spec section 22), so this stays the same neutral stroke weight
        # as every other icon.
        rect = QRectF(w * 0.16, h * 0.16, w * 0.68, h * 0.68)
        painter.drawArc(rect, 30 * 16, 300 * 16)
        tip = QPointF(rect.center().x() + (rect.width() / 2), rect.center().y())
        painter.drawLine(tip, QPointF(tip.x() - w * 0.14, tip.y() - h * 0.08))
        painter.drawLine(tip, QPointF(tip.x() - w * 0.02, tip.y() + h * 0.14))

    def _draw_wave(self, painter: QPainter, w: float, h: float) -> None:
        # POST-RETURN PERSISTENCE: continuity line.
        path = QPainterPath()
        path.moveTo(w * 0.14, h * 0.55)
        path.cubicTo(w * 0.30, h * 0.25, w * 0.38, h * 0.25, w * 0.5, h * 0.55)
        path.cubicTo(w * 0.62, h * 0.85, w * 0.70, h * 0.85, w * 0.86, h * 0.55)
        painter.drawPath(path)

    def _draw_swap(self, painter: QPainter, w: float, h: float) -> None:
        # CONTEXT SWITCHES: two crossing/swap arrows.
        painter.drawLine(QPointF(w * 0.18, h * 0.36), QPointF(w * 0.82, h * 0.36))
        painter.drawLine(QPointF(w * 0.82, h * 0.36), QPointF(w * 0.64, h * 0.20))
        painter.drawLine(QPointF(w * 0.82, h * 0.36), QPointF(w * 0.64, h * 0.52))
        painter.drawLine(QPointF(w * 0.82, h * 0.66), QPointF(w * 0.18, h * 0.66))
        painter.drawLine(QPointF(w * 0.18, h * 0.66), QPointF(w * 0.36, h * 0.50))
        painter.drawLine(QPointF(w * 0.18, h * 0.66), QPointF(w * 0.36, h * 0.82))

    def _draw_hourglass(self, painter: QPainter, w: float, h: float) -> None:
        # EXPERIMENT DURATION: hourglass.
        path = QPainterPath()
        path.moveTo(w * 0.22, h * 0.16)
        path.lineTo(w * 0.78, h * 0.16)
        path.lineTo(w * 0.5, h * 0.5)
        path.lineTo(w * 0.78, h * 0.84)
        path.lineTo(w * 0.22, h * 0.84)
        path.lineTo(w * 0.5, h * 0.5)
        path.closeSubpath()
        painter.drawPath(path)

    def _draw_rail(self, painter: QPainter, w: float, h: float) -> None:
        # LIVE EVIDENCE FEED: vertical event rail (spec section 93).
        painter.drawLine(QPointF(w * 0.5, h * 0.12), QPointF(w * 0.5, h * 0.88))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        for fraction in (0.22, 0.5, 0.78):
            painter.drawEllipse(QPointF(w * 0.5, h * fraction), w * 0.09, h * 0.09)

    def _draw_document(self, painter: QPainter, w: float, h: float) -> None:
        # DERIVED FINDINGS: a small result document, never a brain/wand
        # (spec section 160).
        rect = QRectF(w * 0.22, h * 0.12, w * 0.56, h * 0.76)
        painter.drawRoundedRect(rect, 2, 2)
        for fraction in (0.34, 0.5, 0.66):
            painter.drawLine(
                QPointF(rect.left() + w * 0.08, h * fraction),
                QPointF(rect.right() - w * 0.08, h * fraction),
            )

    def _draw_coverage(self, painter: QPainter, w: float, h: float) -> None:
        # SOURCE COVERAGE: stacked evidence lines feeding one node (spec
        # section 161) -- never Wi-Fi bars implying connectivity.
        painter.drawLine(QPointF(w * 0.20, h * 0.28), QPointF(w * 0.55, h * 0.28))
        painter.drawLine(QPointF(w * 0.20, h * 0.5), QPointF(w * 0.55, h * 0.5))
        painter.drawLine(QPointF(w * 0.20, h * 0.72), QPointF(w * 0.55, h * 0.72))
        painter.drawLine(QPointF(w * 0.55, h * 0.28), QPointF(w * 0.72, h * 0.5))
        painter.drawLine(QPointF(w * 0.55, h * 0.5), QPointF(w * 0.72, h * 0.5))
        painter.drawLine(QPointF(w * 0.55, h * 0.72), QPointF(w * 0.72, h * 0.5))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QPointF(w * 0.78, h * 0.5), w * 0.1, h * 0.1)

    def _draw_boundary(self, painter: QPainter, w: float, h: float) -> None:
        # LIMITATIONS: an information/boundary mark (spec section 162) --
        # never a danger siren.
        painter.drawEllipse(QPointF(w * 0.5, h * 0.5), w * 0.36, h * 0.36)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(self._color))
        painter.drawEllipse(QPointF(w * 0.5, h * 0.28), w * 0.055, h * 0.055)
        pen = QPen(self._color)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(w * 0.5, h * 0.42), QPointF(w * 0.5, h * 0.72))


class _Chapter3MetricCard(QFrame):
    """One research metric card (spec sections 9-14, 31, 42).

    Common anatomy for all eight cards -- title/icon, large value, factual
    qualifier, optional type badge, optional evidence-status badge.  This
    class renders only: it never computes a metric (spec section 33).  A
    later phase calls ``set_metric`` with already-approved presentation
    values; nothing here sums a duration, derives a rate, or infers a
    relapse.
    """

    def __init__(self, definition: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3MetricCard")
        self.setAccessibleName(definition["accessible_name"])
        self.setToolTip(definition["tooltip"])
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(10)
        icon = _MetricIcon(definition["icon"], accent=definition["accent"])
        icon.setObjectName("chapter3MetricIcon")
        header.addWidget(icon)
        title = QLabel(definition["title"].upper())
        title.setObjectName("chapter3MetricTitle")
        title.setFont(make_font(10, 700, spacing=0.4))
        title.setWordWrap(True)
        title.setMinimumHeight(32)
        title.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        _allow_shrink(title)
        header.addWidget(title, 1)
        layout.addLayout(header)

        self._value_label = QLabel("—")
        self._value_label.setObjectName("chapter3MetricValue")
        self._value_label.setFont(make_font(22, 800, mono=True))
        self._value_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._value_label)

        self._qualifier_label = QLabel(definition["qualifier"])
        self._qualifier_label.setObjectName("chapter3MetricQualifier")
        self._qualifier_label.setFont(make_font(9.5, 400))
        self._qualifier_label.setWordWrap(True)
        self._qualifier_label.setMinimumHeight(32)
        _allow_shrink(self._qualifier_label)
        layout.addWidget(self._qualifier_label)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        type_badge = QLabel(definition["type_badge"])
        type_badge.setObjectName("chapter3MetricTypeBadge")
        type_badge.setFont(make_font(8.5, 700, spacing=0.6))
        footer.addWidget(type_badge)
        footer.addStretch(1)
        self._status_badge = QLabel("")
        self._status_badge.setObjectName("chapter3MetricStatusBadge")
        self._status_badge.setFont(make_font(8.5, 700, spacing=0.6))
        self._status_badge.setVisible(False)
        footer.addWidget(self._status_badge)
        layout.addLayout(footer)

    def set_metric(
        self,
        value_text: str = "—",
        qualifier_text: str | None = None,
        status: str | None = None,
    ) -> None:
        """Presentation-only update (spec section 32's ``set_metric``
        concept).  ``status`` is one of PARTIAL / UNAVAILABLE / FINAL /
        RUNNING or ``None`` to hide the badge (spec section 11) -- this
        method never derives ``status`` or ``value_text`` itself."""

        self._value_label.setText(value_text)
        if qualifier_text is not None:
            self._qualifier_label.setText(qualifier_text)
        if status:
            self._status_badge.setText(status)
            self._status_badge.setProperty("statusTone", status.lower())
            self._status_badge.setVisible(True)
        else:
            self._status_badge.setVisible(False)
        self._status_badge.style().unpolish(self._status_badge)
        self._status_badge.style().polish(self._status_badge)


class _MetricsGrid(QFrame):
    """Responsive 4x2 / 2x4 / 1x8 metric grid (spec sections 5, 39).

    Re-parents the same eight card widgets into a QGridLayout with a
    different column count as the panel's own width crosses a breakpoint
    -- never rebuilds the cards, never introduces a horizontal scrollbar.
    """

    _WIDE_COLUMNS = 4
    _MEDIUM_COLUMNS = 2
    _NARROW_COLUMNS = 1
    _WIDE_MIN_WIDTH = 900
    _MEDIUM_MIN_WIDTH = 460

    def __init__(self, cards: list[QWidget], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3MetricsGrid")
        self._cards = cards
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(16)
        self._current_columns = -1
        self._relayout(self._WIDE_COLUMNS)

    def _relayout(self, columns: int) -> None:
        if columns == self._current_columns:
            return
        self._current_columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, card in enumerate(self._cards):
            row, col = divmod(index, columns)
            self._grid.addWidget(card, row, col)

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        width = event.size().width()
        if width >= self._WIDE_MIN_WIDTH:
            columns = self._WIDE_COLUMNS
        elif width >= self._MEDIUM_MIN_WIDTH:
            columns = self._MEDIUM_COLUMNS
        else:
            columns = self._NARROW_COLUMNS
        self._relayout(columns)


class _EvidenceFeedItem(QFrame):
    """One chronological evidence row (spec sections 11, 20).

    Anatomy: timestamp, stage dot + connecting rail, title, short factual
    detail, source/organ chip, evidence-type badge.  Renders only -- it
    never infers what an event means (spec section 24); every field
    arrives already decided by whatever later hands this class real data.
    ``is_last`` hides the trailing rail segment below the dot so the rail
    does not dangle past the final event.
    """

    def __init__(
        self,
        *,
        timestamp: str,
        title: str,
        detail: str,
        source: str,
        evidence: str,
        stage_kind: str = "neutral",
        is_last: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3EvidenceItem")
        self.setAccessibleName(f"Evidence event at {timestamp}: {title}")
        _allow_shrink(self)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(14)

        time_label = QLabel(timestamp)
        time_label.setObjectName("chapter3EvidenceTime")
        time_label.setFont(make_font(10, 700, mono=True))
        time_label.setFixedWidth(56)
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        row.addWidget(time_label)

        rail_column = QVBoxLayout()
        rail_column.setContentsMargins(0, 4, 0, 0)
        rail_column.setSpacing(0)
        dot = QFrame()
        dot.setObjectName("chapter3EvidenceDot")
        dot.setProperty("stageKind", stage_kind)
        dot.setFixedSize(10, 10)
        rail_column.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
        if not is_last:
            line = QFrame()
            line.setObjectName("chapter3EvidenceRail")
            line.setFixedWidth(2)
            line.setMinimumHeight(24)
            rail_column.addWidget(line, 1, Qt.AlignmentFlag.AlignHCenter)
        rail_widget = QWidget()
        rail_widget.setLayout(rail_column)
        rail_widget.setFixedWidth(10)
        row.addWidget(rail_widget)

        content = QVBoxLayout()
        content.setSpacing(6)
        title_label = QLabel(title.upper())
        title_label.setObjectName("chapter3EvidenceTitle")
        title_label.setFont(make_font(11, 700, spacing=0.3))
        title_label.setWordWrap(True)
        _allow_shrink(title_label)
        content.addWidget(title_label)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("chapter3EvidenceDetail")
            detail_label.setFont(make_font(9.5, 400))
            detail_label.setWordWrap(True)
            _allow_shrink(detail_label)
            content.addWidget(detail_label)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        if source:
            source_chip = QLabel(source.upper())
            source_chip.setObjectName("chapter3EvidenceSourceChip")
            source_chip.setFont(make_font(8, 700, spacing=0.5))
            chip_row.addWidget(source_chip)
        if evidence:
            evidence_badge = QLabel(evidence.upper())
            evidence_badge.setObjectName("chapter3EvidenceTypeBadge")
            evidence_badge.setFont(make_font(8, 700, spacing=0.5))
            chip_row.addWidget(evidence_badge)
        chip_row.addStretch(1)
        content.addLayout(chip_row)
        content.addSpacing(0 if is_last else 16)

        row.addLayout(content, 1)


class _EvidenceEmptyState(QFrame):
    """The honest 'nothing yet' body (spec sections 25-26, 96): a short
    dim rail plus factual copy -- never a skeleton shimmer that could be
    misread as active collection (spec section 27)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3EvidenceEmptyState")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 12, 8, 12)
        row.setSpacing(16)

        rail_column = QVBoxLayout()
        rail_column.setSpacing(0)
        for index in range(4):
            dot = QFrame()
            dot.setObjectName("chapter3EvidenceDot")
            dot.setFixedSize(8, 8)
            rail_column.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
            if index < 3:
                line = QFrame()
                line.setObjectName("chapter3EvidenceRail")
                line.setFixedWidth(2)
                line.setFixedHeight(16)
                rail_column.addWidget(line, 0, Qt.AlignmentFlag.AlignHCenter)
        rail_widget = QWidget()
        rail_widget.setLayout(rail_column)
        rail_widget.setFixedWidth(12)
        row.addWidget(rail_widget, 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(8)
        body = QLabel(
            "Chronological behavioral events will appear here when a Science "
            "Lab experiment is connected to certified MYELIN evidence."
        )
        body.setObjectName("chapter3EvidenceEmptyBody")
        body.setFont(make_font(10.5, 400))
        body.setWordWrap(True)
        _allow_shrink(body)
        text_column.addWidget(body)

        text_column.addWidget(_small_caption("No live telemetry is simulated in this dummy page."))
        text_column.addStretch(1)

        row.addLayout(text_column, 1)


class _EvidenceFeedPanel(QFrame):
    """Chapter 3's Live Evidence Feed (spec sections 3-4, 20-21).

    Production default is the honest empty state (spec section 25); a
    later phase calls ``set_events`` with already-approved presentation
    events.  This class never sorts, deduplicates, or infers meaning
    (spec sections 23-24) -- it renders exactly the list it is given, in
    the order it is given.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3EvidencePanel")
        self.setAccessibleName("Live evidence feed")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        icon = _MetricIcon("rail")
        icon.setObjectName("chapter3EvidenceIcon")
        header_row.addWidget(icon)
        title = QLabel("LIVE EVIDENCE FEED")
        title.setObjectName("chapter3EvidenceHeader")
        title.setProperty("role", "cyan")
        title.setFont(make_font(13, 800, spacing=1.0))
        header_row.addWidget(title)
        header_row.addStretch(1)
        self._status_chip = QLabel("AWAITING EVIDENCE")
        self._status_chip.setObjectName("chapter3EvidenceStatus")
        self._status_chip.setFont(make_font(9, 700, spacing=0.6))
        self._status_chip.setToolTip(
            "Events are presented in time order and preserve their MYELIN source provenance."
        )
        header_row.addWidget(self._status_chip)
        layout.addLayout(header_row)

        layout.addWidget(
            _small_caption("Chronological behavioral evidence from the selected Science Lab experiment.")
        )

        self._demo_badge = QLabel("DEMO DATA · NOT REAL TELEMETRY")
        self._demo_badge.setObjectName("chapter3EvidenceDemoBadge")
        self._demo_badge.setFont(make_font(9, 800, spacing=0.6))
        self._demo_badge.setVisible(False)
        layout.addWidget(self._demo_badge)

        self._body_layout = QVBoxLayout()
        self._body_layout.setSpacing(8)
        layout.addLayout(self._body_layout)
        self._body_layout.addWidget(_EvidenceEmptyState())
        self._items: list[_EvidenceFeedItem] = []

        layout.addWidget(
            _small_caption(
                "Feed items represent behavioral/system evidence. Scientific interpretation "
                "belongs to later analysis."
            )
        )

    def set_events(
        self, events: list[dict], *, demo: bool = False, final: bool = False
    ) -> None:
        """Replace the visible event list.  ``demo`` marks the DEMO DATA /
        NOT REAL TELEMETRY banner (spec sections 7, 28); the production
        page must never call this with ``demo=True``.  Each event dict
        carries presentation fields only (timestamp/title/detail/source/
        evidence/stage) -- this method does not compute, sort, or infer
        anything about them (spec sections 22-24)."""

        while self._body_layout.count():
            taken = self._body_layout.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.setParent(None)
        self._items = []
        self._demo_badge.setVisible(demo)

        if not events:
            self._body_layout.addWidget(_EvidenceEmptyState())
            self._status_chip.setText("FINAL CAPTURE" if final else "AWAITING EVIDENCE")
            return

        self._status_chip.setText(
            "DEMO DATA" if demo else "FINAL CAPTURE" if final else "AWAITING EVIDENCE"
        )
        for index, event in enumerate(events):
            item = _EvidenceFeedItem(
                timestamp=event.get("timestamp", ""),
                title=event.get("title", ""),
                detail=event.get("detail", ""),
                source=event.get("source", ""),
                evidence=event.get("evidence", ""),
                stage_kind=event.get("stage", "neutral"),
                is_last=(index == len(events) - 1),
            )
            self._items.append(item)
            self._body_layout.addWidget(item)


class _DerivedFindingCard(QFrame):
    """One derived-finding card (spec sections 16-20, 128).

    Renders only: index, optional title, statement, and a DERIVED RESULT
    badge.  This class never computes a finding -- no comparison, no
    threshold, no inference (spec section 19).  ``status`` reserves the
    future PROVISIONAL/FINAL badge area (spec section 60) and is left
    unset in every current caller.
    """

    def __init__(
        self,
        *,
        index: str,
        title: str,
        statement: str,
        status: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3FindingCard")
        accessible = f"Derived finding {index}: {title}" if title else f"Derived finding {index}"
        self.setAccessibleName(accessible)
        _allow_shrink(self)

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(14)

        index_label = QLabel(index)
        index_label.setObjectName("chapter3FindingIndex")
        index_label.setFont(make_font(11, 800, mono=True))
        index_label.setFixedWidth(24)
        row.addWidget(index_label, 0, Qt.AlignmentFlag.AlignTop)

        content = QVBoxLayout()
        content.setSpacing(8)
        if title:
            title_label = QLabel(title.upper())
            title_label.setObjectName("chapter3FindingTitle")
            title_label.setFont(make_font(9.5, 700, spacing=0.5))
            content.addWidget(title_label)

        statement_label = QLabel(statement)
        statement_label.setObjectName("chapter3FindingText")
        statement_label.setFont(make_font(10.5, 400))
        statement_label.setWordWrap(True)
        _allow_shrink(statement_label)
        content.addWidget(statement_label)

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        badge = QLabel("DERIVED RESULT")
        badge.setObjectName("chapter3FindingBadge")
        badge.setFont(make_font(8, 700, spacing=0.5))
        badge_row.addWidget(badge)
        if status:
            status_badge = QLabel(status)
            status_badge.setObjectName("chapter3FindingBadge")
            status_badge.setFont(make_font(8, 700, spacing=0.5))
            badge_row.addWidget(status_badge)
        badge_row.addStretch(1)
        content.addLayout(badge_row)

        row.addLayout(content, 1)


class _FindingsEmptyState(QFrame):
    """Honest 'nothing derived yet' body (spec sections 14, 85, 160)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3FindingsEmptyState")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 12, 8, 12)
        row.setSpacing(16)

        icon = _MetricIcon("document")
        icon.setObjectName("chapter3FindingsIcon")
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setSpacing(8)
        body = QLabel(
            "Validated behavioral comparisons will appear here when a Science Lab "
            "experiment is connected to certified evidence."
        )
        body.setObjectName("chapter3FindingsEmptyBody")
        body.setFont(make_font(10.5, 400))
        body.setWordWrap(True)
        _allow_shrink(body)
        text_column.addWidget(body)
        text_column.addWidget(_small_caption("No derived result is simulated in this dummy page."))
        text_column.addStretch(1)

        row.addLayout(text_column, 1)


class _DerivedFindingsPanel(QFrame):
    """Chapter 3's Derived Findings panel (spec sections 10-26).

    Production default is the honest empty state; a later phase calls
    ``set_findings`` with already-approved presentation records.  This
    class never writes a sentence from a metric value (spec section 19).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3FindingsPanel")
        self.setAccessibleName("Derived findings")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        icon = _MetricIcon("document")
        icon.setObjectName("chapter3FindingsIcon")
        header_row.addWidget(icon)
        title = QLabel("DERIVED FINDINGS")
        title.setObjectName("chapter3FindingsHeader")
        title.setProperty("role", "cyan")
        title.setFont(make_font(13, 800, spacing=1.0))
        header_row.addWidget(title)
        header_row.addStretch(1)
        self._status_chip = QLabel("AWAITING ANALYSIS")
        self._status_chip.setObjectName("chapter3FindingsStatus")
        self._status_chip.setFont(make_font(9, 700, spacing=0.6))
        self._status_chip.setToolTip(
            "Derived findings summarize relationships calculated from validated "
            "behavioral evidence. They do not explain biological or psychological cause."
        )
        header_row.addWidget(self._status_chip)
        layout.addLayout(header_row)

        layout.addWidget(
            _small_caption("Behavioral relationships calculated from validated experiment evidence.")
        )

        self._demo_badge = QLabel("DEMO DATA · NOT REAL ANALYSIS")
        self._demo_badge.setObjectName("chapter3FindingsDemoBadge")
        self._demo_badge.setFont(make_font(9, 800, spacing=0.6))
        self._demo_badge.setVisible(False)
        layout.addWidget(self._demo_badge)

        self._body_layout = QVBoxLayout()
        self._body_layout.setSpacing(12)
        layout.addLayout(self._body_layout)
        self._body_layout.addWidget(_FindingsEmptyState())
        self._cards: list[_DerivedFindingCard] = []

        self._layout = layout

    def set_findings(
        self, findings: list[dict], *, demo: bool = False, final: bool = False
    ) -> None:
        """Replace the visible finding list.  ``demo`` marks the DEMO DATA
        / NOT REAL ANALYSIS banner (spec section 15); production must
        never call this with ``demo=True``.  Each dict carries
        presentation fields only (index/title/statement/status) -- this
        method computes nothing (spec section 19)."""

        while self._body_layout.count():
            taken = self._body_layout.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.setParent(None)
        self._cards = []
        self._demo_badge.setVisible(demo)

        if not findings:
            self._body_layout.addWidget(_FindingsEmptyState())
            self._status_chip.setText("FINAL ANALYSIS" if final else "AWAITING ANALYSIS")
            return

        self._status_chip.setText(
            "DEMO DATA" if demo else "FINAL ANALYSIS" if final else "AWAITING ANALYSIS"
        )
        for finding in findings:
            card = _DerivedFindingCard(
                index=finding.get("index", ""),
                title=finding.get("title", ""),
                statement=finding.get("statement", ""),
                status=finding.get("status"),
            )
            self._cards.append(card)
            self._body_layout.addWidget(card)


class _SourceCoverageRow(QFrame):
    """One source-coverage row (spec sections 29-31, 36, 129).

    Renders only the status it is given.  It never decides whether a
    source is reachable -- that is Science Lab's evidence authority
    (spec section 43).  ``status`` is one of ``_COVERAGE_STATUS_KINDS``.
    """

    _STATUS_TEXT: Final = {
        "available": "AVAILABLE",
        "no_evidence": "NO EVIDENCE",
        "unavailable": "UNAVAILABLE",
        "pending": "—",
    }

    def __init__(
        self,
        *,
        source: str,
        status: str = "pending",
        reason: str = "Awaiting coverage snapshot",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3CoverageRow")
        status_text = self._STATUS_TEXT.get(status, "—")
        self.setAccessibleName(f"{source} source coverage {status_text.lower()}")
        _allow_shrink(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        name = QLabel(source)
        name.setObjectName("chapter3CoverageSource")
        name.setFont(make_font(10.5, 700, spacing=0.3))
        top_row.addWidget(name)
        top_row.addStretch(1)
        badge = QLabel(status_text)
        badge.setObjectName("chapter3CoverageBadge")
        badge.setProperty("statusKind", status)
        badge.setFont(make_font(8.5, 700, spacing=0.5))
        top_row.addWidget(badge)
        outer.addLayout(top_row)

        reason_label = QLabel(reason)
        reason_label.setObjectName("chapter3CoverageReason")
        reason_label.setFont(make_font(9, 400))
        reason_label.setWordWrap(True)
        _allow_shrink(reason_label)
        outer.addWidget(reason_label)


class _SourceCoveragePanel(QFrame):
    """Chapter 3's Source Coverage panel (spec sections 27-43).

    Production default lists the frozen roster with every row ``pending``
    (spec section 33) -- an honest "not sampled yet" state, never a
    fabricated AVAILABLE/UNAVAILABLE guess.  ``set_source_coverage``
    receives already-approved rows later; this class renders only.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3CoveragePanel")
        self.setAccessibleName("Source coverage")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        icon = _MetricIcon("coverage")
        icon.setObjectName("chapter3CoverageIcon")
        header_row.addWidget(icon)
        title = QLabel("SOURCE COVERAGE")
        title.setObjectName("chapter3CoverageHeader")
        title.setProperty("role", "cyan")
        title.setFont(make_font(13, 800, spacing=1.0))
        header_row.addWidget(title)
        header_row.addStretch(1)
        self._status_chip = QLabel("AWAITING COVERAGE SNAPSHOT")
        self._status_chip.setObjectName("chapter3CoverageStatus")
        self._status_chip.setFont(make_font(8.5, 700, spacing=0.5))
        self._status_chip.setToolTip(
            "Coverage distinguishes readable evidence, readable sources with no matching "
            "evidence, and sources that are currently unavailable."
        )
        header_row.addWidget(self._status_chip)
        layout.addLayout(header_row)

        layout.addWidget(
            _small_caption(
                "Shows whether each approved MYELIN evidence source can contribute to the "
                "selected experiment."
            )
        )

        self._demo_badge = QLabel("DEMO COVERAGE · NOT LIVE SNAPSHOT")
        self._demo_badge.setObjectName("chapter3CoverageDemoBadge")
        self._demo_badge.setFont(make_font(9, 800, spacing=0.6))
        self._demo_badge.setVisible(False)
        layout.addWidget(self._demo_badge)

        self._rows_layout = QVBoxLayout()
        self._rows_layout.setSpacing(10)
        layout.addLayout(self._rows_layout)
        self._rows: list[_SourceCoverageRow] = []
        self._render_rows({})

        layout.addWidget(self._build_legend())

    def _build_legend(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter3CoverageLegend")
        _allow_shrink(frame)
        legend_layout = QVBoxLayout(frame)
        legend_layout.setContentsMargins(0, 8, 0, 0)
        legend_layout.setSpacing(6)
        for name, description in _COVERAGE_LEGEND:
            row = QHBoxLayout()
            row.setSpacing(10)
            name_label = QLabel(name)
            name_label.setObjectName("chapter3CoverageLegendTitle")
            name_label.setFont(make_font(8.5, 700, spacing=0.4))
            name_label.setFixedWidth(90)
            row.addWidget(name_label)
            body_label = QLabel(description)
            body_label.setObjectName("chapter3CoverageLegendBody")
            body_label.setFont(make_font(8.5, 400))
            body_label.setWordWrap(True)
            _allow_shrink(body_label)
            row.addWidget(body_label, 1)
            legend_layout.addLayout(row)
        return frame

    def _render_rows(self, statuses_by_source: dict) -> None:
        while self._rows_layout.count():
            taken = self._rows_layout.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.setParent(None)
        self._rows = []
        for source in _SOURCE_COVERAGE_ROSTER:
            data = statuses_by_source.get(source)
            if data is None:
                row = _SourceCoverageRow(source=source)
            else:
                row = _SourceCoverageRow(
                    source=source,
                    status=data.get("status", "pending"),
                    reason=data.get("reason", "Awaiting coverage snapshot"),
                )
            self._rows.append(row)
            self._rows_layout.addWidget(row)

    def set_source_coverage(
        self, rows: list[dict], *, demo: bool = False, final: bool = False
    ) -> None:
        """Replace the visible coverage rows.  ``demo`` marks the DEMO
        COVERAGE / NOT LIVE SNAPSHOT banner (spec sections 124-125);
        production must never call this with ``demo=True``.  Each row
        dict carries ``source``/``status``/``reason`` -- this method does
        not decide any source's status (spec section 43)."""

        self._demo_badge.setVisible(demo)
        statuses_by_source = {row["source"]: row for row in rows}
        self._render_rows(statuses_by_source)
        self._status_chip.setText(
            "DEMO COVERAGE"
            if demo
            else "FINAL SNAPSHOT"
            if final
            else "AWAITING COVERAGE SNAPSHOT"
        )


class _LimitationItem(QFrame):
    """One limitation block (spec sections 44-53, 130).

    ``kind`` is ``"boundary"`` (the permanent, static measurement
    boundary) or ``"evidence"`` (a dynamic, per-experiment gap).  Renders
    only -- text is supplied by the caller, never generated here.
    """

    def __init__(self, *, kind: str, title: str, body: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3LimitationItem")
        self.setProperty("limitationKind", kind)
        self.setAccessibleName(f"{title}: {body}")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)

        title_label = QLabel(title.upper())
        title_label.setObjectName("chapter3LimitationTitle")
        title_label.setFont(make_font(9.5, 700, spacing=0.5))
        layout.addWidget(title_label)

        body_label = QLabel(body)
        body_label.setObjectName("chapter3LimitationBody")
        body_label.setFont(make_font(9.5, 400))
        body_label.setWordWrap(True)
        _allow_shrink(body_label)
        layout.addWidget(body_label)


class _LimitationsPanel(QFrame):
    """Chapter 3's Limitations panel (spec sections 44-63, 91).

    Always shows the static MEASUREMENT BOUNDARY (spec section 47) --
    limitations must remain visible without expanding (spec section 159)
    and must never be hidden once findings look "good" (spec section 56).
    ``set_experiment_limitations`` replaces only the dynamic
    EXPERIMENT-SPECIFIC block below it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3LimitationsPanel")
        self.setAccessibleName("Limitations")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        icon = _MetricIcon("boundary")
        icon.setObjectName("chapter3LimitationsIcon")
        header_row.addWidget(icon)
        title = QLabel("LIMITATIONS")
        title.setObjectName("chapter3LimitationsHeader")
        title.setProperty("role", "cyan")
        title.setFont(make_font(13, 800, spacing=1.0))
        title.setToolTip(
            "Limitations describe evidence gaps and variables MYELIN did not directly measure."
        )
        header_row.addWidget(title)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        layout.addWidget(
            _small_caption("Evidence gaps and measurement boundaries that constrain interpretation.")
        )

        layout.addWidget(
            _LimitationItem(
                kind="boundary",
                title="Measurement boundary",
                body=_MEASUREMENT_BOUNDARY_TEXT,
            )
        )

        self._experiment_layout = QVBoxLayout()
        self._experiment_layout.setSpacing(10)
        layout.addLayout(self._experiment_layout)
        self._experiment_items: list[_LimitationItem] = []
        self._set_default_experiment_limitation()

    def _set_default_experiment_limitation(self) -> None:
        self._experiment_layout.addWidget(
            _LimitationItem(
                kind="evidence",
                title="Experiment-specific limitations",
                body="Awaiting evidence coverage.",
            )
        )

    def set_experiment_limitations(self, items: list[dict]) -> None:
        """Replace the dynamic EXPERIMENT-SPECIFIC limitations only; the
        static measurement boundary above is never removed (spec section
        56). Each dict carries ``title``/``body`` -- this method invents
        no limitation text of its own."""

        while self._experiment_layout.count():
            taken = self._experiment_layout.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.setParent(None)
        self._experiment_items = []

        if not items:
            self._set_default_experiment_limitation()
            return

        for item in items:
            widget = _LimitationItem(
                kind="evidence",
                title=item.get("title", "Experiment-specific limitations"),
                body=item.get("body", ""),
            )
            self._experiment_items.append(widget)
            self._experiment_layout.addWidget(widget)


class _TwoColumnRow(QFrame):
    """Responsive Source-Coverage / Limitations row (spec sections 8,
    80-83): side-by-side above the wide-layout threshold, stacked below
    it -- same re-parent-don't-rebuild technique as ``_MetricsGrid``.
    """

    _WIDE_MIN_WIDTH = 760

    def __init__(self, left: QWidget, right: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3TwoColumnRow")
        self._left = left
        self._right = right
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(16)
        self._wide: bool | None = None
        self._relayout(True)

    def _relayout(self, wide: bool) -> None:
        if wide == self._wide:
            return
        self._wide = wide
        while self._grid.count():
            self._grid.takeAt(0)
        if wide:
            self._grid.addWidget(self._left, 0, 0, Qt.AlignmentFlag.AlignTop)
            self._grid.addWidget(self._right, 0, 1, Qt.AlignmentFlag.AlignTop)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 1)
            self._grid.setRowStretch(1, 0)
        else:
            self._grid.addWidget(self._left, 0, 0)
            self._grid.addWidget(self._right, 1, 0)
            self._grid.setColumnStretch(0, 1)
            self._grid.setColumnStretch(1, 0)

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        self._relayout(event.size().width() >= self._WIDE_MIN_WIDTH)


class _ResponsiveGrid(QFrame):
    """Generic reflow grid: ``wide_columns`` above ``wide_min_width``,
    ``narrow_columns`` below it.  Re-parents the same widgets rather than
    rebuilding them -- the same technique as ``_MetricsGrid``/
    ``_TwoColumnRow``, generalised so Phase 5 does not duplicate it a
    third time for the experiment fields and a fourth time for the
    experiment controls.
    """

    def __init__(
        self,
        items: list[QWidget],
        *,
        wide_columns: int,
        narrow_columns: int,
        wide_min_width: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3ResponsiveGrid")
        self._items = items
        self._wide_columns = wide_columns
        self._narrow_columns = narrow_columns
        self._wide_min_width = wide_min_width
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(10)
        self._current_columns = -1
        self._relayout(wide_columns)

    def _relayout(self, columns: int) -> None:
        if columns == self._current_columns:
            return
        self._current_columns = columns
        while self._grid.count():
            self._grid.takeAt(0)
        for index, item in enumerate(self._items):
            row, col = divmod(index, columns)
            self._grid.addWidget(item, row, col)

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt override
        super().resizeEvent(event)
        width = event.size().width()
        columns = self._wide_columns if width >= self._wide_min_width else self._narrow_columns
        self._relayout(columns)


#: Whole-MYELIN Analysis roster (Chapter 3 -> Chapter 5 transfer spec,
#: 2026-09-12 section 4).  Only sources Science Lab can actually certify
#: appear here -- adding a row because there is room in the layout is
#: exactly the fabrication this roster exists to prevent.
_WHOLE_MYELIN_ROSTER: Final = (
    ("SINE", "Completed episodes"),
    ("MINE", "Completed episodes"),
    ("COSINE", "Completed episodes"),
    ("MIRL", "Verified recoveries"),
    ("COSECANT", "Completed returns"),
    ("STUDY", "Completed study blocks"),
    ("NORMAL BREAK", "Completed break events"),
)


class _WholeMyelinRow(QFrame):
    """One organ's line in the Whole-MYELIN Analysis roster.  Renders only
    the value it is given; the honest production default is ``"—"``."""

    def __init__(self, organ: str, measure: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3WholeMyelinRow")
        _allow_shrink(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(10)

        organ_label = QLabel(organ)
        organ_label.setObjectName("chapter3WholeMyelinOrgan")
        organ_label.setFont(make_font(10.5, 700, spacing=0.3))
        layout.addWidget(organ_label)

        measure_label = QLabel(measure)
        measure_label.setObjectName("chapter3WholeMyelinMeasure")
        measure_label.setFont(make_font(9.5, 400))
        measure_label.setWordWrap(True)
        _allow_shrink(measure_label)
        layout.addWidget(measure_label, 1)

        self._value_label = QLabel("—")
        self._value_label.setObjectName("chapter3WholeMyelinValue")
        self._value_label.setFont(make_font(11, 800))
        layout.addWidget(self._value_label)


class _WholeMyelinAnalysisPanel(QFrame):
    """Chapter 3's Whole-MYELIN Analysis summary (Chapter 3 -> Chapter 5
    transfer spec section 4): one compact whole-session summary prepared
    for Chapter 5, not a second dashboard.

    Production default: every organ row reads ``"—"`` and the analysis
    status reads AWAITING COMPLETED MYELIN RUN -- this widget holds no
    session truth of its own, computes nothing, and is never fed a real
    count in Phase 1.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3WholeMyelinPanel")
        self.setAccessibleName("Whole-MYELIN analysis")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        title = QLabel("WHOLE-MYELIN ANALYSIS")
        title.setObjectName("chapter3WholeMyelinHeader")
        title.setProperty("role", "cyan")
        title.setFont(make_font(13, 800, spacing=1.0))
        header_row.addWidget(title)
        header_row.addStretch(1)
        self._status_chip = QLabel("AWAITING COMPLETED MYELIN RUN")
        self._status_chip.setObjectName("chapter3WholeMyelinStatus")
        self._status_chip.setFont(make_font(8.5, 700, spacing=0.5))
        header_row.addWidget(self._status_chip)
        layout.addLayout(header_row)

        layout.addWidget(
            _small_caption("Final session-level summary prepared for Chapter 5.")
        )

        rows_layout = QVBoxLayout()
        rows_layout.setSpacing(10)
        self._rows: dict[str, _WholeMyelinRow] = {}
        for organ, measure in _WHOLE_MYELIN_ROSTER:
            row_widget = _WholeMyelinRow(organ, measure)
            self._rows[organ.replace(" ", "_")] = row_widget
            rows_layout.addWidget(row_widget)
        layout.addLayout(rows_layout)

        footer = QFrame()
        footer.setObjectName("chapter3WholeMyelinFooter")
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(14, 12, 14, 12)
        footer_layout.setSpacing(8)
        self._footer_values: dict[str, QLabel] = {}
        for label_text, value_text in (
            ("Session status", "—"),
            ("Analysis status", "AWAITING COMPLETED MYELIN RUN"),
        ):
            row = QHBoxLayout()
            row.setSpacing(10)
            key_label = QLabel(label_text)
            key_label.setObjectName("chapter3WholeMyelinFooterKey")
            key_label.setFont(make_font(9.5, 400))
            row.addWidget(key_label)
            row.addStretch(1)
            value_label = QLabel(value_text)
            value_label.setObjectName("chapter3WholeMyelinFooterValue")
            value_label.setFont(make_font(9.5, 700))
            row.addWidget(value_label)
            self._footer_values[label_text] = value_label
            footer_layout.addLayout(row)
        layout.addWidget(footer)

        layout.addWidget(
            _small_caption("Whole-session analysis will appear after STOP.")
        )

    def render_final(self, rows: tuple[object, ...], *, analysis_status: str) -> None:
        """Render backend-certified full-session rows without recalculation."""

        supplied = {str(getattr(row, "source", "")): row for row in rows}
        for source, widget in self._rows.items():
            row = supplied.get(source)
            if row is None:
                widget._value_label.setText("Unavailable")  # noqa: SLF001
                continue
            status = str(getattr(row, "status", "UNAVAILABLE"))
            count = getattr(row, "count", None)
            value = str(count) if status == "AVAILABLE" else (
                "No evidence" if status == "NO_EVIDENCE" else "Unavailable"
            )
            widget._value_label.setText(value)  # noqa: SLF001
            widget.setToolTip(str(getattr(row, "reason", "")))
        final_status = str(analysis_status).replace("_", " ")
        self._status_chip.setText(
            "RESULT PACKAGE CERTIFIED · READY FOR TRANSFER"
            if analysis_status == "CERTIFIED"
            else final_status
        )
        self._footer_values["Session status"].setText("STOPPED")
        self._footer_values["Analysis status"].setText(final_status)


class _TransferResultsCard(QFrame):
    """Chapter 3's TRANSFER RESULTS action (Chapter 3 -> Chapter 5 transfer
    spec section 5): a deliberate, user-visible research handoff, not an
    automatic hidden transfer.

    Production default: disabled, helper text reads "Available after
    STOP." -- this widget decides nothing about transfer eligibility
    itself and is not wired to any side effect in Phase 1 (presentation
    only; STOP wiring is Phase 2).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3TransferCard")
        self.setAccessibleName("Transfer results to Chapter 5")
        _allow_shrink(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)
        relationship = QLabel("CHAPTER 3 → CHAPTER 5")
        relationship.setObjectName("chapter3TransferRelationship")
        relationship.setProperty("role", "cyan")
        relationship.setFont(make_font(9.5, 700, spacing=0.8))
        text_column.addWidget(relationship)

        title = QLabel("TRANSFER RESULTS")
        title.setObjectName("chapter3TransferTitle")
        title.setFont(make_font(14, 800, spacing=0.4))
        text_column.addWidget(title)

        self._helper = QLabel("Available after STOP.")
        self._helper.setObjectName("chapter3TransferHelper")
        self._helper.setWordWrap(True)
        _allow_shrink(self._helper)
        self._helper.setFont(make_font(9.5, 400))
        text_column.addWidget(self._helper)

        layout.addLayout(text_column, 1)

        self._button = _ExperimentControlButton(
            "TRANSFER RESULTS",
            object_name="chapter3TransferButton",
            accessible_name="Transfer certified Chapter 3 results to Chapter 5",
        )
        self._button.setToolTip("Available after STOP.")
        layout.addWidget(self._button, 0, Qt.AlignmentFlag.AlignVCenter)

    def render_state(self, *, enabled: bool, helper_text: str) -> None:
        """Render host-decided transfer eligibility without owning it."""

        self._button.setEnabled(bool(enabled))
        self._helper.setText(helper_text)
        self._button.setToolTip(helper_text)

    def show_pending_analysis(self) -> None:
        self.render_state(
            enabled=False,
            helper_text="Final snapshot captured. Analysis package pending.",
        )

    def show_waiting_for_stop(self) -> None:
        self.render_state(enabled=False, helper_text="Available after STOP.")

    def show_finalization_error(self) -> None:
        self.render_state(
            enabled=False,
            helper_text="Finalization failed. Transfer unavailable.",
        )

    def show_analysis_ready(self) -> None:
        self.render_state(
            enabled=True,
            helper_text="Send certified analysis to Chapter 5.",
        )

    def show_analysis_unavailable(self, reason: str) -> None:
        self.render_state(enabled=False, helper_text=reason)


class _ExperimentField(QFrame):
    """One Science Experiment identity/status field (spec section 109).
    Renders only whatever value it is given; the honest production
    default is ``"—"``.
    """

    def __init__(self, *, label: str, accessible_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3ExperimentField")
        self.setAccessibleName(accessible_label)
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        label_widget = QLabel(label.upper())
        label_widget.setObjectName("chapter3ExperimentFieldLabel")
        label_widget.setFont(make_font(8.5, 700, spacing=0.5))
        layout.addWidget(label_widget)

        self._value_label = QLabel("—")
        self._value_label.setObjectName("chapter3ExperimentFieldValue")
        self._value_label.setFont(make_font(11, 700))
        self._value_label.setWordWrap(True)
        _allow_shrink(self._value_label)
        layout.addWidget(self._value_label)

    def set_value(self, text: str) -> None:
        self._value_label.setText(text)


class _ExperimentControlButton(QPushButton):
    """One Science Experiment control (spec sections 10, 109).

    It starts disabled and only displays host-decided capability.  The
    enclosing Chapter 3 view converts clicks into request signals; this
    button never talks to a backend directly.
    """

    def __init__(self, text: str, *, object_name: str, accessible_name: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName(object_name)
        self.setAccessibleName(accessible_name)
        self.setFont(make_font(10, 700, spacing=0.4))
        self.setEnabled(False)
        self.setToolTip("Available after Science Lab experiment backend is connected.")


class _ExperimentStrip(QFrame):
    """Chapter 3's Science Experiment strip (spec sections 7-26).

    Production default: identity fields read ``—``, status reads
    "NOT CONNECTED", and all four controls are visible but disabled --
    this widget holds no authoritative experiment state of its own (spec
    section 24).  ``apply_demo_state`` is an isolated-preview-only seam
    (spec section 25): it sets already-decided display values/
    capabilities directly and is never called from this class's own
    construction.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter3ExperimentStrip")
        self.setAccessibleName("Science experiment")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        title = QLabel("SCIENCE EXPERIMENT")
        title.setObjectName("chapter3ExperimentHeader")
        title.setProperty("role", "cyan")
        title.setFont(make_font(13, 800, spacing=1.0))
        layout.addWidget(title)

        subtitle = QLabel("Research observation window attached to the active MYELIN session.")
        subtitle.setObjectName("chapter3ExperimentSubtitle")
        subtitle.setFont(make_font(9.5, 400))
        subtitle.setWordWrap(True)
        _allow_shrink(subtitle)
        layout.addWidget(subtitle)

        self._id_field = _ExperimentField(label="Experiment ID", accessible_label="Experiment ID")
        self._session_field = _ExperimentField(
            label="Parent Session", accessible_label="Parent MYELIN session"
        )
        self._status_field = _ExperimentField(label="Status", accessible_label="Experiment status")
        self._status_field.set_value("NOT CONNECTED")
        layout.addWidget(
            _ResponsiveGrid(
                [self._id_field, self._session_field, self._status_field],
                wide_columns=3,
                narrow_columns=1,
                wide_min_width=560,
            )
        )

        self._start_button = _ExperimentControlButton(
            "START EXPERIMENT",
            object_name="chapter3ExperimentStart",
            accessible_name="Start Science Lab experiment",
        )
        self._end_button = _ExperimentControlButton(
            "END EXPERIMENT",
            object_name="chapter3ExperimentEnd",
            accessible_name="End Science Lab experiment",
        )
        self._refresh_button = _ExperimentControlButton(
            "REFRESH",
            object_name="chapter3ExperimentRefresh",
            accessible_name="Refresh Science Lab evidence",
        )
        layout.addWidget(
            _ResponsiveGrid(
                [self._start_button, self._end_button, self._refresh_button],
                wide_columns=3,
                narrow_columns=2,
                wide_min_width=420,
            )
        )

        self._dummy_badge = QLabel("DUMMY CONTROLS · BACKEND NOT CONNECTED")
        self._dummy_badge.setObjectName("chapter3ExperimentDummyBadge")
        self._dummy_badge.setFont(make_font(9, 700, spacing=0.6))
        layout.addWidget(self._dummy_badge)

        layout.addWidget(
            _small_caption("Ending the Science Lab experiment does not stop the parent MYELIN session.")
        )

    def apply_demo_state(
        self,
        *,
        experiment_id: str,
        parent_session: str,
        status_text: str,
        can_start: bool,
        can_end: bool,
        can_refresh: bool,
    ) -> None:
        """Isolated-preview-only seam (spec section 25).  Sets already-
        decided display values and capabilities directly -- this method
        does not compute eligibility itself, and production construction
        never calls it.  Always forces the DEMO STATE banner (spec
        section 18)."""

        self._id_field.set_value(experiment_id)
        self._session_field.set_value(parent_session)
        self._status_field.set_value(status_text)
        self._start_button.setEnabled(can_start)
        self._end_button.setEnabled(can_end)
        self._refresh_button.setEnabled(can_refresh)
        self._dummy_badge.setText("DEMO STATE · NOT REAL EXPERIMENT")
        self._dummy_badge.setProperty("demoActive", "true")
        self._dummy_badge.style().unpolish(self._dummy_badge)
        self._dummy_badge.style().polish(self._dummy_badge)

    def apply_live_state(
        self,
        *,
        experiment_id: str,
        parent_session: str,
        status_text: str,
        can_start: bool,
        can_end: bool,
        can_refresh: bool,
        badge_text: str,
    ) -> None:
        """Display factual state and capabilities decided by the host."""

        self._id_field.set_value(experiment_id)
        self._session_field.set_value(parent_session)
        self._status_field.set_value(status_text)
        self._start_button.setEnabled(can_start)
        self._end_button.setEnabled(can_end)
        self._refresh_button.setEnabled(can_refresh)
        self._dummy_badge.setText(badge_text)
        self._dummy_badge.setProperty("demoActive", "false")
        self._dummy_badge.style().unpolish(self._dummy_badge)
        self._dummy_badge.style().polish(self._dummy_badge)

    def reset_to_production_dummy(self) -> None:
        """Restores the honest default state (spec section 9)."""

        self._id_field.set_value("—")
        self._session_field.set_value("—")
        self._status_field.set_value("NOT CONNECTED")
        for button in (self._start_button, self._end_button, self._refresh_button):
            button.setEnabled(False)
        self._dummy_badge.setText("DUMMY CONTROLS · BACKEND NOT CONNECTED")
        self._dummy_badge.setProperty("demoActive", "false")
        self._dummy_badge.style().unpolish(self._dummy_badge)
        self._dummy_badge.style().polish(self._dummy_badge)


class Chapter3TimelineView(QWidget):
    """Chapter 3's Behavioural Timeline hero panel.

    Presentation-only: it renders host-decided experiment state and emits
    requests for its three explicit experiment controls.  It never reads a
    session, touches evidence, or starts/commands MYELIN directly.  Timeline
    demo controls remain local visual simulations.
    """

    start_experiment_requested = pyqtSignal()
    end_experiment_requested = pyqtSignal()
    refresh_experiment_requested = pyqtSignal()
    transfer_results_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._reduced_motion = False
        self._is_paused = False
        self._pending_steps: list[tuple[int, Callable[[], None]]] = []
        self._last_sequence: list[tuple[int, Callable[[], None]]] = []
        self._active_organ = "SINE"
        self._organ_buttons: dict[str, QPushButton] = {}
        self._live_identity: tuple[int, str] | None = None
        self._live_mode = ""
        self._live_states: dict[str, LiveOrganTimelineState] = {}
        self._live_visual_progress: dict[tuple[str, str], float] = {}
        self._live_timer_tick_count = 0

        self._step_timer = QTimer(self)
        self._step_timer.setSingleShot(True)
        self._step_timer.timeout.connect(self._advance_sequence)

        # The sole live presentation timer.  It reads only the immutable
        # state cached above and changes widget geometry; runtime facts enter
        # through render_live_organ_timeline, never through this tick.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(160)
        self._live_timer.timeout.connect(self._animate_live_frame)

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(self._build_hero())
        self._transfer_results_card = _TransferResultsCard()
        root.addWidget(self._transfer_results_card)
        self._transfer_results_card._button.clicked.connect(  # noqa: SLF001
            self.transfer_results_requested.emit
        )
        self._experiment_strip = _ExperimentStrip()
        root.addWidget(self._experiment_strip)
        self._experiment_strip._start_button.clicked.connect(  # noqa: SLF001
            self.start_experiment_requested.emit
        )
        self._experiment_strip._end_button.clicked.connect(  # noqa: SLF001
            self.end_experiment_requested.emit
        )
        self._experiment_strip._refresh_button.clicked.connect(  # noqa: SLF001
            self.refresh_experiment_requested.emit
        )
        root.addWidget(self._build_timeline_card())
        root.addWidget(self._build_key_metrics_panel())
        self._evidence_feed = _EvidenceFeedPanel()
        root.addWidget(self._evidence_feed)

        self._findings_panel = _DerivedFindingsPanel()
        root.addWidget(self._findings_panel)

        self._coverage_panel = _SourceCoveragePanel()
        self._limitations_panel = _LimitationsPanel()
        root.addWidget(_TwoColumnRow(self._coverage_panel, self._limitations_panel))
        self._whole_myelin_panel = _WholeMyelinAnalysisPanel()
        root.addWidget(self._whole_myelin_panel)

        root.addStretch(1)

        self._episode_bar.reset()
        self._sync_trigger_note()

    def render_experiment_state(
        self,
        *,
        experiment_id: str,
        parent_session: str,
        status_text: str,
        can_start: bool,
        can_end: bool,
        can_refresh: bool,
        badge_text: str,
    ) -> None:
        """Render backend-decided experiment truth without interpreting it."""

        self._experiment_strip.apply_live_state(
            experiment_id=experiment_id,
            parent_session=parent_session,
            status_text=status_text,
            can_start=can_start,
            can_end=can_end,
            can_refresh=can_refresh,
            badge_text=badge_text,
        )

    def render_live_organ_timeline(self, state: LiveOrganTimelineState) -> None:
        """Render one immutable live projection; query no runtime authority."""

        identity = (state.parent_session_id, state.experiment_id)
        if identity != self._live_identity:
            self._live_identity = identity
            self._live_states.clear()
            self._live_visual_progress.clear()
            self._active_organ = ""
        self._live_mode = state.mode
        self._step_timer.stop()
        self._pending_steps = []
        self._demo_controls.setVisible(False)
        if state.mode != MODE_LIVE:
            self._freeze_live_timeline(state.mode)
            return
        self._timeline_badge.setText("LIVE ORGAN STATE")
        if state.organ is None:
            self._live_timer.stop()
            self._episode_bar.reset()
            self._break_lane.hide_lane()
            self._break_connector.setVisible(False)
            self._active_organ = ""
            for button in self._organ_buttons.values():
                button.setChecked(False)
                button.setEnabled(False)
            self._trigger_note.setText(
                "Waiting for qualifying factual organ activity. No episode is assumed."
            )
            return

        organ = str(state.organ)
        self._live_states[organ] = state
        if not self._active_organ or self._active_organ not in self._live_states:
            self._active_organ = organ
        for key, button in self._organ_buttons.items():
            button.setChecked(key == self._active_organ)
            button.setEnabled(key in self._live_states)
        self._present_live_state()

    def render_idle_timeline(self) -> None:
        self._live_timer.stop()
        self._live_mode = "IDLE"
        self._live_identity = None
        self._live_states.clear()
        self._live_visual_progress.clear()
        self._active_organ = ""
        self._demo_controls.setVisible(False)
        self._timeline_badge.setText("LIVE TIMELINE IDLE")
        self._episode_bar.reset()
        self._break_lane.hide_lane()
        self._break_connector.setVisible(False)
        for button in self._organ_buttons.values():
            button.setChecked(False)
            button.setEnabled(False)
        self._trigger_note.setText("START EXPERIMENT TO VIEW LIVE ORGAN TIMELINE")

    def render_finalizing_timeline(self) -> None:
        self._freeze_live_timeline(MODE_FINALIZING)

    def render_experiment_ended_timeline(self) -> None:
        self._freeze_live_timeline(MODE_EXPERIMENT_ENDED)

    def render_interrupted_timeline(self) -> None:
        self._freeze_live_timeline(MODE_INTERRUPTED)

    def render_analysis_unavailable_timeline(self, reason: str) -> None:
        self._live_timer.stop()
        self._live_mode = MODE_INTERRUPTED
        self._demo_controls.setVisible(False)
        self._timeline_badge.setText("ANALYSIS UNAVAILABLE · NOT CERTIFIED")
        self._episode_bar.reset()
        self._break_lane.hide_lane()
        self._break_connector.setVisible(False)
        self._trigger_note.setText(reason or "No certified Chapter 3 package is available.")
        for button in self._organ_buttons.values():
            button.setEnabled(False)

    def _freeze_live_timeline(self, mode: str) -> None:
        self._live_timer.stop()
        self._live_mode = mode
        labels = {
            MODE_FINALIZING: (
                "FINALIZING EVIDENCE",
                "Provisional live geometry is frozen while canonical STOP finalizes evidence.",
            ),
            MODE_EXPERIMENT_ENDED: (
                "EXPERIMENT ENDED · AWAITING FINAL ANALYSIS",
                "The experiment window ended. Provisional state is frozen until MYELIN STOP.",
            ),
            MODE_INTERRUPTED: (
                "INTERRUPTED · FINAL CERTIFICATION UNAVAILABLE",
                "Live presentation stopped without a certified Chapter 3 package.",
            ),
        }
        badge, note = labels.get(mode, labels[MODE_INTERRUPTED])
        self._timeline_badge.setText(badge)
        self._demo_controls.setVisible(False)
        self._trigger_note.setText(note)
        for button in self._organ_buttons.values():
            button.setEnabled(False)

    def _present_live_state(self) -> None:
        state = self._live_states.get(self._active_organ)
        if state is None:
            return
        targets: dict[str, float] = {}
        needs_animation = False
        for row in state.stages:
            key = (self._active_organ, row.stage)
            if row.status == STATUS_COMPLETE:
                self._live_visual_progress[key] = 1.0
                targets[row.stage] = 1.0
            elif row.status in {STATUS_ACTIVE, STATUS_PAUSED}:
                if row.progress is None:
                    continue
                target = max(0.0, min(1.0, float(row.progress)))
                current = self._live_visual_progress.get(key)
                if current is None or target < current or row.status == STATUS_PAUSED:
                    current = target
                self._live_visual_progress[key] = current
                targets[row.stage] = current
                needs_animation = needs_animation or (
                    row.status == STATUS_ACTIVE and current < target
                )
        self._episode_bar.render_live_stages(state.stages, targets)
        if state.break_progress is not None:
            self._break_connector.setVisible(True)
            self._break_lane.render_live(state.break_progress)
        else:
            self._break_lane.hide_lane()
            self._break_connector.setVisible(False)
        current = next((row for row in state.stages if row.stage == state.stage), None)
        if current is None:
            note = f"{self._active_organ} · waiting for factual stage activity."
        else:
            timing = ""
            if current.elapsed_seconds is not None:
                timing = f" · {current.elapsed_seconds:.1f} s elapsed"
            note = f"{self._active_organ} · {current.stage.replace('_', ' ')} · {current.reason}{timing}"
        self._trigger_note.setText(note)
        if needs_animation and self._live_mode == MODE_LIVE:
            self._live_timer.start()
        else:
            self._live_timer.stop()

    def _animate_live_frame(self) -> None:
        """Ease cached targets toward their truthful targets; perform no
        authority reads.  Only runs while a stage with authoritative
        elapsed/total progress is still catching up to its target -- an
        indeterminate stage is rendered once as a stationary highlight and
        never re-animates itself."""

        self._live_timer_tick_count += 1
        if self._live_mode != MODE_LIVE:
            self._live_timer.stop()
            return
        state = self._live_states.get(self._active_organ)
        if state is None:
            self._live_timer.stop()
            return
        visual: dict[str, float] = {}
        needs_animation = False
        for row in state.stages:
            key = (self._active_organ, row.stage)
            if row.status == STATUS_COMPLETE:
                self._live_visual_progress[key] = 1.0
                visual[row.stage] = 1.0
            elif row.status in {STATUS_ACTIVE, STATUS_PAUSED} and row.progress is not None:
                target = max(0.0, min(1.0, float(row.progress)))
                current = self._live_visual_progress.get(key, target)
                if target < current:
                    current = target
                elif row.status == STATUS_ACTIVE and current < target:
                    current = min(target, current + max(0.004, (target - current) * 0.24))
                    needs_animation = current < target
                self._live_visual_progress[key] = current
                visual[row.stage] = current
        self._episode_bar.render_live_stages(state.stages, visual)
        if state.break_progress is not None:
            self._break_lane.render_live(state.break_progress)
        if not needs_animation:
            self._live_timer.stop()

    def render_transfer_pending_after_stop(self) -> None:
        self._transfer_results_card.show_pending_analysis()

    def render_transfer_waiting_for_stop(self) -> None:
        self._transfer_results_card.show_waiting_for_stop()

    def render_transfer_finalization_error(self) -> None:
        self._transfer_results_card.show_finalization_error()

    def render_transfer_state(self, *, enabled: bool, helper_text: str) -> None:
        """Render transfer eligibility decided by the application authority."""

        self._transfer_results_card.render_state(
            enabled=enabled,
            helper_text=helper_text,
        )

    def render_analysis_outcome(self, outcome: object) -> None:
        """Render one stored immutable backend outcome; perform no analysis."""

        status = str(getattr(outcome, "status", "ANALYSIS_UNAVAILABLE"))
        package = getattr(outcome, "package", None)
        coverage = tuple(getattr(outcome, "source_coverage", ()) or ())
        whole = tuple(getattr(outcome, "whole_myelin_summary", ()) or ())
        limitations = tuple(getattr(outcome, "limitations", ()) or ())

        if status == "CERTIFIED" and package is not None:
            self.render_experiment_state(
                experiment_id=str(package.experiment_id),
                parent_session=str(package.parent_session_id),
                status_text="ANALYSIS CERTIFIED",
                can_start=False,
                can_end=False,
                can_refresh=False,
                badge_text="RESULT PACKAGE CERTIFIED · READY FOR TRANSFER",
            )
            self._render_timeline(
                tuple(package.timeline), package.experiment_start_monotonic_ns
            )
            self._render_metrics(tuple(package.key_metrics))
            self._evidence_feed.set_events(
                [self._timeline_presentation(event, package.experiment_start_monotonic_ns)
                 for event in package.timeline],
                final=True,
            )
            self._findings_panel.set_findings(
                [
                    {
                        "index": f"{index:02d}",
                        "title": finding.scientific_label,
                        "statement": finding.text,
                        "status": "FINAL",
                    }
                    for index, finding in enumerate(package.derived_findings, start=1)
                ],
                final=True,
            )
        else:
            reason = str(getattr(outcome, "reason", "Analysis unavailable."))
            self.render_analysis_unavailable_timeline(reason)
            self._render_metrics(())
            self._evidence_feed.set_events([], final=True)
            self._findings_panel.set_findings(
                [{"index": "01", "title": "LIMITATION", "statement": reason, "status": "FINAL"}],
                final=True,
            )

        self._coverage_panel.set_source_coverage(
            [
                {
                    "source": row.source_system.replace("_", " "),
                    "status": row.status.lower(),
                    "reason": row.reason or (
                        f"{row.item_count} final evidence item(s)" if row.item_count is not None else ""
                    ),
                }
                for row in coverage
            ],
            final=True,
        )
        self._limitations_panel.set_experiment_limitations(
            [
                {"title": "Experiment-specific limitations", "body": text}
                for text in limitations
            ]
        )
        self._whole_myelin_panel.render_final(whole, analysis_status=status)

    @staticmethod
    def _relative_time(timestamp_ns: int, start_ns: int) -> str:
        return f"+{(timestamp_ns - start_ns) / 1_000_000_000:.3f} s"

    def _timeline_presentation(self, event: object, start_ns: int) -> dict:
        return {
            "timestamp": self._relative_time(event.occurred_monotonic_ns, start_ns),
            "title": event.label,
            "detail": f"{event.stage.replace('_', ' ').title()} · {event.durable_id}",
            "source": event.source.replace("_", " "),
            "evidence": "FACTUAL",
            "stage": "break" if event.lane == "BREAK" else "neutral",
        }

    def _render_timeline(self, events: tuple[object, ...], start_ns: int) -> None:
        self._step_timer.stop()
        self._live_timer.stop()
        self._live_mode = "FINAL_CERTIFIED"
        self._live_states.clear()
        self._live_visual_progress.clear()
        self._pending_steps = []
        self._demo_controls.setVisible(False)
        self._timeline_badge.setText("FINAL CERTIFIED EVIDENCE")
        for button in self._organ_buttons.values():
            button.setEnabled(False)
        main_stages = tuple(event.stage for event in events if event.lane == "MAIN")
        self._episode_bar.render_certified_stages(main_stages)
        breaks = tuple(event for event in events if event.lane == "BREAK")
        self._break_lane.render_final(len(breaks))
        self._break_connector.setVisible(bool(breaks))
        if events:
            self._trigger_note.setText(
                " · ".join(
                    f"{self._relative_time(event.occurred_monotonic_ns, start_ns)} "
                    f"{event.source}: {event.label}"
                    for event in events
                )
            )
        else:
            self._trigger_note.setText("No factual timeline events fall inside [start,end).")

    def _render_metrics(self, metrics: tuple[object, ...]) -> None:
        by_code = {str(getattr(metric, "code", "")): metric for metric in metrics}
        self._metrics_badge.setText("FINAL CERTIFIED METRICS")
        for code, card in self._metric_cards.items():
            metric = by_code.get(code)
            if metric is None:
                card.set_metric("Unavailable", "No certified metric package.", "UNAVAILABLE")
                continue
            status = str(metric.status)
            if status == "AVAILABLE":
                if metric.unit == "ns":
                    value_text = f"{metric.value / 1_000_000_000:.3f} s"
                else:
                    value_text = f"{metric.value} {metric.unit}".strip()
            elif status == "NO_EVIDENCE":
                value_text = "No evidence"
            else:
                value_text = "Unavailable"
            card.set_metric(value_text, str(metric.reason), status.replace("_", " "))

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build_hero(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("card")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(6)

        eyebrow = QLabel("CHAPTER 3")
        eyebrow.setProperty("role", "cyan")
        eyebrow.setFont(make_font(11, 700, spacing=1.6))
        layout.addWidget(eyebrow)

        title = QLabel("DATA ANALYSIS")
        title.setFont(make_font(24, 800, spacing=0.5))
        title.setWordWrap(True)
        _allow_shrink(title)
        layout.addWidget(title)

        subtitle = QLabel("Live behavioural telemetry and research evidence.")
        subtitle.setProperty("role", "muted")
        subtitle.setFont(make_font(13, 500))
        layout.addWidget(subtitle)
        layout.addSpacing(4)

        body = _small_caption(
            "Chapter 3 analyses behavioural evidence from the selected Science Lab "
            "experiment and prepares the results for transfer to Chapter 5.",
            role="text",
        )
        layout.addWidget(body)

        return frame

    def _build_timeline_card(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter3TimelineCard")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        title = QLabel("BEHAVIOURAL TIMELINE")
        title.setProperty("role", "cyan")
        title.setFont(make_font(13, 800, spacing=1.0))
        header_row.addWidget(title)
        header_row.addStretch(1)
        self._timeline_badge = QLabel("DEMONSTRATION · NOT LIVE TELEMETRY")
        self._timeline_badge.setObjectName("chapter3DemoBadge")
        self._timeline_badge.setFont(make_font(9.5, 700, spacing=0.6))
        header_row.addWidget(self._timeline_badge)
        layout.addLayout(header_row)

        layout.addWidget(
            _small_caption(
                "One common, continuous episode bar. Its structure is identical for "
                "SINE, MINE, COSINE and COSECANT -- only organ identity and factual "
                "events change (spec section 7)."
            )
        )

        layout.addWidget(self._build_organ_selector())

        self._episode_bar = _EpisodeBar()
        layout.addWidget(self._episode_bar)

        self._trigger_note = _small_caption("")
        layout.addWidget(self._trigger_note)

        self._break_connector = QFrame()
        self._break_connector.setObjectName("chapter3BreakConnector")
        self._break_connector.setFixedSize(3, 16)
        self._break_connector.setVisible(False)
        connector_row = QHBoxLayout()
        connector_row.setContentsMargins(0, 0, 0, 0)
        left_weight = _STAGE_WEIGHTS["OFF_TASK_DWELL"]
        right_weight = sum(_STAGE_WEIGHTS[key] for key in _STAGE_KEYS[1:])
        connector_row.addStretch(left_weight)
        connector_column = QVBoxLayout()
        connector_column.setContentsMargins(0, 0, 0, 0)
        connector_column.addWidget(self._break_connector, 0, Qt.AlignmentFlag.AlignHCenter)
        connector_row.addLayout(connector_column, 0)
        connector_row.addStretch(right_weight)
        layout.addLayout(connector_row)

        self._break_lane = _BreakLane()
        layout.addWidget(self._break_lane)

        self._demo_controls = self._build_demo_controls()
        layout.addWidget(self._demo_controls)

        return frame

    def _build_key_metrics_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter3MetricsPanel")
        _allow_shrink(frame)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header = QLabel("KEY METRICS")
        header.setObjectName("chapter3MetricsHeader")
        header.setProperty("role", "cyan")
        header.setFont(make_font(13, 800, spacing=1.0))
        header_row.addWidget(header)
        header_row.addStretch(1)
        self._metrics_badge = QLabel("DUMMY LAYOUT")
        self._metrics_badge.setObjectName("chapter3DemoBadge")
        self._metrics_badge.setFont(make_font(9, 700, spacing=0.6))
        self._metrics_badge.setToolTip(
            "These cards summarize measured or derived behavioural quantities from the "
            "selected Science Lab experiment. No neuroscience claim is made."
        )
        header_row.addWidget(self._metrics_badge)
        layout.addLayout(header_row)

        layout.addWidget(
            _small_caption("Behavioural measurements from the selected Science Lab experiment.")
        )

        self._metric_cards: dict[str, _Chapter3MetricCard] = {}
        cards: list[QWidget] = []
        for definition in _METRIC_DEFINITIONS:
            card = _Chapter3MetricCard(definition)
            self._metric_cards[definition["key"]] = card
            cards.append(card)
        layout.addWidget(_MetricsGrid(cards))

        layout.addWidget(
            _small_caption(
                "Metrics are behavioural measurements. Availability depends on certified "
                "Science Lab evidence."
            )
        )

        return frame

    def _build_organ_selector(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter3OrganSelector")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        label = QLabel("ACTIVE ORGAN")
        label.setProperty("role", "muted")
        label.setFont(make_font(9.5, 700, spacing=0.8))
        layout.addWidget(label)
        for organ in _ORGANS:
            button = QPushButton(organ)
            button.setObjectName("chapter3OrganButton")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(make_font(10.5, 700, spacing=0.5))
            button.setAccessibleName(f"{organ} organ (presentation filter only)")
            button.clicked.connect(lambda _checked=False, key=organ: self._select_organ(key))
            layout.addWidget(button, 1)
            self._organ_buttons[organ] = button
        self._organ_buttons[self._active_organ].setChecked(True)
        return frame

    def _build_demo_controls(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("chapter3TimelineCard")
        _allow_shrink(frame)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        label = QLabel("DEMO CONTROLS")
        label.setProperty("role", "cyan")
        label.setFont(make_font(9.5, 700, spacing=0.8))
        layout.addWidget(label)
        layout.addStretch(1)

        self._play_button = _DemoButton("PLAY")
        self._play_break_button = _DemoButton("PLAY WITH BREAK")
        self._pause_button = _DemoButton("PAUSE")
        self._replay_button = _DemoButton("REPLAY")
        self._reduced_motion_button = _DemoButton("REDUCED MOTION")
        self._reduced_motion_button.setCheckable(True)

        self._play_button.clicked.connect(lambda: self._on_play(with_break=False))
        self._play_break_button.clicked.connect(lambda: self._on_play(with_break=True))
        self._pause_button.clicked.connect(self.pause)
        self._replay_button.clicked.connect(self.replay)
        self._reduced_motion_button.toggled.connect(self._on_reduced_motion_toggled)

        for button in (
            self._play_button,
            self._play_break_button,
            self._pause_button,
            self._replay_button,
            self._reduced_motion_button,
        ):
            layout.addWidget(button)

        return frame

    # ------------------------------------------------------------------
    # Organ selector (presentation filter only)
    # ------------------------------------------------------------------

    def _select_organ(self, organ: str) -> None:
        if self._live_mode == MODE_LIVE and organ not in self._live_states:
            for key, button in self._organ_buttons.items():
                button.setChecked(key == self._active_organ)
            return
        self._active_organ = organ
        for key, button in self._organ_buttons.items():
            button.setChecked(key == organ)
        if self._live_mode == MODE_LIVE and organ in self._live_states:
            self._present_live_state()
        elif not self._live_mode:
            self._sync_trigger_note()

    def _sync_trigger_note(self) -> None:
        self._trigger_note.setText(_ORGAN_TRIGGER_NOTES[self._active_organ])

    # ------------------------------------------------------------------
    # Demo sequencing -- same _pending_steps / _step_timer idiom as
    # SCIENCE_LAB.schematics's organ walkthroughs.
    # ------------------------------------------------------------------

    def _happy_path_steps(self) -> list[tuple[int, Callable[[], None]]]:
        bar = self._episode_bar
        return [
            (0, lambda: bar.set_active_stage("OFF_TASK_DWELL")),
            (_STEP_MS * 2, lambda: bar.set_active_stage("TRIGGER")),
            (_STEP_MS, lambda: bar.set_active_stage("RETURN")),
            (_STEP_MS, lambda: bar.set_active_stage("VERIFIED_RETURN")),
            (_STEP_MS, lambda: bar.set_active_stage("EPISODE_CLOSURE")),
        ]

    def _break_path_steps(self) -> list[tuple[int, Callable[[], None]]]:
        bar = self._episode_bar
        lane = self._break_lane
        return [
            (0, lambda: bar.set_active_stage("OFF_TASK_DWELL")),
            (_STEP_MS * 2, lambda: bar.set_active_stage("TRIGGER")),
            (_STEP_MS, self._start_break),
            (_STEP_MS, lambda: lane.set_progress(0.33)),
            (_STEP_MS, lambda: lane.set_progress(0.66)),
            (_STEP_MS, self._complete_break),
            (_STEP_MS, self._resume_after_break),
            (_STEP_MS, lambda: bar.set_active_stage("RETURN")),
            (_STEP_MS, lambda: bar.set_active_stage("VERIFIED_RETURN")),
            (_STEP_MS, lambda: bar.set_active_stage("EPISODE_CLOSURE")),
        ]

    def _start_break(self) -> None:
        # Break re-entry rule (spec section 13): a break freezes the main
        # bar at its current stage; it never advances the upper bar itself.
        self._episode_bar.set_frozen(True)
        self._break_connector.setVisible(True)
        self._break_lane.start()

    def _complete_break(self) -> None:
        self._break_lane.complete()

    def _resume_after_break(self) -> None:
        self._break_lane.hide_lane()
        self._break_connector.setVisible(False)
        self._episode_bar.set_frozen(False)

    def _run_sequence(self, steps: list[tuple[int, Callable[[], None]]], *, remember: bool = True) -> None:
        self._step_timer.stop()
        if remember:
            self._last_sequence = list(steps)
        self._pending_steps = list(steps)
        self._is_paused = False
        self._advance_sequence()

    def _advance_sequence(self) -> None:
        if self._is_paused or not self._pending_steps:
            return
        delay, action = self._pending_steps.pop(0)
        action()
        if self._pending_steps:
            self._step_timer.start(0 if self._reduced_motion else delay)

    def pause(self) -> None:
        self._is_paused = True
        self._step_timer.stop()

    def _on_play(self, *, with_break: bool) -> None:
        if self._is_paused and self._pending_steps:
            self._is_paused = False
            self._advance_sequence()
            return
        if self._pending_steps:
            return
        self._reset_visual_state()
        self._run_sequence(self._break_path_steps() if with_break else self._happy_path_steps())

    def replay(self) -> None:
        self._reset_visual_state()
        self._run_sequence(self._last_sequence or self._happy_path_steps(), remember=False)

    def _reset_visual_state(self) -> None:
        self._episode_bar.reset()
        self._break_lane.hide_lane()
        self._break_connector.setVisible(False)

    def _on_reduced_motion_toggled(self, checked: bool) -> None:
        self._reduced_motion = checked
