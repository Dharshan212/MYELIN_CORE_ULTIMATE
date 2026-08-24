"""Phase 2 external lab: semantic telemetry truth and GUI transport."""

from __future__ import annotations

import inspect
import queue
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


ULTIMATE = Path(r"C:\Users\Dharshan\Downloads\MYELIN_GENALOGY\MYELIN2.0_ULTIMATE")
if str(ULTIMATE) not in sys.path:
    sys.path.insert(0, str(ULTIMATE))

from CONTROL_STATION.controller import ControlStationController, TelemetryEvent
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication, QSizePolicy

from CONTROL_STATION.launcher import (
    ControlPage,
    ControlStationWindow,
    FeedList,
    FeedTag,
)
from CORE_ENGINE.monitor import (
    ForegroundObservation,
    MonitorContext,
    PendingTriggerWorkflow,
    WindowsMonitorCoordinator,
)
from CORE_ENGINE.resource_intent import ResourceIntent, ResourceSurface
from CORE_ENGINE.blacklist import SineThresholdPolicy
from _lab import Engine, INSTAGRAM, MRBEAST


class _Live:
    def __init__(self, value=None) -> None:
        self.value = value

    def live_view(self):
        return self.value


class _Cosine:
    def __init__(self, phase="IDLE") -> None:
        self.phase = phase

    def snapshot(self, *, now_ns):
        return SimpleNamespace(phase=self.phase)


def _context(*, process_name="chrome", title="Ordinary page"):
    return MonitorContext(
        foreground=ForegroundObservation(
            sequence=1,
            hwnd=10,
            process_id=20,
            process_name=process_name,
            window_title=title,
            observed_monotonic_ns=10_000_000_000,
            observed_wall_time_utc="2026-08-24T00:00:00+00:00",
            idle_seconds=0.0,
        ),
        browser_evidence=SimpleNamespace(),
        resource_intent=SimpleNamespace(),
    )


def _semantic_coordinator(
    *,
    classification=ResourceIntent.UNCERTAIN,
    surface=ResourceSurface.WEB_CONTENT,
    blacklist=None,
    cosine_phase="IDLE",
):
    coordinator = object.__new__(WindowsMonitorCoordinator)
    coordinator.services = SimpleNamespace(
        resource_intent=_Live(
            SimpleNamespace(
                classification=classification,
                resource_surface=surface,
            )
        ),
        blacklist=_Live(blacklist),
        cosine=_Cosine(cosine_phase),
        sine=_Live(
            SimpleNamespace(
                stage_2_delay_seconds_applied=600.0,
                stage_3_delay_seconds_applied=795.0,
            )
        ),
    )
    coordinator._pending_dwell_telemetry = None
    return coordinator


def _actionable_blacklist(label="YOUTUBE"):
    return SimpleNamespace(
        disposition="accused",
        resource_label=label,
    )


def test_p2_01_02_normal_web_and_native_activity_are_activity():
    coordinator = _semantic_coordinator()
    assert coordinator._activity_telemetry_semantics(_context()) == (
        "ACTIVITY",
        "cyan",
    )
    assert coordinator._activity_telemetry_semantics(
        _context(process_name="python", title="worker.py")
    )[0] == "ACTIVITY"


def test_p2_03_social_uses_authoritative_blacklist_not_title_guessing():
    social = _semantic_coordinator(blacklist=_actionable_blacklist())
    assert social._activity_telemetry_semantics(_context())[0] == "SOCIAL"

    title_only = _semantic_coordinator(blacklist=None)
    assert title_only._activity_telemetry_semantics(
        _context(title="YouTube Instagram Snapchat")
    )[0] == "ACTIVITY"


