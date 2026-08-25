"""Canonical MYELIN visual tokens and theme presentation helpers.

This module contains visual facts only. SINE stage truth remains owned by
SINE.sine; profiles/settings cannot choose Blue/Amber/Red intervention state.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon
from PyQt6.QtWidgets import QLabel, QWidget

UI_FAMILIES: Final = ["Segoe UI", "Inter", "Noto Sans", "DejaVu Sans", "sans-serif"]
MONO_FAMILIES: Final = [
    "Consolas",
    "Cascadia Mono",
    "SFMono-Regular",
    "DejaVu Sans Mono",
    "monospace",
]

RADIUS_SM: Final = 8
RADIUS_MD: Final = 14
RADIUS_LG: Final = 22


@dataclass(frozen=True, slots=True)
class ThemeTokens:
    """MYELIN core design system, keyed to ``myelin_v2_mockup_2.html``.

    Names on the left are the historical launcher role names kept for existing
    consumers; the values are the mockup's ``:root`` custom properties.  The
    ``mix_*`` entries are the mockup's ``color-mix()`` results resolved ahead of
    time, because Qt style sheets have no ``color-mix()``.
    """

    world_name: str = "MYELIN"
    # --base / --surface / --surface-soft / --surface-2
    window_background: str = "#0B0F19"
    surface: str = "#1E293B"
    surface_soft: str = "#111827"
    surface_2: str = "#16202F"
    # --text / --muted
    text_primary: str = "#E5E7EB"
    muted: str = "#94A3B8"
    # --cyan / --cyan-dim
    cyan: str = "#38BDF8"
    cyan_dim: str = "#1E7BAE"
    # --red / --amber / --green and their dims
    red: str = "#F43F5E"
    red_dim: str = "#9F1239"
    amber: str = "#FBBF24"
    amber_dim: str = "#92600A"
    green: str = "#22C55E"
    green_dim: str = "#15803D"
    # --violet (donor SINE BLUE chart_violet) -- brand-mark gradient only
    violet: str = "#B7A1FF"
    border: str = "#334155"
    is_dark: bool = True

    # Resolved color-mix() results.
    mix_card_border: str = "#34526C"     # cyan 14% over --border
    mix_hero_border: str = "#345A76"     # cyan 20% over --border
    mix_card_tint: str = "#203348"       # cyan  7% over --surface
    mix_hero_tint: str = "#224159"       # cyan 16% over --surface
    mix_toggle_bg: str = "#213B52"       # cyan 12% over --surface
    mix_toggle_border: str = "#2B739A"   # cyan 50% over --surface
    mix_pill_bg: str = "#1F3F40"         # green 14% over --surface
    mix_pill_border: str = "#206749"     # green 40% over --surface
    mix_stop_border: str = "#94354E"     # red 55% over --surface
    mix_stage_bg: str = "#16293C"        # cyan 10% over --surface-soft

    # --radius-sm / --radius-md / --radius-lg
    radius_sm: int = 8
    radius_md: int = 14
    radius_lg: int = 22


DEFAULT_THEME: Final = ThemeTokens()

class ThemeController(QObject):
    theme_changed = pyqtSignal(object)
    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._theme = DEFAULT_THEME
        self._reduced_motion = False
    @property
    def current_theme(self) -> ThemeTokens:
        return self._theme
    def set_reduced_motion(self, enabled: bool) -> None:
        self._reduced_motion = bool(enabled)
    # The MYELIN wordmark console now lives in CONTROL_STATION.launcher as
    # BrandConsole -- shell/topbar composition belongs with the shell.

def _assets_root() -> Path:
    # One canonical asset root, shared with PERSISTENCE.database (C12-E).
    from PERSISTENCE.database import ASSET_ROOT_NAME

    return Path(__file__).resolve().parents[1] / ASSET_ROOT_NAME

def resource_icon(relative_path: str) -> QIcon:
    relative = Path(str(relative_path))
    if relative.is_absolute() or ".." in relative.parts:
        return QIcon()
    path = (_assets_root() / relative).resolve()
    try:
        path.relative_to(_assets_root().resolve())
    except ValueError:
        return QIcon()
    return QIcon(str(path)) if path.is_file() else QIcon()

def _rgb(value: str) -> tuple[int, int, int]:
    colour = QColor(value)
    return colour.red(), colour.green(), colour.blue()


def mix(foreground: str, percent: float, background: str) -> str:
    """``color-mix(in srgb, foreground percent%, background)`` -> ``#RRGGBB``."""

    fr, fg, fb = _rgb(foreground)
    br, bg, bb = _rgb(background)
    k = percent / 100.0
    return "#%02X%02X%02X" % (
        round(fr * k + br * (1 - k)),
        round(fg * k + bg * (1 - k)),
        round(fb * k + bb * (1 - k)),
    )


