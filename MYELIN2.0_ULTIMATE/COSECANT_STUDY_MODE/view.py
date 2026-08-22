"""Study Mode presentation for the MYELIN Control Station.

This file renders exact ``StudySnapshot``, ``CosecantSnapshot`` and
``ResourceIntentLiveView`` objects.  It emits user intent, but it never starts
a runtime, advances a deadline, classifies a resource or confirms a return.

All visual identity is expressed through stable Qt object names so the single
MYELIN theme authority can retain the approved design without backend logic
being hidden inside style code.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace as dataclasses_replace
from typing import Final

from PyQt6.QtCore import QDate, QObject, Qt, QTime, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QKeyEvent
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from CORE_ENGINE.resource_intent import ResourceIntentLiveView
from COSECANT_STUDY_MODE.cosecant import (
    CosecantSnapshot,
    CosecantState,
    CosecantUiAction,
)
from COSECANT_STUDY_MODE.planner import (
    PlanStatus,
    RecurrenceKind,
    RecurrenceRule,
    timezone_available,
)
from COSECANT_STUDY_MODE.study import StudySnapshot, StudyState
from UI_THEMES.animation import StudyRing
from UI_THEMES.theme import make_font, restyle


VIEW_SCHEMA_VERSION: Final = "myelin-study-view-v1"


@dataclass(frozen=True, slots=True)
class StudyViewState:
    """One exact presentation bundle; no dictionary guessing is allowed."""

    study: StudySnapshot | None
    cosecant: CosecantSnapshot | None
    resource_intent: ResourceIntentLiveView | None
    schema_version: str = VIEW_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.study is not None and not isinstance(self.study, StudySnapshot):
            raise TypeError("study must be a StudySnapshot")
        if self.cosecant is not None and not isinstance(
            self.cosecant, CosecantSnapshot
        ):
            raise TypeError("cosecant must be a CosecantSnapshot")
        if self.resource_intent is not None and not isinstance(
            self.resource_intent, ResourceIntentLiveView
        ):
            raise TypeError("resource_intent must be a ResourceIntentLiveView")


class StudyTimerCard(QFrame):
    """Timer setup and command presentation; every button emits intent only.

    Laid out as the mockup's left Study Mode column: a ``.sm-timer-card``
    holding the countdown ring, the PLANNED / ELAPSED / ENDS AT meta strip
    and the action row, above a ``Timer Setup`` card holding the duration
    presets and prepare fields.

    Nothing here decides anything.  The ring, the meta strip and the presets
    are paint: the ring shows the fraction the snapshot already published,
    the meta strip shows fields the telemetry panel already shows, and a
    preset button only writes a number into the minutes spin box the user
    could always have typed into themselves.
    """

    prepare_requested = pyqtSignal(str, str, int, int, object, object)
    action_requested = pyqtSignal(str)
    break_requested = pyqtSignal(int)

    DURATION_PRESETS: Final = (25, 45, 60, 90)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studyModeColumn")
        self.setAccessibleName("Study timer card")

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(18)
        column.addWidget(self._build_timer_panel())
        column.addWidget(self._build_setup_panel())

        self.render(None, None)

    # -- composition ------------------------------------------------------

    def _build_timer_panel(self) -> QFrame:
        """``.sm-timer-card`` -- caption, subject, ring, meta strip, actions."""

        panel = QFrame(self)
        panel.setObjectName("studyTimerCard")
        root = QVBoxLayout(panel)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(0)

        caption = QLabel("CURRENT TASK", panel)
        caption.setObjectName("studyTimerCaption")
        caption.setFont(make_font(11, 600, spacing=1.4))
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(caption)

        self.subject_label = QLabel("No subject selected", panel)
        self.subject_label.setObjectName("studySubject")
        self.subject_label.setFont(make_font(19, 800))
        self.subject_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addSpacing(4)
        root.addWidget(self.subject_label)

        self.task_label = QLabel("Prepare a Study block to begin", panel)
        self.task_label.setObjectName("studyTask")
        self.task_label.setFont(make_font(12, 400))
        self.task_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.task_label.setWordWrap(True)
        root.addSpacing(2)
        root.addWidget(self.task_label)

        # ``.sm-ring-wrap`` -- the countdown and its state caption live inside
        # the ring, so the historical label attributes simply point at them.
        self.ring = StudyRing(panel)
        ring_row = QHBoxLayout()
        ring_row.addStretch(1)
        ring_row.addWidget(self.ring)
        ring_row.addStretch(1)
        root.addSpacing(20)
        root.addLayout(ring_row)
        self.time_label = self.ring.time_label
        self.state_label = self.ring.caption_label

        self.progress = QProgressBar(panel)
        self.progress.setObjectName("studyTimerProgress")
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(StudyRing.SIZE)
        progress_row = QHBoxLayout()
        progress_row.addStretch(1)
        progress_row.addWidget(self.progress)
        progress_row.addStretch(1)
        root.addSpacing(14)
        root.addLayout(progress_row)

        meta_row = QHBoxLayout()
        meta_row.setSpacing(22)
        meta_row.addStretch(1)
        self._meta: dict[str, QLabel] = {}
        for key, text in (("planned", "Planned"), ("elapsed", "Elapsed"), ("ends", "Ends At")):
            meta_row.addLayout(self._meta_column(panel, key, text))
        meta_row.addStretch(1)
        root.addSpacing(14)
        root.addLayout(meta_row)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        self.start_button = self._action_button("START", "START", panel)
        self.pause_button = self._action_button("PAUSE", "PAUSE", panel)
        self.resume_button = self._action_button("RESUME", "RESUME", panel)
        self.complete_button = self._action_button("COMPLETE", "COMPLETE", panel)
        for button in (
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.complete_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addSpacing(22)
        root.addLayout(actions)

        break_row = QHBoxLayout()
        break_row.addStretch(1)
        self.break_button = QPushButton("START BREAK", panel)
        self.break_button.setObjectName("studyStartBreakButton")
        self.break_button.setFont(make_font(12, 700, spacing=0.8))
        self.break_button.setMinimumWidth(110)
        self.break_button.clicked.connect(
            lambda: self.break_requested.emit(self.break_minutes.value() * 60)
        )
        break_row.addWidget(self.break_button)
        break_row.addStretch(1)
        root.addSpacing(10)
        root.addLayout(break_row)
        return panel

    def _meta_column(self, parent: QWidget, key: str, text: str) -> QVBoxLayout:
        """One ``.sm-timer-meta`` cell: a 10px caption over a mono value."""

        cell = QVBoxLayout()
        cell.setSpacing(3)
        caption = QLabel(text.upper(), parent)
        caption.setObjectName("studyMetaLabel")
        caption.setFont(make_font(10, 600, spacing=1.0))
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value = QLabel("—", parent)
        value.setObjectName("studyMetaValue")
        value.setFont(make_font(13, 500, mono=True))
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cell.addWidget(caption)
        cell.addWidget(value)
        self._meta[key] = value
        return cell

    def _build_setup_panel(self) -> QFrame:
        """``Timer Setup`` -- duration presets over the four prepare fields."""

        panel = QFrame(self)
        panel.setObjectName("studySetupCard")
        root = QVBoxLayout(panel)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(0)

        heading = QLabel("TIMER SETUP", panel)
        heading.setObjectName("studySectionHeading")
        heading.setFont(make_font(12.5, 700, spacing=1.4))
        root.addWidget(heading)

        presets = QHBoxLayout()
        presets.setSpacing(8)
        self._preset_buttons: dict[int, QPushButton] = {}
        for minutes in self.DURATION_PRESETS:
            button = QPushButton(f"{minutes} MIN", panel)
            button.setObjectName("studyDurationButton")
            button.setFont(make_font(12.5, 700, mono=True))
            button.setCheckable(True)
            button.setMinimumWidth(64)
            button.clicked.connect(
                lambda _checked=False, value=minutes: self._apply_preset(value)
            )
            self._preset_buttons[minutes] = button
            presets.addWidget(button, 1)
        root.addSpacing(10)
        root.addLayout(presets)

        self.subject_input = QLineEdit(panel)
        self.subject_input.setObjectName("studySubjectInput")
        self.subject_input.setPlaceholderText("Subject")
        self.task_input = QLineEdit(panel)
        self.task_input.setObjectName("studyTaskInput")
        self.task_input.setPlaceholderText("Task or lecture title")
        self.keywords_input = QLineEdit(panel)
        self.keywords_input.setObjectName("studyTaskInput")
        self.keywords_input.setPlaceholderText("Keyword or phrase")
        self.important_keywords_input = QLineEdit(panel)
        self.important_keywords_input.setObjectName("studyTaskInput")
        self.important_keywords_input.setPlaceholderText("Important keyword or phrase")
        self.study_minutes = QSpinBox(panel)
        self.study_minutes.setObjectName("studyMinutesInput")
        self.study_minutes.setRange(1, 24 * 60)
        self.study_minutes.setValue(45)
        self.study_minutes.setSuffix(" min study")
        self.break_minutes = QSpinBox(panel)
        self.break_minutes.setObjectName("studyBreakInput")
        self.break_minutes.setRange(1, 24 * 60)
        self.break_minutes.setValue(10)
        self.break_minutes.setSuffix(" min break")
        for field in (
            self.subject_input,
            self.task_input,
            self.keywords_input,
            self.important_keywords_input,
            self.study_minutes,
            self.break_minutes,
        ):
            field.setFont(make_font(13, 500, mono=True))
        self.study_minutes.valueChanged.connect(self._sync_presets)

        fields = QGridLayout()
        fields.setHorizontalSpacing(14)
        fields.setVerticalSpacing(12)
        fields.addLayout(self._field(panel, "Study length", self.study_minutes), 0, 0)
        fields.addLayout(self._field(panel, "Break length", self.break_minutes), 0, 1)
        fields.addLayout(self._field(panel, "Subject", self.subject_input), 0, 2)
        fields.addLayout(self._field(panel, "Task / lecture", self.task_input), 1, 0, 1, 3)
        fields.addLayout(self._field(panel, "Keywords", self.keywords_input), 2, 0, 1, 2)
        fields.addLayout(
            self._field(panel, "Important Keywords", self.important_keywords_input),
            2,
            2,
        )
        fields.setColumnStretch(2, 1)
        root.addSpacing(16)
        root.addLayout(fields)

        self.prepare_button = QPushButton("PREPARE", panel)
        self.prepare_button.setObjectName("studyPrepareButton")
        self.prepare_button.setFont(make_font(12, 700, spacing=1.0))
        self.prepare_button.clicked.connect(self._emit_prepare)
        prepare_row = QHBoxLayout()
        prepare_row.addWidget(self.prepare_button)
        prepare_row.addStretch(1)
        root.addSpacing(16)
        root.addLayout(prepare_row)

        # Everything the lock covers, gathered once.  PREPARE is deliberately
        # not in this list: its own enabled-state is decided by the existing
        # frozen gating in render() and must not be touched from here.
        self._setup_inputs: tuple[QWidget, ...] = (
            self.study_minutes,
            self.break_minutes,
            self.subject_input,
            self.task_input,
            self.keywords_input,
            self.important_keywords_input,
        )

        self._sync_presets(self.study_minutes.value())
        return panel

    def _set_setup_locked(self, locked: bool) -> None:
        """Make Timer Setup non-editable while a block is ACTIVE or PAUSED.

        Values stay on screen; only editability changes.  Editing them could
        not alter the block already running, so presenting them as editable
        would tell the reader something untrue.
        """

        editable = not bool(locked)
        for field in self._setup_inputs:
            field.setEnabled(editable)
        for button in self._preset_buttons.values():
            button.setEnabled(editable)

    @staticmethod
    def _field(parent: QWidget, text: str, widget: QWidget) -> QVBoxLayout:
        """``.sm-field`` -- a 10px uppercase caption above one input."""

        cell = QVBoxLayout()
        cell.setSpacing(6)
        caption = QLabel(text.upper(), parent)
        caption.setObjectName("studyFieldLabel")
        caption.setFont(make_font(10, 600, spacing=1.0))
        cell.addWidget(caption)
        cell.addWidget(widget)
        return cell

    def _apply_preset(self, minutes: int) -> None:
        """Write a preset into the minutes box; nothing else is touched.

        This is an approved presentation affordance, not an incidental one:
        it writes a number into the same spin box the user could always type
        into, and reaches no runtime.  Whether the setup card as a whole is
        editable while a block runs is settled: ``_set_setup_locked`` makes it
        read-only in ACTIVE and PAUSED, driven from the published Study state
        in ``render``.  This preset writes into a field that lock already owns.
        """

        self.study_minutes.setValue(int(minutes))

    def _sync_presets(self, minutes: int) -> None:
        """Light the preset that matches the box, and none if it is custom."""

        for value, button in self._preset_buttons.items():
            button.setChecked(value == int(minutes))

    def _action_button(self, label: str, action: str, parent: QWidget) -> QPushButton:
        button = QPushButton(label, parent)
        button.setObjectName(f"study{action.title()}Button")
        button.setFont(make_font(12, 700, spacing=0.8))
        button.setMinimumWidth(110)
        button.clicked.connect(lambda _checked=False, name=action: self.action_requested.emit(name))
        return button

    def _emit_prepare(self) -> None:
        subject = " ".join(self.subject_input.text().split())
        task = " ".join(self.task_input.text().split())
        keyword = self.keywords_input.text()
        important_keyword = self.important_keywords_input.text()
        if not subject or not task:
            self.subject_input.setFocus()
            return
        self.prepare_requested.emit(
            subject,
            task,
            self.study_minutes.value() * 60,
            self.break_minutes.value() * 60,
            (keyword,) if keyword.strip() else (),
            (important_keyword,) if important_keyword.strip() else (),
        )

    def render(
        self,
        study: StudySnapshot | None,
        cosecant: CosecantSnapshot | None,
    ) -> None:
        if study is None:
            self.subject_label.setText("No subject selected")
            self.task_label.setText("Prepare a Study block to begin")
            self.time_label.setText("00:00")
            self.state_label.setText("EMPTY")
            self.progress.setValue(0)
            self.ring.set_progress(0.0)
            self._meta["planned"].setText("—")
            self._meta["elapsed"].setText("—")
            self._meta["ends"].setText("--:--")
            state = StudyState.EMPTY
        else:
            self.subject_label.setText(study.subject or "No subject selected")
            self.task_label.setText(study.task or "No task selected")
            self.time_label.setText(_duration(study.remaining_seconds))
            self.state_label.setText(study.state.value)
            self.progress.setValue(
                max(0, min(1000, int(round(study.progress_percent * 10))))
            )
            self.ring.set_progress(study.progress_percent / 100.0)
            self._meta["planned"].setText(_duration(study.planned_seconds))
            self._meta["elapsed"].setText(_duration(study.elapsed_seconds))
            self._meta["ends"].setText(_clock_text(study.ends_at_wall_time_utc))
            state = study.state

        # Locked strictly on the published Study state -- never on a timer
        # value, a button, COSECANT, Monitor or Resource Intent.  Only ACTIVE
        # and PAUSED lock; every other state keeps its existing behaviour.
        self._set_setup_locked(state in {StudyState.ACTIVE, StudyState.PAUSED})

        break_active = bool(
            cosecant is not None
            and cosecant.state
            in {
                CosecantState.BREAK_ACTIVE,
                CosecantState.BREAK_COMPLETE,
                CosecantState.BREAK_ALREADY_OVER,
                CosecantState.FINAL_LOCK,
                CosecantState.RETURN_CONFIRMING,
            }
        )
        final_lock = bool(cosecant is not None and cosecant.final_locked)
        self.prepare_button.setEnabled(
            state not in {StudyState.ACTIVE, StudyState.PAUSED, StudyState.SHUTDOWN}
        )
        self.start_button.setEnabled(state is StudyState.READY)
        self.pause_button.setEnabled(state is StudyState.ACTIVE and not break_active)
        self.resume_button.setEnabled(
            state is StudyState.PAUSED and not break_active and not final_lock
        )
        self.complete_button.setEnabled(
            state in {StudyState.ACTIVE, StudyState.PAUSED} and not final_lock
        )
        self.break_button.setEnabled(state is StudyState.ACTIVE and not break_active)


class StudyTelemetryPanel(QFrame):
    """Presentation-only Study and COSECANT telemetry."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("studyTelemetryCard")
        layout = QGridLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(10)
        title = QLabel("STUDY TELEMETRY", self)
        title.setObjectName("studySectionHeading")
        title.setFont(make_font(12.5, 700, spacing=1.4))
        layout.addWidget(title, 0, 0, 1, 2)
        self._values: dict[str, QLabel] = {}
        rows = (
            ("State", "state"),
            ("Planned", "planned"),
            ("Elapsed", "elapsed"),
            ("Ends at", "ends"),
            ("Protection", "protection"),
            ("Context delivery", "delivery"),
            ("COSECANT", "cosecant"),
            ("Next stage", "next"),
            ("Selected break", "selected_break"),
            ("Return status", "return_status"),
            ("Final lock", "final_lock"),
        )
        for row, (label, key) in enumerate(rows, start=1):
            name = QLabel(label.upper(), self)
            name.setObjectName("studyTelemetryName")
            name.setFont(make_font(10.5, 600, spacing=1.0))
            value = QLabel("—", self)
            value.setObjectName("studyTelemetryValue")
            value.setFont(make_font(12.5, 600))
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setWordWrap(True)
            layout.addWidget(name, row, 0)
            layout.addWidget(value, row, 1)
            self._values[key] = value

    def render(
        self,
        study: StudySnapshot | None,
        cosecant: CosecantSnapshot | None,
    ) -> None:
        if study is None:
            for value in self._values.values():
                value.setText("—")
            return
        self._values["state"].setText(study.state.value)
        self._values["planned"].setText(_duration(study.planned_seconds))
        self._values["elapsed"].setText(_duration(study.elapsed_seconds))
        self._values["ends"].setText(study.ends_at_wall_time_utc or "—")
        # "Protection" mirrors StudyContext.protection_active's own definition
        # (CORE_ENGINE.resource_intent.StudyContext: protection_active == the
        # ACTIVE display state) -- StudySnapshot's equivalent field is named
        # study_active. Context delivery is COSECANT's own fact (it is the
        # one publishing/retiring the StudyContext), not Study's.
        self._values["protection"].setText(
            "ACTIVE" if study.study_active else "INACTIVE"
        )
        self._values["delivery"].setText(
            cosecant.context_delivery.value if cosecant is not None else "—"
        )
        if cosecant is None:
            self._values["cosecant"].setText("INACTIVE")
            self._values["next"].setText("—")
            self._values["selected_break"].setText("—")
            self._values["return_status"].setText("—")
            self._values["final_lock"].setText("—")
        else:
            self._values["cosecant"].setText(cosecant.state.value)
            self._values["next"].setText(
                _duration(cosecant.seconds_to_next_stage)
                if cosecant.seconds_to_next_stage is not None
                else "—"
            )
            # Every row below reads a field COSECANT already published. None
            # of them computes a deadline, matches a resource or verifies a
            # return; the confirmation figure is the authority's own elapsed
            # count, shown, never a second three-second verifier.
            self._values["selected_break"].setText(
                _duration(cosecant.selected_break_seconds)
                if cosecant.selected_break_seconds
                else "—"
            )
            self._values["return_status"].setText(_return_status(cosecant))
            self._values["final_lock"].setText(
                "YES" if cosecant.final_locked else "NO"
            )


