"""AMBER-4 -- Today's Session Health.

Wires the Control Station's "Today's Session Health" card to real persisted
MYELIN facts through one new read-only projection
(``PERSISTENCE/session_health.py``), a second async/coalesced read lane in
``CONTROL_STATION/analytics.py``, and presentation-only rendering in
``CONTROL_STATION/launcher.py``.

Coverage mirrors the AMBER-4 roadmap's T1-T21 acceptance list:

    T1-T5    session / trigger boundary counting        (Section A)
    T6-T12   MIRL "Returns" law and integrity            (Section A)
    T13-T16  event-driven refresh routing                (Section B)
    T17-T19  presentation-only rendering                 (Section C)
    T20-T21  timezone independence, shutdown discipline   (Section D)

Section A's last two tests (duplicate / malformed MIRL evidence) leave the
shared scratch database's ``mirl_events`` table permanently unparsable by
``PERSISTENCE.storage.read_mirl_events`` -- that IS the fail-closed contract
under test -- so they are ordered last within Section A and nothing after
them in this file touches ``read_today_session_health`` against real
persistence again.  Sections B-D use injected fake providers or fabricated
snapshot objects, never the shared database, so they are order-independent.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import threading
from itertools import count

import pytest

import _lab  # noqa: F401 - installs the production tree and isolated APPDATA

import PERSISTENCE.storage as storage
from PERSISTENCE.database import connect_database
from PERSISTENCE.session_health import TodaySessionHealthSnapshot, read_today_session_health

storage.bootstrap_production_schema()

_MONOTONIC = count(1_000_000_000)


# ---------------------------------------------------------------------------
# Raw fixture-data helpers.  These write directly through their own SQLite
# connection rather than the queued production writer lane: AMBER-4 is a
# READ-side operation and no ``EngineStorage``/shared lane is constructed in
# this file, so there is no concurrent writer to race.
# ---------------------------------------------------------------------------


def _insert_session(*, started_at_utc: str, profile_type: str = "study") -> int:
    connection = connect_database(read_only=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            "INSERT INTO sessions(profile_type, started_at_utc) VALUES(?, ?)",
            (profile_type, started_at_utc),
        )
        connection.commit()
        return int(cursor.lastrowid)
    finally:
        connection.close()


def _insert_trigger(*, session_id: int, created_at_utc: str, candidate_uid: str) -> None:
    connection = connect_database(read_only=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO triggers"
            "(session_id, candidate_uid, occurred_monotonic_ns, payload_json, created_at_utc) "
            "VALUES(?, ?, ?, ?, ?)",
            (session_id, candidate_uid, next(_MONOTONIC), "{}", created_at_utc),
        )
        connection.commit()
    finally:
        connection.close()


def _insert_mirl_event(
    *,
    episode_id: str,
    event_name: str,
    occurred_wall_time_utc: str,
    reason: str = "",
    omit_episode_id: bool = False,
) -> None:
    """Insert one durable ``mirl_events`` row with a hand-built payload.

    Mirrors exactly the keys ``PERSISTENCE.storage.read_mirl_events`` reads:
    required (kind, event_name, event_class, event_id, episode_id,
    episode_sequence, occurred_monotonic_ns, occurred_wall_time_utc) and
    optional-with-default (reason, among others).
    """

    occurred_ns = next(_MONOTONIC)
    event_id = f"evt-{episode_id}-{occurred_ns}"
    payload = {
        "kind": f"MIRL_{event_name.upper()}",
        "event_name": event_name,
        "event_class": "DERIVED",
        "event_id": event_id,
        "episode_id": episode_id,
        "episode_sequence": 1,
        "occurred_monotonic_ns": occurred_ns,
        "occurred_wall_time_utc": occurred_wall_time_utc,
        "reason": reason,
    }
    if omit_episode_id:
        del payload["episode_id"]
    connection = connect_database(read_only=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "INSERT INTO mirl_events"
            "(event_id, session_id, episode_id, episode_sequence, event_name, "
            "occurred_monotonic_ns, payload_json, created_at_utc) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_id,
                None,
                "" if omit_episode_id else episode_id,
                1,
                event_name,
                occurred_ns,
                json.dumps(payload),
                occurred_wall_time_utc,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def _window(day: str) -> dict:
    return {
        "local_date_iso": day,
        "window_start_utc": f"{day}T00:00:00.000000Z",
        "window_end_utc": _next_day_start(day),
    }


def _next_day_start(day: str) -> str:
    from datetime import date, timedelta

    year, month, dom = (int(part) for part in day.split("-"))
    nxt = date(year, month, dom) + timedelta(days=1)
    return f"{nxt.isoformat()}T00:00:00.000000Z"


# ---------------------------------------------------------------------------
# Section A -- the read model: sessions, triggers, returns, integrity
# ---------------------------------------------------------------------------


def test_t1_empty_window_reads_all_zero():
    snapshot = read_today_session_health(**_window("2000-01-01"))
    assert snapshot.session_count == 0
    assert snapshot.returned_episode_count == 0
    assert snapshot.trigger_count == 0
    assert isinstance(snapshot, TodaySessionHealthSnapshot)


def test_t2_t3_session_start_boundary_is_half_open():
    window = _window("2001-02-01")
    _insert_session(started_at_utc=window["window_start_utc"])  # T2: included
    _insert_session(started_at_utc=window["window_end_utc"])  # T3: excluded
    snapshot = read_today_session_health(**window)
    assert snapshot.session_count == 1


def test_t4_t5_trigger_boundary_is_half_open():
    window = _window("2001-03-01")
    session_id = _insert_session(started_at_utc="1999-01-01T00:00:00.000000Z")
    _insert_trigger(
        session_id=session_id,
        created_at_utc=window["window_start_utc"],
        candidate_uid="cand-t4-included",
    )
    _insert_trigger(
        session_id=session_id,
        created_at_utc=window["window_end_utc"],
        candidate_uid="cand-t5-excluded",
    )
    snapshot = read_today_session_health(**window)
    assert snapshot.trigger_count == 1


def test_t6_t7_return_verified_alone_or_before_relapse_never_counts():
    window = _window("2001-04-01")
    mid = f"{window['local_date_iso']}T12:00:00.000000Z"
    # T6: a lone RETURN_VERIFIED (10s confirmation only) is not a Return.
    _insert_mirl_event(
        episode_id="ep-t6",
        event_name="return_verified",
        occurred_wall_time_utc=mid,
    )
    # T7: RETURN_VERIFIED followed by a relapse that closes the episode
    # WITHOUT reason RETURNED must still not count.
    _insert_mirl_event(
        episode_id="ep-t7",
        event_name="return_verified",
        occurred_wall_time_utc=mid,
    )
    _insert_mirl_event(
        episode_id="ep-t7",
        event_name="episode_closed",
        reason="ABORTED",
        occurred_wall_time_utc=mid,
    )
    snapshot = read_today_session_health(**window)
    assert snapshot.returned_episode_count == 0


def test_t8_episode_closed_returned_counts_exactly_one():
    window = _window("2001-05-01")
    _insert_mirl_event(
        episode_id="ep-t8",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc=f"{window['local_date_iso']}T08:00:00.000000Z",
    )
    snapshot = read_today_session_health(**window)
    assert snapshot.returned_episode_count == 1


@pytest.mark.parametrize("reason", ["ABORTED", "EMERGENCY", "SESSION_ENDED"])
def test_t9_t10_non_returned_closures_never_count(reason):
    window = _window("2001-06-01")
    _insert_mirl_event(
        episode_id=f"ep-t9-{reason}",
        event_name="episode_closed",
        reason=reason,
        occurred_wall_time_utc=f"{window['local_date_iso']}T09:00:00.000000Z",
    )
    snapshot = read_today_session_health(**window)
    assert snapshot.returned_episode_count == 0


def test_t11_returned_episode_outside_window_is_not_counted():
    target_window = _window("2001-07-01")
    _insert_mirl_event(
        episode_id="ep-t11",
        event_name="episode_closed",
        reason="RETURNED",
        # A real returned closure, but on a different day than we query.
        occurred_wall_time_utc="2001-07-02T00:00:00.000001Z",
    )
    snapshot = read_today_session_health(**target_window)
    assert snapshot.returned_episode_count == 0

    other_window = _window("2001-07-02")
    snapshot_other_day = read_today_session_health(**other_window)
    assert snapshot_other_day.returned_episode_count == 1


def test_t18_t19_valid_snapshots_carry_exact_integers():
    """T18 (all-zero) and T19 (populated) round-trip through the real reader."""

    zero_window = _window("2001-08-01")
    zero_snapshot = read_today_session_health(**zero_window)
    assert (
        zero_snapshot.session_count,
        zero_snapshot.returned_episode_count,
        zero_snapshot.trigger_count,
    ) == (0, 0, 0)

    populated_window = _window("2001-08-02")
    _insert_session(started_at_utc=f"{populated_window['local_date_iso']}T01:00:00.000000Z")
    _insert_session(started_at_utc=f"{populated_window['local_date_iso']}T02:00:00.000000Z")
    session_id = _insert_session(
        started_at_utc=f"{populated_window['local_date_iso']}T03:00:00.000000Z"
    )
    for index in range(7):
        _insert_trigger(
            session_id=session_id,
            created_at_utc=f"{populated_window['local_date_iso']}T04:00:0{index}.000000Z",
            candidate_uid=f"cand-t19-{index}",
        )
    _insert_mirl_event(
        episode_id="ep-t19-a",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc=f"{populated_window['local_date_iso']}T05:00:00.000000Z",
    )
    _insert_mirl_event(
        episode_id="ep-t19-b",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc=f"{populated_window['local_date_iso']}T06:00:00.000000Z",
    )
    populated_snapshot = read_today_session_health(**populated_window)
    assert populated_snapshot.session_count == 3
    assert populated_snapshot.trigger_count == 7
    assert populated_snapshot.returned_episode_count == 2


# -- fail-closed tests: ORDER-SENSITIVE, must stay last in Section A --------
#
# ``_returned_episode_count`` scans every mirl_events row through
# ``PERSISTENCE.storage.read_mirl_events`` (not windowed at the SQL level),
# so once a malformed row exists it makes EVERY later
# ``read_today_session_health`` call in this process raise.  Nothing below
# this point may call it against the shared scratch database again.


def test_t12a_duplicate_returned_closure_fails_closed():
    window = _window("2001-09-01")
    stamp = f"{window['local_date_iso']}T10:00:00.000000Z"
    _insert_mirl_event(
        episode_id="ep-t12-dup",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc=stamp,
    )
    _insert_mirl_event(
        episode_id="ep-t12-dup",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc=stamp,
    )
    with pytest.raises(ValueError, match="duplicate"):
        read_today_session_health(**window)


def test_t12c_cross_midnight_duplicate_returned_closure_fails_closed():
    """Duplicate-episode identity is global, not a property of one window.

    One RETURNED closure just before a midnight boundary and a second,
    duplicate RETURNED closure for the SAME episode just after it: neither
    day's window alone contains both rows, so a per-window duplicate check
    would let both slip through as two unrelated single closures. The
    integrity check must catch this regardless of which day is queried.
    """

    window = _window("2001-09-02")
    _insert_mirl_event(
        episode_id="ep-t12c-cross-midnight",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc="2001-09-02T23:59:59.000000Z",
    )
    _insert_mirl_event(
        episode_id="ep-t12c-cross-midnight",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc="2001-09-03T00:00:01.000000Z",
    )
    with pytest.raises(ValueError, match="duplicate"):
        read_today_session_health(**window)


def test_t12b_malformed_returned_payload_fails_closed():
    window = _window("2001-10-01")
    _insert_mirl_event(
        episode_id="ep-t12-malformed",
        event_name="episode_closed",
        reason="RETURNED",
        occurred_wall_time_utc=f"{window['local_date_iso']}T11:00:00.000000Z",
        omit_episode_id=True,
    )
    with pytest.raises(Exception):
        read_today_session_health(**window)


# ---------------------------------------------------------------------------
# Section B -- AnalyticsController event-driven refresh routing (T13-T16)
# Uses injected fake providers; never touches the shared database above.
# ---------------------------------------------------------------------------

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from CONTROL_STATION.analytics import (  # noqa: E402
    PAGE_CONTROL,
    PAGE_METRIC_HUB,
    AnalyticsController,
)


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class _FakeReportAccess:
    def refusal(self):
        return None

    def begin_export(self, owner: str):
        raise AssertionError("not exercised in this file")


class _RedGuard:
    def allow_surface(self, kind):
        return True

    def restore_authoritative_surface(self):
        pass


class _RecordingProvider:
    """A today-health provider that records calls without blocking."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.call_count = 0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.call_count += 1
        self.entered.set()
        return TodaySessionHealthSnapshot(
            local_date_iso="2020-01-01",
            window_start_utc="2020-01-01T00:00:00.000000Z",
            window_end_utc="2020-01-02T00:00:00.000000Z",
            session_count=0,
            returned_episode_count=0,
            trigger_count=0,
            generated_at_utc="2020-01-01T00:00:00.000000Z",
        )