def alpha(value: str, a: float) -> str:
    """``color-mix(in srgb, value n%, transparent)`` -> a Qt ``rgba(...)``."""

    r, g, b = _rgb(value)
    return "rgba(%d, %d, %d, %d)" % (r, g, b, round(max(0.0, min(1.0, a)) * 255))


def qalpha(value, a: float) -> QColor:
    colour = QColor(value)
    colour.setAlpha(int(max(0.0, min(1.0, a)) * 255))
    return colour


def make_font(
    size_px: float,
    weight: int = 400,
    *,
    mono: bool = False,
    spacing: float = 0.0,
    italic: bool = False,
) -> QFont:
    """CSS px -> Qt font, exactly as the donor's ``mkfont``.

    Sizes throughout the shell are the mockup's CSS pixel values; Qt wants
    points, hence the 0.75 factor.  Letter-spacing is absolute px because Qt
    style sheets have no ``letter-spacing`` property at all.
    """

    font = QFont()
    font.setFamilies(MONO_FAMILIES if mono else UI_FAMILIES)
    font.setPointSizeF(float(size_px) * 0.75)
    font.setWeight(QFont.Weight(max(100, min(900, int(weight)))))
    font.setItalic(bool(italic))
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(spacing))
    return font


def label(
    text: str,
    size_px: float = 13.0,
    weight: int = 400,
    role: str = "text",
    *,
    mono: bool = False,
    spacing: float = 0.0,
    upper: bool = False,
    wrap: bool = False,
) -> QLabel:
    """One themed label; colour comes from the ``role`` property, not QSS ids."""

    made = QLabel(text.upper() if upper else text)
    made.setFont(make_font(size_px, weight, mono=mono, spacing=spacing))
    made.setProperty("role", role)
    made.setWordWrap(wrap)
    made.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    return made