def test_p2_04_dwell_is_a_separate_bounded_fact():
    coordinator = _semantic_coordinator(blacklist=_actionable_blacklist())
    assert coordinator._activity_telemetry_semantics(_context())[0] == "SOCIAL"
    snapshot = SimpleNamespace(
        restarted=True,
        study_context_active=False,
        verdict=SimpleNamespace(
            disposition="accused",
            display_label="YouTube",
            platform_key="youtube",
        ),
    )
    coordinator._prepare_dwell_telemetry(snapshot)
    prepared = coordinator._pending_dwell_telemetry
    assert prepared["badge"] == "DWELL"
    assert prepared["feed_text"] == "YOUTUBE — person is dwelling"
    assert prepared["tone"] == "violet"

    coordinator._prepare_dwell_telemetry(
        SimpleNamespace(
            restarted=False,
            study_context_active=False,
            verdict=snapshot.verdict,
        )
    )
    assert coordinator._pending_dwell_telemetry is None


def test_p2_05_founding_trigger_emits_exactly_one_prepared_trigger_row():
    coordinator = object.__new__(WindowsMonitorCoordinator)
    coordinator.telemetry_queue = queue.Queue()
    coordinator._pending_trigger = PendingTriggerWorkflow(
        candidate_uid="candidate-1",
        candidate=object(),
        receipt_id="receipt-1",
        submitted_monotonic_ns=1,
    )
    forgotten = []
    coordinator.services = SimpleNamespace(
        trigger=SimpleNamespace(
            confirm_durable_admission=lambda **kwargs: True,
        ),
        mirl=SimpleNamespace(
            prepare_trigger=lambda **kwargs: object(),
            drain_events=lambda: (),
        ),
        sine=SimpleNamespace(request_trigger=lambda **kwargs: True),
        storage=SimpleNamespace(forget_receipt=forgotten.append),
    )
    coordinator._persist_mirl_events = lambda events: None
    coordinator._console_history = lambda message: None
    receipt = {
        "receipt_id": "receipt-1",
        "state": "COMMITTED",
        "result_id": 77,
    }

    coordinator._apply_trigger_receipt(receipt)
    coordinator._apply_trigger_receipt(receipt)

    rows = []
    while not coordinator.telemetry_queue.empty():
        rows.append(coordinator.telemetry_queue.get_nowait())
    trigger_rows = [row for row in rows if row.get("badge") == "TRIGGER"]
    assert len(trigger_rows) == 1
    assert trigger_rows[0]["feed_text"] == "SINE 1 — triggered"
    assert trigger_rows[0]["tone"] == "red"


def test_p2_06_07_sine_schedule_and_accepted_return_are_fact_mapped():
    coordinator = _semantic_coordinator()
    stage_2 = coordinator._semantic_domain_telemetry(
        "sine", SimpleNamespace(kind="SINE_STAGE_2_SCHEDULED")
    )
    stage_3 = coordinator._semantic_domain_telemetry(
        "sine", SimpleNamespace(kind="SINE_STAGE_3_SCHEDULED")
    )
    accepted = coordinator._semantic_domain_telemetry(
        "sine", SimpleNamespace(kind="SINE_RETURN_INTENT_RECORDED")
    )
    rejected = coordinator._semantic_domain_telemetry(
        "sine", SimpleNamespace(kind="SINE_RESPONSE_REJECTED")
    )

    assert stage_2 == {
        "badge": "SINE",
        "feed_text": "SINE 2 — stage scheduled for 600 s",
        "tone": "amber",
    }
    assert stage_3["feed_text"] == "SINE 3 — stage scheduled for 795 s"
    assert accepted["badge"] == "MONITOR"
    assert accepted["feed_text"] == "USER PRESSED — I'M BACK"
    assert rejected == {}


def test_p2_08_09_10_mirl_events_map_by_kind_and_use_factual_target():
    coordinator = _semantic_coordinator()
    verification = coordinator._semantic_domain_telemetry(
        "mirl", SimpleNamespace(kind="MIRL_RETURN_VERIFICATION_STARTED")
    )
    returned = coordinator._semantic_domain_telemetry(
        "mirl", SimpleNamespace(kind="MIRL_RETURN_VERIFIED")
    )
    closure = coordinator._semantic_domain_telemetry(
        "mirl",
        SimpleNamespace(
            kind="MIRL_CLOSURE_CONFIRMATION_STARTED",
            target_seconds=73.5,
        ),
    )
    closed = coordinator._semantic_domain_telemetry(
        "mirl", SimpleNamespace(kind="MIRL_EPISODE_CLOSED")
    )

    assert verification == {
        "badge": "RETURN INTENT",
        "feed_text": "RETURN UNVERIFIED — verification started",
        "tone": "amber",
    }
    assert returned["badge"] == "RETURNED"
    assert returned["feed_text"] == "USER RETURNED — WELCOME BACK TO FOCUS"
    assert closure["badge"] == "MIRL"
    assert closure["feed_text"].endswith("73.5 s")
    assert closed["feed_text"] == "EPISODE CLOSED"