class _Event:
    def __init__(self, *, kind: str) -> None:
        self.kind = kind


def _unused_snapshot_provider():
    raise AssertionError("the dashboard-bundle lane is not exercised in this file")


def _controller(provider=None) -> AnalyticsController:
    return AnalyticsController(
        report_access=_FakeReportAccess(),
        red_guard=_RedGuard(),
        snapshot_provider=_unused_snapshot_provider,
        today_health_provider=provider or _RecordingProvider(),
    )


def test_t13_control_page_open_requests_today_health_refresh(qt_app):
    provider = _RecordingProvider()
    controller = _controller(provider)
    try:
        controller.page_opened(PAGE_CONTROL)
        assert provider.entered.wait(5.0)
    finally:
        controller.shutdown(timeout=5.0)


def test_t13b_analytics_page_open_does_not_touch_today_health(qt_app):
    provider = _RecordingProvider()
    controller = _controller(provider)
    try:
        controller.create_metric_hub_page()
        controller.page_opened(PAGE_METRIC_HUB)
        assert not provider.entered.wait(0.3)
    finally:
        controller.shutdown(timeout=5.0)


def test_t14_trigger_telemetry_requests_refresh(qt_app):
    provider = _RecordingProvider()
    controller = _controller(provider)
    try:
        controller.telemetry_received(_Event(kind="trigger"))
        assert provider.entered.wait(5.0)
    finally:
        controller.shutdown(timeout=5.0)


