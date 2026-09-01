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
from datetime import datetime, timezone
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
    QIcon,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QResizeEvent,
    QShowEvent,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .analytics import AnalyticsController
from .controller import ControlStationController, EngineStatus
from .lifecycle import LifecycleController, StartupGateResult
from .myelin_loading_screen import MyelinLoadingScreen
from .navigation import NavigationController
from .settings import TIMEZONE_CHOICES, SettingsController, ThemePreferenceDialog
from .tray import TrayController
from COSECANT_STUDY_MODE.cosecant import CosecantFactKind, CosecantState
from COSECANT_STUDY_MODE.notes import NoteSession, NotesWorkspace
from COSECANT_STUDY_MODE.planner import StudyPlanner
from COSECANT_STUDY_MODE.view import StudyView
from PERSISTENCE.storage import EngineStorage, bootstrap_production_schema
from PROFILES.profiles import ProfileController
from UI_THEMES.animation import (
    AlertBorderOverlay,
    AxonCanvas,
    BarTrack,
    BrandMark,
    CircuitTrace,
    Dot,
    EngineRing,
    NavIcon,
    StudyRing,
    set_active_theme,
)
from UI_THEMES.theme import (
    AMBER_ALERT_THEME,
    Atmosphere,
    DEFAULT_THEME,
    RED_ALERT_THEME,
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
    About row stays removed; Settings now carries the one real preference
    MYELIN exposes today -- the base theme -- via ``settings_requested``.
    """

    page_requested = pyqtSignal(str)
    open_changed = pyqtSignal(bool)
    settings_requested = pyqtSignal()
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
        self._theme = DEFAULT_THEME
        self._coming_soon_icon: NavIcon | None = None

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
        row.addWidget(self._brand_icon(26))

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

    @staticmethod
    def _brand_icon(height: int) -> QLabel:
        """The sidebar's own brand glyph -- the approved raster artwork.

        Renders ``ASSETS/images/Myelin_Loading_Screen.png`` (the same source
        art as the taskbar icon) in place of the donor's hand-drawn
        ``BrandMark`` vector approximation, scaled to the row's height with
        its own aspect ratio preserved.
        """

        from PERSISTENCE.database import resource_path

        icon = QLabel()
        icon.setObjectName("plainBox")
        pixmap = QPixmap(str(resource_path("images/Myelin_Loading_Screen.png")))
        if not pixmap.isNull():
            scaled = pixmap.scaledToHeight(
                height, Qt.TransformationMode.SmoothTransformation
            )
            icon.setPixmap(scaled)
            icon.setFixedSize(scaled.size())
        else:
            icon.setFixedSize(height, height)
        return icon

    def _build_foot(self) -> QWidget:
        """``.sidebar-foot`` -- Settings, the closing hairline, an identity line.

        Settings currently opens the base-theme picker directly: MYELIN has
        exactly one ordinary preference to expose today.  It is a real
        ``QPushButton`` with its own ``clicked`` handler, not a page --
        opening it does not go through ``page_requested``/``select`` and does
        not touch ``_buttons``/``_rows``.
        """

        foot = QWidget(self)
        foot.setObjectName("sidebarFoot")
        row = QVBoxLayout(foot)
        row.setContentsMargins(20, 14, 20, 2)
        row.setSpacing(4)
        row.addWidget(self._settings_row())
        row.addSpacing(10)
        note = label("CONTROL STATION v2.0", 9.5, 600, "muted", mono=True, spacing=1.4)
        note.setObjectName("sidebarFootNote")
        note.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        row.addWidget(note)
        return foot

    def _settings_row(self) -> QPushButton:
        """``MENU -> SETTINGS -> THEME`` -- the one entry point to base themes."""

        button = QPushButton(self)
        button.setObjectName("sidebarNavigationButton")
        button.setAccessibleName("Open MYELIN settings")
        # QPushButton sizes itself from its own (empty) text; see _nav_row.
        button.setMinimumHeight(42)
        button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(button)
        row.setContentsMargins(12, 11, 12, 11)
        row.setSpacing(13)
        row.addWidget(label("Settings", 13.5, 400, "text"))
        row.addStretch(1)
        button.clicked.connect(self.settings_requested.emit)
        return button

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

        dim = mix(self._theme.muted, 55, self._theme.surface_soft)
        icon = NavIcon(key, row)
        icon.set_colour(dim)
        self._coming_soon_icon = icon
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
            colour, role = mix(self._theme.muted, 55, self._theme.surface_soft), "muted"
        elif active:
            colour, role = self._theme.cyan, "cyan"
        else:
            colour, role = self._theme.muted, "text"
        icon.set_colour(colour)
        if row_label.property("role") != role:
            row_label.setProperty("role", role)
            restyle(row_label)

    # -- navigation contract (unchanged) ----------------------------------

    @property
    def is_open(self) -> bool:
        return self._is_open

    def apply_theme(self, tokens) -> None:
        """Refresh every row's colour for the newly active world."""

        self._theme = tokens
        for name, button in self._buttons.items():
            self._paint_row(name, button.isChecked())
        if self._coming_soon_icon is not None:
            self._coming_soon_icon.set_colour(
                mix(tokens.muted, 55, tokens.surface_soft)
            )

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = DEFAULT_THEME

    def apply_theme(self, tokens) -> None:
        self._theme = tokens
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        t = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())
        painter.fillRect(rect, QColor(t.window_background))

        window = self.window()
        page_height = float(max(self.height(), window.height() if window else 0))
        cyan = QColor(t.cyan)

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
        base = QColor(t.window_background)
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
        self.top_bar = top_bar
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

        # Common presentation infrastructure: shows only when a caller (the
        # future SINE/MIRL presentation coordinator) calls ``set_alert``.  It
        # sits above everything else so a warning border is never occluded.
        self.alert_border = AlertBorderOverlay(self)

        self.sidebar_backdrop.raise_()
        self.sidebar.raise_()
        self.loading_overlay.raise_()
        self.alert_border.raise_()

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

    def apply_theme(self, tokens) -> None:
        self.top_bar.apply_theme(tokens)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        bounds = self.rect()
        self.sidebar.setFixedHeight(bounds.height())
        self.sidebar_backdrop.setGeometry(bounds)
        self.loading_overlay.setGeometry(bounds)
        self.alert_border.setGeometry(bounds)
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
        self.setFont(make_font(9, 600, spacing=0.4))