def test_p2_11_12_ott_and_messaging_are_authoritative_activity_tags():
    ott = _semantic_coordinator(cosine_phase="ACTIVE")
    assert ott._activity_telemetry_semantics(_context())[0] == "OTT"

    messaging = _semantic_coordinator(surface=ResourceSurface.MESSAGING)
    assert messaging._activity_telemetry_semantics(_context())[0] == "MESSAGING"


def test_p2_13_reserved_future_badges_were_not_added():
    domain_source = inspect.getsource(WindowsMonitorCoordinator._semantic_domain_telemetry)
    activity_source = inspect.getsource(WindowsMonitorCoordinator._activity_telemetry_semantics)
    assert '"badge": "COSINE"' not in domain_source
    assert '"badge": "MINE"' not in domain_source
    assert 'return "COSINE"' not in activity_source
    assert 'return "MINE"' not in activity_source


def test_p2_14_controller_round_trip_preserves_all_semantic_fields():
    emitted = []
    fake = SimpleNamespace(
        _telemetry_queue=queue.Queue(),
        _route_prepared_view=lambda kind, raw: False,
        telemetry_received=SimpleNamespace(emit=emitted.append),
    )
    fake._telemetry_queue.put_nowait(
        {
            "time": "2026-08-24T00:00:00+00:00",
            "kind": "activity",
            "app": "YouTube",
            "title": "Certified video",
            "message": "Foreground activity observed",
            "badge": "SOCIAL",
            "feed_text": "PREPARED EXACTLY",
            "tone": "amber",
        }
    )

    assert ControlStationController._drain_telemetry(fake, drain_all=True) == 1
    assert emitted == [
        TelemetryEvent(
            time="2026-08-24T00:00:00+00:00",
            kind="activity",
            app="YouTube",
            title="Certified video",
            message="Foreground activity observed",
            badge="SOCIAL",
            feed_text="PREPARED EXACTLY",
            tone="amber",
        )
    ]


def test_p2_sine_fact_reaches_presenter_and_semantic_live_telemetry():
    applied = []
    emitted = []
    fact = SimpleNamespace(kind="SINE_STAGE_2_SCHEDULED")
    ignored_signal = SimpleNamespace(emit=lambda value: None)
    fake = SimpleNamespace(
        _telemetry_queue=queue.Queue(),
        _sine_presenter=SimpleNamespace(apply_fact=applied.append),
        telemetry_received=SimpleNamespace(emit=emitted.append),
        control_view_changed=ignored_signal,
        study_view_changed=ignored_signal,
        cosine_live_status_changed=ignored_signal,
        resource_intent_live_status_changed=ignored_signal,
        sine_watch_status_changed=ignored_signal,
        mine_watch_status_changed=ignored_signal,
        mirl_health_status_changed=ignored_signal,
    )
    fake._route_prepared_view = lambda kind, raw: (
        ControlStationController._route_prepared_view(fake, kind, raw)
    )
    fake._telemetry_queue.put_nowait(
        {
            "time": "2026-08-24T00:00:00+00:00",
            "kind": "sine_fact",
            "app": "",
            "title": "",
            "message": "SINE 2 was scheduled from factual SINE 1 display",
            "badge": "SINE",
            "feed_text": "SINE 2 — stage scheduled for 600 s",
            "tone": "amber",
            "fact": fact,
        }
    )

    assert ControlStationController._drain_telemetry(fake, drain_all=True) == 1
    assert applied == [fact]
    assert emitted == [
        TelemetryEvent(
            time="2026-08-24T00:00:00+00:00",
            kind="sine_fact",
            app="",
            title="",
            message="SINE 2 was scheduled from factual SINE 1 display",
            badge="SINE",
            feed_text="SINE 2 — stage scheduled for 600 s",
            tone="amber",
        )
    ]

    plain_fact = SimpleNamespace(kind="SINE_DISPLAYED")
    assert ControlStationController._route_prepared_view(
        fake,
        "sine_fact",
        {"fact": plain_fact},
    ) is True
    assert applied == [fact, plain_fact]


