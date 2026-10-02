"""NEW COSINE popup presentation for MYELIN (Phase 1H).

This file draws the four NEW COSINE surfaces: the intention gate, the branch
aware duration entry, the break acknowledgement and the final baseless
callback.  It emits ``CosineCommand`` objects and displays delivery status.
It never changes COSINE state, detects a platform, writes an event, reads the
database or decides an outcome.

Critical acknowledgement rule
-----------------------------
A popup closes only when ``CosineRuntime.submit_command`` returns an accepted
result for the exact generation/request, or when the runtime emits an
authoritative close effect.  Queue failure, stale identity or a durability
failure leaves the popup open with a retry message.

Timing authority rule
---------------------
There is no behavioural QTimer in this file.  The 5 minute initial gate, the
5 minute return intent window, the 10-200 minute break deadline, the 3 second
final callback hide, the 10 second verification and the 60 second closure all
belong to ``CosineRuntime``.  The only QTimers here drive a cosmetic mascot
blink and a short cosmetic delay after an already-accepted command.

Branch and duration facts
-------------------------
Duration copy comes from ``effect.presentation_variant`` and the acknowledged
break length comes from ``effect.duration_minutes``.  Nothing here parses a
message, inspects runtime state or infers a branch from time.
"""

from __future__ import annotations

from CONTROL_STATION.command_delivery import PendingCommand, on_popup_reply

import random
import sys
import threading
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from COSINE.cosine import (
    CommandKind,
    CommandResult,
    CosineChoice,
    CosineCommand,
    CosineEffect,
    EffectKind,
    PLATFORM_LABELS,
)


POPUP_SCHEMA_VERSION: Final = "myelin-cosine-popup-v2-new-face"

#: The NEW COSINE show surfaces this presentation layer owns.
SHOW_EFFECTS: Final = frozenset(
    {
        EffectKind.SHOW_INTENT_GATE,
        EffectKind.SHOW_DURATION_ENTRY,
        EffectKind.SHOW_BREAK_ACK,
        EffectKind.SHOW_FINAL_CALLBACK,
    }
)

#: Runtime-authorised close / hide / restore effects.
CONTROL_EFFECTS: Final = frozenset(
    {
        EffectKind.CLOSE_INTENT_GATE,
        EffectKind.CLOSE_DURATION_ENTRY,
        EffectKind.CLOSE_BREAK_ACK,
        EffectKind.HIDE_FINAL_CALLBACK,
        EffectKind.RESTORE_FINAL_CALLBACK,
        EffectKind.CLOSE_PRESENTATION,
    }
)

#: Commands that are a factual statement that a surface became visible.
DISPLAY_COMMANDS: Final = frozenset(
    {
        CommandKind.INTENT_GATE_DISPLAYED,
        CommandKind.BREAK_ACK_DISPLAYED,
        CommandKind.FINAL_CALLBACK_DISPLAYED,
    }
)

DIRECT_BREAK: Final = "DIRECT_BREAK"
FAILED_RETURN_INTENTION: Final = "FAILED_RETURN_INTENTION"


@dataclass(frozen=True, slots=True)
class _PlatformSkin:
    """The two image filenames one certified platform contributes.

    Presentation metadata only.  This is NOT a platform map: it decides no
    identity, matches no host, process, URL or title, and is only ever reached
    with a ``platform_key`` COSINE has already certified.
    """

    logo_filename: str
    background_filename: str


#: Phase 1J.  Certified platform key -> the images it lends Popup 1.
#:
#: Keys mirror the runtime's certified platforms exactly; a key that is not
#: here simply gets the existing generic surface.  Nothing is copied from
#: ``COSINE/cosine.py`` except the key spelling those platforms already own.
PLATFORM_SKINS: Final = {
    "netflix": _PlatformSkin(
        "netflix_logo.png", "cosine_background_netflix.jpg"
    ),
    "prime_video": _PlatformSkin(
        "prime_video_logo.png", "cosine_background_prime_video.jpg"
    ),
    "jiohotstar": _PlatformSkin(
        "jiohotstar_logo.png", "cosine_background_jiohotstar.jpg"
    ),
    "disney_plus": _PlatformSkin(
        "disney_plus_logo.png", "cosine_background_disney_plus.jpg"
    ),
    "hulu": _PlatformSkin(
        "hulu_logo.png", "cosine_background_hulu.jpg"
    ),
    "hbo_max": _PlatformSkin(
        "hbo_max_logo.png", "cosine_background_hbo_max.jpg"
    ),
    "apple_tv_plus": _PlatformSkin(
        "apple_tv_plus_logo.png", "cosine_background_apple_tv_plus.jpg"
    ),
    "paramount_plus": _PlatformSkin(
        "paramount_plus_logo.png", "cosine_background_paramount_plus.jpg"
    ),
}

#: Visual box the platform logo is fitted into, never stretched beyond.
LOGO_MAX_WIDTH: Final = 300
LOGO_MAX_HEIGHT: Final = 90


def _cosine_asset_path(filename: str) -> Path:
    """Resolve one bundled COSINE image beside this package.

    Static internal filenames only.  No user input, no database, no Monitor,
    no Browser and no Control Station participates in finding an image.
    """

    return (
        Path(__file__).resolve().parents[1]
        / "ASSETS"
        / "images"
        / "Cosine"
        / filename
    )


def _skin_for_platform(platform_key: object) -> _PlatformSkin | None:
    """Return the skin for an ALREADY-CERTIFIED platform key, or None.

    The key is never parsed, guessed or repaired -- an unknown or empty key
    simply has no skin, which is the generic-popup path.
    """

    return PLATFORM_SKINS.get(str(platform_key or "").strip())


@dataclass(frozen=True, slots=True)
class PopupRequest:
    effect: CosineEffect
    submit_command: Callable[[CosineCommand], CommandResult]

    def __post_init__(self) -> None:
        if self.effect.kind not in SHOW_EFFECTS:
            raise ValueError("PopupRequest requires a NEW COSINE show effect")
        if not callable(self.submit_command):
            raise TypeError("submit_command must be callable")