def test_t15_sine_verified_return_telemetry_requests_refresh(qt_app):
    provider = _RecordingProvider()
    controller = _controller(provider)
    try:
        controller.telemetry_received(_Event(kind="sine_verified_return"))
        assert provider.entered.wait(5.0)
    finally:
        controller.shutdown(timeout=5.0)


def test_t16_ordinary_activity_telemetry_does_not_request_refresh(qt_app):
    provider = _RecordingProvider()
    controller = _controller(provider)
    try:
        controller.telemetry_received(_Event(kind="activity"))
        assert not provider.entered.wait(0.3)
    finally:
        controller.shutdown(timeout=5.0)


def test_t13c_engine_status_change_requests_refresh(qt_app):
    provider = _RecordingProvider()
    controller = _controller(provider)
    try:
        controller.engine_status_changed(object())
        assert provider.entered.wait(5.0)
    finally:
        controller.shutdown(timeout=5.0)


def test_t21_shutdown_drains_the_today_health_worker(qt_app):
    class _Gate:
        def __init__(self) -> None:
            self.entered = threading.Event()
            self.release = threading.Event()

        def __call__(self):
            self.entered.set()
            self.release.wait(20.0)
            return TodaySessionHealthSnapshot(
                local_date_iso="2020-01-01",
                window_start_utc="2020-01-01T00:00:00.000000Z",
                window_end_utc="2020-01-02T00:00:00.000000Z",
                session_count=0,
                returned_episode_count=0,
                trigger_count=0,
                generated_at_utc="2020-01-01T00:00:00.000000Z",
            )

    gate = _Gate()
    controller = _controller(gate)
    controller.request_today_session_health_refresh()
    assert gate.entered.wait(10.0)

    assert controller.shutdown(timeout=0.4) is False

    gate.release.set()
    assert controller.shutdown(timeout=10.0) is True
    assert not any(
        thread.name == "MyelinAnalyticsRefresh" and thread.is_alive()
        for thread in threading.enumerate()
    )