class ResourceIntentTelemetryPanel(QFrame):
    """Renders the exact Resource Intent live view without reclassification."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resourceIntentTelemetryCard")
        layout = QGridLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setHorizontalSpacing(18)
        layout.setVerticalSpacing(10)
        title = QLabel("RESOURCE INTENT", self)
        title.setObjectName("studySectionHeading")
        title.setFont(make_font(12.5, 700, spacing=1.4))
        layout.addWidget(title, 0, 0, 1, 2)
        self._values: dict[str, QLabel] = {}
        rows = (
            ("Classification", "classification"),
            ("Confidence", "confidence"),
            ("Resource", "resource"),
            ("Surface", "surface"),
            ("Evidence", "evidence"),
            ("Off-task dwell", "dwell"),
            ("SINE contribution", "sine"),
            ("Study idle", "idle"),
            ("Why no nudge", "reason"),
        )
        for row, (label, key) in enumerate(rows, start=1):
            name = QLabel(label.upper(), self)
            name.setObjectName("resourceIntentName")
            name.setFont(make_font(10.5, 600, spacing=1.0))
            value = QLabel("—", self)
            value.setObjectName("resourceIntentValue")
            value.setFont(make_font(12.5, 600))
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setWordWrap(True)
            layout.addWidget(name, row, 0)
            layout.addWidget(value, row, 1)
            self._values[key] = value

    def render(self, live: ResourceIntentLiveView | None) -> None:
        if live is None:
            for value in self._values.values():
                value.setText("—")
            return
        self._values["classification"].setText(live.classification.value)
        self._values["confidence"].setText(f"{live.confidence * 100:.0f}%")
        self._values["resource"].setText(live.display_title or "—")
        self._values["surface"].setText(live.resource_surface.value)
        self._values["evidence"].setText(
            "CERTIFIED" if live.browser_evidence_certified else "UNAVAILABLE"
        )
        self._values["dwell"].setText(
            f"{_duration(live.dwell_elapsed_seconds)} / "
            f"{_duration(live.dwell_target_seconds)}"
        )
        self._values["sine"].setText(live.sine_contribution.value.upper())
        self._values["idle"].setText(
            "ALLOWED" if live.study_idle_allowed else "OFF"
        )
        self._values["reason"].setText(live.no_nudge_reason_code or "—")


def _cosecant_supersedes(
    incoming: CosecantSnapshot,
    current: CosecantSnapshot | None,
) -> bool:
    """Return True when ``incoming`` may replace ``current`` on screen.

    Presentation ordering only.  This decides nothing about the break: it
    decides which already-published COSECANT fact is the newest one this
    surface has been handed, so a queued or retired snapshot cannot repaint
    over a newer episode.

    A higher generation always wins.  Within one generation the break_id must
    match, the durable ``fact_sequence`` may never move backwards, and an equal
    sequence may not carry a different state -- every COSECANT transition emits
    a fact, so a state change with an unchanged sequence is out of order.  An
    equal sequence in the same state IS accepted: countdown and progress
    projections update without creating a new durable fact.
    """

    if current is None:
        return True
    if int(incoming.generation) != int(current.generation):
        return int(incoming.generation) > int(current.generation)
    if str(incoming.break_id) != str(current.break_id):
        return False
    if int(incoming.fact_sequence) != int(current.fact_sequence):
        return int(incoming.fact_sequence) > int(current.fact_sequence)
    return incoming.state is current.state


def _study_supersedes(
    incoming: StudySnapshot,
    current: StudySnapshot | None,
) -> bool:
    """Return True when ``incoming`` may replace ``current`` on screen.

    A higher Study generation always wins.  Within one generation the block_id
    must match and the runtime's own ``published_monotonic_ns`` may not move
    backwards; an equal publication instant is accepted so an ordinary repaint
    is never mistaken for a regression.
    """

    if current is None:
        return True
    if int(incoming.generation) != int(current.generation):
        return int(incoming.generation) > int(current.generation)
    if str(incoming.block_id) != str(current.block_id):
        return False
    return int(incoming.published_monotonic_ns) >= int(
        current.published_monotonic_ns
    )


class ContinuityPopup(QDialog):
    """COSECANT reminder presentation; the snapshot owns every decision."""

    #: break_id, COSECANT generation, Study block_id, Study generation -- the
    #: identity of the snapshot that actually displayed the button, so a click
    #: can never be applied to whatever episode happens to be current later.
    return_intent_requested = pyqtSignal(str, int, str, int)

    def __init__(self) -> None:
        super().__init__(None)
        self.setObjectName("cosecantContinuityPopup")
        self.setWindowTitle("MYELIN — COSECANT")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setModal(False)
        self.setMinimumWidth(520)
        self._snapshot: CosecantSnapshot | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(34, 30, 34, 28)
        root.setSpacing(14)
        badge = QLabel("COSECANT · BREAK RETURN", self)
        badge.setObjectName("cosecantPopupBadge")
        root.addWidget(badge)
        self.message_label = QLabel("", self)
        self.message_label.setObjectName("cosecantPopupMessage")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setWordWrap(True)
        root.addWidget(self.message_label)
        self.detail_label = QLabel("", self)
        self.detail_label.setObjectName("cosecantPopupDetail")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setWordWrap(True)
        root.addWidget(self.detail_label)
        self.countdown_label = QLabel("", self)
        self.countdown_label.setObjectName("cosecantPopupCountdown")
        self.countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.countdown_label)
        self.return_button = QPushButton("RETURN TO STUDY", self)
        self.return_button.setObjectName("cosecantReturnIntentButton")
        self.return_button.clicked.connect(self._emit_return_intent)
        root.addWidget(self.return_button)

    def _emit_return_intent(self) -> None:
        """Emit the identity of the snapshot that displayed this button.

        The identity is read from ``self._snapshot`` rather than invented
        downstream, so an old click carries the old episode's name and the
        authority can refuse it.
        """

        snapshot = self._snapshot
        if snapshot is None:
            return
        self.return_intent_requested.emit(
            str(snapshot.break_id),
            int(snapshot.generation),
            str(snapshot.study_block_id),
            int(snapshot.study_generation),
        )

    def present_snapshot(self, snapshot: CosecantSnapshot) -> None:
        if not isinstance(snapshot, CosecantSnapshot):
            raise TypeError("continuity popup requires a CosecantSnapshot")
        # Fail closed on presentation order.  ``request_continuity_popup`` is a
        # public pathway over a queued connection, so a retired episode's
        # snapshot can arrive after a newer one; it must not repaint over it or
        # reopen a notice a terminal generation has already closed.
        if not _cosecant_supersedes(snapshot, self._snapshot):
            return
        self._snapshot = snapshot
        if not snapshot.popup_required:
            self.hide()
            return
        self.message_label.setText(snapshot.message.value)
        if snapshot.state is CosecantState.RETURN_CONFIRMING:
            self.detail_label.setText(
                "Keep the confirmed Study resource present for 3 continuous seconds."
            )
        elif snapshot.final_locked:
            self.detail_label.setText(
                "Open the intended Study resource. This notice closes only after observed return."
            )
        else:
            self.detail_label.setText(
                "Your selected break has ended. Return evidence is verified by MYELIN."
            )
        self.countdown_label.setText(
            _duration(snapshot.seconds_to_next_stage)
            if snapshot.seconds_to_next_stage is not None
            else ""
        )
        action_allowed = (
            CosecantUiAction.RETURN_TO_STUDY in snapshot.allowed_actions
        )
        # Locked invariant: FINAL_LOCK and its confirmation have no button.
        self.return_button.setVisible(action_allowed and not snapshot.final_locked)
        self.return_button.setEnabled(action_allowed and not snapshot.final_locked)
        self.show()
        self.raise_()
        self.activateWindow()

    def reset_presentation_epoch(self) -> None:
        """Clear the ordering baseline for a NEW Core Engine session.

        Each engine session builds fresh Study and COSECANT authorities whose
        generations legitimately restart from zero.  A baseline kept across
        that boundary would refuse the new session's genuine truth as stale,
        so the boundary -- and only the boundary -- clears it.

        This is not a FINAL_LOCK escape.  It is reachable only from
        ``ControlStationController._prepare_new_session``, i.e. when the
        previous engine authority has already ended and there is no live break
        left to hold anything open.  No ordinary ``CosecantSnapshot`` can reach
        it, and ``closeEvent`` / ``keyPressEvent`` are untouched.
        """

        self._snapshot = None
        self.hide()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._snapshot is not None and self._snapshot.popup_must_remain_open:
            event.ignore()
            self.show()
            return
        event.accept()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if (
            event.key() == Qt.Key.Key_Escape
            and self._snapshot is not None
            and self._snapshot.popup_must_remain_open
        ):
            event.accept()
            return
        super().keyPressEvent(event)


class _ContinuityPopupDispatcher(QObject):
    """Carry worker requests to one GUI-thread popup without blocking engine."""

    popup_requested = pyqtSignal(object)
    reset_requested = pyqtSignal()
    return_intent_requested = pyqtSignal(str, int, str, int)

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._popup = ContinuityPopup()
        self._popup.return_intent_requested.connect(
            self.return_intent_requested.emit
        )
        self.popup_requested.connect(
            self._present,
            Qt.ConnectionType.QueuedConnection,
        )
        self.reset_requested.connect(
            self._reset,
            Qt.ConnectionType.QueuedConnection,
        )

    @pyqtSlot(object)
    def _present(self, snapshot: object) -> None:
        if isinstance(snapshot, CosecantSnapshot):
            self._popup.present_snapshot(snapshot)

    @pyqtSlot()
    def _reset(self) -> None:
        self._popup.reset_presentation_epoch()


_DISPATCHER_LOCK = threading.RLock()
_DISPATCHER: _ContinuityPopupDispatcher | None = None


def install_popup_dispatcher(app: QApplication) -> None:
    """Install the one COSECANT popup dispatcher on the Qt main thread."""

    if not isinstance(app, QApplication):
        raise TypeError("app must be a QApplication")
    global _DISPATCHER
    with _DISPATCHER_LOCK:
        if _DISPATCHER is None:
            _DISPATCHER = _ContinuityPopupDispatcher(app)


def request_continuity_popup(snapshot: CosecantSnapshot) -> bool:
    """Queue one exact snapshot; never wait for the GUI from engine code."""

    if not isinstance(snapshot, CosecantSnapshot):
        return False
    with _DISPATCHER_LOCK:
        dispatcher = _DISPATCHER
    if dispatcher is None:
        return False
    dispatcher.popup_requested.emit(snapshot)
    return True


def reset_continuity_presentation() -> bool:
    """Clear the popup's ordering baseline for a new Core Engine session."""

    with _DISPATCHER_LOCK:
        dispatcher = _DISPATCHER
    if dispatcher is None:
        return False
    dispatcher.reset_requested.emit()
    return True




