"""MYELIN Control Station application launcher.

This file owns the visible application shell and the startup order.

The launcher has six clear duties:

1. create the Qt application;
2. show the real MYELIN startup loading screen;
3. run the required startup safety checks;
4. build the Control Station window and its pages;
5. connect the seven Control Station owners; and
6. hand shutdown requests to the lifecycle authority.

Important boundary
------------------
The launcher does not monitor Windows, classify activity, calculate SINE,
advance Study/COSECANT, write MIRL events, or decide database truth.  Those
jobs belong to their own authorities.  Keeping that boundary visible makes
the program easier to read and prevents the main window from becoming a
second engine.
"""

from __future__ import annotations

import ctypes
import math
import random
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Direct-file startup bootstrap
# ---------------------------------------------------------------------------
# Supports both:
#
#   python -m CONTROL_STATION.launcher
#
# and:
#
#   python CONTROL_STATION/launcher.py
#
# When launcher.py is executed directly Python does not assign its package,
# so relative imports such as ``from .analytics import ...`` would fail.
# Add the MYELIN2.0_ULTIMATE root to sys.path and establish the package name.
if __package__ in (None, ""):
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    _project_root_text = str(_PROJECT_ROOT)

    if _project_root_text not in sys.path:
        sys.path.insert(0, _project_root_text)

    __package__ = "CONTROL_STATION"
from datetime import datetime
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QLinearGradient,
    QCloseEvent,
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .analytics import AnalyticsController
from .controller import ControlStationController, EngineStatus
from .lifecycle import LifecycleController, StartupGateResult
from .navigation import NavigationController
from .settings import TIMEZONE_CHOICES, SettingsController
from .tray import TrayController
from COSECANT_STUDY_MODE.planner import StudyPlanner
from COSECANT_STUDY_MODE.view import StudyView
from PERSISTENCE.schema import ensure_production_schema
from PERSISTENCE.storage import EngineStorage
from PROFILES.profiles import ProfileController
from UI_THEMES.animation import (
    AxonCanvas,
    BarTrack,
    BrandMark,
    CircuitTrace,
    Dot,
    EngineRing,
    LoadingBackdrop,
    LoadingCornerTrace,
    LoadingLogoBadge,
    LoadingSweepBar,
    NavIcon,
)
from UI_THEMES.theme import (
    DEFAULT_THEME,
    qalpha,
    RADIUS_LG,
    RADIUS_MD,
    RADIUS_SM,
    ThemeController,
    apply_native_titlebar,
    build_application_stylesheet,
    card_shadow,
    label,
    make_font,
    mix,
    resource_icon,
    restyle,
)


APP_NAME: Final = "MYELIN — Control Station v2.0"
WINDOWS_APP_ID: Final = "MYELIN.ControlStation.2"
MINIMUM_WINDOW_SIZE: Final = QSize(1024, 700)
DEFAULT_WINDOW_SIZE: Final = QSize(1460, 960)

PAGE_CONTROL: Final = "control"
PAGE_STUDY: Final = "study-mode"
PAGE_METRIC_HUB: Final = "metric-hub"
PAGE_SCIENCE_LAB: Final = "science-lab"
PAGE_LIVE_MIRL: Final = "live-mirl"
PAGE_MINE: Final = "mine"
PAGE_COSINE: Final = "cosine"

PAGE_ORDER: Final = (
    PAGE_CONTROL,
    PAGE_STUDY,
    PAGE_METRIC_HUB,
    PAGE_SCIENCE_LAB,
    PAGE_LIVE_MIRL,
    PAGE_MINE,
    PAGE_COSINE,
)

STARTUP_MESSAGES: Final = (
    "Initializing Control Station",
    "Loading behavioral model",
    "Calibrating SINE stages",
    "Connecting telemetry feed",
)


@dataclass(frozen=True)
class ControlStationPages:
    """The real pages shown by the Control Station.

    A frozen page bundle prevents page order from being silently changed in
    several different parts of the program.  ``mine`` is a presentation-only
    placeholder: a real navigation destination whose subsystem does not exist
    yet.
    """

    control: QWidget
    study: QWidget
    metric_hub: QWidget
    science_lab: QWidget
    live_mirl: QWidget
    mine: QWidget
    cosine: QWidget

    def by_name(self) -> dict[str, QWidget]:
        return {
            PAGE_CONTROL: self.control,
            PAGE_STUDY: self.study,
            PAGE_METRIC_HUB: self.metric_hub,
            PAGE_SCIENCE_LAB: self.science_lab,
            PAGE_LIVE_MIRL: self.live_mirl,
            PAGE_MINE: self.mine,
            PAGE_COSINE: self.cosine,
        }


class ControlStationSidebar(QFrame):
    """Launcher-owned navigation drawer for the approved Control Station pages.

    Presentation follows the mockup's ``.sidebar``: a divided brand head,
    rows collected under CORE / RESEARCH group titles, an 18px stroke glyph
    per row and a hairline foot.  The navigation contract is unchanged --
    ``page_requested``, ``select``, ``set_navigation_enabled`` and
    ``set_open`` behave exactly as before, and every approved page is still
    reachable from here.

    SYSTEM carries one approved entry, SenseHub, marked COMING SOON.  It is
    built as a QFrame rather than a button so it has no ``clicked`` signal to
    connect at all, and it is kept out of ``_buttons`` and ``_rows`` so
    ``select`` and ``set_navigation_enabled`` cannot reach it.  The mockup's
    Settings and About rows stay removed.
    """

    page_requested = pyqtSignal(str)
    open_changed = pyqtSignal(bool)
    WIDTH: Final = 290

    LABELS: Final = {
        PAGE_CONTROL: "Control",
        PAGE_STUDY: "Study Mode",
        PAGE_METRIC_HUB: "Metric Hub",
        PAGE_SCIENCE_LAB: "Science Lab",
        PAGE_LIVE_MIRL: "Live MIRL",
        PAGE_MINE: "MINE",
        PAGE_COSINE: "COSINE",
    }

    GROUPS: Final = (
        ("Core", (PAGE_CONTROL, PAGE_STUDY, PAGE_METRIC_HUB)),
        ("Research", (PAGE_SCIENCE_LAB, PAGE_LIVE_MIRL, PAGE_MINE, PAGE_COSINE)),
    )
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(self.WIDTH)
        self._buttons: dict[str, QPushButton] = {}
        self._rows: dict[str, tuple[NavIcon, QLabel]] = {}
        self._selected = PAGE_CONTROL
        self._is_open = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 20, 0, 14)
        layout.setSpacing(0)
        layout.addWidget(self._build_head())
        layout.addSpacing(14)

        # ``.sidebar-scroll`` -- the 10px inset the rows and titles sit inside.
        nav_host = QWidget(self)
        nav_host.setObjectName("plainBox")
        nav = QVBoxLayout(nav_host)
        nav.setContentsMargins(10, 0, 10, 0)
        nav.setSpacing(0)

        for group_title, page_names in self.GROUPS:
            nav.addWidget(self._group_title(group_title))
            for page_name in page_names:
                nav.addWidget(self._nav_row(page_name, self.LABELS[page_name]))
            nav.addSpacing(16)

        nav.addWidget(self._group_title("System"))
        nav.addWidget(self._coming_soon_row("sensehub", "SenseHub"))

        layout.addWidget(nav_host)
        layout.addStretch(1)
        layout.addWidget(self._build_foot())

        self.select(PAGE_CONTROL)
        self.hide()

        self._animation = QPropertyAnimation(self, b"pos", self)
        self._animation.setDuration(250)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._animation.finished.connect(self._animation_finished)

    # -- composition ------------------------------------------------------

    def _build_head(self) -> QWidget:
        """``.sidebar-head`` -- brand mark, wordmark and the dividing rule."""

        head = QWidget(self)
        head.setObjectName("sidebarHead")
        row = QHBoxLayout(head)
        row.setContentsMargins(20, 0, 20, 18)
        row.setSpacing(10)
        row.addWidget(BrandMark(26))

        wordmark = QWidget(head)
        wordmark.setObjectName("plainBox")
        marks = QHBoxLayout(wordmark)
        marks.setContentsMargins(0, 0, 0, 0)
        marks.setSpacing(0)
        name = label("MYELIN", 15, 800, "text", spacing=3.0)
        name.setObjectName("sidebarBrand")
        marks.addWidget(name)
        accent = label(" · core", 15, 800, "cyan", spacing=3.0)
        accent.setObjectName("sidebarBrandAccent")
        marks.addWidget(accent)
        row.addWidget(wordmark)
        row.addStretch(1)
        return head

    def _build_foot(self) -> QWidget:
        """``.sidebar-foot`` -- the closing hairline and a quiet identity line.

        The mockup's light/dark toggle is intentionally absent: MYELIN ships
        one canonical dark theme, and a control that cannot change anything
        would be a dead affordance.
        """

        foot = QWidget(self)
        foot.setObjectName("sidebarFoot")
        row = QVBoxLayout(foot)
        row.setContentsMargins(20, 14, 20, 2)
        row.setSpacing(0)
        note = label("CONTROL STATION v2.0", 9.5, 600, "muted", mono=True, spacing=1.4)
        note.setObjectName("sidebarFootNote")
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        row.addWidget(note)
        return foot

    def _coming_soon_row(self, key: str, text: str) -> QFrame:
        """An approved, deliberately inert COMING SOON marker.

        This is not a disabled button -- it is a QFrame, so there is no
        ``clicked`` signal in existence to connect, nothing is added to
        ``_buttons`` or ``_rows``, and ``page_requested`` can never carry its
        name.  ``set_navigation_enabled(True)`` has no route to it.  Mouse
        events pass straight through, so it cannot even take a press.

        It announces a future capability.  It creates no page, no runtime and
        no hardware connection of any kind.
        """

        row = QFrame(self)
        row.setObjectName("sidebarComingSoonRow")
        row.setMinimumHeight(42)
        row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row.setAccessibleName(f"{text} — coming soon, not yet available")

        line = QHBoxLayout(row)
        line.setContentsMargins(12, 11, 12, 11)
        line.setSpacing(13)

        dim = mix(DEFAULT_THEME.muted, 55, DEFAULT_THEME.surface_soft)
        icon = NavIcon(key, row)
        icon.set_colour(dim)
        line.addWidget(icon)

        name = label(text, 13.5, 400, "muted")
        name.setObjectName("comingSoonLabel")
        line.addWidget(name, 1)

        badge = label("COMING SOON", 9.0, 700, "muted", mono=True, spacing=0.6)
        badge.setObjectName("comingSoonBadge")
        line.addWidget(badge)
        return row

    def _group_title(self, text: str) -> QLabel:
        """``.nav-group-title`` -- 10.5px cyan caption above each group."""

        title = label(text, 10.5, 700, "cyan", spacing=2.2, upper=True)
        title.setObjectName("navGroupTitle")
        title.setContentsMargins(10, 0, 10, 4)
        return title

    def _nav_row(self, page_name: str, text: str) -> QPushButton:
        """``.nav-row`` -- one 18px glyph beside a 13.5px label.

        The glyph is a child widget rather than a QSS ``image``, so it is told
        its colour by ``_paint_row`` whenever checked or enabled state moves.
        """

        button = QPushButton(self)
        button.setObjectName("sidebarNavigationButton")
        button.setCheckable(True)
        button.setAccessibleName(f"Open {text}")
        # QPushButton sizes itself from its own (empty) text, so the child
        # layout has to be given the row height the mockup asks for.
        button.setMinimumHeight(42)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(button)
        row.setContentsMargins(12, 11, 12, 11)
        row.setSpacing(13)
        icon = NavIcon(page_name, button)
        row.addWidget(icon)
        row_label = label(text, 13.5, 400, "text")
        row_label.setObjectName("navRowLabel")
        row_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        row.addWidget(row_label, 1)

        button.setProperty("pageName", page_name)
        button.clicked.connect(
            lambda checked=False, name=page_name: self._request_page(name)
        )
        self._buttons[page_name] = button
        self._rows[page_name] = (icon, row_label)
        self._paint_row(page_name, False)
        return button

    def _request_page(self, page_name: str) -> None:
        """Ask for a page.  The navigation authority decides what is selected.

        A checkable QPushButton toggles itself the instant it is pressed, so
        without this the pressed row would light up immediately while the
        outgoing row stayed lit until the transition finished -- two rows
        selected at once -- and a row would still light up for a navigation
        the authority goes on to reject.  Selection truth belongs to
        ``select()``, which NavigationController calls once a page has
        actually been activated, so the click is undone here and only the
        request is emitted.
        """

        self.select(self._selected)
        self.page_requested.emit(page_name)

    def _paint_row(self, page_name: str, active: bool) -> None:
        """Give one row the colour its state earns; no state is decided here."""

        icon, row_label = self._rows[page_name]
        if not self._buttons[page_name].isEnabled():
            colour, role = mix(DEFAULT_THEME.muted, 55, DEFAULT_THEME.surface_soft), "muted"
        elif active:
            colour, role = DEFAULT_THEME.cyan, "cyan"
        else:
            colour, role = DEFAULT_THEME.muted, "text"
        icon.set_colour(colour)
        if row_label.property("role") != role:
            row_label.setProperty("role", role)
            restyle(row_label)

    # -- navigation contract (unchanged) ----------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    def select(self, page_name: str) -> None:
        self._selected = page_name
        for name, button in self._buttons.items():
            button.setChecked(name == page_name)
            self._paint_row(name, name == page_name)

    def set_navigation_enabled(self, enabled: bool) -> None:
        for name, button in self._buttons.items():
            button.setEnabled(bool(enabled))
            self._paint_row(name, button.isChecked())

    def set_open(self, open_drawer: bool, *, animate: bool = True) -> None:
        target = bool(open_drawer)
        if (
            target == self._is_open
            and self._animation.state() is QAbstractAnimation.State.Stopped
        ):
            return

        self._is_open = target
        self.open_changed.emit(target)
        self._animation.stop()
        if target:
            if not self.isVisible():
                self.move(-self.width(), 0)
            self.show()
            self.raise_()

        end = QPoint(0 if target else -self.width(), 0)
        if not animate:
            self.move(end)
            if not target:
                self.hide()
            return

        self._animation.setStartValue(self.pos())
        self._animation.setEndValue(end)
        self._animation.start()

    def _animation_finished(self) -> None:
        if not self._is_open:
            self.hide()