class HeroCard(QFrame):
    """Engine Core: radial-tinted card, decorative axon canvas, ring, controls."""

    study_mode_requested = pyqtSignal()

    def __init__(self, profiles, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("heroCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._theme = DEFAULT_THEME

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

    def apply_theme(self, tokens) -> None:
        self._theme = tokens
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        t = self._theme

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
        layout.setContentsMargins(6, 9, 6, 9)
        layout.setSpacing(8)

        layout.addWidget(Dot(8, tone or "cyan", glow=False))
        stamp = label(time_text, 11, 400, "muted", mono=True)
        stamp.setFixedWidth(50)
        layout.addWidget(stamp)
        body = label(text, 11, 400, "text", wrap=True)
        body.setMinimumWidth(0)
        body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
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


#: The tokens in force right now.  ``_apply_theme`` keeps this in step on
#: every world change, mirroring ``animation.set_active_theme``.  It exists so
#: a fixture rebuilt BETWEEN world changes (Live MIRL rebuilds on every
#: projection) starts on the live world instead of the default one.
_LIVE_TOKENS = DEFAULT_THEME


def _set_live_tokens(tokens) -> None:
    global _LIVE_TOKENS
    _LIVE_TOKENS = tokens


def live_tokens():
    """The theme a newly constructed launcher fixture should start from."""

    return _LIVE_TOKENS


def _retheme_subtree(root: QWidget) -> None:
    """Bring one freshly built subtree onto the live world.

    Same closure contract as ``_apply_theme``'s sweep, applied to one branch
    instead of the whole shell.
    """

    tokens = live_tokens()
    for widget in (root, *root.findChildren(QWidget)):
        retheme = getattr(widget, "_retheme", None)
        if callable(retheme):
            retheme(tokens)
        apply_theme = getattr(widget, "apply_theme", None)
        if callable(apply_theme):
            apply_theme(tokens)


def _remember_retheme(widget: QWidget, retheme: Callable[[object], None]) -> None:
    """Attach a per-widget theme-refresh closure for the launcher's sweep.

    Several showcase fixtures are plain ``QFrame``/``QLabel``/``QPushButton``
    instances that build one literal stylesheet string at construction time
    instead of going through a custom painter class.  Rather than inventing a
    QSS attribute-selector for every one-off conditional, each such fixture
    keeps the exact styling code it always had, wrapped in a small closure
    over ``tokens`` that ``ControlStationWindow._apply_theme`` re-invokes on
    every world change.
    """

    widget._retheme = retheme  # noqa: SLF001 -- deliberate, see docstring


def _showcase_colour(role: str, tokens=DEFAULT_THEME) -> QColor:
    """Resolve one mockup palette name against the given (or default) theme."""

    table = {
        "cyan": tokens.cyan,
        "green": tokens.green,
        "amber": tokens.amber,
        "red": tokens.red,
        "muted": tokens.muted,
        "text": tokens.text_primary,
        "rose": "#FB7185",
        "blue": "#60A5FA",
    }
    return QColor(table.get(role, role))


def _white_alpha(a: float) -> str:
    """A theme-neutral ``rgba(255,255,255,a)`` overlay, ported 1:1 from CSS."""

    return qalpha(QColor(255, 255, 255), a).name(QColor.NameFormat.HexArgb)


class _GlassPanel(QFrame):
    """``.glass-panel`` -- rounded, translucent surface, mockup CSS ported 1:1.

    The mockup's panel is ``color-mix(in srgb, var(--surface) 55%,
    transparent)`` with ``backdrop-filter: blur(22px)`` as a progressive
    enhancement on top -- browsers without ``backdrop-filter`` support fall
    back to that flat translucent colour alone, still a correct glass panel,
    just without the live blur.  Qt has no live backdrop-filter and no
    reliable way to fake one from a static grab (see prior attempts in git
    history), so this paints that same standards-sanctioned fallback
    directly: the translucent surface tint plus the 14%-white border, no
    screenshot/blur step at all.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("plainBox")
        self._tint = QColor(DEFAULT_THEME.surface)
        self._border = QColor(_white_alpha(0.14))

    def apply_tint(self, tokens) -> None:
        self._tint = QColor(tokens.surface)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, RADIUS_LG, RADIUS_LG)

        tint = QColor(self._tint)
        tint.setAlphaF(0.55)
        painter.fillPath(path, tint)

        pen = QPen(self._border)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()


def _glass_gstat(caption: str, value: str, value_size: float = 22.0) -> QFrame:
    """``.gstat`` -- translucent left-aligned tile over a glass panel."""

    box = QFrame()
    box.setObjectName("glassGstat")
    box.setStyleSheet(
        f"QFrame#glassGstat {{ background: {_white_alpha(0.03)};"
        f" border: 1px solid {_white_alpha(0.09)}; border-radius: {RADIUS_MD}px; }}"
    )
    lay = QVBoxLayout(box)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(6)
    lay.addWidget(label(caption, 11, 400, "muted"))
    value_label = label(value, value_size, 700, "text", mono=True)
    value_label.setWordWrap(True)
    lay.addWidget(value_label)
    return box


def _glass_gcard(padding: int = 20) -> tuple[QFrame, QVBoxLayout]:
    """``.gcard`` -- translucent card over a glass panel."""

    card = QFrame()
    card.setObjectName("glassGcard")
    card.setStyleSheet(
        f"QFrame#glassGcard {{ background: {_white_alpha(0.03)};"
        f" border: 1px solid {_white_alpha(0.09)}; border-radius: {RADIUS_LG}px; }}"
    )
    lay = QVBoxLayout(card)
    lay.setContentsMargins(padding, padding, padding, padding)
    lay.setSpacing(0)
    return card, lay


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
        self._theme = DEFAULT_THEME

    def apply_theme(self, tokens) -> None:
        self._theme = tokens
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())

        axis = QPen(QColor(t.border))
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
            cyan = _showcase_colour("cyan", t)
            red = _showcase_colour("red", t)
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
            dashed = QPen(QColor(t.cyan_dim))
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
            p.fillRect(box, QColor(t.surface))
            p.setPen(QColor(t.cyan))
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
        self._theme = DEFAULT_THEME

    def apply_theme(self, tokens) -> None:
        self._theme = tokens
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        box = QRectF(0.0, 0.0, float(self.SIZE), float(self.SIZE))

        start = 90.0 * 16.0          # conic-gradient starts at twelve o'clock
        p.setPen(Qt.PenStyle.NoPen)
        for _name, _count, percent, role in self._segments:
            span = -(float(percent) / 100.0) * 360.0 * 16.0
            p.setBrush(_showcase_colour(role, t))
            p.drawPie(box, int(round(start)), int(round(span)))
            start += span

        hole = box.adjusted(self.HOLE, self.HOLE, -self.HOLE, -self.HOLE)
        p.setBrush(QColor(t.surface))
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
        self._theme = DEFAULT_THEME

    def apply_theme(self, tokens) -> None:
        self._theme = tokens
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        t = self._theme
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect())

        axis = QPen(QColor(t.border))
        axis.setWidthF(1.0)
        p.setPen(axis)
        p.drawLine(QPointF(0.5, 0.0), QPointF(0.5, rect.height() - 0.5))
        p.drawLine(
            QPointF(0.5, rect.height() - 0.5),
            QPointF(rect.width(), rect.height() - 0.5),
        )

        cyan = _showcase_colour("cyan", t)
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

    box = QFrame()
    box.setObjectName("showcaseMetricStat")
    box.setFrameShape(QFrame.Shape.NoFrame)
    card_shadow(box)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 22, 14, 22)
    lay.setSpacing(0)

    figure = QLabel(number)
    figure.setObjectName("plainBox")
    figure.setFont(make_font(size, 700, mono=True))
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

    def _retheme(tokens) -> None:
        accent = _showcase_colour(role, tokens).name() if role else tokens.border
        if number_role:
            figure_colour = _showcase_colour(number_role, tokens).name()
        elif role:
            figure_colour = _showcase_colour(role, tokens).name()
        else:
            figure_colour = tokens.text_primary
        box.setStyleSheet(
            f"QFrame#showcaseMetricStat {{ background: {tokens.surface};"
            f" border: 1px solid {accent}; border-radius: {RADIUS_LG}px; }}"
        )
        figure.setStyleSheet(f"color: {figure_colour}; background: transparent;")

    _retheme(DEFAULT_THEME)
    _remember_retheme(box, _retheme)
    # Same convention as ``showcase_episode_banner.detail_label``: exposed so a
    # per-second readout can be retitled in place instead of rebuilding the
    # whole tile on every tick.
    box.figure_label = figure  # noqa: SLF001 -- see comment
    return box


def showcase_status_badge(text: str, role: str = "red") -> QLabel:
    """``.status-badge`` -- 12% tint, 45% border, uppercase."""

    badge = QLabel(text)
    badge.setObjectName("showcaseStatusBadge")
    badge.setFont(make_font(12, 800, spacing=1.5))
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _retheme(tokens) -> None:
        colour = _showcase_colour(role, tokens)
        badge.setStyleSheet(
            f"QLabel#showcaseStatusBadge {{ color: {colour.name()};"
            f" background: {qalpha(colour, 0.12).name(QColor.NameFormat.HexArgb)};"
            f" border: 1px solid {qalpha(colour, 0.45).name(QColor.NameFormat.HexArgb)};"
            f" border-radius: {RADIUS_SM}px; padding: 9px 18px; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(badge, _retheme)
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

            def _retheme_swatch(tokens, swatch=swatch, role=role) -> None:
                swatch.setStyleSheet(
                    f"background: {_showcase_colour(role, tokens).name()};"
                    " border-radius: 2px;"
                )

            _retheme_swatch(DEFAULT_THEME)
            _remember_retheme(swatch, _retheme_swatch)
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
        rule.setObjectName("showcaseDivider")
        rule.setFrameShape(QFrame.Shape.NoFrame)
        rule.setFixedHeight(1)
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
            cell.setProperty("divider", True)
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
                    cell.setProperty("divider", True)
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

    pill = QLabel(text)
    pill.setObjectName("showcaseJourneyPill")
    pill.setFont(make_font(10, 700, spacing=0.5))

    def _retheme(tokens) -> None:
        colour = _showcase_colour(_JOURNEY_PILL_ROLES.get(role, "muted"), tokens)
        # Mockup border rules, per class:
        #   .journey-pill                -> var(--border)
        #   .journey-pill.start/.active  -> var(--cyan-dim)   (a SOLID token)
        #   .journey-pill.evidence       -> #A78BFA 50%
        #   .journey-pill.completed      -> var(--green) 45%
        #   .journey-pill.terminal       -> inherits var(--border)
        if role in ("", "terminal"):
            border = tokens.border
        elif role in ("start", "active"):
            border = tokens.cyan_dim
        else:
            alpha_percent = 0.45 if role == "completed" else 0.50
            border = qalpha(colour, alpha_percent).name(QColor.NameFormat.HexArgb)
        pill.setStyleSheet(
            f"QLabel#showcaseJourneyPill {{ color: {colour.name()};"
            f" background: transparent; border: 1px solid {border};"
            f" border-radius: {RADIUS_SM}px; padding: 4px 10px; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(pill, _retheme)
    return pill


def showcase_journey_step(entry: tuple) -> QFrame:
    """``.journey-step`` -- 150px node: index, name, pill, timestamp."""

    index, name, pill_role, pill_text, stamp_label, stamp = entry
    box = QFrame()
    box.setObjectName("showcaseJourneyStep")
    box.setFrameShape(QFrame.Shape.NoFrame)
    box.setFixedWidth(150)

    def _retheme(tokens) -> None:
        edge = (
            qalpha(_showcase_colour("#A78BFA", tokens), 0.50).name(QColor.NameFormat.HexArgb)
            if pill_role == "evidence"
            else tokens.border
        )
        box.setStyleSheet(
            f"QFrame#showcaseJourneyStep {{ background: {tokens.surface_soft};"
            f" border: 1px solid {edge}; border-radius: {RADIUS_MD}px; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(box, _retheme)

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

    box = QFrame()
    box.setObjectName("showcaseFlowOutcome")
    box.setFrameShape(QFrame.Shape.NoFrame)
    box.setFixedWidth(150)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(12, 12, 12, 12)
    lay.setSpacing(4)
    head = QLabel(text)
    head.setFont(make_font(12, 700))
    head.setWordWrap(True)
    lay.addWidget(head)
    note = QLabel(sub)
    note.setFont(make_font(10, 400, mono=True))
    note.setWordWrap(True)
    lay.addWidget(note)

    def _retheme(tokens) -> None:
        colour = _showcase_colour("green" if kind == "returned" else "red", tokens)
        box.setStyleSheet(
            f"QFrame#showcaseFlowOutcome {{"
            f" background: {qalpha(colour, 0.12).name(QColor.NameFormat.HexArgb)};"
            f" border: 1px solid {qalpha(colour, 0.50).name(QColor.NameFormat.HexArgb)};"
            f" border-radius: {RADIUS_MD}px; }}"
        )
        text_style = f"color: {colour.name()}; background: transparent;"
        head.setStyleSheet(text_style)
        note.setStyleSheet(text_style)

    _retheme(DEFAULT_THEME)
    _remember_retheme(box, _retheme)
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
        self._theme = DEFAULT_THEME
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def apply_theme(self, tokens) -> None:
        self._theme = tokens
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setOpacity(0.6)
        pen = QPen(QColor(self._theme.muted))
        pen.setWidthF(1.4)
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(1.0, 4.0), QPointF(17.0, 4.0))
        solid = QPen(QColor(self._theme.muted))
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
    status_size: float = 19.0,
    detail: str = "",
) -> QFrame:
    """``.episode-banner`` -- 8% tint, 30% border, status left, outcome right.

    ``detail`` adds one muted line under the status value and publishes it as
    ``banner.detail_label`` so a live readout (Live MIRL's open-episode
    elapsed time) can be retitled in place instead of rebuilding the banner
    once a second.
    """

    tone = _showcase_colour("green" if ok else "red")
    banner = QFrame()
    banner.setObjectName("showcaseEpisodeBanner")
    banner.setFrameShape(QFrame.Shape.NoFrame)
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
    value: QLabel | None = None
    if status_value:
        value = QLabel(status_value)
        value.setFont(make_font(status_size, 700))
        value.setWordWrap(True)
        left.addWidget(value)
    detail_label: QLabel | None = None
    if detail:
        detail_label = label(detail, 11.5, 400, "muted")
        left.addWidget(detail_label)
    banner.detail_label = detail_label  # noqa: SLF001 -- see docstring
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

    def _retheme(tokens) -> None:
        banner.setStyleSheet(
            f"QFrame#showcaseEpisodeBanner {{"
            f" background: {mix(tone.name(), 8, tokens.surface)};"
            f" border: 1px solid {mix(tone.name(), 30, tokens.border)};"
            f" border-radius: {RADIUS_LG}px; }}"
        )
        if value is not None:
            value.setStyleSheet(f"color: {tone.name()}; background: transparent;")

    _retheme(DEFAULT_THEME)
    _remember_retheme(banner, _retheme)
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
    # ``.btn-cta svg`` -- the mockup puts a 12x12 play triangle before the
    # label.  Qt has no inline SVG in a button, so the same glyph is painted
    # once into a pixmap and re-painted on every world change.
    button.setIconSize(QSize(12, 12))

    def _retheme(tokens) -> None:
        button.setIcon(_showcase_play_icon(QColor(tokens.cyan)))
        hover_bg = qalpha(QColor(tokens.cyan), 0.10).name(QColor.NameFormat.HexArgb)
        pressed_bg = qalpha(QColor(tokens.cyan), 0.18).name(QColor.NameFormat.HexArgb)
        button.setStyleSheet(
            f"QPushButton#showcaseCta {{ background: transparent;"
            f" color: {tokens.cyan}; border: 1px solid {tokens.cyan_dim};"
            f" border-radius: {RADIUS_SM}px; padding: 11px 20px; }}"
            f"QPushButton#showcaseCta:disabled {{ color: {tokens.cyan};"
            f" border-color: {tokens.cyan_dim}; }}"
            f"QPushButton#showcaseCta:enabled:hover {{ background: {hover_bg};"
            f" color: {tokens.cyan}; border-color: {tokens.cyan}; }}"
            f"QPushButton#showcaseCta:enabled:pressed {{ background: {pressed_bg}; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(button, _retheme)
    return button


def showcase_chip_pill(text: str, role: str | None = None) -> QLabel:
    """``.chip-pill`` -- neutral-background status chip, coloured text/border."""

    chip = QLabel(text.upper())
    chip.setObjectName("showcaseChipPill")
    chip.setFont(make_font(10.5, 700, spacing=0.8))

    def _retheme(tokens) -> None:
        colour = _showcase_colour(role, tokens) if role else None
        text_colour = colour.name() if colour else tokens.muted
        border_colour = (
            qalpha(colour, 0.45).name(QColor.NameFormat.HexArgb) if colour else tokens.border
        )
        chip.setStyleSheet(
            f"QLabel#showcaseChipPill {{ color: {text_colour};"
            f" background: {_white_alpha(0.03)}; border: 1px solid {border_colour};"
            f" border-radius: {RADIUS_SM}px; padding: 6px 12px; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(chip, _retheme)
    return chip


def _mirl_html(value: object) -> str:
    """One recorded value, escaped for the rich-text summary."""

    return (
        _mirl_text(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _mirl_story_html(row: object, tokens) -> str:
    """One episode told as prose, with its recorded values highlighted.

    The words are identical for every episode and only the values change, so
    the shape of an episode reads at a glance instead of having to be
    reassembled from a key/value list.

    Every highlighted value is a recorded field.  Nothing is inferred, and a
    field MYELIN never recorded says so rather than being smoothed over -- an
    unmeasured latency reads as unmeasured, not as zero.  Colour follows the
    established rules: a verified return is green, a non-return is red, and
    integrity is green only when CONFIRMED and otherwise MUTED, never red,
    because degraded evidence is the ordinary condition of this surface.
    """

    muted = tokens.muted

    def plain(text: str) -> str:
        return f'<span style="color:{muted}">{text}</span>'

    def strong(value: object, role: str = "cyan") -> str:
        colour = _showcase_colour(role, tokens).name()
        return (
            f'<span style="color:{colour}; font-weight:700">'
            f"{_mirl_html(value)}</span>"
        )

    if row is None:
        return plain("No episode has been projected yet.")

    opened = _mirl_parse_any_utc(getattr(row, "started_at", None))
    application = str(getattr(row, "application", "") or "").strip()
    timeline = tuple(getattr(row, "timeline", ()) or ())
    outcome = getattr(row, "final_outcome", None)
    integrity = _mirl_text(
        getattr(getattr(row, "integrity_status", None), "value", None), "UNKNOWN"
    )

    lines = []

    # 1 -- which episode, when, and what pulled attention away.
    opened_at = plain(" opened on ") + strong(opened.strftime("%d %b %Y")) if opened else plain(" opened")
    lines.append(
        plain("Episode ")
        + strong(getattr(row, "short_display_id", None))
        + opened_at
        + plain(" at ")
        + strong(_mirl_clock_utc(getattr(row, "started_at", None)))
        + plain(" on ")
        + (strong(application) if application else plain("an unnamed surface"))
        + plain(" \u2014 trigger ")
        + strong(getattr(row, "source_event_id", None))
        + plain(", session ")
        + strong(getattr(row, "session_id", None))
        + plain(".")
    )

    # 2 -- how far SINE escalated, and how much evidence there is.
    last_event = getattr(timeline[-1], "event_name", None) if timeline else None
    lines.append(
        plain("MYELIN escalated as far as ")
        + strong(_mirl_highest_sine(row))
        + plain(" and recorded ")
        + strong(len(timeline))
        + plain(" event(s)")
        + (plain(", the last being ") + strong(last_event) if last_event else plain(""))
        + plain(".")
    )

    # 3 -- how it ended.  Each branch states only what the evidence supports.
    latency = _mirl_measured_return_latency(row)
    if _mirl_recovered(outcome):
        if latency is not None:
            lines.append(
                plain("You returned after ")
                + strong(_mirl_duration(latency), "green")
                + plain(", verified at ")
                + strong(_mirl_clock_utc(_mirl_recovered_at(row)), "green")
                + plain(".")
            )
        else:
            lines.append(
                plain("You returned, but the exact latency could not be measured.")
            )
    elif outcome is None:
        lines.append(plain("The episode is ") + strong("still open", "amber") + plain("."))
    elif _mirl_text(outcome) in _MIRL_UNNAMED_OUTCOMES:
        lines.append(plain("The episode ended when the ") + strong("emergency stop", "red") + plain(" was pressed."))
    else:
        lines.append(
            plain("You did not return ")
            + plain("\u2014 it ended ")
            + strong(_mirl_text(outcome).replace("_", " "), "red")
            + plain(".")
        )

    # 4 -- what the episode cost, and whether the evidence is sound.
    lines.append(
        plain("It carries ")
        + strong(getattr(row, "recovery_attempt_count", None))
        + plain(" recovery attempt(s) and ")
        + strong(getattr(row, "relapse_count", None))
        + plain(" relapse(s), with evidence integrity ")
        + strong(integrity, "green" if integrity == "CONFIRMED" else "muted")
        + plain(".")
    )

    return " ".join(lines)


def showcase_episode_story(row: object) -> QLabel:
    """``.gkv``'s prose cousin: one episode summarised in sentences.

    The rich text is rebuilt inside ``_retheme`` rather than once at
    construction, because the value colours are inlined into the HTML and a
    stylesheet swap alone would leave them on the old world's palette.
    """

    block = QLabel()
    block.setObjectName("showcaseStoryBlock")
    block.setFont(make_font(13, 400))
    block.setWordWrap(True)
    block.setTextFormat(Qt.TextFormat.RichText)
    block.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def _retheme(tokens) -> None:
        block.setStyleSheet(
            f"QLabel#showcaseStoryBlock {{ color: {tokens.text_primary};"
            f" background: {_white_alpha(0.02)}; border: 1px solid {_white_alpha(0.08)};"
            f" border-radius: {RADIUS_SM}px; padding: 16px 18px; }}"
        )
        block.setText(_mirl_story_html(row, tokens))

    _retheme(DEFAULT_THEME)
    _remember_retheme(block, _retheme)
    return block


def showcase_kv_block(text: str) -> QLabel:
    """``.gkv`` -- pre-wrapped monospace key/value block."""

    block = QLabel(text)
    block.setObjectName("showcaseKvBlock")
    block.setFont(make_font(12, 400, mono=True))
    block.setWordWrap(True)
    block.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def _retheme(tokens) -> None:
        block.setStyleSheet(
            f"QLabel#showcaseKvBlock {{ color: {tokens.text_primary};"
            f" background: {_white_alpha(0.02)}; border: 1px solid {_white_alpha(0.08)};"
            f" border-radius: {RADIUS_SM}px; padding: 14px 16px; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(block, _retheme)
    return block


def showcase_outline_button(text: str, *, small: bool = False) -> QPushButton:
    """``.btn-block.outline`` -- bordered neutral action, unconnected by default."""

    button = QPushButton(text.upper())
    button.setObjectName("showcaseOutlineButton")
    button.setFont(make_font(10.5 if small else 12, 700, spacing=1.0))
    padding = "7px 14px" if small else "11px 20px"

    def _retheme(tokens) -> None:
        button.setStyleSheet(
            f"QPushButton#showcaseOutlineButton {{ background: transparent;"
            f" color: {tokens.text_primary}; border: 1px solid {tokens.border};"
            f" border-radius: {RADIUS_SM}px; padding: {padding}; }}"
            f"QPushButton#showcaseOutlineButton:hover {{ color: {tokens.cyan};"
            f" border-color: {tokens.cyan_dim}; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(button, _retheme)
    return button


def _showcase_play_icon(colour: QColor) -> QIcon:
    """``.btn-cta svg`` -- the 12x12 filled play triangle ``M6 4l14 8-14 8V4z``."""

    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(colour)
    triangle = QPainterPath()
    # The mockup path is authored on a 24x24 viewBox; halve it for 12x12.
    triangle.moveTo(3.0, 2.0)
    triangle.lineTo(10.0, 6.0)
    triangle.lineTo(3.0, 10.0)
    triangle.closeSubpath()
    painter.drawPath(triangle)
    painter.end()
    return QIcon(pixmap)


def _showcase_chevron_button(forward: bool) -> QPushButton:
    """``.journey-nav button`` -- 26x26 bordered chevron beside the strip."""

    button = QPushButton("\u203a" if forward else "\u2039")
    button.setObjectName("showcaseJourneyNav")
    button.setFixedSize(26, 26)
    button.setFont(make_font(15, 700))
    button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def _retheme(tokens) -> None:
        button.setStyleSheet(
            f"QPushButton#showcaseJourneyNav {{ background: {tokens.surface_soft};"
            f" color: {tokens.muted}; border: 1px solid {tokens.border};"
            f" border-radius: {RADIUS_SM}px; padding: 0px; }}"
            f"QPushButton#showcaseJourneyNav:hover {{ color: {tokens.cyan};"
            f" border-color: {tokens.cyan_dim}; }}"
            f"QPushButton#showcaseJourneyNav:disabled {{ color: {tokens.border};"
            f" border-color: {tokens.border}; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(button, _retheme)
    return button


def _clear_layout(layout) -> None:
    """Drop every child of one layout, recursing into nested layouts."""

    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            # hide() MUST come before setParent(None).  Reparenting a visible
            # widget to no parent makes it a top-level window, and Qt then
            # shows it as a real OS window -- captioned with the application
            # name, because these fixtures set no window title -- on the next
            # event-loop pass, well before deleteLater() collects it.  Live
            # MIRL rebuilds these blocks on every projection and live-signal
            # tick, so each tick spawned a fresh stack of blank "MYELIN
            # Control Station" windows.  Hiding first latches the widget's
            # hidden state so the orphan can never be shown.
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
        elif child is not None:
            _clear_layout(child)


# --------------------------------------------------------------------------
# Live MIRL: one projection -> presentation
#
# Everything below reads a ``LiveMirlProjection`` prepared by
# ``MIRL.read_model``.  Nothing here recomputes episode truth, re-derives an
# outcome, or invents a journey node: an absent field renders as unavailable,
# never as a completed step.
# --------------------------------------------------------------------------

#: The Live MIRL presentation states.  ``degraded`` is deliberately NOT one of
#: them -- integrity is a MODIFIER layered over whichever state is showing.
#: On real evidence most episodes carry an integrity issue, so degraded is the
#: ORDINARY look on this surface and must never be styled as an alert.
MIRL_STATE_ENTRY: Final = "entry"
MIRL_STATE_EMPTY: Final = "empty"
MIRL_STATE_IDLE: Final = "idle-with-history"
MIRL_STATE_ACTIVE: Final = "active-episode"

#: ``MirlEventName`` value -> (journey pill role, pill label).  Every name in
#: MIRL's event contract is listed, so a real timeline never lands on the
#: neutral fallback by accident; an unknown future name still degrades safely.
_MIRL_EVENT_PILLS: Final = {
    "trigger_prepared": ("", "Prepared"),
    "first_display_timed_out": ("", "Timed Out"),
    "first_display_rejected": ("", "Rejected"),
    "episode_created": ("start", "Start"),
    "sine_displayed": ("active", "Active"),
    "sine_response_recorded": ("evidence", "Evidence"),
    "return_intent_recorded": ("evidence", "Evidence"),
    "sine_terminated": ("terminal", "Terminal"),
    "return_verification_started": ("active", "Active"),
    "return_unverified": ("", "Unverified"),
    "return_verification_interrupted": ("", "Interrupted"),
    "return_verification_completed": ("completed", "Completed"),
    "return_verified": ("completed", "Completed"),
    "closure_confirmation_started": ("active", "Active"),
    "closure_confirmation_interrupted": ("", "Interrupted"),
    "relapse_detected": ("", "Relapse"),
    "episode_resumed": ("active", "Active"),
    "closure_confirmation_completed": ("completed", "Completed"),
    "episode_closed": ("terminal", "Terminal"),
    "evidence_gap": ("", "Evidence Gap"),
    "emergency_stopped": ("terminal", "Terminal"),
}

#: The one outcome meaning the user actually came back.  ABORTED, EMERGENCY,
#: SESSION_ENDED and the read model's display-only NOT_RETURNED all closed
#: WITHOUT a verified recovery and must never be painted as a success.
_MIRL_RECOVERED_OUTCOME: Final = "RETURNED"

_MIRL_UNAVAILABLE: Final = "Unavailable"
_MIRL_NOT_RECORDED: Final = "Not Recorded"


def _mirl_text(value: object, empty: str = "\u2014") -> str:
    if value is None:
        return empty
    cleaned = " ".join(str(value).split())
    return cleaned or empty


def _mirl_parse_utc(value: object) -> "datetime | None":
    """Parse one projected UTC stamp; malformed evidence returns None."""

    text = str(value or "")
    if not text.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError:
        return None


def _mirl_clock(value: object) -> str:
    """``HH:MM:SS`` of a projected stamp -- the mockup's journey ``ts``."""

    moment = _mirl_parse_utc(value)
    return moment.strftime("%H:%M:%S") if moment else _mirl_text(value)


def _mirl_clock_utc(value: object) -> str:
    """``HH:MM UTC`` for an evidence-table time column.

    The UTC label is deliberate and must stay.  These stamps ARE UTC, and a
    bare "18:22" reads as the viewer's local clock -- the standing ruling from
    the Study Mode presentation audit, which applies to every surface, not
    just Study.

    Accepts BOTH the canonical ``...Z`` form and the ``+00:00`` offset form.
    The offset form is what the malformed-timestamp writer produced (see
    CORE_ENGINE/monitor.py ``_utc_now``); it still names an unambiguous UTC
    instant, so reading a clock off it is reading recorded evidence, not
    estimating one.  Integrity is untouched by this: the read model still
    flags those events, and the Data Quality tab still counts every one of
    them.  Only ``_mirl_parse_utc`` -- the strict parser used everywhere
    integrity matters -- keeps rejecting them.
    """

    moment = _mirl_parse_any_utc(value)
    if moment is None:
        return _MIRL_UNAVAILABLE
    return f"{moment.strftime('%H:%M')} UTC"


def _mirl_clock_utc_seconds(value: object) -> str:
    """``HH:MM:SS UTC`` -- used where a few seconds actually carry meaning.

    Trigger Time needs the seconds: the trigger fires roughly three seconds
    before SINE-1 displays, and at minute resolution the two columns would
    read identically and look like a duplicated field.
    """

    moment = _mirl_parse_any_utc(value)
    if moment is None:
        return _MIRL_UNAVAILABLE
    return f"{moment.strftime('%H:%M:%S')} UTC"


def _mirl_parse_any_utc(value: object) -> "datetime | None":
    """Parse a recorded UTC stamp in either form MYELIN has written.

    ``_mirl_parse_utc`` stays strict -- it governs everywhere integrity
    matters.  This one additionally accepts the ``+00:00`` offset form the
    malformed-timestamp writer produced (CORE_ENGINE/monitor.py ``_utc_now``),
    because that string still names an unambiguous instant and refusing to
    read it would hide real evidence from display without making anything
    truer.
    """

    text = str(value or "").strip()
    moment = _mirl_parse_utc(text)
    if moment is None and text.endswith("+00:00"):
        try:
            moment = datetime.fromisoformat(text)
        except ValueError:
            return None
    return moment


def _mirl_stamp(value: object) -> str:
    """``24 Jul 2026 - 12:11:51``, the mockup's evidence-table stamp."""

    moment = _mirl_parse_utc(value)
    if moment is None:
        return _mirl_UNAVAILABLE_or(value)
    return moment.strftime("%d %b %Y \u00b7 %H:%M:%S")


def _mirl_UNAVAILABLE_or(value: object) -> str:
    return _mirl_text(value, _MIRL_UNAVAILABLE)


def _mirl_duration(seconds: object) -> str:
    """Human duration for an already-measured span; never re-derives one."""

    if seconds is None or isinstance(seconds, bool):
        return _MIRL_UNAVAILABLE
    if not isinstance(seconds, (int, float)):
        return _MIRL_UNAVAILABLE
    total = int(max(0.0, float(seconds)))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours:02d}h"
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _mirl_latency(seconds: object) -> str:
    """A latency the read model measured, to one decimal, or an em dash."""

    if seconds is None or isinstance(seconds, bool):
        return "\u2014"
    if not isinstance(seconds, (int, float)):
        return "\u2014"
    return f"{float(seconds):.1f}s"


def _mirl_delta(first: object, second: object) -> str:
    """Gap between two projected stamps -- the mockup's ``jflowTimeDelta``."""

    start = _mirl_parse_utc(first)
    end = _mirl_parse_utc(second)
    if start is None or end is None:
        return "\u2014"
    gap = int((end - start).total_seconds())
    sign = "+" if gap >= 0 else "-"
    gap = abs(gap)
    hours, rest = divmod(gap, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{sign}{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{sign}{minutes:02d}:{secs:02d}"


def _mirl_elapsed(started_at: object, *, now=None) -> str:
    """How long an OPEN episode has been open.

    This is the one value on this surface computed in the presentation layer:
    the read model publishes ``started_at`` but no elapsed field, because
    elapsed depends on the current clock rather than on recorded evidence.
    It exists so an hours-old unresolved episode cannot read as though it had
    just begun.  It is never written anywhere and never feeds a metric.
    """

    opened = _mirl_parse_utc(started_at)
    if opened is None:
        return _MIRL_UNAVAILABLE
    moment = now or datetime.now(timezone.utc)
    return _mirl_duration((moment - opened).total_seconds())


def _mirl_event_title(event_name: object) -> str:
    return str(event_name or "").replace("_", " ").title() or "Event"


def _mirl_event_pill(event_name: object) -> tuple:
    key = str(event_name or "")
    if key in _MIRL_EVENT_PILLS:
        return _MIRL_EVENT_PILLS[key]
    return ("", _mirl_event_title(key))


def _mirl_recovered(outcome: object) -> bool:
    return str(outcome or "") == _MIRL_RECOVERED_OUTCOME


def _mirl_application_text(row: object) -> str:
    """What actually pulled attention away, not the token identifying it.

    ``application`` is resolved by the read model from Trigger's own recorded
    evidence (platform first, else the process it was observed in).  The
    opaque ``trg_...`` candidate_uid stays as the fallback: it is still true,
    merely unreadable, and showing it beats showing nothing where a trigger
    recorded no surface at all.
    """

    application = str(getattr(row, "application", "") or "").strip()
    if application:
        return application
    return _mirl_text(getattr(row, "candidate_uid", None), _MIRL_UNAVAILABLE)


def _mirl_highest_sine(row: object) -> str:
    stages = tuple(getattr(row, "sine_stages_exposed", ()) or ())
    return f"SINE-{max(stages)}" if stages else _MIRL_NOT_RECORDED


#: The live "SINE Stage" readout (Current Episode surfaces only -- Episode
#: History keeps using ``_mirl_highest_sine`` on the projected row, since a
#: past episode's highest stage is real history, not a live signal).
_SINE_STAGE_INACTIVE_TEXT: Final = "SINE INACTIVE"

#: ``SinePhase`` values (SINE/sine.py) in which a stage is actually in
#: flight. Mirrors ``_MIRL_ENGINE_ACTIVE_PHASES`` in spirit -- SINE.sine.py
#: is not imported here for its own types, so these are plain string values.
_SINE_ENGINE_ACTIVE_PHASES: Final = frozenset(
    {"waiting_for_display", "active", "protected_red"}
)


def _sine_stage_display(
    sine_view: object,
    live_view_last_seen: float | None,
    waiting_since: float,
    *,
    now: float | None = None,
) -> str:
    """"SINE-N" from a fresh, live-confirmed in-flight stage; "SINE INACTIVE"
    otherwise -- no trigger, no engine running, a resolved/cancelled stage,
    or a stale/lost signal all read the same way. Shares the MIRL badge's
    freshness timeout (ruling 3.1/4.2) so the two live indicators never
    disagree about whether the app is currently running.
    """

    moment = time.monotonic() if now is None else now
    reference = live_view_last_seen if live_view_last_seen is not None else waiting_since
    fresh = (moment - reference) <= _MIRL_LIVE_SIGNAL_TIMEOUT_SECONDS
    if not fresh or sine_view is None:
        return _SINE_STAGE_INACTIVE_TEXT
    phase = getattr(sine_view, "phase", None)
    phase_value = str(getattr(phase, "value", phase) or "")
    if phase_value not in _SINE_ENGINE_ACTIVE_PHASES:
        return _SINE_STAGE_INACTIVE_TEXT
    stage = getattr(sine_view, "stage", None)
    stage_value = getattr(stage, "value", stage)
    try:
        stage_num = int(stage_value)
    except (TypeError, ValueError):
        return _SINE_STAGE_INACTIVE_TEXT
    if stage_num <= 0:
        return _SINE_STAGE_INACTIVE_TEXT
    return f"SINE-{stage_num}"


def _mirl_session_text(
    live_view: object,
    live_view_last_seen: float | None,
    waiting_since: float,
    *,
    fallback: object = None,
    now: float | None = None,
) -> str:
    """The live session number, falling back to the last recorded one.

    Guideline: "session also must update after i press stop button ... so
    previous session and trigger numbers must be displayed". Two rules, in
    order:

    * While the engine is running and the live signal is fresh, this is the
      CURRENT session -- never a frozen number left over from before Stop.
    * Otherwise it shows ``fallback``: the session of the newest episode in
      the committed projection. Pressing Stop already forces one projection
      refresh (see ``engine_stopped`` in ``_connect_components``), so the
      number the user is left looking at is the session that just ended, not
      a stale live value and not a blank.

    "Not Recorded" is therefore reserved for the genuinely empty case -- no
    live signal AND no episode ever committed.
    """

    moment = time.monotonic() if now is None else now
    reference = live_view_last_seen if live_view_last_seen is not None else waiting_since
    fresh = (moment - reference) <= _MIRL_LIVE_SIGNAL_TIMEOUT_SECONDS
    if fresh and live_view is not None:
        session_id = getattr(live_view, "session_id", None)
        if session_id:
            return _mirl_text(session_id)
    return _mirl_text(fallback) if fallback else _MIRL_NOT_RECORDED


def _mirl_trigger_text(
    live_view: object,
    live_view_last_seen: float | None,
    waiting_since: float,
    *,
    fallback: object = None,
    now: float | None = None,
) -> str:
    """The live trigger id, falling back to the last recorded one.

    Guideline: "trigger must update from 57 to 58 when i trigger ... so
    previous session and trigger numbers must be displayed". Same two rules,
    same order, as ``_mirl_session_text``: the live id while an episode is
    actually running, otherwise ``fallback`` -- the ``source_event_id`` of
    the newest episode in the committed projection. So the tile sits on 57
    at rest and becomes 58 once the new episode exists.

    Honest caveat on WHEN it flips: ``MirlLiveView.operational_event_id`` is
    populated from the episode object only once one exists (see
    ``MirlAuthority.live_view()`` in the protected MIRL/mirl.py), so 58
    appears at the same moment the episode badge goes Active -- not one tick
    earlier, at raw detection before SINE-1 displays. The earlier
    pending-trigger token does carry the id internally, but exposing it would
    mean editing that protected file.
    """

    moment = time.monotonic() if now is None else now
    reference = live_view_last_seen if live_view_last_seen is not None else waiting_since
    fresh = (moment - reference) <= _MIRL_LIVE_SIGNAL_TIMEOUT_SECONDS
    if fresh and live_view is not None:
        operational_event_id = getattr(live_view, "operational_event_id", None)
        if operational_event_id:
            return _mirl_text(operational_event_id)
    return _mirl_text(fallback) if fallback else _MIRL_NOT_RECORDED


#: Which applied escalation window the SINE timer measures against, keyed by
#: the stage currently in flight.  SINE-3 is terminal -- it opens no further
#: window -- so it is deliberately absent rather than mapped to a guess.
_SINE_TIMER_STAGE_WINDOWS: Final = {
    1: "stage_2_delay_seconds_applied",
    2: "stage_3_delay_seconds_applied",
}


def _mirl_is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _sine_clock(seconds: object) -> str:
    """MM:SS for an already-measured span."""

    total = int(max(0.0, float(seconds)))
    return f"{total // 60:02d}:{total % 60:02d}"


def _sine_timer_text(
    sine_view: object,
    sine_view_last_seen: float | None,
    waiting_since: float,
    *,
    now: float | None = None,
) -> str:
    """Time served against the SINE window in flight, as ``MM:SS / MM:SS``.

    Both halves are the engine's own numbers: ``next_deadline_seconds`` is the
    time SINE says is left, and ``stage_N_delay_seconds_applied`` is the window
    it actually applied for this session, already personalised by the F factor.
    Served time is their difference.  Nothing here selects a stage, sets a
    deadline or assumes a baseline -- a hardcoded "5:00" would be an invented
    number, since the applied window varies per session (the SINE-1 -> SINE-2
    baseline alone is 600s BEFORE personalisation).

    Deliberately NOT interpolated between engine ticks.  The monitor publishes
    a fresh SineLiveView every poll; counting down locally in between would put
    a figure on screen that SINE never published, and the launcher cannot
    compare monotonic clocks across the engine boundary anyway.  Same freshness
    rule and blank-on-stale behaviour as the SINE Stage readout, so the two
    never disagree about whether a stage is running.
    """

    moment = time.monotonic() if now is None else now
    reference = sine_view_last_seen if sine_view_last_seen is not None else waiting_since
    if (moment - reference) > _MIRL_LIVE_SIGNAL_TIMEOUT_SECONDS or sine_view is None:
        return "\u2014"
    phase = getattr(sine_view, "phase", None)
    if str(getattr(phase, "value", phase) or "") not in _SINE_ENGINE_ACTIVE_PHASES:
        return "\u2014"
    stage = getattr(sine_view, "stage", None)
    try:
        stage_num = int(getattr(stage, "value", stage))
    except (TypeError, ValueError):
        return "\u2014"
    field = _SINE_TIMER_STAGE_WINDOWS.get(stage_num)
    if field is None:
        return "\u2014"
    window = getattr(sine_view, field, None)
    remaining = getattr(sine_view, "next_deadline_seconds", None)
    if not _mirl_is_number(window) or not _mirl_is_number(remaining) or window <= 0:
        return "\u2014"
    # Count ON from the snapshot rather than freezing on it.  The monitor
    # publishes every DEFAULT_POLL_SECONDS (1.5s), which does not divide into
    # whole seconds, so rendering the raw snapshot skipped one second in three
    # (00:00, 00:01, 00:03, 00:04, 00:06 ...).
    #
    # ``reference`` is ``sine_view_last_seen`` -- the local instant THIS
    # snapshot arrived -- so what is added is a LOCAL elapsed delta, never a
    # comparison against the engine's own clock.  Every arriving snapshot
    # re-anchors it, so the reading cannot drift further than one poll, and the
    # staleness gate above blanks the tile entirely once SINE goes quiet.  This
    # is display-only, exactly like ``_mirl_elapsed``: never written, never
    # counted, never feeding a metric.
    since_snapshot = max(0.0, moment - reference)
    remaining_now = max(0.0, float(remaining) - since_snapshot)
    served = min(float(window), max(0.0, float(window) - remaining_now))
    return f"{_sine_clock(served)} / {_sine_clock(window)}"


#: Outcomes that keep reading "unavailable" instead of being named.
#: EMERGENCY is deliberately here (Dharshan, 2026-09-01): naming it belongs
#: with the emergency follow-up history work, which is parked, so the surface
#: stays exactly as it was rather than half-telling that story.
_MIRL_UNNAMED_OUTCOMES: Final = frozenset({"EMERGENCY"})


def _mirl_last_timeline_event(row: object, event_name: str):
    """The LAST timeline event of one name, or ``None``.

    Last rather than first: an episode that relapsed and recovered again
    carries several verification events, and the final one is the return that
    actually stuck.
    """

    found = None
    for event in tuple(getattr(row, "timeline", ()) or ()):
        if str(getattr(event, "event_name", "")) == event_name:
            found = event
    return found


def _mirl_recovered_at(row: object) -> object:
    """When the return was VERIFIED -- the moment this episode recovered.

    Deliberately not the episode's last event.  That is the closure record,
    which lands about a minute later once closure confirmation completes, and
    reading it as the recovery time overstates every return by that gap.
    """

    event = _mirl_last_timeline_event(row, "return_verified")
    return getattr(event, "occurred_at", None) if event is not None else None


def _mirl_measured_return_latency(row: object) -> float | None:
    """Seconds from SINE-1 displaying to the return being verified.

    Measured from the two stamps this table already shows -- Time Distracted
    and Time Recovered -- so the column is the visible subtraction of its own
    neighbours and can be checked by eye.

    This is computed here rather than read from the projection ON PURPOSE, and
    the trade is worth stating plainly: the read model suppresses
    ``verified_return_latency_seconds`` for any episode carrying an integrity
    issue, which on current evidence is nearly all of them, so the column was
    blank for 25 episodes that genuinely did return.  Cross-checked against
    the one episode the read model does measure, this agrees to 1.3 seconds
    (646.5s here vs 647.8s there) -- the difference being wall clock versus
    the monotonic clock the read model uses.

    It invents nothing: both stamps are recorded evidence, and a pair that
    cannot be read, or that runs backwards, yields ``None`` rather than a
    number.
    """

    start = _mirl_parse_any_utc(getattr(row, "started_at", None))
    recovered = _mirl_parse_any_utc(_mirl_recovered_at(row))
    if start is None or recovered is None:
        return None
    seconds = (recovered - start).total_seconds()
    return seconds if seconds >= 0 else None


def _mirl_evidence_return_latency(row: object, recovered: bool) -> str:
    """Return Latency for the evidence table: Time Recovered minus Time Distracted.

    Gated on the SAME ``recovered`` test that gates the Time Recovered column,
    so this cell is always the visible subtraction of its two neighbours.

    That gate matters on real evidence: three episodes DID have a verified
    return and then ended NOT_RETURNED, ABORTED or EMERGENCY after relapsing.
    Printing a duration there while Time Recovered reads unavailable would put
    a number in the row that the row itself cannot account for, so those read
    their outcome instead.
    """

    if recovered:
        seconds = _mirl_measured_return_latency(row)
        if seconds is not None:
            return _mirl_duration(seconds)
    return _mirl_non_return_label(row) or _MIRL_UNAVAILABLE


def _mirl_non_return_label(row: object) -> str:
    """The outcome that explains a missing return, or ``""`` if none does.

    Names the ACTUAL ending -- NOT RETURNED, ABORTED -- rather than collapsing
    every non-return into one word, so "unavailable" can go back to meaning
    just one thing: MYELIN could not measure it.

    Two cases deliberately return ``""`` and so keep reading unavailable:
    an episode that DID return but whose latency was suppressed (a measurement
    gap, not an outcome), and any outcome in ``_MIRL_UNNAMED_OUTCOMES``.
    """

    if row is None:
        return ""
    outcome = getattr(row, "final_outcome", None)
    if outcome is None or _mirl_recovered(outcome):
        return ""
    text = _mirl_text(outcome)
    if text in _MIRL_UNNAMED_OUTCOMES:
        return ""
    return text.replace("_", " ").upper()


def _mirl_return_latency_text(focus: object) -> str:
    """The focused episode's SINE-1 to verified-return latency, or why none.

    ``verified_return_latency_seconds`` is measured BY THE READ MODEL from the
    episode's own start -- the instant the trigger minted it, which is SINE-1 --
    to the verified-return event.  It is exactly the span this tile names, and
    is never recomputed on this side.

    A closed episode that never returned reads NOT RETURNED rather than
    borrowing the previous episode's latency: printing another episode's number
    under this episode's heading would state something untrue about it.
    """

    if focus is None:
        return "\u2014"
    latency = getattr(focus, "verified_return_latency_seconds", None)
    if latency is not None:
        return _mirl_latency(latency)
    # Still open, or returned with no measured latency -> unmeasured, which is
    # not the same claim as naming how the episode actually ended.
    return _mirl_non_return_label(focus) or "\u2014"


def _mirl_verified_return_count_text(projection: object) -> str:
    """How many episodes actually reached a verified RETURNED outcome.

    Counted from the episode rows this surface is showing, by the SAME rule the
    evidence table uses, so the tile cannot contradict the column beneath it.

    ``native_outcome_counts`` is deliberately NOT used here: it buckets any
    integrity-degraded episode as DEGRADED rather than RETURNED, which on
    current evidence reported 1 verified return while the table listed 26 real
    ones.  It stays as the fallback when no rows are present, so an empty
    capped list can never read as "no returns" when the read model knows
    better.

    Caveat inherited from the row list: it is capped at
    MAX_RECENTLY_CLOSED_EPISODES (100).  Below that -- 56 episodes today --
    this is the true total.  Zero is a real answer and renders as "0".
    """

    episodes = _mirl_projection_episodes(projection)
    if episodes:
        return str(
            sum(
                1
                for row in episodes
                if _mirl_recovered(getattr(row, "final_outcome", None))
            )
        )
    counts = getattr(projection, "native_outcome_counts", None)
    getter = getattr(counts, "get", None)
    if not callable(getter):
        return "\u2014"
    value = getter(_MIRL_RECOVERED_OUTCOME)
    return str(value) if _mirl_is_number(value) and isinstance(value, int) else "\u2014"


def _mirl_day_label(row: object) -> str:
    """The UTC day an episode opened, as ``31 Aug 2026``.

    The episode's display id already carries this date (EPI-DDMMYYYY-NN), but
    reading it off the id would be parsing a presentation string; this reads
    the recorded stamp instead.  An unreadable stamp is named as such rather
    than silently grouped with a real day.
    """

    moment = _mirl_parse_any_utc(getattr(row, "started_at", None))
    return moment.strftime("%d %b %Y") if moment else "Date unavailable"


def _mirl_day_heading(day: str, count: int) -> QWidget:
    """One date separator above the episodes recorded on that day."""

    host = QWidget()
    host.setObjectName("plainBox")
    row = QHBoxLayout(host)
    row.setContentsMargins(2, 0, 2, 0)
    row.setSpacing(10)
    row.addWidget(label(day, 12.5, 700, "cyan", spacing=1.4, upper=True))
    row.addWidget(
        label(f"{count} episode(s)" if count != 1 else "1 episode", 11, 400, "muted")
    )
    row.addStretch(1)
    return host


def _glass_episode_picker() -> QComboBox:
    """The Event Timeline's episode chooser, styled like the glass overlay.

    Built with a per-instance stylesheet plus ``_remember_retheme`` rather than
    a QSS rule, because ``theme.py`` styles only the Control page's profile
    combo and this one lives inside the dashboard overlay.
    """

    box = QComboBox()
    box.setObjectName("mirlEpisodePicker")
    box.setFont(make_font(11.5, 600))
    box.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    box.setAccessibleName("Choose which episode's timeline to show")

    def _retheme(tokens) -> None:
        box.setStyleSheet(
            f"QComboBox#mirlEpisodePicker {{ background: {tokens.surface_soft};"
            f" color: {tokens.text_primary}; border: 1px solid {tokens.border};"
            f" border-radius: {RADIUS_SM}px; padding: 6px 10px; }}"
            f"QComboBox#mirlEpisodePicker:hover {{ border-color: {tokens.cyan_dim}; }}"
            f"QComboBox#mirlEpisodePicker::drop-down {{ border: none; width: 18px; }}"
            f"QComboBox#mirlEpisodePicker QAbstractItemView {{"
            f" background: {tokens.surface}; color: {tokens.text_primary};"
            f" border: 1px solid {tokens.border};"
            f" selection-background-color: {tokens.surface_soft};"
            f" selection-color: {tokens.cyan}; outline: none; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(box, _retheme)
    return box


def _mirl_projection_episodes(projection: object) -> tuple:
    """Every episode row a projection carries, active first."""

    return tuple(getattr(projection, "active_episodes", ()) or ()) + tuple(
        getattr(projection, "recently_closed_episodes", ()) or ()
    )


def _mirl_worst_drift_text(projection: object) -> str:
    """The longest single drift MYELIN has sound evidence for.

    The read model's ``worst_return_latency_seconds``: the maximum
    verified-return latency across EVERY recorded episode, not the capped
    window the launcher receives, so the launcher must not recompute it from
    ``recently_closed_episodes``.

    Rendered as a duration rather than raw seconds -- the worst case runs to
    tens of minutes, and "1951.1s" is not a readable answer to "how long was
    my worst drift".  Unavailable until at least one episode has a measured
    verified return; an episode that never returned has no return latency at
    all and can never be the worst *return*.
    """

    prepared = getattr(projection, "worst_return_latency_seconds", None)
    candidates = [prepared] if _mirl_is_number(prepared) else []
    # Measured the SAME way the evidence table measures each row, so the tile
    # can never contradict the column it summarises.  Without this the tile
    # read 10m 47s -- the single episode the read model still measures --
    # while the table plainly showed a 32m 29s drift two rows down.
    for row in _mirl_projection_episodes(projection):
        if not _mirl_recovered(getattr(row, "final_outcome", None)):
            continue
        seconds = _mirl_measured_return_latency(row)
        if seconds is not None:
            candidates.append(seconds)
    return _mirl_duration(max(candidates)) if candidates else _mirl_duration(None)


#: Distinct issue kinds listed in the Data Quality digest before it stops.
#: This bounds DISTINCT kinds, not occurrences -- every occurrence is still
#: counted into its kind, so no total is ever hidden by the cap.
_MIRL_ISSUE_DIGEST_KINDS: Final = 12


def _mirl_issue_digest(
    issues: object,
    exclusions: object,
    *,
    limit: int = _MIRL_ISSUE_DIGEST_KINDS,
) -> str:
    """One counted line per DISTINCT integrity issue, worst offender first.

    Real evidence repeats the same issue across hundreds of events: a single
    malformed-timestamp writer produced 276 identical
    ``INVALID_WALL_TIMESTAMP`` lines here.  Printing them one per line said
    nothing 276 lines could that one counted line cannot, and buried every
    other finding in the panel.

    Grouping also stops the previous truncation from misleading.  Listing the
    first 40 occurrences reported "40" of something there were 276 of; the
    count here is the TRUE total for that kind, and the cap applies only to
    how many distinct KINDS are listed.
    """

    grouped: dict[tuple[str, str, str], int] = {}

    for issue in tuple(issues or ()):
        key = (
            _mirl_text(getattr(getattr(issue, "severity", None), "value", None)),
            _mirl_text(getattr(issue, "code", None)),
            _mirl_text(getattr(issue, "detail", None)),
        )
        grouped[key] = grouped.get(key, 0) + 1

    for item in tuple(exclusions or ()):
        key = (
            "EXCLUDED",
            _mirl_text(getattr(item, "metric", None)),
            _mirl_text(getattr(item, "reason", None)),
        )
        grouped[key] = grouped.get(key, 0) + 1

    if not grouped:
        return "No integrity issue or metric exclusion was recorded."

    # Worst offender first, then alphabetical so equal counts stay stable
    # across refreshes instead of shuffling under the reader.
    ranked = sorted(grouped.items(), key=lambda pair: (-pair[1], pair[0][1], pair[0][2]))
    lines = [
        f"[{severity}] {code}"
        + (f" \u00d7{count}" if count > 1 else "")
        + f" \u2014 {detail}"
        for (severity, code, detail), count in ranked[:limit]
    ]
    if len(ranked) > limit:
        remaining = sum(count for _, count in ranked[limit:])
        lines.append(
            f"\u2026 and {len(ranked) - limit} more kinds "
            f"({remaining} occurrences) not listed here."
        )
    return "\n".join(lines)


def _mirl_state(projection: object) -> str:
    """Resolve the data state.  Integrity is handled separately, as a modifier."""

    if projection is None:
        return MIRL_STATE_ENTRY
    if not bool(getattr(projection, "available", False)):
        return MIRL_STATE_EMPTY
    if tuple(getattr(projection, "active_episodes", ()) or ()):
        return MIRL_STATE_ACTIVE
    return MIRL_STATE_IDLE


def _mirl_effective_focus(
    projection: object,
    live_view: object,
    live_view_last_seen: float | None,
    waiting_since: float,
    *,
    now: float | None = None,
):
    """Which episode's content the Current Episode / Event Journey show.

    Preferring ``active_episodes[0]`` outright would be wrong: that "active"
    row can be nothing more than the single still-unclosed episode MIRL
    happens to be carrying in its history.  If nobody ever closes it, it sits
    there forever, silently outranking every genuinely more recent,
    cleanly-closed episode (guideline: "make sure it shows the latest one" --
    a day-old abandoned episode must not hide a real episode from an hour
    ago).

    When the live engine actually confirms an episode is running right now
    (the same check the "Episode Active" badge uses, ruling 3.1/4.2), this
    shows that episode, matching the badge. Otherwise it shows whichever
    episode -- open or closed -- genuinely started most recently.
    """

    if projection is None:
        return None
    active = tuple(getattr(projection, "active_episodes", ()) or ())
    closed = tuple(getattr(projection, "recently_closed_episodes", ()) or ())
    state, _ = _mirl_effective_state(
        projection, live_view, live_view_last_seen, waiting_since, now=now
    )
    if state == MIRL_STATE_ACTIVE and active:
        return active[0]
    candidates = active + closed
    if not candidates:
        return None
    return max(candidates, key=lambda row: str(getattr(row, "started_at", "") or ""))


#: Mirrors ``MirlAuthority._ACTIVE_PHASES`` in MIRL/mirl.py (private, not
#: exported, and mirl.py is protected -- never imported here for its own
#: types). These are the coarse phases in which a real recovery episode is
#: in flight. Keep in sync if that set ever changes.
_MIRL_ENGINE_ACTIVE_PHASES: Final = frozenset(
    {"WAITING_FOR_RETURN", "RETURN_VERIFICATION", "CLOSURE_CONFIRMATION"}
)

#: monitor.py republishes "mirl_health_status" on every monitoring cycle
#: unconditionally (see monitor.py's ``_publish_live_views``), so once the
#: engine is running this signal is effectively continuous. A gap shorter
#: than this is a normal startup window; a gap longer than this means the
#: connection itself -- not the episode -- is the problem, and is surfaced
#: to the user rather than silently trusted.
_MIRL_LIVE_SIGNAL_TIMEOUT_SECONDS: Final = 5.0


def _mirl_live_active(live_view: object) -> bool | None:
    """True/False from a real engine snapshot; ``None`` if there is none."""

    if live_view is None:
        return None
    episode_id = str(getattr(live_view, "episode_id", "") or "")
    if not episode_id:
        return False
    phase = getattr(live_view, "phase", None)
    phase_value = str(getattr(phase, "value", phase) or "")
    return phase_value in _MIRL_ENGINE_ACTIVE_PHASES


def _mirl_effective_state(
    projection: object,
    live_view: object,
    live_view_last_seen: float | None,
    waiting_since: float,
    *,
    now: float | None = None,
) -> tuple[str, bool]:
    """Resolve the live "episode active" state and the live-signal health flag.

    The read model alone cannot tell a genuinely open episode from one
    abandoned by a session that already ended -- it only sees history. So
    the active badge trusts ONLY a fresh, live, positive confirmation from
    the running engine: no engine running, no live signal received yet, a
    stale/lost signal, or a live signal that itself reports no active
    episode -- all of these show INACTIVE. The DB projection is NEVER used
    on its own to promote this badge to active -- see Chief's ruling 3.1/4.2
    ("must show Episode Inactive when there is no MYELIN activity"). Every
    other Live MIRL surface (episode list, timeline, evidence, and the
    focus episode's own content when idle) still comes from the projection,
    unchanged.

    Returns ``(state, live_signal_degraded)``. ``live_signal_degraded`` is
    True only once the live engine has gone quiet for longer than a normal
    startup gap; it is purely informational and never promotes the state
    above, which already defaults to inactive with no live confirmation.
    """

    state = _mirl_state(projection)
    moment = time.monotonic() if now is None else now
    reference = live_view_last_seen if live_view_last_seen is not None else waiting_since
    fresh = (moment - reference) <= _MIRL_LIVE_SIGNAL_TIMEOUT_SECONDS
    if state == MIRL_STATE_ACTIVE and (not fresh or _mirl_live_active(live_view) is not True):
        state = MIRL_STATE_IDLE
    return state, not fresh


def _mirl_journey_step(event: object) -> tuple:
    """One ``showcase_journey_step`` tuple built only from a projected event."""

    role, pill_text = _mirl_event_pill(getattr(event, "event_name", ""))
    return (
        getattr(event, "episode_seq", 0),
        _mirl_event_title(getattr(event, "event_name", "")),
        role,
        pill_text,
        str(getattr(event, "observed_or_derived", "") or "").title() or "Recorded",
        _mirl_clock(getattr(event, "occurred_at", "")),
    )


def _mirl_fill_journey_strip(layout, row: object) -> None:
    """Rebuild one journey strip from an episode row's projected timeline.

    A closed episode's final event becomes the mockup's coloured terminal
    node; green ONLY for a verified RETURNED outcome, red for every other
    ending, including the display-only NOT_RETURNED.
    """

    _clear_layout(layout)
    timeline = tuple(getattr(row, "timeline", ()) or []) if row is not None else ()
    if not timeline:
        layout.addWidget(
            label(
                "No recorded event evidence for this episode.",
                12,
                400,
                "muted",
            )
        )
        layout.addStretch(1)
        return

    outcome = getattr(row, "final_outcome", None)
    closed = outcome is not None
    kind = "returned" if _mirl_recovered(outcome) else "terminal-red"
    for position, event in enumerate(timeline):
        last = position == len(timeline) - 1
        entry = _mirl_journey_step(event)
        if last and closed:
            layout.addWidget(
                showcase_flow_outcome(
                    _mirl_text(outcome),
                    f"{entry[4]} \u00b7 {entry[5]}",
                    kind,
                ),
                0,
                Qt.AlignmentFlag.AlignVCenter,
            )
        else:
            layout.addWidget(showcase_journey_step(entry))
        if not last:
            layout.addWidget(
                ShowcaseFlowLink(
                    _mirl_delta(
                        getattr(event, "occurred_at", ""),
                        getattr(timeline[position + 1], "occurred_at", ""),
                    )
                ),
                0,
                Qt.AlignmentFlag.AlignVCenter,
            )
    layout.addStretch(1)


class LiveMirlShowcasePage(QWidget):
    """The Live MIRL launcher page, reproduced from the approved mockup.

    Presentation only.  Every value comes from one ``LiveMirlProjection``
    handed to :meth:`render_projection` by ``AnalyticsController``'s single
    shared refresh lane -- this page owns no MIRL runtime, opens no database,
    reads no SQL and derives no episode truth.  The one value computed here
    is how long an open episode has been open (``_mirl_elapsed``), which the
    read model cannot publish because it depends on the current clock.

    It implements exactly the contract ``AnalyticsController`` already uses
    for its own dashboard pages -- a ``refresh_requested`` signal plus
    ``render_projection`` / ``set_refreshing`` / ``show_refresh_failure`` --
    so it joins the existing refresh lane rather than opening a second one.
    It deliberately exposes neither ``request_refresh`` nor ``ready``, so
    NavigationController still treats it as ready on the next event-loop
    turn, exactly as before.
    """

    refresh_requested = pyqtSignal()

    #: Cadence of the open-episode elapsed readout.  ONE timer, owned by this
    #: page, running only while an open episode is actually on screen.
    ELAPSED_TICK_MS: Final = 1000

    #: One journey node (150px) plus the strip's 6px gap.
    _STRIP_STEP_PX: Final = 156

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("showcasePage")
        self.setAccessibleName("Live MIRL showcase")
        self._dashboard_dialog: LiveMirlDashboardDialog | None = None
        self._projection: object | None = None
        self._refreshing = False
        self._failed = False
        self._banner: QFrame | None = None
        # The SINE timer's own figure label, refreshed in place once a second
        # between engine ticks; ``_sine_timer_measured`` tracks whether it is
        # currently showing a real value, so the tick knows when a full tile
        # rebuild (colour and figure size change) is actually required.
        self._sine_timer_label: QLabel | None = None
        self._sine_timer_measured = False

        # Live engine signal (ruling 3.1/4.2) -- independent of the
        # projection refresh lane. See MirlAuthority.live_view() /
        # EngineController.mirl_health_status_changed.
        self._live_view: object | None = None
        self._live_view_last_seen: float | None = None
        self._constructed_at: float = time.monotonic()
        self._live_degraded = False

        # Live SINE stage (guideline: "SINE INACTIVE" with no trigger, else
        # the real in-flight stage). Shares ``_constructed_at`` as its
        # startup-grace reference with the live episode signal above.
        self._sine_view: object | None = None
        self._sine_view_last_seen: float | None = None

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

        # Mockup block order for #page-live-mirl: topline, episode banner,
        # 3-up metric stats, journey card, 4-up outcome stats, and the CTA
        # row LAST, right-aligned (``.btn-cta-row { justify-content: flex-end }``).
        self._topline_host = QVBoxLayout()
        self._topline_host.setContentsMargins(0, 0, 0, 0)
        wrap.addLayout(self._topline_host)

        self._banner_host = QVBoxLayout()
        self._banner_host.setContentsMargins(0, 0, 0, 0)
        wrap.addLayout(self._banner_host)

        self._stats_host = QGridLayout()
        self._stats_host.setHorizontalSpacing(16)
        wrap.addLayout(self._stats_host)

        wrap.addWidget(self._build_journey_card())

        self._outcome_host = QGridLayout()
        self._outcome_host.setHorizontalSpacing(16)
        wrap.addLayout(self._outcome_host)

        cta_row = QHBoxLayout()
        cta_row.addStretch(1)
        # Manual refresh drives the SAME lane page navigation and Stop already
        # use (AnalyticsController._create_page wires refresh_requested to the
        # real refresh) -- it is a second caller, never a second mechanism.
        self._refresh_button = showcase_outline_button("Refresh")
        self._refresh_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        cta_row.addWidget(self._refresh_button)
        cta_row.addSpacing(10)
        self._open_dashboard_button = showcase_cta("Open Full Dashboard")
        self._open_dashboard_button.setEnabled(True)
        self._open_dashboard_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._open_dashboard_button.clicked.connect(self._open_full_dashboard)
        cta_row.addWidget(self._open_dashboard_button)
        wrap.addLayout(cta_row)

        wrap.addStretch(1)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(self.ELAPSED_TICK_MS)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

        self._render()

    # -- analytics refresh-lane contract --------------------------------------

    def render_projection(self, projection: object) -> None:
        self._projection = projection
        self._failed = False
        self._render()
        dialog = self._dashboard_dialog
        if dialog is not None:
            dialog.render_projection(projection)

    def render_live_view(self, live_view: object | None) -> None:
        """One ``MirlLiveView`` snapshot from the running engine, or ``None``.

        ``None`` is the same reset sentinel ``EngineController`` uses for
        every other replace-in-place card at session start -- it clears the
        cached snapshot and restarts the startup grace window rather than
        immediately reporting the live signal as unavailable.
        """

        if live_view is None:
            self._live_view = None
            self._live_view_last_seen = None
            self._constructed_at = time.monotonic()
        else:
            self._live_view = live_view
            self._live_view_last_seen = time.monotonic()
        self._render()
        dialog = self._dashboard_dialog
        if dialog is not None:
            dialog.apply_live_view(self._live_view, self._live_view_last_seen, self._constructed_at)

    def render_sine_view(self, sine_view: object | None) -> None:
        """One ``SineLiveView`` snapshot from ``EngineController.sine_watch_
        status_changed`` -- the SAME signal the Control page already
        consumes; this page is simply a second subscriber. ``None`` is the
        session-reset sentinel, same convention as :meth:`render_live_view`.
        """

        if sine_view is None:
            self._sine_view = None
            self._sine_view_last_seen = None
        else:
            self._sine_view = sine_view
            self._sine_view_last_seen = time.monotonic()
        self._render()
        dialog = self._dashboard_dialog
        if dialog is not None:
            dialog.apply_sine_view(self._sine_view, self._sine_view_last_seen, self._constructed_at)

    def _sine_stage_text(self) -> str:
        return _sine_stage_display(self._sine_view, self._sine_view_last_seen, self._constructed_at)

    def _session_text(self, focus: object) -> str:
        return _mirl_session_text(
            self._live_view,
            self._live_view_last_seen,
            self._constructed_at,
            fallback=getattr(focus, "session_id", None),
        )

    def _trigger_text(self, focus: object) -> str:
        return _mirl_trigger_text(
            self._live_view,
            self._live_view_last_seen,
            self._constructed_at,
            fallback=getattr(focus, "source_event_id", None),
        )

    def _sine_timer_text(self) -> str:
        return _sine_timer_text(
            self._sine_view, self._sine_view_last_seen, self._constructed_at
        )

    def set_refreshing(self, refreshing: bool) -> None:
        self._refreshing = bool(refreshing)
        # Same busy contract as analytics.DashboardPage.set_refreshing.
        self._refresh_button.setEnabled(not self._refreshing)
        self._render_topline()

    def show_refresh_failure(self) -> None:
        # Keep the last honest snapshot on screen; only the status line
        # changes, exactly as DashboardPage does.
        self._failed = True
        self._render_topline()

    # -- rendering ------------------------------------------------------------

    def _render(self) -> None:
        state, self._live_degraded = self._effective_state()
        focus = self._effective_focus()
        self._render_topline()
        self._render_banner(state, focus)
        self._render_stats(focus)
        self._render_journey(state, focus)
        self._render_outcomes(focus)

        # Two readouts share the per-second tick now: the open-episode
        # "Open for ..." line and the SINE timer.  Either alone is reason to
        # keep it running.  ``_render_outcomes`` ran just above, so
        # ``_sine_timer_measured`` is current.
        wants_tick = state == MIRL_STATE_ACTIVE or self._sine_timer_measured
        if wants_tick and not self._elapsed_timer.isActive():
            self._elapsed_timer.start()
        elif not wants_tick and self._elapsed_timer.isActive():
            self._elapsed_timer.stop()

    def _effective_state(self) -> tuple[str, bool]:
        return _mirl_effective_state(
            self._projection,
            self._live_view,
            self._live_view_last_seen,
            self._constructed_at,
        )

    def _effective_focus(self):
        return _mirl_effective_focus(
            self._projection,
            self._live_view,
            self._live_view_last_seen,
            self._constructed_at,
        )

    def _render_topline(self) -> None:
        """Topline hint carries evidence scope, integrity and refresh status.

        Integrity lives here, in muted body text, rather than as a coloured
        alert: on real evidence most episodes carry an integrity issue, so
        DEGRADED is the ordinary condition of this surface, not an emergency.
        """

        projection = self._projection
        # Kept SHORT deliberately.  ``.mirl-topline``'s hint does not wrap, so
        # a long sentence here widens the whole page past the window and forces
        # a horizontal scrollbar across every block below it.  The full status
        # message and every integrity issue live on the dashboard's Data
        # Quality tab instead.
        parts: list[str] = []
        if self._failed:
            parts.append(
                "Refresh failed — last recorded evidence"
                if projection is not None
                else "Evidence unavailable"
            )
        elif self._refreshing:
            parts.append("Refreshing…")
        if self._live_degraded:
            parts.append("Live signal unavailable")
        if projection is None:
            parts.append("No projection loaded yet")
        else:
            parts.append("All committed evidence")
            integrity = getattr(projection, "integrity_status", None)
            parts.append(
                f"Integrity: {_mirl_text(getattr(integrity, 'value', integrity), 'UNKNOWN')}"
            )
            metadata = getattr(projection, "metadata", None)
            exclusions = getattr(metadata, "exclusion_count", None)
            if isinstance(exclusions, int):
                parts.append(f"{exclusions} Exclusions")
        _clear_layout(self._topline_host)
        host = showcase_topline(
            "Live MIRL \u2014 Authoritative Overview",
            "  |  ".join(part for part in parts if part),
        )
        self._topline_host.addWidget(host)
        _retheme_subtree(host)

    def _render_banner(self, state: str, focus: object) -> None:
        _clear_layout(self._banner_host)
        outcome_label = "Latest Outcome"
        detail = ""
        if state == MIRL_STATE_ACTIVE:
            status_value = "Episode Active"
            outcome_value = "In Progress"
            detail = f"Open for {_mirl_elapsed(getattr(focus, 'started_at', None))}"
            ok = True
        elif state == MIRL_STATE_IDLE:
            status_value = "No Active Episode"
            outcome_value = _mirl_text(getattr(focus, "final_outcome", None))
            ok = False
        elif state == MIRL_STATE_EMPTY:
            status_value = "No Episode Evidence"
            outcome_value = _mirl_text(
                getattr(self._projection, "empty_state_reason", None)
            )
            outcome_label = ""
            ok = False
        else:  # entry -- nothing has been projected yet
            status_value = "Not Loaded"
            outcome_value = "\u2014"
            ok = False
        banner = showcase_episode_banner(
            "Episode Status",
            status_value,
            outcome_label,
            outcome_value,
            ok=ok,
            outcome_muted=state == MIRL_STATE_EMPTY,
            detail=detail,
        )
        self._banner = banner
        self._banner_host.addWidget(banner)
        _retheme_subtree(banner)

    def _render_stats(self, focus: object) -> None:
        _clear_layout(self._stats_host)
        values = (
            (self._trigger_text(focus), "Trigger", 32.0),
            (self._sine_stage_text(), "SINE Stage", 24.0),
            (self._session_text(focus), "Session No.", 32.0),
        )
        for column, (number, caption, size) in enumerate(values):
            # A word-shaped value ("Not Recorded") cannot ride the 32px mono
            # figure size the mockup uses for a numeral.
            shown_size = size if number.isdigit() or number.startswith("SINE-") else 15.0
            cell = showcase_metric_stat(number, caption, "", "cyan", size=shown_size)
            self._stats_host.addWidget(cell, 0, column)
            self._stats_host.setColumnStretch(column, 1)
            _retheme_subtree(cell)

    def _render_journey(self, state: str, focus: object) -> None:
        if focus is None:
            self._journey_title.setText("Event Journey")
            self._journey_hint.setText(
                "No episode recorded"
                if state == MIRL_STATE_EMPTY
                else "Awaiting projection"
            )
        else:
            self._journey_title.setText(
                f"Event Journey \u2014 {_mirl_text(getattr(focus, 'short_display_id', None))}"
            )
            count = len(tuple(getattr(focus, "timeline", ()) or ()))
            self._journey_hint.setText(f"{count} recorded events")
        _mirl_fill_journey_strip(self._strip_layout, focus)
        _retheme_subtree(self._strip_body)
        has_steps = focus is not None and bool(getattr(focus, "timeline", ()))
        self._journey_prev.setEnabled(has_steps)
        self._journey_next.setEnabled(has_steps)

    def _render_outcomes(self, focus: object) -> None:
        """The four-tile outcome row.

        "Candidate Return" was removed rather than left as a permanent em
        dash: LiveMirlEpisodeRow carries no such field, so the tile could
        never say anything.  The SINE timer took its slot -- it is the one
        live reading on this row, and the only one that answers "what is SINE
        doing right now" while a distraction sits in the foreground.
        """

        _clear_layout(self._outcome_host)
        values = (
            ("Return Latency", _mirl_return_latency_text(focus)),
            ("SINE Timer", self._sine_timer_text()),
            ("Verified Returns", _mirl_verified_return_count_text(self._projection)),
            ("Worst Drift", _mirl_worst_drift_text(self._projection)),
        )
        self._sine_timer_label = None
        for column, (caption, value) in enumerate(values):
            measured = value != "\u2014"
            cell = showcase_metric_stat(
                value,
                caption,
                "",
                "cyan" if measured else None,
                # "NOT RETURNED" and "03:47 / 10:00" cannot ride the 22px mono
                # figure size a bare latency uses.
                size=22.0 if len(value) <= 8 else 15.0,
                number_role=None if measured else "muted",
            )
            if caption == "SINE Timer":
                self._sine_timer_label = getattr(cell, "figure_label", None)
                self._sine_timer_measured = measured
            self._outcome_host.addWidget(cell, 0, column)
            self._outcome_host.setColumnStretch(column, 1)
            _retheme_subtree(cell)

    def _tick_elapsed(self) -> None:
        """Retitle the per-second readouts in place.

        Two share this tick: the open-episode "Open for ..." line and the SINE
        timer.  The ONE case that rebuilds is the SINE timer crossing between a
        real value and unavailable -- that changes the tile's colour and figure
        size, which ``setText`` alone cannot carry.
        """

        if not self.isVisible():
            return

        active = self._effective_state()[0] == MIRL_STATE_ACTIVE

        timer_text = self._sine_timer_text()
        timer_measured = timer_text != "\u2014"
        if timer_measured != self._sine_timer_measured:
            # SINE just started, ended, or its signal went stale.
            self._render_outcomes(self._effective_focus())
        elif self._sine_timer_label is not None:
            try:
                self._sine_timer_label.setText(timer_text)
            except RuntimeError:
                # The tile was rebuilt underneath us; the next render re-binds.
                self._sine_timer_label = None

        if active:
            banner = self._banner
            detail = getattr(banner, "detail_label", None) if banner is not None else None
            if detail is not None:
                focus = self._effective_focus()
                detail.setText(
                    f"Open for {_mirl_elapsed(getattr(focus, 'started_at', None))}"
                )

        if not active and not timer_measured:
            self._elapsed_timer.stop()

    def hideEvent(self, event) -> None:  # noqa: N802
        # Nothing off-screen needs a per-second readout.
        self._elapsed_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._effective_state()[0] == MIRL_STATE_ACTIVE or self._sine_timer_measured:
            self._elapsed_timer.start()

    # -- journey card ---------------------------------------------------------

    def _build_journey_card(self) -> QFrame:
        card, body = make_card()

        head = QHBoxLayout()
        head.setSpacing(10)
        self._journey_title = label("Event Journey", 12.5, 700, "cyan", spacing=1.2)
        head.addWidget(self._journey_title)
        head.addStretch(1)
        self._journey_hint = label("", 11.5, 400, "muted")
        head.addWidget(self._journey_hint)
        # ``.journey-nav`` -- the mockup draws two chevrons here and binds no
        # handler to them.  With a real timeline the strip can overflow, so
        # they scroll it; that is the only job for them that invents no data.
        self._journey_prev = _showcase_chevron_button(False)
        self._journey_next = _showcase_chevron_button(True)
        self._journey_prev.clicked.connect(lambda: self._scroll_strip(-1))
        self._journey_next.clicked.connect(lambda: self._scroll_strip(1))
        head.addWidget(self._journey_prev)
        head.addWidget(self._journey_next)
        body.addLayout(head)
        body.addSpacing(16)

        self._strip_host = QScrollArea()
        self._strip_host.setObjectName("showcaseScroll")
        self._strip_host.setWidgetResizable(True)
        self._strip_host.setFrameShape(QFrame.Shape.NoFrame)
        self._strip_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._strip_host.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._strip_host.setMinimumHeight(150)

        self._strip_body = QWidget()
        self._strip_body.setObjectName("plainBox")
        self._strip_layout = QHBoxLayout(self._strip_body)
        self._strip_layout.setContentsMargins(0, 0, 0, 6)
        self._strip_layout.setSpacing(6)
        self._strip_host.setWidget(self._strip_body)
        body.addWidget(self._strip_host)
        return card

    def _scroll_strip(self, direction: int) -> None:
        bar = self._strip_host.horizontalScrollBar()
        bar.setValue(bar.value() + direction * self._STRIP_STEP_PX)

    # -- full dashboard -------------------------------------------------------

    def _open_full_dashboard(self) -> None:
        """Open the Live MIRL Dashboard over the whole Control Station window.

        Lazily created once and reused on every later click, matching how
        ``AnalyticsController.open_composer`` keeps ``AnalyticsSheetDialog``
        alive across opens instead of rebuilding it.  It opens as a glass
        overlay above the whole window, not a separate top-level window, so
        it is parented to ``self.window()`` rather than to this page.
        """

        host = self.window()
        if self._dashboard_dialog is None:
            self._dashboard_dialog = LiveMirlDashboardDialog(host)
            self._dashboard_dialog.apply_live_view(
                self._live_view, self._live_view_last_seen, self._constructed_at
            )
            self._dashboard_dialog.apply_sine_view(
                self._sine_view, self._sine_view_last_seen, self._constructed_at
            )
        self._dashboard_dialog.render_projection(self._projection)
        self._dashboard_dialog.open_over(host)


class LiveMirlDashboardDialog(QWidget):
    """Live MIRL Dashboard, reproduced from the mockup's glass overlay.

    Opened from ``LiveMirlShowcasePage``'s "Open Full Dashboard" button and
    fed the SAME ``LiveMirlProjection`` that page already holds -- it never
    reads persistence itself, never starts a refresh, and never recomputes an
    episode.  It is a second view of one projection, not a second source.

    The mockup's ``.glass-overlay`` is a ``position:fixed; inset:0`` layer
    inside the SAME page, not a second browser window -- so this is a plain
    ``QWidget`` raised above the rest of the Control Station window, never a
    top-level ``QDialog``.  It has no OS titlebar and no taskbar/alt-tab
    entry, matching that.  The panel itself paints the mockup's own
    ``backdrop-filter``-unsupported fallback (see ``_GlassPanel``) rather
    than attempting to fake a live blur, which Qt has no reliable way to do.
    """

    TAB_TITLES: Final = (
        "Current Episode",
        "Episode History",
        "Event Timeline",
        "History Evidence",
        "Data Quality",
    )

    PANEL_MARGIN: Final = 16
    # DEFAULT_WINDOW_SIZE is 1460x960 and MINIMUM_WINDOW_SIZE is 1024x700
    # (see module top) -- this cap only binds once the host grows past
    # those, e.g. maximized on a large monitor, so it's set generously
    # above the default rather than pinned to it. It still stops well short
    # of covering a huge/ultrawide/4K display edge-to-edge, since
    # ``_layout_panel`` clamps to whichever is smaller: this cap, or the
    # host's own size minus margin.
    PANEL_MAX_SIZE: Final = QSize(1800, 1100)

    #: Journey strips drawn as soon as Episode History opens.  Every episode
    #: still gets a card and every card can draw its strip on request; only
    #: the up-front drawing is budgeted.  On real evidence 52 episodes carry
    #: ~560 journey nodes, and building all of them for rows nobody has
    #: scrolled to yet costs ~3 seconds.  The mockup pre-drew all 13 of its
    #: fixtures, which does not survive contact with a real, growing history.
    HISTORY_STRIPS_EXPANDED: Final = 3

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("liveMirlDashboardOverlay")
        self.hide()
        self._host: QWidget | None = None
        self._projection: object | None = None
        # Tabs render on first view, not all five up front: the history strip
        # alone is ~550 journey nodes on real evidence, and paying for four
        # hidden tabs would stall the open.
        self._dirty_tabs: set = set()
        # Event Timeline is no longer locked to the newest episode.  Empty means
        # "follow the focus episode"; otherwise it holds the chosen episode_id.
        # ``_timeline_rebuilding`` suppresses the combo's own change signal while
        # the list is being repopulated, which would otherwise re-enter render.
        self._timeline_selection: str = ""
        self._timeline_rebuilding = False

        # Mirrors LiveMirlShowcasePage's live engine snapshot -- forwarded by
        # the page on every update via apply_live_view(), not read directly
        # from the engine (see ruling 3.1/4.2).
        self._live_view: object | None = None
        self._live_view_last_seen: float | None = None
        self._page_constructed_at: float = time.monotonic()
        self._live_degraded = False
        self._sine_view: object | None = None
        self._sine_view_last_seen: float | None = None

        # The panel is positioned by hand in ``_layout_panel`` rather than
        # through a layout with an alignment flag: an aligned QBoxLayout item
        # is only ever given its children's sizeHint (here, whatever height
        # the header/subline/tabbar/footer naturally add up to) and centred
        # at THAT size, ignoring its Expanding size policy and maximumSize --
        # so it never actually grows to fill a larger window.
        self._panel = _GlassPanel(self)
        self._panel.setMaximumSize(self.PANEL_MAX_SIZE)

        panel_root = QVBoxLayout(self._panel)
        panel_root.setContentsMargins(0, 0, 0, 0)
        panel_root.setSpacing(0)

        panel_root.addWidget(self._build_header())
        panel_root.addWidget(self._build_subline())

        body = QWidget(self._panel)
        body.setObjectName("plainBox")
        body_row = QHBoxLayout(body)
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)
        body_row.addWidget(self._build_tabbar())
        self._stack = QStackedWidget(body)
        self._stack.setStyleSheet("QStackedWidget { background: transparent; }")
        for page in (
            self._build_current_tab(),
            self._build_history_tab(),
            self._build_timeline_tab(),
            self._build_evidence_tab(),
            self._build_quality_tab(),
        ):
            self._stack.addWidget(self._wrap_scroll(page))
        body_row.addWidget(self._stack, 1)
        panel_root.addWidget(body, 1)

        self._footer_time = label("Not loaded", 11, 400, "muted", mono=True)
        panel_root.addWidget(self._build_footer())

        def _retheme(tokens) -> None:
            self._panel.apply_tint(tokens)

        _retheme(DEFAULT_THEME)
        _remember_retheme(self, _retheme)

        # One timer, and it no longer invents a "refreshed" time: the footer
        # now shows the projection's own generated_at.  All this tick does is
        # recover the overlay's geometry if the host resized in a way that
        # produced no plain resize event (a maximize/restore transition).
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._resync_if_stale)
        self._clock.start()

    # -- open/close -----------------------------------------------------------

    def open_over(self, host: QWidget) -> None:
        """Raise this overlay above ``host``'s full client area.

        ``host`` is normally the top-level Control Station window.
        """

        if self.parent() is not host:
            self.setParent(host)
            self._host = None
        if self._host is not host:
            if self._host is not None:
                self._host.removeEventFilter(self)
            host.installEventFilter(self)
            self._host = host
        self.setGeometry(host.rect())
        self._layout_panel()
        self.show()
        self.raise_()

    def _layout_panel(self) -> None:
        """Centre ``self._panel``, filling up to ``PANEL_MAX_SIZE``.

        Positioned by hand rather than through a layout -- see the
        ``__init__`` note on why an aligned layout item won't do this.
        """

        margin = self.PANEL_MARGIN
        width = min(max(0, self.width() - 2 * margin), self.PANEL_MAX_SIZE.width())
        height = min(max(0, self.height() - 2 * margin), self.PANEL_MAX_SIZE.height())
        x = (self.width() - width) // 2
        y = (self.height() - height) // 2
        self._panel.setGeometry(x, y, width, height)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_panel()

    def eventFilter(self, watched, event):  # noqa: N802
        if (
            watched is self._host
            and event.type() == QEvent.Type.Resize
            and self.isVisible()
        ):
            self.setGeometry(self._host.rect())
        return super().eventFilter(watched, event)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(4, 8, 16, round(0.55 * 255)))
        painter.end()

    # -- chrome -----------------------------------------------------------

    def _resync_if_stale(self) -> None:
        """Recover if this overlay's geometry ever drifts from the host's.

        The ``eventFilter`` below re-syncs on a plain resize, but some host
        size changes (a maximize/restore window-state transition) are not
        guaranteed to arrive as a plain ``QEvent.Resize``. One timer already
        ticks every second while the overlay is open, so this piggybacks on
        it rather than adding a second timer.
        """

        if not self.isVisible() or self._host is None:
            return
        if self.size() == self._host.size():
            return
        self.setGeometry(self._host.rect())
        self._layout_panel()

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("mirlDashboardHeader")
        header.setFrameShape(QFrame.Shape.NoFrame)
        row = QHBoxLayout(header)
        row.setContentsMargins(26, 18, 26, 18)
        row.setSpacing(16)

        left = QHBoxLayout()
        left.setSpacing(10)
        left.addWidget(BrandMark(20))
        left.addWidget(label("MYELIN", 13, 700, "text", mono=True, spacing=2.0))
        row.addLayout(left)

        title = label("Live MIRL Dashboard", 15, 800, "text", spacing=3.0, upper=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(title, 1)

        # The three chips are rebuilt from the projection on every render,
        # so they live in their own layout rather than being added once.
        self._chip_host = QHBoxLayout()
        self._chip_host.setContentsMargins(0, 0, 0, 0)
        self._chip_host.setSpacing(10)
        right = QHBoxLayout()
        right.setSpacing(10)
        right.addLayout(self._chip_host)
        right.addWidget(self._build_close_button())
        row.addLayout(right)

        header.setStyleSheet(
            f"QFrame#mirlDashboardHeader {{ background: {_white_alpha(0.02)};"
            f" border-bottom: 1px solid {_white_alpha(0.1)}; }}"
        )
        return header

    def _build_close_button(self) -> QPushButton:
        button = QPushButton("✕")
        button.setObjectName("mirlDashboardClose")
        button.setFixedSize(32, 32)
        button.setFont(make_font(12, 700))
        button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        button.clicked.connect(self.hide)

        def _retheme(tokens) -> None:
            hover_border = qalpha(QColor(tokens.red), 0.5).name(QColor.NameFormat.HexArgb)
            button.setStyleSheet(
                f"QPushButton#mirlDashboardClose {{ background: transparent;"
                f" color: {tokens.muted}; border: 1px solid {tokens.border};"
                f" border-radius: 16px; }}"
                f"QPushButton#mirlDashboardClose:hover {{ color: {tokens.red};"
                f" border-color: {hover_border}; }}"
            )

        _retheme(DEFAULT_THEME)
        _remember_retheme(button, _retheme)
        return button

    def _build_subline(self) -> QWidget:
        sub = QFrame()
        sub.setObjectName("mirlDashboardSubline")
        sub.setFrameShape(QFrame.Shape.NoFrame)
        row = QHBoxLayout(sub)
        row.setContentsMargins(26, 10, 26, 10)
        row.setSpacing(14)
        row.addWidget(label("Authoritative Native MIRL Episode Evidence", 11, 400, "muted"))
        self._subline_exclusions = label("Exclusions: \u2014", 11, 400, "muted")
        row.addWidget(self._subline_exclusions)
        row.addStretch(1)
        self._export_button = showcase_outline_button("Export MIRL Report", small=True)
        self._export_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._export_button.clicked.connect(self._export_report)
        row.addWidget(self._export_button)

        sub.setStyleSheet(
            f"QFrame#mirlDashboardSubline {{ background: transparent;"
            f" border-bottom: 1px solid {_white_alpha(0.07)}; }}"
        )
        return sub

    #: How long the export button reports its outcome before returning to its
    #: normal label.
    _EXPORT_FEEDBACK_MS: Final = 4000

    def _export_report(self) -> None:
        """Offer the two formats and write only the one chosen.

        A menu rather than two buttons: the formats answer different questions
        (a report to read, an archive to query) and are never both wanted at
        once, so the subline keeps one control instead of growing a second.
        """

        tokens = live_tokens()
        menu = QMenu(self._export_button)
        menu.setObjectName("mirlExportMenu")
        menu.setFont(make_font(11.5, 600))
        # Styled from the live tokens at popup time rather than through
        # ``_remember_retheme``: the menu exists only while it is open, so it
        # would never be reached by the shell's theme sweep anyway.
        menu.setStyleSheet(
            f"QMenu#mirlExportMenu {{ background: {tokens.surface};"
            f" color: {tokens.text_primary}; border: 1px solid {tokens.border};"
            f" border-radius: {RADIUS_SM}px; padding: 6px; }}"
            f"QMenu#mirlExportMenu::item {{ padding: 8px 18px;"
            f" border-radius: {RADIUS_SM}px; }}"
            f"QMenu#mirlExportMenu::item:selected {{"
            f" background: {qalpha(_showcase_colour('cyan', tokens), 0.16).name(QColor.NameFormat.HexArgb)};"
            f" color: {tokens.cyan}; }}"
        )
        pdf_action = menu.addAction("PDF report  \u00b7  2 pages")
        json_action = menu.addAction("JSON data  \u00b7  all five tabs")
        button = self._export_button
        chosen = menu.exec(button.mapToGlobal(QPoint(0, button.height() + 4)))
        if chosen is pdf_action:
            self._write_export("pdf")
        elif chosen is json_action:
            self._write_export("json")

    def _write_export(self, output_format: str) -> None:
        """Write one export and report the outcome on the button itself.

        Run on the GUI thread deliberately: the whole export measures ~130ms on
        real evidence (read and project 81ms, PDF 28ms, JSON 22ms), so a worker
        thread would add failure modes to hide a delay nobody can perceive.

        Failure is reported rather than swallowed -- an export that silently
        does nothing is worse than one that says it failed.
        """

        from PERSISTENCE.storage import export_mirl_report

        button = self._export_button
        button.setEnabled(False)
        button.setText("EXPORTING\u2026")
        try:
            written = export_mirl_report(output_format)
        except Exception as error:  # export must never take the dashboard down
            print(f"[MYELIN][EXPORT] MIRL {output_format} failed: {error!r}", flush=True)
            button.setText("EXPORT FAILED")
        else:
            print(f"[MYELIN][EXPORT] MIRL {output_format} written: {written}", flush=True)
            button.setText(f"{output_format.upper()} SAVED TO DOWNLOADS")
        QTimer.singleShot(self._EXPORT_FEEDBACK_MS, self._restore_export_button)

    def _restore_export_button(self) -> None:
        try:
            self._export_button.setText("EXPORT MIRL REPORT")
            self._export_button.setEnabled(True)
        except RuntimeError:
            # The dashboard was torn down while the label was still reverting.
            return

    def _build_tabbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("mirlDashboardTabbar")
        bar.setFrameShape(QFrame.Shape.NoFrame)
        bar.setFixedWidth(190)
        lay = QVBoxLayout(bar)
        lay.setContentsMargins(10, 14, 10, 14)
        lay.setSpacing(2)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)
        # The mockup's ``.glass-tabbar`` is a plain top-flowing flex column
        # (``flex-direction: column; gap: 2px; overflow-y: auto``) with no
        # centring, so the buttons start at the top and the leftover height
        # falls below them.
        for index, title in enumerate(self.TAB_TITLES):
            button = self._build_tab_button(title)
            self._tab_group.addButton(button, index)
            lay.addWidget(button)
        lay.addStretch(1)
        self._tab_group.idClicked.connect(self._set_current_tab)
        self._tab_group.buttons()[0].setChecked(True)

        bar.setStyleSheet(
            f"QFrame#mirlDashboardTabbar {{ background: transparent;"
            f" border-right: 1px solid {_white_alpha(0.08)}; }}"
        )
        return bar

    def _build_tab_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("mirlDashboardTab")
        button.setCheckable(True)
        button.setFont(make_font(12.5, 400))
        button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        button.setMinimumHeight(40)

        def _retheme(tokens) -> None:
            # ``.glass-tab`` carries no border in any state; the active tab is
            # a 14% cyan wash alone.
            active_bg = qalpha(QColor(tokens.cyan), 0.14).name(QColor.NameFormat.HexArgb)
            hover_bg = _white_alpha(0.05)
            button.setStyleSheet(
                f"QPushButton#mirlDashboardTab {{ text-align: left; background: transparent;"
                f" color: {tokens.muted}; border: none;"
                f" border-radius: {RADIUS_SM}px; padding: 10px 12px; }}"
                f"QPushButton#mirlDashboardTab:hover {{ background: {hover_bg};"
                f" color: {tokens.text_primary}; }}"
                f"QPushButton#mirlDashboardTab:checked {{ background: {active_bg};"
                f" color: {tokens.cyan}; font-weight: 700; }}"
            )

        _retheme(DEFAULT_THEME)
        _remember_retheme(button, _retheme)
        return button

    def _set_current_tab(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self._render_visible_tab()

    @staticmethod
    def _wrap_scroll(page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("showcaseScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        # QAbstractScrollArea always paints its viewport with an opaque
        # QPalette.Base fill; toggling autoFillBackground off does not stop
        # it, only an explicit stylesheet on the viewport itself does -- see
        # https://doc.qt.io/qt-6/qabstractscrollarea.html#autoFillBackground
        # behaviour of the viewport widget.  Without this the viewport paints
        # solid over the glass panel's translucent backdrop instead of
        # letting it show through.
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setWidget(page)
        return scroll

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setObjectName("mirlDashboardFooter")
        footer.setFrameShape(QFrame.Shape.NoFrame)
        row = QHBoxLayout(footer)
        row.setContentsMargins(26, 12, 26, 12)
        row.addWidget(label("MYELIN v2.0 · Corrected Design Preview", 11, 400, "muted"))
        row.addStretch(1)
        row.addWidget(self._footer_time)

        footer.setStyleSheet(
            f"QFrame#mirlDashboardFooter {{ background: transparent;"
            f" border-top: 1px solid {_white_alpha(0.08)}; }}"
        )
        return footer

    # -- tab content ----------------------------------------------------------

    def _tab_page(self, spacing: int = 0) -> tuple:
        """One ``.glass-tabpage`` shell plus the layout its content lives in."""

        page = QWidget()
        page.setObjectName("plainBox")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(26, 22, 26, 22)
        lay.setSpacing(spacing)
        return page, lay

    def _build_current_tab(self) -> QWidget:
        page, lay = self._tab_page()
        self._current_host = lay
        return page

    def _build_history_tab(self) -> QWidget:
        page, lay = self._tab_page()
        self._history_host = lay
        return page

    def _build_timeline_tab(self) -> QWidget:
        page, lay = self._tab_page()

        chooser = QHBoxLayout()
        chooser.setSpacing(10)
        chooser.addWidget(label("Episode", 11, 700, "muted", spacing=1.4, upper=True))
        self._timeline_picker = _glass_episode_picker()
        self._timeline_picker.currentIndexChanged.connect(self._timeline_episode_chosen)
        chooser.addWidget(self._timeline_picker, 1)
        lay.addLayout(chooser)
        lay.addSpacing(16)

        # The body is its own nested layout so clearing it on every render
        # cannot take the chooser down with it.
        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        lay.addLayout(body)
        self._timeline_host = body
        return page

    def _build_evidence_tab(self) -> QWidget:
        page, lay = self._tab_page()
        headers = (
            "#",
            "Episode ID",
            "Time Distracted",
            "Time Recovered",
            "Highest SINE",
            "Trigger Time",
            "Application",
            "Return Latency",
        )
        table = QTableWidget(0, len(headers))
        table.setObjectName("mirlDashboardEvidenceTable")
        table.setHorizontalHeaderLabels(list(headers))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setMinimumHeight(320)

        def _retheme(tokens) -> None:
            table.setStyleSheet(
                f"QTableWidget#mirlDashboardEvidenceTable {{ background: transparent;"
                f" color: {tokens.text_primary}; border: 1px solid {_white_alpha(0.08)};"
                f" border-radius: {RADIUS_SM}px; gridline-color: {_white_alpha(0.06)}; }}"
                f"QTableWidget#mirlDashboardEvidenceTable QHeaderView::section {{"
                f" background: transparent; color: {tokens.muted};"
                f" border: none; border-bottom: 1px solid {_white_alpha(0.1)};"
                f" padding: 8px 10px; font-weight: 700; }}"
            )

        _retheme(DEFAULT_THEME)
        _remember_retheme(table, _retheme)

        self._evidence_caption = label("", 12, 400, "muted")
        lay.addWidget(self._evidence_caption)
        lay.addSpacing(14)
        self._evidence_table = table
        lay.addWidget(table)
        lay.addStretch(1)
        return page

    def _build_quality_tab(self) -> QWidget:
        page, lay = self._tab_page(spacing=18)
        self._quality_host = lay
        return page

    # -- projection -> the five tabs ------------------------------------------

    def render_projection(self, projection: object) -> None:
        """Take one projection.  Chrome and the visible tab render now; the
        other four are marked dirty and render when they are first shown."""

        self._projection = projection
        self._dirty_tabs = set(range(len(self.TAB_TITLES)))
        self._render_chrome()
        self._render_visible_tab()

    def _render_visible_tab(self) -> None:
        index = self._stack.currentIndex()
        if index not in self._dirty_tabs:
            return
        self._dirty_tabs.discard(index)
        renderer = (
            self._render_current,
            self._render_history,
            self._render_timeline,
            self._render_evidence,
            self._render_quality,
        )[index]
        renderer()

    def apply_live_view(
        self,
        live_view: object | None,
        live_view_last_seen: float | None,
        constructed_at: float,
    ) -> None:
        """Receive the page's forwarded live engine snapshot (ruling 3.1/4.2)."""

        self._live_view = live_view
        self._live_view_last_seen = live_view_last_seen
        self._page_constructed_at = constructed_at
        self._render_chrome()
        if self._stack.currentIndex() == 0:
            self._render_current()
        else:
            self._dirty_tabs.add(0)

    def apply_sine_view(
        self,
        sine_view: object | None,
        sine_view_last_seen: float | None,
        constructed_at: float,
    ) -> None:
        """Receive the page's forwarded live SINE snapshot."""

        self._sine_view = sine_view
        self._sine_view_last_seen = sine_view_last_seen
        self._page_constructed_at = constructed_at
        if self._stack.currentIndex() == 0:
            self._render_current()
        else:
            self._dirty_tabs.add(0)

    def _sine_stage_text(self) -> str:
        return _sine_stage_display(
            self._sine_view, self._sine_view_last_seen, self._page_constructed_at
        )

    def _trigger_text(self, focus: object) -> str:
        return _mirl_trigger_text(
            self._live_view,
            self._live_view_last_seen,
            self._page_constructed_at,
            fallback=getattr(focus, "source_event_id", None),
        )

    def _state(self) -> str:
        state, self._live_degraded = _mirl_effective_state(
            self._projection,
            self._live_view,
            self._live_view_last_seen,
            self._page_constructed_at,
        )
        return state

    def _focus(self):
        return _mirl_effective_focus(
            self._projection,
            self._live_view,
            self._live_view_last_seen,
            self._page_constructed_at,
        )

    def _episodes(self) -> tuple:
        projection = self._projection
        active = tuple(getattr(projection, "active_episodes", ()) or ())
        closed = tuple(getattr(projection, "recently_closed_episodes", ()) or ())
        return active, closed

    def _empty_text(self, fallback: str) -> str:
        return _mirl_text(getattr(self._projection, "empty_state_reason", None), fallback)

    def _render_chrome(self) -> None:
        projection = self._projection
        state = self._state()
        _clear_layout(self._chip_host)
        if state == MIRL_STATE_ACTIVE:
            episode_chip = ("MIRL: Episode Open", "green")
        elif state == MIRL_STATE_IDLE:
            episode_chip = ("MIRL: No Open Episode", "red")
        elif state == MIRL_STATE_EMPTY:
            episode_chip = ("MIRL: No Evidence", None)
        else:
            episode_chip = ("MIRL: Not Loaded", None)
        # Integrity rides a NEUTRAL chip.  Degraded evidence is the ordinary
        # condition of this surface, so it is stated plainly rather than
        # coloured like a fault.
        integrity = getattr(projection, "integrity_status", None)
        integrity_text = _mirl_text(getattr(integrity, "value", integrity), "UNKNOWN")
        chips = (
            episode_chip,
            (f"Integrity: {integrity_text}", "green" if integrity_text == "CONFIRMED" else None),
            ("Source: Read Model", "cyan"),
        )
        if self._live_degraded:
            chips = chips + (("Live Signal: Unavailable", None),)
        for text, role in chips:
            chip = showcase_chip_pill(text, role)
            self._chip_host.addWidget(chip)
            _retheme_subtree(chip)

        metadata = getattr(projection, "metadata", None)
        exclusions = getattr(metadata, "exclusion_count", None)
        self._subline_exclusions.setText(
            f"Exclusions: {exclusions}" if isinstance(exclusions, int) else "Exclusions: \u2014"
        )
        generated = getattr(metadata, "generated_at", None)
        self._footer_time.setText(
            f"Projected {_mirl_stamp(generated)}" if generated else "Not loaded"
        )

    def _render_current(self) -> None:
        _clear_layout(self._current_host)
        lay = self._current_host
        focus = self._focus()
        if focus is None:
            lay.addWidget(
                label(self._empty_text("No projection loaded yet."), 12, 400, "muted", wrap=True)
            )
            lay.addStretch(1)
            return

        active = self._state() == MIRL_STATE_ACTIVE
        outcome = getattr(focus, "final_outcome", None)
        banner = showcase_episode_banner(
            "Episode Status",
            "Episode Active" if active else "No Active Episode \u2014 Inspecting Closed Episode",
            "Latest Outcome",
            "In Progress" if active else _mirl_text(outcome),
            ok=active,
            status_size=16.0,
        )
        lay.addWidget(banner)
        lay.addSpacing(18)

        stats = QGridLayout()
        stats.setHorizontalSpacing(14)
        cells = (
            ("Trigger", self._trigger_text(focus), 22.0),
            ("SINE Stage", self._sine_stage_text(), 16.0),
            (
                "Elapsed Time",
                _mirl_elapsed(getattr(focus, "started_at", None))
                if active
                else _mirl_duration(getattr(focus, "stable_recovery_latency_seconds", None)),
                16.0,
            ),
        )
        for column, (caption, value, size) in enumerate(cells):
            stats.addWidget(_glass_gstat(caption, value, size), 0, column)
            stats.setColumnStretch(column, 1)
        lay.addLayout(stats)
        lay.addSpacing(18)

        lay.addWidget(showcase_episode_story(focus))
        lay.addStretch(1)
        _retheme_subtree(self._current_host.parentWidget())

    def _render_history(self) -> None:
        _clear_layout(self._history_host)
        lay = self._history_host
        active, closed = self._episodes()
        episodes = (*active, *closed)
        if not episodes:
            lay.addWidget(
                label(self._empty_text("No episode has been recorded."), 12, 400, "muted", wrap=True)
            )
            lay.addStretch(1)
            return

        drawn = min(self.HISTORY_STRIPS_EXPANDED, len(episodes))
        caption = (
            f"{len(active)} open \u00b7 {len(closed)} closed episode(s), newest first."
        )
        if len(episodes) > drawn:
            caption += (
                f"  Journeys for the newest {drawn} are drawn; open any other "
                "episode's journey with its own button."
            )
        lay.addWidget(label(caption, 12, 400, "muted", wrap=True))
        lay.addSpacing(14)

        # Open episodes are listed first under their own heading rather than
        # folded into their calendar day.  An episode can stay open past
        # midnight -- the open one here opened a day before the newest closed
        # one -- so grouping it by date would push a day heading out of order
        # and print that day twice.
        per_day: dict[str, int] = {}
        for row in closed:
            day = _mirl_day_label(row)
            per_day[day] = per_day.get(day, 0) + 1

        index = 0
        if active:
            lay.addWidget(_mirl_day_heading("Open now", len(active)))
            lay.addSpacing(10)
            for row in active:
                lay.addWidget(self._history_card(row, expanded=index < drawn))
                lay.addSpacing(12)
                index += 1

        current_day = None
        for row in closed:
            day = _mirl_day_label(row)
            if day != current_day:
                if current_day is not None or active:
                    lay.addSpacing(10)
                current_day = day
                lay.addWidget(_mirl_day_heading(day, per_day[day]))
                lay.addSpacing(10)
            lay.addWidget(self._history_card(row, expanded=index < drawn))
            lay.addSpacing(12)
            index += 1
        lay.addStretch(1)

    def _history_card(self, row: object, *, expanded: bool) -> QFrame:
        """One episode: header always, journey strip on request.

        Collapsing a strip hides nothing that is not stated on the card -- the
        episode, its outcome, its opening stamp and its recorded event count
        are all on the header, and History Evidence lists every episode in
        full regardless.
        """

        card, body = _glass_gcard(padding=16)
        timeline = tuple(getattr(row, "timeline", ()) or ())
        outcome = getattr(row, "final_outcome", None)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(
            label(_mirl_text(getattr(row, "short_display_id", None)), 12.5, 700, "cyan", spacing=1.2)
        )
        head.addStretch(1)
        head.addWidget(label(f"{len(timeline)} recorded events", 11, 400, "muted"))
        head.addWidget(
            showcase_chip_pill(
                _mirl_text(outcome, "In Progress"),
                "green" if _mirl_recovered(outcome) else ("red" if outcome else "cyan"),
            )
        )
        head.addWidget(label(_mirl_stamp(getattr(row, "started_at", None)), 11, 400, "muted"))
        toggle = showcase_outline_button("Hide Journey" if expanded else "Show Journey", small=True)
        toggle.setEnabled(bool(timeline))
        toggle.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        head.addWidget(toggle)
        body.addLayout(head)

        strip_host = QScrollArea()
        strip_host.setObjectName("showcaseScroll")
        strip_host.setWidgetResizable(True)
        strip_host.setFrameShape(QFrame.Shape.NoFrame)
        strip_host.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        strip_host.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        strip_host.setMinimumHeight(150)
        strip_host.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        strip_host.viewport().setStyleSheet("background: transparent;")
        strip_body = QWidget()
        strip_body.setObjectName("plainBox")
        strip_layout = QHBoxLayout(strip_body)
        strip_layout.setContentsMargins(0, 0, 0, 6)
        strip_layout.setSpacing(6)
        strip_host.setWidget(strip_body)
        body.addSpacing(12)
        body.addWidget(strip_host)

        # ``shown`` is tracked explicitly rather than read back from
        # ``strip_host.isVisible()``: a widget reports itself invisible
        # whenever ANY ancestor is hidden, so querying it would make the
        # toggle stick open while the overlay itself is closed.
        state = {"built": False, "shown": bool(expanded)}

        def build() -> None:
            if state["built"]:
                return
            state["built"] = True
            _mirl_fill_journey_strip(strip_layout, row)
            _retheme_subtree(strip_body)

        def toggled() -> None:
            state["shown"] = not state["shown"]
            if state["shown"]:
                build()
            strip_host.setVisible(state["shown"])
            toggle.setText("Hide Journey" if state["shown"] else "Show Journey")

        toggle.clicked.connect(toggled)
        if expanded:
            build()
        else:
            strip_host.setVisible(False)
        _retheme_subtree(card)
        return card

    def _timeline_episode_chosen(self, index: int) -> None:
        if self._timeline_rebuilding:
            return
        self._timeline_selection = str(self._timeline_picker.itemData(index) or "")
        self._render_timeline_body()

    def _timeline_episode(self):
        """The episode the timeline is showing: the chosen one, else the focus."""

        if self._timeline_selection:
            for row in self._episodes_flat():
                if str(getattr(row, "episode_id", "")) == self._timeline_selection:
                    return row
        return self._focus()

    def _episodes_flat(self) -> tuple:
        active, closed = self._episodes()
        return (*active, *closed)

    def _render_timeline(self) -> None:
        self._rebuild_timeline_picker()
        self._render_timeline_body()

    def _rebuild_timeline_picker(self) -> None:
        """Refill the chooser, keeping the user's pick if that episode survives."""

        picker = self._timeline_picker
        episodes = self._episodes_flat()
        self._timeline_rebuilding = True
        try:
            picker.clear()
            for row in episodes:
                outcome = _mirl_text(getattr(row, "final_outcome", None), "In Progress")
                events = len(tuple(getattr(row, "timeline", ()) or ()))
                picker.addItem(
                    f"{_mirl_day_label(row)}  \u00b7  "
                    f"{_mirl_text(getattr(row, 'short_display_id', None))}  \u00b7  "
                    f"{outcome}  \u00b7  {events} event(s)",
                    str(getattr(row, "episode_id", "")),
                )
            picker.setEnabled(bool(episodes))
            wanted = self._timeline_selection or str(
                getattr(self._focus(), "episode_id", "") or ""
            )
            index = picker.findData(wanted)
            if index < 0:
                # The chosen episode fell out of the projection; fall back to
                # following the focus again rather than showing a stale pick.
                self._timeline_selection = ""
                index = 0 if episodes else -1
            if index >= 0:
                picker.setCurrentIndex(index)
        finally:
            self._timeline_rebuilding = False

    def _render_timeline_body(self) -> None:
        _clear_layout(self._timeline_host)
        lay = self._timeline_host
        focus = self._timeline_episode()
        timeline = tuple(getattr(focus, "timeline", ()) or ()) if focus is not None else ()
        if not timeline:
            lay.addWidget(label("No authoritative event to show.", 12, 400, "muted"))
            lay.addStretch(1)
            return
        lay.addWidget(
            label(
                f"{_mirl_text(getattr(focus, 'short_display_id', None))} \u00b7 "
                f"{len(timeline)} authoritative event(s) \u2014 episode_seq order",
                12,
                400,
                "muted",
            )
        )
        lay.addSpacing(14)
        for event in timeline:
            lay.addWidget(self._timeline_row(event))
            lay.addSpacing(10)
        lay.addStretch(1)

    def _timeline_row(self, event: object) -> QFrame:
        card, body = _glass_gcard(padding=14)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(
            label(f"#{_mirl_text(getattr(event, 'episode_seq', None))}", 11, 400, "muted", mono=True)
        )
        row.addWidget(label(_mirl_event_title(getattr(event, "event_name", None)), 12.5, 700, "text"))
        row.addStretch(1)
        pill_role, pill_text = _mirl_event_pill(getattr(event, "event_name", None))
        row.addWidget(showcase_journey_pill(pill_role, pill_text))
        row.addWidget(
            showcase_chip_pill(
                f"{str(getattr(event, 'observed_or_derived', '') or '').title()} "
                f"{_mirl_clock(getattr(event, 'occurred_at', None))}",
                "cyan",
            )
        )
        code = getattr(event, "reason_or_outcome_code", None)
        if code:
            row.addWidget(showcase_chip_pill(_mirl_text(code), None))
        if getattr(event, "reference", None):
            row.addWidget(showcase_chip_pill("Has Evidence", None))
        body.addLayout(row)
        _retheme_subtree(card)
        return card

    def _render_evidence(self) -> None:
        active, closed = self._episodes()
        episodes = (*active, *closed)
        self._evidence_caption.setText(
            f"{len(episodes)} episode(s) in this projection \u2014 every column is a "
            "recorded or projected value; nothing is estimated."
            if episodes
            else self._empty_text("No episode has been recorded.")
        )
        table = self._evidence_table
        table.setRowCount(len(episodes))
        for index, row in enumerate(episodes):
            timeline = tuple(getattr(row, "timeline", ()) or ())
            outcome = getattr(row, "final_outcome", None)
            recovered = _mirl_recovered(outcome)
            cells = (
                str(index + 1),
                _mirl_text(getattr(row, "short_display_id", None)),
                # Time Distracted is the moment SINE-1 displayed, i.e. when
                # MYELIN first told you that you had drifted.  Clock only: the
                # date already rides the Episode ID (EPI-DDMMYYYY-NN).
                _mirl_clock_utc(getattr(row, "started_at", None)),
                # Time Recovered is when the return was VERIFIED, so that this
                # column minus the one before it IS the Return Latency column.
                _mirl_clock_utc(_mirl_recovered_at(row))
                if recovered
                else _MIRL_UNAVAILABLE,
                _mirl_highest_sine(row),
                # The trigger's OWN fire time, not the episode's start: SINE-1
                # follows about three seconds later, and this column used to
                # show that later instant under the trigger's name.
                _mirl_clock_utc_seconds(getattr(row, "trigger_fired_at", None)),
                _mirl_application_text(row),
                _mirl_evidence_return_latency(row, recovered),
            )
            for column, value in enumerate(cells):
                table.setItem(index, column, QTableWidgetItem(value))

    def _render_quality(self) -> None:
        _clear_layout(self._quality_host)
        lay = self._quality_host
        projection = self._projection
        integrity = getattr(projection, "integrity_status", None)
        integrity_text = _mirl_text(getattr(integrity, "value", integrity), "UNKNOWN")
        metadata = getattr(projection, "metadata", None)
        issues = tuple(getattr(projection, "integrity_issues", ()) or ())
        exclusions = tuple(getattr(metadata, "exclusions", ()) or ())

        first, first_body = _glass_gcard(padding=20)
        first_body.addWidget(label("Authoritative Evidence Boundary", 14, 700, "text"))
        first_body.addSpacing(6)
        # CONFIRMED reads green; every other status reads muted, NOT red.
        # Degraded evidence is still authoritative evidence -- it is reported,
        # not alarmed about.
        first_body.addWidget(
            label(
                _mirl_text(getattr(projection, "status_message", None), "No projection loaded"),
                12,
                600,
                "green" if integrity_text == "CONFIRMED" else "muted",
                wrap=True,
            )
        )
        first_body.addSpacing(8)
        first_body.addWidget(
            showcase_kv_block(
                f"Integrity status: {integrity_text}\n"
                f"Integrity issues: {len(issues)}\n"
                f"Metric exclusions: {_mirl_text(getattr(metadata, 'exclusion_count', None))}\n"
                f"Evidence population: {_mirl_text(getattr(metadata, 'evidence_population', None))}\n"
                f"Population scope: {_mirl_text(getattr(metadata, 'population_scope', None))}\n"
                f"Range: {_mirl_text(getattr(metadata, 'selected_range_label', None))}\n"
                f"Projected at: {_mirl_text(getattr(metadata, 'generated_at', None))}\n"
                f"Projector: {_mirl_text(getattr(metadata, 'projector_version', None))}\n"
                "Episode ordering: episode_seq\n"
                "Missing evidence: Display as unavailable; never paint as completed\n"
                "Scientific boundary: Behavioral and software evidence only"
            )
        )
        lay.addWidget(first)

        counts = dict(getattr(projection, "native_outcome_counts", {}) or {})
        availability = dict(getattr(projection, "evidence_availability", {}) or {})
        second, second_body = _glass_gcard(padding=20)
        second_body.addWidget(label("Recorded Outcome Population", 14, 700, "text"))
        second_body.addSpacing(6)
        second_body.addWidget(
            label(
                "Counts below come from the read model unchanged. An episode with "
                "no closing event stays PENDING here even where Live MIRL shows it "
                "as NOT_RETURNED, because no recorded event ever ended it.",
                12,
                400,
                "muted",
                wrap=True,
            )
        )
        second_body.addSpacing(8)
        second_body.addWidget(
            showcase_kv_block(
                "\n".join(f"{key}: {value}" for key, value in counts.items())
                + ("\n" if counts and availability else "")
                + "\n".join(f"{key}: {value}" for key, value in availability.items())
                or "No counts published."
            )
        )
        lay.addWidget(second)

        third, third_body = _glass_gcard(padding=20)
        third_body.addWidget(label("Integrity Issues and Exclusions", 14, 700, "text"))
        third_body.addSpacing(6)
        if not issues and not exclusions:
            third_body.addWidget(
                label("No integrity issue or metric exclusion was recorded.", 12, 400, "muted")
            )
        else:
            third_body.addWidget(
                showcase_kv_block(_mirl_issue_digest(issues, exclusions))
            )
        lay.addWidget(third)

        lay.addStretch(1)
        _retheme_subtree(self._quality_host.parentWidget())


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

    def _retheme(tokens) -> None:
        box.setStyleSheet(
            f"QFrame#showcaseJourneyStep {{ background: {tokens.surface_soft};"
            f" border: 1px solid {tokens.border}; border-radius: {RADIUS_MD}px; }}"
        )

    _retheme(DEFAULT_THEME)
    _remember_retheme(box, _retheme)
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
        self._latest_blacklist_live_view = None
        self._latest_sine_live_view = None
        self._active_normal_break_fact = None
        self._normal_break_stop_in_flight = False
        self._engine_paused = False
        self._session_elapsed = QElapsedTimer()
        self._session_tick = QTimer(self)
        self._session_tick.setInterval(1000)
        self._session_tick.timeout.connect(self._advance_session_clock)
        self._sine_projection_timer = QTimer(self)
        self._sine_projection_timer.setInterval(200)
        self._sine_projection_timer.timeout.connect(self._project_sine_countdown)
        self._sine_projection_timer.start()

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
        self._buttons["pause"].clicked.connect(self._pause_resume_clicked)
        self._buttons["stop"].clicked.connect(lifecycle.request_stop)
        self._emergency.clicked.connect(lifecycle.request_emergency)
        left.addWidget(self.hero)

        # -------------------------------------------- Today's Session Health
        health, health_body = make_card()
        head, self._health_hint = card_head("Today's Session Health", "Loading")
        health_body.addWidget(head)
        health_body.addSpacing(16)
        health_row = QHBoxLayout()
        health_row.setSpacing(14)
        sessions, self._stat_sessions = stat_box("Sessions", "\u2014", "cyan")
        returns, self._stat_returns = stat_box("Returns", "\u2014", "green")
        triggers, self._stat_triggers = stat_box("Triggers", "\u2014", "amber")
        for widget in (sessions, returns, triggers):
            health_row.addWidget(widget, 1)
        health_body.addLayout(health_row)
        left.addWidget(health)

        # ------------------------------------------------- Current Resource
        current, current_body = make_card()
        head, self._current_hint = card_head("Current Resource", "Idle")
        current_body.addWidget(head)
        current_body.addSpacing(16)
        self._resource_label = label("\u2014", 13.5, 600, "text", mono=True)
        self._resource_label.setMinimumWidth(0)
        self._resource_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        current_body.addWidget(self._resource_label)
        self._resource_title = label("", 11.5, 400, "muted", mono=True)
        self._resource_title.setMinimumWidth(0)
        self._resource_title.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        current_body.addWidget(self._resource_title)
        current_body.addSpacing(10)
        dwell_row, self._dwell_track, self._dwell_value = bar_row("Dwell / target")
        self._dwell_value.setFixedWidth(118)
        current_body.addWidget(dwell_row)
        current_body.addSpacing(10)
        self._resource_reason = label(
            "No managed resource is in the foreground.", 11.5, 400, "muted", wrap=True
        )
        current_body.addWidget(self._resource_reason)
        left.addWidget(current)

        # --------------------------------------- Normal Break Continuity
        normal_break, normal_break_body = make_card()
        self._normal_break_card = normal_break
        head, self._normal_break_hint = card_head(
            "Normal Break Continuity", "Inactive"
        )
        normal_break_body.addWidget(head)
        normal_break_body.addSpacing(16)
        break_row = QHBoxLayout()
        break_row.setSpacing(14)
        remaining, self._normal_break_remaining_value = stat_box(
            "Remaining", "\u2014", "text", 16.0
        )
        elapsed, self._normal_break_elapsed = stat_box(
            "Elapsed / Duration", "\u2014 / \u2014", "text", 16.0
        )
        state, self._normal_break_state = stat_box(
            "State", "Inactive", "text", 16.0
        )
        for widget in (remaining, elapsed, state):
            break_row.addWidget(widget, 1)
        normal_break_body.addLayout(break_row)
        normal_break_body.addSpacing(12)
        progress_row, self._normal_break_track, self._normal_break_progress = bar_row(
            "Break progress", "cyan", 118
        )
        normal_break_body.addWidget(progress_row)
        normal_break_body.addSpacing(12)
        self._normal_break_stop = QPushButton("STOP BREAK", normal_break)
        self._normal_break_stop.setObjectName("btnStop")
        self._normal_break_stop.setFont(make_font(12, 700, spacing=0.8))
        self._normal_break_stop.setCursor(
            QCursor(Qt.CursorShape.PointingHandCursor)
        )
        self._normal_break_stop.setMinimumHeight(44)
        self._normal_break_stop.setAccessibleName("Stop the active Normal Break")
        self._normal_break_stop.clicked.connect(self._request_normal_break_stop)
        normal_break_body.addWidget(
            self._normal_break_stop, 0, Qt.AlignmentFlag.AlignHCenter
        )
        self._normal_break_stop.hide()
        left.addWidget(normal_break)

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

        for card in (health, current, normal_break, sine, mine, research):
            card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # --------------------------------------------------- Live Telemetry
        feed_card, feed_body = make_card()
        self._feed_card = feed_card
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

    def _pause_resume_clicked(self) -> None:
        """Route the single Pause/Resume button to the correct engine call."""

        if self._engine_paused:
            self._engine.resume()
        else:
            self._engine.pause()

    def _profile_changed(self, index: int) -> None:
        key = str(self._profile.itemData(index) or "general")
        if self._profiles.set_active(key):
            self._engine.set_profile_type(key)

    def _engine_status_changed(self, status) -> None:
        """Reflect engine status in the pill, the buttons and the ring clock."""

        text = str(getattr(status, "name", status)).replace("_", " ").upper()
        if text in {"IDLE", "STOPPING", "STOPPED", "EMERGENCY", "ERROR"}:
            self._clear_normal_break_presentation()
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

        self._engine_paused = paused
        self._buttons["start"].setEnabled(not running)
        self._buttons["pause"].setEnabled(running)
        self._buttons["pause"].setText("RESUME" if paused else "PAUSE")
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

    def render_normal_break_fact(self, fact: object) -> None:
        """Project immutable Normal Break facts without owning their lifecycle."""

        if fact is None:
            self._clear_normal_break_presentation()
            return
        kind_value = self._value(fact, "kind")
        kind = str(getattr(kind_value, "value", kind_value) or "").replace(
            "_", " "
        ).upper()
        if kind == "NORMAL BREAK STARTED":
            self._active_normal_break_fact = fact
            self._normal_break_stop_in_flight = False
            self.refresh_normal_break()
            return
        if kind == "NORMAL BREAK STOP REQUESTED":
            if self._normal_break_matches(fact):
                self._normal_break_stop_in_flight = True
                self.refresh_normal_break()
            return
        if kind in {
            "NORMAL BREAK STOPPED",
            "NORMAL BREAK COMPLETED",
            "NORMAL BREAK TERMINATED",
            "NORMAL BREAK START ROLLED BACK",
        } and self._normal_break_matches(fact):
            self._clear_normal_break_presentation()

    def refresh_normal_break(self, _elapsed_seconds: object = None) -> None:
        """Redraw elapsed/progress from the factual STARTED timestamps."""

        del _elapsed_seconds
        fact = self._active_normal_break_fact
        if fact is None:
            self._render_normal_break_inactive()
            return
        started_ns = self._value(fact, "started_monotonic_ns")
        deadline_ns = self._value(fact, "deadline_monotonic_ns")
        if type(started_ns) is not int or type(deadline_ns) is not int:
            self._clear_normal_break_presentation()
            return
        duration_ns = max(0, deadline_ns - started_ns)
        elapsed_ns = min(duration_ns, max(0, time.monotonic_ns() - started_ns))
        remaining_ns = max(0, deadline_ns - time.monotonic_ns())
        duration_seconds = duration_ns // 1_000_000_000
        elapsed_seconds = elapsed_ns // 1_000_000_000
        remaining_seconds = math.ceil(remaining_ns / 1_000_000_000)
        ratio = 0.0 if duration_ns <= 0 else elapsed_ns / duration_ns

        self._normal_break_hint.setText(
            "Stopping\u2026" if self._normal_break_stop_in_flight else "Active"
        )
        self._normal_break_remaining_value.setText(
            self._format_seconds(remaining_seconds)
        )
        self._normal_break_elapsed.setText(
            f"{self._format_seconds(elapsed_seconds)} / "
            f"{self._format_seconds(duration_seconds)}"
        )
        self._normal_break_state.setText("Active")
        self._normal_break_track.set_progress(ratio)
        self._normal_break_progress.setText(f"{int(round(ratio * 100))}%")
        self._normal_break_stop.show()
        self._normal_break_stop.setEnabled(
            not self._normal_break_stop_in_flight
        )

    def _request_normal_break_stop(self) -> None:
        fact = self._active_normal_break_fact
        if fact is None or self._normal_break_stop_in_flight:
            return
        payload = {
            "break_id": self._value(fact, "break_id"),
            "generation": self._value(fact, "generation"),
            "episode_uid": self._value(fact, "episode_uid"),
            "candidate_uid": self._value(fact, "candidate_uid"),
        }
        self._normal_break_stop_in_flight = True
        self._normal_break_stop.setEnabled(False)
        if not self._engine.request_normal_break_stop(payload):
            if self._active_normal_break_fact is fact:
                self._normal_break_stop_in_flight = False
                self._normal_break_stop.setEnabled(True)

    def _normal_break_matches(self, fact: object) -> bool:
        current = self._active_normal_break_fact
        if current is None:
            return False
        fields = ("break_id", "generation", "episode_uid", "candidate_uid")
        return all(
            self._value(current, field) == self._value(fact, field)
            for field in fields
        )

    def _clear_normal_break_presentation(self) -> None:
        self._active_normal_break_fact = None
        self._normal_break_stop_in_flight = False
        self._render_normal_break_inactive()

    def _render_normal_break_inactive(self) -> None:
        self._normal_break_hint.setText("Inactive")
        self._normal_break_remaining_value.setText("\u2014")
        self._normal_break_elapsed.setText("\u2014 / \u2014")
        self._normal_break_state.setText("Inactive")
        self._normal_break_track.set_progress(0.0)
        self._normal_break_progress.setText("\u2014")
        self._normal_break_stop.hide()
        self._normal_break_stop.setEnabled(False)

    # -------------------------------------------------------------- render
    def render(self, payload: object) -> None:
        """Format the prepared control view; no value here is recalculated."""

        if payload is None:
            return
        session_id = self._value(payload, "session_id")
        if session_id is not None:
            self._status.setToolTip(f"Session {session_id}")

        blacklist = self._value(payload, "blacklist")
        self._latest_blacklist_live_view = blacklist
        if blacklist is not None:
            name = str(self._value(blacklist, "resource_label", "") or "").strip()
            title = str(self._value(blacklist, "resource_title", "") or "").strip()
            self._resource_label.setText(name or "\u2014")
            self._resource_title.setText(title)
            self._resource_label.setToolTip(name)
            self._resource_title.setToolTip(title)

            disposition = self._enum_text(self._value(blacklist, "disposition"), "")
            state = self._enum_text(self._value(blacklist, "state"), "INACTIVE")
            confidence = self._enum_text(self._value(blacklist, "confidence"), "")
            parts = [p for p in (state, disposition, confidence) if p and p.upper() != "NONE"]
            self._current_hint.setText(" \u00b7 ".join(p.upper() for p in parts) or "Idle")

            reason = str(self._value(blacklist, "reason", "") or "").strip()
            self._resource_reason.setText(
                reason or "No managed resource is in the foreground."
            )

            self._render_current_authority_interval()

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

    def render_today_session_health(self, snapshot: object) -> None:
        """Place three already-calculated Today Health integers into labels.

        Presentation only: no ratio, SQL, event counting, date arithmetic or
        MIRL interpretation happens here. The snapshot is trusted exactly as
        the read model prepared it.
        """

        self._stat_sessions.setText(
            self._display_count(self._value(snapshot, "session_count"))
        )
        self._stat_returns.setText(
            self._display_count(self._value(snapshot, "returned_episode_count"))
        )
        self._stat_triggers.setText(
            self._display_count(self._value(snapshot, "trigger_count"))
        )
        self._health_hint.setText("Resets 00:00 local")

    def show_today_session_health_unavailable(self) -> None:
        """A failed or not-yet-proven read must never be shown as zero."""

        self._stat_sessions.setText("—")
        self._stat_returns.setText("—")
        self._stat_triggers.setText("—")
        self._health_hint.setText("Unavailable")

    @staticmethod
    def _display_count(value: object) -> str:
        """Only an exact, already-validated non-negative int is a count.

        No coercion: ``True``, ``3.8`` and ``"3"`` must never be displayed
        as a believable number on a research metric card.
        """

        if type(value) is int and value >= 0:
            return str(value)
        return "—"

    def render_sine(self, payload: object) -> None:
        """Render exactly the latest SINE live-view facts."""

        if payload is None:
            self._latest_sine_live_view = None
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
            self._render_current_authority_interval()
            return

        self._latest_sine_live_view = payload

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
        self._render_current_authority_interval()

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

    def _sine_actively_counting_deadline(self) -> int | None:
        """Return the authoritative deadline to project, or None while frozen.

        Presentation-only: every guard here mirrors a SINE fact that already
        holds the countdown still. Never decrements locally under a hold.
        """

        sine = self._latest_sine_live_view
        if sine is None:
            return None
        if bool(self._value(sine, "protected_red_active", False)):
            return None
        for flag in (
            "presentation_withheld_for_recovery",
            "activity_clock_paused",
            "normal_break_held",
            "post_normal_break_return_pending",
        ):
            if bool(self._value(sine, flag, False)):
                return None
        stage = self._value(sine, "stage")
        try:
            stage_number = int(getattr(stage, "value", stage))
        except (TypeError, ValueError):
            return None
        if stage_number == 1:
            return self._value(sine, "stage_2_deadline_monotonic_ns")
        if stage_number == 2:
            return self._value(sine, "stage_3_deadline_monotonic_ns")
        return None

    def _project_sine_countdown(self) -> None:
        """Smooth the SINE timer label between backend snapshots.

        Reads only the already-published monotonic deadline; never advances
        SINE, never invents a stage, never writes back to the engine.
        """

        deadline_ns = self._sine_actively_counting_deadline()
        if deadline_ns is None:
            return
        remaining = max(0.0, (deadline_ns - time.monotonic_ns()) / 1_000_000_000)
        self._sine_timer.setText(self._format_seconds(remaining))

    def _render_current_authority_interval(self) -> None:
        """Project the current owner without inventing any timing value."""

        sine = self._latest_sine_live_view
        if sine is not None:
            stage = self._value(sine, "stage")
            try:
                stage_number = int(getattr(stage, "value", stage))
            except (TypeError, ValueError):
                stage_number = 0
            phase = self._enum_text(self._value(sine, "phase"), "IDLE")
            protected = bool(self._value(sine, "protected_red_active", False))
            if protected or phase == "PROTECTED RED":
                self._dwell_track.set_progress(1.0, "red")
                self._dwell_value.setText("RETURN REQUIRED")
                self._ring.set_progress(1.0)
                return

            target_field = {
                1: "stage_2_delay_seconds_applied",
                2: "stage_3_delay_seconds_applied",
            }.get(stage_number)
            remaining_raw = self._value(sine, "next_deadline_seconds")
            target_raw = self._value(sine, target_field) if target_field else None
            try:
                target = float(target_raw)
                remaining = max(0.0, float(remaining_raw))
            except (TypeError, ValueError, OverflowError):
                target = 0.0
                remaining = 0.0
            if target > 0.0 and remaining_raw is not None:
                elapsed = min(target, max(0.0, target - remaining))
                fraction = min(1.0, max(0.0, elapsed / target))
                self._dwell_track.set_progress(
                    fraction,
                    "red"
                    if fraction >= 0.85
                    else "rose"
                    if fraction >= 0.5
                    else "cyan",
                )
                self._dwell_value.setText(
                    f"{self._format_seconds(elapsed)} / "
                    f"{self._format_seconds(target)}"
                )
                self._ring.set_progress(fraction)
                return

        blacklist = self._latest_blacklist_live_view
        elapsed = self._value(blacklist, "dwell_elapsed_seconds", 0.0)
        target = self._value(blacklist, "dwell_target_seconds", 0.0)
        fraction = 0.0
        try:
            target_value = float(target or 0.0)
            if target_value > 0.0:
                fraction = min(
                    1.0,
                    max(0.0, float(elapsed or 0.0) / target_value),
                )
        except (TypeError, ValueError, OverflowError):
            target_value = 0.0
            fraction = 0.0
        self._dwell_track.set_progress(
            fraction,
            "red" if fraction >= 0.85 else "rose" if fraction >= 0.5 else "cyan",
        )
        self._dwell_value.setText(
            f"{self._format_seconds(elapsed)} / {self._format_seconds(target_value)}"
            if target_value > 0.0
            else self._format_seconds(elapsed)
        )
        self._ring.set_progress(fraction)

    def _highlight_sine_stage(self, stage: object) -> None:
        """Mark the chip SINE reports as current; never infer one locally."""

        try:
            active = int(getattr(stage, "value", stage))
        except (TypeError, ValueError):
            active = 0
        for number, chip in self._sine_chips.items():
            chip.setProperty("current", "true" if number == active else "false")
            restyle(chip)


def _sine_owner_claim_id(fact: object) -> str | None:
    """Build the opaque claim id from the frozen SINE<->MIRL shared owner.

    ``(session_id, candidate_uid, operational_event_id)`` is the identity
    MIRL's own final-closure fact will also expose once Phase 2E exists.
    SINE's own ``episode_uid`` is NOT the same as MIRL's episode id -- see
    the Phase 1.1 source-audit finding -- so ``episode_uid`` must never be
    the cross-organ key ``ThemeController`` is handed.  All three fields are
    required; a fact missing any of them cannot be safely owned.
    """

    session_id = getattr(fact, "session_id", None)
    candidate_uid = str(getattr(fact, "candidate_uid", "") or "")
    operational_event_id = getattr(fact, "operational_event_id", None)
    if session_id is None or not candidate_uid or operational_event_id is None:
        return None
    return f"sine:{session_id}:{candidate_uid}:{operational_event_id}"


# COSECANT states for which the continuity popup's own ``popup_required`` is
# True -- BREAK_ACTIVE is deliberately excluded, matching the doc's Green
# start law.  Kept in sync with ``CosecantSnapshot`` construction, not
# re-derived from it, since a presentation coordinator must not guess.
_COSECANT_GREEN_STATES: Final = frozenset(
    {
        CosecantState.BREAK_COMPLETE,
        CosecantState.BREAK_ALREADY_OVER,
        CosecantState.FINAL_LOCK,
        CosecantState.RETURN_CONFIRMING,
    }
)


def _cosecant_owner_claim_id(payload: object) -> str | None:
    """Build the opaque Green claim id from the COSECANT break identity.

    ``(study_block_id, break_id)`` together uniquely identify one approved
    break: a fresh ``break_id`` is minted for every accepted break, and both
    fields are present on both the ``CosecantSnapshot`` that presents Green
    and the ``CosecantFact`` that releases it -- unlike COSECANT's own
    generation counter, which a release fact does not carry.
    """

    study_block_id = str(getattr(payload, "study_block_id", "") or "")
    break_id = str(getattr(payload, "break_id", "") or "")
    if not study_block_id or not break_id:
        return None
    return f"cosecant:{study_block_id}:{break_id}"


@dataclass
class _PendingSineAtmosphere:
    """One tracked Normal-SINE presentation window for one owner.

    ``claim_id`` is the shared cross-organ owner identity handed to
    ``ThemeController``.  ``episode_uid``/``popup_request_id`` are SINE's own
    local identity, retained only so this coordinator can recognise a
    duplicate ``SINE_DISPLAYED`` fact for the exact occurrence it is already
    tracking -- they never reach ``theme.py``.

    ``active_atmosphere`` and ``pending_atmosphere`` are deliberately
    separate: SINE advancing an episode from stage 2 to stage 3 must replace
    the pending target (Amber -> Red) on this same record without losing
    track of the atmosphere that is already claimed, or a cancellation
    arriving during that one-second handoff would have no address left to
    release.
    """

    claim_id: str
    episode_uid: str
    popup_request_id: str
    active_atmosphere: "Atmosphere | None" = None
    pending_atmosphere: "Atmosphere | None" = None


class _NormalSinePresentationCoordinator:
    """Translates raw SINE and MIRL facts into common-theme atmosphere claims.

    Phase 2B+2C+2D+2E scope: a factual ``SINE_DISPLAYED`` stage-2 fact,
    anchored to its own ``occurred_monotonic_ns``, becomes an
    ``AMBER_ALERT`` claim exactly one second later; stage 3 becomes
    ``RED_ALERT`` the same way, replacing Amber on the very same owner claim
    so there is no base/Neon flash between them.  A factual
    ``SINE_POST_BREAK_RETURN_GATE_DISPLAYED`` (Welcome Back actually shown
    -- not a stage, SINE says so explicitly) claims ``GREEN_RETURN``
    immediately, no delay; the matching
    ``SINE_POST_BREAK_RETURN_ACKNOWLEDGED`` (I'M BACK accepted) releases it
    immediately, and only it -- never an active Amber/Red.  A factual
    ``MIRL_EPISODE_CLOSED`` with reason ``RETURNED``, anchored to its own
    ``occurred_monotonic_ns`` (never SINE's resolution timestamp -- that can
    be tens of seconds stale by the time final closure happens), releases a
    still-active matching Amber/Red exactly two seconds later -- never
    Green, which only the Break acknowledgement releases.  All of this is
    cancelled/resolved/reset exactly as Amber alone was in Phase 2B.

    Phase 3A+3B: stage 2 and stage 3 both activate for a STUDY episode (a
    non-empty ``study_context_token``) through the exact same path as a
    Normal one -- Study SINE is still SINE, still the same organ, still the
    same common body, with no separate Study identity in the claim.  Phase
    3C/3D certified (with zero code required) that the same generic
    MIRL-release and terminal-cancellation handling below already covers a
    Study-owned Amber/Red claim, because neither ever inspects
    ``study_context_token``.

    Phase 3E: a factual "this exact COSECANT continuity-popup snapshot was
    visibly presented" receipt for a popup-required state (BREAK_COMPLETE,
    BREAK_ALREADY_OVER, FINAL_LOCK, RETURN_CONFIRMING -- never BREAK_ACTIVE)
    claims ``GREEN_RETURN`` immediately, keyed by the COSECANT break's own
    ``(study_block_id, break_id)`` identity -- a second, independent owner
    namespace from the SINE/MIRL one above, tracked in two plain attributes
    rather than a second dictionary.  A factual ``RETURN_INTENT_RECORDED``
    (RETURN TO STUDY accepted) or ``RETURN_CONFIRMED`` (the FINAL_LOCK
    fallback) releases that exact Green claim immediately and permanently
    suppresses it, so a later queued popup projection for the same
    already-released break cannot re-claim Green.

    This coordinator owns no SINE timing, no MIRL truth, no COSECANT timing
    and no stage/break state of its own: it only reacts to facts SINE, MIRL
    and COSECANT already publish and to the engine's existing lifecycle
    signal, and it tracks only what it needs to keep a delayed
    activation/release from firing -- or a suppressed claim from
    re-activating -- after its owner is no longer current.
    """

    _ONE_SECOND_NS = 1_000_000_000
    _TWO_SECOND_NS = 2_000_000_000

    def __init__(self, theme: ThemeController) -> None:
        self._theme = theme
        # COSECANT Green ownership: a second, independent claim namespace
        # from the SINE/MIRL ``_pending`` dict above.  Exactly two pointers,
        # not a second dictionary -- one active break can hold Green.
        self._cosecant_green_claim_id: str | None = None
        self._cosecant_green_suppressed_claim_id: str | None = None
        self._pending: dict[str, _PendingSineAtmosphere] = {}

    def handle_sine_fact(self, fact: object) -> None:
        kind = str(getattr(fact, "kind", ""))
        if kind == "SINE_DISPLAYED":
            self._handle_displayed(fact)
        elif kind == "SINE_POST_BREAK_RETURN_GATE_DISPLAYED":
            self._handle_return_gate_displayed(fact)
        elif kind == "SINE_POST_BREAK_RETURN_ACKNOWLEDGED":
            self._handle_return_acknowledged(fact)
        elif kind == "SINE_EPISODE_CANCELLED":
            self._invalidate_matching(fact, release_if_active=True)
        elif kind == "SINE_EPISODE_RESOLVED":
            # Phase 2E owns the final MIRL +2s release for an already-active
            # claim; resolution only stops a still-pending one from firing.
            self._invalidate_matching(fact, release_if_active=False)

    def handle_mirl_fact(self, event: object) -> None:
        """Factual MIRL recovery closure: release a matching warning at +2s.

        Only ``MIRL_EPISODE_CLOSED`` with ``reason == "RETURNED"`` matters
        here; every other MIRL event (return verification, closure
        confirmation, a non-RETURNED closure) is ignored.  The owner is the
        same shared ``(session_id, candidate_uid, operational_event_id)``
        identity SINE facts use -- MIRL's own ``episode_id`` is never
        compared against SINE's ``episode_uid``; they are different
        namespaces and this coordinator does not bridge them.
        """

        if str(getattr(event, "kind", "")) != "MIRL_EPISODE_CLOSED":
            return
        if str(getattr(event, "reason", "")) != "RETURNED":
            return

        claim_id = _sine_owner_claim_id(event)
        if claim_id is None:
            return
        record = self._pending.get(claim_id)
        if record is None or record.active_atmosphere not in (
            Atmosphere.AMBER_ALERT,
            Atmosphere.RED_ALERT,
        ):
            return  # nothing to release, or the active claim is Green -- never touch that

        anchor_ns = int(getattr(event, "occurred_monotonic_ns", 0) or 0)
        if anchor_ns <= 0:
            return  # no safe factual timestamp to anchor a release to

        remaining_ns = (anchor_ns + self._TWO_SECOND_NS) - time.monotonic_ns()
        remaining_ms = (remaining_ns + 999_999) // 1_000_000 if remaining_ns > 0 else 0

        QTimer.singleShot(
            remaining_ms,
            lambda record=record, claim_id=claim_id: self._release_after_mirl(record, claim_id),
        )

    def _release_after_mirl(self, record: _PendingSineAtmosphere, claim_id: str) -> None:
        if self._pending.get(claim_id) is not record:
            return  # invalidated (cancelled/resolved/session reset) before firing
        if record.active_atmosphere not in (Atmosphere.AMBER_ALERT, Atmosphere.RED_ALERT):
            return  # no longer a warning to release (e.g. became Green meanwhile)
        del self._pending[claim_id]
        self._theme.release_atmosphere(claim_id)

    def handle_engine_status(self, status: object) -> None:
        """Reset at a new-session/stop/emergency presentation boundary.

        ``STOPPING`` resets immediately rather than waiting for ``STOPPED``:
        the presentation is already invalid the moment a normal stop begins,
        and waiting for backend cleanup to finish would leave a window where
        an old +1s callback could still fire and show Amber for a session
        that is already on its way out.
        """

        if str(getattr(status, "value", status)) in (
            "STARTING",
            "STOPPING",
            "STOPPED",
            "EMERGENCY",
        ):
            self.reset()

    def reset(self) -> None:
        """Invalidate every pending callback and release only our claims.

        Never calls ``theme.clear_runtime_atmospheres()``: one common theme
        depends on all organs, and another organ may own a claim this SINE
        presentation layer has no business touching.
        """

        for record in self._pending.values():
            if record.active_atmosphere is not None:
                self._theme.release_atmosphere(record.claim_id)
        self._pending.clear()

        if self._cosecant_green_claim_id is not None:
            self._theme.release_atmosphere(self._cosecant_green_claim_id)
        self._cosecant_green_claim_id = None
        self._cosecant_green_suppressed_claim_id = None

    def handle_cosecant_popup_presented(self, snapshot: object) -> None:
        """A COSECANT continuity popup was factually shown: claim Green.

        The Green start law is the presentation receipt itself, not the
        break clock: this is called only when ``ContinuityPopup.present_
        snapshot`` actually returned True for this exact snapshot.
        """

        if not bool(getattr(snapshot, "popup_required", False)):
            return
        if getattr(snapshot, "state", None) not in _COSECANT_GREEN_STATES:
            return
        claim_id = _cosecant_owner_claim_id(snapshot)
        if claim_id is None:
            return
        if claim_id == self._cosecant_green_suppressed_claim_id:
            return  # this exact break's Green was already authoritatively released

        if (
            self._cosecant_green_claim_id is not None
            and self._cosecant_green_claim_id != claim_id
        ):
            # COSECANT owns only one approved break at a time.  Release the
            # old break's Green claim before claiming the new one; never
            # touch a SINE/MIRL claim from here.
            self._theme.release_atmosphere(self._cosecant_green_claim_id)

        self._cosecant_green_claim_id = claim_id
        self._theme.claim_atmosphere(claim_id, Atmosphere.GREEN_RETURN)

    def handle_cosecant_fact(self, fact: object) -> None:
        """Factual RETURN_INTENT_RECORDED/RETURN_CONFIRMED: release Green now.

        Both releases are immediate -- no timer, no MIRL-style delay.  The
        claim is also permanently suppressed here (even if Green was never
        actually claimed yet), so a delayed ``popup_presented`` receipt for
        this exact already-released break cannot re-claim Green later.
        """

        kind = getattr(fact, "kind", None)
        if kind not in (
            CosecantFactKind.RETURN_INTENT_RECORDED,
            CosecantFactKind.RETURN_CONFIRMED,
        ):
            return
        claim_id = _cosecant_owner_claim_id(fact)
        if claim_id is None:
            return

        self._cosecant_green_suppressed_claim_id = claim_id
        if self._cosecant_green_claim_id == claim_id:
            self._theme.release_atmosphere(claim_id)
            self._cosecant_green_claim_id = None

    def _handle_displayed(self, fact: object) -> None:
        stage = int(getattr(fact, "stage", 0) or 0)
        if stage == 2:
            target = Atmosphere.AMBER_ALERT
        elif stage == 3:
            target = Atmosphere.RED_ALERT
        else:
            return  # stage 2/3 claim Amber/Red for Normal AND Study; stage 1 claims nothing.

        claim_id = _sine_owner_claim_id(fact)
        episode_uid = str(getattr(fact, "episode_uid", "") or "")
        if claim_id is None or not episode_uid:
            return

        record = self._pending.get(claim_id)
        if record is not None and record.episode_uid == episode_uid:
            if record.pending_atmosphere is target or record.active_atmosphere is target:
                return  # duplicate DISPLAYED fact -- already scheduled or already this world
        else:
            record = _PendingSineAtmosphere(
                claim_id=claim_id,
                episode_uid=episode_uid,
                popup_request_id=str(getattr(fact, "popup_request_id", "") or ""),
            )
            self._pending[claim_id] = record

        record.popup_request_id = str(getattr(fact, "popup_request_id", "") or "")
        record.pending_atmosphere = target

        # Anchor to the fact's own display time, not to when it happened to
        # reach this GUI callback, so queue/transport delay cannot shorten or
        # lengthen the approved one-second delay.  Ceiling (never floor) the
        # remaining duration so presentation cannot land fractionally before
        # the +1s boundary.
        anchor_ns = int(getattr(fact, "occurred_monotonic_ns", 0) or 0)
        remaining_ns = (anchor_ns + self._ONE_SECOND_NS) - time.monotonic_ns()
        remaining_ms = (remaining_ns + 999_999) // 1_000_000 if remaining_ns > 0 else 0

        QTimer.singleShot(
            remaining_ms,
            lambda record=record, target=target: self._activate(record, target),
        )

    def _activate(self, record: _PendingSineAtmosphere, target: "Atmosphere") -> None:
        if self._pending.get(record.claim_id) is not record:
            return  # invalidated (cancelled/resolved/session reset) before firing
        if record.pending_atmosphere is not target:
            return  # superseded by a later stage's own scheduled activation
        record.pending_atmosphere = None
        record.active_atmosphere = target
        self._theme.claim_atmosphere(record.claim_id, target)

    def _handle_return_gate_displayed(self, fact: object) -> None:
        """Welcome Back is factually visible: claim Green -- no +1s delay.

        This is not a stage escalation (SINE says so explicitly: "SINE 2
        does not exist yet"), so it uses the same record but never goes
        through the pending/+1s machinery ``_handle_displayed`` uses.
        """

        if str(getattr(fact, "study_context_token", "") or "").strip():
            return  # Study Break Green is Phase 3, not Phase 2D.

        claim_id = _sine_owner_claim_id(fact)
        episode_uid = str(getattr(fact, "episode_uid", "") or "")
        if claim_id is None or not episode_uid:
            return

        record = self._pending.get(claim_id)
        if record is None or record.episode_uid != episode_uid:
            record = _PendingSineAtmosphere(
                claim_id=claim_id,
                episode_uid=episode_uid,
                popup_request_id=str(getattr(fact, "popup_request_id", "") or ""),
            )
            self._pending[claim_id] = record

        # A still-pending Amber/Red activation for this owner must not fire
        # after Green has been claimed; Green itself is immediate truth, not
        # a scheduled one.
        record.popup_request_id = str(getattr(fact, "popup_request_id", "") or "")
        record.pending_atmosphere = None
        record.active_atmosphere = Atmosphere.GREEN_RETURN
        self._theme.claim_atmosphere(claim_id, Atmosphere.GREEN_RETURN)

    def _handle_return_acknowledged(self, fact: object) -> None:
        """I'M BACK was accepted: release Green immediately, nothing else.

        Must never release Amber/Red -- only a matching, currently-active
        Green claim for the exact tracked owner and episode.
        """

        claim_id = _sine_owner_claim_id(fact)
        if claim_id is None:
            return
        episode_uid = str(getattr(fact, "episode_uid", "") or "")
        record = self._pending.get(claim_id)
        if record is None or record.episode_uid != episode_uid:
            return  # wrong owner or wrong episode -- an active Green stays untouched
        if record.active_atmosphere is not Atmosphere.GREEN_RETURN:
            return  # guard: never release Amber/Red from this acknowledgement
        del self._pending[claim_id]
        self._theme.release_atmosphere(claim_id)

    def _invalidate_matching(self, fact: object, *, release_if_active: bool) -> None:
        claim_id = _sine_owner_claim_id(fact)
        if claim_id is None:
            return
        episode_uid = str(getattr(fact, "episode_uid", "") or "")
        record = self._pending.get(claim_id)
        if record is None or record.episode_uid != episode_uid:
            return  # not a match for the exact occurrence this coordinator tracks

        if record.active_atmosphere is not None and not release_if_active:
            # Resolution: the active world (Amber or Red) stays claimed and
            # stays tracked, so a later STOPPING/EMERGENCY reset (or Phase
            # 2E's own release) still has this claim's address instead of
            # losing it the moment SINE resolves the episode.  A still-
            # pending (not yet fired) activation is cancelled either way --
            # nothing should activate for an episode that just resolved.
            record.pending_atmosphere = None
            return

        del self._pending[claim_id]
        if record.active_atmosphere is not None and release_if_active:
            self._theme.release_atmosphere(claim_id)


class ControlStationWindow(QMainWindow):
    """The main MYELIN window and composition root.

    This class creates each authority once and connects their public signals.
    It deliberately contains no engine rules.
    """

    def __init__(self) -> None:
        super().__init__()
        self._shutdown_is_authorized = False

        self.setObjectName("myelinControlStation")
        # The Control Station is an ordinary Windows application window.  The
        # loading screen and SINE surfaces are intentionally frameless, but
        # that presentation contract must never leak onto this host window.
        # Keep the native caption and its minimize/maximize/close controls
        # explicit so a stale Qt geometry/state cannot strand the user in a
        # borderless surface.
        native_flags = self.windowFlags()
        native_flags &= ~Qt.WindowType.FramelessWindowHint
        native_flags |= (
            Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.setWindowFlags(native_flags)
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(_canonical_application_icon())
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
        self.theme = ThemeController(parent=self)
        self._sine_presentation = _NormalSinePresentationCoordinator(self.theme)
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
        # ONE long-lived Notes session and workspace for the whole shell.
        # EngineStorage already satisfies the NoteStore protocol, so no
        # adapter or second repository exists.  Reopening STUDY NOTES reuses
        # this workspace rather than building another autosave worker.
        self.note_session = NoteSession(store=self.storage)
        self.notes_workspace = NotesWorkspace(session=self.note_session)

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
                notes_workspace=self.notes_workspace,
                note_store=self.storage,
            ),
            # Showcase visual body; Metric Hub and COSINE are still fixture
            # surfaces, reconnected in a later approved phase.  Live MIRL is
            # now wired to the real read model: it is registered on the SAME
            # shared refresh lane the analytics pages use, so navigating to
            # it triggers exactly one coalesced projection read and no second
            # reader is created.  analytics.py itself is untouched.
            metric_hub=MetricHubShowcasePage(),
            science_lab=self.analytics.create_science_lab_page(),
            live_mirl=self.analytics._create_page(  # noqa: SLF001 -- see above
                PAGE_LIVE_MIRL, LiveMirlShowcasePage
            ),
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
        self.sidebar.settings_requested.connect(self._open_settings)
        self.settings.changed.connect(self._settings_changed)

        self.navigation.page_opened.connect(self.analytics.page_opened)
        self.navigation.page_opened.connect(self.settings.set_last_page)
        self.lifecycle.navigation_enabled.connect(self.navigation.set_enabled)
        self.lifecycle.exit_authorized.connect(self._finish_shutdown)

        self.analytics.today_session_health_ready.connect(
            self.pages.control.render_today_session_health
        )
        self.analytics.today_session_health_failed.connect(
            lambda _message: self.pages.control.show_today_session_health_unavailable()
        )

        # The controller supplies prepared view data. The launcher does not
        # interpret or recalculate any telemetry value.
        self.engine.control_view_changed.connect(self.pages.control.render)
        self.engine.sine_watch_status_changed.connect(self.pages.control.render_sine)
        # Live MIRL's "Episode Active" badge must read the running engine,
        # not be inferred from the read model's history -- see ruling
        # 3.1/4.2 (myelin-mirl-live-signal-roadmap memory). The other four
        # Live MIRL Dashboard tabs stay on the projection refresh lane above.
        self.engine.mirl_health_status_changed.connect(self.pages.live_mirl.render_live_view)
        # Live "SINE Stage" readout on the same page: a second subscriber on
        # the SAME signal Control already uses (sine_watch_status_changed),
        # not a new source of truth. "SINE INACTIVE" with no trigger, the
        # real stage once one is in flight -- same build request as above.
        self.engine.sine_watch_status_changed.connect(self.pages.live_mirl.render_sine_view)
        # Event Journey must reflect the episode's real ending, not whatever
        # it looked like mid-flight: request one real projection refresh the
        # moment the engine reports STOPPED. engine_stopped only fires after
        # Core Engine cleanup is confirmed factual (see
        # EngineController._finish_worker_exit), so the terminal event
        # (episode_closed / emergency_stopped) is already persisted by the
        # time this fires -- no risk of reading ahead of the write. Reuses
        # the SAME refresh lane a manual refresh or page navigation already
        # uses (AnalyticsController._create_page wires refresh_requested to
        # the real refresh); this is not a second refresh mechanism.
        self.engine.engine_stopped.connect(self.pages.live_mirl.refresh_requested.emit)
        # Session No. (and, so the three live readouts never disagree, the
        # episode badge and SINE Stage too) must not sit on a frozen number
        # left over from before Stop was pressed. The 5s staleness timeout
        # in _mirl_effective_state / _sine_stage_display / _mirl_session_text
        # would get there on its own, but engine_stopped already tells us
        # definitively -- so clear both live snapshots immediately instead
        # of leaving the UI stale for up to 5 more seconds.
        self.engine.engine_stopped.connect(lambda: self.pages.live_mirl.render_live_view(None))
        self.engine.engine_stopped.connect(lambda: self.pages.live_mirl.render_sine_view(None))
        self.engine.normal_break_fact_changed.connect(
            self.pages.control.render_normal_break_fact
        )
        self.engine.session_time_changed.connect(
            self.pages.control.refresh_normal_break
        )
        self.engine.study_view_changed.connect(self.pages.study.render)
        self.engine.telemetry_received.connect(self._print_telemetry_event)
        self.engine.telemetry_received.connect(self.analytics.telemetry_received)
        self.engine.engine_status_changed.connect(self._engine_status_changed)
        self.engine.engine_status_changed.connect(self.analytics.engine_status_changed)
        self.engine.normal_stop_requested.connect(self.lifecycle.request_stop)
        self.pages.study.prepare_requested.connect(self.engine.prepare_study)
        self.pages.study.study_action_requested.connect(self.engine.request_study_action)
        self.pages.study.break_requested.connect(self.engine.request_study_break)
        self.pages.study.return_intent_requested.connect(self.engine.request_cosecant_return_intent)

        self.theme.theme_changed.connect(self._apply_theme)
        self.engine.sine_fact_received.connect(self._sine_presentation.handle_sine_fact)
        self.engine.mirl_fact_received.connect(self._sine_presentation.handle_mirl_fact)
        self.engine.cosecant_fact_received.connect(self._sine_presentation.handle_cosecant_fact)
        self.pages.study.continuity_popup_presented.connect(
            self._sine_presentation.handle_cosecant_popup_presented
        )

        # After every signal connection exists, request one initial Today
        # Health read so the card cannot remain permanently at Loading when
        # Control is already the restored page.
        self.analytics.request_today_session_health_refresh()

    def _restore_preferences(self) -> None:
        """Restore normal UI preferences without restoring a SINE stage."""

        preferences = self.settings.snapshot()
        self.settings.restore_window(self)

        self.shell.set_clock_visible(preferences.clock_visible)
        self.navigation.restore_page(preferences.last_page, fallback=PAGE_CONTROL)
        self.theme.set_base_theme(preferences.base_theme)
        self.theme.set_reduced_motion(preferences.reduced_motion)
        self.navigation.set_reduced_motion(preferences.reduced_motion)
        self.shell.alert_border.set_reduced_motion(preferences.reduced_motion)
        self.tray.apply_minimize_behavior(preferences.minimize_behavior)
        self._apply_theme(self.theme.current_theme)

    def _toggle_clock(self) -> None:
        visible = not self.shell.clock.isVisible()
        self.shell.set_clock_visible(visible)
        self.settings.set_clock_visible(visible)

    def _settings_changed(self, name: str, value: object) -> None:
        """React to a validated preference change; never to organ truth."""

        if name == "base_theme":
            self.theme.set_base_theme(str(value))

    def _open_settings(self) -> None:
        """``MENU -> SETTINGS -> THEME``: the drawer's Settings row was pressed."""

        self.navigation.close_sidebar()
        dialog = ThemePreferenceDialog(self.theme.base_theme.value, parent=self)
        dialog.theme_selected.connect(lambda key: self.settings.set("base_theme", key))
        dialog.exec()

    def _engine_status_changed(self, status: EngineStatus) -> None:
        self.pages.study.set_monitoring_active(status is EngineStatus.ACTIVE)
        self._sine_presentation.handle_engine_status(status)
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
        badge = str(getattr(event, "badge", "") or "").strip()
        feed_text = str(getattr(event, "feed_text", "") or "").strip()
        tone = str(getattr(event, "tone", "") or "").strip()

        local_time = self._activity_time(timestamp)

        if kind == "console_banner":
            print(str(message), flush=True)
            return

        if kind == "console_history":
            print(f"[{local_time}] {message}", flush=True)
            return

        if kind == "activity":
            badge = badge or "ACTIVITY"
            headline = self._activity_title(app, title)
            print(
                f"[MYELIN][{badge}] [{local_time}] app->{app or 'Unknown'} "
                f"[{headline}]",
                flush=True,
            )

            self.pages.control.append_telemetry(
                time_text=local_time,
                text=feed_text or f"{(app or 'UNKNOWN').upper()} \u2014 {headline}",
                tag=badge,
                tone=tone,
            )
            return

        if badge:
            text = feed_text or str(message or "Telemetry event")
            print(f"[{local_time}] [{badge}] {text}", flush=True)
            self.pages.control.append_telemetry(
                time_text=local_time,
                text=text,
                tag=badge,
                tone=tone,
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

    # Every custom painter this launcher can reach.  A widget of one of these
    # classes anywhere under ``self.shell`` is refreshed automatically, so no
    # per-page wiring is needed when a new card or chart is added later.
    _THEME_AWARE_WIDGET_TYPES: Final = (
        AxonCanvas,
        EngineRing,
        BarTrack,
        Dot,
        CircuitTrace,
        BrandMark,
        NavIcon,
        HeroCard,
        ShowcaseBarChart,
        ShowcaseDonut,
        ShowcaseScatter,
        StudyRing,
        _ShowcaseArrow,
    )

    def _apply_theme(self, theme) -> None:
        """Apply visual truth, then refresh the native Windows caption."""

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_application_stylesheet(theme))
        set_active_theme(theme)
        _set_live_tokens(theme)
        self.navigation.apply_theme(theme)
        self.shell.apply_theme(theme)
        self.pages.study.apply_theme(theme)
        for widget_type in self._THEME_AWARE_WIDGET_TYPES:
            for widget in self.shell.findChildren(widget_type):
                widget.apply_theme(theme)

        # One-off showcase fixtures (Metric Hub / Live MIRL / COSINE cards,
        # journey pills/steps, the CTA button, table dividers, ...) that build
        # a literal per-instance stylesheet instead of a custom painter class
        # register a ``_retheme`` closure at construction time -- see
        # ``_remember_retheme``.  This is the one place that closure is ever
        # invoked again.
        for widget in self.shell.findChildren(QWidget):
            retheme = getattr(widget, "_retheme", None)
            if callable(retheme):
                retheme(theme)

        self.shell.alert_border.set_alert(
            theme.cyan if theme in (AMBER_ALERT_THEME, RED_ALERT_THEME) else None
        )

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

    def _reassert_window_icon(self) -> None:
        self.setWindowIcon(_canonical_application_icon())

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        self._reassert_window_icon()
        QTimer.singleShot(0, self._reassert_window_icon)
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
        # Analytics workers READ persistence, so they must finish before this
        # facade releases the shared SQLite lane below.  The wait is bounded;
        # an overrun is reported, never silently ignored (C12-C).
        try:
            if not self.analytics.shutdown():
                print("[MYELIN][SHUTDOWN] analytics worker did not finish", flush=True)
        except Exception as exc:
            print(f"[MYELIN][SHUTDOWN] analytics shutdown failed: {exc}", flush=True)
        self.tray.shutdown()
        # Stop accepting new Notes edits and drain accepted ones through the
        # existing bounded contract, BEFORE the engine stops and before this
        # facade releases the shared lane -- otherwise an accepted edit could
        # still be queued when persistence goes away.
        try:
            if not self.notes_workspace.shutdown(timeout=2.0):
                print("[MYELIN][SHUTDOWN] notes flush incomplete", flush=True)
        except Exception as exc:
            print(f"[MYELIN][SHUTDOWN] notes shutdown failed: {exc}", flush=True)
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

        self._splash = MyelinLoadingScreen(
            logo_path=self._resolve_loading_logo(),
        )
        # Volunteer the window icon up front rather than waiting to be asked.
        # Qt holds it until the native window exists, so this is the icon the
        # HWND created by start()'s show() is born with.
        self._splash.setWindowIcon(_canonical_application_icon())

    @property
    def splash(self) -> MyelinLoadingScreen:
        return self._splash

    def start(self) -> None:
        self._splash.start()
        # The splash now owns a native window and the GUI thread is still
        # free.  Push the icon again here so a real WM_SETICON goes out while
        # nothing is blocking, instead of Explorer having to query for it
        # later while ControlStationWindow() holds the thread.
        self._splash.setWindowIcon(_canonical_application_icon())
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


def _canonical_application_icon() -> QIcon:
    """Return THE MYELIN icon, for every window and for the application.

    One asset, one loader.  Windows paints the *window* icon on the taskbar
    button and falls back to the *application* icon only for windows that set
    none -- in practice the frameless startup splash.  Two call sites loading
    two different files therefore showed two different marks during startup.
    Routing both through here keeps them from drifting apart again.
    """

    return resource_icon("icons/Myelin_2.ico")


def _configure_application(app: QApplication) -> None:
    """Apply process-wide Qt settings before any main window is created."""

    app.setApplicationName("MYELIN Control Station")
    app.setWindowIcon(_canonical_application_icon())
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
    # This is THE process bootstrap (C12-B): it latches, so no later facade
    # construction or dashboard read reinstalls the schema behind the shared
    # SQLite writer lane.
    bootstrap_production_schema()

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
