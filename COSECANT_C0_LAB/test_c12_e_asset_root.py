"""C12-E -- one canonical asset root.

The production body ships ``ASSETS/``.  Both path authorities pointed at
``Required_assets/``, a directory that does not exist, so every window icon,
tray icon and loading image silently resolved to nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import _lab  # noqa: F401

from PERSISTENCE.database import project_root, resource_path

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qt_app():
    """Hold the QApplication for the whole module; a collected one crashes."""

    app = QApplication.instance() or QApplication([])
    yield app

ULTIMATE = _lab.ULTIMATE
CANONICAL = "ASSETS"

PRODUCTION_ASSETS = (
    "icons/Myelin_Loading_Screen.ico",
    "images/Myelin_Loading_Screen.png",
)


# ---------------------------------------------------------------------------
# The physical truth
# ---------------------------------------------------------------------------

def test_canonical_asset_root_exists_and_is_unique():
    assert (ULTIMATE / CANONICAL).is_dir()
    assert not (ULTIMATE / "Required_assets").exists(), (
        "a duplicate asset tree was created instead of repairing the path "
        "authorities"
    )


def test_no_production_source_references_the_old_root():
    offenders = [
        str(path.relative_to(ULTIMATE))
        for path in ULTIMATE.rglob("*.py")
        if "Required_assets" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], offenders


# ---------------------------------------------------------------------------
# Path authority 1 -- PERSISTENCE.database.resource_path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", PRODUCTION_ASSETS)
def test_resource_path_resolves_real_files(relative):
    resolved = resource_path(relative)
    assert resolved.is_file(), resolved
    assert resolved.parent.parent.name == CANONICAL


def test_loading_image_resolves_through_the_launcher_helper():
    import ast

    source = (ULTIMATE / "CONTROL_STATION" / "launcher.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    helper = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_resolve_loading_logo"
    )
    assert "images/Myelin_Loading_Screen.png" in ast.unparse(helper)
    assert Path(resource_path("images/Myelin_Loading_Screen.png")).is_file()


def test_resource_path_still_refuses_escape():
    with pytest.raises(ValueError):
        resource_path("../PERSISTENCE/storage.py")
    with pytest.raises(ValueError):
        resource_path(str(ULTIMATE / "PERSISTENCE" / "storage.py"))
    with pytest.raises(ValueError):
        resource_path("icons/../../CORE_ENGINE/monitor.py")


def test_resource_path_missing_file_stays_inside_the_root():
    """A missing asset is still a contained path, not an error or an escape."""

    resolved = resource_path("icons/does_not_exist.ico")
    assert not resolved.exists()
    assert resolved.is_relative_to((project_root() / CANONICAL).resolve())


# ---------------------------------------------------------------------------
# Path authority 2 -- UI_THEMES.theme.resource_icon
# ---------------------------------------------------------------------------

def test_resource_icon_resolves_application_and_tray_icon(qt_app):
    from UI_THEMES.theme import _assets_root, resource_icon

    assert _assets_root().name == CANONICAL
    assert _assets_root().is_dir()

    # The application window icon and the tray icon are the same asset.
    icon = resource_icon("icons/Myelin_Loading_Screen.ico")
    assert not icon.isNull()
    assert icon.availableSizes()


def test_application_window_and_tray_bind_the_approved_icon():
    launcher = (ULTIMATE / "CONTROL_STATION" / "launcher.py").read_text(
        encoding="utf-8"
    )
    tray = (ULTIMATE / "CONTROL_STATION" / "tray.py").read_text(
        encoding="utf-8"
    )
    binding = 'resource_icon("icons/Myelin_Loading_Screen.ico")'
    assert launcher.count(binding) == 2
    assert tray.count(binding) == 1
    assert 'resource_icon("icons/Myelin.ico")' not in launcher
    assert 'resource_icon("icons/Myelin.ico")' not in tray


def test_resource_icon_missing_resource_is_still_safe(qt_app):
    from UI_THEMES.theme import resource_icon

    assert resource_icon("icons/does_not_exist.ico").isNull()
    assert resource_icon("../PERSISTENCE/storage.py").isNull()
    assert resource_icon(str(ULTIMATE / "ASSETS" / "icons" / "Myelin.ico")).isNull()