def build_application_stylesheet(tokens: ThemeTokens | None = None) -> str:
    """Return the launcher QSS, ported 1:1 from the donor ``build_qss``.

    Presentation only.  Role and state colours arrive as Qt properties so a
    widget never has to be re-created to change appearance, and no rule here
    decides a SINE stage, a disposition or any engine value.
    """

    t = tokens or DEFAULT_THEME
    base, surface, soft = t.window_background, t.surface, t.surface_soft
    text, muted, border = t.text_primary, t.muted, t.border
    cyan, cyan_dim = t.cyan, t.cyan_dim
    red, red_dim, amber, green, green_dim, violet = (
        t.red,
        t.red_dim,
        t.amber,
        t.green,
        t.green_dim,
        t.violet,
    )

    return f"""
/* ---------- base ---------- */
QWidget#appRoot, QWidget#pagesHost, QWidget#pageBody, QWidget#scrollHost,
QWidget#pageGrid, QWidget#plainBox {{
    background: {base};
}}
QWidget#pageGrid, QWidget#plainBox {{ background: transparent; }}
QLabel {{ background: transparent; color: {text}; }}
QLabel[role="muted"] {{ color: {muted}; }}
QLabel[role="cyan"]   {{ color: {cyan}; }}
QLabel[role="green"]  {{ color: {green}; }}
QLabel[role="amber"]  {{ color: {amber}; }}
QLabel[role="red"]    {{ color: {red}; }}
QToolTip {{
    background: {surface}; color: {text}; border: 1px solid {border};
    padding: 6px 9px;
}}

/* ---------- card language (radius 22, 1px border, soft shadow) ---------- */
QFrame#card {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {RADIUS_LG}px;
}}
QFrame#statBox {{
    background: {soft};
    border: 1px solid {border};
    border-radius: {RADIUS_MD}px;
}}

/* ---------- topbar ---------- */
QFrame#hudClock, QFrame#systemClock {{
    background: {surface};
    border: 1px solid {border};
    border-radius: {RADIUS_LG}px;
}}
QFrame#hudDateRow {{ border-top: 1px solid {border}; background: transparent; }}
QPushButton#clockSettingsButton, QPushButton#clockCollapseButton {{
    background: transparent; color: {muted};
    border: 1px solid {border}; border-radius: 13px; padding: 0px;
}}
QPushButton#clockSettingsButton:hover, QPushButton#clockCollapseButton:hover {{
    color: {cyan}; border-color: {cyan_dim};
}}

/* ---------- clock timezone dialog ---------- */
QDialog#timezoneDialog {{
    background: {surface};
    border: 1px solid {border};
}}
QDialog#timezoneDialog QLabel {{ background: transparent; }}
QListWidget#timezoneList {{
    background: {soft};
    color: {text};
    border: 1px solid {border};
    border-radius: {RADIUS_SM}px;
    padding: 4px;
    outline: none;
}}
QListWidget#timezoneList::item {{
    padding: 7px 10px;
    border-radius: {RADIUS_SM}px;
}}
QListWidget#timezoneList::item:hover {{ background: {alpha(cyan, 0.08)}; }}
QListWidget#timezoneList::item:selected {{
    background: {alpha(cyan, 0.18)};
    color: {cyan};
}}

QPushButton#menuButton, QPushButton#topbarClock {{
    background: {soft}; color: {muted};
    border: 1px solid {border}; border-radius: {RADIUS_SM}px;
    padding: 9px 15px;
}}
QPushButton#menuButton:hover, QPushButton#topbarClock:hover {{
    color: {cyan}; border-color: {cyan_dim};
}}
QPushButton#topbarChart {{
    background: {cyan}; color: {base};
    border: 1px solid {cyan}; border-radius: {RADIUS_SM}px;
    padding: 9px 17px;
}}
QPushButton#topbarChart:hover {{ background: {mix(cyan, 80, text)}; }}

/* ---------- engine core ---------- */
QLabel#statusPill {{
    color: {muted};
    background: {alpha(muted, 0.14)};
    border: 1px solid {alpha(muted, 0.40)};
    border-radius: 999px;
    padding: 4px 12px;
}}
QLabel#statusPill[state="active"] {{
    color: {green};
    background: {alpha(green, 0.14)};
    border: 1px solid {alpha(green, 0.40)};
}}
QLabel#statusPill[state="paused"] {{
    color: {amber};
    background: {alpha(amber, 0.14)};
    border: 1px solid {alpha(amber, 0.40)};
}}
QLabel#statusPill[state="alert"] {{
    color: {red};
    background: {alpha(red, 0.14)};
    border: 1px solid {alpha(red, 0.40)};
}}
QLabel#profileButtonPrefix {{ color: {muted}; background: transparent; border: none; }}
QLabel#profileButtonValue {{
    color: {cyan}; background: transparent; border: none; font-weight: 700;
}}
QFrame#profileButton {{
    background: {mix(cyan, 8, surface)};
    border: 1px solid {alpha(cyan, 0.28)};
    border-radius: {RADIUS_SM}px;
}}
QComboBox#profileButtonValue {{
    color: {cyan}; background: transparent; border: none; font-weight: 700;
}}
QComboBox#profileButtonValue::drop-down {{ border: none; width: 14px; }}
QComboBox#profileButtonValue QAbstractItemView {{
    background: {surface}; color: {text};
    border: 1px solid {border}; selection-background-color: {alpha(cyan, 0.18)};
}}
QPushButton#studyModeButton {{
    background: {mix(cyan, 12, surface)}; color: {cyan};
    border: 1px solid {alpha(cyan, 0.50)}; border-radius: {RADIUS_SM}px;
    padding: 8px 14px;
}}
QPushButton#studyModeButton:hover {{ background: {mix(cyan, 20, surface)}; }}

/* ---------- engine controls (donor material button roles) ---------- */
QPushButton#btnStart {{
    background: {green}; color: #06210F; border: none;
    border-radius: {RADIUS_SM}px; padding: 10px 18px;
}}
QPushButton#btnPause {{
    background: {amber}; color: #2A1B02; border: none;
    border-radius: {RADIUS_SM}px; padding: 10px 18px;
}}
QPushButton#btnStop {{
    background: transparent; color: {red};
    border: 1px solid {alpha(red, 0.55)};
    border-radius: {RADIUS_SM}px; padding: 10px 18px;
}}
QPushButton#btnStart:hover {{ background: {mix(green, 88, text)}; }}
QPushButton#btnPause:hover {{ background: {mix(amber, 88, text)}; }}
QPushButton#btnStop:hover {{ background: {alpha(red, 0.10)}; }}
QPushButton#btnStart:disabled, QPushButton#btnPause:disabled {{
    background: {soft}; color: {mix(muted, 45, soft)}; border: 1px solid {border};
}}
QPushButton#btnStop:disabled {{ color: {mix(muted, 45, soft)}; border-color: {border}; }}
QPushButton#btnEmergency {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 {red}, stop:1 {red_dim});
    color: #FFF1F2; border: none;
    border-radius: {RADIUS_SM}px; padding: 13px 18px;
}}
QPushButton#btnEmergency:hover {{ background: {red}; }}
QPushButton#btnEmergency:disabled {{
    background: {soft}; color: {mix(muted, 45, soft)};
}}

/* ---------- SINE strip ---------- */
QFrame#sineStage {{
    background: {soft};
    border: 1px solid {border};
    border-radius: {RADIUS_SM}px;
}}
QFrame#sineStage[current="true"] {{
    background: {mix(cyan, 10, soft)};
    border: 1px solid {cyan_dim};
}}

/* ---------- feed ---------- */
QFrame#feedItem {{ border-bottom: 1px solid {border}; background: transparent; }}
QFrame#feedItem[last="true"] {{ border-bottom: none; }}
QLabel#feedTag {{
    border-radius: 999px; padding: 2px 8px;
    color: {cyan}; background: {alpha(cyan, 0.12)};
}}
QLabel#feedTag[tone="amber"] {{ color: {amber}; background: {alpha(amber, 0.12)}; }}
QLabel#feedTag[tone="red"]   {{ color: {red};   background: {alpha(red, 0.12)}; }}
QLabel#feedTag[tone="green"] {{ color: {green}; background: {alpha(green, 0.12)}; }}
QLabel#feedTag[tone="violet"] {{ color: {violet}; background: {alpha(violet, 0.14)}; }}

/* ---------- scroll areas ---------- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0px; }}
QScrollBar::handle:vertical {{
    background: {border}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {cyan_dim}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 0px; }}
QScrollBar::handle:horizontal {{
    background: {border}; border-radius: 4px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ---------- generic ---------- */
/* NOTE: no bare ``QFrame`` rule.  QLabel derives from QFrame, so a plain
   QFrame selector silently repaints every label in the shell -- use the
   exact-class form ``.QFrame`` or an object name instead. */
QWidget#loadingPanel {{ background: {surface}; border: 1px solid {border}; }}
QPushButton {{
    background: {soft}; color: {text};
    border: 1px solid {border}; border-radius: {RADIUS_SM}px; padding: 7px 12px;
}}
QPushButton:hover {{ border-color: {cyan_dim}; }}

/* ---------- navigation drawer (mockup .sidebar) ---------- */
/* The drawer is the mockup's off-canvas ``.sidebar``: --surface-soft, a
   single right border, a divided head and grouped rows.  Row colour is
   driven by ``:checked``; the row's icon is painted by NavIcon and is told
   its colour by the sidebar, because a QSS ``color`` cannot reach into a
   child widget's painter. */
QFrame#sidebar {{
    background: {soft};
    border: none;
    border-right: 1px solid {border};
}}
QWidget#sidebarHead {{
    background: transparent;
    border: none;
    border-bottom: 1px solid {border};
}}
QLabel#sidebarBrand {{ color: {text}; background: transparent; }}
QLabel#sidebarBrandAccent {{ color: {cyan}; background: transparent; }}
QLabel#navGroupTitle {{ color: {cyan}; background: transparent; }}

QPushButton#sidebarNavigationButton {{
    background: transparent;
    color: {text};
    border: none;
    border-radius: {RADIUS_SM}px;
    padding: 0px;
    text-align: left;
}}
QPushButton#sidebarNavigationButton:hover {{ background: {t.surface_2}; }}
QPushButton#sidebarNavigationButton:checked {{ background: {alpha(cyan, 0.14)}; }}
QPushButton#sidebarNavigationButton:disabled {{ background: transparent; }}

/* ``.sidebar-backdrop`` -- dims the page while the drawer is open so the
   drawer reads as modal and the click-to-dismiss target is obvious. */
QWidget#sidebarBackdrop {{ background: rgba(0, 0, 0, 90); }}

/* A real destination whose subsystem is not built yet. */
QWidget#comingSoonPage {{ background: {base}; }}
QFrame#comingSoonCard {{
    background: {surface};
    border: 1px solid {t.mix_card_border};
    border-radius: {RADIUS_LG}px;
}}
QLabel#comingSoonPageBadge {{
    color: {cyan};
    background: {alpha(cyan, 0.12)};
    border: 1px solid {alpha(cyan, 0.40)};
    border-radius: 999px;
    padding: 6px 16px;
}}

/* An approved future-capability marker.  It must read as "not yet", never
   as broken and never as clickable. */
QFrame#sidebarComingSoonRow {{ background: transparent; border: none; }}
QLabel#comingSoonLabel {{ color: {mix(muted, 58, soft)}; background: transparent; }}
QLabel#comingSoonBadge {{
    color: {mix(muted, 58, soft)};
    background: transparent;
    border: 1px solid {mix(border, 70, soft)};
    border-radius: 999px;
    padding: 2px 7px;
}}

QWidget#sidebarFoot {{
    background: transparent;
    border: none;
    border-top: 1px solid {border};
}}
QLabel#sidebarFootNote {{ color: {mix(muted, 62, soft)}; background: transparent; }}

/* ---------- Study Mode (mockup #page-study-mode) ---------- */
QWidget#studyModePage {{ background: {base}; }}
QWidget#studyModeBody {{ background: transparent; }}
QLabel#studyModeTitle {{ color: {text}; background: transparent; }}
QLabel#studyModeSubtitle {{ color: {muted}; background: transparent; }}

/* .sm-status-pill -- 999px radius, 14% tint, 45% border.
   Muted is the default, so a pill that is never given a tone reads as
   neutral rather than as a state it has not earned. */
QLabel#studyStatePill, QLabel#studyMonitoringPill,
QLabel#studyStatePill[tone="muted"], QLabel#studyMonitoringPill[tone="muted"] {{
    border-radius: 999px;
    padding: 7px 16px;
    color: {muted};
    background: {soft};
    border: 1px solid {border};
}}
/* Approved STUDY state mapping: EMPTY muted, READY cyan, ACTIVE green,
   PAUSED amber.  A state outside the mapping keeps the muted default -- no
   colour is invented for it here. */
QLabel#studyStatePill[tone="cyan"] {{
    color: {cyan};
    background: {alpha(cyan, 0.14)};
    border: 1px solid {alpha(cyan, 0.45)};
}}
QLabel#studyStatePill[tone="green"], QLabel#studyMonitoringPill[tone="green"] {{
    color: {green};
    background: {alpha(green, 0.14)};
    border: 1px solid {alpha(green, 0.45)};
}}
QLabel#studyStatePill[tone="amber"] {{
    color: {amber};
    background: {alpha(amber, 0.14)};
    border: 1px solid {alpha(amber, 0.45)};
}}

/* .btn-cta -- the Study Menu control */
QToolButton#studyMenuButton {{
    background: transparent;
    color: {cyan};
    border: 1px solid {cyan_dim};
    border-radius: {RADIUS_SM}px;
    padding: 10px 18px;
}}
QToolButton#studyMenuButton:hover {{ background: {alpha(cyan, 0.10)}; }}
QToolButton#studyMenuButton::menu-indicator {{ image: none; width: 0px; }}
QMenu#studyMenu {{
    background: {surface};
    color: {text};
    border: 1px solid {border};
    border-radius: {RADIUS_SM}px;
    padding: 6px;
}}
QMenu#studyMenu::item {{ padding: 8px 18px; border-radius: {RADIUS_SM}px; }}
QMenu#studyMenu::item:selected {{ background: {alpha(cyan, 0.16)}; color: {cyan}; }}
QMenu#studyMenu::separator {{ height: 1px; background: {border}; margin: 5px 8px; }}

/* .card -- one card language shared by every Study Mode panel */
QFrame#studyTimerCard, QFrame#studySetupCard, QFrame#studyTelemetryCard,
QFrame#resourceIntentTelemetryCard, QFrame#studyStreamCard, QFrame#studyPlanCard {{
    background: {surface};
    border: 1px solid {t.mix_card_border};
    border-radius: {RADIUS_LG}px;
}}
/* .card-head h2 */
QLabel#studySectionHeading {{ color: {muted}; background: transparent; }}

/* .sm-timer-task / .sm-timer-subject / .sm-timer-block */
QLabel#studyTimerCaption {{ color: {muted}; background: transparent; }}
QLabel#studySubject {{ color: {text}; background: transparent; }}
QLabel#studyTask {{ color: {cyan}; background: transparent; }}
QLabel#studyTimerState {{ color: {muted}; background: transparent; }}

/* .sm-timer-meta */
QLabel#studyMetaLabel {{ color: {muted}; background: transparent; }}
QLabel#studyMetaValue {{ color: {text}; background: transparent; }}

/* The linear bar is kept as a thin under-ring reading of the same fraction */
QProgressBar#studyTimerProgress {{
    background: {soft};
    border: none;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
}}
QProgressBar#studyTimerProgress::chunk {{
    background: {cyan};
    border-radius: 3px;
}}

/* .sm-dur-btn */
QPushButton#studyDurationButton {{
    background: {soft};
    color: {text};
    border: 1px solid {border};
    border-radius: {RADIUS_SM}px;
    padding: 10px 8px;
}}
QPushButton#studyDurationButton:hover {{ border-color: {cyan_dim}; color: {cyan}; }}
QPushButton#studyDurationButton:checked {{
    background: {alpha(cyan, 0.16)};
    border-color: {cyan_dim};
    color: {cyan};
}}

/* .sm-field label + .sm-field input */
QLabel#studyFieldLabel {{ color: {muted}; background: transparent; }}
QLineEdit#studySubjectInput, QLineEdit#studyTaskInput,
QSpinBox#studyMinutesInput, QSpinBox#studyBreakInput {{
    background: {soft};
    color: {text};
    border: 1px solid {border};
    border-radius: {RADIUS_SM}px;
    padding: 8px 10px;
    selection-background-color: {alpha(cyan, 0.30)};
}}
QLineEdit#studySubjectInput:focus, QLineEdit#studyTaskInput:focus,
QSpinBox#studyMinutesInput:focus, QSpinBox#studyBreakInput:focus {{
    border-color: {cyan_dim};
}}
QSpinBox#studyMinutesInput::up-button, QSpinBox#studyBreakInput::up-button,
QSpinBox#studyMinutesInput::down-button, QSpinBox#studyBreakInput::down-button {{
    background: transparent;
    border: none;
    width: 14px;
}}
/* Locked while a Study block is ACTIVE or PAUSED: the configured values stay
   readable, but nothing here may look editable, because editing it could not
   change the block that is already running. */
QLineEdit#studySubjectInput:disabled, QLineEdit#studyTaskInput:disabled,
QSpinBox#studyMinutesInput:disabled, QSpinBox#studyBreakInput:disabled {{
    background: {soft};
    color: {mix(muted, 78, soft)};
    border: 1px solid {mix(border, 60, soft)};
}}
QPushButton#studyDurationButton:disabled {{
    background: {soft};
    color: {mix(muted, 55, soft)};
    border: 1px solid {mix(border, 60, soft)};
}}
QPushButton#studyDurationButton:checked:disabled {{
    background: {mix(cyan, 7, surface)};
    color: {mix(cyan, 55, soft)};
    border: 1px solid {mix(cyan_dim, 55, soft)};
}}

/* .btn-block.solid-cyan */
QPushButton#studyPrepareButton {{
    background: {cyan};
    color: {base};
    border: 1px solid {cyan};
    border-radius: {RADIUS_SM}px;
    padding: 11px 22px;
}}
QPushButton#studyPrepareButton:hover {{ background: {mix(cyan, 84, text)}; }}

/* .btn-start / .btn-pause / .btn-block.outline */
QPushButton#studyStartButton {{
    background: {green}; color: #06210F; border: none;
    border-radius: {RADIUS_SM}px; padding: 10px 18px;
}}
QPushButton#studyStartButton:hover {{ background: {mix(green, 88, text)}; }}
QPushButton#studyPauseButton {{
    background: {amber}; color: #2A1B02; border: none;
    border-radius: {RADIUS_SM}px; padding: 10px 18px;
}}
QPushButton#studyPauseButton:hover {{ background: {mix(amber, 88, text)}; }}
QPushButton#studyResumeButton, QPushButton#studyStartBreakButton {{
    background: transparent; color: {cyan};
    border: 1px solid {cyan_dim};
    border-radius: {RADIUS_SM}px; padding: 10px 18px;
}}
QPushButton#studyResumeButton:hover, QPushButton#studyStartBreakButton:hover {{
    background: {alpha(cyan, 0.10)};
}}
QPushButton#studyCompleteButton {{
    background: transparent; color: {text};
    border: 1px solid {border};
    border-radius: {RADIUS_SM}px; padding: 10px 18px;
}}
QPushButton#studyCompleteButton:hover {{ border-color: {cyan_dim}; color: {cyan}; }}
QPushButton#studyStartButton:disabled, QPushButton#studyPauseButton:disabled,
QPushButton#studyPrepareButton:disabled {{
    background: {soft}; color: {mix(muted, 45, soft)}; border: 1px solid {border};
}}
QPushButton#studyResumeButton:disabled, QPushButton#studyCompleteButton:disabled,
QPushButton#studyStartBreakButton:disabled {{
    background: transparent; color: {mix(muted, 45, soft)}; border-color: {border};
}}

/* .sm-kv-row -- the hairline runs under both columns of the grid */
QLabel#studyTelemetryName, QLabel#resourceIntentName {{
    color: {muted};
    background: transparent;
    border-bottom: 1px solid {border};
    padding-bottom: 9px;
}}
QLabel#studyTelemetryValue, QLabel#resourceIntentValue {{
    color: {text};
    background: transparent;
    border-bottom: 1px solid {border};
    padding-bottom: 9px;
}}

/* COSECANT continuity popup -- one green MYELIN presentation family. */
QDialog#cosecantContinuityPopup {{
    background: {alpha(green, 0.10)};
    border: none;
}}
QFrame#cosecantPopupShell {{
    background: {soft};
    border: 2px solid {green};
    border-radius: 18px;
}}
QLabel#cosecantPopupStatusDot {{
    color: {green};
    background: transparent;
}}
QLabel#cosecantPopupEyebrow {{
    color: {muted};
    background: transparent;
}}
QLabel#cosecantPopupBadge {{
    color: {green};
    background: {alpha(green, 0.08)};
    border: 1px solid {green};
    border-radius: 13px;
}}
QLabel#cosecantPopupMessage {{
    color: {green};
    background: transparent;
}}
QLabel#cosecantPopupDetail {{
    color: {text};
    background: transparent;
}}
QLabel#cosecantPopupStatus, QLabel#cosecantPopupProtected {{
    color: {green};
    background: transparent;
}}
QLabel#cosecantPopupCountdown, QLabel#cosecantPopupFooter {{
    color: {muted};
    background: transparent;
}}
QFrame#cosecantPopupAccentLine {{
    background: {green};
    border: none;
    border-radius: 2px;
}}
QPushButton#cosecantReturnIntentButton {{
    color: #06210F;
    background: {green};
    border: 1px solid {green};
    border-radius: 10px;
    padding: 10px 22px;
}}
QPushButton#cosecantReturnIntentButton:hover {{
    background: {mix(green, 86, text)};
    border-color: {mix(green, 86, text)};
}}
QPushButton#cosecantReturnIntentButton:pressed {{
    background: {green_dim};
    border-color: {green_dim};
}}
QPushButton#cosecantReturnIntentButton:focus {{
    border: 2px solid {mix(green, 70, text)};
}}
QPushButton#cosecantReturnIntentButton:disabled {{
    color: {mix(muted, 55, soft)};
    background: {mix(green_dim, 28, soft)};
    border-color: {mix(green_dim, 40, soft)};
}}
"""


