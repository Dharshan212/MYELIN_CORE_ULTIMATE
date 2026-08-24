"""Validated user preferences for the MYELIN Control Station.

This module owns normal interface preferences only:

* the clock and its timezone;
* main-window placement;
* mini-controller placement and appearance; and
* ordinary visual and minimize preferences.

Important boundary
------------------
SINE BLUE, AMBER and RED are live intervention facts.  They are never user
preferences and must never be restored from this file.  Runtime, evidence,
trigger, dwell and Study-state fields are rejected for the same reason.

The public controller intentionally separates two jobs:

1. damaged files are repaired field by field while loading; and
2. live callers must provide a valid value or the entire update is rejected.

That separation prevents a programming mistake from silently becoming a
successful settings change.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
import threading
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone, tzinfo
from enum import Enum
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PyQt6.QtCore import QByteArray, QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


SCHEMA_VERSION: Final = 3
DEFAULT_TIMEZONE: Final = "local"
DEFAULT_PAGE: Final = "control"

VALID_PAGES: Final = frozenset(
    {
        "control",
        "study-mode",
        "metric-hub",
        "science-lab",
        "live-mirl",
        "mine",
        "cosine",
    }
)
VALID_APPEARANCES: Final = frozenset({"dark", "light", "system"})
VALID_MINIMIZE_BEHAVIORS: Final = frozenset({"adaptive", "taskbar", "tray"})

# INSTRUCTION: These names are not preferences.  Keeping the deny-list close
# to the schema makes the safety boundary easy to audit.
FORBIDDEN_RUNTIME_KEYS: Final = frozenset(
    {
        "sine_world",
        "sine_stage",
        "current_sine_stage",
        "sine_blue",
        "sine_amber",
        "sine_red",
        "protected_red",
        "red_protected",
        "open_red_intervention",
        "intervention_stage",
        "study_state",
        "study_mode_active",
        "cosecant_state",
        "engine_state",
        "engine_status",
        "resource_intent",
        "resource_confidence",
        "resource_evidence",
        "off_task_dwell",
        "dwell_seconds",
        "idle_state",
        "idle_seconds",
        "trigger_state",
        "mirl_state",
    }
)


@dataclass(frozen=True, slots=True)
class TimezoneChoice:
    """One approved clock choice with a Windows-safe fallback offset."""

    key: str
    label: str
    tag: str
    fallback_minutes: int | None


TIMEZONE_CHOICES: Final = (
    TimezoneChoice("local", "Local system time", "LOCAL", None),
    TimezoneChoice("Asia/Kolkata", "India", "IST", 330),
    TimezoneChoice("Europe/London", "London / Edinburgh", "UK", 60),
    TimezoneChoice("America/New_York", "New York / Pittsburgh", "ET", -240),
    TimezoneChoice("America/Chicago", "Chicago / Minneapolis", "CT", -300),
    TimezoneChoice(
        "America/Los_Angeles", "San Francisco / Los Angeles", "PT", -420
    ),
    TimezoneChoice("Europe/Berlin", "Berlin", "CET", 120),
    TimezoneChoice("Asia/Tokyo", "Tokyo / Osaka", "JST", 540),
    TimezoneChoice("Asia/Shanghai", "Shanghai", "CST", 480),
    TimezoneChoice("Asia/Jerusalem", "Israel", "ISR", 180),
    TimezoneChoice("Asia/Dubai", "Dubai", "GST", 240),
    TimezoneChoice("Asia/Singapore", "Singapore", "SGT", 480),
    TimezoneChoice("Australia/Sydney", "Sydney", "AET", 600),
    TimezoneChoice("Pacific/Auckland", "Auckland", "NZT", 720),
)
TIMEZONE_BY_KEY: Final = {choice.key: choice for choice in TIMEZONE_CHOICES}


@dataclass(frozen=True, slots=True)
class MiniControllerPreferences:
    """Normal presentation preferences for the small controller window."""

    visible: bool = False
    collapsed: bool = True
    position_is_set: bool = False
    x: int = 0
    y: int = 0
    always_on_top: bool = True


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    """Immutable settings truth supplied to UI consumers."""

    schema_version: int = SCHEMA_VERSION
    appearance: str = "dark"
    reduced_motion: bool = False
    clock_visible: bool = True
    clock_timezone: str = DEFAULT_TIMEZONE
    clock_collapsed: bool = False
    last_page: str = DEFAULT_PAGE
    window_geometry: QByteArray | None = None
    window_maximized: bool = False
    minimize_behavior: str = "adaptive"
    tray_enabled: bool = True
    mini_controller: MiniControllerPreferences = MiniControllerPreferences()

    # These convenience properties retain the simple names used by the
    # mini-controller without exposing the JSON representation.
    @property
    def mini_controller_visible(self) -> bool:
        return self.mini_controller.visible

    @property
    def mini_controller_collapsed(self) -> bool:
        return self.mini_controller.collapsed

    @property
    def mini_controller_position_set(self) -> bool:
        return self.mini_controller.position_is_set

    @property
    def mini_controller_x(self) -> int:
        return self.mini_controller.x

    @property
    def mini_controller_y(self) -> int:
        return self.mini_controller.y

    @property
    def mini_controller_always_on_top(self) -> bool:
        return self.mini_controller.always_on_top


class SettingsSource(str, Enum):
    PRIMARY = "primary"
    BACKUP = "backup"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class _LoadResult:
    document: dict[str, object] | None
    source: SettingsSource


def _settings_path() -> Path:
    """Return one per-user Windows path without depending on the engine."""

    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "MYELIN" / "control_station_preferences.json"


def _read_json(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


class _AtomicJsonStore:
    """Small atomic JSON store with one known-good backup."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.backup_path = path.with_suffix(path.suffix + ".bak")

    def load(self) -> _LoadResult:
        primary = _read_json(self.path)
        if primary is not None:
            return _LoadResult(primary, SettingsSource.PRIMARY)
        backup = _read_json(self.backup_path)
        if backup is not None:
            return _LoadResult(backup, SettingsSource.BACKUP)
        return _LoadResult(None, SettingsSource.NONE)

    def save(self, document: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Only a parseable primary is allowed to replace the known-good backup.
        if _read_json(self.path) is not None:
            shutil.copy2(self.path, self.backup_path)

        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(document, stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class _PreferenceWriter:
    """Coalesce disk writes on one daemon thread.

    INSTRUCTION: the GUI thread never joins this worker.  A damaged or slow
    disk therefore cannot freeze the Control Station during shutdown.
    """

    def __init__(self, store: _AtomicJsonStore) -> None:
        self._store = store
        self._condition = threading.Condition()
        self._pending: tuple[int, dict[str, object]] | None = None
        self._closing = False
        self._last_written_revision = -1
        self._errors: list[str] = []
        self._thread = threading.Thread(
            target=self._run,
            name="MyelinPreferenceWriter",
            daemon=True,
        )
        self._thread.start()

    def submit(self, revision: int, document: dict[str, object]) -> None:
        with self._condition:
            if self._closing:
                return
            self._pending = (revision, document)
            self._condition.notify()

    def close(self, revision: int, document: dict[str, object]) -> None:
        """Queue the final value and return immediately."""

        with self._condition:
            if self._closing:
                return
            self._pending = (revision, document)
            self._closing = True
            self._condition.notify()

    def take_errors(self) -> tuple[str, ...]:
        with self._condition:
            errors = tuple(self._errors)
            self._errors.clear()
            return errors

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closing:
                    self._condition.wait()
                work = self._pending
                self._pending = None
                should_close = self._closing

            if work is not None:
                revision, document = work
                if revision > self._last_written_revision:
                    try:
                        self._store.save(document)
                    except Exception as error:  # disk failures must not kill UI
                        with self._condition:
                            self._errors.append(str(error))
                    else:
                        self._last_written_revision = revision

            with self._condition:
                if should_close and self._pending is None:
                    return


def _strict_bool(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be true or false")
    return value


def _strict_text_choice(value: object, name: str, choices: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{name} is not an approved value")
    return value


def _strict_coordinate(value: object, name: str) -> int:
    if type(value) is not int or not -100_000 <= value <= 100_000:
        raise ValueError(f"{name} must be a safe screen coordinate")
    return value


def _decode_geometry(value: object) -> QByteArray | None:
    if value in {None, ""}:
        return None
    if not isinstance(value, str) or len(value) > 32_768:
        raise ValueError("window_geometry is not a safe encoded value")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as error:
        raise ValueError("window_geometry is not valid base64") from error
    if not raw or len(raw) > 24_576:
        raise ValueError("window_geometry has an invalid size")
    return QByteArray(raw)


def _encode_geometry(value: QByteArray | bytes | bytearray | None) -> str | None:
    if value is None:
        return None
    raw = bytes(value)
    if not raw or len(raw) > 24_576:
        raise ValueError("window_geometry has an invalid size")
    return base64.b64encode(raw).decode("ascii")


def _validate_timezone(value: object) -> str:
    if not isinstance(value, str) or value not in TIMEZONE_BY_KEY:
        raise ValueError("clock_timezone is not an approved timezone")
    return value


def _default_document() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "appearance": "dark",
        "reduced_motion": False,
        "clock_visible": True,
        "clock_timezone": DEFAULT_TIMEZONE,
        "clock_collapsed": False,
        "last_page": DEFAULT_PAGE,
        "window_geometry": None,
        "window_maximized": False,
        "minimize_behavior": "adaptive",
        "tray_enabled": True,
        "mini_controller": asdict(MiniControllerPreferences()),
    }


def _validate_field(name: str, value: object) -> object:
    """Validate one live update.  Unknown fields never become preferences."""

    if name in FORBIDDEN_RUNTIME_KEYS or name.startswith("sine_"):
        raise ValueError(f"{name} is runtime truth and cannot be stored")
    if name == "appearance":
        return _strict_text_choice(value, name, VALID_APPEARANCES)
    if name in {"reduced_motion", "clock_visible", "clock_collapsed"}:
        return _strict_bool(value, name)
    if name == "clock_timezone":
        return _validate_timezone(value)
    if name == "last_page":
        return _strict_text_choice(value, name, VALID_PAGES)
    if name == "window_geometry":
        if isinstance(value, (QByteArray, bytes, bytearray)) or value is None:
            return _encode_geometry(value)
        _decode_geometry(value)
        return value
    if name in {"window_maximized", "tray_enabled"}:
        return _strict_bool(value, name)
    if name == "minimize_behavior":
        raw = getattr(value, "value", value)
        return _strict_text_choice(raw, name, VALID_MINIMIZE_BEHAVIORS)
    if name == "mini_controller":
        return _validate_mini_controller(value)
    raise ValueError(f"{name} is not a supported user preference")


def _validate_mini_controller(value: object) -> dict[str, object]:
    if isinstance(value, MiniControllerPreferences):
        value = asdict(value)
    if not isinstance(value, dict):
        raise ValueError("mini_controller must be an object")
    required = {
        "visible",
        "collapsed",
        "position_is_set",
        "x",
        "y",
        "always_on_top",
    }
    if set(value) != required:
        raise ValueError("mini_controller contains missing or unknown fields")
    return {
        "visible": _strict_bool(value["visible"], "mini_controller.visible"),
        "collapsed": _strict_bool(value["collapsed"], "mini_controller.collapsed"),
        "position_is_set": _strict_bool(
            value["position_is_set"], "mini_controller.position_is_set"
        ),
        "x": _strict_coordinate(value["x"], "mini_controller.x"),
        "y": _strict_coordinate(value["y"], "mini_controller.y"),
        "always_on_top": _strict_bool(
            value["always_on_top"], "mini_controller.always_on_top"
        ),
    }


def _repair_loaded_document(document: dict[str, object] | None) -> dict[str, object]:
    """Repair known UI fields while discarding every unknown/runtime field."""

    repaired = _default_document()
    if document is None:
        return repaired
    version = document.get("schema_version", 1)
    if type(version) is not int or version > SCHEMA_VERSION:
        raise RuntimeError("settings were written by a newer MYELIN version")

    for name in tuple(repaired):
        if name == "schema_version" or name not in document:
            continue
        try:
            repaired[name] = _validate_field(name, document[name])
        except (TypeError, ValueError):
            # Disk repair is deliberately tolerant. Live updates are not.
            continue

    # Clean import from the old flat mini-controller representation.
    if "mini_controller" not in document:
        old_names = {
            "mini_controller_visible": "visible",
            "mini_controller_collapsed": "collapsed",
            "mini_controller_position_set": "position_is_set",
            "mini_controller_x": "x",
            "mini_controller_y": "y",
            "mini_controller_always_on_top": "always_on_top",
        }
        mini = dict(repaired["mini_controller"])
        for old_name, new_name in old_names.items():
            if old_name not in document:
                continue
            candidate = dict(mini)
            candidate[new_name] = document[old_name]
            try:
                mini = _validate_mini_controller(candidate)
            except (TypeError, ValueError):
                continue
        repaired["mini_controller"] = mini

    repaired["schema_version"] = SCHEMA_VERSION
    return repaired


def _snapshot_from_document(document: dict[str, object]) -> SettingsSnapshot:
    mini = _validate_mini_controller(document["mini_controller"])
    return SettingsSnapshot(
        appearance=str(document["appearance"]),
        reduced_motion=bool(document["reduced_motion"]),
        clock_visible=bool(document["clock_visible"]),
        clock_timezone=str(document["clock_timezone"]),
        clock_collapsed=bool(document["clock_collapsed"]),
        last_page=str(document["last_page"]),
        window_geometry=_decode_geometry(document["window_geometry"]),
        window_maximized=bool(document["window_maximized"]),
        minimize_behavior=str(document["minimize_behavior"]),
        tray_enabled=bool(document["tray_enabled"]),
        mini_controller=MiniControllerPreferences(**mini),
    )


def _clock_timezone(choice: TimezoneChoice) -> tzinfo | None:
    if choice.key == "local":
        return None
    try:
        return ZoneInfo(choice.key)
    except ZoneInfoNotFoundError:
        # Some Windows Python installations do not include the IANA database.
        return timezone(timedelta(minutes=choice.fallback_minutes or 0))


class TimezoneDialog(QDialog):
    """Non-blocking timezone chooser; no nested Qt event loop is used."""

    timezone_selected = pyqtSignal(str)

    def __init__(self, current_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("timezoneDialog")
        self.setWindowTitle("Clock timezone")
        self.setModal(True)
        self.resize(440, 470)

        from UI_THEMES.theme import label as themed_label

        title = themed_label("SELECT CLOCK TIMEZONE", 13, 700, "text", spacing=1.2, upper=True)
        title.setObjectName("dialogTitle")
        explanation = themed_label(
            "This changes the Control Station clock only. It does not change "
            "Windows or any MYELIN engine time.",
            11.5, 400, "muted", wrap=True,
        )

        self.list_widget = QListWidget()
        self.list_widget.setObjectName("timezoneList")
        for choice in TIMEZONE_CHOICES:
            item = QListWidgetItem(f"{choice.label}   [{choice.tag}]")
            item.setData(Qt.ItemDataRole.UserRole, choice.key)
            self.list_widget.addItem(item)
            if choice.key == current_key:
                self.list_widget.setCurrentItem(item)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("APPLY")
        buttons.button(QDialogButtonBox.StandardButton.Apply).setObjectName("btnStart")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("btnStop")
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        self.list_widget.itemDoubleClicked.connect(self._accept_selection)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(explanation)
        layout.addWidget(self.list_widget, 1)
        layout.addWidget(buttons)

    def _accept_selection(self, *_args) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        key = str(item.data(Qt.ItemDataRole.UserRole))
        if key not in TIMEZONE_BY_KEY:
            return
        self.timezone_selected.emit(key)
        self.accept()


def _clock_icon_button(text: str, tooltip: str, object_name: str) -> QPushButton:
    """Small round icon-only button matching the donor's HUD chevron/gear."""

    button = QPushButton(text)
    button.setObjectName(object_name)
    button.setToolTip(tooltip)
    button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    button.setFixedSize(26, 26)
    return button


class SystemClockWidget(QFrame):
    """The approved expandable Control Station clock.

    Styled as a normal card (card language: 1px border, surface fill, soft
    shadow, radius-lg) with a dot-marked heading, a large mono time, a cyan
    timezone tag and a muted day/date row -- ported from the donor's
    ``HudClock`` (expanded state only; the compact/collapsed strip keeps its
    existing simpler layout).
    """

    def __init__(self, settings: "SettingsController") -> None:
        super().__init__()
        from UI_THEMES.theme import card_shadow, label as themed_label

        self._settings = settings
        self._dialog: TimezoneDialog | None = None
        self.setObjectName("systemClock")
        self.setFrameShape(QFrame.Shape.NoFrame)
        card_shadow(self)

        self.heading = QWidget()
        self.heading.setObjectName("plainBox")
        head = QHBoxLayout(self.heading)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(7)
        from UI_THEMES.animation import Dot
        head.addWidget(Dot(5, "cyan"))
        self._heading_text = themed_label(
            "System Clock", 10.5, 700, "muted", spacing=2.0, upper=True
        )
        head.addWidget(self._heading_text)
        head.addStretch(1)

        self.settings_button = _clock_icon_button("\u2699", "Choose clock timezone", "clockSettingsButton")
        self.settings_button.clicked.connect(self._open_timezone_dialog)
        head.addWidget(self.settings_button)
        head.addSpacing(4)
        self.collapse_button = _clock_icon_button("\u2039", "Collapse or expand clock", "clockCollapseButton")
        self.collapse_button.clicked.connect(self._toggle_collapsed)
        head.addWidget(self.collapse_button)

        self.time_label = themed_label("--:--:--", 21, 700, "text", mono=True, spacing=1.5)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timezone_label = themed_label("[ \u2014 ]", 10, 400, "cyan", mono=True, spacing=2.0)
        self.timezone_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.date_row = QFrame()
        self.date_row.setObjectName("hudDateRow")
        self.date_row.setFrameShape(QFrame.Shape.NoFrame)
        date_layout = QHBoxLayout(self.date_row)
        date_layout.setContentsMargins(0, 9, 0, 0)
        date_layout.setSpacing(14)
        date_layout.addStretch(1)
        self.day_value = themed_label("\u2014", 9.5, 600, "text", mono=True, spacing=0.6)
        self.date_value = themed_label("\u2014", 9.5, 600, "text", mono=True, spacing=0.6)
        for caption, value in (("DAY : ", self.day_value), ("Date : ", self.date_value)):
            item = QWidget()
            item.setObjectName("plainBox")
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(0, 0, 0, 0)
            item_layout.setSpacing(0)
            item_layout.addWidget(themed_label(caption, 9.5, 400, "muted", mono=True, spacing=0.6))
            item_layout.addWidget(value)
            date_layout.addWidget(item)
        date_layout.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 14, 22, 12)
        layout.setSpacing(0)
        layout.addWidget(self.heading)
        layout.addSpacing(10)
        layout.addWidget(self.time_label)
        layout.addSpacing(5)
        layout.addWidget(self.timezone_label)
        layout.addSpacing(10)
        layout.addWidget(self.date_row)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.apply_collapsed(self._settings.snapshot().clock_collapsed)
        self.refresh()

    def refresh(self) -> None:
        choice = TIMEZONE_BY_KEY[self._settings.snapshot().clock_timezone]
        selected_timezone = _clock_timezone(choice)
        now = datetime.now().astimezone() if selected_timezone is None else datetime.now(selected_timezone)
        self.time_label.setText(now.strftime("%H:%M:%S"))
        self.timezone_label.setText(f"[ {choice.tag} ]")
        self.day_value.setText(now.strftime("%A"))
        self.date_value.setText(now.strftime("%d-%m-%Y"))

    def apply_collapsed(self, collapsed: bool) -> None:
        self.setProperty("collapsed", collapsed)
        self._heading_text.setVisible(not collapsed)
        self.timezone_label.setVisible(not collapsed)
        self.date_row.setVisible(not collapsed)
        self.collapse_button.setText("\u203a" if collapsed else "\u2039")
        self.setFixedWidth(150 if collapsed else 260)
        self.style().unpolish(self)
        self.style().polish(self)

    def _toggle_collapsed(self) -> None:
        collapsed = not self._settings.snapshot().clock_collapsed
        if self._settings.set("clock_collapsed", collapsed):
            self.apply_collapsed(collapsed)

    def _open_timezone_dialog(self) -> None:
        if self._dialog is not None and self._dialog.isVisible():
            self._dialog.raise_()
            self._dialog.activateWindow()
            return
        self._dialog = TimezoneDialog(
            self._settings.snapshot().clock_timezone,
            parent=self.window(),
        )
        self._dialog.timezone_selected.connect(self._select_timezone)
        self._dialog.finished.connect(self._dialog_finished)
        self._dialog.open()

    def _select_timezone(self, key: str) -> None:
        if self._settings.set("clock_timezone", key):
            self.refresh()

    def _dialog_finished(self, _result: int) -> None:
        if self._dialog is not None:
            self._dialog.deleteLater()
            self._dialog = None


class SettingsController(QObject):
    """Single authority for validated, non-runtime user preferences."""

    changed = pyqtSignal(str, object)
    write_failed = pyqtSignal(str)

    def __init__(
        self,
        path: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = _AtomicJsonStore(path or _settings_path())
        self._read_only_reason: str | None = None
        self._closed = False
        self._revision = 0
        self._clock: SystemClockWidget | None = None

        loaded = self._store.load()
        try:
            self._document = _repair_loaded_document(loaded.document)
        except RuntimeError as error:
            # Never overwrite settings from a newer application version.
            self._document = _default_document()
            self._read_only_reason = str(error)

        self._writer = _PreferenceWriter(self._store)
        self._error_timer = QTimer(self)
        self._error_timer.setInterval(500)
        self._error_timer.timeout.connect(self._deliver_write_errors)
        self._error_timer.start()

        # A backup recovery is immediately rewritten to repair the primary.
        if loaded.source is SettingsSource.BACKUP and not self.is_read_only:
            self._queue_write()

    @property
    def is_read_only(self) -> bool:
        return self._read_only_reason is not None

    @property
    def read_only_reason(self) -> str | None:
        return self._read_only_reason

    def snapshot(self) -> SettingsSnapshot:
        return _snapshot_from_document(dict(self._document))

    def get(self, name: str, default=None):
        """Read a normal preference without exposing the mutable document."""

        try:
            snapshot = self.snapshot()
            return getattr(snapshot, name)
        except (AttributeError, TypeError, ValueError):
            return default

    def set(self, name: str, value: object) -> bool:
        """Strictly update one preference; invalid input changes nothing."""

        return self.apply_updates({name: value})

    def apply_updates(self, updates: dict[str, object]) -> bool:
        """Validate the complete transaction before changing any field."""

        if self._closed or self.is_read_only or not isinstance(updates, dict):
            return False
        try:
            validated = {
                name: _validate_field(name, value)
                for name, value in updates.items()
            }
        except (TypeError, ValueError):
            return False
        if not validated or all(self._document.get(k) == v for k, v in validated.items()):
            return True

        self._document = {**self._document, **validated}
        self._revision += 1
        self._queue_write()
        for name, value in validated.items():
            self.changed.emit(name, value)
        return True

    def set_clock_visible(self, visible: bool) -> bool:
        return self.set("clock_visible", visible)

    def set_last_page(self, page_name: str) -> bool:
        return self.set("last_page", page_name)

    def set_mini_controller_preferences(
        self,
        *,
        visible: bool | None = None,
        collapsed: bool | None = None,
        x: int | None = None,
        y: int | None = None,
        always_on_top: bool | None = None,
    ) -> bool:
        current = self.snapshot().mini_controller
        candidate = current
        if visible is not None:
            candidate = replace(candidate, visible=visible)
        if collapsed is not None:
            candidate = replace(candidate, collapsed=collapsed)
        if x is not None or y is not None:
            if x is None or y is None:
                return False
            candidate = replace(candidate, position_is_set=True, x=x, y=y)
        if always_on_top is not None:
            candidate = replace(candidate, always_on_top=always_on_top)
        return self.set("mini_controller", candidate)

    def create_clock_widget(self) -> SystemClockWidget:
        """Create one clock instance; the launcher places it in the top bar."""

        if self._clock is None:
            self._clock = SystemClockWidget(self)
        return self._clock

    def capture_window(self, window: QWidget) -> bool:
        """Capture main-window placement immediately before safe shutdown."""

        try:
            geometry = window.saveGeometry()
            # Full-screen is not a supported Control Station preference.  It
            # has no native caption controls and must never be converted into
            # the approved maximized state during persistence.
            maximized = window.isMaximized() and not window.isFullScreen()
        except (AttributeError, RuntimeError):
            return False
        return self.apply_updates(
            {
                "window_geometry": geometry,
                "window_maximized": bool(maximized),
            }
        )

    def restore_window(self, window: QWidget) -> None:
        """Restore safe placement with an ordinary or maximized native frame."""

        preferences = self.snapshot()
        if preferences.window_geometry:
            window.restoreGeometry(preferences.window_geometry)

        # Qt's geometry blob can carry a window-state bit in addition to the
        # rectangle.  An old/full-screen blob therefore used to override the
        # separate validated preference and remove the Windows caption.  Only
        # normal and maximized are supported for the main Control Station.
        restored_state = window.windowState()
        safe_state = restored_state & ~Qt.WindowState.WindowFullScreen
        if preferences.window_maximized:
            safe_state |= Qt.WindowState.WindowMaximized
        else:
            safe_state &= ~Qt.WindowState.WindowMaximized
        if safe_state != restored_state:
            window.setWindowState(safe_state)

        if preferences.window_maximized:
            window.showMaximized()
            return

        frame = window.frameGeometry()
        screens = QGuiApplication.screens()
        if not screens:
            return
        target = max(
            screens,
            key=lambda screen: frame.intersected(screen.availableGeometry()).width()
            * frame.intersected(screen.availableGeometry()).height(),
        ).availableGeometry()

        # A small screen must not receive a minimum larger than itself.
        width = min(max(640, frame.width()), target.width())
        height = min(max(480, frame.height()), target.height())
        x = min(max(frame.x(), target.left()), target.right() - width + 1)
        y = min(max(frame.y(), target.top()), target.bottom() - height + 1)
        window.setGeometry(x, y, width, height)

    def shutdown(self) -> None:
        """Queue final preferences without waiting on disk from the GUI thread."""

        if self._closed:
            return
        self._closed = True
        self._error_timer.stop()
        self._writer.close(self._revision, dict(self._document))

    def _queue_write(self) -> None:
        if not self.is_read_only:
            self._writer.submit(self._revision, dict(self._document))

    def _deliver_write_errors(self) -> None:
        for message in self._writer.take_errors():
            self.write_failed.emit(message)