class StartupLoadingScreen(QWidget):
    """The real startup screen shown before the main window.

    The visual drawing and animation classes are shared through
    ``UI_THEMES.animation``.  This launcher owns their arrangement, timer
    lifecycle and the handoff to the Control Station.

    The loading screen is presentation only.  It never reads telemetry or
    changes MYELIN state.
    """

    DEFAULT_SIZE: Final = QSize(1000, 720)
    DOT_INTERVAL_MS: Final = 350
    MESSAGE_INTERVAL_MS: Final = 1800

    def __init__(
        self,
        *,
        logo_path: str,
        messages: Sequence[str] = STARTUP_MESSAGES,
        parent: QWidget | None = None,
    ) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        super().__init__(parent, flags)

        self.setObjectName("myelinStartupLoadingScreen")
        self.setWindowTitle("MYELIN — Loading")
        self.resize(self.DEFAULT_SIZE)

        self._messages = tuple(messages) or ("Initializing Control Station",)
        self._message_index = 0
        self._dot_step = 0
        self._status_is_pinned = False
        self._base_status = self._messages[0]

        # These widgets preserve the original loading-screen design.  They
        # contain decoration only and have no authority over the engine.
        self._backdrop = LoadingBackdrop(self)
        self._top_trace = LoadingCornerTrace(rotated=False, delay_ms=0, parent=self)
        self._bottom_trace = LoadingCornerTrace(
            rotated=True,
            delay_ms=1400,
            parent=self,
        )

        self._panel = QWidget(self)
        self._panel.setObjectName("loadingPanel")
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(0)
        panel_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._logo = LoadingLogoBadge(logo_path=logo_path)
        panel_layout.addWidget(self._logo, 0, Qt.AlignmentFlag.AlignHCenter)
        panel_layout.addSpacing(14)

        wordmark = QLabel("MYELIN")
        wordmark.setObjectName("loadingWordmark")
        wordmark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wordmark.setFont(make_font(44, 800, spacing=14.0))
        wordmark.setContentsMargins(0, 0, 14, 0)
        panel_layout.addWidget(wordmark, 0, Qt.AlignmentFlag.AlignHCenter)
        panel_layout.addSpacing(14)

        tagline = QLabel("GUIDE – RECOVER – FOCUS")
        tagline.setObjectName("loadingTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setFont(make_font(13, 400, mono=True, spacing=5.0))
        tagline.setContentsMargins(0, 0, 5, 0)
        panel_layout.addWidget(tagline, 0, Qt.AlignmentFlag.AlignHCenter)
        panel_layout.addSpacing(46)

        self._status = QLabel(self._base_status)
        self._status.setObjectName("loadingStatus")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setFont(make_font(13, 400))
        panel_layout.addWidget(self._status, 0, Qt.AlignmentFlag.AlignHCenter)
        panel_layout.addSpacing(18)

        self._progress = LoadingSweepBar()
        panel_layout.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignHCenter)

        self._version = QLabel(
            "MYELIN Core v2.0  ·  Behavioral Telemetry Interface",
            self,
        )
        self._version.setObjectName("loadingVersion")
        self._version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._version.setFont(make_font(10.5, 400, mono=True, spacing=1.0))

        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._advance_dots)

        self._message_timer = QTimer(self)
        self._message_timer.timeout.connect(self._advance_message)

    def start(self) -> None:
        """Show the loading screen and start every decorative timer."""

        self._centre_on_active_screen()
        self.show()

        for animation in self._animations():
            animation.start()

        self._dot_timer.start(self.DOT_INTERVAL_MS)
        self._message_timer.start(self.MESSAGE_INTERVAL_MS)
        self.raise_()
        self.activateWindow()

    def stop(self) -> None:
        """Stop all loading-screen activity. Safe to call more than once."""

        for animation in self._animations():
            animation.stop()

        self._dot_timer.stop()
        self._message_timer.stop()

    def set_status(self, text: str) -> None:
        """Show a factual startup stage instead of the rotating text."""

        self._status_is_pinned = True
        self._message_timer.stop()
        self._base_status = str(text)
        self._render_status()

    def finish(self, window: QWidget) -> None:
        """Stop the splash before showing the completed Control Station."""

        self.stop()
        self.close()
        window.show()
        window.raise_()
        window.activateWindow()

    def _animations(self) -> tuple[object, ...]:
        return (
            self._backdrop,
            self._top_trace,
            self._bottom_trace,
            self._logo,
            self._progress,
        )

    def _centre_on_active_screen(self) -> None:
        # Open on the monitor the user is actively using. This preserves the
        # old multi-monitor behavior instead of always choosing monitor one.
        screen = QGuiApplication.screenAt(QCursor.pos())
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return

        available = screen.availableGeometry()
        size = self.DEFAULT_SIZE.boundedTo(available.size() * 0.9)
        self.resize(size)
        self.move(available.center() - self.rect().center())

    def _advance_dots(self) -> None:
        self._dot_step = (self._dot_step + 1) % 4
        self._render_status()

    def _advance_message(self) -> None:
        if self._status_is_pinned:
            return

        self._message_index = (self._message_index + 1) % len(self._messages)
        self._base_status = self._messages[self._message_index]
        self._render_status()

    def _render_status(self) -> None:
        self._status.setText(self._base_status + "." * self._dot_step)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._top_trace.move(26, 26)
        self._bottom_trace.move(
            self.width() - self._bottom_trace.width() - 26,
            self.height() - self._bottom_trace.height() - 26,
        )

        panel_size = self._panel.sizeHint()
        self._panel.setGeometry(
            int((self.width() - panel_size.width()) / 2),
            int((self.height() - panel_size.height()) / 2),
            panel_size.width(),
            panel_size.height(),
        )
        self._version.setGeometry(0, self.height() - 36, self.width(), 16)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.stop()
        super().closeEvent(event)


