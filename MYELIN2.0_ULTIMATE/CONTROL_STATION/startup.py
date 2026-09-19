"""MYELIN Control Station startup transition.

Mechanically transplanted from the Phase-1 prepared launcher donor.  This
module owns the splash, startup gate, main-window construction, handoff, and
startup completion.

It is also the canonical icon authority (Icon-First Startup Patch,
2026-09-12): the MYELIN icon must be established, and the splash shown,
before ``application.py`` is ever imported.  ``application.py`` is a heavy
module (Control Station body, every page, every organ wiring) and importing
it early was never required for the icon to exist -- the icon only ever
needed the asset loader and ``QIcon``, both far lighter dependencies.

It also owns the native Win32 window-class icon (2026-09-12): the splash and
``ControlStationWindow`` share one registered Qt window class, so
``setWindowIcon()`` alone (which only ever sends ``WM_SETICON`` to the one
window it's called on) left the class's own ``GCLP_HICON``/``GCLP_HICONSM``
generic -- and that, not import timing, is what the Windows taskbar was
actually showing.  Installing the MYELIN icon on the class once, through the
splash HWND, before ``application.py`` is imported, means every later window
from that class -- ``ControlStationWindow`` included -- inherits it.
Confirmed fix, verified against the live taskbar by Chief on 2026-09-12.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from .lifecycle import LifecycleController, StartupGateResult
from .myelin_loading_screen import MyelinLoadingScreen
from UI_THEMES.theme import resource_icon

if TYPE_CHECKING:
    # Type-checking only: application.py stays unimported at runtime until
    # StartupSequence._build_window() needs the real class.
    from .application import ControlStationWindow


WINDOWS_APP_ID: Final = "MYELIN.ControlStation.2"


def _canonical_application_icon() -> QIcon:
    """Return THE MYELIN icon, for every window and for the application.

    One asset, one loader.  Windows paints the *window* icon on the taskbar
    button and falls back to the *application* icon only for windows that set
    none -- in practice the frameless startup splash.  Two call sites loading
    two different files therefore showed two different marks during startup.
    Routing both through here keeps them from drifting apart again.

    This is the ICON-FIRST authority: startup.py owns it so the icon exists
    before ``application.py`` is ever imported, not after.
    """

    return resource_icon("icons/Myelin_2.ico")


# Keeps the two loaded HICONs alive for the process's life. SetClassLongPtrW
# stores the raw handle; it takes no ownership and makes no copy, so letting
# these go out of scope would eventually hand every MYELIN window a stale
# handle.
_NATIVE_CLASS_ICON_HANDLES: list[int] = []


def _install_native_class_icon(hwnd: int) -> None:
    """Install the MYELIN icon on the shared native Qt window class.

    The splash and ``ControlStationWindow`` are both instances of the same
    registered Win32 window class.  ``setWindowIcon()`` only ever sends
    ``WM_SETICON`` to the one window it's called on; it never reaches the
    shared class icon Windows falls back to for the taskbar button.  Because
    the splash HWND already exists before ``application.py`` is imported,
    installing the MYELIN icon on the class through it here means every
    later window born from the same class inherits it automatically.
    """

    import ctypes
    from ctypes import wintypes

    from PERSISTENCE.database import resource_path

    if sys.platform != "win32":
        return

    icon_path = str(resource_path("icons/Myelin_2.ico"))

    user32 = ctypes.windll.user32

    SM_CXICON, SM_CYICON = 11, 12
    SM_CXSMICON, SM_CYSMICON = 49, 50
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010
    GCLP_HICON, GCLP_HICONSM = -14, -34

    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = [
        wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]

    # Pointer-width-safe: SetClassLongPtrW is the 64-bit form; the plain W
    # form is the correct fallback on 32-bit Python rather than assuming
    # pointer width.
    pointer_width_64 = ctypes.sizeof(ctypes.c_void_p) == 8
    set_class_long = user32.SetClassLongPtrW if pointer_width_64 else user32.SetClassLongW
    set_class_long.restype = ctypes.c_void_p
    set_class_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

    cx_big = user32.GetSystemMetrics(SM_CXICON)
    cy_big = user32.GetSystemMetrics(SM_CYICON)
    cx_small = user32.GetSystemMetrics(SM_CXSMICON)
    cy_small = user32.GetSystemMetrics(SM_CYSMICON)

    big_hicon = user32.LoadImageW(None, icon_path, IMAGE_ICON, cx_big, cy_big, LR_LOADFROMFILE)
    small_hicon = user32.LoadImageW(
        None, icon_path, IMAGE_ICON, cx_small, cy_small, LR_LOADFROMFILE
    )

    if not big_hicon or not small_hicon:
        print(
            f"[MYELIN][STARTUP] native class icon load failed "
            f"(big={big_hicon}, small={small_hicon}); taskbar icon may fall "
            "back to the shared Qt default",
            file=sys.stderr,
        )
        return

    _NATIVE_CLASS_ICON_HANDLES.extend([big_hicon, small_hicon])
    set_class_long(hwnd, GCLP_HICON, big_hicon)
    set_class_long(hwnd, GCLP_HICONSM, small_hicon)


# PHASE 2 COPY-PASTE REGION: startup.py
# =============================================================================
# Splash construction and both startup-time icon assignments remain here.

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
        completed: Callable[[int, "ControlStationWindow | None"], None] | None = None,
    ) -> None:
        self._app = app
        self._minimum_display_ms = max(0, int(minimum_display_ms))
        self._completed = completed
        self._started_at = time.monotonic()
        self._is_finished = False
        self._window: "ControlStationWindow | None" = None

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
        # Native window-CLASS icon: must happen here, through the splash's
        # real HWND, before application.py (and ControlStationWindow) exist.
        _install_native_class_icon(int(self._splash.winId()))
        self._splash.set_progress(15, "Loading MYELIN icons")
        self._splash.set_progress(35, "Applying MYELIN identity")
        QTimer.singleShot(0, self._run_startup_gate)

    def _run_startup_gate(self) -> None:
        try:
            self._splash.set_progress(60, "Starting MYELIN — please wait")
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
            from .application import ControlStationWindow  # local: icon-first

            self._splash.set_progress(85, "Preparing Control Station")

            self._window = ControlStationWindow()
            self._splash.set_progress(100, "MYELIN ready")

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

    def _complete(self, exit_code: int, window: "ControlStationWindow | None") -> None:
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