def _render(event):
    appended = []
    fake = SimpleNamespace(
        pages=SimpleNamespace(
            control=SimpleNamespace(
                append_telemetry=lambda **payload: appended.append(payload)
            )
        ),
        _activity_time=ControlStationWindow._activity_time,
        _activity_title=ControlStationWindow._activity_title,
    )
    ControlStationWindow._print_telemetry_event(fake, event)
    return appended


def test_p2_14_15_launcher_renders_badge_unchanged_and_activity_falls_back_safely():
    social = _render(
        TelemetryEvent(
            time="2026-08-24T00:00:00+00:00",
            kind="activity",
            app="YouTube",
            title="Certified video",
            message="Foreground activity observed",
            badge="SOCIAL",
            feed_text="PREPARED SOCIAL",
            tone="amber",
        )
    )
    ordinary = _render(
        TelemetryEvent(
            time="2026-08-24T00:00:00+00:00",
            kind="activity",
            app="Python",
            title="worker.py",
            message="Foreground activity observed",
        )
    )
    trigger = _render(
        TelemetryEvent(
            time="2026-08-24T00:00:00+00:00",
            kind="trigger",
            app="MYELIN",
            title="",
            message="accepted",
            badge="TRIGGER",
            feed_text="SINE 1 — triggered",
            tone="amber",
        )
    )

    assert social[0]["tag"] == "SOCIAL"
    assert social[0]["text"] == "PREPARED SOCIAL"
    assert ordinary[0]["tag"] == "ACTIVITY"
    assert ordinary[0]["tag"] != "DWELL"
    assert trigger[0]["tag"] == "TRIGGER"


def test_p2_study_a_b_study_precedence_survives_transport_and_rendering():
    coordinator = _semantic_coordinator(
        classification=ResourceIntent.STUDY_ALIGNED,
        surface=ResourceSurface.YOUTUBE_WATCH,
        blacklist=_actionable_blacklist(),
        cosine_phase="ACTIVE",
    )
    assert coordinator._activity_telemetry_semantics(_context())[0] == "STUDY"

    rendered = _render(
        TelemetryEvent(
            time="2026-08-24T00:00:00+00:00",
            kind="activity",
            app="YouTube",
            title="Lecture",
            message="Foreground activity observed",
            badge="STUDY",
        )
    )
    assert rendered[0]["tag"] == "STUDY"


def test_p2_16_phase1_gate_is_still_present_and_precedes_no_observer():
    route = inspect.getsource(WindowsMonitorCoordinator._route_context)
    assert "self.services.mirl.observe(context)" in route
    assert "self.services.sine.observe(context)" in route
    assert "self.services.blacklist.observe(context)" in route
    assert "self.services.study.advance()" in route
    assert "self.services.cosecant.advance()" in route
    assert "not self._sine_owns_intervention()" in route
    assert route.index("self.services.blacklist.observe(context)") < route.index(
        "not self._sine_owns_intervention()"
    )