try:
    from PyQt6.QtCore import (
        QObject,
        QPoint,
        QPointF,
        QPropertyAnimation,
        QRectF,
        Qt,
        QTimer,
        pyqtProperty,
        pyqtSignal,
        pyqtSlot,
    )
    from PyQt6.QtGui import (
        QColor,
        QCloseEvent,
        QCursor,
        QFont,
        QGuiApplication,
        QIntValidator,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
    )
    from PyQt6.QtWidgets import (
        QApplication,
        QDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as _qt_failure:
    _QT_IMPORT_DETAIL = str(_qt_failure)

    class CosinePopupDispatcher:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError(
                f"COSINE popup presentation requires PyQt6: {_QT_IMPORT_DETAIL}"
            )

    def install_cosine_dispatcher(*args, **kwargs):
        raise RuntimeError(
            f"COSINE popup presentation requires PyQt6: {_QT_IMPORT_DETAIL}"
        )

    def dispatch_cosine_effect(*args, **kwargs) -> bool:
        return False

    def shutdown_cosine_dispatcher() -> None:
        return None

else:
    from UI_THEMES.theme import DEFAULT_THEME, ThemeTokens

    def _resolve_tokens(owner: object | None) -> ThemeTokens:
        """Read the current MYELIN body tokens from the launcher owner."""

        controller = getattr(owner, "theme", None)
        tokens = getattr(controller, "current_theme", None)
        return tokens if isinstance(tokens, ThemeTokens) else DEFAULT_THEME

    def _reduced_motion(owner: object | None) -> bool:
        """Honour the stored reduced-motion preference when it is readable.

        ``ThemeController`` exposes no public getter, so this is a defensive
        read-only probe that degrades to "animation allowed" rather than a
        modification of the protected theme authority.
        """

        controller = getattr(owner, "theme", None)
        try:
            return bool(getattr(controller, "_reduced_motion", False))
        except Exception:
            return False

    def _font(
        size: float,
        *,
        weight: QFont.Weight = QFont.Weight.Normal,
        mono: bool = False,
        spacing: float = 0.0,
    ) -> QFont:
        """The MYELIN popup type ramp, matching the SINE surface exactly."""

        font = QFont("Consolas" if mono else "Segoe UI")
        font.setPixelSize(max(1, round(size)))
        font.setWeight(weight)
        if spacing:
            font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, float(spacing))
        return font

    def _on_accent(t: ThemeTokens) -> str:
        """Readable text colour on top of the body's accent fill."""

        colour = QColor(t.cyan)
        luminance = (
            0.2126 * colour.redF() + 0.7152 * colour.greenF() + 0.0722 * colour.blueF()
        )
        return "#0B0F19" if luminance > 0.55 else "#FFFFFF"

    def _halo(t: ThemeTokens) -> str:
        """The soft ring drawn behind the card."""

        accent = QColor(t.cyan)
        base = QColor(t.window_background)
        return QColor(
            (accent.red() * 38 + base.red() * 217) // 255,
            (accent.green() * 38 + base.green() * 217) // 255,
            (accent.blue() * 38 + base.blue() * 217) // 255,
        ).name()

    def _stylesheet(t: ThemeTokens) -> str:
        on_accent = _on_accent(t)
        hover_accent = QColor(t.cyan).lighter(114).name()
        pressed_accent = QColor(t.cyan).darker(114).name()
        return f"""
        QDialog#cosinePopup {{ background: {_halo(t)}; }}
        QFrame#cosineCard {{
            background: {t.surface_soft};
            border: 1.5px solid {t.cyan};
            border-radius: 16px;
        }}
        QLabel {{ background: transparent; color: {t.text_primary}; }}
        QLabel#cosineEyebrow {{ color: {t.muted}; }}
        QLabel#cosineBadge {{
            color: {t.cyan};
            border: 1px solid {t.cyan};
            border-radius: 13px;
            padding: 5px 18px;
        }}
        QLabel#cosineHeadline {{ color: {t.cyan}; }}
        QLabel#cosineMessage {{ color: {t.text_primary}; }}
        QLabel#cosineContext {{ color: {t.muted}; }}
        QLabel#cosineStatus {{ color: {t.cyan}; }}
        QLabel#cosineMinutes {{ color: {t.cyan}; }}
        QLabel#cosineUnit {{ color: {t.muted}; }}
        QLabel#cosineFooter {{ color: {t.muted}; }}
        QLineEdit#cosineDurationField {{
            background: {t.surface_2};
            border: 1.5px solid {t.cyan};
            border-radius: 10px;
            color: {t.text_primary};
            padding: 10px 6px;
        }}
        QLineEdit#cosineDurationField:focus {{ border: 2px solid {t.cyan}; }}
        QLineEdit#cosineDurationField:disabled {{
            border: 1.5px solid {t.border}; color: {t.muted};
        }}
        QPushButton#cosinePrimary {{
            color: {on_accent};
            background: {t.cyan};
            border: none;
            border-radius: 10px;
            padding: 12px 22px;
        }}
        QPushButton#cosinePrimary:hover {{ background: {hover_accent}; }}
        QPushButton#cosinePrimary:pressed {{ background: {pressed_accent}; }}
        QPushButton#cosinePrimary:focus {{ border: 2px solid {t.text_primary}; }}
        QPushButton#cosinePrimary:disabled {{ color: {t.muted}; background: {t.cyan_dim}; }}
        QPushButton#cosineSecondary {{
            color: {t.cyan};
            background: transparent;
            border: 1.5px solid {t.cyan};
            border-radius: 10px;
            padding: 12px 22px;
        }}
        QPushButton#cosineSecondary:hover {{ background: {t.surface_2}; }}
        QPushButton#cosineSecondary:pressed {{ background: {t.cyan_dim}; }}
        QPushButton#cosineSecondary:focus {{ border: 2px solid {t.text_primary}; }}
        QPushButton#cosineSecondary:disabled {{
            color: {t.muted}; border-color: {t.border};
        }}
        QPushButton#cosineRetry {{
            color: {t.cyan};
            background: transparent;
            border: 1px dashed {t.cyan_dim};
            border-radius: 8px;
            padding: 6px 14px;
        }}
        """

    def _load_skin_pixmap(filename: str) -> QPixmap | None:
        """Load one presentation asset, or return None if it is unusable.

        Every failure mode collapses to None -- absent file, unreadable bytes,
        unsupported or corrupt data, a null pixmap, or any OS error.  The
        caller then uses the existing generic surface.  A decoration problem
        must never reach the dispatcher or the intention gate.
        """

        try:
            path = _cosine_asset_path(filename)
            if not path.is_file():
                return None
            pixmap = QPixmap(str(path))
        except Exception:  # noqa: BLE001 -- decoration must never raise
            return None
        return None if pixmap.isNull() else pixmap

    class _PlatformBackdrop(QFrame):
        """The intention card, painting one certified platform image inside it.

        Presentation only: no state, no timer, no platform opinion.  It is
        handed an already-loaded pixmap chosen from the factual platform key
        and paints it inside the existing card, under a dark overlay that keeps
        the COSINE headline, delivery state and buttons readable.

        It IS the card rather than an extra layer above it, so it adds no new
        focusable, clickable or accessible widget to the popup -- the image
        cannot intercept input because it is paint, not a widget.
        """

        #: ~78% dark.  Presentation styling only; no state is read from colour.
        OVERLAY_ALPHA: Final = 200

        def __init__(self, background: QPixmap, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._background = background
            self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        def paintEvent(self, event) -> None:  # noqa: N802
            # The QSS card paints first (surface, 1.5px cyan border, 16px
            # radius).  The image is then clipped just inside that border, so
            # MYELIN's cyan edge and rounded identity are never covered.
            super().paintEvent(event)
            if self._background.isNull():
                return
            painter = QPainter(self)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setRenderHint(
                    QPainter.RenderHint.SmoothPixmapTransform, True
                )
                clip = QPainterPath()
                clip.addRoundedRect(
                    QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5), 14.5, 14.5
                )
                painter.setClipPath(clip)
                scaled = self._background.scaled(
                    self.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                # Centre-crop.  The image is expanded to cover and then
                # centred; it is never stretched to the card's aspect ratio.
                painter.drawPixmap(
                    int(round((self.width() - scaled.width()) / 2)),
                    int(round((self.height() - scaled.height()) / 2)),
                    scaled,
                )
                painter.fillRect(self.rect(), QColor(4, 8, 14, self.OVERLAY_ALPHA))
            finally:
                painter.end()

    def _window_center(hwnd: int) -> QPoint | None:
        """One-shot GetWindowRect read used for popup placement only.

        This is never an identity, ownership or platform authority and it
        never becomes a polling loop.
        """

        if hwnd <= 0 or not sys.platform.startswith("win"):
            return None
        try:
            import ctypes
            from ctypes import wintypes

            rect = wintypes.RECT()
            user32 = ctypes.windll.user32
            if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                return None
            if rect.right <= rect.left or rect.bottom <= rect.top:
                return None
            return QPoint((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        except Exception:
            return None

    class _StatusOrb(QWidget):
        """The small MYELIN status marker, matching the SINE surface."""

        def __init__(self, accent: str, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self._accent = accent
            self.setFixedSize(10, 10)
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            self.setAccessibleName("COSINE status indicator")

        def paintEvent(self, event) -> None:  # noqa: N802
            del event
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._accent))
            painter.drawEllipse(QRectF(0.0, 0.0, 10.0, 10.0))

    class CosineMascot(QWidget):
        """Presentation-only COSINE companion painted from body tokens."""

        def __init__(
            self,
            tokens: ThemeTokens,
            parent: QWidget | None = None,
            *,
            reduced_motion: bool = False,
        ) -> None:
            super().__init__(parent)
            self.setObjectName("cosineMascot")
            self.setFixedSize(164, 140)
            self.setAccessibleName("COSINE companion")
            self._tokens = tokens
            self._reduced_motion = bool(reduced_motion)
            self._eye_close = 0.0
            self._warmth = 0.0
            self._blink_timer = QTimer(self)
            self._blink_timer.setSingleShot(True)
            self._blink_timer.timeout.connect(self._start_blink)
            self._blink_animation = QPropertyAnimation(self, b"eyeClose", self)
            self._blink_animation.setDuration(260)
            self._blink_animation.setStartValue(0.0)
            self._blink_animation.setKeyValueAt(0.5, 1.0)
            self._blink_animation.setEndValue(0.0)
            self._blink_animation.finished.connect(self._schedule_blink)
            self._ack = QPropertyAnimation(self, b"warmth", self)
            self._ack.setDuration(420)
            self._ack.setStartValue(0.0)
            self._ack.setKeyValueAt(0.5, 1.0)
            self._ack.setEndValue(0.0)
            if not self._reduced_motion:
                self._schedule_blink()

        def acknowledge(self) -> None:
            if self._reduced_motion:
                return
            self._ack.stop()
            self._ack.start()

        def stop(self) -> None:
            self._blink_timer.stop()
            self._blink_animation.stop()
            self._ack.stop()

        def _schedule_blink(self) -> None:
            if self._reduced_motion:
                return
            self._blink_timer.start(random.randint(2500, 5200))

        def _start_blink(self) -> None:
            self._blink_animation.stop()
            self._blink_animation.start()

        def _get_eye_close(self) -> float:
            return self._eye_close

        def _set_eye_close(self, value: float) -> None:
            self._eye_close = float(value)
            self.update()

        eyeClose = pyqtProperty(float, _get_eye_close, _set_eye_close)

        def _get_warmth(self) -> float:
            return self._warmth

        def _set_warmth(self, value: float) -> None:
            self._warmth = float(value)
            self.update()

        warmth = pyqtProperty(float, _get_warmth, _set_warmth)

        def paintEvent(self, event) -> None:  # noqa: N802
            del event
            t = self._tokens
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            cx = self.width() / 2
            cy = self.height() / 2 + 3
            center = QPointF(cx, cy)
            glow = QColor(t.cyan)
            glow.setAlpha(52 + int(self._warmth * 90))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(center, 62, 55)
            painter.setBrush(QColor(t.surface_2))
            painter.setPen(QPen(QColor(t.cyan), 2.5))
            painter.drawEllipse(center, 54, 48)
            eye_height = max(1.3, 10 * (1.0 - self._eye_close))
            painter.setBrush(QColor(t.text_primary))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(cx - 27, cy - 12, 15, eye_height))
            painter.drawEllipse(QRectF(cx + 12, cy - 12, 15, eye_height))
            painter.setPen(QPen(QColor(t.cyan), 2.4))
            painter.drawArc(QRectF(cx - 17, cy + 3, 34, 20), 205 * 16, 130 * 16)

    class _CosineDialog(QDialog):
        """Shared protected delivery shell for every NEW COSINE surface."""

        CARD_WIDTH = 780
        BADGE = ""
        FOOTER = "COSINE INTERVENTION"
        ACCESSIBLE = "MYELIN COSINE intervention"

        def __init__(
            self,
            request: PopupRequest,
            tokens: ThemeTokens,
            parent=None,
            *,
            reduced_motion: bool = False,
        ) -> None:
            super().__init__(parent)
            self._request = request
            self._tokens = tokens
            self._reduced_motion = bool(reduced_motion)
            self._delivery_in_progress = False
            self._accepted_close = False
            self._display_acknowledged = False
            # True only while the runtime itself has hidden this surface.
            self._runtime_hidden = False
            self._drag_origin: QPoint | None = None
            self._retry_command: (
                tuple[CommandKind, CosineChoice | None, int | None, bool] | None
            ) = None
            self.setModal(False)
            self.setWindowFlags(
                Qt.WindowType.Dialog
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool
            )
            self.setObjectName("cosinePopup")
            self.setWindowTitle("MYELIN COSINE")
            self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.setAccessibleName(self.ACCESSIBLE)
            self.setStyleSheet(_stylesheet(tokens))
            self.setFixedWidth(self.CARD_WIDTH)

        # ---------------------------------------------------------------- card

        def _create_card(self) -> QFrame:
            """Return this popup's card frame.  Presentation-only seam.

            Every popup family receives exactly this plain frame.  Only the
            Phase-1J intention gate overrides it, and only to paint a platform
            image inside the same card; no behaviour differs either way.
            """

            return QFrame(self)

        def _build_card(self) -> QVBoxLayout:
            outer = QVBoxLayout(self)
            # The outer dialog is the soft halo; the inner frame is the card.
            outer.setContentsMargins(8, 8, 8, 8)
            self.card = self._create_card()
            self.card.setObjectName("cosineCard")
            outer.addWidget(self.card)
            body = QVBoxLayout(self.card)
            body.setContentsMargins(30, 22, 30, 20)
            body.setSpacing(14)

            header = QHBoxLayout()
            header.setSpacing(10)
            self.orb = _StatusOrb(self._tokens.cyan, self.card)
            header.addWidget(self.orb, 0, Qt.AlignmentFlag.AlignVCenter)
            eyebrow = QLabel("MYELIN · COSINE", self.card)
            eyebrow.setObjectName("cosineEyebrow")
            eyebrow.setFont(_font(13, weight=QFont.Weight.DemiBold, spacing=1.4))
            header.addWidget(eyebrow, 0, Qt.AlignmentFlag.AlignVCenter)
            header.addStretch(1)
            if self.BADGE:
                badge = QLabel(self.BADGE, self.card)
                badge.setObjectName("cosineBadge")
                badge.setFont(_font(12, weight=QFont.Weight.Bold, spacing=1.2))
                header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
            body.addLayout(header)
            return body

        def _add_headline(self, layout: QVBoxLayout, text: str) -> QLabel:
            label = QLabel(text, self.card)
            label.setObjectName("cosineHeadline")
            label.setFont(_font(27, weight=QFont.Weight.Bold, spacing=0.6))
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            return label

        def _add_message(self, layout: QVBoxLayout, text: str) -> QLabel:
            label = QLabel(text, self.card)
            label.setObjectName("cosineMessage")
            label.setFont(_font(15))
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            return label

        def _add_context(self, layout: QVBoxLayout, text: str) -> QLabel:
            label = QLabel(text, self.card)
            label.setObjectName("cosineContext")
            label.setFont(_font(13, mono=True))
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label)
            return label

        def _add_mascot(self, layout: QVBoxLayout) -> None:
            self.mascot = CosineMascot(
                self._tokens, self.card, reduced_motion=self._reduced_motion
            )
            layout.addWidget(self.mascot, 0, Qt.AlignmentFlag.AlignHCenter)

        def _add_delivery_state(self, layout: QVBoxLayout, *, retry: bool) -> None:
            self.delivery_label = QLabel("AWAITING DISPLAY ACKNOWLEDGEMENT", self.card)
            self.delivery_label.setObjectName("cosineStatus")
            self.delivery_label.setFont(
                _font(12, weight=QFont.Weight.DemiBold, mono=True, spacing=1.2)
            )
            self.delivery_label.setWordWrap(True)
            self.delivery_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self.delivery_label)
            if retry:
                self.retry_button = QPushButton("RETRY DELIVERY", self.card)
                self.retry_button.setObjectName("cosineRetry")
                self.retry_button.setFont(
                    _font(11, weight=QFont.Weight.DemiBold, spacing=1.0)
                )
                self.retry_button.setVisible(False)
                self.retry_button.clicked.connect(self._retry_delivery)
                layout.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignHCenter)

        def _add_footer(self, layout: QVBoxLayout) -> None:
            # No progress bar and no countdown: COSINE timing belongs to the
            # backend, so this surface carries no visible clock at all.
            footer = QLabel(self.FOOTER, self.card)
            footer.setObjectName("cosineFooter")
            footer.setFont(_font(11, mono=True, spacing=1.0))
            footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(footer)

        def _button_row(self, layout: QVBoxLayout, buttons) -> None:
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addStretch(1)
            for button in buttons:
                button.setFont(_font(14, weight=QFont.Weight.Bold, spacing=0.8))
                button.setMinimumWidth(230 if len(buttons) > 1 else 260)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                row.addWidget(button)
            row.addStretch(1)
            layout.addLayout(row)

        def _platform_context(self) -> str:
            effect = self._request.effect
            if not effect.platform_key:
                return ""
            label = PLATFORM_LABELS.get(
                effect.platform_key, effect.platform_key.replace("_", " ").title()
            )
            if effect.content_title:
                return f"NOW PLAYING: {label} · {effect.content_title}"
            return f"NOW PLAYING: {label}"

        # ------------------------------------------------------------ delivery

        def _deliver(
            self,
            kind: CommandKind,
            *,
            choice: CosineChoice | None = None,
            duration_minutes: int | None = None,
            close_after_acceptance: bool,
        ) -> bool:
            if self._delivery_in_progress:
                return False
            self._retry_command = (
                kind,
                choice,
                duration_minutes,
                close_after_acceptance,
            )
            self._delivery_in_progress = True
            if hasattr(self, "retry_button"):
                self.retry_button.setVisible(False)
            self._set_buttons_enabled(False)
            self.delivery_label.setText("DELIVERING COMMAND")
            command = CosineCommand(
                kind=kind,
                generation=self._request.effect.generation,
                request_id=self._request.effect.request_id,
                choice=choice,
                occurred_monotonic_ns=time.monotonic_ns(),
                duration_minutes=duration_minutes,
            )
            try:
                result = self._request.submit_command(command)
            except Exception as exc:
                result = None
                detail = " ".join(str(exc).split())[:180]
            else:
                if isinstance(result, PendingCommand):
                    def completed(reply):
                        try:
                            value = reply.result()
                            message = getattr(value, "message", "Invalid command result")
                        except RuntimeError as error:
                            value, message = None, str(error)
                        self._complete_delivery(kind, close_after_acceptance, value, message)
                    on_popup_reply(result, self, completed)
                    return not bool(result.error)
                detail = (
                    result.message
                    if isinstance(result, CommandResult)
                    else "Invalid command result"
                )
            return self._complete_delivery(kind, close_after_acceptance, result, detail)

        def _complete_delivery(self, kind, close_after_acceptance, result, detail):
            """Apply only an actual backend reply, on the GUI thread."""
            self._delivery_in_progress = False
            if not isinstance(result, CommandResult) or not result.accepted:
                self.delivery_label.setText(
                    f"NOT ACCEPTED · {detail or 'Please retry'}".upper()
                )
                # A failed DISPLAYED command must be retried before choices
                # become usable.  This prevents a confusing invalid action.
                self._set_buttons_enabled(kind not in DISPLAY_COMMANDS)
                if hasattr(self, "retry_button"):
                    self.retry_button.setVisible(True)
                return False
            self.delivery_label.setText("COMMAND ACCEPTED")
            if hasattr(self, "mascot"):
                self.mascot.acknowledge()
            if kind in DISPLAY_COMMANDS:
                self._display_acknowledged = True
            self._delivery_accepted(kind)
            if close_after_acceptance and result.close_popup:
                self._accepted_close = True
                # Cosmetic only: lets the accepted state be seen before an
                # already-authorised close.  It is not behavioural time.
                QTimer.singleShot(280, self.accept)
            else:
                self._set_buttons_enabled(True)
            return True

        def _retry_delivery(self) -> None:
            if self._retry_command is None:
                return
            kind, choice, minutes, close_after = self._retry_command
            self._deliver(
                kind,
                choice=choice,
                duration_minutes=minutes,
                close_after_acceptance=close_after,
            )

        def _delivery_accepted(self, kind: CommandKind) -> None:
            del kind

        def _display_command(self) -> CommandKind | None:
            """The factual DISPLAYED command for this surface, if any."""

            return None

        def submit_display_if_pending(self) -> None:
            """Deliver or retry the factual DISPLAYED command on this window."""

            kind = self._display_command()
            if kind is None or self._display_acknowledged:
                return
            self._deliver(kind, close_after_acceptance=False)

        def showEvent(self, event) -> None:  # noqa: N802
            super().showEvent(event)
            self.submit_display_if_pending()

        # ------------------------------------------------------- runtime close

        def force_close_from_runtime(self) -> None:
            """Close only after an authoritative runtime CLOSE effect."""

            self._accepted_close = True
            self.accept()

        @property
        def runtime_hidden(self) -> bool:
            """The runtime hid this surface and only the runtime may revive it."""

            return self._runtime_hidden

        def hide_from_runtime(self) -> None:
            """Hide without destroying, on runtime authority only."""

            self._runtime_hidden = True
            self.hide()

        def restore_from_runtime(self) -> None:
            """Show the very same object again, on runtime authority only.

            This is the ONLY path that may revive an authoritatively hidden
            surface, so it is the only place the hidden flag is cleared.
            """

            self._runtime_hidden = False
            self.show()
            self.raise_()
            self.activateWindow()

        def raise_for_repeat_show(self) -> None:
            """Re-raise on a duplicate SHOW of the same generation/request.

            A replayed SHOW is not a hide/restore authority: it must never
            revive a surface the runtime has hidden.
            """

            if self._runtime_hidden:
                return
            self.show()
            self.raise_()
            self.activateWindow()

        def reject(self) -> None:
            # Escape and window-manager dismissal are not COSINE actions.
            self.delivery_label.setText("COSINE IS WAITING FOR AN ACCEPTED ACTION")

        def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
            if self._accepted_close:
                if hasattr(self, "mascot"):
                    self.mascot.stop()
                event.accept()
            else:
                self.delivery_label.setText("COSINE IS WAITING FOR AN ACCEPTED ACTION")
                event.ignore()

        def _set_buttons_enabled(self, enabled: bool) -> None:
            raise NotImplementedError

        # ----------------------------------------------------------- placement

        def place_for_effect(self) -> None:
            """Centre the card on the intended display.  Presentation only."""

            screen = None
            hwnd = int(getattr(self._request.effect, "source_hwnd", 0) or 0)
            centre = _window_center(hwnd)
            if centre is not None:
                screen = QGuiApplication.screenAt(centre)
            if screen is None:
                try:
                    screen = QGuiApplication.screenAt(QCursor.pos())
                except Exception:
                    screen = None
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            area = screen.availableGeometry()
            self.adjustSize()
            frame = self.frameGeometry()
            self.move(
                area.center().x() - frame.width() // 2,
                area.center().y() - frame.height() // 2,
            )

        # ---------------------------------------------------------- drag/move

        def mousePressEvent(self, event) -> None:  # noqa: N802
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_origin = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                event.accept()
                return
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event) -> None:  # noqa: N802
            if self._drag_origin is not None and (
                event.buttons() & Qt.MouseButton.LeftButton
            ):
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                event.accept()
                return
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event) -> None:  # noqa: N802
            self._drag_origin = None
            super().mouseReleaseEvent(event)

    class CosineIntentionPopup(_CosineDialog):
        """Popup 1 - the intention gate."""

        BADGE = "INTENTION"
        FOOTER = "COSINE · INTENTION GATE"
        ACCESSIBLE = "MYELIN COSINE intention gate"

        def __init__(self, request, tokens, parent=None, *, reduced_motion=False):
            super().__init__(request, tokens, parent, reduced_motion=reduced_motion)
            body = self._build_card()
            self._add_platform_logo(body)
            self._add_headline(body, "IT SEEMS YOU ARE INTERESTED TO WATCH THIS SHOW")
            self._add_mascot(body)
            context = self._platform_context()
            if context:
                self._add_context(body, context)
            self.come_back = QPushButton("SORRY, I'LL COME BACK", self.card)
            self.come_back.setObjectName("cosinePrimary")
            self.take_break = QPushButton("YEAH, I WANT SOME BREAK", self.card)
            self.take_break.setObjectName("cosineSecondary")
            # RETURN_INTENTION is an intention only.  Nothing here may ever
            # present the user as having already returned.
            self.come_back.clicked.connect(
                lambda: self._deliver(
                    CommandKind.INTENT_ACTION,
                    choice=CosineChoice.RETURN_INTENTION,
                    close_after_acceptance=True,
                )
            )
            self.take_break.clicked.connect(
                lambda: self._deliver(
                    CommandKind.INTENT_ACTION,
                    choice=CosineChoice.INTENTIONAL_BREAK,
                    close_after_acceptance=True,
                )
            )
            self._add_delivery_state(body, retry=True)
            self._button_row(body, (self.come_back, self.take_break))
            self._add_footer(body)
            # Choices stay unusable until the factual display is accepted.
            self._set_buttons_enabled(False)

        def _create_card(self) -> QFrame:
            """Paint the certified platform's backdrop inside the same card.

            Falls back to the shared plain frame whenever the platform key is
            unknown or its background cannot be loaded, so a visual problem can
            never stop the intention gate.
            """

            skin = _skin_for_platform(self._request.effect.platform_key)
            if skin is None:
                return super()._create_card()
            background = _load_skin_pixmap(skin.background_filename)
            if background is None:
                return super()._create_card()
            return _PlatformBackdrop(background, self)

        def _add_platform_logo(self, layout: QVBoxLayout) -> None:
            """Add the certified platform's logo, or add nothing at all.

            The eight source logos have very different aspect ratios, so each
            is fitted into one shared box with KeepAspectRatio -- none is
            stretched, and no image file is touched.  Information never lives
            only in the logo: the factual platform context line is unchanged.
            """

            skin = _skin_for_platform(self._request.effect.platform_key)
            if skin is None:
                return
            pixmap = _load_skin_pixmap(skin.logo_filename)
            if pixmap is None:
                return
            key = self._request.effect.platform_key
            label = QLabel(self.card)
            label.setObjectName("cosinePlatformLogo")
            label.setPixmap(
                pixmap.scaled(
                    LOGO_MAX_WIDTH,
                    LOGO_MAX_HEIGHT,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            # A decorative pixmap carries no action: QLabel would otherwise
            # default to LinksAccessibleByMouse.
            label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
            label.setAccessibleName(
                f"{PLATFORM_LABELS.get(key, str(key).replace('_', ' ').title())} logo"
            )
            self.platform_logo = label
            layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)

        def _display_command(self) -> CommandKind:
            return CommandKind.INTENT_GATE_DISPLAYED

        def _set_buttons_enabled(self, enabled: bool) -> None:
            self.come_back.setEnabled(enabled)
            self.take_break.setEnabled(enabled)

    class CosineDurationPopup(_CosineDialog):
        """Popups 2A and 2B - one class driven by the factual variant."""

        FOOTER = "COSINE · BREAK DURATION"
        ACCESSIBLE = "MYELIN COSINE break duration entry"

        def __init__(self, request, tokens, parent=None, *, reduced_motion=False):
            super().__init__(request, tokens, parent, reduced_motion=reduced_motion)
            # The branch is a factual effect field, never a guess from state,
            # timing or message text.
            self.variant = str(getattr(request.effect, "presentation_variant", "") or "")
            self.failed_return = self.variant == FAILED_RETURN_INTENTION
            self.BADGE = "SET A LIMIT" if self.failed_return else "BREAK LENGTH"
            body = self._build_card()
            if self.failed_return:
                self._add_headline(body, "IT SEEMS YOU'D LIKE TO KEEP WATCHING.")
                self._add_message(
                    body,
                    "LET'S SET A LIMIT.\nI'LL CALL YOU BACK WHEN YOUR BREAK IS OVER.",
                )
                self._add_context(body, "TRY TO KEEP IT TO ONE EPISODE.")
                action_text = "START WATCHING"
            else:
                self._add_headline(body, "HOW LONG WOULD YOU LIKE YOUR BREAK TO BE?")
                action_text = "SET TIME"
            field_row = QHBoxLayout()
            field_row.setSpacing(12)
            field_row.addStretch(1)
            self.minutes_field = QLineEdit(self.card)
            self.minutes_field.setObjectName("cosineDurationField")
            self.minutes_field.setPlaceholderText("XX")
            self.minutes_field.setFont(_font(28, weight=QFont.Weight.Bold, spacing=2.0))
            self.minutes_field.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.minutes_field.setFixedWidth(140)
            self.minutes_field.setMaxLength(4)
            self.minutes_field.setAccessibleName("Break length in whole minutes")
            # A deliberately wide validator only blocks non-numeric text.  It
            # must never clamp: 9 and 201 have to reach the backend and be
            # rejected there.
            self.minutes_field.setValidator(QIntValidator(0, 9999, self))
            self.minutes_field.returnPressed.connect(self._submit)
            field_row.addWidget(self.minutes_field)
            unit = QLabel("MINS", self.card)
            unit.setObjectName("cosineUnit")
            unit.setFont(_font(15, weight=QFont.Weight.Bold, mono=True, spacing=2.4))
            field_row.addWidget(unit, 0, Qt.AlignmentFlag.AlignVCenter)
            field_row.addStretch(1)
            body.addLayout(field_row)
            self.action = QPushButton(action_text, self.card)
            self.action.setObjectName("cosinePrimary")
            self.action.clicked.connect(self._submit)
            self._add_delivery_state(body, retry=True)
            self._button_row(body, (self.action,))
            self._add_footer(body)
            # There is no DURATION_DISPLAYED command, so this surface is
            # usable as soon as the runtime shows it.
            self.delivery_label.setText("COSINE IS WAITING FOR YOUR CHOSEN MINUTES")
            self.minutes_field.setFocus()

        def _display_command(self) -> None:
            return None

        def _entered_minutes(self) -> int | None:
            text = self.minutes_field.text().strip()
            try:
                return int(text)
            except (TypeError, ValueError):
                return None

        def _submit(self) -> None:
            # The exact typed value is submitted.  The backend alone accepts
            # 10 through 200; nothing is clamped or corrected here.
            self._deliver(
                CommandKind.DURATION_SUBMITTED,
                duration_minutes=self._entered_minutes(),
                close_after_acceptance=True,
            )

        def _set_buttons_enabled(self, enabled: bool) -> None:
            self.action.setEnabled(enabled)
            self.minutes_field.setEnabled(enabled)

    class CosineBreakAckPopup(_CosineDialog):
        """Popup 3 - the enjoy-the-show acknowledgement."""

        BADGE = "BREAK SET"
        FOOTER = "COSINE · BREAK ACKNOWLEDGEMENT"
        ACCESSIBLE = "MYELIN COSINE break acknowledgement"

        def __init__(self, request, tokens, parent=None, *, reduced_motion=False):
            super().__init__(request, tokens, parent, reduced_motion=reduced_motion)
            body = self._build_card()
            self._add_headline(body, "ENJOY THE SHOW")
            self._add_message(body, "I'LL CALL YOU BACK IN")
            minutes = getattr(request.effect, "duration_minutes", None)
            self.minutes_value = (
                minutes
                if isinstance(minutes, int) and not isinstance(minutes, bool)
                else None
            )
            self.minutes_label = QLabel(
                f"{self.minutes_value} MINS"
                if self.minutes_value is not None
                else "-- MINS",
                self.card,
            )
            self.minutes_label.setObjectName("cosineMinutes")
            self.minutes_label.setFont(_font(46, weight=QFont.Weight.Bold, spacing=2.0))
            self.minutes_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            body.addWidget(self.minutes_label)
            # The visible label is YAY; the submitted choice is the NEW
            # ACKNOWLEDGE, never the legacy compatibility CosineChoice.YAY.
            self.yay = QPushButton("YAY", self.card)
            self.yay.setObjectName("cosinePrimary")
            self.yay.clicked.connect(
                lambda: self._deliver(
                    CommandKind.BREAK_ACKNOWLEDGED,
                    choice=CosineChoice.ACKNOWLEDGE,
                    close_after_acceptance=True,
                )
            )
            self._add_delivery_state(body, retry=True)
            self._button_row(body, (self.yay,))
            self._add_footer(body)
            # YAY stays unusable until the factual display is accepted.  There
            # is no acknowledgement timeout of any kind.
            self._set_buttons_enabled(False)

        def _display_command(self) -> CommandKind:
            return CommandKind.BREAK_ACK_DISPLAYED

        def _set_buttons_enabled(self, enabled: bool) -> None:
            self.yay.setEnabled(enabled)

    class CosineFinalCallbackPopup(_CosineDialog):
        """Popup 4 - the final baseless callback.  It has no controls at all."""

        BADGE = "FOCUS"
        FOOTER = "COSINE · FINAL CALLBACK"
        ACCESSIBLE = "MYELIN COSINE final callback"

        def __init__(self, request, tokens, parent=None, *, reduced_motion=False):
            super().__init__(request, tokens, parent, reduced_motion=reduced_motion)
            self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
            self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
            self.setWindowFlag(Qt.WindowType.WindowSystemMenuHint, False)
            self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
            body = self._build_card()
            self._add_headline(body, "HOPE YOU ENJOYED THE SHOW.")
            self._add_message(body, "NOW IT'S TIME TO FOCUS.")
            self._add_mascot(body)
            # No action button, no extension, no retry control, no dismissal
            # and no countdown.  The backend alone decides when this surface
            # hides, returns or closes.
            self._add_delivery_state(body, retry=False)
            self._add_footer(body)

        def _display_command(self) -> CommandKind:
            return CommandKind.FINAL_CALLBACK_DISPLAYED

        def _set_buttons_enabled(self, enabled: bool) -> None:
            del enabled

        def keyPressEvent(self, event) -> None:  # noqa: N802
            if event.key() == Qt.Key.Key_Escape:
                event.ignore()
                return
            super().keyPressEvent(event)

    class CosinePopupDispatcher(QObject):  # type: ignore[no-redef]
        """The one GUI-thread owner of every NEW COSINE popup instance."""

        request_popup = pyqtSignal(object)
        close_popup = pyqtSignal(object)
        shutdown_requested = pyqtSignal()

        POPUP_SLOTS: Final = (
            "_intent_popup",
            "_duration_popup",
            "_break_ack_popup",
            "_final_popup",
        )

        def __init__(self, app: QApplication, *, owner=None) -> None:
            super().__init__(app)
            self._owner_ref = weakref.ref(owner) if owner is not None else (lambda: None)
            self._intent_popup: CosineIntentionPopup | None = None
            self._duration_popup: CosineDurationPopup | None = None
            self._break_ack_popup: CosineBreakAckPopup | None = None
            self._final_popup: CosineFinalCallbackPopup | None = None
            self._show_slots = {
                EffectKind.SHOW_INTENT_GATE: ("_intent_popup", CosineIntentionPopup),
                EffectKind.SHOW_DURATION_ENTRY: ("_duration_popup", CosineDurationPopup),
                EffectKind.SHOW_BREAK_ACK: ("_break_ack_popup", CosineBreakAckPopup),
                EffectKind.SHOW_FINAL_CALLBACK: (
                    "_final_popup",
                    CosineFinalCallbackPopup,
                ),
            }
            self._close_slots = {
                EffectKind.CLOSE_INTENT_GATE: "_intent_popup",
                EffectKind.CLOSE_DURATION_ENTRY: "_duration_popup",
                EffectKind.CLOSE_BREAK_ACK: "_break_ack_popup",
            }
            self.request_popup.connect(self._show, Qt.ConnectionType.QueuedConnection)
            self.close_popup.connect(self._close, Qt.ConnectionType.QueuedConnection)
            self.shutdown_requested.connect(
                self.shutdown, Qt.ConnectionType.QueuedConnection
            )

        def set_owner(self, owner) -> None:
            self._owner_ref = weakref.ref(owner) if owner is not None else (lambda: None)

        @pyqtSlot(object)
        def _show(self, request: object) -> None:
            if not isinstance(request, PopupRequest):
                return
            effect = request.effect
            slot_name, popup_class = self._show_slots[effect.kind]
            existing = getattr(self, slot_name)
            if existing is not None:
                current = existing._request.effect
                if effect.generation < current.generation:
                    # A stale episode may not retire a newer presentation.
                    return
                if effect.generation == current.generation:
                    if effect.request_id != current.request_id:
                        # Exact fencing is generation AND request_id.  The
                        # runtime never issues two requests for one slot inside
                        # one generation, so this effect is stale or invalid and
                        # must never close or replace the current popup.
                        return
                    if existing.runtime_hidden:
                        # The runtime hid this surface on its own authority.  A
                        # replayed SHOW may not revive it and may not resend the
                        # DISPLAYED command; only RESTORE_FINAL_CALLBACK may.
                        return
                    # Same generation and request: reuse this window, never
                    # build a second one, and retry the factual DISPLAYED
                    # command only while it has not been accepted.
                    existing.raise_for_repeat_show()
                    existing.submit_display_if_pending()
                    return
                # Only a genuinely newer episode may retire the old surface.
                existing.force_close_from_runtime()
            owner = self._owner_ref()
            popup = popup_class(
                request,
                _resolve_tokens(owner),
                reduced_motion=_reduced_motion(owner),
            )
            popup.finished.connect(
                lambda _result=0, p=popup, s=slot_name: self._clear(s, p)
            )
            setattr(self, slot_name, popup)
            popup.place_for_effect()
            popup.show()
            popup.raise_()
            popup.activateWindow()

        @pyqtSlot(object)
        def _close(self, effect: object) -> None:
            if not isinstance(effect, CosineEffect):
                return
            kind = effect.kind
            if kind in self._close_slots:
                popup = getattr(self, self._close_slots[kind])
                if popup is not None and self._matches(popup, effect):
                    popup.force_close_from_runtime()
                return
            if kind is EffectKind.HIDE_FINAL_CALLBACK:
                popup = self._final_popup
                if popup is not None and self._matches(popup, effect):
                    popup.hide_from_runtime()
                return
            if kind is EffectKind.RESTORE_FINAL_CALLBACK:
                popup = self._final_popup
                if popup is not None and self._matches(popup, effect):
                    popup.restore_from_runtime()
                return
            if kind is EffectKind.CLOSE_PRESENTATION:
                for slot_name in self.POPUP_SLOTS:
                    popup = getattr(self, slot_name)
                    if popup is not None and self._matches(popup, effect):
                        popup.force_close_from_runtime()

        @staticmethod
        def _matches(popup: _CosineDialog, effect: CosineEffect) -> bool:
            request = popup._request.effect
            return (
                request.generation == effect.generation
                and request.request_id == effect.request_id
            )

        def _clear(self, slot_name: str, popup: _CosineDialog) -> None:
            if getattr(self, slot_name) is popup:
                setattr(self, slot_name, None)

        @pyqtSlot()
        def shutdown(self) -> None:
            for slot_name in self.POPUP_SLOTS:
                popup = getattr(self, slot_name)
                if popup is not None:
                    popup.force_close_from_runtime()
                setattr(self, slot_name, None)

    _dispatcher_lock = threading.RLock()
    _dispatcher: CosinePopupDispatcher | None = None

    def install_cosine_dispatcher(
        app: QApplication, *, owner=None
    ) -> CosinePopupDispatcher:
        """Install exactly one dispatcher on the QApplication main thread."""

        global _dispatcher
        if app is None:
            raise ValueError("QApplication is required")
        with _dispatcher_lock:
            if _dispatcher is None:
                _dispatcher = CosinePopupDispatcher(app, owner=owner)
            elif owner is not None:
                _dispatcher.set_owner(owner)
            return _dispatcher

    def dispatch_cosine_effect(
        effect: CosineEffect,
        *,
        submit_command: Callable[[CosineCommand], CommandResult],
    ) -> bool:
        """Thread-safe effect delivery from the engine/controller."""

        with _dispatcher_lock:
            dispatcher = _dispatcher
        if dispatcher is None:
            return False
        if effect.kind in SHOW_EFFECTS:
            dispatcher.request_popup.emit(PopupRequest(effect, submit_command))
            return True
        if effect.kind in CONTROL_EFFECTS:
            dispatcher.close_popup.emit(effect)
            return True
        return False

    def shutdown_cosine_dispatcher() -> None:
        with _dispatcher_lock:
            dispatcher = _dispatcher
        if dispatcher is not None:
            dispatcher.shutdown_requested.emit()


__all__ = [
    "CONTROL_EFFECTS",
    "DIRECT_BREAK",
    "DISPLAY_COMMANDS",
    "FAILED_RETURN_INTENTION",
    "POPUP_SCHEMA_VERSION",
    "SHOW_EFFECTS",
    "CosinePopupDispatcher",
    "PopupRequest",
    "dispatch_cosine_effect",
    "install_cosine_dispatcher",
    "shutdown_cosine_dispatcher",
]
