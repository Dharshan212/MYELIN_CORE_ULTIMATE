"""Chapter 5 -- Results & Discussion: the thesis-style presentation layer
that interprets and presents Chapter 3's certified analysis.

The page consumes only an explicit in-memory Chapter 3 transfer receipt.  It
formats the exact immutable package without rereading evidence or
recalculating metrics, and it never generates a report itself: EXPORT PDF
(Phase 5) delegates entirely to the frozen ``SCIENCE_LAB.report`` generator,
passing it the exact current receipt this module already holds.

Import boundary (same one-directional composition every Science Lab
chapter module already uses): this module may import PyQt6,
UI_THEMES.theme, and the frozen ``SCIENCE_LAB.report.generate_report_pdf``
entry point (Phase 5 EXPORT PDF only -- never ``generate_dev_preview_pdf``
or ``_build_dev_fixtures``).  It must NOT import CORE_ENGINE, SINE, MINE,
COSINE, MIRL, COSECANT_STUDY_MODE, PERSISTENCE, sqlite3, or SCIENCE_LAB.lab
(lab.py hosts this module; this module never reaches back into lab.py).  It
also does not import SCIENCE_LAB.chapter3_view or SCIENCE_LAB.report_model
directly: Chapter 5 receives the certified package through
``SCIENCE_LAB.handoff``, never by reaching into Chapter 3's widgets, and it
hands that receipt to ``generate_report_pdf`` without inspecting the render
model itself.

Chapter 5 history addition (Chief's 20260917 instruction): this module also
imports the plain, frozen ``HistoryEntry``/``HistoryReconstruction`` data
shapes from ``SCIENCE_LAB.history`` for type hints on the widgets below --
never any function from that module.  This widget performs no historical
read of its own: ``SHOW HISTORY``/row selection only emit
``history_requested``/``history_experiment_selected``; the application host
(the only layer permitted to reach ``SCIENCE_LAB.history``'s read-only
PERSISTENCE-backed functions) calls back in with the already-computed
result via ``render_history_list``/``render_history_result``.  A
successfully reconstructed historical package is exported exactly like the
current receipt -- straight to the same frozen ``generate_report_pdf`` --
but is never written into ``_current_receipt`` and never labelled
TRANSFERRED; it stays a clearly separate, explicitly labelled
HISTORICAL RECONSTRUCTION preview, and the top-right EXPORT PDF/current
receipt are untouched by anything in the history dialog.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from UI_THEMES.theme import FEED_BADGE_COSINE, make_font
from SCIENCE_LAB.analysis import (
    AVAILABLE,
    CERTIFIED,
    NO_EVIDENCE,
    UNAVAILABLE,
    Chapter3Metric,
    Chapter3ResultPackage,
    Chapter3TimelineEvent,
    CertifiedPattern,
    SourceCoverage,
    WholeMyelinRow,
)
from SCIENCE_LAB.handoff import Chapter3TransferReceipt
from SCIENCE_LAB.report import generate_report_pdf

if TYPE_CHECKING:
    # Type hints only -- never imported at runtime, so this module stays
    # free of any transitive PERSISTENCE/sqlite dependency (SCIENCE_LAB.
    # history imports PERSISTENCE.storage at module load).  The matching
    # runtime literals ("CERTIFIED" / "HISTORICAL RECONSTRUCTION") are
    # duplicated as local constants below instead of imported.
    from SCIENCE_LAB.history import HistoryEntry, HistoryReconstruction

#: Must equal SCIENCE_LAB.history.HISTORY_CERTIFIED and RECONSTRUCTION_LABEL
#: exactly -- duplicated as plain literals rather than imported so this
#: module never carries a runtime dependency on SCIENCE_LAB.history (and
#: therefore PERSISTENCE) at all; see the TYPE_CHECKING import above.
_HISTORY_CERTIFIED: Final = "CERTIFIED"
_RECONSTRUCTION_LABEL: Final = "HISTORICAL RECONSTRUCTION"

#: The seven Results & Discussion sections (Chapter 3 -> Chapter 5 transfer
#: spec section 7.1).  Presentation sections only, not independent analysis
#: engines -- each renders the honest dummy state until Chapter 3 results
#: are transferred (Phase 2).
_SECTIONS: Final = (
    ("1", "RESULTS OVERVIEW", "SUMMARY",
     "Awaiting certified analysis from Chapter 3."),
    ("2", "BEHAVIOURAL RESULTS", "BEHAVIOURAL EVIDENCE",
     "Behavioral results will appear after experiment analysis is complete."),
    ("3", "RESULT PATTERNS", "TRENDS & INSIGHTS",
     "Patterns and trends will be extracted from Chapter 3 results."),
    ("4", "DISCUSSION", "INTERPRETATION",
     "Discussion will appear after experiment analysis is complete."),
    ("5", "ALTERNATIVE EXPLANATIONS", "CRITICAL ANALYSIS",
     "Alternative explanations will be considered once results are available."),
    ("6", "INTERPRETIVE SUMMARY", "THESIS SUMMARY",
     "A coherent summary will be generated based on the certified results from Chapter 3."),
    ("7", "LIMITATIONS IN INTERPRETATION", "STUDY LIMITATIONS",
     "No result is interpreted until Chapter 3 finalizes the evidence."),
)

_FIXED_INTERPRETATION_BOUNDARY: Final = (
    "These results describe software-observed behavioral evidence and should not "
    "be interpreted as direct measurement of neural state, neurotransmitter "
    "activity, diagnosis, or subjective mental state."
)


@dataclass(frozen=True, slots=True)
class Chapter5Presentation:
    """Deterministic formatting of one transferred package, retaining truth."""

    package: Chapter3ResultPackage
    experiment_id: str
    parent_session_id: int
    source_coverage: tuple[SourceCoverage, ...]
    behavioral_results: tuple[Chapter3Metric, ...]
    whole_myelin_summary: tuple[WholeMyelinRow, ...]
    result_patterns: tuple[CertifiedPattern, ...]
    results_overview_lines: tuple[str, ...]
    behavioral_result_lines: tuple[str, ...]
    result_pattern_lines: tuple[str, ...]
    discussion_lines: tuple[str, ...]
    alternative_explanation_lines: tuple[str, ...]
    interpretive_summary_lines: tuple[str, ...]
    limitation_lines: tuple[str, ...]


def _metric_line(metric: Chapter3Metric) -> str:
    if metric.status == AVAILABLE:
        rendered = f"{metric.value} {metric.unit}".strip()
    elif metric.status == NO_EVIDENCE:
        rendered = "No evidence"
    else:
        rendered = "Unavailable"
    return f"{metric.label}: {rendered} [{metric.status}] — {metric.reason}"


def _whole_line(row: WholeMyelinRow) -> str:
    if row.status == AVAILABLE:
        rendered = str(row.count)
    elif row.status == NO_EVIDENCE:
        rendered = "No evidence"
    else:
        rendered = "Unavailable"
    return f"{row.source.replace('_', ' ')} — {row.label}: {rendered} [{row.status}]"


def build_chapter5_presentation(
    receipt: Chapter3TransferReceipt,
) -> Chapter5Presentation:
    """Validate and format package truth before any visible widget mutation."""

    if not isinstance(receipt, Chapter3TransferReceipt):
        raise TypeError("Chapter 5 requires a Chapter3TransferReceipt")
    package = receipt.package
    if (
        not isinstance(package, Chapter3ResultPackage)
        or package.analysis_status != CERTIFIED
        or receipt.experiment_id != package.experiment_id
        or receipt.parent_session_id != package.parent_session_id
    ):
        raise ValueError("Chapter 5 transfer receipt is inconsistent")

    resource = tuple(
        row for row in package.source_coverage if row.source_system == "RESOURCE_INTENT"
    )
    if len(resource) != 1 or (
        resource[0].status != UNAVAILABLE
        or resource[0].reason != "no_durable_event_identity"
        or resource[0].item_count is not None
    ):
        raise ValueError("Resource Intent coverage truth changed during transfer")

    available_metric_count = sum(
        1 for metric in package.key_metrics if metric.status == AVAILABLE
    )
    overview = (
        f"Experiment ID: {package.experiment_id}",
        f"Parent Session ID: {package.parent_session_id}",
        "Analysis: CERTIFIED",
        "Transfer: TRANSFERRED",
        f"Experiment window: [{package.experiment_start_monotonic_ns}, "
        f"{package.experiment_end_monotonic_ns}) monotonic ns",
        f"Available metrics: {available_metric_count} of {len(package.key_metrics)}",
        f"Certified patterns: {len(package.certified_patterns)}",
        "The selected experiment is a bounded subset of the full parent session.",
        "Source coverage: "
        + "; ".join(
            f"{row.source_system.replace('_', ' ')}={row.status}"
            for row in package.source_coverage
        ),
        "Whole-MYELIN full-session summary:",
        *tuple(_whole_line(row) for row in package.whole_myelin_summary),
    )
    behavioral = tuple(_metric_line(metric) for metric in package.key_metrics)
    patterns = tuple(
        f"{pattern.label}: {pattern.description} [{pattern.code}]"
        for pattern in package.certified_patterns
    ) or ("No certified patterns were present in the transferred package.",)

    metrics_by_code = {metric.code: metric for metric in package.key_metrics}
    discussion: list[str] = []
    verified = metrics_by_code.get("verified_returns")
    if verified is not None and verified.status == AVAILABLE:
        discussion.append(
            f"The selected experiment contained {verified.value} factually verified "
            "return event(s). This describes observed recovery behavior within the "
            "experiment window and does not establish an explanation for return."
        )
    pattern_codes = {pattern.code for pattern in package.certified_patterns}
    if "RELAPSE_AFTER_VERIFIED_RETURN" in pattern_codes:
        discussion.append(
            "A factual relapse was observed after a verified return in at least one "
            "MIRL episode. This supports treating return and sustained re-engagement "
            "as distinct behavioral events."
        )
    if "MULTIPLE_VERIFIED_RETURNS" in pattern_codes:
        discussion.append(
            "Multiple verified returns occurred during the selected experiment, "
            "indicating repeated recovery events rather than one uninterrupted "
            "behavioral trajectory."
        )
    if any(metric.status == UNAVAILABLE for metric in package.key_metrics):
        discussion.append(
            "Some behavioral quantities remain unavailable because the current "
            "durable evidence does not support a complete certified calculation."
        )
    if not discussion:
        discussion.append(
            "The transferred package contains no additional certified discussion rule."
        )

    alternatives: list[str] = []
    if verified is not None and verified.status == AVAILABLE and verified.value:
        alternatives.append(
            "Software-observed return does not prove subjective attentional recovery."
        )
    normal_break = next(
        (row for row in package.whole_myelin_summary if row.source == "NORMAL_BREAK"),
        None,
    )
    if normal_break is not None and normal_break.status == AVAILABLE and normal_break.count:
        alternatives.append("Recorded breaks may be deliberate and task-compatible.")
    mine = next(
        (row for row in package.whole_myelin_summary if row.source == "MINE"), None
    )
    if mine is not None and mine.status == AVAILABLE and mine.count:
        alternatives.append("Messaging activity may be purposeful rather than distracting.")
    alternatives.append(
        "Missing durable Resource Intent history limits complete task-alignment reconstruction."
    )

    summary = (
        f"Experiment {package.experiment_id} transferred the exact certified Chapter 3 "
        f"package for parent session {package.parent_session_id}.",
        f"Within this experiment, {available_metric_count} of "
        f"{len(package.key_metrics)} metric values were available and "
        f"{len(package.certified_patterns)} certified pattern(s) were retained.",
        "Interpretation is limited to observed or derived software-observed evidence "
        "and the limitations carried by the package.",
    )
    limitations = tuple(dict.fromkeys((*package.limitations, _FIXED_INTERPRETATION_BOUNDARY)))

    return Chapter5Presentation(
        package=package,
        experiment_id=package.experiment_id,
        parent_session_id=package.parent_session_id,
        source_coverage=package.source_coverage,
        behavioral_results=package.key_metrics,
        whole_myelin_summary=package.whole_myelin_summary,
        result_patterns=package.certified_patterns,
        results_overview_lines=overview,
        behavioral_result_lines=behavioral,
        result_pattern_lines=patterns,
        discussion_lines=tuple(discussion),
        alternative_explanation_lines=tuple(alternatives),
        interpretive_summary_lines=summary,
        limitation_lines=limitations,
    )


def _allow_shrink(widget: QWidget) -> None:
    """Let a widget shrink below its natural width instead of forcing the
    ancestor layout's minimum width up with it (same technique every other
    Science Lab chapter module already uses)."""

    policy = widget.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    widget.setSizePolicy(policy)


def _paragraph(text: str, *, role: str | None = None, size: float = 11.5) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    _allow_shrink(label)
    label.setFont(make_font(size, 400))
    if role:
        label.setProperty("role", role)
    return label


class _ExportAction(QFrame):
    """Chapter 5's EXPORT PDF action (Chapter 3 -> Chapter 5 transfer spec
    section 8), anchored beside the page heading.  Production default:
    disabled -- this widget decides nothing about export eligibility itself
    and generates no report.  It only emits ``export_requested`` on click;
    ``Chapter5ResultsView`` (the sole owner of the current certified
    receipt) performs every certification/identity check, owns the save
    dialog, and calls the frozen generator."""

    export_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter5ExportAction")
        # No _allow_shrink here: this frame's own natural width (button +
        # one short helper line) is what the top-right corner should
        # reserve.  Marking it "Ignored" (the technique every other frame
        # in this module uses for long word-wrapped paragraphs) let the
        # sibling text column's stretch factor claim all the width and
        # squeezed this frame -- and therefore the button -- to zero.

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._button = QPushButton("EXPORT PDF")
        self._button.setObjectName("chapter5ExportButton")
        self._button.setFont(make_font(10.5, 700, spacing=0.4))
        self._button.setEnabled(False)
        self._button.setToolTip(
            "Available after Chapter 3 results are transferred and validated."
        )
        self._button.clicked.connect(self.export_requested.emit)
        layout.addWidget(self._button, 0, Qt.AlignmentFlag.AlignRight)

        self._helper = QLabel("Generate a thesis-style report of Chapter 5.")
        self._helper.setObjectName("chapter5ExportHelper")
        self._helper.setWordWrap(True)
        self._helper.setAlignment(Qt.AlignmentFlag.AlignRight)
        _allow_shrink(self._helper)
        self._helper.setFont(make_font(9, 400))
        layout.addWidget(self._helper)

    def show_transferred(self) -> None:
        """Called only after a certified receipt has been successfully
        applied (see ``Chapter5ResultsView._apply_presentation``) -- Phase 4
        report certification is complete, so export is now available for
        this exact receipt."""

        self._button.setEnabled(True)
        helper = "Export the current certified experiment as a MYELIN Report PDF."
        self._helper.setText(helper)
        self._button.setToolTip(helper)


class _SourcePackageStrip(QFrame):
    """Chapter 5's dependency strip (Chapter 3 -> Chapter 5 transfer spec
    section 7): makes the Chapter 3 -> Chapter 5 handoff visible even
    before a transfer has happened.  Renders only the honest "awaiting
    transfer" default -- it holds no package state of its own."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter5SourceStrip")
        self.setAccessibleName("Chapter 3 certified analysis package")
        _allow_shrink(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(20)

        text_column = QVBoxLayout()
        text_column.setSpacing(3)
        source = QLabel("SOURCE: CHAPTER 3 CERTIFIED ANALYSIS PACKAGE")
        source.setObjectName("chapter5SourceLabel")
        source.setProperty("role", "cyan")
        source.setFont(make_font(10, 800, spacing=0.6))
        source.setWordWrap(True)
        _allow_shrink(source)
        text_column.addWidget(source)

        self._body = QLabel("Chapter 5 consumes the final, certified analysis from Chapter 3.")
        self._body.setObjectName("chapter5SourceBody")
        self._body.setWordWrap(True)
        _allow_shrink(self._body)
        self._body.setFont(make_font(9.5, 400))
        text_column.addWidget(self._body)

        layout.addLayout(text_column, 1)
        layout.addWidget(self._build_status_column())
        layout.addWidget(self._build_dependency_column())

    def _build_status_column(self) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        label = QLabel("STATUS")
        label.setObjectName("chapter5ColumnLabel")
        label.setFont(make_font(8.5, 700, spacing=0.6))
        layout.addWidget(label)
        self._status_value = QLabel("Awaiting Chapter 3")
        self._status_value.setObjectName("chapter5StatusValue")
        self._status_value.setFont(make_font(10, 700))
        layout.addWidget(self._status_value)
        return column

    def _build_dependency_column(self) -> QWidget:
        column = QWidget()
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        label = QLabel("DEPENDENCY")
        label.setObjectName("chapter5ColumnLabel")
        label.setFont(make_font(8.5, 700, spacing=0.6))
        layout.addWidget(label)
        value = QLabel("Chapter 3 → Chapter 5")
        value.setObjectName("chapter5DependencyValue")
        value.setFont(make_font(10, 700))
        layout.addWidget(value)
        self._dependency_sub = QLabel("Analysis informs Discussion")
        self._dependency_sub.setObjectName("chapter5DependencySub")
        self._dependency_sub.setFont(make_font(8.5, 400))
        layout.addWidget(self._dependency_sub)
        return column

    def render_presentation(self, presentation: Chapter5Presentation) -> None:
        self._body.setText(
            f"Experiment {presentation.experiment_id} · Parent Session "
            f"{presentation.parent_session_id} · Analysis: CERTIFIED"
        )
        self._status_value.setText("TRANSFERRED")
        self._dependency_sub.setText("Exact certified package retained")


class _ResultsSectionCard(QFrame):
    """One numbered Results & Discussion section (spec section 7.1).

    Reuses the same generic numbered-card language every other Science Lab
    chapter card already uses (``#card`` / ``#chapterCardBadge`` /
    ``#chapterCardBadgeText``) rather than inventing a second card style.
    Renders only the dummy body text it is given; Phase 2 replaces the
    body once a transferred Chapter 3 package exists.
    """

    def __init__(self, number: str, title: str, tag: str, body_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(10)
        badge_frame = QFrame()
        badge_frame.setObjectName("chapterCardBadge")
        badge_frame.setFixedSize(28, 28)
        badge_layout = QVBoxLayout(badge_frame)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_label = QLabel(number)
        badge_label.setObjectName("chapterCardBadgeText")
        badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_label.setFont(make_font(11, 700))
        badge_layout.addWidget(badge_label)
        header.addWidget(badge_frame)

        heading = QLabel(title)
        heading.setWordWrap(True)
        _allow_shrink(heading)
        heading.setFont(make_font(12.5, 700))
        header.addWidget(heading, 1)

        chevron = QLabel("›")
        chevron.setObjectName("chapter5SectionChevron")
        chevron.setFont(make_font(14, 700))
        header.addWidget(chevron, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        dash = QLabel("—")
        dash.setObjectName("chapter5SectionDash")
        dash.setFont(make_font(11, 700))
        layout.addWidget(dash)

        self._body = _paragraph(body_text, role="muted", size=11)
        layout.addWidget(self._body)

        tag_label = QLabel(tag)
        tag_label.setObjectName("chapter5SectionTag")
        tag_label.setFont(make_font(8.5, 700, spacing=0.5))
        layout.addWidget(tag_label, 0, Qt.AlignmentFlag.AlignLeft)

    def set_lines(self, lines: tuple[str, ...]) -> None:
        self._body.setText("\n\n".join(lines))


class _SectionGrid(QFrame):
    """Reflow grid for the seven section cards: four columns above
    ``wide_min_width``, two above ``medium_min_width``, one below it (same
    reflow technique as Chapter 3's own ``_ResponsiveGrid``, kept as a
    local copy here rather than a cross-chapter import -- each Science Lab
    chapter module stays independent)."""

    def __init__(
        self,
        items: list[QWidget],
        *,
        wide_columns: int,
        medium_columns: int,
        narrow_columns: int,
        wide_min_width: int,
        medium_min_width: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chapter5SectionGrid")
        self._items = items
        self._wide_columns = wide_columns
        self._medium_columns = medium_columns
        self._narrow_columns = narrow_columns
        self._wide_min_width = wide_min_width
        self._medium_min_width = medium_min_width
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
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
        if width >= self._wide_min_width:
            columns = self._wide_columns
        elif width >= self._medium_min_width:
            columns = self._medium_columns
        else:
            columns = self._narrow_columns
        self._relayout(columns)


class _BoundaryNote(QFrame):
    """The static research-boundary reminder every Science Lab chapter
    carries (spec section 2): behavioural evidence only, no neural or
    diagnostic claim."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter5BoundaryNote")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        title = QLabel("IMPORTANT NOTE")
        title.setObjectName("chapter5BoundaryTitle")
        title.setProperty("role", "cyan")
        title.setFont(make_font(9.5, 800, spacing=0.6))
        layout.addWidget(title)

        layout.addWidget(
            _paragraph(
                "Chapter 5 interprets behavioural outcomes from controlled experiments. "
                "It does not infer neural mechanisms, clinical status, or diagnostic "
                "conclusions.",
                role="muted",
                size=10,
            )
        )


#: Phase 4 semantic audit (Chapter 3 -> Chapter 5 transfer spec, Whole-MYELIN
#: roster in SCIENCE_LAB/analysis.py::_WHOLE_ROSTER / _build_whole_myelin):
#:
#: SINE (_whole_generic: terminal kind SINE_EPISODE_RESOLVED, keyed by
#: episode_uid), MINE (_whole_mine: MineEpisodeProjection.is_closed, keyed by
#: mine_episode_id), COSINE (_whole_cosine: CosineEpisodeProjection.is_closed,
#: keyed by cosine_session_id+generation), and SECANT (certified native
#: founded-and-closed episodes) share the completed-organ-episode count unit.
#: These existing Whole-MYELIN rows cover the full finalized parent MYELIN
#: session, not just the selected experiment. A completed native episode does
#: not necessarily mean successful recovery. Preserve each organ's existing
#: certification; never substitute SECANT's lifetime landing count or its
#: separate experiment-contained detail rows.
#:
#: This does NOT prove the four organs' episode identities form one
#: mutually exclusive population of unique behavioral episodes -- one
#: broader user journey could transition between organ domains. The donut
#: therefore means exactly "share of the summed completed organ-episode
#: counts among SINE, MINE, COSINE and SECANT" -- never time share, dwell share,
#: percentage of unique user episodes, distraction probability, or share of
#: the whole session.
#:
#: MIRL ("Verified recoveries" = distinct return_verified MIRL events) and
#: COSECANT ("Completed returns" = distinct break_id with RETURN_CONFIRMED)
#: both count "a return was confirmed", but via different event streams and
#: different identity keys than an episode closing -- not the same unit as
#: SINE/MINE/COSINE/SECANT's episode count, and not proven identical to each other.
#: STUDY ("Completed study blocks") counts distinct (block_id, generation)
#: pairs -- a planned time-block unit, unrelated to episodes or returns.
#: NORMAL_BREAK ("Completed break events") counts distinct break_id with
#: EITHER a natural completion OR an early stop folded into one count -- a
#: break-lane unit, and not even a single terminal-kind basis internally.
#:
#: Conclusion: SINE/MINE/COSINE/SECANT share this chartable count basis. MIRL,
#: COSECANT, STUDY and NORMAL_BREAK are held out of the Phase 4 bar/donut --
#: their certified values remain fully visible, unchanged, in Chapter 3's
#: Whole-MYELIN Analysis panel.
_EPISODE_CHART_ORGANS: Final = ("SINE", "MINE", "COSINE", "SECANT")
_EPISODE_CHART_HELD_NOTE: Final = (
    "MIRL (verified recoveries), COSECANT (completed returns), STUDY (completed "
    "study blocks) and NORMAL BREAK (completed break events) use a different "
    "certified unit than a completed episode and are not included in this "
    "comparison. Their certified values remain in Chapter 3's Whole-MYELIN "
    "Analysis panel."
)
_EPISODE_CHART_ACCENTS: Final = {
    "SINE": "#38BDF8",  # mirrors chapter3_view.py's local SINE-identity cyan
    "MINE": "#22C55E",  # mirrors chapter3_view.py's local MINE-identity green
    "COSINE": FEED_BADGE_COSINE,  # UI_THEMES.theme's existing COSINE badge color
    "SECANT": "#8E5FC4",  # existing Science Lab report-chart purple
}
_MUTED_CHART_COLOR: Final = "#475569"


def _episode_rows(
    presentation: Chapter5Presentation | None,
) -> dict[str, WholeMyelinRow] | None:
    """Pick out only the certified rows sharing the completed-episode basis;
    perform no recalculation -- every value returned is exactly the row
    Chapter 3 already certified."""

    if presentation is None:
        return None
    by_source = {row.source: row for row in presentation.whole_myelin_summary}
    return {organ: by_source[organ] for organ in _EPISODE_CHART_ORGANS if organ in by_source}


class _QuickSummaryStrip(QFrame):
    """Chapter 5's Quick Summary strip: a compact, at-a-glance restatement of
    identity/status fields Chapter 5 already holds on ``Chapter5Presentation``
    (Chapter 3 -> Chapter 5 transfer spec section 7).  Renders only -- the
    "available metrics" and "certified patterns" counts are the same counts
    already carried by ``presentation.behavioral_results`` / ``.result_patterns``
    (each metric's own already-certified ``status``); this widget performs no
    new analysis, no raw-source read, and no recalculation of certified truth.
    """

    _FIELDS: Final = (
        "EXPERIMENT ID",
        "PARENT SESSION ID",
        "ANALYSIS",
        "TRANSFER",
        "AVAILABLE METRICS",
        "CERTIFIED PATTERNS",
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # "card" (the same object name the hero and every other Science Lab
        # card use), not a bespoke name -- a bespoke QFrame name has no
        # background rule of its own, which left this strip's value labels
        # dark-on-dark in WHITE theme (found in the final visual-program
        # UAT, same root cause as the hero heading fix).
        self.setObjectName("card")
        self.setAccessibleName("Chapter 5 quick summary")
        _allow_shrink(self)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(20)

        self._values: dict[str, QLabel] = {}
        for field in self._FIELDS:
            column = QVBoxLayout()
            column.setSpacing(4)
            caption = QLabel(field)
            caption.setObjectName("chapter5SummaryCaption")
            caption.setProperty("role", "cyan")
            caption.setFont(make_font(8.5, 700, spacing=0.5))
            column.addWidget(caption)
            value = QLabel("—")
            value.setObjectName("chapter5SummaryValue")
            value.setFont(make_font(11, 800))
            value.setWordWrap(True)
            _allow_shrink(value)
            column.addWidget(value)
            self._values[field] = value
            layout.addLayout(column, 1)

    def render_presentation(self, presentation: Chapter5Presentation) -> None:
        """Restate already-certified fields; compute nothing new."""

        available = sum(
            1 for metric in presentation.behavioral_results if metric.status == AVAILABLE
        )
        self._values["EXPERIMENT ID"].setText(str(presentation.experiment_id))
        self._values["PARENT SESSION ID"].setText(str(presentation.parent_session_id))
        self._values["ANALYSIS"].setText("CERTIFIED")
        self._values["TRANSFER"].setText("TRANSFERRED")
        self._values["AVAILABLE METRICS"].setText(
            f"{available} of {len(presentation.behavioral_results)}"
        )
        self._values["CERTIFIED PATTERNS"].setText(str(len(presentation.result_patterns)))


#: The comparison uses parent-session totals from one certified package,
#: not a comparable four-organ time series. SECANT has certified timeline
#: events, including both recovery closure and native episode closure; those
#: must not be counted as separate completed episodes. Historical previews
#: remain separate packages, not an accumulated trend dataset. Keep the
#: existing "NOT ENOUGH CERTIFIED HISTORY FOR TREND" placeholder.
_LINE_GRAPH_REASON: Final = (
    "The certified package does not provide a comparable completed-episode "
    "time series for SINE, MINE, COSINE and SECANT. Existing SECANT timeline "
    "events do not provide the missing comparable four-organ series."
)


class _LineGraphPlaceholderCard(QFrame):
    """ORGAN TREND ACROSS EPISODES -- Phase 5 finding: neither a certified
    cross-experiment history nor a comparable within-experiment multi-organ
    series exists (see the audit note above).  Renders the honest
    NOT ENOUGH CERTIFIED HISTORY FOR TREND state; never a fabricated line.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("ORGAN TREND ACROSS EPISODES")
        title.setObjectName("chapter5ChartTitle")
        title.setProperty("role", "cyan")
        title.setFont(make_font(11.5, 800, spacing=0.6))
        title.setWordWrap(True)
        _allow_shrink(title)
        header.addWidget(title, 1)
        self._status_chip = QLabel("AWAITING CHAPTER 3")
        self._status_chip.setObjectName("chapter5ChartStatus")
        self._status_chip.setFont(make_font(8, 700, spacing=0.5))
        header.addWidget(self._status_chip, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "Intended basis: certified organ-episode counts across episodes, "
                "experiments, or sessions.",
                role="muted", size=9.5,
            )
        )

        empty_state = QFrame()
        empty_state.setObjectName("chapter5LineGraphEmptyState")
        empty_layout = QVBoxLayout(empty_state)
        empty_layout.setContentsMargins(4, 24, 4, 24)
        empty_layout.setSpacing(6)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        headline = QLabel("NOT ENOUGH CERTIFIED HISTORY FOR TREND")
        headline.setObjectName("chapter5LineGraphEmptyHeadline")
        headline.setWordWrap(True)
        headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        headline.setFont(make_font(10.5, 800, spacing=0.3))
        _allow_shrink(headline)
        empty_layout.addWidget(headline)

        reason = _paragraph(_LINE_GRAPH_REASON, role="muted", size=9)
        reason.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(reason)

        layout.addWidget(empty_state)

    def render_presentation(self, presentation: Chapter5Presentation | None) -> None:
        """No fabricated point is ever drawn -- only the status chip moves,
        acknowledging a package was certified while the trend remains
        honestly unavailable under the current transfer contract."""

        self._status_chip.setText(
            "NOT ENOUGH CERTIFIED HISTORY" if presentation is not None else "AWAITING CHAPTER 3"
        )


class _EpisodeBarCanvas(QFrame):
    """Hand-painted bar canvas (no external chart library, native MYELIN
    look): a truthful bar per organ using exactly the certified
    ``WholeMyelinRow`` count it is given.  Owns no data itself."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter5EpisodeBarCanvas")
        # Fixed, not minimum: an unbounded QFrame in a QHBoxLayout row can be
        # stretched taller than intended to match a taller sibling card,
        # which grows this canvas's paintEvent geometry (bars/labels use
        # self.rect()) far past its designed size and visually collides with
        # whatever sits below it in this card's own layout (found in the
        # final visual-program UAT).
        self.setFixedHeight(140)
        self._rows: dict[str, WholeMyelinRow] | None = None

    def set_rows(self, rows: dict[str, WholeMyelinRow] | None) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        width, height = float(rect.width()), float(rect.height())
        baseline = height - 26.0
        available_height = max(1.0, baseline - 30.0)

        if not self._rows:
            painter.end()
            return

        organs = list(self._rows.keys())
        counts = [
            row.count for row in self._rows.values()
            if row.status == AVAILABLE and row.count is not None
        ]
        peak = max(counts) if counts else 0
        slot = width / len(organs)
        bar_width = min(64.0, slot * 0.42)

        for index, organ in enumerate(organs):
            row = self._rows[organ]
            center_x = slot * index + slot / 2
            if row.status == AVAILABLE and row.count is not None:
                bar_height = available_height * (row.count / peak) if peak > 0 else 0.0
                color = QColor(_EPISODE_CHART_ACCENTS.get(organ, _MUTED_CHART_COLOR))
                value_text = str(row.count)
            else:
                # A thin, clearly-not-a-bar marker -- never rendered as an
                # indistinguishable "0" bar, so missing evidence is never
                # visually confused with a certified zero count.
                bar_height = 4.0
                color = QColor(_MUTED_CHART_COLOR)
                value_text = "No evidence" if row.status == NO_EVIDENCE else "Unavailable"

            bar_rect = QRectF(
                center_x - bar_width / 2, baseline - bar_height, bar_width, max(2.0, bar_height)
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(bar_rect, 3, 3)

            painter.setFont(make_font(9, 700, spacing=0.2))
            painter.setPen(QPen(QColor("#E2E8F0")))
            value_rect = QRectF(slot * index, max(0.0, baseline - bar_height - 18), slot, 16)
            painter.drawText(value_rect, Qt.AlignmentFlag.AlignCenter, value_text)

            painter.setFont(make_font(9.5, 700, spacing=0.4))
            painter.setPen(QPen(QColor("#94A3B8")))
            label_rect = QRectF(slot * index, baseline + 4, slot, 18)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, organ)

        painter.setPen(QPen(QColor("#334155")))
        painter.drawLine(QPointF(0, baseline), QPointF(width, baseline))
        painter.end()


class _EpisodeBarChartCard(QFrame):
    """COMPLETED EPISODES BY ORGAN -- SINE/MINE/COSINE/SECANT (see the
    semantic-audit note above ``_EPISODE_CHART_ORGANS``); a truthful bar per
    organ using exactly the certified count Chapter 3 already produced.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("COMPLETED EPISODES BY ORGAN")
        title.setObjectName("chapter5ChartTitle")
        title.setProperty("role", "cyan")
        title.setFont(make_font(11.5, 800, spacing=0.6))
        header.addWidget(title, 1)
        self._status_chip = QLabel("AWAITING CHAPTER 3")
        self._status_chip.setObjectName("chapter5ChartStatus")
        self._status_chip.setFont(make_font(8, 700, spacing=0.5))
        header.addWidget(self._status_chip, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "Certified completed-episode counts for SINE, MINE, COSINE and "
                "SECANT in the finalized parent MYELIN session. Completed does "
                "not necessarily mean recovered.",
                role="muted", size=9.5,
            )
        )

        self._canvas = _EpisodeBarCanvas()
        layout.addWidget(self._canvas)

        layout.addWidget(_paragraph(_EPISODE_CHART_HELD_NOTE, role="muted", size=8.5))

    def render_presentation(self, presentation: Chapter5Presentation | None) -> None:
        rows = _episode_rows(presentation)
        self._canvas.set_rows(rows)
        self._status_chip.setText("CERTIFIED" if rows else "AWAITING CHAPTER 3")


class _EpisodeShareDonutCanvas(QFrame):
    """Hand-painted donut.  Slices are proportional ONLY to AVAILABLE,
    certified counts; a NO_EVIDENCE/UNAVAILABLE row is excluded from the
    total and never silently folded into a "0" share."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chapter5EpisodeDonutCanvas")
        # Fixed, not minimum -- see _EpisodeBarCanvas's comment: an unbounded
        # canvas visually grew into the legend/held-note text below it when
        # its row was stretched taller than 150px (found in the final
        # visual-program UAT).
        self.setFixedHeight(150)
        self._rows: dict[str, WholeMyelinRow] | None = None

    def set_rows(self, rows: dict[str, WholeMyelinRow] | None) -> None:
        self._rows = rows
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 -- Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect()
        side = max(60.0, min(rect.width(), rect.height()) - 20.0)
        square = QRectF(
            rect.center().x() - side / 2, rect.center().y() - side / 2, side, side
        )

        available = {}
        if self._rows:
            available = {
                organ: row.count
                for organ, row in self._rows.items()
                if row.status == AVAILABLE and row.count is not None
            }
        total = sum(available.values())

        painter.setPen(QPen(QColor("#334155"), 14))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(square)

        if total > 0:
            start_angle = 90 * 16
            for organ in _EPISODE_CHART_ORGANS:
                count = available.get(organ, 0)
                if count <= 0:
                    continue
                span = int(round((count / total) * 360 * 16))
                pen = QPen(QColor(_EPISODE_CHART_ACCENTS.get(organ, _MUTED_CHART_COLOR)), 14)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawArc(square, start_angle, -span)
                start_angle -= span

        if self._rows is None:
            center_text = "—"
        elif not available:
            center_text = "N/A"
        else:
            center_text = str(total)
        painter.setPen(QPen(QColor("#E2E8F0")))
        painter.setFont(make_font(16, 800, mono=True))
        painter.drawText(square, Qt.AlignmentFlag.AlignCenter, center_text)
        painter.end()


class _EpisodeShareDonutCard(QFrame):
    """COMPLETED ORGAN-EPISODE SHARE -- share of the summed completed
    organ-episode counts among SINE, MINE, COSINE and SECANT for the finalized
    parent MYELIN session. Deliberately not named "dwell distribution", "time share",
    or "percentage of unique user episodes": no certified evidence for any
    of those exists for this basis, and the four organs' episode identities
    are not proven to form one mutually exclusive population -- one broader
    user journey could transition between organ domains.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        _allow_shrink(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("COMPLETED ORGAN-EPISODE SHARE")
        title.setObjectName("chapter5ChartTitle")
        title.setProperty("role", "cyan")
        title.setFont(make_font(11.5, 800, spacing=0.6))
        title.setWordWrap(True)
        _allow_shrink(title)
        header.addWidget(title, 1)
        self._status_chip = QLabel("AWAITING CHAPTER 3")
        self._status_chip.setObjectName("chapter5ChartStatus")
        self._status_chip.setFont(make_font(8, 700, spacing=0.5))
        header.addWidget(self._status_chip, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "Share of the summed completed organ-episode counts among SINE, "
                "MINE, COSINE and SECANT in the finalized parent MYELIN session "
                "-- not a measure of time, dwell, unique user episodes, "
                "distraction probability, or session duration.",
                role="muted", size=9.5,
            )
        )

        self._canvas = _EpisodeShareDonutCanvas()
        layout.addWidget(self._canvas)

        self._legend_layout = QVBoxLayout()
        self._legend_layout.setSpacing(4)
        layout.addLayout(self._legend_layout)
        self._legend_values: dict[str, QLabel] = {}
        for organ in _EPISODE_CHART_ORGANS:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(8)
            dot = QFrame()
            dot.setFixedSize(9, 9)
            dot.setStyleSheet(
                f"background: {_EPISODE_CHART_ACCENTS[organ]}; border-radius: 4px;"
            )
            row_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignVCenter)
            name_label = QLabel(organ)
            name_label.setFont(make_font(9, 700))
            row_layout.addWidget(name_label)
            row_layout.addStretch(1)
            value_label = QLabel("—")
            value_label.setObjectName("chapter5DonutLegendValue")
            value_label.setFont(make_font(9, 700, mono=True))
            row_layout.addWidget(value_label)
            self._legend_values[organ] = value_label
            self._legend_layout.addLayout(row_layout)

        layout.addWidget(_paragraph(_EPISODE_CHART_HELD_NOTE, role="muted", size=8.5))

    def render_presentation(self, presentation: Chapter5Presentation | None) -> None:
        rows = _episode_rows(presentation)
        self._canvas.set_rows(rows)
        self._status_chip.setText("CERTIFIED" if rows else "AWAITING CHAPTER 3")
        for organ in _EPISODE_CHART_ORGANS:
            label = self._legend_values[organ]
            row = rows.get(organ) if rows else None
            if row is None:
                label.setText("—")
            elif row.status == AVAILABLE:
                label.setText(str(row.count))
            elif row.status == NO_EVIDENCE:
                label.setText("No evidence")
            else:
                label.setText("Unavailable")


#: Phase 6 forensic audit (SCIENCE_LAB/analysis.py::_build_timeline,
#: read-only; not reopened) -- exactly which organs have certified,
#: timestamped timeline events, and which sources compose each organ's
#: route:
#:
#: SINE: SINE_DISPLAYED -> TRIGGER, SINE_EPISODE_RESOLVED -> EPISODE_CLOSURE
#: (source="SINE"). Return tracking for a SINE-triggered episode is
#: certified under a DIFFERENT source, MIRL: return_verification_started ->
#: RETURN, return_verified -> VERIFIED_RETURN, episode_closed ->
#: EPISODE_CLOSURE (source="MIRL"). SCIENCE_LAB/live_timeline.py's own
#: ``_project_sine`` already combines SINE+MIRL into one organ narrative for
#: exactly this reason -- the SINE branch here follows that same,
#: pre-existing convention rather than inventing a new one.
#: COSECANT: BREAK_STARTED/BREAK_COMPLETE -> BREAK_LANE,
#: RETURN_CONFIRMATION_STARTED -> RETURN, RETURN_CONFIRMED ->
#: VERIFIED_RETURN (source="COSECANT" only -- self-contained, no merge
#: needed).
#: MINE: contributes ZERO timeline events. COSINE: contributes ZERO
#: timeline events. Both organs exist only as a single aggregate
#: completed-episode count in ``whole_myelin_summary`` -- no certified
#: per-episode timestamp, stage, or identity exists for either in
#: ``package.timeline`` today.
#:
#: Conclusion: the branch selector shows all four organ identities (SINE /
#: MINE / COSINE / COSECANT), but only SINE and COSECANT can ever render a
#: detailed certified route. MINE and COSINE show an honest "no certified
#: journey events" state instead of a manufactured one.
#: OFF_TASK_DWELL is a declared valid stage constant but no builder in
#: _build_timeline ever emits it for any organ -- it is never rendered as a
#: node because no certified event of that stage exists to draw.
_JOURNEY_ORGANS: Final = ("SINE", "MINE", "COSINE", "SECANT", "COSECANT")
_JOURNEY_SOURCES_BY_ORGAN: Final = {
    "SINE": ("SINE", "MIRL"),
    "MINE": ("MINE",),
    "COSINE": ("COSINE",),
    "SECANT": ("SECANT",),
    "COSECANT": ("COSECANT",),
}
_JOURNEY_NO_EVENTS_NOTE: Final = (
    "No certified journey events for {organ} exist in the transferred package's "
    "timeline. Only an aggregate completed-episode count is certified for this "
    "organ (see the bar chart above) -- no route is drawn rather than inventing one."
)


def _journey_events(
    presentation: Chapter5Presentation | None, organ: str
) -> tuple[Chapter3TimelineEvent, ...] | None:
    """Read only ``presentation.package.timeline`` -- the certified event log
    already carried by the transferred package -- filter to the sources
    that compose this organ's route, and order by real occurrence time.
    Invents no event, infers no stage, merges nothing beyond the same
    SINE+MIRL convention ``live_timeline.py`` already uses."""

    if presentation is None:
        return None
    sources = _JOURNEY_SOURCES_BY_ORGAN[organ]
    events = tuple(
        event for event in presentation.package.timeline if event.source in sources
    )
    return tuple(sorted(events, key=lambda event: event.occurred_monotonic_ns))


class _JourneyEventRow(QFrame):
    """One certified timeline event rendered as one factual route node.
    Every field shown (timestamp, stage, label, source) comes directly from
    the certified ``Chapter3TimelineEvent`` it is given -- nothing here is
    computed, inferred, or narrated."""

    def __init__(
        self, event: Chapter3TimelineEvent, *, start_ns: int, is_last: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chapter5JourneyEventRow")
        _allow_shrink(self)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)

        relative_seconds = max(0.0, (event.occurred_monotonic_ns - start_ns) / 1_000_000_000)
        time_label = QLabel(f"+{relative_seconds:.1f}s")
        time_label.setObjectName("chapter5JourneyTime")
        time_label.setFont(make_font(9, 700, mono=True))
        time_label.setFixedWidth(54)
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        row.addWidget(time_label)

        rail_column = QVBoxLayout()
        rail_column.setContentsMargins(0, 3, 0, 0)
        rail_column.setSpacing(0)
        dot = QFrame()
        dot.setObjectName("chapter5JourneyDot")
        dot.setFixedSize(8, 8)
        rail_column.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
        if not is_last:
            line = QFrame()
            line.setObjectName("chapter5JourneyRail")
            line.setFixedWidth(2)
            line.setMinimumHeight(18)
            rail_column.addWidget(line, 1, Qt.AlignmentFlag.AlignHCenter)
        rail_widget = QWidget()
        rail_widget.setLayout(rail_column)
        rail_widget.setFixedWidth(8)
        row.addWidget(rail_widget)

        content = QVBoxLayout()
        content.setSpacing(2)
        label = QLabel(event.label)
        label.setObjectName("chapter5JourneyLabel")
        label.setFont(make_font(10, 700))
        label.setWordWrap(True)
        _allow_shrink(label)
        content.addWidget(label)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(6)
        stage_chip = QLabel(event.stage.replace("_", " "))
        stage_chip.setObjectName("chapter5JourneyStageChip")
        stage_chip.setFont(make_font(7.5, 700, spacing=0.4))
        chip_row.addWidget(stage_chip)
        source_chip = QLabel(event.source)
        source_chip.setObjectName("chapter5JourneySourceChip")
        source_chip.setFont(make_font(7.5, 700, spacing=0.4))
        chip_row.addWidget(source_chip)
        chip_row.addStretch(1)
        content.addLayout(chip_row)
        content.addSpacing(0 if is_last else 8)

        row.addLayout(content, 1)


class _BehavioralJourneyCard(QFrame):
    """BEHAVIORAL JOURNEY -- SELECTED EXPERIMENT.  Forensic rendering, not
    storytelling: the branch selector names all four organs, but only a
    branch backed by certified ``package.timeline`` events (see the audit
    above) ever draws a route.  Narrative/possible-response bubbles are
    never attached to a specific node -- MYELIN certifies no such fact for
    any experiment -- and the legend below states this plainly instead of
    inventing an example that could be mistaken for evidence.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        _allow_shrink(self)
        self._presentation: Chapter5Presentation | None = None
        self._active_organ = "SINE"
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(10)
        title = QLabel("BEHAVIORAL JOURNEY -- SELECTED EXPERIMENT")
        title.setObjectName("chapter5ChartTitle")
        title.setProperty("role", "cyan")
        title.setFont(make_font(11.5, 800, spacing=0.6))
        title.setWordWrap(True)
        _allow_shrink(title)
        header.addWidget(title, 1)
        self._status_chip = QLabel("AWAITING CHAPTER 3")
        self._status_chip.setObjectName("chapter5ChartStatus")
        self._status_chip.setFont(make_font(8, 700, spacing=0.5))
        header.addWidget(self._status_chip, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(header)

        layout.addWidget(
            _paragraph(
                "Certified event route for the selected experiment, by organ. Only "
                "an organ with certified timeline events shows a detailed route.",
                role="muted", size=9.5,
            )
        )

        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self._organ_buttons: dict[str, QPushButton] = {}
        for organ in _JOURNEY_ORGANS:
            button = QPushButton(organ)
            button.setObjectName("chapter5JourneyOrganButton")
            button.setFont(make_font(9.5, 700, spacing=0.4))
            button.setCheckable(True)
            button.setChecked(organ == self._active_organ)
            button.clicked.connect(lambda _checked, o=organ: self._select_organ(o))
            tabs_row.addWidget(button)
            self._organ_buttons[organ] = button
        tabs_row.addStretch(1)

        self._inspect_button = QPushButton("INSPECT")
        self._inspect_button.setObjectName("chapter5ChartUtilityButton")
        self._inspect_button.setFont(make_font(8, 700, spacing=0.4))
        self._inspect_button.setCheckable(True)
        self._inspect_button.toggled.connect(self._set_inspect_visible)
        tabs_row.addWidget(self._inspect_button)

        self._expand_button = QPushButton("EXPAND")
        self._expand_button.setObjectName("chapter5ChartUtilityButton")
        self._expand_button.setFont(make_font(8, 700, spacing=0.4))
        self._expand_button.setCheckable(True)
        self._expand_button.toggled.connect(self._set_expanded)
        tabs_row.addWidget(self._expand_button)
        layout.addLayout(tabs_row)

        self._route_layout = QVBoxLayout()
        self._route_layout.setSpacing(4)
        route_container = QWidget()
        route_container.setLayout(self._route_layout)
        self._route_scroll_target = route_container

        # A real certified route can exceed the compact default height with
        # more than a couple of events -- a plain fixed-height QWidget let
        # rows visually overlap once content exceeded it (found in the final
        # visual-program UAT). A QScrollArea scrolls the overflow instead.
        route_scroll = QScrollArea()
        route_scroll.setObjectName("chapter5JourneyRouteScroll")
        route_scroll.setWidgetResizable(True)
        route_scroll.setFrameShape(QFrame.Shape.NoFrame)
        route_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        route_scroll.setWidget(route_container)
        route_scroll.setMinimumHeight(120)
        route_scroll.setMaximumHeight(120)
        self._route_container = route_scroll
        layout.addWidget(route_scroll)

        self._inspect_panel = _paragraph("", role="muted", size=8.5)
        self._inspect_panel.setVisible(False)
        layout.addWidget(self._inspect_panel)

        legend = QHBoxLayout()
        legend.setSpacing(16)
        factual_swatch = QLabel("■  FACTUAL EVENT (certified)")
        factual_swatch.setObjectName("chapter5JourneyLegendFactual")
        factual_swatch.setFont(make_font(8, 700))
        legend.addWidget(factual_swatch)
        narrative_swatch = QLabel("◇  NARRATIVE ANNOTATION -- illustrative only, never measured")
        narrative_swatch.setObjectName("chapter5JourneyLegendNarrative")
        narrative_swatch.setFont(make_font(8, 700))
        narrative_swatch.setWordWrap(True)
        _allow_shrink(narrative_swatch)
        legend.addWidget(narrative_swatch, 1)
        layout.addLayout(legend)

        layout.addWidget(
            _paragraph(
                "MYELIN certifies no fact about a user's internal thoughts for any "
                "experiment; this route contains factual events only.",
                role="muted", size=8,
            )
        )

        self._render_route()

    def _select_organ(self, organ: str) -> None:
        self._active_organ = organ
        for key, button in self._organ_buttons.items():
            button.setChecked(key == organ)
        self._render_route()
        if not self._inspect_panel.isHidden():
            # Refresh the basis text for the newly active organ -- found in
            # the final visual-program UAT switching tabs while INSPECT was
            # open left the previous organ's source list on screen.
            # isHidden() (the widget's own explicit flag) is used rather
            # than isVisible() (which also depends on the top-level window
            # actually being shown) so this check is reliable regardless of
            # window state.
            self._set_inspect_visible(True)

    def _set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        target_height = 260 if expanded else 120
        self._route_container.setMinimumHeight(target_height)
        self._route_container.setMaximumHeight(target_height)
        self._expand_button.setText("COLLAPSE" if expanded else "EXPAND")

    def _set_inspect_visible(self, visible: bool) -> None:
        self._inspect_panel.setVisible(visible)
        self._inspect_button.setText("HIDE BASIS" if visible else "INSPECT")
        if visible:
            sources = ", ".join(_JOURNEY_SOURCES_BY_ORGAN[self._active_organ])
            self._inspect_panel.setText(
                f"Basis: presentation.package.timeline, filtered to source in "
                f"[{sources}], ordered by occurred_monotonic_ns. No event is "
                f"computed or inferred here -- each row is one certified "
                f"Chapter3TimelineEvent."
            )

    def render_presentation(self, presentation: Chapter5Presentation | None) -> None:
        self._presentation = presentation
        self._status_chip.setText("CERTIFIED" if presentation is not None else "AWAITING CHAPTER 3")
        for organ in _JOURNEY_ORGANS:
            events = _journey_events(presentation, organ)
            self._organ_buttons[organ].setEnabled(True)
        self._render_route()
        if not self._inspect_panel.isHidden():
            self._set_inspect_visible(True)

    def _render_route(self) -> None:
        while self._route_layout.count():
            taken = self._route_layout.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.setParent(None)

        events = _journey_events(self._presentation, self._active_organ)
        if events is None:
            note = _paragraph(
                "Awaiting certified analysis from Chapter 3.", role="muted", size=9.5,
            )
            self._route_layout.addWidget(note)
            return
        if not events:
            note = _paragraph(
                _JOURNEY_NO_EVENTS_NOTE.format(organ=self._active_organ),
                role="muted", size=9.5,
            )
            self._route_layout.addWidget(note)
            return

        start_ns = self._presentation.package.experiment_start_monotonic_ns
        for index, event in enumerate(events):
            row = _JourneyEventRow(event, start_ns=start_ns, is_last=(index == len(events) - 1))
            self._route_layout.addWidget(row)
        self._route_layout.addStretch(1)


_WINDOWS_INVALID_FILENAME_CHARS: Final = frozenset('<>:"/\\|?*')


def _default_export_filename(experiment_id: str) -> str:
    """A deterministic, Windows-safe default filename derived only from the
    certified experiment identity -- never invented, never a counter."""

    safe = "".join(
        ch if ch not in _WINDOWS_INVALID_FILENAME_CHARS else "_" for ch in experiment_id
    ).strip()
    return f"MYELIN_REPORT_{safe or 'EXPERIMENT'}.pdf"


def _normalize_pdf_path(path: Path) -> Path:
    """Accept an existing ``.pdf``/``.PDF`` suffix; otherwise append ``.pdf``
    (never replace an unrelated suffix) so the output is always a PDF."""

    if path.suffix.lower() == ".pdf":
        return path
    return path.with_name(path.name + ".pdf")


class _HistoryRow(QFrame):
    """One durable experiment row in the SHOW HISTORY list.

    Eligible rows (COMPLETED, valid durable end boundary -- see
    ``SCIENCE_LAB.history._listing_eligibility``) get a VIEW RESULTS
    button; every other row is shown honestly, disabled, with its factual
    reason -- never repaired, never hidden."""

    selected = pyqtSignal(str)

    def __init__(self, entry: "HistoryEntry", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._experiment_id = entry.experiment_id
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(14)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        title = QLabel(f"{entry.experiment_id}  ·  session {entry.parent_session_id}")
        title.setFont(make_font(10.5, 700))
        _allow_shrink(title)
        text_column.addWidget(title)
        detail = (
            f"{entry.status}  ·  started {entry.started_at_utc}"
            if entry.eligible
            else f"{entry.status}  ·  {entry.reason}"
        )
        detail_label = QLabel(detail)
        detail_label.setFont(make_font(8.5, 400))
        detail_label.setProperty("role", "muted")
        detail_label.setWordWrap(True)
        _allow_shrink(detail_label)
        text_column.addWidget(detail_label)
        layout.addLayout(text_column, 1)

        button = QPushButton("VIEW RESULTS" if entry.eligible else "UNAVAILABLE")
        button.setFont(make_font(9, 700, spacing=0.3))
        button.setEnabled(entry.eligible)
        if entry.eligible:
            button.clicked.connect(lambda: self.selected.emit(self._experiment_id))
        else:
            button.setToolTip(entry.reason)
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)


class _HistoryDialog(QDialog):
    """SHOW HISTORY: a bounded, scrollable dialog listing every durable
    Science Lab experiment.

    This dialog performs no read of its own -- ``Chapter5ResultsView``
    supplies the list and every reconstruction result through
    ``render_entries``/``render_result`` after the application host has
    called the read-only ``SCIENCE_LAB.history`` functions.  The only
    action this dialog ever takes directly is exporting an already-
    reconstructed, already-CERTIFIED package through the same frozen
    ``generate_report_pdf`` the main EXPORT PDF button uses -- it never
    touches ``_current_receipt`` and never claims TRANSFERRED.
    """

    experiment_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Experiment History")
        self.setMinimumSize(600, 460)
        self._package: Chapter3ResultPackage | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        heading = QLabel("EXPERIMENT HISTORY")
        heading.setFont(make_font(13, 800, spacing=0.5))
        root.addWidget(heading)
        self._list_status = QLabel("Loading durable experiment records…")
        self._list_status.setFont(make_font(9, 400))
        self._list_status.setProperty("role", "muted")
        root.addWidget(self._list_status)

        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setMaximumHeight(220)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch(1)
        list_scroll.setWidget(self._list_container)
        root.addWidget(list_scroll, 0)

        result_scroll = QScrollArea()
        result_scroll.setWidgetResizable(True)
        self._result_container = QWidget()
        self._result_layout = QVBoxLayout(self._result_container)
        self._result_layout.setContentsMargins(4, 4, 4, 4)
        self._result_layout.setSpacing(6)
        self._result_placeholder = QLabel(
            "Select an eligible experiment above to view its historical reconstruction."
        )
        self._result_placeholder.setWordWrap(True)
        self._result_placeholder.setFont(make_font(9.5, 400))
        self._result_placeholder.setProperty("role", "muted")
        self._result_layout.addWidget(self._result_placeholder)
        self._result_layout.addStretch(1)
        result_scroll.setWidget(self._result_container)
        root.addWidget(result_scroll, 1)

        button_row = QHBoxLayout()
        self._export_button = QPushButton("EXPORT PDF")
        self._export_button.setFont(make_font(9.5, 700, spacing=0.3))
        self._export_button.setEnabled(False)
        self._export_button.clicked.connect(self._handle_export)
        button_row.addWidget(self._export_button)
        button_row.addStretch(1)
        close_button = QPushButton("CLOSE")
        close_button.setFont(make_font(9.5, 700, spacing=0.3))
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)
        root.addLayout(button_row)

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count() > 1:  # keep the trailing stretch
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def render_entries(self, entries: tuple["HistoryEntry", ...]) -> None:
        self._clear_layout(self._list_layout)
        if not entries:
            self._list_status.setText("No durable Science Lab experiments exist yet.")
            return
        self._list_status.setText(f"{len(entries)} durable experiment(s), newest first.")
        for entry in entries:
            row = _HistoryRow(entry)
            row.selected.connect(self.experiment_selected.emit)
            self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def show_list_error(self, message: str) -> None:
        self._clear_layout(self._list_layout)
        self._list_status.setText(f"History list unavailable: {message}")

    def render_result(self, reconstruction: "HistoryReconstruction") -> None:
        self._clear_layout(self._result_layout)
        self._package = None
        self._export_button.setEnabled(False)

        header = QLabel(
            f"{reconstruction.experiment_id}  ·  {_RECONSTRUCTION_LABEL}"
        )
        header.setFont(make_font(11, 800, spacing=0.3))
        header.setWordWrap(True)
        _allow_shrink(header)
        self._result_layout.addWidget(header)

        if reconstruction.status != _HISTORY_CERTIFIED or reconstruction.package is None:
            reason = QLabel(f"Unavailable: {reconstruction.reason}")
            reason.setWordWrap(True)
            reason.setFont(make_font(9.5, 400))
            reason.setProperty("role", "muted")
            self._result_layout.addWidget(reason)
            self._result_layout.addStretch(1)
            return

        package = reconstruction.package
        self._package = package

        identity = QLabel(
            f"Parent session {package.parent_session_id}  ·  Analysis: "
            f"{package.analysis_status}  ·  {reconstruction.reason}"
        )
        identity.setWordWrap(True)
        identity.setFont(make_font(9.5, 400))
        self._result_layout.addWidget(identity)

        coverage_text = "  ·  ".join(
            f"{row.source_system}: {row.status}" for row in package.source_coverage
        )
        coverage = QLabel(f"Source coverage — {coverage_text}")
        coverage.setWordWrap(True)
        coverage.setFont(make_font(9, 400))
        self._result_layout.addWidget(coverage)

        metrics_text = "  ·  ".join(
            f"{metric.label}: {metric.value if metric.status == AVAILABLE else metric.status}"
            for metric in package.key_metrics
        )
        if metrics_text:
            metrics = QLabel(f"Key metrics — {metrics_text}")
            metrics.setWordWrap(True)
            metrics.setFont(make_font(9, 400))
            self._result_layout.addWidget(metrics)

        organs_text = "  ·  ".join(
            f"{row.source}: {row.status}"
            + (f" ({row.count})" if row.count is not None else "")
            for row in package.whole_myelin_summary
        )
        if organs_text:
            organs = QLabel(f"Whole-MYELIN organ availability — {organs_text}")
            organs.setWordWrap(True)
            organs.setFont(make_font(9, 400))
            self._result_layout.addWidget(organs)

        self._result_layout.addStretch(1)
        self._export_button.setEnabled(True)

    def _handle_export(self) -> None:
        package = self._package
        if package is None or package.analysis_status != CERTIFIED:
            QMessageBox.warning(self, "MYELIN Report", "No certified historical package is loaded.")
            return
        default_name = _default_export_filename(package.experiment_id)
        path_text, _ = QFileDialog.getSaveFileName(
            self, "Export Historical MYELIN Report PDF", default_name, "PDF Files (*.pdf)"
        )
        if not path_text:
            return  # Cancelled: silent, no generation, no state change.
        output_path = _normalize_pdf_path(Path(path_text))
        try:
            saved_path = generate_report_pdf(package, output_path)
        except Exception as error:
            QMessageBox.warning(self, "MYELIN Report", f"Report generation failed: {error}")
            return
        QMessageBox.information(
            self, "MYELIN Report", f"Historical MYELIN Report PDF saved to:\n{saved_path}"
        )


class Chapter5ResultsView(QWidget):
    """Chapter 5's Results & Discussion hero panel.

    Presentation-only: it retains one receipt for display continuity and
    formats only that receipt's package.  It never generates a report
    itself -- EXPORT PDF (Phase 5) hands this exact retained receipt to the
    frozen ``SCIENCE_LAB.report.generate_report_pdf`` entry point, which owns
    all rendering and destination-file safety.

    SHOW HISTORY (20260917) is deliberately independent of that receipt:
    it is available even when ``_current_receipt`` is ``None`` (e.g. right
    after a MYELIN restart), and nothing it does ever writes to
    ``_current_receipt`` or the main dashboard -- see ``_HistoryDialog``.
    """

    #: SHOW HISTORY clicked -- the application host answers with
    #: ``render_history_list``/``show_history_list_error``.
    history_requested = pyqtSignal()
    #: A specific experiment id chosen in the history dialog -- the
    #: application host answers with ``render_history_result``.
    history_experiment_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current_receipt: Chapter3TransferReceipt | None = None
        self._current_presentation: Chapter5Presentation | None = None
        self._history_dialog = _HistoryDialog(self)
        self._history_dialog.experiment_selected.connect(
            self.history_experiment_selected.emit
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(14)

        root.addWidget(self._build_hero())

        top_row = QHBoxLayout()
        top_row.setSpacing(14)
        self._source_strip = _SourcePackageStrip()
        top_row.addWidget(self._source_strip, 1)
        self._details_button = QPushButton("OPEN DETAILS")
        self._details_button.setObjectName("chapter5DetailsToggle")
        self._details_button.setFont(make_font(10, 700, spacing=0.4))
        self._details_button.setCheckable(True)
        self._details_button.setAccessibleName(
            "Open the detailed Chapter 5 Results & Discussion text"
        )
        self._details_button.toggled.connect(self._set_details_visible)
        top_row.addWidget(self._details_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(top_row)

        self._quick_summary = _QuickSummaryStrip()
        root.addWidget(self._quick_summary)

        self._dashboard_container = QWidget()
        dashboard_layout = QVBoxLayout(self._dashboard_container)
        dashboard_layout.setContentsMargins(0, 0, 0, 0)
        dashboard_layout.setSpacing(14)
        charts_row = QHBoxLayout()
        charts_row.setSpacing(14)
        self._line_graph_card = _LineGraphPlaceholderCard()
        self._episode_bar_chart = _EpisodeBarChartCard()
        self._episode_share_donut = _EpisodeShareDonutCard()
        charts_row.addWidget(self._line_graph_card, 1)
        charts_row.addWidget(self._episode_bar_chart, 1)
        charts_row.addWidget(self._episode_share_donut, 1)
        dashboard_layout.addLayout(charts_row)
        from PyQt6.QtWidgets import QPlainTextEdit
        self._secant_results = QPlainTextEdit()
        self._secant_results.setReadOnly(True)
        self._secant_results.setFont(make_font(13, 400))
        self._secant_results.setStyleSheet("QPlainTextEdit { background: #111827; color: #E5E7EB; border: 1px solid #334155; border-radius: 10px; padding: 12px; }")
        self._secant_results.setAccessibleName("SECANT experiment results")
        self._secant_results.setMinimumHeight(180)
        self._secant_results.setMaximumHeight(300)
        self._secant_results.setPlainText("SECANT — awaiting a certified experiment package.")
        dashboard_layout.addWidget(self._secant_results)
        self._journey_card = _BehavioralJourneyCard()
        dashboard_layout.addWidget(self._journey_card)
        root.addWidget(self._dashboard_container)

        self._section_cards = tuple(
            _ResultsSectionCard(number, title, tag, body_text)
            for number, title, tag, body_text in _SECTIONS
        )
        self._section_grid = _SectionGrid(
            list(self._section_cards),
            wide_columns=4,
            medium_columns=2,
            narrow_columns=1,
            wide_min_width=1300,
            medium_min_width=820,
        )
        self._section_grid.setVisible(False)
        root.addWidget(self._section_grid)

        root.addWidget(_BoundaryNote())
        root.addStretch(1)

    def _set_details_visible(self, visible: bool) -> None:
        """Toggle only presentation hierarchy: default = visual-dashboard
        shell, OPEN DETAILS = the existing scientific text.  No content is
        created or destroyed -- the same seven section cards and the same
        placeholder widget simply swap visibility."""

        self._section_grid.setVisible(visible)
        self._dashboard_container.setVisible(not visible)
        self._details_button.setText("CLOSE DETAILS" if visible else "OPEN DETAILS")

    @property
    def current_receipt(self) -> Chapter3TransferReceipt | None:
        return self._current_receipt

    @property
    def current_presentation(self) -> Chapter5Presentation | None:
        return self._current_presentation

    def render_transferred_results(self, receipt: Chapter3TransferReceipt) -> None:
        """Validate first, then replace the visible result as one presentation."""

        presentation = build_chapter5_presentation(receipt)
        old_receipt = self._current_receipt
        old_presentation = self._current_presentation
        try:
            self._apply_presentation(presentation)
        except Exception:
            if old_presentation is not None:
                self._apply_presentation(old_presentation)
            self._current_receipt = old_receipt
            self._current_presentation = old_presentation
            raise
        self._current_receipt = receipt
        self._current_presentation = presentation

    def _apply_presentation(self, presentation: Chapter5Presentation) -> None:
        from .report_model import _secant_model, UnavailableOrgan
        result = _secant_model(presentation.package)
        if isinstance(result, UnavailableOrgan):
            self._secant_results.setPlainText(f"SECANT — {result.status}\n{result.reason}\nNo evidence does not prove non-use.")
        else:
            lines = ["SECANT — experiment-scoped Study recovery", result.reason, result.overlap_note]
            lines.extend(f"{c.label}: {c.value}" for c in result.snapshot_cards)
            for table in (result.table1, result.table2):
                lines.extend(("", table.title, " | ".join(table.headers)))
                lines.extend(" | ".join(row) for row in table.rows)
            lines.extend(("", result.discussion_note))
            self._secant_results.setPlainText("\n".join(lines))
        sections = (
            presentation.results_overview_lines,
            presentation.behavioral_result_lines,
            presentation.result_pattern_lines,
            presentation.discussion_lines,
            presentation.alternative_explanation_lines,
            presentation.interpretive_summary_lines,
            presentation.limitation_lines,
        )
        if len(sections) != len(self._section_cards) or any(
            type(lines) is not tuple or not lines for lines in sections
        ):
            raise ValueError("Chapter 5 presentation section contract is incomplete")
        self._source_strip.render_presentation(presentation)
        self._quick_summary.render_presentation(presentation)
        self._line_graph_card.render_presentation(presentation)
        self._episode_bar_chart.render_presentation(presentation)
        self._episode_share_donut.render_presentation(presentation)
        self._journey_card.render_presentation(presentation)
        for card, lines in zip(self._section_cards, sections, strict=True):
            card.set_lines(lines)
        self._export_action.show_transferred()

    def _build_hero(self) -> QWidget:
        # A plain QWidget has no background of its own -- it is fully
        # transparent and shows whatever sits behind it. In WHITE theme this
        # left "RESULTS & DISCUSSION" (color: {text}, a dark tone meant for
        # a light card surface) sitting directly on a dark backdrop, nearly
        # unreadable (found in the final visual-program UAT). Chapter 3's
        # equivalent hero already avoids this by using the same #card frame
        # every other Science Lab hero/card uses, which carries its own
        # opaque theme-correct background in every theme; this mirrors that
        # exact, already-correct pattern instead of inventing a new one.
        hero = QFrame()
        hero.setObjectName("card")
        _allow_shrink(hero)
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(26, 22, 26, 22)
        layout.setSpacing(20)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)

        eyebrow = QLabel("CHAPTER 5")
        eyebrow.setObjectName("chapter5Eyebrow")
        eyebrow.setProperty("role", "cyan")
        eyebrow.setFont(make_font(11, 700, spacing=1.4))
        text_column.addWidget(eyebrow)

        heading = QLabel("RESULTS & DISCUSSION")
        heading.setObjectName("chapter5Heading")
        heading.setWordWrap(True)
        _allow_shrink(heading)
        heading.setFont(make_font(22, 800, spacing=0.6))
        text_column.addWidget(heading)

        subtitle = QLabel(
            "Interpret and present the analyzed results from Chapter 3 in thesis form."
        )
        subtitle.setObjectName("chapter5Subtitle")
        subtitle.setWordWrap(True)
        _allow_shrink(subtitle)
        subtitle.setFont(make_font(10.5, 400))
        text_column.addWidget(subtitle)

        layout.addLayout(text_column, 1)

        actions_column = QVBoxLayout()
        actions_column.setSpacing(8)
        self._history_button = QPushButton("SHOW HISTORY")
        self._history_button.setObjectName("chapter5HistoryButton")
        self._history_button.setFont(make_font(9.5, 700, spacing=0.3))
        self._history_button.setToolTip(
            "Browse every durable Science Lab experiment, independent of "
            "the current transferred result."
        )
        self._history_button.clicked.connect(self._handle_show_history)
        actions_column.addWidget(self._history_button, 0, Qt.AlignmentFlag.AlignRight)
        self._export_action = _ExportAction()
        self._export_action.export_requested.connect(self._handle_export_requested)
        actions_column.addWidget(self._export_action, 0, Qt.AlignmentFlag.AlignRight)
        layout.addLayout(actions_column, 0)

        return hero

    def _handle_show_history(self) -> None:
        """SHOW HISTORY click handler.

        Emits synchronously (same-thread Qt signal): by the time
        ``emit()`` returns, the connected application host has already
        called ``render_history_list``/``show_history_list_error``, so the
        dialog opens already populated.  Available even when
        ``_current_receipt`` is ``None``.
        """

        self.history_requested.emit()
        self._history_dialog.exec()

    def render_history_list(self, entries: "tuple[HistoryEntry, ...]") -> None:
        self._history_dialog.render_entries(entries)

    def show_history_list_error(self, message: str) -> None:
        self._history_dialog.show_list_error(message)

    def render_history_result(self, reconstruction: "HistoryReconstruction") -> None:
        self._history_dialog.render_result(reconstruction)

    def _handle_export_requested(self) -> None:
        """EXPORT PDF click handler (Phase 5).

        Gates strictly in order: read the current receipt, refuse if it is
        missing or not CERTIFIED, preserve the existing identity guard, and
        only then open the save dialog.  The frozen ``generate_report_pdf``
        receives this exact receipt object -- never a reconstruction from
        IDs, never a database read, never lifetime data -- and owns all
        destination-file safety itself; this handler does not duplicate it.
        """

        receipt = self._current_receipt
        if receipt is None:
            self._show_export_error(
                "No certified experiment is currently available to export."
            )
            return
        package = receipt.package
        if (
            not isinstance(package, Chapter3ResultPackage)
            or package.analysis_status != CERTIFIED
        ):
            self._show_export_error(
                "The current experiment package is not certified. Export refused."
            )
            return
        if (
            receipt.experiment_id != package.experiment_id
            or receipt.parent_session_id != package.parent_session_id
        ):
            self._show_export_error(
                "The certified receipt identity does not match its package. Export refused."
            )
            return

        default_name = _default_export_filename(package.experiment_id)
        path_text, _ = QFileDialog.getSaveFileName(
            self, "Export MYELIN Report PDF", default_name, "PDF Files (*.pdf)"
        )
        if not path_text:
            return  # Cancelled: silent, no generator call, no state change.

        output_path = _normalize_pdf_path(Path(path_text))
        try:
            saved_path = generate_report_pdf(receipt, output_path)
        except Exception as error:
            self._show_export_error(f"Report generation failed: {error}")
            return

        QMessageBox.information(
            self,
            "MYELIN Report",
            f"MYELIN Report PDF saved to:\n{saved_path}",
        )

    def _show_export_error(self, message: str) -> None:
        QMessageBox.warning(self, "MYELIN Report", message)


__all__ = [
    "Chapter5Presentation",
    "Chapter5ResultsView",
    "build_chapter5_presentation",
]