def card_shadow(widget: QWidget, blur: int = 50, dy: int = 20, strength: float = 0.6) -> None:
    """Apply the donor's card shadow foundation to one launcher card."""

    from PyQt6.QtWidgets import QGraphicsDropShadowEffect

    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setXOffset(0)
    effect.setYOffset(dy)
    effect.setColor(qalpha(QColor(0, 0, 0), strength))
    widget.setGraphicsEffect(effect)


def restyle(widget: QWidget) -> None:
    """Re-evaluate QSS after a dynamic property changed."""

    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def apply_native_titlebar(window, *, background: str, foreground: str, dark_mode: bool) -> bool:
    """Best-effort Windows DWM caption styling; never changes application truth."""
    try:
        import ctypes
        if not hasattr(ctypes, "windll"):
            return False
        hwnd = int(window.winId())
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1 if dark_mode else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
        def colorref(value: str) -> int:
            c = QColor(value)
            return c.red() | (c.green() << 8) | (c.blue() << 16)
        bg = ctypes.c_uint(colorref(background)); fg = ctypes.c_uint(colorref(foreground))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(bg), ctypes.sizeof(bg))
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(fg), ctypes.sizeof(fg))
        return True
    except Exception:
        return False

__all__ = ["ThemeController", "ThemeTokens", "DEFAULT_THEME", "apply_native_titlebar", "build_application_stylesheet", "make_font", "resource_icon"]