class StudyPlannerPanel(QWidget):
    """The Study Planner surface, inside the Study page.

    Presentation and assembly only.  Every planning FACT -- validation,
    recurrence expansion, DST fold, conflict detection, versioning, durability
    and one-use preparation -- belongs to ``StudyPlanner``.  This panel builds
    candidates from the form, hands them to that authority, and renders
    whatever the authority says afterwards.

    It never starts Study and never touches COSECANT.  ``SET STUDY TIMER``
    obtains a one-use preparation and emits it; ``StudyView`` performs the
    Protected Red recheck and the Study identity fence before anything reaches
    the controller, and the user still presses START on the Study card.
    """

    back_requested = pyqtSignal()
    #: One CosecantTimerPreparation the user explicitly asked to set.
    timer_requested = pyqtSignal(object)


    #: Local dark styling for the Planner's input and list widgets.
    #:
    #: view.py normally expresses visual identity through object names alone so
    #: UI_THEMES.theme stays the single design authority.  The theme currently
    #: carries no rule for a generic QListWidget / QComboBox / QDateEdit, so
    #: without this the Planner list paints white against the dark Study page.
    #: theme.py is not an authorized C11-B file, so the rules live here for now
    #: and should be folded into the theme authority when that file is opened.
    #: They set colour only -- no rule here decides any Planner fact.
    PANEL_STYLE: Final = """
    QListWidget#plannerBlockList {
        background: %(raised)s; color: %(text)s;
        border: 1px solid %(border)s; border-radius: 10px; padding: 6px;
    }
    QListWidget#plannerBlockList::item {
        color: %(text)s; padding: 7px 8px; border-radius: 7px;
    }
    QListWidget#plannerBlockList::item:selected {
        background: %(cyan)s; color: %(base)s;
    }
    QComboBox, QDateEdit, QTimeEdit {
        background: %(raised)s; color: %(text)s;
        border: 1px solid %(border)s; border-radius: 7px; padding: 6px 8px;
    }
    QComboBox QAbstractItemView {
        background: %(surface)s; color: %(text)s;
        selection-background-color: %(cyan)s; selection-color: %(base)s;
    }
    """

    def _apply_panel_style(self) -> None:
        from UI_THEMES.theme import DEFAULT_THEME

        self.setStyleSheet(
            self.PANEL_STYLE
            % {
                "base": DEFAULT_THEME.window_background,
                "surface": DEFAULT_THEME.surface,
                "raised": DEFAULT_THEME.surface_soft,
                "border": DEFAULT_THEME.border,
                "text": DEFAULT_THEME.text_primary,
                "cyan": DEFAULT_THEME.cyan,
            }
        )
    RECURRENCE_LABELS: Final = (
        ("Does not repeat", RecurrenceKind.NONE),
        ("Every day", RecurrenceKind.DAILY),
        ("Weekdays", RecurrenceKind.WEEKDAYS),
        ("Every week", RecurrenceKind.WEEKLY),
    )

    def __init__(
        self,
        *,
        planner: object,
        timezone_choices: tuple[str, ...] = (),
        configured_timezone: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("studyPlannerPanel")
        self.setAccessibleName("MYELIN Study Planner")
        self._planner = planner
        self._mode = "day"
        self._visible: list = []
        self._editing_block_id = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addLayout(self._build_header())
        layout.addWidget(self._build_form())
        layout.addWidget(self._build_list(), 1)
        layout.addWidget(self._build_actions())

        self._install_timezones(timezone_choices, configured_timezone)
        self._apply_panel_style()
        self._sync_actions()

    # -- composition ------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        title = QLabel("STUDY PLANNER", self)
        title.setObjectName("studyModeTitle")
        title.setFont(make_font(20, 700, mono=True, spacing=2.0))
        heading.addWidget(title)
        subtitle = QLabel("Planned Study blocks · preparation only", self)
        subtitle.setObjectName("studyModeSubtitle")
        subtitle.setFont(make_font(12.5, 400))
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch(1)

        self.day_button = QPushButton("DAY", self)
        self.day_button.setObjectName("studyDurationButton")
        self.day_button.setCheckable(True)
        self.day_button.setChecked(True)
        self.day_button.clicked.connect(lambda: self.set_mode("day"))
        self.list_button = QPushButton("LIST", self)
        self.list_button.setObjectName("studyDurationButton")
        self.list_button.setCheckable(True)
        self.list_button.clicked.connect(lambda: self.set_mode("list"))
        header.addWidget(self.day_button)
        header.addWidget(self.list_button)

        self.back_button = QPushButton("BACK TO STUDY", self)
        self.back_button.setObjectName("studyMenuButton")
        self.back_button.setFont(make_font(12, 700, spacing=0.8))
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        return header

    def _build_form(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("studySetupCard")
        root = QVBoxLayout(panel)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(0)

        heading = QLabel("PLAN A STUDY BLOCK", panel)
        heading.setObjectName("studySectionHeading")
        heading.setFont(make_font(12.5, 700, spacing=1.4))
        root.addWidget(heading)

        self.date_input = QDateEdit(QDate.currentDate(), panel)
        self.date_input.setObjectName("studySubjectInput")
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("yyyy-MM-dd")
        self.time_input = QTimeEdit(QTime(9, 0), panel)
        self.time_input.setObjectName("studySubjectInput")
        self.time_input.setDisplayFormat("HH:mm")
        self.subject_input = QLineEdit(panel)
        self.subject_input.setObjectName("studySubjectInput")
        self.subject_input.setPlaceholderText("Subject")
        self.task_input = QLineEdit(panel)
        self.task_input.setObjectName("studyTaskInput")
        self.task_input.setPlaceholderText("Task or lecture title")
        self.study_minutes = QSpinBox(panel)
        self.study_minutes.setObjectName("studyMinutesInput")
        self.study_minutes.setRange(1, 24 * 60)
        self.study_minutes.setValue(45)
        self.study_minutes.setSuffix(" min study")
        self.break_minutes = QSpinBox(panel)
        self.break_minutes.setObjectName("studyBreakInput")
        self.break_minutes.setRange(1, 24 * 60)
        self.break_minutes.setValue(10)
        self.break_minutes.setSuffix(" min break")
        self.recurrence_input = QComboBox(panel)
        self.recurrence_input.setObjectName("studySubjectInput")
        for text, kind in self.RECURRENCE_LABELS:
            self.recurrence_input.addItem(text, kind.value)
        self.timezone_input = QComboBox(panel)
        self.timezone_input.setObjectName("studySubjectInput")

        for field in (
            self.date_input,
            self.time_input,
            self.subject_input,
            self.task_input,
            self.study_minutes,
            self.break_minutes,
            self.recurrence_input,
            self.timezone_input,
        ):
            field.setFont(make_font(13, 500, mono=True))

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        grid.addLayout(self._field("Date", self.date_input), 0, 0)
        grid.addLayout(self._field("Start time", self.time_input), 0, 1)
        grid.addLayout(self._field("Timezone", self.timezone_input), 0, 2)
        grid.addLayout(self._field("Study length", self.study_minutes), 1, 0)
        grid.addLayout(self._field("Break length", self.break_minutes), 1, 1)
        grid.addLayout(self._field("Repeats", self.recurrence_input), 1, 2)
        grid.addLayout(self._field("Subject", self.subject_input), 2, 0, 1, 3)
        grid.addLayout(self._field("Task / lecture", self.task_input), 3, 0, 1, 3)
        grid.setColumnStretch(2, 1)
        root.addSpacing(16)
        root.addLayout(grid)

        row = QHBoxLayout()
        self.save_button = QPushButton("SAVE BLOCK", panel)
        self.save_button.setObjectName("studyPrepareButton")
        self.save_button.setFont(make_font(12, 700, spacing=1.0))
        self.save_button.clicked.connect(self._save_block)
        self.clear_button = QPushButton("CLEAR", panel)
        self.clear_button.setObjectName("studyDurationButton")
        self.clear_button.clicked.connect(self.clear_form)
        row.addWidget(self.save_button)
        row.addWidget(self.clear_button)
        row.addStretch(1)
        root.addSpacing(16)
        root.addLayout(row)
        return panel

    def _build_list(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("studyTelemetryCard")
        root = QVBoxLayout(panel)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(10)

        heading = QLabel("PLANNED BLOCKS", panel)
        heading.setObjectName("studySectionHeading")
        heading.setFont(make_font(12.5, 700, spacing=1.4))
        root.addWidget(heading)

        self.date_row = QHBoxLayout()
        self.previous_day = QPushButton("‹", panel)
        self.previous_day.setObjectName("studyDurationButton")
        self.previous_day.clicked.connect(lambda: self._shift_day(-1))
        self.today_button = QPushButton("TODAY", panel)
        self.today_button.setObjectName("studyDurationButton")
        self.today_button.clicked.connect(self.show_today)
        self.next_day = QPushButton("›", panel)
        self.next_day.setObjectName("studyDurationButton")
        self.next_day.clicked.connect(lambda: self._shift_day(1))
        self.view_date = QDateEdit(QDate.currentDate(), panel)
        self.view_date.setObjectName("studySubjectInput")
        self.view_date.setDisplayFormat("yyyy-MM-dd")
        self.view_date.setCalendarPopup(True)
        self.view_date.dateChanged.connect(lambda _value: self.render())
        self.date_row.addWidget(self.previous_day)
        self.date_row.addWidget(self.view_date)
        self.date_row.addWidget(self.today_button)
        self.date_row.addWidget(self.next_day)
        self.date_row.addStretch(1)
        root.addLayout(self.date_row)

        self.conflict_label = QLabel("", panel)
        self.conflict_label.setObjectName("studyTelemetryValue")
        self.conflict_label.setFont(make_font(12, 600))
        self.conflict_label.setWordWrap(True)
        root.addWidget(self.conflict_label)

        self.block_list = QListWidget(panel)
        self.block_list.setObjectName("plannerBlockList")
        self.block_list.setAccessibleName("Planned study blocks")
        self.block_list.currentRowChanged.connect(lambda _row: self._sync_actions())
        root.addWidget(self.block_list, 1)

        self.status_label = QLabel("", panel)
        self.status_label.setObjectName("studyTelemetryName")
        self.status_label.setFont(make_font(11.5, 600))
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        return panel

    def _build_actions(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("plainBox")
        row = QHBoxLayout(panel)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.edit_button = self._action("EDIT", self._edit_selected, panel)
        self.duplicate_button = self._action("DUPLICATE", self._duplicate_selected, panel)
        self.skip_button = self._action("SKIP", self._skip_selected, panel)
        self.remove_button = self._action("REMOVE", self._remove_selected, panel)
        for button in (
            self.edit_button,
            self.duplicate_button,
            self.skip_button,
            self.remove_button,
        ):
            row.addWidget(button)
        row.addStretch(1)
        self.set_timer_button = QPushButton("SET STUDY TIMER", panel)
        self.set_timer_button.setObjectName("studyPrepareButton")
        self.set_timer_button.setFont(make_font(12, 700, spacing=1.0))
        self.set_timer_button.setMinimumWidth(180)
        self.set_timer_button.clicked.connect(self._set_study_timer)
        row.addWidget(self.set_timer_button)
        return panel

    def _action(self, text: str, handler, parent: QWidget) -> QPushButton:
        button = QPushButton(text, parent)
        button.setObjectName("studyDurationButton")
        button.setFont(make_font(12, 700, spacing=0.8))
        button.clicked.connect(handler)
        return button

    @staticmethod
    def _field(text: str, widget: QWidget) -> QVBoxLayout:
        cell = QVBoxLayout()
        cell.setSpacing(6)
        caption = QLabel(text.upper(), widget.parentWidget())
        caption.setObjectName("studyFieldLabel")
        caption.setFont(make_font(10, 600, spacing=1.0))
        cell.addWidget(caption)
        cell.addWidget(widget)
        return cell

    # -- timezone ---------------------------------------------------------

    def _install_timezones(
        self,
        choices: tuple[str, ...],
        configured: str,
    ) -> None:
        """Offer NAMED IANA zones only.

        Recurrence needs real DST transition rules.  The clock's ``"local"``
        setting is not an IANA name and its fixed-offset fallback carries no
        transitions, so neither may become planner truth: an unusable
        configured value simply leaves no zone preselected and the user picks
        a named one.
        """

        named = tuple(
            name for name in choices if name and timezone_available(name)
        )
        for name in named:
            self.timezone_input.addItem(name, name)
        if not named:
            self.timezone_input.addItem("No named timezone available", "")
            self.timezone_input.setEnabled(False)
            self._set_status(
                "Choose a named timezone before planning: recurring Study "
                "blocks need real daylight-saving rules."
            )
            return
        index = self.timezone_input.findData(str(configured))
        if index >= 0:
            self.timezone_input.setCurrentIndex(index)
        else:
            self._set_status(
                "Select a named Planner timezone. The clock setting "
                f"({configured or 'local'}) has no daylight-saving rules."
            )

    def selected_timezone(self) -> str:
        return str(self.timezone_input.currentData() or "")

    # -- planner truth ----------------------------------------------------

    def activate(self) -> None:
        """Entering the Planner: reload durable truth, then render it."""

        try:
            self._planner.load_persisted()
        except Exception as exc:                # noqa: BLE001 - shown, not hidden
            self._set_status(f"Could not load saved plans: {exc}")
        self.render()

    def set_mode(self, mode: str) -> None:
        self._mode = "list" if str(mode) == "list" else "day"
        self.day_button.setChecked(self._mode == "day")
        self.list_button.setChecked(self._mode == "list")
        self.render()

    def show_today(self) -> None:
        self.view_date.setDate(QDate.currentDate())
        self.render()

    def _shift_day(self, days: int) -> None:
        self.view_date.setDate(self.view_date.date().addDays(int(days)))
        self.render()

    def render(self) -> None:
        """Repaint from planner truth.  Nothing is computed here."""

        self.block_list.clear()
        self._visible = []
        day = self.view_date.date().toString("yyyy-MM-dd")
        try:
            if self._mode == "day":
                projection = self._planner.project(date_from=day, date_to=day)
                self._render_occurrences(projection)
            else:
                self._render_blocks()
        except Exception as exc:                # noqa: BLE001 - shown, not hidden
            self._set_status(f"Planner could not project: {exc}")
        self._sync_actions()

    def _render_occurrences(self, projection: object) -> None:
        for occurrence in projection.occurrences:
            clock = f"{occurrence.local_hour:02d}:{occurrence.local_minute:02d}"
            item = QListWidgetItem(
                f"{clock}   {occurrence.subject} — {occurrence.task}\n"
                f"{occurrence.study_minutes} min study · "
                f"{occurrence.break_minutes} min break · "
                f"{occurrence.status.value} · {occurrence.timezone_id}"
            )
            self.block_list.addItem(item)
            self._visible.append(occurrence)
        # Conflicts come from the Planner's own projection, never from a
        # second overlap algorithm in Qt.
        warnings = tuple(projection.warnings)
        if warnings:
            self.conflict_label.setText(
                "\n".join(f"⚠ {warning.message}" for warning in warnings)
            )
        else:
            self.conflict_label.setText("No planner warnings for this day.")
        if not self._visible:
            self.block_list.addItem(
                QListWidgetItem("No Study blocks planned for this day.")
            )

    def _render_blocks(self) -> None:
        blocks = tuple(self._planner.blocks())
        for block in blocks:
            clock = f"{block.local_hour:02d}:{block.local_minute:02d}"
            item = QListWidgetItem(
                f"{block.local_date}  {clock}   {block.subject} — {block.task}\n"
                f"{block.study_minutes} min study · "
                f"{block.break_minutes} min break · "
                f"{block.status.value} · {block.recurrence.kind.value} · "
                f"{block.timezone_id}"
            )
            self.block_list.addItem(item)
            self._visible.append(block)
        self.conflict_label.setText(f"{len(blocks)} planned block(s) stored.")
        if not blocks:
            self.block_list.addItem(QListWidgetItem("No Study blocks planned yet."))

    def _selected(self):
        row = self.block_list.currentRow()
        if 0 <= row < len(self._visible):
            return self._visible[row]
        return None

    def _selected_block(self):
        """The current PlanBlock behind the selected row, from planner truth."""

        selected = self._selected()
        if selected is None:
            return None
        try:
            return self._planner.block(selected.block_id)
        except Exception:                       # noqa: BLE001 - refreshed below
            return None

    def _sync_actions(self) -> None:
        selected = self._selected() is not None
        for button in (
            self.edit_button,
            self.duplicate_button,
            self.skip_button,
            self.remove_button,
        ):
            button.setEnabled(selected)
        # SET STUDY TIMER needs a canonical OCCURRENCE, which only the Day
        # projection produces; a stored block is not an occurrence.
        self.set_timer_button.setEnabled(selected and self._mode == "day")

    # -- mutations --------------------------------------------------------

    def clear_form(self) -> None:
        self._editing_block_id = ""
        self.subject_input.clear()
        self.task_input.clear()
        self.study_minutes.setValue(45)
        self.break_minutes.setValue(10)
        self.recurrence_input.setCurrentIndex(0)
        self.save_button.setText("SAVE BLOCK")

    def _form_recurrence(self):
        return RecurrenceRule(
            kind=RecurrenceKind(str(self.recurrence_input.currentData()))
        )

    def _save_block(self) -> None:
        subject = " ".join(self.subject_input.text().split())
        task = " ".join(self.task_input.text().split())
        zone = self.selected_timezone()
        if not subject or not task:
            self._set_status("Subject and task are required.")
            return
        if not zone:
            self._set_status("Choose a named Planner timezone first.")
            return
        time_value = self.time_input.time()
        try:
            if self._editing_block_id:
                current = self._planner.block(self._editing_block_id)
                self._planner.replace_block(
                    dataclasses_replace(
                        current,
                        subject=subject,
                        task=task,
                        local_date=self.date_input.date().toString("yyyy-MM-dd"),
                        local_hour=time_value.hour(),
                        local_minute=time_value.minute(),
                        timezone_id=zone,
                        study_minutes=self.study_minutes.value(),
                        break_minutes=self.break_minutes.value(),
                        recurrence=self._form_recurrence(),
                    )
                )
                self._set_status("Study block updated.")
            else:
                self._planner.add_block(
                    subject=subject,
                    task=task,
                    local_date=self.date_input.date().toString("yyyy-MM-dd"),
                    local_hour=time_value.hour(),
                    local_minute=time_value.minute(),
                    timezone_id=zone,
                    dst_fold=0,
                    study_minutes=self.study_minutes.value(),
                    break_minutes=self.break_minutes.value(),
                    recurrence=self._form_recurrence(),
                )
                self._set_status("Study block planned.")
        except Exception as exc:                # noqa: BLE001 - honest failure
            # The mutation was refused.  Previous visible truth is preserved
            # and re-rendered; nothing pretends the change succeeded.
            self._set_status(f"Not saved: {exc}")
            self.render()
            return
        self.clear_form()
        self.render()

    def _edit_selected(self) -> None:
        block = self._selected_block()
        if block is None:
            self._set_status("That block is no longer available; reloaded.")
            self.render()
            return
        self._editing_block_id = block.block_id
        self.subject_input.setText(block.subject)
        self.task_input.setText(block.task)
        self.date_input.setDate(QDate.fromString(block.local_date, "yyyy-MM-dd"))
        self.time_input.setTime(QTime(block.local_hour, block.local_minute))
        self.study_minutes.setValue(block.study_minutes)
        self.break_minutes.setValue(block.break_minutes)
        index = self.recurrence_input.findData(block.recurrence.kind.value)
        if index >= 0:
            self.recurrence_input.setCurrentIndex(index)
        zone_index = self.timezone_input.findData(block.timezone_id)
        if zone_index >= 0:
            self.timezone_input.setCurrentIndex(zone_index)
        self.save_button.setText("UPDATE BLOCK")
        self._set_status(f"Editing {block.subject} — {block.task}.")

    def _mutate(self, operation, success: str) -> None:
        block = self._selected_block()
        if block is None:
            self._set_status("That block is no longer available; reloaded.")
            self.render()
            return
        try:
            operation(block)
        except Exception as exc:                # noqa: BLE001 - honest failure
            self._set_status(f"Not applied: {exc}")
            self.render()
            return
        self._set_status(success)
        self.render()

    def _remove_selected(self) -> None:
        self._mutate(
            lambda block: self._planner.remove_block(
                block.block_id, expected_version=block.version
            ),
            "Study block removed.",
        )

    def _skip_selected(self) -> None:
        self._mutate(
            lambda block: self._planner.set_status(
                block.block_id, PlanStatus.SKIPPED, expected_version=block.version
            ),
            "Study block marked skipped.",
        )

    def _duplicate_selected(self) -> None:
        def duplicate(block) -> None:
            self._planner.add_block(
                subject=block.subject,
                task=block.task,
                local_date=block.local_date,
                local_hour=block.local_hour,
                local_minute=block.local_minute,
                timezone_id=block.timezone_id,
                dst_fold=block.dst_fold,
                study_minutes=block.study_minutes,
                break_minutes=block.break_minutes,
                recurrence=block.recurrence,
                priority=block.priority,
            )

        self._mutate(duplicate, "Study block duplicated.")

    # -- the Study seam ---------------------------------------------------

    def _set_study_timer(self) -> None:
        """Obtain a one-use preparation for the selected canonical occurrence.

        This panel does not decide legality.  ``prepare_cosecant_timer``
        re-derives the occurrence from planner authority and refuses anything
        that is not canonical; ``StudyView`` then performs the Protected Red
        recheck and the Study identity fence.  Nothing here starts Study.
        """

        occurrence = self._selected()
        if occurrence is None or self._mode != "day":
            self._set_status("Select a planned occurrence in DAY view first.")
            return
        try:
            result = self._planner.prepare_cosecant_timer(occurrence)
        except Exception as exc:                # noqa: BLE001 - honest failure
            self._set_status(f"Could not prepare a timer: {exc}")
            return
        if not getattr(result, "accepted", False):
            self._set_status(
                f"Timer not prepared: {getattr(result, 'reason', 'refused')}"
            )
            self.render()
            return
        self.timer_requested.emit(result.preparation)

    def _set_status(self, message: str) -> None:
        text = " ".join(str(message).split())[:240]
        self.status_label.setText(text)
        self.status_label.setToolTip(text)

    def status_text(self) -> str:
        return self.status_label.text()


class StudyNotesPanel(QWidget):
    """The Study Notes surface: a persisted-note browser beside the editor.

    Assembly and presentation only.  Every note FACT -- validation, structured
    opaque blocks, revision lineage, autosave generations, save state -- stays
    inside ``NoteSession`` and ``NotesWorkspace``.  This panel lists what the
    store already holds, asks the workspace to open one, and shows the state
    the session reports.

    NOTES ARE OPAQUE.  Nothing here reads note CONTENT for any purpose beyond
    display: no text is inspected, summarised, classified or forwarded, and
    the panel imports no sensing or behavioural authority.  The only values
    that cross to another organ are linkage IDs, which say "this note is
    associated with that block" and never "this note proves anything".
    """

    back_requested = pyqtSignal()

    def __init__(
        self,
        *,
        workspace: object,
        store: object,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("studyNotesPanel")
        self.setAccessibleName("MYELIN Study Notes")
        self._workspace = workspace
        self._store = store
        self._summaries: list = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        layout.addLayout(self._build_header())

        split = QHBoxLayout()
        split.setSpacing(18)
        split.addWidget(self._build_browser(), 10)
        split.addWidget(self._build_editor_host(), 13)
        layout.addLayout(split, 1)

        self._apply_panel_style()
        self._sync_actions()

    # -- composition ------------------------------------------------------

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        title = QLabel("STUDY NOTES", self)
        title.setObjectName("studyModeTitle")
        title.setFont(make_font(20, 700, mono=True, spacing=2.0))
        heading.addWidget(title)
        subtitle = QLabel("Your own record · never used as Study evidence", self)
        subtitle.setObjectName("studyModeSubtitle")
        subtitle.setFont(make_font(12.5, 400))
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch(1)

        self.new_button = QPushButton("NEW NOTE", self)
        self.new_button.setObjectName("studyPrepareButton")
        self.new_button.setFont(make_font(12, 700, spacing=1.0))
        self.new_button.clicked.connect(self.create_note)
        header.addWidget(self.new_button)

        self.back_button = QPushButton("BACK TO STUDY", self)
        self.back_button.setObjectName("studyMenuButton")
        self.back_button.setFont(make_font(12, 700, spacing=0.8))
        self.back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(self.back_button)
        return header

    def _build_browser(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("studyTelemetryCard")
        root = QVBoxLayout(panel)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(10)

        heading = QLabel("SAVED NOTES", panel)
        heading.setObjectName("studySectionHeading")
        heading.setFont(make_font(12.5, 700, spacing=1.4))
        root.addWidget(heading)

        self.note_list = QListWidget(panel)
        self.note_list.setObjectName("studyNoteList")
        self.note_list.setAccessibleName("Saved study notes")
        self.note_list.currentRowChanged.connect(lambda _row: self._sync_actions())
        self.note_list.itemDoubleClicked.connect(lambda _item: self.open_selected())
        root.addWidget(self.note_list, 1)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.open_button = QPushButton("OPEN", panel)
        self.open_button.setObjectName("studyDurationButton")
        self.open_button.setFont(make_font(12, 700, spacing=0.8))
        self.open_button.clicked.connect(self.open_selected)
        self.refresh_button = QPushButton("REFRESH", panel)
        self.refresh_button.setObjectName("studyDurationButton")
        self.refresh_button.setFont(make_font(12, 700, spacing=0.8))
        self.refresh_button.clicked.connect(self.refresh)
        self.archive_button = QPushButton("ARCHIVE", panel)
        self.archive_button.setObjectName("studyDurationButton")
        self.archive_button.setFont(make_font(12, 700, spacing=0.8))
        self.archive_button.clicked.connect(self.archive_selected)
        actions.addWidget(self.open_button)
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.archive_button)
        actions.addStretch(1)
        root.addLayout(actions)

        self.status_label = QLabel("", panel)
        self.status_label.setObjectName("studyTelemetryName")
        self.status_label.setFont(make_font(11.5, 600))
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        return panel

    def _build_editor_host(self) -> QFrame:
        host = QFrame(self)
        host.setObjectName("studySetupCard")
        root = QVBoxLayout(host)
        root.setContentsMargins(22, 22, 22, 22)
        root.setSpacing(10)
        heading = QLabel("NOTE", host)
        heading.setObjectName("studySectionHeading")
        heading.setFont(make_font(12.5, 700, spacing=1.4))
        root.addWidget(heading)
        # The real NotesWorkspace is embedded, not re-implemented.  It keeps
        # its own save-state label, structured block editors and paste guard.
        self._workspace.setParent(host)
        root.addWidget(self._workspace, 1)
        return host

    PANEL_STYLE: Final = """
    QListWidget#studyNoteList {
        background: %(raised)s; color: %(text)s;
        border: 1px solid %(border)s; border-radius: 10px; padding: 6px;
    }
    QListWidget#studyNoteList::item {
        color: %(text)s; padding: 7px 8px; border-radius: 7px;
    }
    QListWidget#studyNoteList::item:selected {
        background: %(cyan)s; color: %(base)s;
    }
    """

    def _apply_panel_style(self) -> None:
        from UI_THEMES.theme import DEFAULT_THEME

        self.setStyleSheet(
            self.PANEL_STYLE
            % {
                "base": DEFAULT_THEME.window_background,
                "raised": DEFAULT_THEME.surface_soft,
                "border": DEFAULT_THEME.border,
                "text": DEFAULT_THEME.text_primary,
                "cyan": DEFAULT_THEME.cyan,
            }
        )

    # -- browser ----------------------------------------------------------

    def activate(self) -> None:
        """Entering Notes: list what the store actually holds."""

        self.refresh()

    def refresh(self) -> None:
        """Re-list persisted notes.  Metadata only; no content is read."""

        self.note_list.clear()
        self._summaries = []
        lister = getattr(self._store, "list_notes", None)
        if not callable(lister):
            self._set_status("No note store is connected.")
            self._sync_actions()
            return
        try:
            summaries = tuple(lister())
        except Exception as exc:                # noqa: BLE001 - shown, not hidden
            self._set_status(f"Could not list saved notes: {exc}")
            self._sync_actions()
            return
        for summary in summaries:
            links = []
            if getattr(summary, "linked_study_block_id", ""):
                links.append("Study")
            if getattr(summary, "linked_plan_id", ""):
                links.append("Plan")
            suffix = f" · {' + '.join(links)} linked" if links else ""
            self.note_list.addItem(
                QListWidgetItem(
                    f"{summary.title}\n"
                    f"{summary.note_kind.value} · updated "
                    f"{_clock_text(summary.updated_at_utc)}{suffix}"
                )
            )
            self._summaries.append(summary)
        if not self._summaries:
            self.note_list.addItem(QListWidgetItem("No saved notes yet."))
        self._set_status(f"{len(self._summaries)} saved note(s).")
        self._sync_actions()

    def _selected_summary(self):
        row = self.note_list.currentRow()
        if 0 <= row < len(self._summaries):
            return self._summaries[row]
        return None

    def _sync_actions(self) -> None:
        selected = self._selected_summary() is not None
        self.open_button.setEnabled(selected)
        self.archive_button.setEnabled(selected)

    # -- note lifecycle ---------------------------------------------------

    def create_note(
        self,
        *,
        title: str = "Untitled Note",
        study_block_id: str = "",
        plan_id: str = "",
        plan_block_id: str = "",
        task: str = "",
    ) -> bool:
        """Create one note through the existing workspace contract."""

        try:
            self._workspace.new_note(
                title=title,
                linked_study_block_id=str(study_block_id),
                linked_plan_id=str(plan_id),
                linked_plan_block_id=str(plan_block_id),
                linked_task=str(task),
            )
        except Exception as exc:                # noqa: BLE001 - honest failure
            self._set_status(f"Could not create the note: {exc}")
            return False
        self._set_status("New note created.")
        self.refresh()
        return True

    def open_selected(self) -> bool:
        summary = self._selected_summary()
        if summary is None:
            return False
        return self.open_note(summary.note_id)

    def open_note(self, note_id: str) -> bool:
        """Load the AUTHORITATIVE current revision and open it."""

        loader = getattr(self._store, "load_note", None)
        if not callable(loader):
            self._set_status("No note store is connected.")
            return False
        try:
            document = loader(str(note_id))
        except Exception as exc:                # noqa: BLE001 - honest failure
            self._set_status(f"Could not open that note: {exc}")
            self.refresh()
            return False
        if not self._workspace.open_document(document):
            # The session refused, usually because the current note still had
            # unsaved work it could not drain.  Nothing is pretended here.
            self._set_status("The current note could not be saved; not switching.")
            return False
        self._set_status(f"Opened {document.title}.")
        return True

    def archive_selected(self) -> bool:
        """Archive one stored note, protected by its durable revision."""

        summary = self._selected_summary()
        if summary is None:
            return False
        archiver = getattr(self._store, "archive_note", None)
        loader = getattr(self._store, "load_note", None)
        if not callable(archiver) or not callable(loader):
            self._set_status("Archiving is not available.")
            return False
        try:
            # The expected revision comes from durable truth, not from a row
            # this panel painted earlier.
            current = loader(str(summary.note_id))
            archiver(
                str(summary.note_id),
                expected_revision=int(current.revision_number),
            )
        except Exception as exc:                # noqa: BLE001 - honest failure
            self._set_status(f"Not archived: {exc}")
            self.refresh()
            return False
        self._set_status(f"Archived {summary.title}.")
        self.refresh()
        return True

    # -- linkage (metadata only) ------------------------------------------

    def link_current_study(self, study_block_id: str, task: str = "") -> bool:
        """Associate the open note with a Study block.  Metadata only."""

        if not str(study_block_id):
            self._set_status("No Study block to link.")
            return False
        try:
            self._workspace.link_current_study(str(study_block_id), str(task))
        except Exception as exc:                # noqa: BLE001 - honest failure
            self._set_status(f"Could not link the Study block: {exc}")
            return False
        self._set_status("Linked to the current Study block.")
        self.refresh()
        return True

    def link_current_plan(self, plan_id: str, plan_block_id: str = "") -> bool:
        """Associate the open note with a Planner block.  Metadata only."""

        if not str(plan_id):
            self._set_status("No plan to link.")
            return False
        try:
            self._workspace.link_current_plan(str(plan_id), str(plan_block_id))
        except Exception as exc:                # noqa: BLE001 - honest failure
            self._set_status(f"Could not link the plan: {exc}")
            return False
        self._set_status("Linked to the selected planner block.")
        self.refresh()
        return True

    # -- navigation / lifetime --------------------------------------------

    def save_state(self) -> object:
        """The session's own save state.  Never a guess made here."""

        return self._workspace._session.snapshot().save_state

    def prepare_to_leave(self, *, timeout: float = 2.0) -> bool:
        return bool(self._workspace.prepare_to_leave(timeout=timeout))

    def shutdown(self, *, timeout: float = 2.0) -> bool:
        return bool(self._workspace.shutdown(timeout=timeout))

    def _set_status(self, message: str) -> None:
        text = " ".join(str(message).split())[:240]
        self.status_label.setText(text)
        self.status_label.setToolTip(text)

    def status_text(self) -> str:
        return self.status_label.text()
class StudyView(QWidget):
    """The complete Study Mode page used by the Control Station launcher."""

    #: Approved STUDY state -> pill tone mapping.  Presentation only: the tone
    #: follows the Study state the backend already published and nothing else.
    #: States absent from this table (COMPLETED, SHUTDOWN) keep the muted
    #: default rather than being given an invented colour.
    STATE_TONES: Final = {
        StudyState.EMPTY: "muted",
        StudyState.READY: "cyan",
        StudyState.ACTIVE: "green",
        StudyState.PAUSED: "amber",
    }

    ready = pyqtSignal()
    #: Every sensitive Study request carries the identity the user was looking
    #: at when they pressed it: the (block_id, generation) pair is the
    #: Study generation the command was issued AGAINST, never the name of a
    #: block this view invented.  Monitor revalidates it against current truth.
    prepare_requested = pyqtSignal(
        str, str, int, int, str, int, object, object
    )
    study_action_requested = pyqtSignal(str, str, int)
    break_requested = pyqtSignal(int, str, int)
    #: break_id, COSECANT generation, Study block_id, Study generation.
    return_intent_requested = pyqtSignal(str, int, str, int)
    planner_requested = pyqtSignal()
    menu_action_requested = pyqtSignal(str)

    def __init__(
        self,
        *,
        engine: QObject,
        lifecycle: QObject,
        settings: QObject,
        planner: object | None = None,
        timezone_choices: tuple[str, ...] = (),
        notes_workspace: object | None = None,
        note_store: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("studyModePage")
        self.setAccessibleName("COSECANT Study Mode")
        self._engine = engine
        self._lifecycle = lifecycle
        self._settings = settings
        self._planner = planner
        self._timezone_choices = tuple(timezone_choices)
        self._notes_workspace = notes_workspace
        self._note_store = note_store
        self._state = StudyViewState(None, None, None)
        self._monitoring_active = False

        # The Study page owns one internal stack.  Planner is a CHILD SURFACE
        # of Study, not an eighth Control Station page and not a second
        # window: switching between them is presentation only and touches no
        # Study or COSECANT runtime state.
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = QStackedWidget(self)
        self.workspace.setObjectName("studyWorkspaceStack")
        root.addWidget(self.workspace)

        study_page = QWidget(self.workspace)
        study_page.setObjectName("plainBox")
        root = QVBoxLayout(study_page)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(study_page)
        scroll.setObjectName("studyModeScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        body = QWidget(scroll)
        body.setObjectName("studyModeBody")
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(34, 24, 34, 34)
        layout.setSpacing(18)

        # ``.sm-header`` -- title over subtitle, status pills and the menu.
        header = QHBoxLayout()
        header.setSpacing(12)
        heading = QVBoxLayout()
        heading.setSpacing(4)
        title = QLabel("STUDY MODE", body)
        title.setObjectName("studyModeTitle")
        title.setFont(make_font(20, 700, mono=True, spacing=2.0))
        heading.addWidget(title)
        # Anatomy, not branding: StudyRuntime owns the lifecycle and timer,
        # Planner owns planning, and COSECANT owns only planned-break and
        # exact-return regulation.  The subtitle must not hand COSECANT the
        # other organs' jobs.
        subtitle = QLabel("Study Runtime · COSECANT Break-Return Regulation", body)
        subtitle.setObjectName("studyModeSubtitle")
        subtitle.setFont(make_font(12.5, 400))
        heading.addWidget(subtitle)
        header.addLayout(heading)
        header.addStretch(1)
        self.state_pill = QLabel("STUDY · EMPTY", body)
        self.state_pill.setObjectName("studyStatePill")
        self.state_pill.setFont(make_font(11, 800, spacing=1.0))
        self.state_pill.setProperty("tone", self.STATE_TONES[StudyState.EMPTY])
        header.addWidget(self.state_pill)
        self.monitoring_pill = QLabel("MONITORING · OFF", body)
        self.monitoring_pill.setObjectName("studyMonitoringPill")
        self.monitoring_pill.setFont(make_font(11, 800, spacing=1.0))
        self.monitoring_pill.setProperty("tone", "muted")
        header.addWidget(self.monitoring_pill)
        self.menu_button = QToolButton(body)
        self.menu_button.setObjectName("studyMenuButton")
        self.menu_button.setText("STUDY MENU")
        self.menu_button.setFont(make_font(12, 700, spacing=0.8))
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.menu_button.setMenu(self._build_menu())
        header.addWidget(self.menu_button)
        layout.addLayout(header)

        # ``.sm-grid`` -- a 1.3fr timer column beside a 1fr telemetry column.
        top = QHBoxLayout()
        top.setSpacing(18)
        self.timer_card = StudyTimerCard(body)
        top.addWidget(self.timer_card, 13)

        side = QVBoxLayout()
        side.setSpacing(18)
        self.telemetry = StudyTelemetryPanel(body)
        self.resource_intent = ResourceIntentTelemetryPanel(body)
        side.addWidget(self.telemetry)
        side.addWidget(self.resource_intent)
        side.addStretch(1)
        top.addLayout(side, 10)
        layout.addLayout(top)
        layout.addStretch(1)

        self.workspace.addWidget(study_page)
        self._study_page = study_page

        # The Planner child surface.  It exists only when a planner authority
        # was supplied; without one the Study page behaves exactly as before.
        self.planner_panel: StudyPlannerPanel | None = None
        if self._planner is not None:
            planner_host = QWidget(self.workspace)
            planner_host.setObjectName("plainBox")
            planner_root = QVBoxLayout(planner_host)
            planner_root.setContentsMargins(0, 0, 0, 0)
            planner_scroll = QScrollArea(planner_host)
            planner_scroll.setObjectName("studyModeScroll")
            planner_scroll.setWidgetResizable(True)
            planner_scroll.setFrameShape(QFrame.Shape.NoFrame)
            planner_root.addWidget(planner_scroll)
            planner_body = QWidget(planner_scroll)
            planner_body.setObjectName("studyModeBody")
            planner_scroll.setWidget(planner_body)
            planner_layout = QVBoxLayout(planner_body)
            planner_layout.setContentsMargins(34, 24, 34, 34)
            planner_layout.setSpacing(18)
            self.planner_panel = StudyPlannerPanel(
                planner=self._planner,
                timezone_choices=self._timezone_choices,
                configured_timezone=self._configured_timezone(),
                parent=planner_body,
            )
            planner_layout.addWidget(self.planner_panel)
            self.workspace.addWidget(planner_host)
            self._planner_host = planner_host
            self.planner_panel.back_requested.connect(self.show_main_study)
            self.planner_panel.timer_requested.connect(self._on_planner_timer)
            self.planner_requested.connect(self.show_planner)

        # The Notes child surface.  Built only when the launcher supplied the
        # ONE long-lived workspace and the shell's storage facade; without
        # them the Study page is unchanged.
        self.notes_panel: StudyNotesPanel | None = None
        if self._notes_workspace is not None and self._note_store is not None:
            notes_host = QWidget(self.workspace)
            notes_host.setObjectName("plainBox")
            notes_root = QVBoxLayout(notes_host)
            notes_root.setContentsMargins(34, 24, 34, 34)
            notes_root.setSpacing(18)
            self.notes_panel = StudyNotesPanel(
                workspace=self._notes_workspace,
                store=self._note_store,
                parent=notes_host,
            )
            notes_root.addWidget(self.notes_panel)
            self.workspace.addWidget(notes_host)
            self._notes_host = notes_host
            self.notes_panel.back_requested.connect(self.show_main_study)
            self.menu_action_requested.connect(self._on_menu_action)

        # The card knows which button was pressed; only this view holds the
        # published Study identity, so identity is bound here and nowhere else.
        self.timer_card.prepare_requested.connect(self._emit_prepare)
        self.timer_card.action_requested.connect(self._emit_study_action)
        self.timer_card.break_requested.connect(self._emit_break)
        self._connect_engine_signals()
        self._connect_dispatcher()
        QTimer.singleShot(0, self.ready.emit)

    # -- identity-bound command emission -----------------------------------

    def _expected_study_identity(self) -> tuple[str, int]:
        """The Study identity currently on screen, read at the click.

        No identity is generated here.  Before any Study snapshot has been
        published there is nothing to name, and the empty identity is sent so
        the authority can apply its own rule rather than a UI guess.
        """

        study = self._state.study
        if study is None:
            return "", 0
        return str(study.block_id), int(study.generation)

    # -- Study workspace navigation (presentation only) --------------------
    #
    # Switching between MAIN STUDY and STUDY PLANNER changes which child
    # widget is visible and nothing else.  No runtime is started, stopped,
    # reset or re-created, so Study lifecycle and COSECANT physiology are
    # untouched by moving around inside the Study page.

    def _configured_timezone(self) -> str:
        """The clock's configured zone, IF it is usable for recurrence.

        ``"local"`` and any unresolvable name are returned as empty.  The
        clock may fall back to a fixed UTC offset for display, but a fixed
        offset carries no daylight-saving transitions and must never become
        planner truth -- the panel asks the user for a named zone instead.
        """

        snapshot = getattr(self._settings, "snapshot", None)
        if not callable(snapshot):
            return ""
        try:
            configured = str(getattr(snapshot(), "clock_timezone", "") or "")
        except Exception:
            return ""
        return configured if timezone_available(configured) else ""

    def show_main_study(self) -> None:
        self.workspace.setCurrentIndex(0)

    def show_planner(self) -> None:
        if self.planner_panel is None:
            return
        self.workspace.setCurrentWidget(self._planner_host)
        self.planner_panel.activate()

    def show_notes(self) -> None:
        """Open the Notes child surface and list persisted notes."""

        if self.notes_panel is None:
            return
        self.workspace.setCurrentWidget(self._notes_host)
        self.notes_panel.activate()

    def _on_menu_action(self, name: str) -> None:
        """Route the one menu key this view owns; others pass through."""

        if str(name) == "study_notes":
            self.show_notes()

    def open_note_for_current_study(self) -> bool:
        """Create a note LINKED to the Study block currently on screen.

        Linkage is metadata: it records that the note belongs with that block.
        No note content is ever read back into Study, Resource Intent or any
        other authority.
        """

        if self.notes_panel is None:
            return False
        study = self._state.study
        if study is None or not study.block_id:
            self.notes_panel._set_status("No prepared Study block to link.")
            return False
        self.show_notes()
        return self.notes_panel.create_note(
            title=f"{study.subject or 'Study'} — notes",
            study_block_id=str(study.block_id),
            task=str(study.task or ""),
        )

    def open_note_for_planner_block(self, block: object) -> bool:
        """Create a note LINKED to one planner block.  Metadata only."""

        if self.notes_panel is None or self._planner is None or block is None:
            return False
        self.show_notes()
        return self.notes_panel.create_note(
            title=f"{getattr(block, 'subject', 'Plan')} — notes",
            plan_id=str(getattr(self._planner, "plan_id", "")),
            plan_block_id=str(getattr(block, "block_id", "")),
            task=str(getattr(block, "task", "")),
        )

    def _on_planner_timer(self, preparation: object) -> None:
        """SET STUDY TIMER arrived from the Planner panel.

        The B7 seam owns the Protected Red recheck, the one-use validation and
        the Study identity fence.  On success the user is returned to MAIN
        STUDY so they can see the READY card and press START themselves --
        this never presses it for them.
        """

        if self._planner is None or self.planner_panel is None:
            return
        reason = self.confirm_planner_timer(self._planner, preparation)
        if reason:
            self.planner_panel._set_status(f"Timer not set: {reason}")
            self.planner_panel.render()
            return
        self.planner_panel._set_status(
            "Study timer prepared. Press START on the Study card to begin."
        )
        self.show_main_study()

    def _protected_red_active(self) -> bool:
        """Ask the engine whether Protected Red holds RIGHT NOW.

        Fails closed: if the fact cannot be obtained, the answer is "yes".  A
        greyed-out button is a picture of the past, so every Red-sensitive
        action rechecks at command time rather than trusting its own paint.
        """

        probe = getattr(self._engine, "is_protected_red_active", None)
        if not callable(probe):
            return False
        try:
            return bool(probe())
        except Exception:
            return True

    def confirm_planner_timer(self, planner: object, preparation: object) -> str:
        """SET STUDY TIMER -- turn one Planner preparation into Study PREPARE.

        This is the whole Planner -> Study seam, and it PREPARES ONLY.  It does
        not start Study, does not touch COSECANT, and does not classify
        anything; the user still presses START on the Study card afterwards.

        Order is deliberate:

            Protected Red recheck   (before the token is spent, so a Red
                                     refusal does not burn a one-use
                                     preparation the user must re-make)
            one-use consumption     (Planner re-verifies block identity and
                                     version at this exact moment)
            Study identity fence    (the same expected block_id/generation
                                     pair every other sensitive action sends)
            Controller.prepare_study via prepare_requested

        Returns "" when the request was dispatched, otherwise a short reason.
        """

        if self._protected_red_active():
            restore = getattr(self._engine, "request_protected_red_restore", None)
            if callable(restore):
                restore()
            return "protected_red"

        result = planner.consume_preparation(preparation)
        if not getattr(result, "accepted", False):
            return str(getattr(result, "reason", "preparation_refused"))
        ready = result.preparation

        block_id, generation = self._expected_study_identity()
        # Keywords are deliberately EMPTY.  Planner holds no user-declared
        # keyword fields, and inferring them from subject or task text would
        # be a second, hidden classification route.  The Study card's own
        # keyword inputs remain the only place the user declares them.
        self.prepare_requested.emit(
            str(ready.subject),
            str(ready.task),
            int(ready.study_seconds),
            int(ready.selected_break_seconds),
            block_id,
            generation,
            (),
            (),
        )
        return ""

    def _emit_prepare(
        self,
        subject: str,
        task: str,
        planned_seconds: int,
        break_seconds: int,
        keywords: object,
        important_keywords: object,
    ) -> None:
        block_id, generation = self._expected_study_identity()
        self.prepare_requested.emit(
            subject,
            task,
            planned_seconds,
            break_seconds,
            block_id,
            generation,
            keywords,
            important_keywords,
        )

    def _emit_study_action(self, action: str) -> None:
        block_id, generation = self._expected_study_identity()
        self.study_action_requested.emit(str(action), block_id, generation)

    def _emit_break(self, selected_break_seconds: int) -> None:
        block_id, generation = self._expected_study_identity()
        self.break_requested.emit(
            int(selected_break_seconds), block_id, generation
        )

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setObjectName("studyMenu")
        planner = menu.addAction("Study Planner")
        planner.triggered.connect(self.planner_requested.emit)
        menu.addSeparator()
        for label, key in (
            ("Study Notes", "study_notes"),
            ("Timer preferences", "timer_preferences"),
            ("Study information", "study_information"),
        ):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, name=key: self.menu_action_requested.emit(name)
            )
        return menu

    def _connect_engine_signals(self) -> None:
        resource_signal = getattr(
            self._engine, "resource_intent_live_status_changed", None
        )
        if resource_signal is not None:
            resource_signal.connect(self.set_resource_intent)

    def _connect_dispatcher(self) -> None:
        with _DISPATCHER_LOCK:
            dispatcher = _DISPATCHER
        if dispatcher is not None:
            dispatcher.return_intent_requested.connect(
                self.return_intent_requested.emit
            )

    @pyqtSlot(object)
    def _on_study_payload(self, payload: object) -> None:
        # Exact objects only.  Legacy mappings are deliberately not guessed.
        if payload is None:
            self.reset_presentation_epoch()
        elif isinstance(payload, StudyViewState):
            self.set_state(payload)
        elif isinstance(payload, StudySnapshot):
            self.set_study_snapshot(payload)
        elif isinstance(payload, CosecantSnapshot):
            self.set_cosecant_snapshot(payload)

    def reset_presentation_epoch(self) -> None:
        """Start a NEW Core Engine presentation epoch.

        ``ControlStationController._prepare_new_session`` publishes ``None`` on
        the Study presentation channel when it builds a new engine session.
        Each session creates fresh Study and COSECANT authorities whose
        generations legitimately restart, so the ordering baseline this view
        holds must be dropped -- otherwise the new session's genuine truth
        would be refused as stale by the very guards that protect ordering
        WITHIN a session.

        Presentation only.  It clears held snapshots, repaints the empty
        surface and clears the popup's baseline.  It calls no runtime, reads
        no clock, classifies nothing, mints no identity and changes no engine
        state.  Ordering rules inside a session are untouched.
        """

        self._state = StudyViewState(None, None, None)
        self._render()
        reset_continuity_presentation()

    @pyqtSlot(object)
    def render(self, payload: object) -> None:
        """Launcher-facing exact-state render contract."""

        self._on_study_payload(payload)

    def set_state(self, state: StudyViewState) -> None:
        if not isinstance(state, StudyViewState):
            raise TypeError("state must be a StudyViewState")
        self._state = state
        self._render()

    def set_study_snapshot(self, snapshot: StudySnapshot) -> None:
        if not isinstance(snapshot, StudySnapshot):
            raise TypeError("snapshot must be a StudySnapshot")
        # Ordering only: an already-superseded Study publication must not
        # repaint over the newer one this surface has already accepted.
        if not _study_supersedes(snapshot, self._state.study):
            return
        self.set_state(
            StudyViewState(snapshot, self._state.cosecant, self._state.resource_intent)
        )

    def set_cosecant_snapshot(self, snapshot: CosecantSnapshot) -> None:
        if not isinstance(snapshot, CosecantSnapshot):
            raise TypeError("snapshot must be a CosecantSnapshot")
        if not _cosecant_supersedes(snapshot, self._state.cosecant):
            return
        self.set_state(
            StudyViewState(self._state.study, snapshot, self._state.resource_intent)
        )
        request_continuity_popup(snapshot)

    @pyqtSlot(object)
    def set_resource_intent(self, live: object) -> None:
        if live is not None and not isinstance(live, ResourceIntentLiveView):
            return
        self.set_state(
            StudyViewState(self._state.study, self._state.cosecant, live)
        )

    def _render(self) -> None:
        self.timer_card.render(self._state.study, self._state.cosecant)
        self.telemetry.render(self._state.study, self._state.cosecant)
        self.resource_intent.render(self._state.resource_intent)
        # The pill reads the published Study state only -- never a timer
        # value, never a button's enabled-ness, never COSECANT.
        study_state = (
            self._state.study.state if self._state.study else StudyState.EMPTY
        )
        self.state_pill.setText(f"STUDY · {study_state.value}")
        self.state_pill.setProperty(
            "tone", self.STATE_TONES.get(study_state, "muted")
        )
        restyle(self.state_pill)

    def refresh(self) -> None:
        """Re-render the authoritative snapshots already held, then report ready.

        Navigation's readiness contract, and nothing more.  This page is fed
        published engine snapshots continuously, including while it is hidden,
        so re-entering Study Mode needs a repaint and a readiness fact -- not a
        second data authority.

        It deliberately does not start Study, query Browser, classify a
        resource, advance a COSECANT deadline, touch a timer or manufacture a
        snapshot.  ``ready`` is emitted on the next event-loop turn, the same
        way the constructor emits it, so NavigationController keeps ownership
        of readiness, the timeout and page activation.
        """

        self._render()
        QTimer.singleShot(0, self.ready.emit)

    def prepare_to_leave_async(self, completed) -> bool:
        """Navigation gate: drain accepted Notes work before leaving Study.

        Study presentation still owns no unsaved runtime truth, but Notes now
        does.  An accepted edit waiting on autosave must reach persistence
        before the page changes, so a bounded flush runs first and a FAILED
        flush KEEPS THE USER HERE rather than quietly losing their work.
        """

        if not callable(completed):
            return False
        if self.notes_panel is None:
            QTimer.singleShot(0, lambda: completed(True))
            return True
        try:
            drained = self.notes_panel.prepare_to_leave(timeout=2.0)
        except Exception:                       # noqa: BLE001 - fail closed
            drained = False
        if not drained:
            self.notes_panel._set_status(
                "Your note could not be saved, so Study Mode stayed open."
            )
        QTimer.singleShot(0, lambda: completed(bool(drained)))
        return True

    def set_navigation_enabled(self, enabled: bool) -> None:
        self.setEnabled(bool(enabled))

    def set_monitoring_active(self, active: bool) -> None:
        """Show engine lifecycle status without changing Study authority."""

        self._monitoring_active = bool(active)
        self.monitoring_pill.setText(
            "MONITORING · ON" if self._monitoring_active else "MONITORING · OFF"
        )
        self.monitoring_pill.setProperty(
            "tone", "green" if self._monitoring_active else "muted"
        )
        restyle(self.monitoring_pill)


def _return_status(cosecant: CosecantSnapshot) -> str:
    """Describe return progress from published fields only.

    Privacy-safe by construction: it reports THAT an intended target exists and
    how far COSECANT's own confirmation has run.  The opaque resource token is
    never rendered, and no comparison against the live resource happens here --
    exact-return matching belongs to the nucleus.
    """

    if cosecant.return_confirmed:
        return "CONFIRMED"
    if cosecant.state is CosecantState.RETURN_CONFIRMING:
        return f"CONFIRMING · {cosecant.confirmation_elapsed_seconds:.0f}s"
    if cosecant.intended_return_target is None:
        return "—"
    return "TARGET FROZEN"


def _duration(seconds: float | int | None) -> str:
    if seconds is None:
        return "—"
    whole = max(0, int(float(seconds)))
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _clock_text(value: str | None) -> str:
    """Show the wall-clock portion of an already-published UTC timestamp.

    Formatting only.  No timezone is converted, no time is computed and no
    missing value is invented -- an unrecognised stamp is shown exactly as
    the snapshot published it.

    The ``UTC`` suffix is not decoration.  ``StudySnapshot.ends_at_wall_time_utc``
    is published in UTC, so a bare ``14:37`` would read as the reader's own
    clock and silently misstate when the block ends.  Until local presentation
    is deliberately wired to the timezone settings, the unit stays visible.
    """

    if not value:
        return "--:--"
    text = str(value)
    if "T" in text:
        clock = text.split("T", 1)[1]
        if len(clock) >= 5 and clock[2] == ":":
            return f"{clock[:5]} UTC"
    return text


__all__ = [
    "ContinuityPopup",
    "ResourceIntentTelemetryPanel",
    "StudyTelemetryPanel",
    "StudyTimerCard",
    "StudyView",
    "StudyViewState",
    "VIEW_SCHEMA_VERSION",
    "install_popup_dispatcher",
    "request_continuity_popup",
    "reset_continuity_presentation",
]
