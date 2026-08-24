"""External regression for the Control Station's native Windows frame."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMainWindow

import _lab  # noqa: F401  # installs the production root for external tests
from CONTROL_STATION.settings import SettingsController


@pytest.fixture(scope="module")
def app():
    existing = QApplication.instance()
    return existing if existing is not None else QApplication([])


def _controller(path: Path, *, maximized: bool) -> SettingsController:
    controller = SettingsController(path=path)
    controller._document["window_geometry"] = None
    controller._document["window_maximized"] = maximized
    return controller


def test_restore_rejects_fullscreen_and_returns_normal_native_window(
    app, tmp_path: Path
):
    controller = _controller(tmp_path / "normal.json", maximized=False)
    window = QMainWindow()
    try:
        window.setWindowState(Qt.WindowState.WindowFullScreen)
        assert window.windowState() & Qt.WindowState.WindowFullScreen

        controller.restore_window(window)

        assert not window.windowState() & Qt.WindowState.WindowFullScreen
        assert not window.windowState() & Qt.WindowState.WindowMaximized
    finally:
        window.close()
        controller.shutdown()


def test_restore_converts_stale_fullscreen_to_approved_maximized_state(
    app, tmp_path: Path
):
    controller = _controller(tmp_path / "maximized.json", maximized=True)
    window = QMainWindow()
    try:
        window.setWindowState(Qt.WindowState.WindowFullScreen)

        controller.restore_window(window)
        QApplication.processEvents()

        assert not window.windowState() & Qt.WindowState.WindowFullScreen
        assert window.windowState() & Qt.WindowState.WindowMaximized
    finally:
        window.close()
        controller.shutdown()


def test_main_window_explicitly_requires_native_caption_controls():
    launcher = (
        Path(__file__).resolve().parents[1]
        / "MYELIN2.0_ULTIMATE"
        / "CONTROL_STATION"
        / "launcher.py"
    ).read_text(encoding="utf-8")

    required = (
        "~Qt.WindowType.FramelessWindowHint",
        "Qt.WindowType.WindowTitleHint",
        "Qt.WindowType.WindowSystemMenuHint",
        "Qt.WindowType.WindowMinimizeButtonHint",
        "Qt.WindowType.WindowMaximizeButtonHint",
        "Qt.WindowType.WindowCloseButtonHint",
    )
    assert all(token in launcher for token in required)