# ---------------------------------------------------------------------------
# Section C -- presentation-only rendering (T17-T19)
# Fabricated snapshot objects only; never touches persistence.
# ---------------------------------------------------------------------------

from PyQt6.QtCore import QObject, pyqtSignal  # noqa: E402

from CONTROL_STATION.launcher import ControlPage  # noqa: E402


class _EngineStub(QObject):
    engine_status_changed = pyqtSignal(object)

    def pause(self):
        return True

    def resume(self):
        return True

    def set_profile_type(self, _profile):
        return True


class _LifecycleStub:
    def request_start(self):
        return True

    def request_stop(self):
        return True

    def request_emergency(self):
        return True


class _ProfilesStub:
    def all_profiles(self):
        from types import SimpleNamespace

        return (SimpleNamespace(label="General", key="general"),)

    def set_active(self, _key):
        return True


def _control_page(qt_app) -> ControlPage:
    return ControlPage(engine=_EngineStub(), lifecycle=_LifecycleStub(), profiles=_ProfilesStub())


def test_t19_populated_snapshot_renders_exact_integers(qt_app):
    page = _control_page(qt_app)
    snapshot = TodaySessionHealthSnapshot(
        local_date_iso="2020-01-01",
        window_start_utc="2020-01-01T00:00:00.000000Z",
        window_end_utc="2020-01-02T00:00:00.000000Z",
        session_count=3,
        returned_episode_count=2,
        trigger_count=7,
        generated_at_utc="2020-01-01T00:00:00.000000Z",
    )
    page.render_today_session_health(snapshot)
    assert page._stat_sessions.text() == "3"
    assert page._stat_returns.text() == "2"
    assert page._stat_triggers.text() == "7"
    assert page._health_hint.text() == "Resets 00:00 local"


