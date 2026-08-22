"""SINE popup presentation: Blue / Amber / Red -- the MYELIN visual family.

``SINE.sine`` owns every stage, deadline, response decision and Protected Red
truth.  This module draws SINE, emits action intent, certifies factual
visibility/HWND, reports delivery failure, and waits for an exact SINE close
fact before ever closing.  Visual design and mechanical behavior were
finished together in one phase -- see
``MYELIN_32_CANONICAL_OLD_TO_NEW_FILE_MAPPING_20260820.txt`` section 14 --
specifically so this file would not need to be redrawn and rewired twice.

Strict boundary
---------------
* A button emits a user action; it never decides or advances a SINE stage.
* A button does not close its own popup.  It waits for an exact SINE close
  fact.
* The countdown (label and glow strip) is a visual projection of SINE's own
  monotonic deadline (``request.visible_seconds`` against a local
  ``QElapsedTimer``); this module never owns or invents a deadline.
* Protected SINE 3 has no action buttons and cannot be manually dismissed.
* Study Material is never granted here; this file imports no Study/Resource
  Intent authority.
* The Weber-Fechner line is presentation metadata already computed by
  ``SINE.sine``.  The popup never calculates a psychophysical value or
  chooses intervention level -- escalating visual salience (Blue -> Amber ->
  Red, calm -> direct) is this module's own presentation choice, not a
  second timing engine.

Donor lineage
-------------
Harvested, not copied whole -- see the GOOD/BAD forensic reports for
``widgets/nudge_ui.py``, ``themes/sine_intervention_surface.py``,
``themes/sine_animator.py``, ``control_station/study_mode/
study_nudge_presenter.py`` and ``widgets/material_button.py``:

* the breathing status orb and Red-only alert glyph (from
  ``sine_intervention_surface.py``'s ``_BreathingOrb``/``_RedWarningTriangle``);
* the halo-bordered panel identity and glow-button language (from
  ``nudge_ui.py``'s ``_outer_shell``/``_glow_button``);
* the entrance drift+fade and the breathing glow cycle (from
  ``sine_animator.py``'s ``slide_fade_in``/``soft_glow_breathing``,
  reduced-motion aware via its ``reduced_motion_requested()``);
* the "STUDY ACTIVE" footer idea (from ``study_nudge_presenter.py``); and
* explicit hover/pressed/focus button states (from ``material_button.py``,
  reimplemented compactly rather than importing the donor's general-purpose
  ripple widget for what is at most two fixed buttons here).

Deliberately NOT harvested: the donors' absolute-pixel ``setGeometry``
layout (this file uses Qt layouts + elided/word-wrapped text instead, so
long resource titles and Windows display scaling cannot clip content); the
donors' Study/Resource Intent state mutation, SQLite writes, legacy
``t_star`` copy, and SINE-4 presentation (all confirmed WEED); and the
donors' persistent single mutable surface with in-place ``world_transition``
(this module keeps one immutable window per ``SinePopupRequest``, matching
this module's own pre-existing supersession mechanics, which predate this
design pass and are unchanged below).
"""

from __future__ import annotations

import os
import threading
import time
import weakref
from dataclasses import dataclass
from typing import Final

from PyQt6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSequentialAnimationGroup,
    QThread,
    QTimer,
    QVariantAnimation,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QCloseEvent, QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from SINE.sine import SineFact, SinePopupRequest, SineResponse, SineStage


POPUP_SCHEMA_VERSION: Final = "myelin-sine-popup-v1"
COUNTDOWN_REFRESH_MS: Final = 250
POPUP_WIDTH: Final = 620
STANDARD_HEIGHT: Final = 460
PROTECTED_RED_HEIGHT: Final = 360
ENTRANCE_DURATION_MS: Final = 320
ENTRANCE_DRIFT_PX: Final = 14
ENTRANCE_START_OPACITY: Final = 0.88
GLOW_BREATH_DURATION_MS: Final = 1800

_ACTIVE_HWND_LOCK = threading.RLock()
_ACTIVE_POPUP_HWND: set[int] = set()


