"""Phase 2 deterministic contract tests. No on-disk database or OS observation.

Run: python -B test_phase2_study_reconstruction.py
Real authorities run against a fake clock, recorded persistence transport and
explicit popup acknowledgments. Qt methods are compiled from their actual AST
with environmental widgets/signals supplied by the tests (PyQt is not needed).
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import math
import queue
import sqlite3
import threading
import time
import unittest
from enum import Enum
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

from CORE_ENGINE import browser as br
from CORE_ENGINE import resource_intent as ri
from CORE_ENGINE.blacklist import BlacklistAuthority
from CORE_ENGINE.trigger import TriggerAuthority, TriggerSource, TriggerStatus
from CORE_ENGINE.monitor import (
    ForegroundObservation, MonitorContext, MonitorServices,
    WindowsMonitorCoordinator, _study_app_category_metadata,
)
from COSECANT_STUDY_MODE.study import StudyRuntime, StudyState
from COSECANT_STUDY_MODE.cosecant import CosecantRuntime, CosecantState
from COSECANT_STUDY_MODE.cosecant import CosecantReturnTarget, StudyReturnObservation, StudyPresence
from SINE.sine import SineAuthority, SinePhase, SineStage, PopupState
from SINE.normal_break import NormalBreakAuthority
from MIRL.mirl import MirlAuthority, RecoveryObservation, RecoveryContext, MirlPhase
from MIRL.read_model import MirlReadAuthority, MirlReadInput, IntegrityStatus
from PERSISTENCE.storage import _operational_trigger_rows
from PERSISTENCE.session_health import _trigger_count
from COSINE.cosine import CosineRuntime
from MINE.mine import MineRuntime

ROOT = Path(__file__).resolve().parent
NS_PER_SECOND = 1_000_000_000


class Clock:
    def __init__(self):
        self.ns = 100 * NS_PER_SECOND

    def __call__(self):
        return self.ns

    def step(self, seconds=1):
        self.ns += round(seconds * NS_PER_SECOND)
        return self.ns


class MemoryStorage:
    """Persistence transport only. Does not implement admission or reporting."""
    def __init__(self):
        self.candidates = []
        self.sine = []
        self.mirl = []
        self.study = []
        self.cosecant = []
        self.normal_break = []
        self.order = []
        self.receipts = {}
        self.fail = ""
        self.receipt_state = "COMMITTED"

    def persist_trigger(self, **kw):
        self.candidates.append(kw["candidate"])
        i = len(self.candidates)
        receipt = NS(receipt_id=f"receipt-{i}", state=self.receipt_state, result_id=i)
        self.receipts[receipt.receipt_id] = receipt
        return receipt

    def receipt(self, receipt_id):
        return self.receipts[receipt_id]

    def forget_receipt(self, receipt_id):
        self.receipts.pop(receipt_id, None)

    def append_sine_facts(self, facts):
        if self.fail == "sine":
            return False
        self.sine.extend(facts)
        self.order.extend(f.kind for f in facts)
        return True

    def append_mirl_events(self, facts):
        if self.fail == "mirl":
            return False
        self.mirl.extend(facts)
        self.order.extend(f.kind for f in facts)
        return True

    def record_study_snapshot(self, **kw):
        if self.fail == "study":
            return False
        self.study.append(kw)
        return True

    def append_cosecant_facts(self, **kw):
        self.cosecant.extend(kw["facts"])
        return True

    def append_normal_break_facts(self, facts):
        self.normal_break.extend(facts)
        return True

    def append_event(self, event):
        return True


class Rig:
    def __init__(self, clock, *, study=True):
        self.clock = clock
        self.db = MemoryStorage()
        self.ri = ri.ResourceIntentAuthority()
        self.ri.start_session(profile_type="GENERAL")
        self.blacklist = BlacklistAuthority()
        self.blacklist.start_session()
        assert self.ri.set_stage_one_target_seconds(self.blacklist.stage_one_target_seconds())
        self.trigger = TriggerAuthority(monotonic_ns=clock)
        self.trigger.start_session(session_id=1, profile_type="GENERAL", decay_rate_per_minute=0.1)
        self.sine = SineAuthority(monotonic_ns=clock)
        self.sine.start_session(session_id=1, profile_type="GENERAL")
        self.mirl = MirlAuthority()
        self.mirl.start_session(session_id=1, profile_type="GENERAL")
        self.study = StudyRuntime(monotonic_ns=clock)
        self.cosecant = CosecantRuntime(context_authority=self.ri, monotonic_ns=clock)
        self.normal_break = NormalBreakAuthority(monotonic_ns=clock)
        self.cosine = CosineRuntime(event_sink=self.db)
        self.cosine.bind_parent_session(1)
        self.mine = MineRuntime(event_sink=self.db)
        self.mine.bind_parent_session(1)
        self.telemetry = queue.Queue()
        self.commands = queue.Queue()
        self.monitor = WindowsMonitorCoordinator(
            profile_type="GENERAL",
            services=MonitorServices(
                browser=None, resource_intent=self.ri, blacklist=self.blacklist,
                trigger=self.trigger, sine=self.sine, cosine=self.cosine,
                mirl=self.mirl, study=self.study, cosecant=self.cosecant,
                normal_break=self.normal_break, storage=self.db, mine=self.mine,
            ),
            foreground_reader=None, stop_event=threading.Event(),
            pause_event=threading.Event(), ready_event=threading.Event(),
            loop_stopped_event=threading.Event(), cleanup_complete_event=threading.Event(),
            telemetry_queue=self.telemetry, command_queue=self.commands,
        )
        self.monitor._monotonic_ns = clock
        self.monitor.session_id = 1
        self.monitor._profile_learning_key = "general"
        self.sequence = 0
        self.context = None
        self.black = None
        if study:
            self.prepare()
            self.monitor._handle_study_action("START")

    def prepare(self, **kw):
        result = self.study.prepare(
            subject=kw.get("subject", "neuroscience"), task=kw.get("task", "brain circuits"),
            planned_seconds=20000, keywords=kw.get("keywords", ("brain", "neuron")),
            important_keywords=kw.get("important_keywords", ()),
        )
        self.monitor._handle_study_result("PREPARE", result)
        return result

    def observe(self, *, process="chrome.exe", title="Funny entertainment", url="https://www.youtube.com/watch?v=unrelated", ott="", route=False, process_id=202, hwnd=101):
        self.sequence += 1
        process = process.removesuffix(".exe")  # WindowsForegroundReader contract
        foreground = ForegroundObservation(self.sequence, hwnd, process_id, process, title, self.clock(),
                                            "2026-09-24T10:00:00+00:00", 0.0)
        is_browser = process in {"chrome", "msedge"}
        evidence = br.classify_address_value(url, identity_secret=b"phase2-test-only-secret") if is_browser and url else None
        browser = br.BrowserEvidenceSnapshot(
            self.sequence, hwnd, process_id, process, br.BrowserKind.CHROME if is_browser else None,
            "Chrome" if is_browser else "", is_browser, is_browser,
            br.BrowserUrlReadStatus.OK if evidence else br.BrowserUrlReadStatus.NOT_SUPPORTED_BROWSER,
            evidence,
        )
        snap = self.ri.observe(foreground=foreground, browser_evidence=browser, certified_ott_platform_key=ott)
        platform = NS(platform_key=ott, process_name=process, process_id=process_id, hwnd=hwnd,
                      observed_monotonic_ns=self.clock()) if ott else None
        context = MonitorContext(foreground, browser, snap, cosine_platform=platform,
                                 study_owned=self.monitor._study_owns_moment())
        black = self.blacklist.observe(context)
        self.context, self.black = context, black
        if route:
            self.monitor._route_context(context, black)
        return context

    def dwell(self, seconds=300, **kw):
        self.observe(**kw)
        for _ in range(seconds):
            self.clock.step()
            self.observe(**kw)
        return self.context

    def submit(self):
        candidate = self.trigger.evaluate(context=self.context, blacklist=self.black)
        assert candidate is not None, "No candidate from current factual watch"
        self.monitor._begin_trigger_persistence(candidate, self.context, self.black)
        return candidate

    def reconcile(self, **kw):
        self.clock.step()
        self.observe(**kw)
        self.monitor._reconcile_pending_trigger(self.context, self.black)

    def flush(self):
        return self.monitor._route_sine_batch(self.sine.advance(now_monotonic_ns=self.clock()))

    def show(self):
        return self.monitor._handle_sine_command("sine_popup_shown", {
            "request_id": self.sine.live_view().popup_request_id,
            "occurred_monotonic_ns": self.clock(), "popup_hwnd": 909,
        })

    def close(self, request_id=None):
        return self.monitor._handle_sine_command("sine_popup_closed", {
            "request_id": request_id or self.sine.live_view().popup_request_id,
            "occurred_monotonic_ns": self.clock(), "reason": "authority_close",
        })

    def admit(self):
        self.dwell()
        candidate = self.submit()
        self.reconcile()
        assert self.sine.live_view().candidate_uid == candidate.candidate_uid
        return candidate

    def stage(self, stage):
        self.admit()
        assert self.show()
        if stage >= 2:
            self.clock.step(600)
            self.flush()
            assert self.show()
        if stage >= 3:
            self.clock.step(795)
            self.flush()
            assert self.show()


class Widget:
    def __init__(self, text="", value=0):
        self._text, self._value = text, value
        self.enabled, self.visible, self.focused = True, True, False
        self.calls = []

    def text(self): return self._text
    def value(self): return self._value
    def setText(self, value): self._text = value
    def setValue(self, value): self._value = value
    def setEnabled(self, value): self.enabled = value
    def setVisible(self, value): self.visible = value
    def setFocus(self): self.focused = True
    def set_progress(self, value, *args): self.progress = value
    def setAccessibleName(self, value): self.accessible = value
    def setStyleSheet(self, value): self.style = value
    def emit(self, *args): self.calls.append(args)
    def stop(self): pass


def actual_methods(relative, class_name, methods, globals_extra=None):
    """Execute unchanged production method bodies with fake Qt environment."""
    tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
    source = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    body = [n for n in source.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in methods]
    assert {n.name for n in body} == set(methods)
    for n in body:
        n.decorator_list = [d for d in n.decorator_list if isinstance(d, ast.Name) and d.id == "staticmethod"]
    cls = ast.ClassDef(name=class_name, bases=[], keywords=[], body=body, decorator_list=[])
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[])
    env = dict(globals())
    env.update(globals_extra or {})
    exec(compile(ast.fix_missing_locations(module), str(ROOT / relative), "exec"), env)
    return env[class_name]


class TestEngineStatus(str, Enum):
    ACTIVE="ACTIVE"; PAUSED="PAUSED"; STOPPING="STOPPING"; STOPPED="STOPPED"; ERROR="ERROR"


def controller_fixture():
    methods = ["prepare_study", "_drain_study_prepare_result", "_enqueue_command", "_expected_study_identity", "_finish_worker_exit"]
    cls = actual_methods("CONTROL_STATION/controller.py", "ControlStationController", methods,
                         {"EngineStatus": TestEngineStatus, "EngineCommand": NS})
    obj = cls()
    obj._pending_study_prepare = None
    obj._status = TestEngineStatus.ACTIVE
    obj._command_queue = queue.Queue(maxsize=1)
    obj._pending_study_confirmation_actions = {}
    obj._study_confirmation_presenter = None
    obj.study_prepare_result = Widget()
    obj.study_view_changed = Widget()
    obj.study_start_transition_changed = Widget()
    return obj


def timer_fixture():
    methods = ["_emit_prepare", "show_prepare_result", "render", "render_sine", "show_start_transition", "_project_study_countdown"]
    cls = actual_methods("COSECANT_STUDY_MODE/view.py", "StudyTimerCard", methods,
                         {"_duration": lambda n: str(n), "_clock_text": lambda n: str(n)})
    obj = cls()
    for name in ("subject_input", "task_input", "keywords_input", "important_keywords_input",
                 "prepare_feedback", "prepare_button", "start_button", "pause_button", "resume_button",
                 "complete_button", "break_button", "subject_label", "task_label", "time_label",
                 "state_label", "progress", "ring", "prepare_requested"):
        setattr(obj, name, Widget())
    obj.study_minutes = Widget(value=45); obj.break_minutes = Widget(value=10)
    obj._meta = {key: Widget() for key in ("planned", "elapsed", "ends")}
    obj._study_snapshot = obj._cosecant_snapshot = obj._sine_snapshot = None
    obj._prepare_pending = False; obj._start_transition = {}
    obj._set_setup_locked = lambda value: None  # environmental widgets only
    return obj


class ReconstructionTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.clock_patch = patch("time.monotonic_ns", self.clock)
        self.clock_patch.start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.clock_patch.stop()

    def rig(self, **kw):
        return Rig(self.clock, **kw)

    def test_B1_0459_self_return_is_observation_only(self):
        r = self.rig()
        r.dwell(299)
        self.assertEqual(r.context.resource_intent.verdict.off_task_dwell_seconds, 299)
        self.assertIsNone(r.trigger.evaluate(context=r.context, blacklist=r.black))
        r.clock.step()
        r.observe(title="brain neuron neuroscience brain circuits", route=True)
        self.assertEqual(r.context.resource_intent.verdict.off_task_dwell_seconds, 0)
        self.assertFalse(r.db.candidates or r.db.sine or r.db.mirl)
        self.assertEqual(r.trigger.live_view().admitted_count, 0)
        self.assertFalse(r.mirl.drain_verified_recovery_evidence())

    def test_B2_prepare_failure_no_admission(self):
        r = self.rig()
        r.dwell()
        c = r.submit()
        r.mirl.shutdown()  # real unavailable authority
        r.reconcile()
        self.assertEqual(len(r.db.candidates), 1)
        result = r.trigger.trigger_result(c.candidate_uid)
        self.assertIs(result.status, TriggerStatus.SETTLED_WITHOUT_INTERVENTION)
        self.assertFalse(result.cooldown_committed)
        self.assertFalse(r.db.sine)
        self.assertFalse(r.mirl.live_view().episode_id)

    def test_B3_prepare_durable_before_acceptance_before_display(self):
        r = self.rig()
        c = r.admit()
        self.assertFalse(r.mirl.live_view().episode_id)
        self.assertLess(r.db.order.index("MIRL_TRIGGER_PREPARED"), r.db.order.index("SINE_TRIGGER_ACCEPTED"))
        accepted = next(f for f in r.db.sine if f.kind == "SINE_TRIGGER_ACCEPTED")
        self.assertEqual((accepted.candidate_uid, accepted.operational_event_id), (c.candidate_uid, 1))
        self.assertTrue(r.show())
        self.assertTrue(r.mirl.live_view().episode_id)
        self.assertEqual(r.mirl.live_view().candidate_uid, c.candidate_uid)
        self.assertEqual(sum(f.kind == "SINE_DISPLAYED" for f in r.db.sine), 1)
        self.assertFalse(r.show())

    def test_B4_T13_committed_candidate_loses_authority(self):
        for mutation in ("refocus", "complete", "generation", "red", "stop", "pause", "cosecant", "segment"):
            with self.subTest(mutation=mutation):
                r = self.rig()
                r.dwell()
                c = r.submit()
                kw = {}
                if mutation == "refocus": kw["title"] = "brain neuron neuroscience brain circuits"
                if mutation in {"complete", "generation"}:
                    r.monitor._handle_study_action("COMPLETE")
                    if mutation == "generation":
                        r.prepare(); r.monitor._handle_study_action("START")
                if mutation == "red": r.ri.set_protected_red(True)
                if mutation == "stop": r.monitor.stop_event.set()
                if mutation == "pause": r.monitor.pause_event.set()
                if mutation == "cosecant":
                    current = r.ri._context
                    r.ri.publish_study_context(replace(current, display_state="BREAK", protection_active=False, planned_break_active=True,
                                                       published_monotonic_ns=r.clock()))
                if mutation == "segment":
                    r.clock.step(); r.observe(title="brain neuron neuroscience brain circuits")
                r.reconcile(**kw)
                self.assertIsNone(r.monitor._pending_trigger)
                self.assertIs(r.trigger.trigger_result(c.candidate_uid).status, TriggerStatus.SETTLED_WITHOUT_INTERVENTION)
                self.assertFalse(r.trigger.live_view().cooldown_active)
                self.assertFalse(r.db.sine)
                self.assertFalse(r.mirl.live_view().episode_id)

    def _transition(self, stage):
        r = self.rig(study=False)
        r.stage(stage)
        r.prepare()
        old = r.sine.live_view()
        r.monitor._handle_study_action("START")
        self.assertIsNotNone(r.monitor._pending_study_start)
        self.assertIs(r.study.snapshot().state, StudyState.READY)
        r.clock.step(4.999)
        r.monitor._advance_pending_study_start()
        self.assertIs(r.study.snapshot().state, StudyState.READY)
        self.assertEqual(r.sine.live_view().episode_uid, old.episode_uid)
        r.clock.step(.001)
        r.monitor._advance_pending_study_start()
        self.assertIs(r.study.snapshot().state, StudyState.READY)
        self.assertTrue(r.sine.live_view().study_transition_close_pending)
        self.assertFalse(r.close("wrong-request"))
        self.assertTrue(r.close())
        self.assertIs(r.study.snapshot().state, StudyState.ACTIVE)
        self.assertFalse(r.sine.protected_red_active())
        self.assertEqual(r.sine.live_view().episode_uid, old.episode_uid)
        closes = [f for f in r.db.mirl if f.kind == "MIRL_EPISODE_CLOSED"]
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0].reason, "ABORTED")
        self.assertFalse(any(f.kind == "MIRL_RETURN_VERIFIED" for f in r.db.mirl))
        self.assertFalse(r.monitor._observed_lambda_estimates)
        projected = MirlReadAuthority().project_runtime(r.mirl)
        return r, projected

    def test_B5_T01_stage2_five_second_transfer(self):
        r, projected = self._transition(2)
        self.assertFalse(projected.live_mirl.integrity_issues)

    def test_T01_stage1_is_settled_before_Study_ACTIVE(self):
        for displayed in (False, True):
            with self.subTest(displayed=displayed):
                r=self.rig(study=False);r.admit()
                if displayed:self.assertTrue(r.show())
                old=r.sine.live_view().popup_request_id
                r.prepare();r.monitor._handle_study_action("START")
                self.assertIs(r.study.snapshot().state,StudyState.ACTIVE)
                self.assertIs(r.sine.live_view().phase,SinePhase.CANCELLED)
                self.assertFalse(r.sine.popup_shown(request_id=old,shown_monotonic_ns=r.clock()))
                self.assertFalse(r.mirl.live_view().pending_display)
                self.assertFalse(r.monitor._observed_lambda_estimates)

    def test_B6_T19_protected_red_transfer_no_reopen_or_Tr(self):
        r, projected = self._transition(3)
        count = len(r.db.sine)
        r.clock.step(30); r.flush()
        self.assertEqual(len(r.db.sine), count)
        self.assertFalse(r.sine.restore_protected_red())

    def test_B7_pause_resume_backend_rejection(self):
        r = self.rig(); r.admit()
        for action in ("PAUSE", "RESUME"):
            r.monitor._handle_study_action(action)
            self.assertIs(r.study.snapshot().state, StudyState.ACTIVE)
        r.show()
        r.monitor._handle_study_action("PAUSE")
        self.assertIs(r.study.snapshot().state, StudyState.ACTIVE)

    def test_B8_complete_is_terminal_not_recovery(self):
        r = self.rig(); r.admit(); r.show()
        r.monitor._handle_study_action("COMPLETE")
        self.assertIs(r.study.snapshot().state, StudyState.COMPLETED)
        self.assertIs(r.sine.live_view().phase, SinePhase.CANCELLED)
        self.assertFalse(r.mirl.drain_verified_recovery_evidence())
        self.assertTrue(any(f.kind == "MIRL_EPISODE_CLOSED" and f.reason == "ABORTED" for f in r.db.mirl))

    def test_T03_T07_every_distraction_surface_uses_shared_dwell(self):
        surfaces = [
            ({"url": "https://www.instagram.com/reels/abc"}, ri.ResourceSurface.SOCIAL),
            ({"process": "steam.exe", "url": ""}, ri.ResourceSurface.GAMING),
            ({}, ri.ResourceSurface.YOUTUBE_WATCH),
            ({"url": "https://www.youtube.com/shorts/abc"}, ri.ResourceSurface.YOUTUBE_SHORTS),
            ({"process": "whatsapp.exe", "url": ""}, ri.ResourceSurface.MESSAGING),
            ({"process": "netflix.exe", "url": "", "ott": "netflix"}, ri.ResourceSurface.UNKNOWN),
        ]
        r = self.rig()
        segments = set()
        for kw, surface in surfaces:
            r.observe(**kw)
            for _ in range(50):
                r.clock.step(); r.observe(**kw)
                verdict = r.context.resource_intent.verdict
                self.assertIs(verdict.resource_identity.surface, surface)
                self.assertIs(verdict.classification, ri.ResourceIntent.DISTRACTION)
                segments.add(verdict.distraction_segment_uid)
        self.assertEqual(len(segments), 1)
        self.assertIs(r.context.resource_intent.verdict.sine_contribution, ri.SineContribution.READY)
        c = r.trigger.evaluate(context=r.context, blacklist=r.black)
        self.assertIs(c.evidence.source, TriggerSource.STUDY_OFF_TASK)

    def test_T09_T10_watchdog_exact_remainder(self):
        r = self.rig(); r.admit(); r.show()
        r.clock.step(13)
        r.observe(title="brain neuron neuroscience brain circuits")
        r.monitor._sync_study_sine_activity_clock(r.context, r.sine.live_view())
        saved = r.sine.live_view().next_deadline_seconds
        self.assertEqual(saved, 587)
        r.clock.step(1000); r.flush()
        self.assertEqual(r.sine.live_view().next_deadline_seconds, saved)
        self.assertEqual(r.sine.live_view().stage, 1)
        r.dwell()
        r.monitor._sync_study_sine_activity_clock(r.context, r.sine.live_view())
        self.assertEqual(r.sine.live_view().next_deadline_seconds, saved)
        r.clock.step(586); r.flush()
        self.assertEqual(r.sine.live_view().stage, 1)
        r.clock.step(); r.flush()
        self.assertTrue(r.show())
        self.assertEqual(r.sine.live_view().stage, 2)
        self.assertFalse(r.monitor._observed_lambda_estimates)

    def test_T12_same_segment_and_replayed_observation_no_duplicate(self):
        r = self.rig(); c = r.admit(); r.show()
        for _ in range(305):
            r.clock.step(); r.observe()
        self.assertIsNone(r.trigger.evaluate(context=r.context, blacklist=r.black))
        self.assertIsNone(r.trigger.evaluate(context=r.context, blacklist=r.black))
        self.assertEqual(r.trigger.live_view().admitted_count, 1)

    def test_T17_normal_blacklist_delayed_receipt_still_admits(self):
        r = self.rig(study=False); c = r.admit()
        self.assertIs(c.evidence.source, TriggerSource.EXECUTIVE_BLACKLIST)
        self.assertFalse(r.sine.live_view().study_mode)
        self.assertTrue(r.show())

    def test_missing_mismatched_expired_token_refused_by_sine(self):
        r = self.rig(); r.dwell()
        c = r.trigger.evaluate(context=r.context, blacklist=r.black)
        token = r.mirl.prepare_trigger(candidate=c, operational_event_id=1)
        mutations = [None, replace(token, session_id=2), replace(token, candidate_uid="other"),
                     replace(token, operational_event_id=2), replace(token, study_context_token="other"),
                     replace(token, evidence_digest="wrong"), replace(token, deadline_monotonic_ns=r.clock()),
                     replace(token, issued_monotonic_ns=r.clock()+1)]
        for bad in mutations:
            self.assertFalse(r.sine.request_trigger(candidate=c, operational_event_id=1, mirl_display_token=bad))
        self.assertFalse(r.sine.live_view().episode_uid)

    def test_prepare_write_failure_and_sine_write_failure_compensate(self):
        for fail in ("mirl", "sine"):
            with self.subTest(fail=fail):
                r = self.rig(); r.dwell(); c = r.submit(); r.db.fail = fail
                with self.assertRaises(RuntimeError): r.reconcile()
                self.assertFalse(r.trigger.live_view().cooldown_active)
                self.assertEqual(r.trigger.live_view().admitted_count, 0)
                self.assertFalse(r.mirl.live_view().pending_display)
                self.assertFalse(r.mirl.live_view().episode_id)
                self.assertFalse(any(f.kind == "SINE_TRIGGER_ACCEPTED" for f in r.db.sine))

    def test_display_expiry_does_not_create_visible_episode(self):
        r = self.rig(); r.admit()
        r.clock.step(46)
        self.assertFalse(r.show())
        self.assertIs(r.sine.live_view().phase, SinePhase.CANCELLED)
        self.assertFalse(r.mirl.live_view().episode_id)
        self.assertFalse(any(f.kind == "SINE_DISPLAYED" for f in r.db.sine))

    def test_T02_Dad_suppresses_siblings_and_blacklist(self):
        r = self.rig()
        for kw in ({"title": "brain neuron neuroscience brain circuits"},
                   {"process": "whatsapp", "url": ""},
                   {"process": "netflix", "url": "", "ott": "netflix"}):
            r.clock.step(); r.observe(**kw, route=True)
        self.assertFalse(r.db.candidates)
        self.assertFalse(r.mine.monitor_status(now_ns=r.clock()).factual_episode)
        self.assertFalse(r.cosine.monitor_status(now_ns=r.clock()).factual_episode)
        self.assertFalse(r.monitor._handover.snapshot(r.clock()).active)

    def test_uncertain_popup_strict_alignment_interval_and_user_confirm(self):
        for fraction, expected in ((25, ri.ResourceIntent.DISTRACTION), (50, ri.ResourceIntent.UNCERTAIN),
                                   (75, ri.ResourceIntent.STUDY_ALIGNED)):
            with self.subTest(fraction=fraction):
                r = self.rig(study=False)
                r.prepare(keywords=("alpha", "beta", "gamma", "delta"))
                r.monitor._handle_study_action("START")
                title = {25: "alpha", 50: "alpha beta", 75: "alpha beta gamma"}[fraction]
                r.dwell(300, title=title)
                v = r.context.resource_intent.verdict
                self.assertEqual(v.study_alignment_percent, fraction)
                self.assertIs(v.classification, expected)
                facts = r.ri.drain_facts()
                popups = [f.popup for f in facts if f.kind == "STUDY_CONFIRMATION_POPUP_REQUESTED"]
                self.assertEqual(len(popups), int(fraction == 50))
                if fraction == 50:
                    self.assertIs(v.sine_contribution, ri.SineContribution.NONE)
                    request = popups[0]
                    self.assertTrue(r.ri.record_study_confirmation_popup_shown(
                        request_id=request.request_id, shown_monotonic_ns=r.clock(), popup_hwnd=808))
                    self.assertTrue(r.ri.record_study_confirmation_response(
                        request_id=request.request_id, response=ri.StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL.value,
                        occurred_monotonic_ns=r.clock(), expected_study_context_token=request.study_context_token,
                        expected_resource_key=request.resource_key))
                    r.clock.step(); r.observe(title=title)
                    self.assertIs(r.context.resource_intent.verdict.classification, ri.ResourceIntent.STUDY_ALIGNED)
                    self.assertFalse(r.db.sine or r.db.mirl or r.db.candidates)

    def test_uncertain_existing_study_sine_freezes_and_keeps_clarification_separate(self):
        r = self.rig(study=False)
        r.prepare(keywords=("alpha", "beta", "gamma", "delta")); r.monitor._handle_study_action("START")
        r.admit(); r.show(); r.ri.set_sine_episode_active(True)
        r.clock.step(10); r.observe(title="alpha beta")
        r.monitor._sync_study_sine_activity_clock(r.context, r.sine.live_view())
        remainder = r.sine.live_view().next_deadline_seconds
        r.dwell(300, title="alpha beta")
        r.flush()
        self.assertEqual(r.sine.live_view().next_deadline_seconds, remainder)
        self.assertTrue(any(f.kind == "STUDY_CONFIRMATION_POPUP_REQUESTED" for f in r.ri.drain_facts()))
        self.assertEqual(len([f for f in r.db.sine if f.kind == "SINE_TRIGGER_ACCEPTED"]), 1)

    def test_T11_T14_verified_return_relapse_and_same_resource_rearm(self):
        r = self.rig(); first = r.admit(); r.show()
        def recovery(context, count):
            for _ in range(count):
                r.clock.step()
                events = r.mirl.record_recovery_observation(RecoveryObservation(
                    context, r.clock(), "2026-09-24T10:00:01Z", "test_foreground",
                    f"obs-{r.clock()}", r.study.snapshot().context_token, True))
                r.monitor._persist_mirl_events(events)
                r.flush()
        recovery(RecoveryContext.FOCUS, 12)
        self.assertTrue(r.sine.live_view().presentation_withheld_for_recovery)
        recovery(RecoveryContext.DISTRACTION, 1)
        self.assertFalse(r.sine.live_view().presentation_withheld_for_recovery)
        self.assertEqual(r.mirl.live_view().relapse_count, 1)
        recovery(RecoveryContext.FOCUS, 73)
        self.assertIs(r.sine.live_view().phase, SinePhase.RESOLVED)
        self.assertEqual(len(r.monitor._observed_lambda_estimates), 1)
        projected = MirlReadAuthority().project_runtime(r.mirl)
        self.assertFalse(projected.live_mirl.integrity_issues)
        self.assertEqual(projected.live_mirl.recently_closed_episodes[0].final_outcome, "RETURNED")
        r.clock.step(); r.observe(title="brain neuron neuroscience brain circuits")
        r.clock.step(); r.dwell()
        second = r.submit(); r.reconcile()
        self.assertNotEqual(first.candidate_uid, second.candidate_uid)
        self.assertNotEqual(first.evidence.correlation_keys, second.evidence.correlation_keys)
        self.assertEqual(first.evidence.resource_key, second.evidence.resource_key)
        self.assertEqual(r.trigger.live_view().admitted_count, 2)

    def start_cosecant(self, r):
        r.observe(title="brain neuron neuroscience brain circuits")
        identity = r.context.resource_intent.verdict.resource_identity
        target = CosecantReturnTarget(r.study.snapshot().context_token, "youtube", identity.opaque_resource_token, r.clock())
        paused = r.study.pause()
        r.monitor._handle_study_result("PAUSE", paused)
        result = r.cosecant.start_break(study=paused.snapshot, selected_break_seconds=60, intended_return_target=target)
        self.assertTrue(result.accepted)
        r.monitor._route_cosecant_result(result)
        return target

    def test_T08_T18_cosecant_exact_target_and_three_second_return(self):
        r = self.rig(); target = self.start_cosecant(r)
        for _ in range(301):
            r.clock.step(); r.observe(url="https://www.youtube.com/watch?v=break-video", route=True)
        self.assertFalse(r.db.candidates or r.db.sine)
        self.assertFalse(r.monitor._study_trigger_admission_open(r.context))
        r.clock.step(); r.observe(title="brain neuron neuroscience brain circuits", url="https://www.youtube.com/watch?v=other")
        self.assertFalse(r.monitor._exact_return_confirmed(r.context, target))
        for seconds in range(4):
            r.clock.step(); r.observe(title="brain neuron neuroscience brain circuits")
            r.monitor._observe_cosecant_return(r.context)
            if seconds < 3: self.assertIs(r.study.snapshot().state, StudyState.PAUSED)
        self.assertIs(r.study.snapshot().state, StudyState.ACTIVE)
        self.assertTrue(any(f.kind.value == "RETURN_CONFIRMED" for f in r.db.cosecant))

    def test_complete_available_during_cosecant_final_lock(self):
        r = self.rig(); self.start_cosecant(r)
        r.clock.step(420); r.monitor._route_cosecant_result(r.cosecant.advance())
        self.assertIs(r.cosecant.snapshot().state, CosecantState.FINAL_LOCK)
        timer = timer_fixture(); timer.render(r.study.snapshot(), r.cosecant.snapshot())
        self.assertTrue(timer.complete_button.enabled)
        self.assertFalse(timer.resume_button.enabled)
        r.monitor._handle_study_action("COMPLETE")
        self.assertIs(r.study.snapshot().state, StudyState.COMPLETED)
        self.assertTrue(any(f.kind.value == "BREAK_CANCELLED" for f in r.db.cosecant))
        self.assertFalse(any(f.kind.value == "RETURN_CONFIRMED" for f in r.db.cosecant))

    def test_T15_prepare_transport_validation_and_durable_result(self):
        r = self.rig(study=False); controller = controller_fixture(); controller._command_queue = r.commands
        timer = timer_fixture()
        timer.subject_input.setText("  neuroscience "); timer.task_input.setText(" brain circuits ")
        timer.keywords_input.setText("brain, neuron, , imaging")
        timer.important_keywords_input.setText("brain, imaging")
        timer._emit_prepare()
        subject, task, seconds, break_seconds, keywords, important = timer.prepare_requested.calls[-1]
        self.assertEqual(keywords, ("brain", "neuron", "imaging"))
        self.assertTrue(controller.prepare_study(subject, task, seconds, break_seconds, keywords=keywords, important_keywords=important))
        self.assertFalse(controller.prepare_study(subject, task, seconds))
        self.assertIsNone(controller.study_prepare_result.calls[-1][0]["accepted"])
        r.monitor._drain_commands(); controller._drain_study_prepare_result()
        result = controller.study_prepare_result.calls[-1][0]
        self.assertTrue(result["accepted"])
        self.assertEqual(r.study.snapshot().keywords, keywords)
        self.assertEqual(len(r.db.study), 1)
        timer._study_snapshot = r.study.snapshot(); timer.show_prepare_result(result)
        self.assertEqual(timer.prepare_feedback.text(), "Study is READY. Press START to begin.")
        stale_reply = controller._pending_study_prepare
        self.assertIsNone(stale_reply)
        self.assertTrue(controller.prepare_study(subject, task, seconds))  # obsolete empty identity
        r.monitor._drain_commands(); controller._drain_study_prepare_result()
        self.assertFalse(controller.study_prepare_result.calls[-1][0]["accepted"])
        self.assertEqual(controller.study_view_changed.calls[-1][0], r.study.snapshot())
        for invalid in ({"subject": ""}, {"planned_seconds": -1}, {"keywords": "bare-string"}):
            snapshot = r.study.snapshot()
            payload = dict(subject=subject, task=task, planned_seconds=100, keywords=(),
                           expected_study_block_id=snapshot.block_id, expected_study_generation=snapshot.generation)
            payload.update(invalid)
            reply = queue.SimpleQueue()
            r.commands.put(NS(kind="study_prepare", payload=payload, response_queue=reply))
            r.monitor._drain_commands()
            self.assertFalse(reply.get_nowait()["accepted"])
            self.assertEqual(r.study.snapshot(), snapshot)
        r.db.fail = "study"
        snapshot = r.study.snapshot()
        controller.prepare_study(subject, task, seconds, expected_study_block_id=snapshot.block_id, expected_study_generation=snapshot.generation)
        with self.assertRaises(RuntimeError): r.monitor._drain_commands()
        controller._drain_study_prepare_result()
        self.assertIsNotNone(controller._pending_study_prepare)
        self.assertIsNone(controller.study_prepare_result.calls[-1][0]["accepted"])

    def test_T15_prepare_off_queue_full_and_worker_exit(self):
        c = controller_fixture()
        for state in (TestEngineStatus.STOPPED, TestEngineStatus.STOPPING):
            c._status = state
            self.assertFalse(c.prepare_study("x", "y", 100))
            self.assertFalse(c.study_prepare_result.calls[-1][0]["accepted"])
        c._status = TestEngineStatus.ACTIVE
        c._command_queue.put(NS())
        self.assertFalse(c.prepare_study("x", "y", 100))
        self.assertIsNone(c._pending_study_prepare)
        c._command_queue.get(); self.assertTrue(c.prepare_study("x", "y", 100))
        old_reply = c._pending_study_prepare
        c._drain_telemetry = lambda **kw: c._drain_study_prepare_result()
        c._drain_worker_errors = lambda: ()
        c._startup_failure_reported = False
        c._cleanup_complete_event = threading.Event(); c._cleanup_complete_event.set()
        c._current_session_id = None
        c._worker_timer = c._telemetry_timer = c._elapsed_timer = Widget()
        c._release_report_lease = lambda: None
        c._set_status = lambda value: setattr(c, "_status", value)
        c.engine_stopped = Widget()
        c._finish_worker_exit()
        self.assertIsNone(c._pending_study_prepare)
        self.assertFalse(c.study_prepare_result.calls[-1][0]["accepted"])
        old_reply.put({"accepted": True})
        c._drain_study_prepare_result()
        self.assertFalse(c.study_prepare_result.calls[-1][0]["accepted"])

    def test_UI_pause_resume_guards_and_transition_is_presentation(self):
        r = self.rig(); r.admit()
        timer = timer_fixture(); timer.render(r.study.snapshot(), r.cosecant.snapshot())
        timer.render_sine(r.sine.live_view())
        self.assertFalse(timer.pause_button.enabled)
        self.assertFalse(timer.resume_button.enabled)
        self.assertTrue(timer.complete_button.enabled)
        r2 = self.rig(study=False); r2.prepare()
        timer = timer_fixture(); timer.render(r2.study.snapshot(), r2.cosecant.snapshot())
        timer.show_start_transition(dict(block_id=r2.study.snapshot().block_id, generation=r2.study.snapshot().generation,
                                        deadline_monotonic_ns=self.clock()+5*NS_PER_SECOND, state="COUNTDOWN"))
        self.assertFalse(timer.start_button.enabled)
        self.clock.step(5); timer._project_study_countdown()
        self.assertIs(r2.study.snapshot().state, StudyState.READY)
        self.assertIn("Closing", timer.prepare_feedback.text())

    def test_operational_metrics_join_exact_acceptance_not_candidate_or_display(self):
        r = self.rig(); r.dwell(); r.submit()
        connection = sqlite3.connect(":memory:"); self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.executescript("CREATE TABLE triggers(id INTEGER, session_id INTEGER,candidate_uid TEXT,payload_json TEXT,created_at_utc TEXT);"
                                 "CREATE TABLE sine_facts(id INTEGER,session_id INTEGER,candidate_uid TEXT,episode_uid TEXT,kind TEXT,payload_json TEXT);")
        candidate = r.db.candidates[0]
        connection.execute("INSERT INTO triggers VALUES(1,1,?,?,?)", (candidate.candidate_uid,json.dumps(asdict(candidate)),"2026-09-23T23:59:59+00:00"))
        self.assertFalse(_operational_trigger_rows(connection))
        r.reconcile()
        fact = next(f for f in r.db.sine if f.kind == "SINE_TRIGGER_ACCEPTED")
        fact = replace(fact, occurred_wall_time_utc="2026-09-24T00:00:01+00:00")
        payload = json.dumps(asdict(fact))
        args = (1,1,fact.candidate_uid,fact.episode_uid,fact.kind,payload)
        connection.execute("INSERT INTO sine_facts VALUES(?,?,?,?,?,?)",args)
        connection.execute("INSERT INTO sine_facts VALUES(?,?,?,?,?,?)",args)
        self.assertEqual(len(_operational_trigger_rows(connection)),1)
        self.assertEqual(_trigger_count(connection,"2026-09-24T00:00:00Z","2026-09-25T00:00:00Z"),1)
        # Exercise the actual public readers with only their connection transport replaced.
        from PERSISTENCE import storage
        connection.execute("CREATE TABLE sessions(id INTEGER)")
        connection.execute("INSERT INTO sessions VALUES(1)")
        transport=NS(execute=connection.execute,in_transaction=True,close=lambda:None)
        with patch.object(storage,"connect_database",return_value=transport):
            self.assertEqual(storage._counts(),(1,1))
            self.assertEqual(len(storage.read_trigger_candidate_evidence()),1)
            self.assertEqual(storage.read_trigger_platform_keys(),("youtube",))
            self.assertEqual(storage.read_trigger_identities(),{candidate.candidate_uid:"youtube"})
            self.assertEqual(storage.read_trigger_fire_times(),{candidate.candidate_uid:"2026-09-24T00:00:01+00:00"})
        self.assertFalse(any(f.kind == "SINE_DISPLAYED" for f in r.db.sine))
        bad = dict(asdict(fact),operational_event_id=2)
        connection.execute("INSERT INTO sine_facts VALUES(?,?,?,?,?,?)",(3,1,fact.candidate_uid,fact.episode_uid,fact.kind,json.dumps(bad)))
        with self.assertRaises(ValueError): _operational_trigger_rows(connection)

    def test_B3_popup_retry_exhaustion_never_becomes_visible_intervention(self):
        r = self.rig(); r.admit()
        candidate_uid = r.sine.live_view().candidate_uid
        for attempt in range(4):
            self.assertTrue(r.monitor._handle_sine_command("sine_popup_failed", {
                "request_id": r.sine.live_view().popup_request_id,
                "occurred_monotonic_ns": r.clock(), "reason": "test_OS_display_failure",
            }))
            if attempt < 3:
                r.clock.step(10); r.flush()
        self.assertTrue(any(f.kind == "SINE_DISPLAY_RETRY_EXHAUSTED" for f in r.db.sine))
        self.assertFalse(any(f.kind == "SINE_DISPLAYED" for f in r.db.sine))
        self.assertFalse(r.mirl.live_view().episode_id)
        r.clock.step(16); r.flush()
        self.assertIs(r.sine.live_view().phase, SinePhase.CANCELLED)
        self.assertFalse(r.mirl.live_view().pending_display)
        self.assertEqual(r.sine.live_view().candidate_uid, candidate_uid)
        self.assertEqual(r.trigger.live_view().admitted_count, 1)  # durable admission stays factual
        self.assertFalse(r.monitor._observed_lambda_estimates)

    def test_B5_natural_verified_return_during_countdown_stays_real_return(self):
        r = self.rig(study=False); r.stage(2); r.prepare()
        def focus():
            r.clock.step()
            events = r.mirl.record_recovery_observation(RecoveryObservation(
                RecoveryContext.FOCUS, r.clock(), "2026-09-24T10:00:01Z", "test_foreground",
                f"obs-{r.clock()}", "", True))
            r.monitor._persist_mirl_events(events); r.flush()
        for _ in range(68):
            focus()
            if r.sine.live_view().popup_state is PopupState.CLOSE_REQUESTED:
                self.assertTrue(r.close())
        self.assertIsNot(r.mirl.live_view().phase, MirlPhase.CLOSED)
        r.monitor._handle_study_action("START")
        pending = dict(r.monitor._pending_study_start)
        r.monitor._handle_study_action("START")
        self.assertEqual(r.monitor._pending_study_start, pending)
        for _ in range(5):
            focus(); r.monitor._advance_pending_study_start()
        self.assertIs(r.study.snapshot().state, StudyState.ACTIVE)
        closes = [event for event in r.db.mirl if event.kind == "MIRL_EPISODE_CLOSED"]
        self.assertEqual([event.reason for event in closes], ["RETURNED"])
        self.assertEqual(len(r.monitor._observed_lambda_estimates), 1)
        self.assertFalse(any(event.kind == "MIRL_SINE_TERMINATED" for event in r.db.mirl))

    def test_B5_changed_ready_identity_cancels_only_pending_start(self):
        r = self.rig(study=False); r.stage(3); r.prepare()
        old = r.sine.live_view()
        r.monitor._handle_study_action("START")
        r.prepare(subject="changed subject")
        r.clock.step(5); r.monitor._advance_pending_study_start()
        self.assertIsNone(r.monitor._pending_study_start)
        self.assertIs(r.study.snapshot().state, StudyState.READY)
        self.assertEqual(r.sine.live_view().episode_uid, old.episode_uid)
        self.assertTrue(r.sine.live_view().protected_red_active)
        self.assertFalse(any(event.kind == "MIRL_EPISODE_CLOSED" for event in r.db.mirl))

    def test_transition_missing_mirl_close_failure_and_stop_fail_closed(self):
        for cause in ("missing_mirl", "stop", "missing_ack", "durability"):
            with self.subTest(cause=cause):
                r = self.rig(study=False); r.stage(3); r.prepare()
                if cause == "missing_mirl": r.mirl.shutdown()
                r.monitor._handle_study_action("START")
                if cause == "stop": r.monitor.stop_event.set()
                r.clock.step(5); r.monitor._advance_pending_study_start()
                if cause == "durability":
                    r.db.fail = "mirl"
                    with self.assertRaises(RuntimeError): r.close()
                    self.assertTrue(r.monitor._uncommitted_mirl_events)
                if cause == "missing_ack":
                    r.clock.step(10); r.monitor._advance_pending_study_start()
                self.assertIs(r.study.snapshot().state, StudyState.READY)
                self.assertFalse(r.monitor._observed_lambda_estimates)

    def test_T16_activity_categories_and_exact_study_precedence(self):
        study_cases = [
            ({}, "SOCIAL", "SOCIAL"),
            ({"title":"brain neuron neuroscience brain circuits"}, "STUDY", "STUDY"),
            ({"process":"code", "title":"brain neuron neuroscience brain circuits"}, "STUDY FOCUS", "STUDY_FOCUS"),
            ({"process":"notepad"}, "STUDY ACTIVITY", "ACTIVITY"),
            ({"process":"steam"}, "GAMING", "GAMING"),
            ({"process":"whatsapp"}, "MESSAGING", "MESSAGING"),
            ({"process":"netflix", "ott":"netflix"}, "OTT", "OTT"),
        ]
        r = self.rig()
        for kw, badge, category in study_cases:
            with self.subTest(kw=kw):
                r.clock.step(); r.observe(**kw)
                self.assertEqual(r.monitor._activity_telemetry_semantics(r.context)[0], badge)
                metadata = _study_app_category_metadata(r.context, r.black, session_id=1)
                self.assertTrue(metadata["evidence_available"])
                self.assertEqual(metadata["category"], category)
                mismatched = replace(r.black, observation_sequence=r.black.observation_sequence-1)
                self.assertFalse(_study_app_category_metadata(r.context,mismatched,session_id=1)["evidence_available"])
        r = self.rig(study=False)
        for kw, badge in (({},"SOCIAL"),({"process":"code"},"FOCUS"),({"process":"notepad"},"ACTIVITY"),
                          ({"process":"steam"},"GAMING"),({"process":"whatsapp"},"MESSAGING"),
                          ({"process":"netflix","ott":"netflix"},"OTT")):
            r.clock.step();r.observe(**kw)
            self.assertEqual(r.monitor._activity_telemetry_semantics(r.context)[0],badge)

    def test_T16_current_resource_and_study_RI_timer_scope(self):
        r = self.rig(); r.admit(); r.show(); r.clock.step(20)
        cls = actual_methods("CONTROL_STATION/application.py", "ControlPage",
                             ["_render_current_authority_interval", "_value", "_enum_text", "_format_seconds"])
        page = cls(); page._latest_sine_live_view = r.sine.live_view(); page._latest_blacklist_live_view = r.blacklist.live_view()
        page._dwell_track = Widget(); page._dwell_value = Widget(); page._ring = Widget()
        page._render_current_authority_interval()
        self.assertEqual(page._dwell_value.text(), "00:20 / 10:00")
        cls = actual_methods("COSECANT_STUDY_MODE/view.py", "ResourceIntentTelemetryPanel",
                             ["_render_authoritative_dwell"], {"_duration": lambda value: str(int(value))})
        panel = cls(); panel._values = {"dwell": Widget()}; panel._latest_resource_intent = r.ri.live_view()
        panel._latest_sine_live_view = r.sine.live_view(); panel._render_authoritative_dwell()
        self.assertEqual(panel._values["dwell"].text(), "20 / 600")
        panel._latest_sine_live_view = replace(r.sine.live_view(), study_mode=False, study_context_token="")
        panel._render_authoritative_dwell()
        self.assertEqual(panel._values["dwell"].text(), "301 / 300")
        r.monitor._publish_console_live_status(r.context)
        # Console and telemetry are observations; painting never mutates either authority.
        self.assertEqual(r.trigger.live_view().admitted_count, 1)
        self.assertEqual(r.study.snapshot().state, StudyState.ACTIVE)

    def test_T16_fact_badges_do_not_promote_requests_to_display_or_return(self):
        r = self.rig()
        cases = [("resource_intent","STUDY_UNCERTAINTY_STARTED","UNCERTAIN"),
                 ("resource_intent","STUDY_CONFIRMATION_POPUP_DISPLAYED","STUDY CONFIRM"),
                 ("resource_intent","USER_CONFIRMED_STUDY","USER CONFIRM"),
                 ("resource_intent","USER_CONFIRMED_OFF_TASK","USER CONFIRM"),
                 ("sine","SINE_STAGE_2_SCHEDULED","SINE"),
                 ("mirl","MIRL_RETURN_VERIFICATION_STARTED","RETURN INTENT"),
                 ("mirl","MIRL_CLOSURE_CONFIRMATION_STARTED","MIRL")]
        for domain,kind,badge in cases:
            self.assertEqual(r.monitor._semantic_domain_telemetry(domain,NS(kind=kind))["badge"],badge)
        self.assertEqual(r.monitor._semantic_domain_telemetry("mirl",NS(kind="MIRL_TRIGGER_PREPARED")),{})

    def test_source_fence_before_candidate_persistence(self):
        r = self.rig();r.dwell()
        c = r.trigger.evaluate(context=r.context,blacklist=r.black)
        r.clock.step(6)
        r.monitor._begin_trigger_persistence(c,r.context,r.black)
        self.assertFalse(r.db.candidates)
        self.assertEqual(r.trigger.live_view().admitted_count,0)

    def test_running_receipt_then_fresh_postcommit_observation_required(self):
        r = self.rig();r.db.receipt_state="RUNNING";r.dwell();r.submit()
        r.reconcile();self.assertFalse(r.db.mirl or r.db.sine)
        receipt=next(iter(r.db.receipts.values()));receipt.state="COMMITTED"
        r.monitor._reconcile_pending_trigger(r.context,r.black)
        self.assertFalse(r.db.mirl or r.db.sine)
        r.reconcile();self.assertEqual(r.trigger.live_view().admitted_count,1)

    def test_sine_rejection_abandons_exact_token_and_compensates(self):
        r=self.rig();r.dwell();r.submit()
        r.sine.emergency_stop()  # real SINE authority rejects the later handoff
        with self.assertRaises(RuntimeError):r.reconcile()
        self.assertFalse(r.mirl.live_view().pending_display)
        self.assertEqual(r.trigger.live_view().admitted_count,0)
        self.assertFalse(r.trigger.live_view().cooldown_active)

    def test_token_expiring_during_prepared_write_never_starts_sine(self):
        r=self.rig();r.dwell();r.submit()
        transport=r.db.append_mirl_events
        def slow_write(events):
            result=transport(events)
            r.clock.step(46)
            return result
        r.db.append_mirl_events=slow_write
        with self.assertRaises(RuntimeError):r.reconcile()
        self.assertFalse(r.sine.live_view().episode_uid)
        self.assertFalse(r.mirl.live_view().pending_display)
        self.assertFalse(r.trigger.live_view().cooldown_active)

    def test_background_audio_uses_RI_truth_and_rendered_tags_are_read_only(self):
        r=self.rig();r.dwell(300,title="lofi study music")
        live=r.ri.live_view()
        self.assertIs(live.classification,ri.ResourceIntent.BACKGROUND_AUDIO)
        self.assertIs(live.sine_contribution,ri.SineContribution.WITHHELD)
        self.assertIsNone(r.trigger.evaluate(context=r.context,blacklist=r.black))
        tree=ast.parse((ROOT/"COSECANT_STUDY_MODE/view.py").read_text(encoding="utf-8"))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="_study_task_match_text")
        env={"ResourceIntent":ri.ResourceIntent,"IntentReason":ri.IntentReason,"ResourceIntentLiveView":ri.ResourceIntentLiveView}
        exec(compile(ast.Module(body=[fn],type_ignores=[]),"view.py","exec"),env)
        for classification,label in ((ri.ResourceIntent.STUDY_ALIGNED,"ALIGNED"),(ri.ResourceIntent.DISTRACTION,"OFF-TASK"),
            (ri.ResourceIntent.UNCERTAIN,"UNCERTAIN"),(ri.ResourceIntent.APPROVED_BREAK,"BREAK"),
            (ri.ResourceIntent.BACKGROUND_AUDIO,"BACKGROUND AUDIO")):
            self.assertEqual(env["_study_task_match_text"](replace(live,classification=classification)),label)
        self.assertIs(r.ri.live_view().classification,ri.ResourceIntent.BACKGROUND_AUDIO)

    def test_normal_activity_monitor_and_recovery_holds_preserve_remainder(self):
        r=self.rig(study=False);r.admit();r.show();r.clock.step(17)
        uid=r.sine.live_view().candidate_uid
        self.assertTrue(r.sine.pause_escalation_for_activity(candidate_uid=uid,occurred_monotonic_ns=r.clock(),evidence_source="ordinary_activity"))
        status=r.sine.monitor_status(now_ns=r.clock())
        self.assertTrue(r.sine.monitor_hold(episode_key=status.episode_key,now_ns=r.clock()))
        r.clock.step(300);r.flush()
        self.assertEqual(r.sine.live_view().next_deadline_seconds,583)
        self.assertTrue(r.sine.monitor_resume(episode_key=status.episode_key,now_ns=r.clock()))
        self.assertTrue(r.sine.resume_escalation_after_activity(candidate_uid=uid,occurred_monotonic_ns=r.clock(),evidence_source="distraction"))
        self.assertEqual(r.sine.live_view().next_deadline_seconds,583)

    def test_normal_break_preserves_same_episode_and_no_Tr(self):
        r=self.rig(study=False);r.admit();r.show();sine=r.sine.live_view()
        self.assertTrue(r.sine.popup_response(request_id=sine.popup_request_id,response="request_break",occurred_monotonic_ns=r.clock()))
        result=r.normal_break.request_duration(episode_uid=sine.episode_uid,candidate_uid=sine.candidate_uid,
            source_sine_popup_request_id=sine.popup_request_id,requested_monotonic_ns=r.clock(),session_id=1)
        self.assertTrue(result.accepted)
        pending=r.normal_break.snapshot()
        result=r.normal_break.start_break(break_id=pending.break_id,generation=pending.generation,
            episode_uid=sine.episode_uid,candidate_uid=sine.candidate_uid,source_sine_popup_request_id=sine.popup_request_id,
            selected_minutes=5,started_monotonic_ns=r.clock())
        self.assertTrue(result.accepted)
        self.assertTrue(r.sine.hold_for_normal_break(candidate_uid=sine.candidate_uid,episode_uid=sine.episode_uid,
            break_id=pending.break_id,break_generation=pending.generation,started_monotonic_ns=r.clock(),
            source_popup_request_id=sine.popup_request_id))
        r.clock.step(300);r.flush()
        self.assertEqual(r.sine.live_view().episode_uid,sine.episode_uid)
        self.assertTrue(r.sine.live_view().normal_break_held)
        self.assertFalse(r.mirl.drain_verified_recovery_evidence())

    def test_ordinary_protected_red_still_restores_and_recovers(self):
        r=self.rig(study=False);r.stage(3)
        old=r.sine.live_view().popup_request_id
        self.assertTrue(r.close())
        r.clock.step();r.flush()
        self.assertNotEqual(r.sine.live_view().popup_request_id,old)
        self.assertTrue(r.show());self.assertTrue(r.sine.protected_red_active())
        for _ in range(72):
            r.clock.step()
            facts=r.mirl.record_recovery_observation(RecoveryObservation(RecoveryContext.FOCUS,r.clock(),
                "2026-09-24T11:00:00Z","test_focus",str(r.clock())))
            r.monitor._persist_mirl_events(facts);r.flush()
        self.assertIs(r.sine.live_view().phase,SinePhase.RESOLVED)
        self.assertFalse(r.sine.protected_red_active())
        self.assertEqual(len(r.monitor._observed_lambda_estimates),1)

    def test_shutdown_settles_candidate_and_restart_has_no_old_authority(self):
        r=self.rig();r.dwell();c=r.submit()
        r.monitor.stop_event.set();r.monitor._settle_pending_trigger_for_shutdown(wait_seconds=0)
        self.assertIs(r.trigger.trigger_result(c.candidate_uid).status,TriggerStatus.SETTLED_WITHOUT_INTERVENTION)
        self.assertFalse(r.db.sine or r.db.mirl)
        r2=self.rig();r2.observe()
        self.assertFalse(r2.sine.live_view().episode_uid)
        self.assertEqual(r2.trigger.live_view().admitted_count,0)

    def test_emergency_terminal_is_not_recovery(self):
        r=self.rig();r.admit();r.show();r.sine.emergency_stop();r.flush()
        self.assertIs(r.sine.live_view().phase,SinePhase.EMERGENCY_STOPPED)
        self.assertFalse(r.mirl.drain_verified_recovery_evidence())
        self.assertFalse(any(f.kind=="MIRL_RETURN_VERIFIED" for f in r.db.mirl))

    def test_report_humanizes_study_transition_and_keeps_aborted_evidence(self):
        r,projected=self._transition(2)
        tree=ast.parse((ROOT/"MIRL/report.py").read_text(encoding="utf-8"))
        methods=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in {"_outcome","_humanize"}]
        env={}
        exec(compile(ast.fix_missing_locations(ast.Module(body=methods,type_ignores=[])),"report.py","exec"),env)
        row=projected.live_mirl.recently_closed_episodes[0]
        self.assertEqual(row.final_outcome,"ABORTED")
        self.assertEqual(row.terminal_reason,"STUDY_MODE_ACTIVATED")
        self.assertEqual(env["_outcome"](row),"Study Mode started")
        self.assertIsNone(row.verified_return_latency_seconds)

    def test_phase3_clarification_timer_uses_only_RI_clock(self):
        r=self.rig(study=False);r.prepare(keywords=("alpha","beta","gamma","delta"));r.monitor._handle_study_action("START")
        r.observe(title="alpha beta",url="https://chatgpt.com/c/example")
        cls=actual_methods("COSECANT_STUDY_MODE/view.py","ResourceIntentTelemetryPanel",
                           ["_render_clarification"],{"_duration":lambda seconds:f"{int(seconds)//60:02d}:{int(seconds)%60:02d}"})
        panel=cls();panel._values={"clarification":Widget()};panel._latest_resource_intent=r.ri.live_view()
        panel._render_clarification();self.assertEqual(panel._values["clarification"].text(),"00:00 / 05:00")
        r.clock.step();r.observe(title="alpha beta",url="https://chatgpt.com/c/example")
        panel._latest_resource_intent=r.ri.live_view();panel._render_clarification()
        self.assertEqual(panel._values["clarification"].text(),"00:01 / 05:00")
        r.dwell(299,title="alpha beta",url="https://chatgpt.com/c/example")
        panel._latest_resource_intent=r.ri.live_view();panel._render_clarification()
        self.assertEqual(panel._values["clarification"].text(),"05:00 / 05:00")
        self.assertEqual(panel._latest_resource_intent.uncertainty_target_seconds,300)
        self.assertIs(panel._latest_resource_intent.sine_contribution,ri.SineContribution.NONE)

    def test_phase3_study_confirmation_bridge_same_web_content_and_new_resource(self):
        r=self.rig(study=False);r.prepare(keywords=("alpha","beta","gamma","delta"));r.monitor._handle_study_action("START")
        url="https://chatgpt.com/c/example";r.dwell(300,title="alpha beta",url=url)
        fact=next(f for f in r.ri.drain_facts() if f.kind=="STUDY_CONFIRMATION_POPUP_REQUESTED")
        request=fact.popup;self.assertIs(r.context.resource_intent.verdict.classification,ri.ResourceIntent.UNCERTAIN)
        self.assertTrue(r.ri.record_study_confirmation_popup_shown(request_id=request.request_id,shown_monotonic_ns=r.clock(),popup_hwnd=909))
        r.commands.put(NS(kind="study_confirmation_user_action",payload=dict(request_id=request.request_id,
            response=ri.StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL.value,occurred_monotonic_ns=r.clock(),
            expected_study_context_token=request.study_context_token,expected_resource_key=request.resource_key),
            response_queue=queue.SimpleQueue()))
        response=r.commands.queue[0].response_queue
        r.monitor._drain_commands();self.assertTrue(response.get_nowait())
        self.assertIs(r.ri.live_view().classification,ri.ResourceIntent.STUDY_ALIGNED)
        self.assertFalse(r.ri.live_view().uncertainty_active)
        self.assertEqual(sum(entry.case1_popup_confirmed and entry.user_confirmation is ri.StudyUserConfirmation.STUDY for entry in r.ri._study_memory.values()),1)
        for _ in range(301):
            r.clock.step();r.observe(title="alpha beta",url=url)
        self.assertIs(r.ri.live_view().classification,ri.ResourceIntent.STUDY_ALIGNED)
        self.assertFalse(r.ri.live_view().uncertainty_active)
        self.assertFalse(any(f.kind=="STUDY_CONFIRMATION_POPUP_REQUESTED" for f in r.ri.drain_facts()))
        r.clock.step();r.observe(title="alpha beta",url="https://chatgpt.com/c/different")
        self.assertIs(r.ri.live_view().classification,ri.ResourceIntent.UNCERTAIN)
        self.assertTrue(r.ri.live_view().uncertainty_active)

    def test_phase3_popup_study_requires_exact_browser_identity(self):
        r=self.rig(study=False);r.prepare(keywords=("alpha","beta","gamma","delta"));r.monitor._handle_study_action("START")
        r.dwell(300,title="alpha beta",url="")
        request=next(f.popup for f in r.ri.drain_facts() if f.kind=="STUDY_CONFIRMATION_POPUP_REQUESTED")
        self.assertFalse(r.ri.record_study_confirmation_response(request_id=request.request_id,
            response=ri.StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL.value,
            occurred_monotonic_ns=r.clock(),expected_study_context_token=request.study_context_token,
            expected_resource_key=request.resource_key))
        self.assertIs(r.ri.live_view().classification,ri.ResourceIntent.UNCERTAIN)
        self.assertFalse(r.ri._study_memory)
        secret=b"phase3-exact-resource"
        for first,second in (
            ("https://chatgpt.com/c/one","https://chatgpt.com/c/two"),
            ("https://coursera.org/learn/one","https://coursera.org/learn/two"),
            ("https://youtube.com/shorts/one","https://youtube.com/shorts/two"),
        ):
            token1=br.classify_address_value(first,identity_secret=secret).resource_token
            token2=br.classify_address_value(second,identity_secret=secret).resource_token
            self.assertTrue(token1)
            self.assertNotEqual(token1,token2)
            self.assertEqual(token1,br.classify_address_value(first,identity_secret=secret).resource_token)

    def test_phase3_confirmation_acknowledgement_does_not_timeout_on_gui(self):
        cls=actual_methods("CONTROL_STATION/controller.py","ControlStationController",
                           ["_submit_study_confirmation_action","_drain_study_confirmation_acknowledgements"])
        controller=cls();controller._pending_study_confirmation_actions={}
        rejected=[];controller._study_confirmation_presenter=NS(
            show_action_rejection=lambda request_id,message:rejected.append((request_id,message)))
        queued=[];controller._enqueue_command=lambda kind,payload,response_queue:queued.append((kind,payload,response_queue)) or True
        self.assertTrue(controller._submit_study_confirmation_action("one","THIS_IS_STUDY_MATERIAL",100,"ctx","key"))
        self.assertEqual(len(queued),1)
        self.assertIn("one",controller._pending_study_confirmation_actions)
        controller._drain_study_confirmation_acknowledgements()
        self.assertEqual(rejected,[])
        queued[0][2].put(True)
        controller._drain_study_confirmation_acknowledgements()
        self.assertFalse(controller._pending_study_confirmation_actions)
        self.assertEqual(rejected,[])
        self.assertTrue(controller._submit_study_confirmation_action("two","IM_COMING_BACK",101,"ctx","key"))
        queued[1][2].put(False)
        controller._drain_study_confirmation_acknowledgements()
        self.assertEqual(rejected[0][0],"two")

    def test_phase3_confirmation_popup_focus_before_shown_ack_preserves_request(self):
        import os
        r=self.rig(study=False);r.prepare(keywords=("alpha","beta","gamma","delta"));r.monitor._handle_study_action("START")
        url="https://chatgpt.com/c/example";r.dwell(300,title="alpha beta",url=url)
        request=next(f.popup for f in r.ri.drain_facts() if f.kind=="STUDY_CONFIRMATION_POPUP_REQUESTED")
        r.clock.step();r.observe(process="python.exe",process_id=os.getpid(),hwnd=909,
            title="MYELIN \u2014 STUDY CONFIRMATION",url="")
        self.assertEqual(r.ri.live_view().uncertainty_popup_request_id,request.request_id)
        self.assertTrue(r.ri.record_study_confirmation_popup_shown(request_id=request.request_id,
            shown_monotonic_ns=r.clock(),popup_hwnd=909))
        self.assertTrue(r.ri.record_study_confirmation_response(request_id=request.request_id,
            response=ri.StudyConfirmationResponse.THIS_IS_STUDY_MATERIAL.value,
            occurred_monotonic_ns=r.clock(),expected_study_context_token=request.study_context_token,
            expected_resource_key=request.resource_key))
        r.clock.step();r.observe(title="alpha beta",url=url)
        self.assertIs(r.ri.live_view().classification,ri.ResourceIntent.STUDY_ALIGNED)

    def test_phase3_coming_back_starts_fresh_study_sine_dwell(self):
        r=self.rig(study=False);r.prepare(keywords=("alpha","beta","gamma","delta"));r.monitor._handle_study_action("START")
        url="https://chatgpt.com/c/example";r.dwell(300,title="alpha beta",url=url)
        request=next(f.popup for f in r.ri.drain_facts() if f.kind=="STUDY_CONFIRMATION_POPUP_REQUESTED")
        self.assertTrue(r.ri.record_study_confirmation_popup_shown(request_id=request.request_id,
            shown_monotonic_ns=r.clock(),popup_hwnd=909))
        self.assertTrue(r.ri.record_study_confirmation_response(request_id=request.request_id,
            response=ri.StudyConfirmationResponse.IM_COMING_BACK.value,
            occurred_monotonic_ns=r.clock(),expected_study_context_token=request.study_context_token,
            expected_resource_key=request.resource_key))
        self.assertIs(r.ri.live_view().classification,ri.ResourceIntent.DISTRACTION)
        self.assertEqual(r.ri.live_view().dwell_elapsed_seconds,0)
        self.assertIs(r.ri.live_view().sine_contribution,ri.SineContribution.PENDING)
        r.clock.step();r.observe(title="alpha beta",url=url)
        self.assertEqual(r.ri.live_view().dwell_elapsed_seconds,1)
        r.dwell(299,title="alpha beta",url=url)
        self.assertIs(r.ri.live_view().sine_contribution,ri.SineContribution.READY)
        self.assertIs(r.trigger.evaluate(context=r.context,blacklist=r.black).evidence.source,TriggerSource.STUDY_OFF_TASK)

    def test_phase3_cosecant_inhibits_normal_watch_before_threshold_and_rebases_after_complete(self):
        quick=self.rig(study=False)
        quick.dwell(299,title="Funny entertainment",url="https://www.instagram.com/reels/abc")
        self.assertFalse(quick.black.threshold_reached)
        quick.prepare();quick.monitor._handle_study_action("START")
        self.assertTrue(quick.blacklist.live_view().sine_watch_inhibited)
        quick.clock.step();quick.monitor._handle_study_action("COMPLETE")
        quick.clock.step();quick.observe(title="Funny entertainment",url="https://www.instagram.com/reels/abc")
        self.assertEqual(quick.black.elapsed_seconds,0)
        self.assertIsNone(quick.black.threshold_offer)
        study_r=self.rig()
        study_r.dwell(320,title="Funny entertainment",url="https://www.instagram.com/reels/abc")
        self.assertTrue(study_r.context.study_owned)
        self.assertTrue(study_r.blacklist.live_view().sine_watch_inhibited)
        self.assertFalse(study_r.black.threshold_reached)
        self.assertIsNone(study_r.black.threshold_offer)
        self.assertIs(study_r.sine.live_view().phase,SinePhase.IDLE)
        r=self.rig();self.start_cosecant(r)
        for state in (CosecantState.BREAK_ACTIVE,CosecantState.BREAK_COMPLETE,
                      CosecantState.BREAK_ALREADY_OVER,CosecantState.RETURN_CONFIRMING,CosecantState.FINAL_LOCK):
            self.assertTrue(r.monitor._cosecant_owns_break_return(NS(state=state)))
        r.dwell(320,title="Funny entertainment",url="https://www.instagram.com/reels/abc")
        self.assertTrue(r.context.study_owned)
        self.assertGreater(r.black.elapsed_seconds,300)  # descriptive Blacklist remains factual
        self.assertFalse(r.black.threshold_reached)
        self.assertIsNone(r.black.threshold_offer)
        self.assertTrue(r.blacklist.live_view().sine_watch_inhibited)
        r.monitor._prepare_dwell_telemetry(replace(r.black,restarted=True,study_context_active=False))
        self.assertIsNone(r.monitor._pending_dwell_telemetry)
        self.assertIsNone(r.blacklist.live_view().next_sine_stage)
        self.assertIs(r.sine.live_view().phase,SinePhase.IDLE)
        self.assertEqual(r.trigger.live_view().admitted_count,0)
        cls=actual_methods("CONTROL_STATION/application.py","ControlPage",
                           ["_render_current_authority_interval","_value","_enum_text","_format_seconds"])
        page=cls();page._latest_sine_live_view=r.sine.live_view();page._latest_blacklist_live_view=r.blacklist.live_view()
        page._dwell_track=Widget();page._dwell_value=Widget();page._ring=Widget()
        page._render_current_authority_interval()
        self.assertEqual(page._dwell_value.text(),"— / —")
        r.monitor._handle_study_action("COMPLETE")
        self.assertIs(r.study.snapshot().state,StudyState.COMPLETED)
        r.clock.step();r.observe(title="Funny entertainment",url="https://www.instagram.com/reels/abc")
        self.assertFalse(r.context.study_owned)
        self.assertFalse(r.blacklist.live_view().sine_watch_inhibited)
        self.assertEqual(r.black.elapsed_seconds,0)
        self.assertFalse(r.black.threshold_reached)
        self.assertIsNone(r.black.threshold_offer)
        r.dwell(300,title="Funny entertainment",url="https://www.instagram.com/reels/abc")
        self.assertTrue(r.black.threshold_reached)
        self.assertIsNotNone(r.black.threshold_offer)

    def test_T20_schema_and_protected_manifest(self):
        import hashlib
        manifest=ROOT.parent/"GOOD PROGRAMS/STUDY MODE FOR GOOD/PHASE3_THREE_LIVE_ISSUES_SOURCE_20260924_001_MANIFEST.json"
        data=json.loads(manifest.read_text(encoding="utf-8-sig"))
        self.assertEqual(len(data),91)
        phase3_changes={
            "CORE_ENGINE/browser.py", "CORE_ENGINE/blacklist.py",
            "CORE_ENGINE/monitor.py", "CORE_ENGINE/resource_intent.py",
            "COSECANT_STUDY_MODE/view.py", "CONTROL_STATION/application.py",
            "CONTROL_STATION/controller.py", "test_phase2_study_reconstruction.py",
        }
        for row in data:
            path=row["path"]
            if path not in phase3_changes:
                self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest().upper(),row["sha256"].upper(),path)
        before=ROOT.parent/"SAFE BACKUP/PHASE2_STUDY_RECONSTRUCTION_SOURCE_20260924_001/PERSISTENCE/storage.py"
        def ddl(path):
            tree=ast.parse(path.read_text(encoding="utf-8-sig"))
            return [n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)
                    and any(word in n.value.upper() for word in ("CREATE TABLE", "ALTER TABLE", "CREATE INDEX"))]
        self.assertEqual(ddl(before),ddl(ROOT/"PERSISTENCE/storage.py"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