def test_t18_zero_snapshot_renders_real_zero_not_dash(qt_app):
    page = _control_page(qt_app)
    snapshot = TodaySessionHealthSnapshot(
        local_date_iso="2020-01-01",
        window_start_utc="2020-01-01T00:00:00.000000Z",
        window_end_utc="2020-01-02T00:00:00.000000Z",
        session_count=0,
        returned_episode_count=0,
        trigger_count=0,
        generated_at_utc="2020-01-01T00:00:00.000000Z",
    )
    page.render_today_session_health(snapshot)
    assert page._stat_sessions.text() == "0"
    assert page._stat_returns.text() == "0"
    assert page._stat_triggers.text() == "0"


def test_t17_initial_state_is_loading_not_zero(qt_app):
    page = _control_page(qt_app)
    assert page._stat_sessions.text() == "—"
    assert page._stat_returns.text() == "—"
    assert page._stat_triggers.text() == "—"
    assert page._health_hint.text() == "Loading"


def test_t17b_provider_failure_shows_unavailable_never_zero(qt_app):
    page = _control_page(qt_app)
    # Prove the sequence a real failed read produces: render once populated,
    # then a failed refresh must still clear it to the honest unavailable
    # state rather than a believable zero.
    page.render_today_session_health(
        TodaySessionHealthSnapshot(
            local_date_iso="2020-01-01",
            window_start_utc="2020-01-01T00:00:00.000000Z",
            window_end_utc="2020-01-02T00:00:00.000000Z",
            session_count=5,
            returned_episode_count=1,
            trigger_count=2,
            generated_at_utc="2020-01-01T00:00:00.000000Z",
        )
    )
    page.show_today_session_health_unavailable()
    assert page._stat_sessions.text() == "—"
    assert page._stat_returns.text() == "—"
    assert page._stat_triggers.text() == "—"
    assert page._health_hint.text() == "Unavailable"