def reduced_motion_requested() -> bool:
    """Read the OS/application reduced-motion preference without raising.

    Harvested from ``themes/sine_animator.py``'s ``reduced_motion_requested``.
    Checked only as the DEFAULT when a caller does not explicitly pass
    ``reduced_motion`` -- an explicit value always wins.
    """

    value = os.environ.get("MYELIN_REDUCED_MOTION", "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    app = QApplication.instance()
    if app is None:
        return False
    try:
        return bool(
            app.property("reducedMotion")
            or app.property("reduceMotion")
            or app.property("sineReducedMotion")
        )
    except Exception:
        return False


@dataclass(frozen=True, slots=True)
class PopupPalette:
    """Immutable visual identity for exactly one SINE world. Carries no SINE truth."""

    world: str
    accent: str
    accent_dim: str
    halo: str
    panel: str
    text: str = "#F4F7FB"
    muted: str = "#93A1B8"
    footer: str = "#6B7A94"
    button_text_on_accent: str = "#06131F"


# SINE 1 (Blue/Gentle) deliberately reuses MYELIN's own brand cyan
# (UI_THEMES.theme.ThemeTokens.cyan / .cyan_dim / .window_background /
# .surface) rather than inventing a separate blue -- the calmest stage IS
# the brand color, which is how all three stages read as "one MYELIN visual
# family" while still escalating in salience toward Amber and Red.
PALETTES: Final = {
    "blue": PopupPalette(
        world="blue",
        accent="#3DDCFF",
        accent_dim="#17677A",
        halo="#123244",
        panel="#111827",
    ),
    "amber": PopupPalette(
        world="amber",
        accent="#F5A623",
        accent_dim="#8A5A12",
        halo="#3A2A0D",
        panel="#1C140A",
    ),
    "red": PopupPalette(
        world="red",
        accent="#FF4D6D",
        accent_dim="#8C1F33",
        halo="#3A0F18",
        panel="#20090F",
    ),
}


def active_popup_hwnds() -> frozenset[int]:
    """Return only the native handles of currently certified SINE windows."""

    with _ACTIVE_HWND_LOCK:
        return frozenset(_ACTIVE_POPUP_HWND)


def is_sine_popup_hwnd(hwnd: int) -> bool:
    """Identify a SINE popup by exact registered HWND, never by window title."""

    if type(hwnd) is not int or hwnd <= 0:
        return False
    with _ACTIVE_HWND_LOCK:
        return hwnd in _ACTIVE_POPUP_HWND


def _register_hwnd(hwnd: int) -> None:
    if type(hwnd) is int and hwnd > 0:
        with _ACTIVE_HWND_LOCK:
            _ACTIVE_POPUP_HWND.add(hwnd)


def _unregister_hwnd(hwnd: int) -> None:
    if type(hwnd) is int and hwnd > 0:
        with _ACTIVE_HWND_LOCK:
            _ACTIVE_POPUP_HWND.discard(hwnd)


def _font(size: float, *, weight: QFont.Weight = QFont.Weight.Normal, mono: bool = False, spacing: float = 0.0) -> QFont:
    font = QFont("Consolas" if mono else "Segoe UI")
    font.setPixelSize(max(1, round(size)))
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(spacing))
    return font


class _StatusOrb(QWidget):
    """The small SINE status marker.  Breathing glow motion is caller-owned.

    Harvested concept from ``sine_intervention_surface.py``'s
    ``_BreathingOrb`` -- "the approved four-pixel SINE marker" -- redrawn as
    a plain filled circle sized for this layout.
    """

    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(10, 10)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAccessibleName("SINE status indicator")

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._accent))
        painter.drawEllipse(QRectF(0.0, 0.0, 10.0, 10.0))


class _AlertGlyph(QWidget):
    """Small, non-animated Red-only marker -- unmistakable, not decorative.

    Harvested concept from ``sine_intervention_surface.py``'s
    ``_RedWarningTriangle``.
    """

    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = accent
        self.setFixedSize(22, 20)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAccessibleName("Protected Red intervention")

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(self._accent)
        outline = QPainterPath()
        outline.moveTo(11.0, 1.5)
        outline.lineTo(20.0, 18.0)
        outline.lineTo(2.0, 18.0)
        outline.closeSubpath()
        pen = QPen(color, 1.8)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(outline)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(QRectF(10.1, 6.5, 1.8, 6.0), 0.9, 0.9)
        painter.drawEllipse(QRectF(10.0, 14.5, 2.0, 2.0))


class _GlowStrip(QWidget):
    """Slim countdown projection.  A pure repaint of a caller-supplied ratio."""

    def __init__(self, accent: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._accent = accent
        self._ratio = 1.0
        self.setFixedHeight(6)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = float(self.width())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self._accent).darker(280))
        painter.drawRoundedRect(QRectF(0.0, 1.0, width, 4.0), 2.0, 2.0)
        fill_w = width * self._ratio
        if fill_w > 0:
            painter.setBrush(QColor(self._accent))
            painter.drawRoundedRect(QRectF(0.0, 1.0, fill_w, 4.0), 2.0, 2.0)