class BrandConsole(QWidget):
    """MYELIN -- core wordmark flanked by decorative circuit traces.

    The wordmark itself is pinned to its natural width so a tight topbar
    drops the decorative traces first rather than clipping "MYELIN" to
    "MYE" -- see ``title_width``/``traces_width`` and the shell's own
    ``_fit_topbar`` below.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        self.trace_left = CircuitTrace(False, 0)
        self.trace_right = CircuitTrace(True, 1100)
        lay.addWidget(self.trace_left)

        title = QWidget()
        title.setObjectName("plainBox")
        tl = QVBoxLayout(title)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        logo_row = QWidget()
        logo_row.setObjectName("plainBox")
        lrl = QHBoxLayout(logo_row)
        lrl.setContentsMargins(0, 0, 0, 0)
        lrl.setSpacing(10)
        lrl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lrl.addWidget(BrandMark(26))
        name = QWidget()
        name.setObjectName("plainBox")
        nl = QHBoxLayout(name)
        nl.setContentsMargins(0, 0, 0, 0)
        nl.setSpacing(0)
        nl.addWidget(label("MYELIN", 25, 800, "text", spacing=7.0))
        dash = label("\u2014", 25, 400, "muted", spacing=2.0)
        dash.setContentsMargins(2, 0, 2, 0)
        nl.addWidget(dash)
        core = label("core", 25, 600, "cyan", spacing=3.0)
        core.setContentsMargins(8, 0, 0, 0)
        nl.addWidget(core)
        lrl.addWidget(name)
        tl.addWidget(logo_row)
        tl.addSpacing(8)

        tagline = QWidget()
        tagline.setObjectName("plainBox")
        tgl = QHBoxLayout(tagline)
        tgl.setContentsMargins(0, 0, 0, 0)
        tgl.setSpacing(0)
        tgl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for index, word in enumerate(("GUIDE", "RECOVER", "FOCUS")):
            if index:
                sep = label("\u2013", 10.5, 400, "cyan", mono=True, spacing=3.0)
                sep.setContentsMargins(2, 0, 2, 0)
                tgl.addWidget(sep)
            tgl.addWidget(label(word, 10.5, 400, "muted", mono=True, spacing=3.0))
        tl.addWidget(tagline)

        self.title = title
        for widget in title.findChildren(QLabel):
            widget.setFixedWidth(widget.sizeHint().width())
        title.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        title.setMinimumWidth(title.sizeHint().width())

        lay.addWidget(title)
        lay.addWidget(self.trace_right)

    def start(self) -> None:
        self.trace_left.start()
        self.trace_right.start()

    def stop(self) -> None:
        self.trace_left.stop()
        self.trace_right.stop()

    def set_traces_visible(self, visible: bool) -> None:
        if self.trace_left.isVisible() == visible:
            return
        self.trace_left.setVisible(visible)
        self.trace_right.setVisible(visible)

    def title_width(self) -> int:
        return self.title.sizeHint().width()

    def traces_width(self) -> int:
        """Smallest width the two traces need before they should be hidden."""

        return int(2 * CircuitTrace.MIN_W + 2 * self.layout().spacing())


class NeonTopBar(QWidget):
    """The header strip and the neon wash behind it.

    The mockup lights the whole page with soft cyan ellipses laid over
    ``--base``; this paints the part of that wash the header sits in, so the
    top of the window carries the glow instead of reading as flat base
    colour.  The ellipses are positioned against the window height, not the
    strip height, so the wash keeps the mockup's geometry rather than being
    squashed into the header.

    Decorative only.  It carries no biological, neurological, diagnostic or
    evidence meaning, and it reports nothing.
    """

    #: centre x (fraction of width), centre y (fraction of window height),
    #: horizontal radius, vertical radius, cyan strength -- the mockup's
    #: ``body`` background ellipses, plus a centred header wash.
    GLOWS: Final = (
        (0.12, -0.08, 950.0, 600.0, 0.10),
        (0.50, -0.02, 900.0, 520.0, 0.055),
        (0.88, -0.08, 950.0, 600.0, 0.08),
    )

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.fillRect(rect, QColor(DEFAULT_THEME.window_background))

        window = self.window()
        page_height = float(max(self.height(), window.height() if window else 0))
        cyan = QColor(DEFAULT_THEME.cyan)

        painter.setPen(Qt.PenStyle.NoPen)
        for cx, cy, radius_x, radius_y, strength in self.GLOWS:
            painter.save()
            painter.translate(rect.width() * cx, page_height * cy)
            painter.scale(1.0, radius_y / radius_x)
            glow = QRadialGradient(QPointF(0.0, 0.0), radius_x)
            glow.setColorAt(0.0, qalpha(cyan, strength))
            glow.setColorAt(1.0, qalpha(cyan, 0.0))
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(QPointF(0.0, 0.0), radius_x, radius_x)
            painter.restore()

        # Settle the wash back into the page colour before the bottom edge, so
        # the strip meets the page below without a visible seam at whatever
        # height the clock happens to give it.
        base = QColor(DEFAULT_THEME.window_background)
        fade = QLinearGradient(
            QPointF(0.0, rect.height() * 0.52),
            QPointF(0.0, rect.height()),
        )
        fade.setColorAt(0.0, qalpha(base, 0.0))
        fade.setColorAt(1.0, qalpha(base, 1.0))
        painter.fillRect(rect, QBrush(fade))
        painter.end()


class SidebarBackdrop(QWidget):
    """Click-catcher shown behind the open navigation drawer.

    The mockup's ``.sidebar-backdrop``: pressing anywhere outside the drawer
    dismisses it, so the drawer no longer has to be closed with the same MENU
    button that opened it.  It only reports the press; the navigation
    authority still decides whether the drawer actually closes.
    """

    dismissed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebarBackdrop")
        self.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.dismissed.emit()
        event.accept()


class ControlStationShell(QWidget):
    """Main Control Station layout: top bar, sidebar and page area.

    This class arranges real widgets.  Navigation decisions remain inside
    ``NavigationController`` and theme decisions remain inside
    ``ThemeController``.
    """

    menu_requested = pyqtSignal()
    sidebar_dismiss_requested = pyqtSignal()
    clock_visibility_requested = pyqtSignal()
    analytics_requested = pyqtSignal()

    def __init__(
        self,
        *,
        clock: QWidget,
        brand: QWidget,
        sidebar: QWidget,
        page_stack: QStackedWidget,
        loading_overlay: QWidget,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("controlStationRoot")

        self.clock = clock
        self.brand = brand
        self.sidebar = sidebar
        self.page_stack = page_stack
        self.loading_overlay = loading_overlay

        self._build_layout()

    def _build_layout(self) -> None:
        """Rebuild the approved shell structure without owning any policy."""

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top_bar = NeonTopBar(self)
        top_bar.setObjectName("topBar")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(34, 24, 34, 10)
        top_layout.setSpacing(16)

        # Three columns, the outer two equally weighted: the wordmark then sits
        # at the true centre of the window however wide the clock or the
        # right-hand buttons happen to be.  Bare stretches could not do this --
        # they balanced the leftover space, not the columns, leaving the
        # wordmark off centre by the difference between the two sides.
        left = QWidget(top_bar)
        left.setObjectName("plainBox")
        left_layout = QHBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(16)
        menu_button = QPushButton("☰ MENU")
        menu_button.setObjectName("menuButton")
        menu_button.clicked.connect(self.menu_requested.emit)
        left_layout.addWidget(menu_button)
        left_layout.addWidget(self.clock)
        left_layout.addStretch(1)
        top_layout.addWidget(left, 1)

        # AlignCenter matters: without it the console is stretched to the full
        # height of the strip and its own column layout pushes the wordmark and
        # the tagline to opposite ends of that height.
        top_layout.addWidget(self.brand, 0, Qt.AlignmentFlag.AlignCenter)

        right = QWidget(top_bar)
        right.setObjectName("plainBox")
        right_layout = QHBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)
        right_layout.addStretch(1)
        self.clock_button = QPushButton("Hide Clock")
        self.clock_button.setObjectName("topbarClock")
        self.clock_button.clicked.connect(self.clock_visibility_requested.emit)
        right_layout.addWidget(self.clock_button)

        analytics_button = QPushButton("GET CHART")
        analytics_button.setObjectName("topbarChart")
        analytics_button.clicked.connect(self.analytics_requested.emit)
        right_layout.addWidget(analytics_button)
        top_layout.addWidget(right, 1)

        self._topbar_left_width = lambda: menu_button.sizeHint().width() + self.clock.sizeHint().width()
        self._topbar_right_width = lambda: self.clock_button.sizeHint().width() + analytics_button.sizeHint().width()
        self._top_layout = top_layout

        root_layout.addWidget(top_bar)
        root_layout.addWidget(self.page_stack, 1)

        # The sidebar and loading overlay float above the page stack exactly as
        # before. Their controllers decide when they are visible.
        self.sidebar_backdrop = SidebarBackdrop(self)
        self.sidebar_backdrop.dismissed.connect(self.sidebar_dismiss_requested.emit)

        self.sidebar.setParent(self)
        self.loading_overlay.setParent(self)
        self.sidebar_backdrop.raise_()
        self.sidebar.raise_()
        self.loading_overlay.raise_()

        opened = getattr(self.sidebar, "open_changed", None)
        if opened is not None:
            opened.connect(self._sidebar_open_changed)

    def _sidebar_open_changed(self, opened: bool) -> None:
        """Show the click-catcher for exactly as long as the drawer is open."""

        self.sidebar_backdrop.setGeometry(self.rect())
        self.sidebar_backdrop.setVisible(bool(opened))
        if opened:
            self.sidebar_backdrop.raise_()
            self.sidebar.raise_()

    def set_clock_visible(self, visible: bool) -> None:
        self.clock.setVisible(bool(visible))
        self.clock_button.setText("Hide Clock" if visible else "Show Clock")

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        bounds = self.rect()
        self.sidebar.setFixedHeight(bounds.height())
        self.sidebar_backdrop.setGeometry(bounds)
        self.loading_overlay.setGeometry(bounds)
        self._fit_topbar()

    def _fit_topbar(self) -> None:
        """Drop the wordmark's decorative traces before anything squeezes.

        The wordmark itself is pinned to its natural width (see
        ``BrandConsole``); this only decides whether there is still room
        either side of it for the circuit traces.
        """

        if not isinstance(self.brand, BrandConsole):
            return
        margins = self._top_layout.contentsMargins()
        spacing = self._top_layout.spacing()
        base = (
            self._topbar_left_width()
            + self._topbar_right_width()
            + self.brand.title_width()
            + margins.left() + margins.right()
            + spacing * 5
        )
        self.brand.set_traces_visible(self.width() >= base + self.brand.traces_width())


def make_card(padding: int = 22, shadow: bool = True) -> tuple[QFrame, QVBoxLayout]:
    """Donor card language: radius 22, 1px border, soft shadow."""

    card = QFrame()
    card.setObjectName("card")
    card.setFrameShape(QFrame.Shape.NoFrame)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(padding, padding, padding, padding)
    lay.setSpacing(0)
    if shadow:
        card_shadow(card)
    return card, lay


def card_head(title: str, hint: str | None = None, dot: bool = False) -> tuple[QWidget, QLabel]:
    """Donor card head: optional dot, uppercase title, right-aligned hint."""

    host = QWidget()
    host.setObjectName("plainBox")
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(7)
    if dot:
        lay.addWidget(Dot(5, "cyan"))
    lay.addWidget(label(title, 12.5, 700, "muted", spacing=1.4, upper=True))
    lay.addStretch(1)
    hint_label = label(hint or "", 11.5, 400, "muted")
    lay.addWidget(hint_label)
    return host, hint_label


def stat_box(caption: str, value: str, role: str = "text", value_size: float = 24.0):
    """Donor stat box: uppercase caption above a mono value."""

    box = QFrame()
    box.setObjectName("statBox")
    box.setFrameShape(QFrame.Shape.NoFrame)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(6)
    lay.addWidget(label(caption, 11, 400, "muted", spacing=1.0, upper=True))
    number = label(value, value_size, 600, role, mono=True)
    lay.addWidget(number)
    return box, number


def bar_row(caption: str, colour: str = "cyan", label_w: int = 108):
    """Donor bar row: fixed caption, BarTrack, right-aligned mono value."""

    host = QWidget()
    host.setObjectName("plainBox")
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    cap = label(caption, 12.5, 400, "muted")
    cap.setFixedWidth(label_w)
    lay.addWidget(cap)
    track = BarTrack(0.0, colour)
    lay.addWidget(track, 1)
    value = label("\u2014", 12, 400, "muted", mono=True)
    value.setFixedWidth(44)
    value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(value)
    return host, track, value


class FeedTag(QLabel):
    """Rounded telemetry tag; tone is a property so QSS colours it."""

    def __init__(self, text: str, tone: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setObjectName("feedTag")
        if tone:
            self.setProperty("tone", tone)
        self.setFont(make_font(10, 600, spacing=0.6))


class HeroCard(QFrame):
    """Engine Core: radial-tinted card, decorative axon canvas, ring, controls."""

    study_mode_requested = pyqtSignal()

    def __init__(self, profiles, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("heroCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.canvas = AxonCanvas(self)
        self.canvas.lower()
        self.canvas.start()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 22)
        lay.setSpacing(0)

        header = QWidget()
        header.setObjectName("plainBox")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(7)
        header_layout.addWidget(Dot(5, "cyan"))
        header_layout.addWidget(label("Engine Core", 11, 700, "muted", spacing=2.0, upper=True))
        header_layout.addStretch(1)

        self.study_mode_btn = QPushButton("STUDY MODE", self)
        self.study_mode_btn.setObjectName("studyModeButton")
        self.study_mode_btn.setFont(make_font(11, 700, spacing=0.5))
        self.study_mode_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.study_mode_btn.setAccessibleName("Open COSECANT Study Mode")
        self.study_mode_btn.setToolTip("Open Study Mode inside this Control Station")
        self.study_mode_btn.setMinimumSize(112, 32)
        self.study_mode_btn.clicked.connect(self.study_mode_requested.emit)
        header_layout.addWidget(self.study_mode_btn)

        profile_btn = QFrame(self)
        profile_btn.setObjectName("profileButton")
        profile_btn.setFrameShape(QFrame.Shape.NoFrame)
        profile_btn.setMinimumHeight(32)
        profile_layout = QHBoxLayout(profile_btn)
        profile_layout.setContentsMargins(10, 4, 6, 4)
        profile_layout.setSpacing(4)
        prefix = label("Profile: ", 11, 400, "muted", spacing=0.4)
        prefix.setObjectName("profileButtonPrefix")
        profile_layout.addWidget(prefix)
        self.profile = QComboBox(profile_btn)
        self.profile.setObjectName("profileButtonValue")
        self.profile.setFont(make_font(11, 700, spacing=0.4))
        self.profile.setAccessibleName("Choose active MYELIN profile")
        for spec in profiles.all_profiles():
            self.profile.addItem(spec.label, spec.key)
        profile_layout.addWidget(self.profile)
        header_layout.addWidget(profile_btn)
        lay.addWidget(header)
        lay.addSpacing(14)

        inner = QWidget()
        inner.setObjectName("plainBox")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.setSpacing(0)
        il.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.status_pill = label("ENGINE IDLE", 11, 700, "muted", spacing=1.2, upper=True)
        self.status_pill.setObjectName("statusPill")
        il.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignHCenter)
        il.addSpacing(16)

        self.ring = EngineRing()
        il.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignHCenter)
        il.addSpacing(18)

        controls = QWidget()
        controls.setObjectName("plainBox")
        controls.setFixedWidth(360)
        cl = QHBoxLayout(controls)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(10)
        self.buttons: dict[str, QPushButton] = {}
        for key, name, text in (
            ("start", "btnStart", "Start"),
            ("pause", "btnPause", "Pause"),
            ("stop", "btnStop", "Stop"),
        ):
            button = QPushButton(text.upper(), self)
            button.setObjectName(name)
            button.setFont(make_font(12, 700, spacing=0.8))
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            cl.addWidget(button, 1)
            self.buttons[key] = button
        il.addWidget(controls, 0, Qt.AlignmentFlag.AlignHCenter)
        il.addSpacing(10)

        self.btn_emergency = QPushButton("EMERGENCY", self)
        self.btn_emergency.setObjectName("btnEmergency")
        self.btn_emergency.setFont(make_font(13, 800, spacing=1.6))
        self.btn_emergency.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_emergency.setFixedWidth(360)
        il.addWidget(self.btn_emergency, 0, Qt.AlignmentFlag.AlignHCenter)

        lay.addWidget(inner, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.canvas.setGeometry(self.rect())

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        from UI_THEMES.theme import DEFAULT_THEME as t

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        grad = QRadialGradient(
            QPointF(rect.width() * 0.5, rect.height() * 0.18), rect.width() * 0.62
        )
        grad.setColorAt(0.0, QColor(mix(t.cyan, 10, t.surface)))
        grad.setColorAt(1.0, QColor(t.surface))
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS_LG, RADIUS_LG)
        p.fillPath(path, QBrush(grad))
        pen = QPen(QColor(t.border))
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.end()


class FeedList(QWidget):
    """Donor feed: newest-first rows of dot / time / message / tag."""

    MAX_ROWS: Final = 80

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self._count = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        host = QWidget(self._scroll)
        host.setObjectName("plainBox")
        self._rows = QVBoxLayout(host)
        self._rows.setContentsMargins(0, 0, 6, 0)
        self._rows.setSpacing(2)
        self._rows.addStretch(1)
        self._scroll.setWidget(host)
        outer.addWidget(self._scroll)

    @property
    def count(self) -> int:
        return self._count

    def append(self, *, time_text: str, text: str, tag: str, tone: str = "") -> None:
        row = QFrame()
        row.setObjectName("feedItem")
        row.setFrameShape(QFrame.Shape.NoFrame)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(12)

        layout.addWidget(Dot(8, tone or "cyan", glow=False))
        stamp = label(time_text, 12.5, 400, "muted", mono=True)
        stamp.setFixedWidth(56)
        layout.addWidget(stamp)
        body = label(text, 12.5, 400, "text")
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(body, 1)
        if tag:
            layout.addWidget(FeedTag(tag, tone))

        self._rows.insertWidget(0, row)
        self._count += 1
        while self._rows.count() - 1 > self.MAX_ROWS:
            item = self._rows.takeAt(self._rows.count() - 2)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()


class ComingSoonPage(QWidget):
    """Presentation-only placeholder for an approved but unbuilt workspace.

    It renders a name, the expansion of that name and a COMING SOON marker.
    It holds no state, owns no timer, reads no telemetry, connects to no
    signal and calls no runtime.  It exists so that the destination is real
    for navigation while the subsystem behind it is not yet built.

    It deliberately exposes neither ``request_refresh`` nor a ``ready``
    signal: NavigationController treats a page without them as ready on the
    next event-loop turn, which is the correct behaviour for a static page.
    """

    def __init__(
        self,
        title: str,
        expansion: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("comingSoonPage")
        self.setAccessibleName(f"{title} — {expansion}, coming soon")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(34, 24, 34, 34)
        root_layout.addStretch(1)

        card, body = make_card()
        card.setObjectName("comingSoonCard")
        card.setFixedWidth(520)
        body.setContentsMargins(38, 34, 38, 34)
        body.setSpacing(0)

        name = label(title, 26, 800, "text", mono=True, spacing=4.0)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(name)
        body.addSpacing(10)

        meaning = label(expansion, 13, 400, "muted", wrap=True)
        meaning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(meaning)
        body.addSpacing(24)

        badge_row = QHBoxLayout()
        badge_row.addStretch(1)
        badge = label("COMING SOON", 10, 700, "cyan", mono=True, spacing=1.8)
        badge.setObjectName("comingSoonPageBadge")
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        body.addLayout(badge_row)

        centre = QHBoxLayout()
        centre.addStretch(1)
        centre.addWidget(card)
        centre.addStretch(1)
        root_layout.addLayout(centre)
        root_layout.addStretch(1)


# ---------------------------------------------------------------------------
# Launcher showcase surfaces
# ---------------------------------------------------------------------------
# The visual body of the Metric Hub, reproduced from the approved mockup
# (``myelin_v2_mockup_2.html``, ``#page-metric-hub``).
#
# These surfaces are PRESENTATION FIXTURES.  They read no database, subscribe
# to no engine signal, own no timer and calculate no MYELIN metric.  Every
# number below is a fixed demonstration value copied from the mockup so the
# visual body can be reviewed before the real data nerves are connected in a
# later approved phase.  Nothing here is authoritative and nothing here may be
# read as a MYELIN observation.

#: mockup ``latencyData`` -- bar heights are v/1671, red above the 300s target.
_SHOWCASE_METRIC_LATENCY: Final = (
    520, 1671, 40, 880, 1520, 35, 45, 60, 650, 45, 40,
    780, 820, 55, 730, 60, 45, 55, 40, 980, 300, 1180,
)
_SHOWCASE_METRIC_LATENCY_MAX: Final = 1671
_SHOWCASE_METRIC_TARGET: Final = 300
_SHOWCASE_METRIC_AVG: Final = 301

#: mockup ``scatterData`` -- (x%, y%) from the left/bottom of the plot box.
_SHOWCASE_METRIC_SCATTER: Final = (
    (3, 2), (8, 2), (12, 58), (16, 60), (19, 58), (22, 60), (26, 58),
    (30, 60), (34, 55), (70, 58), (46, 2), (52, 2), (58, 60), (63, 2),
    (68, 2), (74, 55), (80, 60), (86, 60), (92, 2), (97, 45),
)

_SHOWCASE_METRIC_DRIFT: Final = (
    ("1", "22:36:36", "Session #95", "youtube", "Engagement Drift", "1671s"),
    ("2", "12:26:41", "Session #70", "youtube", "Youtube Dwell", "1493s"),
    ("3", "20:41:07", "Session #38", "youtube", "Youtube Dwell", "1427s"),
    ("4", "22:44:53", "Session #84", "youtube", "Youtube Dwell", "1423s"),
    ("5", "12:41:58", "Session #77", "youtube", "Youtube Dwell", "1262s"),
)

_SHOWCASE_METRIC_DONUT: Final = (
    ("Social Media", 66, 93.0, "green"),
    ("Messaging", 5, 7.0, "rose"),
)


def _showcase_colour(role: str) -> QColor:
    """Resolve one mockup palette name against the live theme."""

    table = {
        "cyan": DEFAULT_THEME.cyan,
        "green": DEFAULT_THEME.green,
        "amber": DEFAULT_THEME.amber,
        "red": DEFAULT_THEME.red,
        "muted": DEFAULT_THEME.muted,
        "text": DEFAULT_THEME.text_primary,
        "rose": "#FB7185",
        "blue": "#60A5FA",
    }
    return QColor(table.get(role, role))


class ShowcaseBarChart(QWidget):
    """``.barchart`` -- flex-end bars over a left/bottom axis rule.

    Presentation fixture: it paints the numbers it is handed and nothing more.
    No value here is measured, derived or stored.
    """

    def __init__(
        self,
        values: Sequence[int],
        maximum: int,
        target: int,
        average: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedHeight(210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._values = tuple(values)
        self._maximum = max(1, int(maximum))
        self._target = int(target)
        self._average = int(average)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())

        axis = QPen(QColor(DEFAULT_THEME.border))
        axis.setWidthF(1.0)
        p.setPen(axis)
        p.drawLine(QPointF(0.5, 0.0), QPointF(0.5, rect.height() - 0.5))
        p.drawLine(
            QPointF(0.5, rect.height() - 0.5),
            QPointF(rect.width(), rect.height() - 0.5),
        )

        # ``padding: 0 4px`` with a 5px gap between flexed bars.
        inner = rect.adjusted(1.0 + 4.0, 0.0, -4.0, -1.0)
        count = len(self._values)
        if count:
            gap = 5.0
            width = max(5.0, (inner.width() - gap * (count - 1)) / count)
            cyan = _showcase_colour("cyan")
            red = _showcase_colour("red")
            p.setPen(Qt.PenStyle.NoPen)
            for index, value in enumerate(self._values):
                height = inner.height() * (float(value) / self._maximum)
                x = inner.left() + index * (width + gap)
                bar = QRectF(x, inner.bottom() - height, width, height)
                path = QPainterPath()
                path.addRoundedRect(bar, 2.0, 2.0)
                p.fillPath(path, red if value > self._target else cyan)

        # ``.avg-line`` -- dashed cyan rule with its own inset caption.
        if self._maximum:
            y = inner.bottom() - inner.height() * (float(self._average) / self._maximum)
            dashed = QPen(QColor(DEFAULT_THEME.cyan_dim))
            dashed.setWidthF(1.0)
            dashed.setStyle(Qt.PenStyle.DashLine)
            p.setPen(dashed)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(QPointF(0.0, y), QPointF(rect.width(), y))

            caption = f"avg return {self._average}s"
            p.setFont(make_font(9.5, 400, mono=True))
            metrics = p.fontMetrics()
            text_width = metrics.horizontalAdvance(caption)
            box = QRectF(
                rect.width() - text_width - 10.0, y - 15.0, text_width + 6.0, 13.0
            )
            p.fillRect(box, QColor(DEFAULT_THEME.surface))
            p.setPen(QColor(DEFAULT_THEME.cyan))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, caption)
        p.end()


class ShowcaseDonut(QWidget):
    """``.donut`` -- 168px conic ring with a 24px inset hole."""

    SIZE = 168
    HOLE = 24

    def __init__(self, segments: Sequence[tuple], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedSize(self.SIZE, self.SIZE)
        self._segments = tuple(segments)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(0.0, 0.0, float(self.SIZE), float(self.SIZE))

        start = 90.0 * 16.0          # conic-gradient starts at twelve o'clock
        p.setPen(Qt.PenStyle.NoPen)
        for _name, _count, percent, role in self._segments:
            span = -(float(percent) / 100.0) * 360.0 * 16.0
            p.setBrush(_showcase_colour(role))
            p.drawPie(box, int(round(start)), int(round(span)))
            start += span

        hole = box.adjusted(self.HOLE, self.HOLE, -self.HOLE, -self.HOLE)
        p.setBrush(QColor(DEFAULT_THEME.surface))
        p.drawEllipse(hole)
        p.end()


class ShowcaseScatter(QWidget):
    """``.scatter-box`` -- percent-positioned dots over a left/bottom axis."""

    DOT = 7.0

    def __init__(self, points: Sequence[tuple], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedHeight(190)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._points = tuple(points)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())

        axis = QPen(QColor(DEFAULT_THEME.border))
        axis.setWidthF(1.0)
        p.setPen(axis)
        p.drawLine(QPointF(0.5, 0.0), QPointF(0.5, rect.height() - 0.5))
        p.drawLine(
            QPointF(0.5, rect.height() - 0.5),
            QPointF(rect.width(), rect.height() - 0.5),
        )

        cyan = _showcase_colour("cyan")
        glow_colour = qalpha(cyan, 0.45)
        p.setPen(Qt.PenStyle.NoPen)
        for x_percent, y_percent in self._points:
            x = rect.width() * (float(x_percent) / 100.0)
            y = rect.height() - rect.height() * (float(y_percent) / 100.0)
            centre = QPointF(x, y)
            glow = QRadialGradient(centre, self.DOT)
            glow.setColorAt(0.0, glow_colour)
            glow.setColorAt(1.0, qalpha(cyan, 0.0))
            p.setBrush(QBrush(glow))
            p.drawEllipse(centre, self.DOT, self.DOT)
            p.setBrush(cyan)
            p.drawEllipse(centre, self.DOT / 2.0, self.DOT / 2.0)
        p.end()


def showcase_metric_stat(
    number: str,
    caption: str,
    sub: str,
    role: str | None = None,
    *,
    size: float = 32.0,
    number_role: str | None = None,
) -> QFrame:
    """``.metric-stat`` -- centred mono figure over an uppercase caption.

    ``role`` is the mockup's ``--mstat-color``: it tints both the border and
    the figure.  Where the mockup sets no ``--mstat-color`` the border falls
    back to ``--border`` and the figure to ``--text``, and a few cells
    override the figure colour and size inline -- hence ``number_role`` and
    ``size``.
    """

    accent = _showcase_colour(role).name() if role else DEFAULT_THEME.border
    if number_role:
        figure_colour = _showcase_colour(number_role).name()
    elif role:
        figure_colour = _showcase_colour(role).name()
    else:
        figure_colour = DEFAULT_THEME.text_primary

    box = QFrame()
    box.setObjectName("showcaseMetricStat")
    box.setFrameShape(QFrame.Shape.NoFrame)
    box.setStyleSheet(
        f"QFrame#showcaseMetricStat {{ background: {DEFAULT_THEME.surface};"
        f" border: 1px solid {accent}; border-radius: {RADIUS_LG}px; }}"
    )
    card_shadow(box)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 22, 14, 22)
    lay.setSpacing(0)

    figure = QLabel(number)
    figure.setObjectName("plainBox")
    figure.setFont(make_font(size, 700, mono=True))
    figure.setStyleSheet(f"color: {figure_colour}; background: transparent;")
    figure.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(figure)

    lay.addSpacing(8)
    name = label(caption, 11, 700, "text", spacing=1.6, upper=True)
    name.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(name)

    if sub:
        lay.addSpacing(4)
        note = label(sub, 10.5, 400, "muted")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(note)
    return box


def showcase_status_badge(text: str, role: str = "red") -> QLabel:
    """``.status-badge`` -- 12% tint, 45% border, uppercase."""

    colour = _showcase_colour(role)
    badge = QLabel(text)
    badge.setObjectName("showcaseStatusBadge")
    badge.setFont(make_font(12, 800, spacing=1.5))
    badge.setStyleSheet(
        f"QLabel#showcaseStatusBadge {{ color: {colour.name()};"
        f" background: {qalpha(colour, 0.12).name(QColor.NameFormat.HexArgb)};"
        f" border: 1px solid {qalpha(colour, 0.45).name(QColor.NameFormat.HexArgb)};"
        f" border-radius: {RADIUS_SM}px; padding: 9px 18px; }}"
    )
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return badge


def showcase_legend_row(swatch: str, text: str, value: str) -> QWidget:
    """``.donut-legend-row`` -- dot, name, right-aligned mono value."""

    host = QWidget()
    host.setObjectName("plainBox")
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(9)
    # Dot only knows the core role names; resolve first so "rose" is not
    # handed to QColor as an unknown colour keyword.
    lay.addWidget(Dot(9, _showcase_colour(swatch).name(), glow=False))
    lay.addWidget(label(text, 12.5, 400, "text"))
    lay.addStretch(1)
    lay.addWidget(label(value, 11.5, 400, "muted", mono=True))
    return host


class MetricHubShowcasePage(QWidget):
    """The Metric Hub visual body, reproduced from the approved mockup.

    Showcase surface.  It holds no projection, requests no refresh, exposes
    neither ``request_refresh`` nor a ``ready`` signal, and every figure it
    shows is a fixed fixture from the mockup rather than a MYELIN observation.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("showcasePage")
        self.setAccessibleName("Metric Hub showcase")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setObjectName("showcaseScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        body = QWidget(scroll)
        body.setObjectName("plainBox")
        scroll.setWidget(body)
        # ``.mh-wrap`` -- padding 14px 34px 34px, gap 20.
        wrap = QVBoxLayout(body)
        wrap.setContentsMargins(34, 14, 34, 34)
        wrap.setSpacing(20)

        wrap.addWidget(self._build_hero())
        wrap.addLayout(self._build_stat_row())
        wrap.addLayout(self._build_chart_row())
        wrap.addLayout(self._build_table_row())
        wrap.addWidget(self._build_evidence_band())
        wrap.addStretch(1)

    # -- composition ------------------------------------------------------

    def _build_hero(self) -> QFrame:
        card, body = make_card()
        row = QHBoxLayout()
        row.setSpacing(20)

        text = QVBoxLayout()
        text.setSpacing(0)
        title = label("MYELIN METRIC HUB", 22, 700, "text", mono=True, spacing=2.0)
        text.addWidget(title)
        text.addSpacing(10)
        for line in (
            "Behavioral telemetry summary — authoritative read-model analytics",
        ):
            text.addWidget(label(line, 13, 400, "muted", wrap=True))
        accent = label("Operational trigger-return overview", 13, 600, "cyan")
        text.addSpacing(4)
        text.addWidget(accent)
        text.addSpacing(4)
        text.addWidget(
            label("Native MIRL episodes: 13  |  Legacy-only observations: 58",
                  13, 400, "muted")
        )
        text.addSpacing(4)
        text.addWidget(
            label("MIRL outcome metrics remain available to Live MIRL and Science Lab.",
                  13, 400, "muted", wrap=True)
        )
        text.addSpacing(12)
        text.addWidget(label("Generated: —  |  Refreshed: —", 11, 400, "muted", mono=True))
        row.addLayout(text, 1)

        badge_column = QVBoxLayout()
        badge_column.addWidget(showcase_status_badge("OFFLINE", "red"))
        badge_column.addStretch(1)
        row.addLayout(badge_column)
        body.addLayout(row)
        return card

    def _build_stat_row(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        cards = (
            ("105", "Total Sessions", "Operational scope", "cyan"),
            ("301s", "Avg Return Latency", "Eligible returned seconds", "green"),
            ("85.3%", "Resolved Return Rate", "Returned / returned + timeout", "blue"),
            ("71", "Total Triggers", "Operational scope", "red"),
        )
        for index, (number, caption, sub, role) in enumerate(cards):
            grid.addWidget(showcase_metric_stat(number, caption, sub, role), 0, index)
            grid.setColumnStretch(index, 1)
        return grid

    def _build_chart_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(20)

        latency, latency_body = make_card()
        head, _ = card_head("Return Latency Per Trigger Event")
        latency_body.addWidget(head)

        axis_row = QHBoxLayout()
        axis_row.addWidget(label(f"{_SHOWCASE_METRIC_LATENCY_MAX}s", 10, 400, "muted", mono=True))
        axis_row.addStretch(1)
        axis_row.addWidget(
            label(f"Operational target: {_SHOWCASE_METRIC_TARGET}s", 10, 400, "muted", mono=True)
        )
        latency_body.addSpacing(6)
        latency_body.addLayout(axis_row)

        latency_body.addSpacing(24)
        latency_body.addWidget(
            ShowcaseBarChart(
                _SHOWCASE_METRIC_LATENCY,
                _SHOWCASE_METRIC_LATENCY_MAX,
                _SHOWCASE_METRIC_TARGET,
                _SHOWCASE_METRIC_AVG,
            )
        )
        zero = label("0", 10, 400, "muted", mono=True)
        latency_body.addWidget(zero)

        caption = label("Eligible Operational Returned Triggers", 11, 400, "muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        latency_body.addSpacing(8)
        latency_body.addWidget(caption)

        legend = QHBoxLayout()
        legend.setSpacing(18)
        legend.addStretch(1)
        for role, name in (("cyan", "Within target"), ("red", "Over target")):
            cell = QWidget()
            cell.setObjectName("plainBox")
            cell_row = QHBoxLayout(cell)
            cell_row.setContentsMargins(0, 0, 0, 0)
            cell_row.setSpacing(6)
            swatch = QLabel()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"background: {_showcase_colour(role).name()}; border-radius: 2px;"
            )
            cell_row.addWidget(swatch)
            cell_row.addWidget(label(name, 11, 400, "muted"))
            legend.addWidget(cell)
        legend.addStretch(1)
        latency_body.addSpacing(12)
        latency_body.addLayout(legend)
        row.addWidget(latency, 16)

        distraction, distraction_body = make_card()
        head, _ = card_head("Distraction Today")
        distraction_body.addWidget(head)
        distraction_body.addSpacing(16)

        donut_row = QHBoxLayout()
        donut_row.addStretch(1)
        donut_row.addWidget(ShowcaseDonut(_SHOWCASE_METRIC_DONUT))
        donut_row.addStretch(1)
        distraction_body.addLayout(donut_row)

        distraction_body.addSpacing(18)
        for name, count, percent, role in _SHOWCASE_METRIC_DONUT:
            distraction_body.addWidget(
                showcase_legend_row(role, name, f"{count} / {percent:.0f}%")
            )
            distraction_body.addSpacing(10)

        rule = QFrame()
        rule.setFrameShape(QFrame.Shape.NoFrame)
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {DEFAULT_THEME.border};")
        distraction_body.addSpacing(4)
        distraction_body.addWidget(rule)
        total = label("Total Triggers: 71", 11, 400, "muted")
        total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        distraction_body.addSpacing(10)
        distraction_body.addWidget(total)
        distraction_body.addStretch(1)
        row.addWidget(distraction, 10)
        return row

    def _build_table_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(20)

        drift, drift_body = make_card()
        head, _ = card_head("Top Drift Events", dot=True)
        drift_body.addWidget(head)
        drift_body.addSpacing(16)

        table = QGridLayout()
        table.setHorizontalSpacing(10)
        table.setVerticalSpacing(0)
        headers = ("#", "Time", "Session", "App", "Reason", "Latency")
        for column, name in enumerate(headers):
            cell = label(name, 10, 700, "muted", spacing=1.2, upper=True)
            cell.setContentsMargins(0, 8, 0, 8)
            cell.setStyleSheet(f"border-bottom: 1px solid {DEFAULT_THEME.border};")
            table.addWidget(cell, 0, column)
        for line, entry in enumerate(_SHOWCASE_METRIC_DRIFT, start=1):
            last = line == len(_SHOWCASE_METRIC_DRIFT)
            for column, value in enumerate(entry):
                if column in (1, 2):
                    cell = label(value, 11.5, 400, "muted", mono=True)
                elif column == 5:
                    cell = label(value, 11.5, 600, "red", mono=True)
                else:
                    cell = label(value, 12.5, 400, "text")
                cell.setContentsMargins(0, 11, 0, 11)
                if not last:
                    cell.setStyleSheet(
                        f"border-bottom: 1px solid {DEFAULT_THEME.border};"
                    )
                table.addWidget(cell, line, column)
        table.setColumnStretch(4, 1)
        drift_body.addLayout(table)
        drift_body.addStretch(1)
        row.addWidget(drift, 16)

        duration, duration_body = make_card()
        head, _ = card_head("Session Duration")
        duration_body.addWidget(head)
        duration_body.addSpacing(6)
        duration_body.addWidget(label("3", 10, 400, "muted", mono=True))
        duration_body.addSpacing(24)
        duration_body.addWidget(ShowcaseScatter(_SHOWCASE_METRIC_SCATTER))
        duration_body.addWidget(label("0", 10, 400, "muted", mono=True))
        caption = label("Session Duration", 11, 400, "muted")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        duration_body.addSpacing(8)
        duration_body.addWidget(caption)
        duration_body.addStretch(1)
        row.addWidget(duration, 10)
        return row

    def _build_evidence_band(self) -> QFrame:
        card, body = make_card(padding=18)
        row = QHBoxLayout()
        row.setSpacing(24)
        row.addWidget(Dot(5, "cyan"))
        for text in (
            "Native MIRL episodes: 13",
            "Legacy-only observations: 58",
            "Operational trigger-return rows: 71",
        ):
            row.addWidget(label(text, 12.5, 400, "muted"))
        row.addStretch(1)
        body.addLayout(row)
        return card


#: mockup ``journeySteps`` -- (index, name, pill role, pill label, stamp label, stamp)
_SHOWCASE_MIRL_JOURNEY: Final = (
    (1, "Episode Started", "start", "Start", "Observed", "12:11:51"),
    (2, "SINE Stage Opened", "active", "Active", "Observed", "12:11:51"),
    (3, "SINE Stage Scheduled", "", "Scheduled", "Observed", "12:11:51"),
    (4, "SINE Response Recorded", "evidence", "Evidence", "Observed", "12:11:58"),
    (5, "SINE Stage Closed", "completed", "Completed", "Observed", "12:11:58"),
    (6, "Break Accepted", "terminal", "Terminal", "Observed", "12:11:59"),
    (7, "Episode Closed", "terminal", "Terminal", "Derived", "12:11:59"),
)

#: mockup ``cosinePlatformData`` and ``cosineEvents``
_SHOWCASE_COSINE_PLATFORMS: Final = (
    ("Netflix", 3, "#F0444D"),
    ("Prime Video", 1, "#60A5FA"),
)
_SHOWCASE_COSINE_EVENTS: Final = (
    ("green", "Returned to Focus after 2.60922 min"),
    ("amber", "Finish My Show selected"),
    ("cyan", "Netflix check-in appeared"),
)

#: mockup ``coHistorySessions[0].nodes`` -- the most recent session only.
_SHOWCASE_COSINE_FLOW: Final = (
    ("content", "Netflix", "school", "08:45:20"),
    ("link", "+02:14", "", ""),
    ("content", "Netflix", "home - netflix - school", "08:47:34"),
    ("link", "+03:02", "", ""),
    ("icon", "return", "", ""),
    ("outcome", "returned", "Returned to Focus", "08:50:36 · after 3m 02s"),
)

_JOURNEY_PILL_ROLES: Final = {
    "start": "cyan",
    "active": "cyan",
    "evidence": "#A78BFA",
    "completed": "green",
    "terminal": "text",
    "": "muted",
}


def showcase_journey_pill(role: str, text: str) -> QLabel:
    """``.journey-pill`` -- 10px uppercase chip, colour keyed by step kind."""

    colour = _showcase_colour(_JOURNEY_PILL_ROLES.get(role, "muted"))
    border = (
        DEFAULT_THEME.border
        if role in ("", "terminal")
        else qalpha(colour, 0.50).name(QColor.NameFormat.HexArgb)
    )
    pill = QLabel(text)
    pill.setObjectName("showcaseJourneyPill")
    pill.setFont(make_font(10, 700, spacing=0.5))
    pill.setStyleSheet(
        f"QLabel#showcaseJourneyPill {{ color: {colour.name()};"
        f" background: transparent; border: 1px solid {border};"
        f" border-radius: {RADIUS_SM}px; padding: 4px 10px; }}"
    )
    return pill


def showcase_journey_step(entry: tuple) -> QFrame:
    """``.journey-step`` -- 150px node: index, name, pill, timestamp."""

    index, name, pill_role, pill_text, stamp_label, stamp = entry
    box = QFrame()
    box.setObjectName("showcaseJourneyStep")
    box.setFrameShape(QFrame.Shape.NoFrame)
    box.setFixedWidth(150)
    edge = (
        qalpha(_showcase_colour("#A78BFA"), 0.50).name(QColor.NameFormat.HexArgb)
        if pill_role == "evidence"
        else DEFAULT_THEME.border
    )
    box.setStyleSheet(
        f"QFrame#showcaseJourneyStep {{ background: {DEFAULT_THEME.surface_soft};"
        f" border: 1px solid {edge}; border-radius: {RADIUS_MD}px; }}"
    )
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(0)

    lay.addWidget(label(f"#{index}", 10, 400, "muted", mono=True))
    lay.addSpacing(4)
    title = label(name, 12, 700, "text", wrap=True)
    title.setMinimumHeight(32)
    title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(title)
    lay.addSpacing(10)

    pill_row = QHBoxLayout()
    pill_row.setContentsMargins(0, 0, 0, 0)
    pill_row.addWidget(showcase_journey_pill(pill_role, pill_text))
    pill_row.addStretch(1)
    lay.addLayout(pill_row)

    lay.addSpacing(10)
    lay.addWidget(label(f"{stamp_label} · {stamp}", 10, 400, "muted", mono=True))
    return box


def showcase_flow_outcome(text: str, sub: str, kind: str = "returned") -> QFrame:
    """``.jflow-outcome`` -- the coloured terminal node closing a strip."""

    colour = _showcase_colour("green" if kind == "returned" else "red")
    box = QFrame()
    box.setObjectName("showcaseFlowOutcome")
    box.setFrameShape(QFrame.Shape.NoFrame)
    box.setFixedWidth(150)
    box.setStyleSheet(
        f"QFrame#showcaseFlowOutcome {{"
        f" background: {qalpha(colour, 0.12).name(QColor.NameFormat.HexArgb)};"
        f" border: 1px solid {qalpha(colour, 0.50).name(QColor.NameFormat.HexArgb)};"
        f" border-radius: {RADIUS_MD}px; }}"
    )
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(4)
    head = QLabel(text)
    head.setFont(make_font(12, 700))
    head.setStyleSheet(f"color: {colour.name()}; background: transparent;")
    head.setWordWrap(True)
    lay.addWidget(head)
    note = QLabel(sub)
    note.setFont(make_font(10, 400, mono=True))
    note.setStyleSheet(f"color: {colour.name()}; background: transparent;")
    note.setWordWrap(True)
    lay.addWidget(note)
    return box


class ShowcaseFlowLink(QWidget):
    """``.jflow-link`` -- a dashed arrow above its time delta."""

    def __init__(self, delta: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedWidth(52)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(3)
        lay.addStretch(1)
        arrow = _ShowcaseArrow(self)
        lay.addWidget(arrow, alignment=Qt.AlignmentFlag.AlignHCenter)
        caption = label(delta, 9, 400, "muted", mono=True)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(caption)
        lay.addStretch(1)


class _ShowcaseArrow(QWidget):
    """The 22x8 dashed arrow glyph inside a flow link."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self.setFixedSize(22, 8)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(0.6)
        pen = QPen(QColor(DEFAULT_THEME.muted))
        pen.setWidthF(1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(1.0, 4.0), QPointF(17.0, 4.0))
        solid = QPen(QColor(DEFAULT_THEME.muted))
        solid.setWidthF(1.4)
        p.setPen(solid)
        p.setBrush(Qt.BrushStyle.NoBrush)
        head = QPainterPath()
        head.moveTo(14.0, 1.0)
        head.lineTo(18.0, 4.0)
        head.lineTo(14.0, 7.0)
        p.drawPath(head)
        p.end()


def showcase_episode_banner(
    status_label: str,
    status_value: str,
    outcome_label: str,
    outcome_value: str,
    *,
    ok: bool = False,
    outcome_muted: bool = False,
) -> QFrame:
    """``.episode-banner`` -- 8% tint, 30% border, status left, outcome right."""

    tone = _showcase_colour("green" if ok else "red")
    banner = QFrame()
    banner.setObjectName("showcaseEpisodeBanner")
    banner.setFrameShape(QFrame.Shape.NoFrame)
    banner.setStyleSheet(
        f"QFrame#showcaseEpisodeBanner {{"
        f" background: {mix(tone.name(), 8, DEFAULT_THEME.surface)};"
        f" border: 1px solid {mix(tone.name(), 30, DEFAULT_THEME.border)};"
        f" border-radius: {RADIUS_LG}px; }}"
    )
    lay = QHBoxLayout(banner)
    lay.setContentsMargins(22, 18, 22, 18)
    lay.setSpacing(14)

    left = QVBoxLayout()
    left.setSpacing(4)
    status_row = QHBoxLayout()
    status_row.setContentsMargins(0, 0, 0, 0)
    status_row.setSpacing(8)
    status_row.addWidget(Dot(9, tone.name()))
    status_row.addWidget(label(status_label, 10.5, 400, "muted", spacing=1.5, upper=True))
    status_row.addStretch(1)
    left.addLayout(status_row)
    if status_value:
        value = QLabel(status_value)
        value.setFont(make_font(19, 700))
        value.setStyleSheet(f"color: {tone.name()}; background: transparent;")
        left.addWidget(value)
    lay.addLayout(left)
    lay.addStretch(1)

    right = QVBoxLayout()
    right.setSpacing(3)
    if outcome_label:
        caption = label(outcome_label, 10.5, 400, "muted", spacing=1.5, upper=True)
        caption.setAlignment(Qt.AlignmentFlag.AlignRight)
        right.addWidget(caption)
    if outcome_muted:
        outcome = label(outcome_value, 13, 400, "muted", wrap=True)
        outcome.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        outcome.setMinimumWidth(260)
    else:
        outcome = label(outcome_value, 17, 700, "text")
        outcome.setAlignment(Qt.AlignmentFlag.AlignRight)
    right.addWidget(outcome)
    lay.addLayout(right)
    return banner


def showcase_topline(title: str, hint: str, action: QWidget | None = None) -> QWidget:
    """``.mirl-topline`` -- dotted uppercase heading with a right-hand hint."""

    host = QWidget()
    host.setObjectName("plainBox")
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)

    text = QVBoxLayout()
    text.setSpacing(4)
    head_row = QHBoxLayout()
    head_row.setContentsMargins(0, 0, 0, 0)
    head_row.setSpacing(7)
    head_row.addWidget(Dot(5, "cyan"))
    head_row.addWidget(label(title, 12.5, 700, "text", spacing=1.6, upper=True))
    head_row.addStretch(1)
    text.addLayout(head_row)
    if action is not None and hint:
        text.addWidget(label(hint, 11.5, 400, "muted"))
    lay.addLayout(text)
    lay.addStretch(1)
    if action is not None:
        lay.addWidget(action)
    elif hint:
        lay.addWidget(label(hint, 11.5, 400, "muted"))
    return host


def showcase_cta(text: str) -> QPushButton:
    """``.btn-cta`` -- outlined cyan action.

    Deliberately unconnected.  The mockup shows this control, and this phase
    reproduces its appearance only; the surface behind it is not built.
    """

    button = QPushButton(text)
    button.setObjectName("showcaseCta")
    button.setFont(make_font(12, 700, spacing=0.8))
    button.setEnabled(False)
    button.setStyleSheet(
        f"QPushButton#showcaseCta {{ background: transparent;"
        f" color: {DEFAULT_THEME.cyan}; border: 1px solid {DEFAULT_THEME.cyan_dim};"
        f" border-radius: {RADIUS_SM}px; padding: 11px 20px; }}"
        f"QPushButton#showcaseCta:disabled {{ color: {DEFAULT_THEME.cyan};"
        f" border-color: {DEFAULT_THEME.cyan_dim}; }}"
    )
    return button


class LiveMirlShowcasePage(QWidget):
    """The Live MIRL launcher page, reproduced from the approved mockup.

    Showcase surface: no MIRL runtime, no read model, no episode machine.
    Every value is a fixed fixture from the mockup.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("showcasePage")
        self.setAccessibleName("Live MIRL showcase")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setObjectName("showcaseScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        body = QWidget(scroll)
        body.setObjectName("plainBox")
        scroll.setWidget(body)
        wrap = QVBoxLayout(body)
        wrap.setContentsMargins(34, 14, 34, 34)
        wrap.setSpacing(20)

        wrap.addWidget(
            showcase_topline(
                "Live MIRL — Authoritative Overview",
                "All committed evidence  |  3 Exclusions",
            )
        )
        wrap.addWidget(
            showcase_episode_banner(
                "Episode Status", "No Active Episode", "Latest Outcome", "Break"
            )
        )

        stats = QGridLayout()
        stats.setHorizontalSpacing(16)
        for column, (number, caption, size) in enumerate(
            (("71", "Trigger", 32.0), ("SINE-1", "SINE Stage", 24.0),
             ("104", "Session No.", 32.0))
        ):
            stats.addWidget(
                showcase_metric_stat(number, caption, "", "cyan", size=size), 0, column
            )
            stats.setColumnStretch(column, 1)
        wrap.addLayout(stats)

        wrap.addWidget(self._build_journey())

        outcomes = QGridLayout()
        outcomes.setHorizontalSpacing(16)
        for column, caption in enumerate(
            ("Return Intent", "Candidate Return", "Verified Return", "Stable Recovery")
        ):
            outcomes.addWidget(
                showcase_metric_stat(
                    "—", caption, "", None, size=22.0, number_role="muted"
                ),
                0,
                column,
            )
            outcomes.setColumnStretch(column, 1)
        wrap.addLayout(outcomes)

        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        cta_row.addWidget(showcase_cta("Open Full Dashboard"))
        wrap.addLayout(cta_row)
        wrap.addStretch(1)

    def _build_journey(self) -> QFrame:
        card, body = make_card()

        head = QHBoxLayout()
        head.setSpacing(10)
        title = label(
            "Event Journey — EPI104-24072026-02", 12.5, 700, "cyan", spacing=1.2
        )
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(label("7 recorded events", 11.5, 400, "muted"))
        body.addLayout(head)
        body.addSpacing(16)

        strip_host = QScrollArea()
        strip_host.setObjectName("showcaseScroll")
        strip_host.setWidgetResizable(True)
        strip_host.setFrameShape(QFrame.Shape.NoFrame)
        strip_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        strip_host.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip_host.setMinimumHeight(150)

        strip = QWidget()
        strip.setObjectName("plainBox")
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(6)

        steps = _SHOWCASE_MIRL_JOURNEY
        for position, entry in enumerate(steps):
            last = position == len(steps) - 1
            if last and entry[2] == "terminal":
                lay.addWidget(
                    showcase_flow_outcome(entry[1], f"{entry[4]} · {entry[5]}", "terminal-red"),
                    0,
                    Qt.AlignmentFlag.AlignVCenter,
                )
            else:
                lay.addWidget(showcase_journey_step(entry))
            if not last:
                lay.addWidget(
                    ShowcaseFlowLink(_showcase_delta(entry[5], steps[position + 1][5])),
                    0,
                    Qt.AlignmentFlag.AlignVCenter,
                )
        lay.addStretch(1)
        strip_host.setWidget(strip)
        body.addWidget(strip_host)
        return card


def _showcase_delta(first: str, second: str) -> str:
    """Format the gap between two fixture stamps, mockup ``jflowTimeDelta``."""

    def seconds(text: str) -> int:
        hours, minutes, secs = (int(part) for part in text.split(":"))
        return hours * 3600 + minutes * 60 + secs

    gap = seconds(second) - seconds(first)
    if gap < 0:
        gap += 24 * 3600
    return f"+{gap // 60:02d}:{gap % 60:02d}"


class CosineShowcasePage(QWidget):
    """The COSINE launcher page, reproduced from the approved mockup.

    Showcase surface: no COSINE runtime, no session logic, no Deep Analysis.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("showcasePage")
        self.setAccessibleName("COSINE showcase")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setObjectName("showcaseScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll)

        body = QWidget(scroll)
        body.setObjectName("plainBox")
        scroll.setWidget(body)
        wrap = QVBoxLayout(body)
        wrap.setContentsMargins(34, 14, 34, 34)
        wrap.setSpacing(20)

        wrap.addWidget(
            showcase_topline(
                "COSINE — Streaming Overview",
                "Choice-Oriented Streaming Insight and Navigation Engine",
                showcase_cta("Deep Analysis"),
            )
        )
        wrap.addWidget(
            showcase_episode_banner(
                "No Streaming Active",
                "",
                "",
                "COSINE is ready when you start watching.",
                ok=True,
                outcome_muted=True,
            )
        )

        stats = QGridLayout()
        stats.setHorizontalSpacing(16)
        for column, (number, caption, role) in enumerate(
            (
                ("4", "Streaming Check-ins", "cyan"),
                ("2", "Returned to Focus", "green"),
                ("3", "Chose to Finish", "amber"),
                ("2m", "Usual Return Time", None),
            )
        ):
            stats.addWidget(
                showcase_metric_stat(
                    number, caption, "", role, size=32.0 if role else 24.0
                ),
                0,
                column,
            )
            stats.setColumnStretch(column, 1)
        wrap.addLayout(stats)

        row = QHBoxLayout()
        row.setSpacing(20)
        row.addWidget(self._build_platforms(), 1)
        row.addWidget(self._build_events(), 1)
        wrap.addLayout(row)

        wrap.addWidget(self._build_flow())
        wrap.addStretch(1)

    def _build_platforms(self) -> QFrame:
        card, body = make_card()
        head, _ = card_head("Check-ins by Platform")
        body.addWidget(head)
        body.addSpacing(16)
        highest = max((value for _n, value, _c in _SHOWCASE_COSINE_PLATFORMS), default=1)
        for name, value, colour in _SHOWCASE_COSINE_PLATFORMS:
            host, track, amount = bar_row(name, colour)
            track.set_progress(float(value) / float(highest or 1), colour)
            amount.setText(str(value))
            body.addWidget(host)
            body.addSpacing(10)
        body.addStretch(1)
        return card

    def _build_events(self) -> QFrame:
        card, body = make_card()
        head, _ = card_head("Latest Events")
        body.addWidget(head)
        body.addSpacing(16)
        for role, text in _SHOWCASE_COSINE_EVENTS:
            line = QWidget()
            line.setObjectName("plainBox")
            lay = QHBoxLayout(line)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            lay.addWidget(Dot(7, role))
            lay.addWidget(label(text, 13, 400, "text", wrap=True), 1)
            body.addWidget(line)
            body.addSpacing(12)
        body.addStretch(1)
        return card

    def _build_flow(self) -> QFrame:
        card, body = make_card()
        head, _ = card_head(
            "Recent Session Flow", "Most recent check-in · full history in Deep Analysis"
        )
        body.addWidget(head)
        body.addSpacing(16)

        strip_host = QScrollArea()
        strip_host.setObjectName("showcaseScroll")
        strip_host.setWidgetResizable(True)
        strip_host.setFrameShape(QFrame.Shape.NoFrame)
        strip_host.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip_host.setMinimumHeight(140)

        strip = QWidget()
        strip.setObjectName("plainBox")
        lay = QHBoxLayout(strip)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(6)

        for kind, first, second, third in _SHOWCASE_COSINE_FLOW:
            if kind == "content":
                lay.addWidget(_showcase_content_node(first, second, third))
            elif kind == "link":
                lay.addWidget(ShowcaseFlowLink(first), 0, Qt.AlignmentFlag.AlignVCenter)
            elif kind == "icon":
                lay.addWidget(_showcase_icon_node(), 0, Qt.AlignmentFlag.AlignVCenter)
            elif kind == "outcome":
                lay.addWidget(
                    showcase_flow_outcome(second, third, first),
                    0,
                    Qt.AlignmentFlag.AlignVCenter,
                )
        lay.addStretch(1)
        strip_host.setWidget(strip)
        body.addWidget(strip_host)
        return card


def _showcase_content_node(platform: str, title: str, stamp: str) -> QFrame:
    """One COSINE flow content node: platform, title, timestamp."""

    box = QFrame()
    box.setObjectName("showcaseJourneyStep")
    box.setFrameShape(QFrame.Shape.NoFrame)
    box.setFixedWidth(150)
    box.setStyleSheet(
        f"QFrame#showcaseJourneyStep {{ background: {DEFAULT_THEME.surface_soft};"
        f" border: 1px solid {DEFAULT_THEME.border}; border-radius: {RADIUS_MD}px; }}"
    )
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(0)
    lay.addWidget(label(platform, 10, 400, "cyan", mono=True))
    lay.addSpacing(4)
    name = label(title, 12, 700, "text", wrap=True)
    name.setMinimumHeight(32)
    name.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    lay.addWidget(name)
    lay.addSpacing(10)
    lay.addWidget(label(stamp, 10, 400, "muted", mono=True))
    return box


def _showcase_icon_node() -> QWidget:
    """The small round return marker between COSINE flow nodes."""

    host = QWidget()
    host.setObjectName("plainBox")
    host.setFixedSize(38, 38)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(Dot(14, "green"), alignment=Qt.AlignmentFlag.AlignCenter)
    return host


class ControlPage(QWidget):
    """Control Station home page, composed from the donor card vocabulary.

    Every widget only formats backend-prepared facts.  The one number produced
    locally is the wall-clock session time on the ring, a presentation
    convenience that is never fed back into the engine.
    """

    study_mode_requested = pyqtSignal()

    # SINE owns stages 1-3.  The donor's fourth "Firm" chip is WEED 02
    # (obsolete SINE-4) and is deliberately not restored here.
    SINE_STAGES: Final = ((1, "Gentle"), (2, "Aware"), (3, "Direct"))

    def __init__(self, *, engine, lifecycle, profiles, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._lifecycle = lifecycle
        self._profiles = profiles
        self._last_sine_console_signature: tuple[object, ...] | None = None
        self._session_elapsed = QElapsedTimer()
        self._session_tick = QTimer(self)
        self._session_tick.setInterval(1000)
        self._session_tick.timeout.connect(self._advance_session_clock)

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page_layout.addWidget(scroll)

        grid = QWidget(scroll)
        grid.setObjectName("pageGrid")
        scroll.setWidget(grid)
        root = QHBoxLayout(grid)
        root.setContentsMargins(34, 14, 34, 34)
        root.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(20)
        right = QVBoxLayout()
        right.setSpacing(20)

        # ----------------------------------------------------- Engine Core
        self.hero = HeroCard(profiles, self)
        self.hero.study_mode_requested.connect(self.study_mode_requested.emit)
        self._status = self.hero.status_pill
        self._ring = self.hero.ring
        self._profile = self.hero.profile
        self._buttons = self.hero.buttons
        self._emergency = self.hero.btn_emergency
        self._profile.currentIndexChanged.connect(self._profile_changed)
        self._buttons["start"].clicked.connect(lifecycle.request_start)
        self._buttons["pause"].clicked.connect(engine.pause)
        self._buttons["stop"].clicked.connect(lifecycle.request_stop)
        self._emergency.clicked.connect(lifecycle.request_emergency)
        left.addWidget(self.hero)

        # -------------------------------------------- Today's Session Health
        health, health_body = make_card()
        head, _ = card_head("Today's Session Health", "Resets 00:00")
        health_body.addWidget(head)
        health_body.addSpacing(16)
        health_row = QHBoxLayout()
        health_row.setSpacing(14)
        sessions, self._stat_sessions = stat_box("Sessions", "0", "cyan")
        returns, self._stat_return = stat_box("Return rate", "\u2014", "green")
        distraction, self._stat_distraction = stat_box("Distraction", "\u2014", "amber")
        for widget in (sessions, returns, distraction):
            health_row.addWidget(widget, 1)
        health_body.addLayout(health_row)
        left.addWidget(health)

        # ------------------------------------------------- Current Resource
        current, current_body = make_card()
        head, self._current_hint = card_head("Current Resource", "Idle")
        current_body.addWidget(head)
        current_body.addSpacing(16)
        self._resource_label = label("\u2014", 16, 600, "text", mono=True)
        current_body.addWidget(self._resource_label)
        current_body.addSpacing(12)
        dwell_row, self._dwell_track, self._dwell_value = bar_row("Dwell / target")
        current_body.addWidget(dwell_row)
        current_body.addSpacing(10)
        self._resource_reason = label(
            "No managed resource is in the foreground.", 11.5, 400, "muted", wrap=True
        )
        current_body.addWidget(self._resource_reason)
        left.addWidget(current)

        # -------------------------------------------- SINE Escalation Stage
        sine, sine_body = make_card()
        head, _ = card_head("SINE Escalation Stage", "Authoritative runtime state")
        sine_body.addWidget(head)
        sine_body.addSpacing(16)
        strip = QHBoxLayout()
        strip.setSpacing(8)
        self._sine_chips: dict[int, QFrame] = {}
        for number, name in self.SINE_STAGES:
            chip = QFrame()
            chip.setObjectName("sineStage")
            chip.setFrameShape(QFrame.Shape.NoFrame)
            chip.setProperty("current", "false")
            chip_layout = QVBoxLayout(chip)
            chip_layout.setContentsMargins(6, 10, 6, 10)
            chip_layout.setSpacing(2)
            digit = label(str(number), 15, 400, "muted", mono=True)
            digit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            word = label(name, 11, 400, "muted")
            word.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip_layout.addWidget(digit)
            chip_layout.addWidget(word)
            strip.addWidget(chip, 1)
            self._sine_chips[number] = chip
        sine_body.addLayout(strip)
        sine_body.addSpacing(14)

        sine_grid = QGridLayout()
        sine_grid.setHorizontalSpacing(24)
        sine_grid.setVerticalSpacing(6)
        self._sine_timer = self._metric_value(sine_grid, 0, "Next authority timer")
        self._sine_stage = self._metric_value(sine_grid, 1, "Stage")
        self._sine_phase = self._metric_value(sine_grid, 2, "Phase")
        self._sine_timing_source = self._metric_value(sine_grid, 3, "Timing source")
        self._sine_lambda = self._metric_value(sine_grid, 4, "Lambda / min")
        self._sine_t_star = self._metric_value(sine_grid, 5, "Ebbinghaus t*")
        self._sine_popup = self._metric_value(sine_grid, 6, "Popup")
        self._sine_fact = self._metric_value(sine_grid, 7, "Last SINE fact")
        self._sine_fact.setWordWrap(True)
        sine_body.addLayout(sine_grid)
        left.addWidget(sine)

        # -------------------------------------------------- MINE Continuity
        mine, mine_body = make_card()
        head, self._mine_hint = card_head("MINE Continuity", "Inactive")
        mine_body.addWidget(head)
        mine_body.addSpacing(16)
        mine_row = QHBoxLayout()
        mine_row.setSpacing(14)
        source, self._mine_source = stat_box("Source", "\u2014", "text", 16.0)
        elapsed, self._mine_elapsed = stat_box(
            "Elapsed / Threshold", "\u2014 / 15:00", "text", 16.0
        )
        state, self._mine_state = stat_box("State", "Inactive", "text", 16.0)
        for widget in (source, elapsed, state):
            mine_row.addWidget(widget, 1)
        mine_body.addLayout(mine_row)
        mine_body.addSpacing(12)
        lock_row, self._mine_track, self._mine_value = bar_row("Lock progress")
        mine_body.addWidget(lock_row)
        left.addWidget(mine)

        # ---------------------------------------------------------- Research
        research, research_body = make_card()
        head, _ = card_head("Research", "Read-only")
        research_body.addWidget(head)
        research_body.addSpacing(16)
        research_row = QHBoxLayout()
        research_row.setSpacing(14)
        episodes, self._stat_episodes = stat_box("MIRL episodes", "0", "cyan")
        evidence, self._stat_evidence = stat_box(
            "Evidence source", "Read model", "text", 16.0
        )
        for widget in (episodes, evidence):
            research_row.addWidget(widget, 1)
        research_body.addLayout(research_row)
        left.addWidget(research)
        left.addStretch(1)

        for card in (health, current, sine, mine, research):
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # --------------------------------------------------- Live Telemetry
        feed_card, feed_body = make_card()
        head, self._feed_count = card_head("Live Telemetry", "Awaiting events")
        feed_body.addWidget(head)
        feed_body.addSpacing(16)
        self._feed = FeedList(feed_card)
        feed_body.addWidget(self._feed, 1)
        right.addWidget(feed_card, 1)

        root.addLayout(left, 100)
        root.addLayout(right, 105)

        engine.engine_status_changed.connect(self._engine_status_changed)
        self._profile_changed(self._profile.currentIndex())
        self._engine_status_changed("IDLE")

    # ------------------------------------------------------------- helpers
    @staticmethod
    def _metric_value(grid: QGridLayout, row: int, caption: str) -> QLabel:
        grid.addWidget(label(caption, 11.5, 400, "muted"), row, 0)
        value = label("\u2014", 12.5, 400, "text")
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(value, row, 1)
        return value

    @staticmethod
    def _value(payload: object, name: str, default=None):
        if isinstance(payload, dict):
            return payload.get(name, default)
        return getattr(payload, name, default)

    @staticmethod
    def _enum_text(value: object, default: str = "\u2014") -> str:
        if value is None:
            return default
        enum_name = getattr(value, "name", None)
        if enum_name is not None:
            return str(enum_name).replace("_", " ")
        enum_value = getattr(value, "value", None)
        if enum_value is not None:
            return str(enum_value).replace("_", " ").upper()
        return str(value)

    @staticmethod
    def _format_seconds(value: object) -> str:
        if value is None:
            return "--:--"
        try:
            seconds = max(0, int(round(float(value))))
        except (TypeError, ValueError, OverflowError):
            return "--:--"
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def _profile_changed(self, index: int) -> None:
        key = str(self._profile.itemData(index) or "general")
        if self._profiles.set_active(key):
            self._engine.set_profile_type(key)

    def _engine_status_changed(self, status) -> None:
        """Reflect engine status in the pill, the buttons and the ring clock."""

        text = str(getattr(status, "name", status)).replace("_", " ").upper()
        active = text == "ACTIVE"
        paused = text == "PAUSED"
        running = active or paused

        self._status.setText(f"ENGINE {text}")
        self._status.setProperty(
            "state",
            "active" if active
            else "paused" if paused
            else "alert" if text in {"EMERGENCY", "STOPPING"}
            else "",
        )
        restyle(self._status)

        self._buttons["start"].setEnabled(not running)
        self._buttons["pause"].setEnabled(running)
        self._buttons["stop"].setEnabled(running)
        self._emergency.setEnabled(running)

        if active:
            if not self._session_elapsed.isValid():
                self._session_elapsed.start()
            self._session_tick.start()
        else:
            self._session_tick.stop()
            if not paused:
                self._session_elapsed.invalidate()
                self._ring.set_elapsed_seconds(0)
                self._ring.set_progress(0.0)

    def _advance_session_clock(self) -> None:
        if self._session_elapsed.isValid():
            self._ring.set_elapsed_seconds(self._session_elapsed.elapsed() // 1000)

    def append_telemetry(self, *, time_text: str, text: str, tag: str, tone: str = "") -> None:
        """Append one prepared telemetry row supplied by the window."""

        self._feed.append(time_text=time_text, text=text, tag=tag, tone=tone)
        self._feed_count.setText(f"{self._feed.count} events")

    # -------------------------------------------------------------- render
    def render(self, payload: object) -> None:
        """Format the prepared control view; no value here is recalculated."""

        if payload is None:
            return
        session_id = self._value(payload, "session_id")
        if session_id is not None:
            self._status.setToolTip(f"Session {session_id}")

        blacklist = self._value(payload, "blacklist")
        if blacklist is not None:
            name = str(self._value(blacklist, "resource_label", "") or "").strip()
            title = str(self._value(blacklist, "resource_title", "") or "").strip()
            self._resource_label.setText(f"{name} \u2014 {title}" if title else (name or "\u2014"))

            disposition = self._enum_text(self._value(blacklist, "disposition"), "")
            state = self._enum_text(self._value(blacklist, "state"), "INACTIVE")
            confidence = self._enum_text(self._value(blacklist, "confidence"), "")
            parts = [p for p in (state, disposition, confidence) if p and p.upper() != "NONE"]
            self._current_hint.setText(" \u00b7 ".join(p.upper() for p in parts) or "Idle")

            reason = str(self._value(blacklist, "reason", "") or "").strip()
            self._resource_reason.setText(
                reason or "No managed resource is in the foreground."
            )

            elapsed = self._value(blacklist, "dwell_elapsed_seconds", 0.0)
            target = self._value(blacklist, "dwell_target_seconds", 0.0)
            fraction = 0.0
            try:
                target_value = float(target or 0.0)
                if target_value > 0:
                    fraction = min(1.0, max(0.0, float(elapsed or 0.0) / target_value))
            except (TypeError, ValueError):
                fraction = 0.0
            self._dwell_track.set_progress(
                fraction, "red" if fraction >= 0.85 else "rose" if fraction >= 0.5 else "cyan"
            )
            self._dwell_value.setText(self._format_seconds(elapsed))
            self._ring.set_progress(fraction)

        mirl = self._value(payload, "mirl")
        if mirl is not None:
            episodes = self._value(mirl, "episode_count")
            if episodes is not None:
                self._stat_episodes.setText(str(episodes))

        cosine = self._value(payload, "cosine")
        if cosine is not None:
            platform = str(self._value(cosine, "current_platform_label", "") or "").strip()
            seconds = self._value(cosine, "current_platform_seconds", 0.0)
            if platform:
                self._mine_source.setText(platform)
                self._mine_state.setText("Active")
                self._mine_hint.setText("Active")
                self._mine_elapsed.setText(f"{self._format_seconds(seconds)} / 15:00")
                try:
                    lock = min(1.0, max(0.0, float(seconds or 0.0) / 900.0))
                except (TypeError, ValueError):
                    lock = 0.0
                self._mine_track.set_progress(lock)
                self._mine_value.setText(f"{int(round(lock * 100))}%")
            else:
                self._mine_source.setText("\u2014")
                self._mine_state.setText("Inactive")
                self._mine_hint.setText("Inactive")
                self._mine_elapsed.setText("\u2014 / 15:00")
                self._mine_track.set_progress(0.0)
                self._mine_value.setText("0%")

    def render_sine(self, payload: object) -> None:
        """Render exactly the latest SINE live-view facts."""

        if payload is None:
            self._sine_timer.setText("--:--")
            for label in (
                self._sine_stage,
                self._sine_phase,
                self._sine_timing_source,
                self._sine_lambda,
                self._sine_t_star,
                self._sine_popup,
                self._sine_fact,
            ):
                label.setText("—")
            self._last_sine_console_signature = None
            self._highlight_sine_stage(None)
            return

        stage = self._enum_text(self._value(payload, "stage"), "NONE")
        phase = self._enum_text(self._value(payload, "phase"), "IDLE")
        timing_source = str(self._value(payload, "stage_2_timing_source", "") or "—")
        remaining_raw = self._value(payload, "next_deadline_seconds")
        timer_text = self._format_seconds(remaining_raw)
        lambda_value = self._value(payload, "ebbinghaus_lambda_per_minute")
        t_star = self._value(payload, "ebbinghaus_t_star_minutes")
        popup = self._enum_text(self._value(payload, "popup_state"), "NONE")
        last_fact = str(self._value(payload, "last_fact", "") or "—")

        self._sine_timer.setText(timer_text)
        self._sine_stage.setText(stage)
        self._highlight_sine_stage(self._value(payload, "stage"))
        self._sine_phase.setText(phase)
        self._sine_timing_source.setText(timing_source)
        self._sine_lambda.setText(
            "—" if lambda_value is None else f"{float(lambda_value):.6f}"
        )
        self._sine_t_star.setText(
            "—" if t_star is None else f"{float(t_star):.3f} min"
        )
        self._sine_popup.setText(popup)
        self._sine_fact.setText(last_fact)

        # A one-second console cadence makes VS Code's terminal useful without
        # flooding it at the controller's 250 ms telemetry polling rate.
        try:
            remaining_second = (
                None if remaining_raw is None else max(0, int(float(remaining_raw)))
            )
        except (TypeError, ValueError, OverflowError):
            remaining_second = None
        signature = (
            stage,
            phase,
            remaining_second,
            timing_source,
            lambda_value,
            t_star,
            popup,
            last_fact,
        )
        if signature != self._last_sine_console_signature:
            self._last_sine_console_signature = signature
            print(
                "[MYELIN][SINE TIMER] "
                f"stage={stage} | phase={phase} | next={timer_text} | "
                f"timing={timing_source} | lambda={self._sine_lambda.text()} | "
                f"t*={self._sine_t_star.text()} | popup={popup}",
                flush=True,
            )

    def _highlight_sine_stage(self, stage: object) -> None:
        """Mark the chip SINE reports as current; never infer one locally."""

        try:
            active = int(getattr(stage, "value", stage))
        except (TypeError, ValueError):
            active = 0
        for number, chip in self._sine_chips.items():
            chip.setProperty("current", "true" if number == active else "false")
            restyle(chip)


class ControlStationWindow(QMainWindow):
    """The main MYELIN window and composition root.

    This class creates each authority once and connects their public signals.
    It deliberately contains no engine rules.
    """

    def __init__(self) -> None:
        super().__init__()
        self._shutdown_is_authorized = False

        self.setObjectName("myelinControlStation")
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(resource_icon("icons/Myelin.ico"))
        self.setMinimumSize(MINIMUM_WINDOW_SIZE)
        self.resize(DEFAULT_WINDOW_SIZE)

        self._create_authorities()
        self.engine.install_popup_dispatchers(QApplication.instance(), owner=self)
        self._create_pages()
        self._create_shell()
        self._connect_components()
        self._restore_preferences()

    def _create_authorities(self) -> None:
        """Create exactly one owner for every Control Station responsibility."""

        self.settings = SettingsController(parent=self)
        self.theme = ThemeController(self.settings)
        self.profiles = ProfileController(self.settings)
        self.engine = ControlStationController(parent=self)

        self.lifecycle = LifecycleController(
            engine=self.engine,
            parent=self,
        )
        self.analytics = AnalyticsController(
            report_access=self.engine.report_access,
            red_guard=self.lifecycle.red_guard,
            parent=self,
        )
        self.tray = TrayController(
            engine=self.engine,
            lifecycle=self.lifecycle,
            settings=self.settings,
            parent=self,
        )

        # Control-Station-side durable storage, and the ONE long-lived Study
        # Planner it backs.  Planner and Notes must persist outside a
        # monitoring session, so this facade exists alongside the Monitor's;
        # both share the single process-wide SQLite write lane, and this one
        # is released in _finish_shutdown.
        #
        # Exactly one StudyPlanner is built for the whole application, so the
        # collection identity stays MYELIN-STUDY-PLANNER-V1 across page
        # openings and no second plan_id is ever minted.
        self.storage = EngineStorage()
        self.planner = StudyPlanner(repository=self.storage)

    def _create_pages(self) -> None:
        """Create the real pages and preserve their approved order."""

        self.pages = ControlStationPages(
            control=ControlPage(engine=self.engine, lifecycle=self.lifecycle, profiles=self.profiles),
            study=StudyView(
                engine=self.engine,
                lifecycle=self.lifecycle,
                settings=self.settings,
                planner=self.planner,
                # Named IANA zones only.  The clock's "local" entry is not an
                # IANA name and its fixed-offset fallback carries no
                # daylight-saving rules, so neither may reach the Planner.
                timezone_choices=tuple(
                    choice.key
                    for choice in TIMEZONE_CHOICES
                    if choice.key != "local"
                ),
            ),
            # Showcase visual body; the read-model page is reconnected in a
            # later approved phase.  analytics.py itself is untouched.
            metric_hub=MetricHubShowcasePage(),
            science_lab=self.analytics.create_science_lab_page(),
            live_mirl=LiveMirlShowcasePage(),
            mine=ComingSoonPage(
                "MINE",
                "Messaging Intervention Nudge Escalation",
            ),
            cosine=CosineShowcasePage(),
        )

        self.page_stack = QStackedWidget(self)
        self.page_stack.setObjectName("pagesHost")
        page_map = self.pages.by_name()
        for page_name in PAGE_ORDER:
            self.page_stack.addWidget(page_map[page_name])

        self.sidebar = ControlStationSidebar()
        self.navigation = NavigationController(
            page_stack=self.page_stack,
            pages=page_map,
            study_page=self.pages.study,
            red_guard=self.lifecycle.red_guard,
            sidebar=self.sidebar,
            parent=self,
        )

    def _create_shell(self) -> None:
        """Build the visible shell after its real components exist."""

        self.shell = ControlStationShell(
            clock=self.settings.create_clock_widget(),
            brand=BrandConsole(),
            sidebar=self.sidebar,
            page_stack=self.page_stack,
            loading_overlay=self.navigation.loading_overlay,
            parent=self,
        )
        self.setCentralWidget(self.shell)

    def _connect_components(self) -> None:
        """Connect requests to authorities and facts back to the views."""

        self.pages.control.study_mode_requested.connect(
            lambda: self.navigation.open_page(PAGE_STUDY)
        )
        self.shell.menu_requested.connect(self.navigation.toggle_sidebar)
        self.shell.sidebar_dismiss_requested.connect(self.navigation.close_sidebar)
        self.shell.clock_visibility_requested.connect(self._toggle_clock)
        self.shell.analytics_requested.connect(self.analytics.open_composer)

        self.navigation.page_opened.connect(self.analytics.page_opened)
        self.navigation.page_opened.connect(self.settings.set_last_page)
        self.lifecycle.navigation_enabled.connect(self.navigation.set_enabled)
        self.lifecycle.exit_authorized.connect(self._finish_shutdown)

        # The controller supplies prepared view data. The launcher does not
        # interpret or recalculate any telemetry value.
        self.engine.control_view_changed.connect(self.pages.control.render)
        self.engine.sine_watch_status_changed.connect(self.pages.control.render_sine)
        self.engine.study_view_changed.connect(self.pages.study.render)
        self.engine.telemetry_received.connect(self._print_telemetry_event)
        self.engine.engine_status_changed.connect(self._engine_status_changed)
        self.engine.normal_stop_requested.connect(self.lifecycle.request_stop)
        self.pages.study.prepare_requested.connect(self.engine.prepare_study)
        self.pages.study.study_action_requested.connect(self.engine.request_study_action)
        self.pages.study.break_requested.connect(self.engine.request_study_break)
        self.pages.study.return_intent_requested.connect(self.engine.request_cosecant_return_intent)

        self.theme.theme_changed.connect(self._apply_theme)

    def _restore_preferences(self) -> None:
        """Restore normal UI preferences without restoring a SINE stage."""

        preferences = self.settings.snapshot()
        self.settings.restore_window(self)

        self.shell.set_clock_visible(preferences.clock_visible)
        self.navigation.restore_page(preferences.last_page, fallback=PAGE_CONTROL)
        self.theme.set_reduced_motion(preferences.reduced_motion)
        self.navigation.set_reduced_motion(preferences.reduced_motion)
        self.tray.apply_minimize_behavior(preferences.minimize_behavior)
        self._apply_theme(self.theme.current_theme)

    def _toggle_clock(self) -> None:
        visible = not self.shell.clock.isVisible()
        self.shell.set_clock_visible(visible)
        self.settings.set_clock_visible(visible)

    def _engine_status_changed(self, status: EngineStatus) -> None:
        self.pages.study.set_monitoring_active(status is EngineStatus.ACTIVE)
        print(f"[MYELIN][ENGINE] status={status}", flush=True)

    @staticmethod
    def _activity_time(timestamp: str) -> str:
        """Render an event timestamp in the computer's local HH:MM:SS time."""

        try:
            parsed = datetime.fromisoformat(str(timestamp or "").replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone()
            return parsed.strftime("%H:%M:%S")
        except (TypeError, ValueError):
            return time.strftime("%H:%M:%S")

    @staticmethod
    def _activity_title(app: str, title: str) -> str:
        """Shorten browser decoration for console presentation only."""

        value = str(title or "").strip()
        if not value:
            return "(no window title)"

        # Windows browsers commonly append their own product name after the
        # page title.  Removing that suffix changes presentation only; monitor
        # classification continues to use certified process/host/URL evidence.
        for suffix in (
            " - Google Chrome",
            " - Microsoft Edge",
            " — Mozilla Firefox",
            " - Mozilla Firefox",
        ):
            if value.casefold().endswith(suffix.casefold()):
                value = value[: -len(suffix)].rstrip()
                break

        platform_suffixes = (f" - {app}", f" — {app}", f" | {app}")
        for suffix in platform_suffixes:
            if app and value.casefold().endswith(suffix.casefold()):
                value = value[: -len(suffix)].rstrip()
                break
        return value or "(no window title)"

    def _print_telemetry_event(self, event: object) -> None:
        kind = str(getattr(event, "kind", "") or "")
        app = str(getattr(event, "app", "") or "")
        title = str(getattr(event, "title", "") or "")
        message = getattr(event, "message", "")
        timestamp = str(getattr(event, "time", "") or "")

        local_time = self._activity_time(timestamp)

        if kind == "console_banner":
            print(str(message), flush=True)
            return

        if kind == "console_history":
            print(f"[{local_time}] {message}", flush=True)
            return

        if kind == "activity":
            headline = self._activity_title(app, title)
            print(
                f"[MYELIN][ACTIVITY] [{local_time}] app->{app or 'Unknown'} "
                f"[{headline}]",
                flush=True,
            )
            self.pages.control.append_telemetry(
                time_text=local_time,
                text=f"{(app or 'UNKNOWN').upper()} \u2014 {headline}",
                tag=str(getattr(event, "badge", "") or "DWELL"),
            )
            return

        if kind == "session":
            print(f"[{local_time}] [SESSION] {message}", flush=True)
            return

        # Rich terminal history is emitted as explicit console_history facts.
        # Suppress their lower-level duplicates while retaining unexpected
        # diagnostics and failures under the generic telemetry prefix.
        if (
            kind.startswith("mirl_")
            or kind in {
                "profile_learning_loaded",
                "profile_learning_observation",
                "profile_learning_committed",
                "trigger",
            }
        ):
            return

        print(
            f"[MYELIN][TELEMETRY] time={timestamp} kind={kind} "
            f"app={app} message={message}",
            flush=True,
        )

    def _apply_theme(self, theme) -> None:
        """Apply visual truth, then refresh the native Windows caption."""

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_application_stylesheet(theme))
        self.navigation.apply_theme(theme)
        self.shell.setProperty("themeWorld", theme.world_name)
        self.shell.style().unpolish(self.shell)
        self.shell.style().polish(self.shell)
        self._apply_native_titlebar(theme)

    def _apply_native_titlebar(self, theme=None) -> None:
        tokens = theme or self.theme.current_theme
        apply_native_titlebar(
            self,
            background=tokens.window_background,
            foreground=tokens.text_primary,
            dark_mode=tokens.is_dark,
        )

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._apply_native_titlebar()
        self.tray.start()
        if isinstance(self.shell.brand, BrandConsole):
            self.shell.brand.start()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.ActivationChange,
            QEvent.Type.WindowStateChange,
        }:
            self._apply_native_titlebar()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.navigation.sidebar_is_open:
            self.navigation.close_sidebar()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Never close before the lifecycle authority approves shutdown."""

        if self._shutdown_is_authorized:
            event.accept()
            return

        event.ignore()
        self.lifecycle.request_exit()

    def _finish_shutdown(self) -> None:
        if isinstance(self.shell.brand, BrandConsole):
            self.shell.brand.stop()
        """Close only after lifecycle has confirmed every required barrier."""

        if self._shutdown_is_authorized:
            return

        self._shutdown_is_authorized = True
        self.lifecycle.shutdown()
        self.navigation.shutdown()
        self.analytics.shutdown()
        self.tray.shutdown()
        self.engine.shutdown()
        # Release this facade's share of the process-wide SQLite lane. The
        # lane itself closes only when the last owner lets go, so this never
        # cuts persistence out from under a still-running Monitor session.
        self.storage.shutdown()
        self.settings.capture_window(self)
        self.settings.shutdown()
        print("[MYELIN][SHUTDOWN] barriers complete; closing Control Station", flush=True)
        QTimer.singleShot(0, self._close_and_quit_application)

    def _close_and_quit_application(self) -> None:
        """Close the authorized window and terminate the Qt event loop.

        ``quitOnLastWindowClosed`` is intentionally disabled because MYELIN owns
        a tray icon.  Therefore an authorized close must explicitly quit Qt
        after every backend/shutdown owner has already been released.
        """

        self.close()
        app = QApplication.instance()
        if app is not None:
            print("[MYELIN][SHUTDOWN] Qt event loop exit requested", flush=True)
            app.quit()


class StartupSequence:
    """Non-blocking startup sequence with one terminal result.

    The Qt event loop must continue painting between stages.  Every stage is
    therefore scheduled separately instead of performing one long operation
    on the GUI thread.
    """

    def __init__(
        self,
        app: QApplication,
        *,
        minimum_display_ms: int = 600,
        completed: Callable[[int, ControlStationWindow | None], None] | None = None,
    ) -> None:
        self._app = app
        self._minimum_display_ms = max(0, int(minimum_display_ms))
        self._completed = completed
        self._started_at = time.monotonic()
        self._is_finished = False
        self._window: ControlStationWindow | None = None

        self._splash = StartupLoadingScreen(
            logo_path=self._resolve_loading_logo(),
        )

    @property
    def splash(self) -> StartupLoadingScreen:
        return self._splash

    def start(self) -> None:
        self._splash.start()
        self._splash.set_status("Initializing Control Station")
        QTimer.singleShot(0, self._run_startup_gate)

    def _run_startup_gate(self) -> None:
        try:
            self._splash.set_status("Checking emergency follow-up")
            LifecycleController.run_startup_gate(
                parent=self._splash,
                completed=self._startup_gate_completed,
            )
        except Exception as exc:  # startup fails closed
            self._fail("emergency follow-up gate", exc)

    def _startup_gate_completed(self, result: StartupGateResult) -> None:
        if result is not StartupGateResult.CLEAR_TO_START:
            self._splash.stop()
            self._splash.close()
            self._complete(0, None)
            return

        QTimer.singleShot(0, self._build_window)

    def _build_window(self) -> None:
        try:
            self._splash.set_status("Loading MYELIN interface")
            self._window = ControlStationWindow()
            self._splash.set_status("Ready")

            elapsed_ms = int((time.monotonic() - self._started_at) * 1000)
            remaining_ms = max(0, self._minimum_display_ms - elapsed_ms)
            QTimer.singleShot(remaining_ms, self._handoff)
        except Exception as exc:  # startup fails closed
            self._fail("Control Station construction", exc)

    def _handoff(self) -> None:
        if self._window is None:
            self._fail(
                "loading-screen handoff",
                RuntimeError("Control Station window was not constructed"),
            )
            return

        self._splash.finish(self._window)
        self._complete(0, self._window)

    def _fail(self, stage: str, exc: BaseException) -> None:
        detail = " ".join(str(exc).split())
        if len(detail) > 240:
            detail = detail[:237] + "..."

        print(
            f"[MYELIN][STARTUP] {stage} failed: "
            f"{type(exc).__name__}: {detail}",
            file=sys.stderr,
        )
        self._splash.stop()
        self._splash.close()
        self._complete(1, None)

    def _complete(self, exit_code: int, window: ControlStationWindow | None) -> None:
        if self._is_finished:
            return
        self._is_finished = True

        if self._completed is not None:
            self._completed(exit_code, window)

    @staticmethod
    def _resolve_loading_logo() -> str:
        """Return the approved loading-screen asset through one path owner."""

        from PERSISTENCE.database import resource_path

        return str(resource_path("images/Myelin_Loading_Screen.png"))


def _configure_application(app: QApplication) -> None:
    """Apply process-wide Qt settings before any main window is created."""

    app.setApplicationName("MYELIN Control Station")
    app.setWindowIcon(resource_icon("icons/Myelin.ico"))
    app.setQuitOnLastWindowClosed(False)
    app.setFont(make_font(13, 400))
    app.setStyleSheet(build_application_stylesheet())


def _set_windows_application_identity() -> None:
    """Give MYELIN one stable Windows taskbar identity.

    Windows otherwise groups the program under the Python interpreter.  The
    explicit identity keeps the approved MYELIN icon and taskbar grouping.
    Other operating systems safely skip this Windows-only instruction.
    """

    if sys.platform != "win32":
        return

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_ID
        )
    except (AttributeError, OSError):
        # A missing Windows shell API must not block MYELIN startup.
        return


def main(argv: Sequence[str] | None = None) -> int:
    """Start one MYELIN process and return its real exit code."""

    arguments = list(sys.argv if argv is None else argv)
    print("[MYELIN][STARTUP] Control Station process starting", flush=True)

    # Persistence owns schema creation and verification. The launcher only
    # enforces that it completes before any runtime authority is constructed.
    ensure_production_schema()

    _set_windows_application_identity()
    app = QApplication(arguments)
    _configure_application(app)

    result = {"exit_code": 0}
    lifetime: dict[str, object | None] = {
        "startup": None,
        "window": None,
    }

    def startup_completed(
        exit_code: int,
        window: ControlStationWindow | None,
    ) -> None:
        result["exit_code"] = int(exit_code)
        lifetime["window"] = window
        if window is None:
            app.quit()

    startup = StartupSequence(app, completed=startup_completed)
    lifetime["startup"] = startup
    startup.start()

    qt_exit_code = int(app.exec())
    lifetime.clear()
    print(f"[MYELIN][SHUTDOWN] process exiting; qt_code={qt_exit_code}", flush=True)
    if result["exit_code"] == 0 and qt_exit_code != 0:
        return qt_exit_code
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