@pytest.mark.parametrize("bad_value", [True, False, 1.5, "3", -1])
def test_exact_integer_display_never_coerces_a_believable_number(bad_value):
    """``_display_count`` shows a number ONLY for an exact non-negative int.

    ``True``/``False`` are rejected even though ``bool`` is an ``int``
    subclass in Python; ``1.5`` and ``"3"`` must not be silently truncated
    or parsed; ``-1`` is not a count. No Qt instance is needed -- this is a
    plain ``@staticmethod``.
    """

    assert ControlPage._display_count(bad_value) == "—"


def test_exact_integer_display_shows_a_valid_zero_or_positive_count():
    assert ControlPage._display_count(0) == "0"
    assert ControlPage._display_count(7) == "7"


@pytest.mark.parametrize(
    "field", ["session_count", "returned_episode_count", "trigger_count"]
)
@pytest.mark.parametrize("bad_value", [True, False, 1.5, "3", -1])
def test_snapshot_rejects_non_exact_or_negative_counts(field, bad_value):
    """The read model itself guarantees its exact-integer contract.

    ``TodaySessionHealthSnapshot`` must refuse to even construct with a
    coercible-looking but non-conforming value, so no caller downstream of
    the read model -- launcher included -- can ever be handed one.
    """

    kwargs = dict(
        local_date_iso="2020-01-01",
        window_start_utc="2020-01-01T00:00:00.000000Z",
        window_end_utc="2020-01-02T00:00:00.000000Z",
        session_count=0,
        returned_episode_count=0,
        trigger_count=0,
        generated_at_utc="2020-01-01T00:00:00.000000Z",
    )
    kwargs[field] = bad_value
    with pytest.raises(ValueError):
        TodaySessionHealthSnapshot(**kwargs)


def test_snapshot_accepts_valid_zero_and_positive_counts():
    snapshot = TodaySessionHealthSnapshot(
        local_date_iso="2020-01-01",
        window_start_utc="2020-01-01T00:00:00.000000Z",
        window_end_utc="2020-01-02T00:00:00.000000Z",
        session_count=0,
        returned_episode_count=3,
        trigger_count=12,
        generated_at_utc="2020-01-01T00:00:00.000000Z",
    )
    assert (snapshot.session_count, snapshot.returned_episode_count, snapshot.trigger_count) == (
        0,
        3,
        12,
    )


# ---------------------------------------------------------------------------
# Section D -- timezone independence, forbidden shortcuts, frozen files
# ---------------------------------------------------------------------------


from datetime import date as _date, datetime as _datetime, timedelta as _timedelta, timezone as _timezone  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from CONTROL_STATION.analytics import _local_day_window_utc  # noqa: E402


def test_t20_local_day_helpers_never_read_the_header_clock_timezone():
    """Structural proof: neither local-day function touches Settings/the clock.

    ``CONTROL_STATION/settings.py``'s own docstring says the header clock's
    timezone selection changes the Control Station clock only. This asserts
    the two functions that resolve Today Health's local day (the default
    provider, and the boundary helper it calls) never reference Settings,
    the clock, or any named timezone choice -- so there is no code path by
    which that selection could reach the daily analytics window.
    """

    import CONTROL_STATION.analytics as analytics_module

    tree = ast.parse(open(analytics_module.__file__, encoding="utf-8").read())
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name
        in {"_default_today_session_health_provider", "_local_day_window_utc"}
    ]
    assert len(functions) == 2
    forbidden = {"settings", "Settings", "TIMEZONE_CHOICES", "clock"}
    for function in functions:
        referenced = {
            node.id
            for node in ast.walk(function)
            if isinstance(node, ast.Name) and node.id in forbidden
        } | {
            node.attr
            for node in ast.walk(function)
            if isinstance(node, ast.Attribute) and node.attr in forbidden
        }
        assert not referenced, (
            f"{function.name} references {referenced!r}; "
            "it must derive the local day from the OS only"
        )