class SinePopupWindow(QWidget):
    """One exact SINE popup occurrence with zero policy authority."""

    # Qt transport types, not value types.  ``pyqtSignal(int)`` is a C++
    # 32-bit int: a ``time.monotonic_ns()`` value (~50 bits) is silently
    # truncated to its low 32 bits and can arrive negative, after which
    # SINE._valid_event_time can never accept it.  ``object`` hands the
    # Python int across unchanged; callers coerce with int() on the far side.
    popup_shown = pyqtSignal(str, object, object)
    popup_failed = pyqtSignal(str, str, object)
    user_action = pyqtSignal(str, str, object)
    popup_closed = pyqtSignal(str, str, object)

    def __init__(
        self,
        request: SinePopupRequest,
        *,
        owner: QWidget | None = None,
        reduced_motion: bool = False,
        origin_point: tuple[int, int] | None = None,
    ) -> None:
        self._validate_request(request)
        super().__init__(None)
        self.request = request
        self._tokens = PALETTES[request.presentation.world]
        self._owner_ref = weakref.ref(owner) if owner is not None else lambda: None
        self._origin_point = origin_point
        self._reduced_motion = bool(reduced_motion)
        self._shown_reported = False
        self._failure_reported = False
        self._closed_reported = False
        self._authority_close_allowed = False
        self._close_reason = ""
        self._action_pending = False
        self._native_hwnd = 0
        self._entrance_animation: QParallelAnimationGroup | None = None
        self._orb_animation: QSequentialAnimationGroup | None = None

        self.setObjectName("sinePopup")
        self.setWindowTitle(f"MYELIN SINE — {request.presentation.badge}")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("MYELIN SINE intervention")
        self.setAccessibleDescription(request.presentation.message)
        self.setFixedSize(
            POPUP_WIDTH,
            PROTECTED_RED_HEIGHT if self.is_protected_red else STANDARD_HEIGHT,
        )

        self._elapsed = QElapsedTimer()
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(COUNTDOWN_REFRESH_MS)
        self._countdown_timer.timeout.connect(self._refresh_countdown)

        self._buttons: dict[SineResponse, QPushButton] = {}
        self._orb: _StatusOrb | None = None
        self._resource: QLabel | None = None
        self._build_widgets()
        self._apply_tokens()

    @staticmethod
    def _validate_request(request: SinePopupRequest) -> None:
        if not isinstance(request, SinePopupRequest):
            raise TypeError("popup requires a SinePopupRequest")
        if request.stage not in {SineStage.SINE_1, SineStage.SINE_2, SineStage.SINE_3}:
            raise ValueError("popup stage must be SINE 1, 2 or 3")
        expected_world = {
            SineStage.SINE_1: "blue",
            SineStage.SINE_2: "amber",
            SineStage.SINE_3: "red",
        }[request.stage]
        if request.presentation.world != expected_world:
            raise ValueError("popup world does not match its SINE stage")
        if request.protected != (request.stage is SineStage.SINE_3):
            raise ValueError("only SINE 3 may be protected")
        if request.stage is SineStage.SINE_3 and request.presentation.allowed_responses:
            raise ValueError("protected SINE 3 must not contain action buttons")
        if not request.request_id or not request.episode_uid or not request.candidate_uid:
            raise ValueError("popup request identity is incomplete")
        if request.operational_event_id <= 0 or request.occurrence <= 0:
            raise ValueError("popup request requires positive event/occurrence identity")
        if request.requested_monotonic_ns <= 0:
            raise ValueError("popup request requires a monotonic request time")
        if request.visible_seconds < 0:
            raise ValueError("popup visible duration cannot be negative")
        theory = request.presentation.weber_fechner
        if theory.stage_ordinal != int(request.stage):
            raise ValueError("Weber-Fechner projection does not match factual SINE stage")

    @property
    def is_protected_red(self) -> bool:
        return bool(self.request.protected and self.request.stage is SineStage.SINE_3)

    @property
    def native_hwnd(self) -> int:
        return self._native_hwnd

    # ------------------------------------------------------------------
    # Widget construction (design layer)
    # ------------------------------------------------------------------

    def _build_widgets(self) -> None:
        tokens = self._tokens
        presentation = self.request.presentation

        root = QVBoxLayout(self)
        root.setContentsMargins(3, 3, 3, 3)
        root.setSpacing(0)

        # Halo shell: a thin colored margin behind a bordered inner panel,
        # harvested from nudge_ui.py's ``_outer_shell`` nested-frame "halo"
        # identity but drawn here as one QSS-bordered frame rather than a
        # triple-nested widget stack.
        shell = QFrame(self)
        shell.setObjectName("sineShell")
        root.addWidget(shell)
        body = QVBoxLayout(shell)
        body.setContentsMargins(26, 22, 26, 20)
        body.setSpacing(12)

        eyebrow = QHBoxLayout()
        eyebrow.setSpacing(10)
        self._orb = _StatusOrb(tokens.accent, shell)
        eyebrow.addWidget(self._orb, 0, Qt.AlignmentFlag.AlignVCenter)
        self._eyebrow_label = QLabel("MYELIN · SESSION ALERT", shell)
        self._eyebrow_label.setObjectName("eyebrow")
        self._eyebrow_label.setFont(_font(11, weight=QFont.Weight.DemiBold, spacing=1.4))
        eyebrow.addWidget(self._eyebrow_label, 0, Qt.AlignmentFlag.AlignVCenter)
        eyebrow.addStretch(1)
        self._alert_glyph = _AlertGlyph(tokens.accent, shell)
        self._alert_glyph.setVisible(self.is_protected_red)
        eyebrow.addWidget(self._alert_glyph, 0, Qt.AlignmentFlag.AlignVCenter)
        self._badge_label = QLabel(presentation.badge.replace(" ", "-"), shell)
        self._badge_label.setObjectName("badge")
        self._badge_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge_label.setFixedSize(78, 24)
        self._badge_label.setFont(_font(10.5, weight=QFont.Weight.Bold, spacing=1.0))
        eyebrow.addWidget(self._badge_label, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(eyebrow)

        body.addSpacing(6)

        self._headline = QLabel(presentation.headline, shell)
        self._headline.setObjectName("headline")
        self._headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._headline.setWordWrap(True)
        self._headline.setFont(_font(26, weight=QFont.Weight.ExtraBold))
        body.addWidget(self._headline)

        self._message = QLabel(presentation.message, shell)
        self._message.setObjectName("message")
        self._message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message.setWordWrap(True)
        self._message.setFont(_font(14))
        body.addWidget(self._message)

        resource = presentation.resource_title.strip()
        if resource:
            resource_font = _font(11, mono=True)
            metrics = QFontMetrics(resource_font)
            available_px = POPUP_WIDTH - 26 - 26 - 6
            elided = metrics.elidedText(
                f"RESOURCE: {resource}", Qt.TextElideMode.ElideMiddle, max(120, available_px)
            )
            self._resource = QLabel(elided, shell)
            self._resource.setObjectName("resource")
            self._resource.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._resource.setFont(resource_font)
            self._resource.setAccessibleDescription(resource)
            body.addWidget(self._resource)

        body.addStretch(1)

        self._status = QLabel("WAITING FOR FACTUAL DISPLAY ACKNOWLEDGEMENT", shell)
        self._status.setObjectName("status")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setWordWrap(True)
        self._status.setFont(_font(11, weight=QFont.Weight.DemiBold, mono=True))
        body.addWidget(self._status)

        if presentation.allowed_responses:
            buttons = QHBoxLayout()
            buttons.setSpacing(12)
            buttons.addStretch(1)
            for index, response in enumerate(presentation.allowed_responses):
                button = QPushButton(self._button_text(response), shell)
                button.setObjectName("primaryAction" if index == 0 else "secondaryAction")
                button.setFont(_font(12.5, weight=QFont.Weight.Bold, spacing=0.6))
                button.setMinimumHeight(46)
                button.setMinimumWidth(190)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                button.clicked.connect(
                    lambda _checked=False, selected=response: self._emit_action(selected)
                )
                self._buttons[response] = button
                buttons.addWidget(button)
            buttons.addStretch(1)
            body.addLayout(buttons)
        else:
            protected = QLabel("NO BUTTONS · AWAITING VERIFIED FOCUS RETURN", shell)
            protected.setObjectName("protectedNotice")
            protected.setAlignment(Qt.AlignmentFlag.AlignCenter)
            protected.setWordWrap(True)
            protected.setFont(_font(11.5, weight=QFont.Weight.Bold, mono=True, spacing=0.8))
            body.addWidget(protected)

        body.addSpacing(6)

        self._glow_strip = _GlowStrip(tokens.accent, shell)
        body.addWidget(self._glow_strip)

        self._countdown = QLabel("DISPLAY WINDOW --:--", shell)
        self._countdown.setObjectName("countdown")
        self._countdown.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._countdown.setFont(_font(10.5, mono=True))
        body.addWidget(self._countdown)

        intensity = presentation.weber_fechner.intensity_label.upper()
        footer_text = (
            "STUDY ACTIVE · SINE INTERVENTION"
            if presentation.study_mode
            else f"WEBER–FECHNER · {intensity}"
        )
        self._footer = QLabel(footer_text, shell)
        self._footer.setObjectName("footer")
        self._footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._footer.setFont(_font(9.5, mono=True, spacing=0.5))
        body.addWidget(self._footer)

    def _button_text(self, response: SineResponse) -> str:
        if response is SineResponse.RETURN_TO_FOCUS:
            if self.request.presentation.study_mode:
                return "RETURN TO STUDY"
            if self.request.stage is SineStage.SINE_2:
                return "I'M BACK NOW"
            return "I'M BACK"
        return {
            SineResponse.REQUEST_BREAK: "NEED A BREAK",
            SineResponse.THIS_IS_STUDY_MATERIAL: "THIS IS STUDY MATERIAL",
            SineResponse.CONTINUE_SINE: "CONTINUE SINE",
        }[response]

    def _apply_tokens(self) -> None:
        t = self._tokens
        hover_accent = QColor(t.accent).lighter(114).name()
        pressed_accent = QColor(t.accent).darker(114).name()
        self.setStyleSheet(
            f"""
            QWidget#sinePopup {{ background: {t.halo}; }}
            QFrame#sineShell {{
                background: {t.panel};
                border: 1.5px solid {t.accent};
                border-radius: 16px;
            }}
            QLabel#eyebrow {{ color: {t.muted}; background: transparent; }}
            QLabel#badge {{
                color: {t.accent};
                background: transparent;
                border: 1px solid {t.accent};
                border-radius: 12px;
            }}
            QLabel#headline {{ color: {t.accent}; background: transparent; }}
            QLabel#message {{ color: {t.text}; background: transparent; }}
            QLabel#resource {{ color: {t.muted}; background: transparent; }}
            QLabel#status {{ color: {t.accent}; background: transparent; }}
            QLabel#protectedNotice {{ color: {t.accent}; background: transparent; }}
            QLabel#countdown {{ color: {t.muted}; background: transparent; }}
            QLabel#footer {{ color: {t.footer}; background: transparent; }}
            QPushButton#primaryAction {{
                color: {t.button_text_on_accent};
                background: {t.accent};
                border: none;
                border-radius: 10px;
                padding: 6px 16px;
            }}
            QPushButton#primaryAction:hover {{ background: {hover_accent}; }}
            QPushButton#primaryAction:pressed {{ background: {pressed_accent}; }}
            QPushButton#primaryAction:focus {{ border: 2px solid {t.text}; }}
            QPushButton#primaryAction:disabled {{ color: {t.muted}; background: {t.accent_dim}; }}
            QPushButton#secondaryAction {{
                color: {t.accent};
                background: transparent;
                border: 1.5px solid {t.accent};
                border-radius: 10px;
                padding: 6px 16px;
            }}
            QPushButton#secondaryAction:hover {{ background: {t.halo}; }}
            QPushButton#secondaryAction:pressed {{ background: {t.accent_dim}; }}
            QPushButton#secondaryAction:focus {{ border: 2px solid {t.text}; }}
            QPushButton#secondaryAction:disabled {{ color: {t.muted}; border-color: {t.accent_dim}; }}
            """
        )

    # ------------------------------------------------------------------
    # Mechanical contract (unchanged behavior; design-layer hooks only)
    # ------------------------------------------------------------------

    def present(self) -> None:
        """Show the window and report SHOWN only after the visible HWND is certified."""

        try:
            self._place_window()
            self._play_entrance()
            self.raise_()
            self.activateWindow()
            QTimer.singleShot(0, self._report_shown_once)
        except Exception:
            self._report_failure_once("popup_display_failed")
            self.force_close("popup_display_failed")

    def _place_window(self) -> None:
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication is required for SINE presentation")
        point = (
            QCursor.pos()
            if self._origin_point is None
            else QPoint(int(self._origin_point[0]), int(self._origin_point[1]))
        )
        screen = QApplication.screenAt(point) or app.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = area.x() + max(12, area.width() - self.width() - 28)
        y = area.y() + max(12, (area.height() - self.height()) // 2)
        self.move(x, y)

    def _play_entrance(self) -> None:
        """Drift-and-fade entrance, harvested from ``sine_animator.slide_fade_in``.

        Purely cosmetic: it never gates the DISPLAYED acknowledgement, which
        still fires strictly from a certified post-``show()`` visibility
        check one event-loop turn later. That guarantee requires the popup
        to already be humanly visible at frame one, not merely
        Qt-``isVisible()``-true: opacity does not affect ``isVisible()``, so
        an earlier version of this method started the fade at 0.0 opacity
        and let ``QTimer.singleShot(0, ...)`` certify (and therefore anchor
        SINE/MIRL timing on) a frame the popup was still invisible in. The
        entrance now starts already visibly present (matching
        ``sine_animator.world_transition``'s own 0.88 floor) and only
        polishes the remaining approach to full opacity/position.
        """

        final_pos = self.pos()
        if self._reduced_motion:
            self.setWindowOpacity(1.0)
            self.show()
            return
        start_pos = final_pos + QPoint(0, ENTRANCE_DRIFT_PX)
        self.move(start_pos)
        self.setWindowOpacity(ENTRANCE_START_OPACITY)
        self.show()
        group = QParallelAnimationGroup(self)
        opacity = QPropertyAnimation(self, b"windowOpacity", group)
        opacity.setStartValue(ENTRANCE_START_OPACITY)
        opacity.setEndValue(1.0)
        position = QPropertyAnimation(self, b"pos", group)
        position.setStartValue(start_pos)
        position.setEndValue(final_pos)
        for animation in (opacity, position):
            animation.setDuration(ENTRANCE_DURATION_MS)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._entrance_animation = group
        group.start()

    def _start_orb_breathing(self) -> None:
        """Soft glow breathing on the status orb, harvested from
        ``sine_animator.soft_glow_breathing``."""

        orb = self._orb
        if orb is None or self._reduced_motion:
            return
        effect = QGraphicsDropShadowEffect(orb)
        effect.setOffset(0, 0)
        effect.setColor(QColor(self._tokens.accent))
        effect.setBlurRadius(10.0)
        orb.setGraphicsEffect(effect)
        group = QSequentialAnimationGroup(self)
        expand = QVariantAnimation(group)
        contract = QVariantAnimation(group)
        for leg, start, end in ((expand, 10.0, 22.0), (contract, 22.0, 10.0)):
            leg.setStartValue(start)
            leg.setEndValue(end)
            leg.setDuration(max(1, GLOW_BREATH_DURATION_MS // 2))
            leg.setEasingCurve(QEasingCurve.Type.InOutSine)
            group.addAnimation(leg)
        group.setLoopCount(-1)
        effect_ref = weakref.ref(effect)

        def tick(value: object) -> None:
            target = effect_ref()
            if target is not None:
                target.setBlurRadius(float(value))

        expand.valueChanged.connect(tick)
        contract.valueChanged.connect(tick)
        self._orb_animation = group
        group.start()

    def _stop_animations(self) -> None:
        if self._entrance_animation is not None:
            self._entrance_animation.stop()
            self._entrance_animation = None
        if self._orb_animation is not None:
            self._orb_animation.stop()
            self._orb_animation = None
        if self._orb is not None:
            self._orb.setGraphicsEffect(None)

    def _report_shown_once(self) -> None:
        if self._shown_reported or self._failure_reported or self._authority_close_allowed:
            return
        if not self.isVisible():
            self._report_failure_once("popup_not_visible_after_show")
            self.force_close("popup_not_visible_after_show")
            return
        try:
            hwnd = int(self.winId())
        except Exception:
            hwnd = 0
        if hwnd <= 0:
            self._report_failure_once("popup_hwnd_unavailable")
            self.force_close("popup_hwnd_unavailable")
            return
        self._native_hwnd = hwnd
        _register_hwnd(hwnd)
        self._shown_reported = True
        self._elapsed.start()
        self._countdown_timer.start()
        self._start_orb_breathing()
        self._status.setText("DISPLAYED · WAITING FOR SINE AUTHORITY")
        self._refresh_countdown()
        self.popup_shown.emit(self.request.request_id, time.monotonic_ns(), hwnd)

    def _refresh_countdown(self) -> None:
        if not self._shown_reported or not self._elapsed.isValid():
            return
        total_ms = max(0, round(float(self.request.visible_seconds) * 1000.0))
        remaining_ms = max(0, total_ms - self._elapsed.elapsed())
        remaining_seconds = remaining_ms / 1000.0
        minutes = int(remaining_seconds // 60)
        seconds = int(remaining_seconds % 60)
        self._countdown.setText(f"DISPLAY WINDOW: {minutes:02d}:{seconds:02d}")
        self._glow_strip.set_ratio(remaining_ms / total_ms if total_ms > 0 else 0.0)
        if remaining_ms <= 0:
            self._countdown_timer.stop()
            if self.is_protected_red:
                self._status.setText("DISPLAY WINDOW ELAPSED · RED REMAINS AUTHORITY-PROTECTED")
            else:
                self._status.setText("DISPLAY WINDOW ELAPSED · WAITING FOR SINE CLOSE COMMAND")

    def _emit_action(self, response: SineResponse) -> None:
        if self._action_pending or response not in self.request.presentation.allowed_responses:
            return
        self._action_pending = True
        self._status.setText(f"ACTION SENT: {response.value.upper()} · WAITING FOR ACCEPTANCE")
        self._sync_action_state()
        self.user_action.emit(
            self.request.request_id,
            response.value,
            time.monotonic_ns(),
        )

    def show_action_result(self, message: str, *, allow_retry: bool) -> None:
        """Present an authority result; only retryability changes button enabled state."""

        self._status.setText(str(message or "ACTION RESULT RECEIVED").upper())
        self._action_pending = not bool(allow_retry)
        if allow_retry:
            self._action_pending = False
        self._sync_action_state()

    def show_authority_status(self, message: str) -> None:
        self._status.setText(str(message or "WAITING FOR SINE AUTHORITY").upper())

    def _sync_action_state(self) -> None:
        for button in self._buttons.values():
            button.setEnabled(not self._action_pending)

    def close_from_authority(self, reason: str) -> bool:
        """Close only because SINE/controller supplied the exact request identity."""

        if self._authority_close_allowed:
            return False
        self._authority_close_allowed = True
        self._close_reason = str(reason or "sine_close_command")
        self._countdown_timer.stop()
        self.close()
        return True

    def force_close(self, reason: str) -> None:
        """Lifecycle/emergency-only UI teardown; never changes SINE truth itself.

        Closes immediately and synchronously -- no entrance/exit motion is
        started or awaited here, so an emergency can never be delayed by
        presentation animation.
        """

        self._authority_close_allowed = True
        self._close_reason = str(reason or "forced_close")
        self._countdown_timer.stop()
        self._stop_animations()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if not self._authority_close_allowed:
            event.ignore()
            self._status.setText("MANUAL CLOSE BLOCKED · SINE AUTHORITY OWNS THIS POPUP")
            return
        self._stop_animations()
        _unregister_hwnd(self._native_hwnd)
        if not self._closed_reported:
            self._closed_reported = True
            self.popup_closed.emit(
                self.request.request_id,
                self._close_reason or "authority_close",
                time.monotonic_ns(),
            )
        event.accept()
        super().closeEvent(event)

    def _report_failure_once(self, reason: str) -> None:
        if self._failure_reported or self._shown_reported:
            return
        self._failure_reported = True
        self.popup_failed.emit(
            self.request.request_id,
            str(reason or "popup_failed"),
            time.monotonic_ns(),
        )


class SinePopupPresenter(QObject):
    """Qt-main-thread presenter and lifecycle bridge for SINE popup windows."""

    # Qt transport types, not value types.  ``pyqtSignal(int)`` is a C++
    # 32-bit int: a ``time.monotonic_ns()`` value (~50 bits) is silently
    # truncated to its low 32 bits and can arrive negative, after which
    # SINE._valid_event_time can never accept it.  ``object`` hands the
    # Python int across unchanged; callers coerce with int() on the far side.
    popup_shown = pyqtSignal(str, object, object)
    popup_failed = pyqtSignal(str, str, object)
    user_action = pyqtSignal(str, str, object)
    popup_closed = pyqtSignal(str, str, object)
    protected_red_visibility_changed = pyqtSignal(bool)

    _present_queued = pyqtSignal(object)
    _fact_queued = pyqtSignal(object)
    _close_queued = pyqtSignal(str, str)
    _emergency_close_queued = pyqtSignal(str)

    def __init__(
        self,
        *,
        owner: QWidget | None = None,
        reduced_motion: bool | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._owner_ref = weakref.ref(owner) if owner is not None else lambda: None
        # An explicit True/False always wins; leaving it unset respects the
        # OS/user reduced-motion preference (harvested default resolution
        # from sine_animator.reduced_motion_requested()) instead of silently
        # ignoring it.
        self._reduced_motion = (
            reduced_motion_requested() if reduced_motion is None else bool(reduced_motion)
        )
        self._windows: dict[str, SinePopupWindow] = {}
        self._accepting_requests = True

        self._present_queued.connect(self._present_on_gui_thread, Qt.ConnectionType.QueuedConnection)
        self._fact_queued.connect(self._apply_fact_on_gui_thread, Qt.ConnectionType.QueuedConnection)
        self._close_queued.connect(self._close_on_gui_thread, Qt.ConnectionType.QueuedConnection)
        self._emergency_close_queued.connect(
            self._emergency_close_on_gui_thread,
            Qt.ConnectionType.QueuedConnection,
        )

    def present(self, request: SinePopupRequest) -> None:
        if self._on_own_thread():
            self._present_on_gui_thread(request)
        else:
            self._present_queued.emit(request)

    def apply_fact(self, fact: SineFact) -> None:
        if self._on_own_thread():
            self._apply_fact_on_gui_thread(fact)
        else:
            self._fact_queued.emit(fact)

    def close_popup(self, request_id: str, reason: str) -> None:
        if self._on_own_thread():
            self._close_on_gui_thread(request_id, reason)
        else:
            self._close_queued.emit(str(request_id), str(reason))

    def emergency_close_all(self, reason: str = "emergency") -> None:
        if self._on_own_thread():
            self._emergency_close_on_gui_thread(reason)
        else:
            self._emergency_close_queued.emit(str(reason))

    @pyqtSlot(object)
    def _present_on_gui_thread(self, request: object) -> None:
        if not self._accepting_requests:
            self._emit_request_failure(request, "presenter_shutdown")
            return
        if not isinstance(request, SinePopupRequest):
            self._emit_request_failure(request, "invalid_popup_request")
            return
        if request.request_id in self._windows:
            return

        protected = next(
            (
                window
                for window in self._windows.values()
                if window.is_protected_red and window.isVisible()
            ),
            None,
        )
        if protected is not None:
            self.popup_failed.emit(
                request.request_id,
                "protected_red_surface_already_visible",
                time.monotonic_ns(),
            )
            return

        # Only the SINE authority decides that a previous occurrence has ended.
        # A later SINE request itself is an authority fact, so replacing a prior
        # non-Red surface here is presentation cleanup, not a state transition.
        for window in list(self._windows.values()):
            if not window.is_protected_red:
                window.close_from_authority("superseded_by_new_sine_request")

        try:
            window = SinePopupWindow(
                request,
                owner=self._owner_ref(),
                reduced_motion=self._reduced_motion,
            )
        except Exception:
            self.popup_failed.emit(
                request.request_id,
                "popup_construction_failed",
                time.monotonic_ns(),
            )
            return

        self._windows[request.request_id] = window
        window.popup_shown.connect(self._on_popup_shown)
        window.popup_failed.connect(self._on_popup_failed)
        window.user_action.connect(self.user_action)
        window.popup_closed.connect(self._on_popup_closed)
        window.destroyed.connect(
            lambda _object=None, request_id=request.request_id: self._remove_window(request_id)
        )
        window.present()

    @pyqtSlot(object)
    def _apply_fact_on_gui_thread(self, fact: object) -> None:
        if not isinstance(fact, SineFact):
            return
        if fact.kind == "SINE_POPUP_REQUESTED" and fact.popup is not None:
            self._present_on_gui_thread(fact.popup)
            return
        if fact.kind == "SINE_POPUP_CLOSE_REQUESTED":
            self._close_on_gui_thread(
                fact.popup_request_id,
                fact.reason or "sine_close_command",
            )
            return
        if fact.kind == "SINE_STUDY_MATERIAL_RESULT":
            window = self._windows.get(fact.popup_request_id)
            if window is not None:
                granted = fact.response == "granted"
                if not granted:
                    reason = fact.reason.replace("_", " ").strip()
                    message = "STUDY MATERIAL ALLOWANCE NOT APPLIED"
                    if reason:
                        message = f"{message} · {reason}"
                    window.show_action_result(message, allow_retry=True)
            return
        if fact.kind == "SINE_PROTECTED_RED_AWAITING_RECOVERY":
            window = self._windows.get(fact.popup_request_id)
            if window is not None:
                window.show_authority_status("Awaiting verified focus return")
            return
        if fact.kind == "SINE_EMERGENCY_STOPPED":
            self._emergency_close_on_gui_thread("emergency")

    @pyqtSlot(str, str)
    def _close_on_gui_thread(self, request_id: str, reason: str) -> None:
        window = self._windows.get(str(request_id or ""))
        if window is not None:
            window.close_from_authority(reason)

    @pyqtSlot(str)
    def _emergency_close_on_gui_thread(self, reason: str) -> None:
        self._accepting_requests = False
        for window in list(self._windows.values()):
            window.force_close(reason)

    @pyqtSlot(str, object, object)
    def _on_popup_shown(self, request_id: str, occurred_ns: int, hwnd: int) -> None:
        window = self._windows.get(request_id)
        if window is None:
            return
        self.popup_shown.emit(request_id, occurred_ns, hwnd)
        if window.is_protected_red:
            self.protected_red_visibility_changed.emit(True)

    @pyqtSlot(str, str, object)
    def _on_popup_failed(self, request_id: str, reason: str, occurred_ns: int) -> None:
        self.popup_failed.emit(request_id, reason, occurred_ns)
        self._remove_window(request_id)

    @pyqtSlot(str, str, object)
    def _on_popup_closed(self, request_id: str, reason: str, occurred_ns: int) -> None:
        window = self._windows.get(request_id)
        was_red = bool(window is not None and window.is_protected_red)
        self.popup_closed.emit(request_id, reason, occurred_ns)
        self._remove_window(request_id)
        if was_red:
            self.protected_red_visibility_changed.emit(False)

    def _remove_window(self, request_id: str) -> None:
        window = self._windows.pop(str(request_id or ""), None)
        if window is not None:
            _unregister_hwnd(window.native_hwnd)

    def _emit_request_failure(self, request: object, reason: str) -> None:
        request_id = str(getattr(request, "request_id", "") or "")
        if request_id:
            self.popup_failed.emit(request_id, reason, time.monotonic_ns())

    def _on_own_thread(self) -> bool:
        return QThread.currentThread() == self.thread()

    def active_request_ids(self) -> tuple[str, ...]:
        return tuple(self._windows)

    def protected_red_visible(self) -> bool:
        return any(
            window.is_protected_red and window.isVisible()
            for window in self._windows.values()
        )

    def shutdown(self) -> None:
        """Stop accepting popups and tear down UI without changing SINE truth."""

        self.emergency_close_all("presenter_shutdown")


__all__ = (
    "POPUP_SCHEMA_VERSION",
    "PopupPalette",
    "SinePopupPresenter",
    "SinePopupWindow",
    "active_popup_hwnds",
    "is_sine_popup_hwnd",
    "reduced_motion_requested",
)
