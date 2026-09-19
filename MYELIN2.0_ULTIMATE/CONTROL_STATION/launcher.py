"""MYELIN Control Station process ignition.

This is the one real executable entry point.  The startup transition lives in
startup.py and the complete Control Station body lives in application.py.
"""

from __future__ import annotations

import ctypes
import sys
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
# so relative imports such as ``from .application import ...`` would fail.
# Add the MYELIN2.0_ULTIMATE_TRIAL root to sys.path and establish the package.
if __package__ in (None, ""):
    _PROJECT_ROOT = Path(__file__).resolve().parents[1]
    _project_root_text = str(_PROJECT_ROOT)

    if _project_root_text not in sys.path:
        sys.path.insert(0, _project_root_text)

    __package__ = "CONTROL_STATION"

from collections.abc import Sequence
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QApplication

from .startup import (
    WINDOWS_APP_ID,
    StartupSequence,
    _canonical_application_icon,
)
from PERSISTENCE.storage import bootstrap_production_schema
from UI_THEMES.theme import build_application_stylesheet, make_font

if TYPE_CHECKING:
    # Type-checking only: application.py stays unimported at runtime until
    # StartupSequence._build_window() needs the real class.
    from .application import ControlStationWindow


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