def test_t20b_normal_civil_day_is_a_plain_24_hour_span():
    """Outside a DST transition, a local day is exactly 24 hours."""

    start, end = _local_day_window_utc(
        _date(2026, 6, 15), zone=ZoneInfo("Asia/Kolkata")
    )
    assert end - start == _timedelta(hours=24)


def test_t20c_dst_spring_forward_day_is_23_hours_not_24():
    """A civil day containing a DST spring-forward is really 23 hours.

    2026-03-08 is the US spring-forward date in America/New_York: local
    midnight on the 8th is still EST (UTC-5); local midnight on the 9th is
    already EDT (UTC-4). The OLD implementation (one aware fixed-offset
    midnight + ``timedelta(days=1)``) reused the 8th's offset for the 9th's
    boundary too and would have silently produced a wrong 24-hour span.
    """

    zone = ZoneInfo("America/New_York")
    start, end = _local_day_window_utc(_date(2026, 3, 8), zone=zone)
    assert end - start == _timedelta(hours=23)
    # Each boundary independently carries its OWN correct offset.
    assert start == _datetime(2026, 3, 8, 5, 0, tzinfo=_timezone.utc)
    assert end == _datetime(2026, 3, 9, 4, 0, tzinfo=_timezone.utc)


def test_t20d_dst_fall_back_day_is_25_hours_not_24():
    """The symmetric case: a civil day containing fall-back is 25 hours."""

    zone = ZoneInfo("America/New_York")
    start, end = _local_day_window_utc(_date(2026, 11, 1), zone=zone)
    assert end - start == _timedelta(hours=25)


def test_t20e_production_path_resolves_via_the_real_os_clock_without_error():
    """No injected zone: the real production path used by the default provider.

    The host's configured zone is unknown to this test, so it cannot assert
    a specific span -- it proves the no-``zone`` path (the one production
    actually calls) succeeds and orders start strictly before end.
    """

    start, end = _local_day_window_utc(_date.today())
    assert start < end


def test_launcher_contains_no_direct_sql_or_sqlite():
    source = _lab.ULTIMATE.joinpath("CONTROL_STATION", "launcher.py").read_text(
        encoding="utf-8"
    )
    lowered = source.lower()
    for forbidden in ("sqlite3", "connect_database", "select ", "insert into"):
        assert forbidden not in lowered, f"launcher.py must not contain {forbidden!r}"


_FROZEN_SHA256 = {
    ("PERSISTENCE", "storage.py"): (
        "5e0a0d7a70352088e6a6c4bb106c67ab7f0b3a4af729928497433cf8a2c49f34"
    ),
    ("PERSISTENCE", "schema.py"): (
        "820160c6e397836d001e434cd7a31b82b8ce8c9d206c3f3be1e1316d2668b6c9"
    ),
    ("PERSISTENCE", "database.py"): (
        "c4331c45ee939e307fd38d6ccf5a6b101a312449f61cc28395065f8195d64bd9"
    ),
}


@pytest.mark.parametrize("relative_parts", list(_FROZEN_SHA256))
def test_frozen_persistence_files_are_byte_identical(relative_parts):
    path = _lab.ULTIMATE.joinpath(*relative_parts)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == _FROZEN_SHA256[relative_parts], (
        f"{'/'.join(relative_parts)} changed but AMBER-4 must leave it frozen"
    )