def test_p2_real_pipeline_social_dwell_trigger_then_active_sine_fresh_visit():
    policy = SineThresholdPolicy(
        stage_one_seconds=0.4,
        stage_two_cumulative_seconds=0.8,
        offer_retry_seconds=0.2,
    )
    rows = []
    with Engine(
        surface=MRBEAST,
        poll_seconds=0.05,
        fast_cosecant=True,
        blacklist_thresholds=policy,
    ) as engine:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            rows.extend(engine.drain_telemetry())
            if any(row.get("badge") == "TRIGGER" for row in rows):
                break
            time.sleep(0.05)
        else:
            raise AssertionError("real pipeline did not durably admit its first trigger")

        first_badges = [row.get("badge") for row in rows if row.get("badge")]
        assert "SOCIAL" in first_badges
        assert "DWELL" in first_badges
        assert first_badges.index("SOCIAL") < first_badges.index("DWELL")
        assert first_badges.count("TRIGGER") == 1

        original_episode = engine.services.sine.live_view().episode_uid
        assert original_episode
        engine.look_at(INSTAGRAM)
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            rows.extend(engine.drain_telemetry())
            if any(
                row.get("badge") == "DWELL" and row.get("title") == "Instagram"
                for row in rows
            ):
                break
            time.sleep(0.05)

        rows.extend(engine.drain_telemetry())
        assert engine.services.sine.live_view().episode_uid == original_episode
        assert sum(row.get("badge") == "TRIGGER" for row in rows) == 1
        assert any(
            row.get("badge") == "SOCIAL" and row.get("title") == "Instagram"
            for row in rows
        )
        assert any(
            row.get("badge") == "DWELL" and row.get("title") == "Instagram"
            for row in rows
        )


def test_p2_study_c_no_case1_case2_or_sine_hold_feature_was_added():
    changed_sources = "\n".join(
        path.read_text(encoding="utf-8-sig")
        for path in (
            ULTIMATE / "CORE_ENGINE" / "monitor.py",
            ULTIMATE / "CONTROL_STATION" / "controller.py",
            ULTIMATE / "CONTROL_STATION" / "launcher.py",
        )
    )
    assert "SINE HELD" not in changed_sources
    assert "study_uncertainty" not in changed_sources
    assert "uncertainty_popup" not in changed_sources


def test_ui_current_resource_two_lines_and_compact_feed_keep_tag_visible():
    app = QApplication.instance() or QApplication([])
    signal = SimpleNamespace(connect=lambda callback: None)
    engine = SimpleNamespace(
        pause=lambda: None,
        set_profile_type=lambda key: None,
        engine_status_changed=signal,
    )
    lifecycle = SimpleNamespace(
        request_start=lambda: None,
        request_stop=lambda: None,
        request_emergency=lambda: None,
    )
    profiles = SimpleNamespace(
        all_profiles=lambda: (SimpleNamespace(label="General", key="general"),),
        set_active=lambda key: True,
    )
    page = ControlPage(
        engine=engine,
        lifecycle=lifecycle,
        profiles=profiles,
    )
    page._resource_label.setText("YOUTUBE · LONG FORM")
    page._resource_title.setText(
        "(93) CM Vijay Kumar — Long lecture title that previously widened the card"
    )

    assert page._resource_label.text() == "YOUTUBE · LONG FORM"
    assert page._resource_title.text().startswith("(93) CM Vijay Kumar")
    assert "— (93)" not in page._resource_label.text()
    assert page._resource_label.font().pointSizeF() <= 13.5
    assert page._resource_title.font().pointSizeF() <= 11.5
    assert (
        page._resource_title.sizePolicy().horizontalPolicy()
        is QSizePolicy.Policy.Ignored
    )

    feed = FeedList()
    feed.resize(390, 300)
    feed.append(
        time_text="14:49:08",
        text="YOUTUBE — a deliberately long telemetry title that must yield room",
        tag="SOCIAL",
        tone="amber",
    )
    feed.show()
    app.processEvents()
    tag = feed.findChild(FeedTag)
    assert tag is not None and tag.isVisible()
    right_edge = tag.mapTo(feed, QPoint(0, 0)).x() + tag.width()
    assert right_edge <= feed.width()
    assert tag.font().pointSizeF() <= 9.0
    page.deleteLater()
    feed.deleteLater()


def load_tests(loader, tests, pattern):
    del loader, tests, pattern
    suite = unittest.TestSuite()
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            suite.addTest(unittest.FunctionTestCase(value, description=name))
    return suite


if __name__ == "__main__":
    unittest.main(verbosity=2)
