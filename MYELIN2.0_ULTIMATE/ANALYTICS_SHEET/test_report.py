"""Regression tests for the date-specific, four-organ Analytics Sheet.

Fixtures are synthetic inputs shaped like the real projections; no value is a
MYELIN measurement.  Lifetime "trap" values (large distinctive numbers) prove
that nothing from an all-time projection leaks into a selected-period report.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ANALYTICS_SHEET import model as M
from ANALYTICS_SHEET import render as R

try:  # pragma: no cover - environment dependent
    import pymupdf
except ImportError:  # pragma: no cover
    pymupdf = None

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 9, 19, 6, 30, tzinfo=timezone.utc)
A4_PT = (595.28, 841.89)
ALL = M.SECTION_KEYS


class Integ(Enum):
    CONFIRMED = "CONFIRMED"
    DEGRADED = "DEGRADED"


class Sev(Enum):
    ERROR = "ERROR"


def ist(y, mo, d, h=0, mi=0, s=0, us=0) -> str:
    """UTC ISO string (Z) of an IST wall-clock instant."""

    return (datetime(y, mo, d, h, mi, s, us, tzinfo=IST).astimezone(timezone.utc)).isoformat().replace("+00:00", "Z")


def plus(iso: str, **delta) -> str:
    return (datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(**delta)).isoformat().replace("+00:00", "Z")


def issue(code="INVALID_WALL_TIMESTAMP", episode="", event="", detail="Event UTC timestamp is malformed."):
    return SimpleNamespace(code=code, severity=Sev.ERROR, detail=detail, episode_id=episode, event_id=event)


def mirl_episode(n, start, *, rows=6, degraded=False, closed=True, event_times=None, issues=()):
    eid = f"mirl-episode-{n:032x}"
    times = event_times or [plus(start, seconds=i * 7) for i in range(rows)]
    names = ["episode_created", "sine_displayed", "sine_response_recorded", "return_intent_recorded", "return_verified", "episode_closed"]
    tl = tuple(
        SimpleNamespace(
            episode_id=eid, episode_seq=i + 1, occurred_at=t, event_name=names[i % len(names)],
            observed_or_derived="DERIVED" if names[i % len(names)] in {"return_verified", "episode_closed"} else "OBSERVED",
            reason_or_outcome_code="RETURN_TO_FOCUS" if i == 2 else None,
            reference=f"mirl-event-{n:08x}{i:024x}" if i == 1 else None,
            integrity_status=Integ.DEGRADED if degraded else Integ.CONFIRMED,
        )
        for i, t in enumerate(times)
    )
    return SimpleNamespace(
        episode_id=eid, short_display_id=f"EPI-{n:02d}092026-01", source_event_id=n, session_id=100 + n,
        candidate_uid=f"trg_{n:032x}", started_at=start,
        episode_status="DEGRADED" if degraded else ("CLOSED_RETURNED" if closed else "WAITING_FOR_RETURN"),
        final_outcome="RETURNED" if closed else None,
        return_intent_latency_seconds=5.09, verified_return_latency_seconds=47.57 if closed else None,
        stable_recovery_latency_seconds=109.06 if closed else None, recovery_attempt_count=1, relapse_count=0,
        relapse_timings_seconds=(), sine_stages_exposed=(1,), sine_responses=("RETURN_TO_FOCUS",), timeline=tl,
        integrity_status=Integ.DEGRADED if degraded else Integ.CONFIRMED, integrity_issues=tuple(issues),
        application="youtube", trigger_fired_at=plus(start, seconds=-2),
    )


def cosine_event(ep, seq, ts, name="CONTENT_OBSERVED", title="", payload=None, withheld=0):
    return SimpleNamespace(
        event_id=f"c{ep:04x}{seq:028x}", cosine_session_id=f"cosine-{ep:04d}", generation=1, sequence=seq,
        event_name=name, event_class="OBSERVED", occurred_at_utc=ts, occurred_at_display="x", timezone_label="IST",
        platform_key="prime_video", platform_label="Prime Video", content_title=title, request_id="",
        payload_display=MappingProxyType(payload or {}), withheld_payload_field_count=withheld, schema_version="v",
    )


def cosine_episode(ep, start, *, events=5, event_times=None, title="", outcome="INCOMPLETE"):
    times = event_times or [plus(start, seconds=i * 30) for i in range(events)]
    evs = tuple(
        cosine_event(ep, i + 1, t, name="COSINE_SESSION_STARTED" if i == 0 else "CONTENT_OBSERVED", title=title if i == 1 else "",
                     payload={"evidence_source": "WINDOWS_APP"} if i == 0 else {}, withheld=2 if i == 0 else 0)
        for i, t in enumerate(times)
    )
    return SimpleNamespace(
        cosine_session_id=f"cosine-{ep:04d}", generation=1, parent_session_id=100 + ep, started_at_utc=start,
        started_at_display="x", ended_at_utc=times[-1], ended_at_display="x", starting_platform_key="prime_video",
        starting_platform_label="Prime Video", event_count=len(evs), user_choice=None, chosen_break_minutes=None,
        hopper_count=0, hopper_transitions=(), closure_reason="STOPPED", closure_outcome=outcome, is_closed=True,
        events=evs, hold_context=False, hold_context_reason=None,
    )


def mine_event(n, seq, ts, name="MINE_CANDIDATE_STARTED", facts=None, elapsed=None):
    return SimpleNamespace(
        session_id=100 + n, generation=1, mine_episode_id=f"mine-{n:04d}", sequence=seq, event_name=name,
        event_class="OBSERVED", occurred_at_utc=ts, occurred_at_display="x", timezone_label="IST",
        platform_key="whatsapp", platform_label="WhatsApp", payload_facts=MappingProxyType(facts or {}),
        withheld_payload_field_count=0, elapsed_from_previous_seconds=elapsed, schema_version="v",
    )


def mine_episode(n, start, *, branch="I_WILL_COME_BACK", outcome="RETURNED_AFTER_CALLBACK", verified=True, event_times=None, dwell=()):
    times = event_times or [plus(start, seconds=i * 60) for i in range(4)]
    evs = tuple(mine_event(n, i + 1, t, name=("MINE_CANDIDATE_STARTED" if i == 0 else "RETURN_CONFIRMED" if i == 3 else "RETURN_INTENT_RECORDED"), elapsed=None if i == 0 else 60.0) for i, t in enumerate(times))
    return SimpleNamespace(
        session_id=100 + n, generation=1, mine_episode_id=f"mine-{n:04d}", display_episode_id=f"MINE-{n:02d}092026-01",
        started_at_utc=start, started_at_display="x", ended_at_utc=times[-1], ended_at_display="x",
        starting_platform_key="whatsapp", starting_platform_label="WhatsApp", branch=branch, important_duration_minutes=None,
        closure_outcome=outcome, closure_reason="VERIFIED_RETURN" if verified else "STOPPED", is_closed=outcome is not None,
        return_verified=verified, closure_confirmed=verified, event_count=len(evs), events=evs, return_closure_events=(),
        messenger_platforms=(), messenger_hops=(), mbi_available=bool(dwell), mbi_status_message="", dwell_records=tuple(dwell),
    )


def study_row(row_id, session, block, action, state, created, *, started="", subject="Neuroscience", task="Reading", planned=2700, elapsed=0.0, completed="", note="note"):
    payload = {"block_id": block, "state": state, "started_wall_time_utc": started, "completed_wall_time_utc": completed,
               "subject": subject, "task": task, "planned_seconds": planned, "elapsed_seconds": elapsed,
               "completion_reason": "NONE", "last_action": note, "schema_version": "myelin-study-v4"}
    return SimpleNamespace(source_event_id=f"study_events:{row_id}", session_id=session, kind=action, occurred_monotonic_ns=row_id,
                           payload_json=json.dumps(payload), created_at_utc=created)


def study_block(idx, start, *, complete=True, late=None):
    bid = f"block{idx:04d}"
    rows = [
        study_row(idx * 10 + 1, idx, bid, "PREPARE", "READY", plus(start, seconds=-8)),
        study_row(idx * 10 + 2, idx, bid, "START", "ACTIVE", start, started=start),
    ]
    if complete:
        done = late or plus(start, minutes=45)
        rows.append(study_row(idx * 10 + 3, idx, bid, "COMPLETE", "COMPLETED", done, started=start, completed=done, elapsed=2700.0))
    return rows


def snapshot(*, mirl=None, cosine=None, mine=None, issues=(), exclusions=(), mirl_projection=..., cosine_projection=..., mine_projection=...):
    mirl = list(mirl or [])
    open_ones = [e for e in mirl if e.episode_status == "WAITING_FOR_RETURN"]
    lifetime_trap = MappingProxyType({"RETURNED": 987654, "PENDING": 13, "DEGRADED": 47})
    live = SimpleNamespace(
        available=bool(mirl), empty_state_reason=None if mirl else "No factual MIRL episode has been recorded.",
        metadata=SimpleNamespace(start_time=None, end_time=None, selected_range_label="All supplied MIRL evidence", exclusions=tuple(exclusions), exclusion_count=555444,
                                 research_provenance=SimpleNamespace(limitation="Read-only behavioral software evidence. No clinical inference.", episode_event_count=777888)),
        active_episodes=tuple(open_ones), recently_closed_episodes=tuple(e for e in mirl if e not in open_ones),
        native_outcome_counts=lifetime_trap, status_message="DEGRADED EVIDENCE", integrity_status=Integ.DEGRADED,
        integrity_issues=tuple(issues), worst_return_latency_seconds=555555.55,
    )
    cos = SimpleNamespace(
        available=True, status="AVAILABLE" if cosine else "EMPTY", read_error=None, status_message="Facts from the database snapshot.",
        overview=SimpleNamespace(captured_episode_count=424242, confirmed_return_count=313131, break_started_count=5, population_scope="DATABASE_SNAPSHOT"),
        episodes=tuple(cosine or ()), latest_events=(), structural_issues=(),
    )
    mn = SimpleNamespace(
        available=True, status="AVAILABLE" if mine else "EMPTY", read_error=None, status_message="Facts from the durable MINE snapshot.",
        overview=SimpleNamespace(captured_episode_count=636363), episodes=tuple(mine or ()), latest_events=(), structural_issues=(),
    )
    metric = SimpleNamespace(total_session_count=138137, total_trigger_count=77077)
    return SimpleNamespace(
        live_mirl=live if mirl_projection is ... else mirl_projection,
        cosine=cos if cosine_projection is ... else cosine_projection,
        mine=mn if mine_projection is ... else mine_projection,
        metric_hub=metric, legacy_evidence_summary=metric, lifetime_metric_hub=None,
    )


def request(sections=ALL, start=date(2026, 9, 17), end=date(2026, 9, 19), tz_key="local"):
    keys = tuple(sections)
    return SimpleNamespace(range_start=start, range_end=end, selected_sections=lambda: keys, presentation_timezone=tz_key)


LIFETIME_TRAPS = ("987,654", "555,555", "138,137", "77,077", "424,242", "313,131", "636,363", "777,888", "555,444")

# Standard populations: two inside 17-19 Sep 2026 (IST), older records outside.
D17 = ist(2026, 9, 17, 9, 0)
D18 = ist(2026, 9, 18, 21, 15)
OLD = ist(2026, 9, 3, 10, 0)


def standard_snapshot(**kw):
    return snapshot(
        mirl=[mirl_episode(1, D17), mirl_episode(2, D18, degraded=True, issues=[issue(episode=f"mirl-episode-{2:032x}", event="mirl-event-in-range")]), mirl_episode(3, OLD, degraded=True, issues=[issue(episode=f"mirl-episode-{3:032x}", event="mirl-event-OLD")])],
        cosine=[cosine_episode(1, D17), cosine_episode(2, OLD)],
        mine=[mine_episode(1, D18), mine_episode(2, OLD)],
        issues=[issue(episode=f"mirl-episode-{2:032x}", event="mirl-event-in-range"), issue(episode=f"mirl-episode-{3:032x}", event="mirl-event-OLD"), issue(episode="", event="mirl-event-GLOBAL", code="CONTROL_EVENT_SCHEMA_MISMATCH")],
        **kw,
    )


def standard_study():
    return tuple(study_block(1, D17) + study_block(2, OLD) + [study_row(99, 9, "", "SAFE_SHUTDOWN", "SHUTDOWN", D18)])


def model(snap=None, req=None, study="default", **kw):
    study_records = standard_study() if study == "default" else study
    return M.build_report(snap if snap is not None else standard_snapshot(), req or request(), generated_at=NOW, tz=IST, study_records=study_records, **kw)


def texts(m) -> str:
    """Every string of the model (for leak checks)."""

    out: list[str] = []

    def walk(value):
        if isinstance(value, str):
            out.append(value)
        elif hasattr(value, "__dataclass_fields__"):
            for f in value.__dataclass_fields__:
                walk(getattr(value, f))
        elif isinstance(value, (tuple, list)):
            for v in value:
                walk(v)

    for s in m.sections:
        walk(s)
    return "\n".join(out)


def chapter(m, key):
    return next(s for s in m.sections if s.key == key)


def records(m, key):
    return [b for b in chapter(m, key).blocks if isinstance(b, M.Record)]


def table(m, key, title):
    return next(b for b in chapter(m, key).blocks if isinstance(b, M.Table) and b.title == title)


class _Tmp(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.tmp = Path(self._tmp.name)
        self._docs: list = []

    def open(self, path):
        doc = pymupdf.open(str(path))
        self._docs.append(doc)
        return doc

    def tearDown(self) -> None:
        for doc in self._docs:
            doc.close()
        self._tmp.cleanup()

    def build(self, snap=None, req=None, name="sheet.pdf", study="default", **kw):
        path = self.tmp / name
        result = R.build_analytics_sheet_pdf(
            snapshot=snap if snap is not None else standard_snapshot(), request=req or request(), output_path=path,
            generated_at=NOW, tz=IST, study_records=standard_study() if study == "default" else study, **kw,
        )
        return path, result

    def text(self, path) -> str:
        return "\n".join(p.get_text() for p in self.open(path))


# --------------------------------------------------------------------------
# Selection: the four organs
# --------------------------------------------------------------------------


class SelectionTests(unittest.TestCase):
    def test_each_checkbox_controls_exactly_its_own_chapter(self) -> None:
        for key in ALL:
            m = model(req=request((key,)))
            self.assertEqual([s.title for s in m.sections if s.key in ALL], [M.SECTION_TITLES[key]], key)
            self.assertEqual(m.cover_items, (M.SECTION_TITLES[key],))
            for other in ALL:
                if other != key:
                    self.assertFalse(any(s.key == other for s in m.sections), f"{other} must not appear when only {key} is selected")

    def test_multiple_and_all_organs_use_the_fixed_approved_order(self) -> None:
        m = model(req=request(("study-mode", "mine", "cosine", "live-mirl")))
        self.assertEqual(m.cover_items, ("MIRL", "COSINE", "MINE", "STUDY MODE"))
        self.assertEqual([s.key for s in m.sections if s.key in ALL], list(ALL))
        two = model(req=request(("mine", "live-mirl")))
        self.assertEqual(two.cover_items, ("MIRL", "MINE"))

    def test_metric_hub_and_science_lab_are_gone_from_the_report(self) -> None:
        m = model()
        blob = texts(m)
        for gone in ("Metric Hub", "Science Lab", "Native outcome counts", "Rates and latency"):
            self.assertNotIn(gone, blob)
        with self.assertRaises(ValueError):
            M.build_report(standard_snapshot(), request(("metric-hub",)), generated_at=NOW, tz=IST)
        with self.assertRaises(ValueError):
            M.build_report(standard_snapshot(), request(("science-lab",)), generated_at=NOW, tz=IST)

    def test_at_least_one_organ_is_required(self) -> None:
        with self.assertRaises(ValueError):
            M.build_report(standard_snapshot(), request(()), generated_at=NOW, tz=IST)

    def test_from_after_to_is_rejected_by_the_report_builder(self) -> None:
        with self.assertRaises(ValueError):
            model(req=request(start=date(2026, 9, 19), end=date(2026, 9, 17)))


# --------------------------------------------------------------------------
# Date filtering, per organ
# --------------------------------------------------------------------------


class FilterTests(unittest.TestCase):
    def test_only_qualifying_episodes_enter_every_organ_chapter(self) -> None:
        m = model()
        self.assertEqual(m.included["live-mirl"], (f"mirl-episode-{1:032x}", f"mirl-episode-{2:032x}"))
        self.assertEqual(m.included["cosine"], ("cosine-0001#1",))
        self.assertEqual(m.included["mine"], ("mine-0001",))
        self.assertEqual(m.included["study-mode"], ("block0001",))
        blob = texts(m)
        for old in (f"mirl-episode-{3:032x}", "EPI-03092026-01", "cosine-0002", "mine-0002", "block0002"):
            self.assertNotIn(old, blob, f"older record {old} leaked into the selected-period report")

    def test_boundary_episodes_from_midnight_included_and_after_to_excluded(self) -> None:
        snap = snapshot(mirl=[
            mirl_episode(1, ist(2026, 9, 16, 23, 59, 59, 999999)),  # just before FROM
            mirl_episode(2, ist(2026, 9, 17, 0, 0, 0)),  # exactly FROM midnight
            mirl_episode(3, ist(2026, 9, 19, 23, 59, 59, 999999)),  # last instant of TO
            mirl_episode(4, ist(2026, 9, 20, 0, 0, 0)),  # exactly the boundary after TO
        ])
        m = model(snap, study=())
        self.assertEqual([i[-32:] for i in m.included["live-mirl"]], [f"{2:032x}", f"{3:032x}"])

    def test_one_day_and_multi_day_ranges(self) -> None:
        one = model(req=request(start=date(2026, 9, 17), end=date(2026, 9, 17)))
        self.assertEqual(len(one.included["live-mirl"]), 1)
        wide = model(req=request(start=date(2026, 9, 1), end=date(2026, 9, 30)))
        self.assertEqual(len(wide.included["live-mirl"]), 3)
        self.assertEqual(len(wide.included["cosine"]), 2)

    def test_local_versus_utc_dates_change_membership(self) -> None:
        # 2026-09-17 20:00 UTC is 18 Sep 01:30 IST.
        snap = snapshot(mirl=[mirl_episode(1, "2026-09-17T20:00:00Z")])
        one_day = request(("live-mirl",), date(2026, 9, 17), date(2026, 9, 17))
        as_ist = M.build_report(snap, one_day, generated_at=NOW, tz=IST)
        as_utc = M.build_report(snap, one_day, generated_at=NOW, tz=timezone.utc)
        self.assertEqual((len(as_ist.included["live-mirl"]), len(as_utc.included["live-mirl"])), (0, 1))

    def test_selected_timezone_key_from_the_request_is_used(self) -> None:
        snap = snapshot(mirl=[mirl_episode(1, "2026-09-17T20:00:00Z")])
        for key, expected in (("Asia/Kolkata", 0), ("UTC", 1)):
            m = M.build_report(snap, request(("live-mirl",), date(2026, 9, 17), date(2026, 9, 17), tz_key=key), generated_at=NOW)
            self.assertEqual(len(m.included["live-mirl"]), expected, key)

    def test_episode_crossing_midnight_keeps_its_whole_timeline_and_marks_outside_events(self) -> None:
        start = ist(2026, 9, 19, 23, 58)
        times = [start, plus(start, minutes=1), plus(start, minutes=3), plus(start, minutes=5)]  # last three are on 20 Sep
        snap = snapshot(mirl=[mirl_episode(1, start, event_times=times)])
        m = model(snap, request(("live-mirl",)))
        rec = records(m, "live-mirl")[0]
        self.assertEqual(len(rec.table.rows), 4, "the recorded timeline must not be truncated")
        self.assertEqual([r[1].sub for r in rec.table.rows], ["", "", "outside selected period", "outside selected period"])
        self.assertIn("2 event(s) of this episode fall outside the selected dates", rec.caption)

    def test_an_older_episode_with_events_inside_the_range_is_not_included(self) -> None:
        start = ist(2026, 9, 16, 23, 50)
        snap = snapshot(mirl=[mirl_episode(1, start, event_times=[start, ist(2026, 9, 17, 0, 5), ist(2026, 9, 17, 0, 10)])])
        m = model(snap, request(("live-mirl",)))
        self.assertEqual(m.included["live-mirl"], ())
        self.assertNotIn(f"mirl-episode-{1:032x}", texts(m))

    def test_mirl_chapter_reconciles_index_records_and_included_identities(self) -> None:
        m = model()
        index = table(m, "live-mirl", "Episode index")
        recs = records(m, "live-mirl")
        self.assertEqual(len(index.rows), len(recs), len(m.included["live-mirl"]))
        self.assertEqual([r[0].text for r in index.rows], [r.title for r in recs])
        self.assertEqual([dict(r.ids)["Episode"] for r in recs], list(m.included["live-mirl"]))
        cards = next(b for b in chapter(m, "live-mirl").blocks if isinstance(b, M.CardRow)).cards
        self.assertEqual(cards[0].value, str(len(recs)))
        status = table(m, "live-mirl", "Recorded episode status")
        self.assertEqual(sum(int(r[1].text) for r in status.rows), len(recs))

    def test_mirl_keeps_recorded_facts_without_inferring_recovery(self) -> None:
        snap = snapshot(mirl=[mirl_episode(1, D17, closed=False)])
        rec = records(model(snap, request(("live-mirl",))), "live-mirl")[0]
        facts = dict(rec.facts)
        self.assertEqual(facts["Final outcome"], "Not closed")
        self.assertEqual(facts["Verified return"], M.DASH)
        self.assertEqual(facts["Return intent"], "5.09 s")
        self.assertEqual(rec.table.rows[3][2].text, "Return intent recorded")
        self.assertEqual([r[3].text for r in rec.table.rows][:2], ["OBSERVED", "OBSERVED"])
        self.assertIn("DERIVED", [r[3].text for r in rec.table.rows])

    def test_cosine_episodes_events_and_no_duration_inference(self) -> None:
        snap = snapshot(cosine=[cosine_episode(1, D17, title="Prime Video: Sample"), cosine_episode(2, OLD)])
        m = model(snap, request(("cosine",)))
        rec = records(m, "cosine")
        self.assertEqual(len(rec), 1)
        rows = rec[0].table.rows
        self.assertEqual([r[0].text for r in rows], ["1", "2", "3", "4", "5"])
        self.assertEqual(rows[0][1].sub, D17)
        self.assertIn("2 payload field(s) withheld by the source", rows[0][5].text)
        self.assertIn("Title: Prime Video: Sample", rows[1][5].text)
        blob = texts(m)
        self.assertIn("no continuous viewing duration is inferred", blob)
        self.assertNotIn("viewing time", blob.lower())
        outcome = table(m, "cosine", "Recorded closure outcome")
        self.assertEqual([(r[0].text, r[1].text) for r in outcome.rows], [("Incomplete", "1")])

    def test_mine_chapter_choices_outcomes_and_verified_flags_are_as_recorded(self) -> None:
        dwell = [SimpleNamespace(segment_order=1, platform_label="WhatsApp", dwell_seconds=620.5, mbi_band="11\u201330 MIN", completed_at_utc=plus(D18, minutes=10))]
        snap = snapshot(mine=[
            mine_episode(1, D18, dwell=dwell),
            mine_episode(2, ist(2026, 9, 17, 12), branch="ITS_IMPORTANT", outcome="STUDY_PREEMPTION", verified=False),
            mine_episode(3, OLD),
        ])
        m = model(snap, request(("mine",)))
        self.assertEqual(len(records(m, "mine")), 2)
        choices = table(m, "mine", "Choices and documented outcomes")
        got = {(r[0].text, r[1].text): r[2].text for r in choices.rows}
        self.assertEqual(got, {("I will come back", "Returned after callback"): "1", ("It's important", "Study preemption"): "1"})
        cards = next(b for b in chapter(m, "mine").blocks if isinstance(b, M.CardRow)).cards
        self.assertEqual([c.value for c in cards], ["2", "2", "1", "2"])
        self.assertIn("is a decision, not a verified return", texts(m))
        idx = table(m, "mine", "Episode index")
        self.assertEqual({r[0].text: r[5].text for r in idx.rows}, {"MINE-01092026-01": "Yes", "MINE-02092026-01": "No"})
        first = next(r for r in records(m, "mine") if r.title == "MINE-01092026-01")
        self.assertEqual(len(first.extra), 1, "recorded dwell segments are shown when the source has them")
        self.assertEqual(first.extra[0].rows[0][2].text, "620.50 s")

    def test_mine_events_outside_the_range_are_marked_not_dropped(self) -> None:
        start = ist(2026, 9, 19, 23, 58)
        snap = snapshot(mine=[mine_episode(1, start, event_times=[start, plus(start, minutes=1), plus(start, minutes=3), plus(start, minutes=4)])])
        rec = records(model(snap, request(("mine",))), "mine")[0]
        self.assertEqual(len(rec.table.rows), 4)
        self.assertEqual(sum(1 for r in rec.table.rows if "outside selected period" in r[1].sub), 2)

    def test_study_mode_uses_the_block_start_and_never_replaces_it(self) -> None:
        rows = study_block(1, D17) + study_block(2, OLD) + study_block(3, ist(2026, 9, 16, 23, 50), late=ist(2026, 9, 17, 1, 0))
        rows += [study_row(500, 5, "block0004", "PREPARE", "READY", D17)]  # prepared, never started
        rows += [study_row(501, 6, "", "SAFE_SHUTDOWN", "SHUTDOWN", D17)]  # shutdown marker with no block
        m = model(req=request(("study-mode",)), study=tuple(rows))
        self.assertEqual(m.included["study-mode"], ("block0001",))
        rec = records(m, "study-mode")[0]
        self.assertEqual([r[2].sub for r in rec.table.rows], ["PREPARE", "START", "COMPLETE"])
        facts = dict(rec.facts)
        self.assertEqual((facts["Subject"], facts["Task"], facts["Planned"]), ("Neuroscience", "Reading", "45 min (2,700 s)"))
        blob = texts(m)
        self.assertIn("Recorded unit: the study block", blob)
        for absent in ("block0003", "block0004"):
            self.assertNotIn(absent, blob)
        for invented in ("productivity", "focus score", "attention", "quality"):
            self.assertNotIn(invented, blob.lower())

    def test_study_block_snapshots_outside_the_dates_are_marked(self) -> None:
        start = ist(2026, 9, 19, 23, 40)
        rows = study_block(1, start, late=plus(start, minutes=45))  # completes on 20 Sep
        rec = records(model(req=request(("study-mode",)), study=tuple(rows)), "study-mode")[0]
        self.assertIn("outside selected period", rec.table.rows[2][1].sub)
        self.assertIn("1 snapshot(s)", rec.caption)

    def test_no_lifetime_count_or_total_leaks_into_the_report(self) -> None:
        blob = texts(model())
        for trap in LIFETIME_TRAPS:
            self.assertNotIn(trap, blob)
        for word in ("Native outcome counts", "Worst return latency", "Lifetime", "All supplied MIRL evidence"):
            self.assertNotIn(word, blob)

    def test_cover_and_overview_statistics_describe_only_the_selected_records(self) -> None:
        m = model()
        cards = next(b for b in m.sections[0].blocks if isinstance(b, M.CardRow)).cards
        self.assertEqual({c.label: c.value for c in cards}, {"MIRL": "2", "COSINE": "1", "MINE": "1", "STUDY MODE": "1"})
        self.assertEqual(m.period_text, "17 Sep 2026 \u2013 19 Sep 2026")


# --------------------------------------------------------------------------
# Empty periods, unavailable evidence
# --------------------------------------------------------------------------


class StateTests(unittest.TestCase):
    EMPTY = request(start=date(2026, 1, 1), end=date(2026, 1, 2))

    def test_zero_qualifying_records_say_no_episode_recorded_for_every_organ(self) -> None:
        m = model(req=self.EMPTY)
        for key in ALL:
            blocks = chapter(m, key).blocks
            empties = [b for b in blocks if isinstance(b, M.EmptyState)]
            self.assertEqual([e.title for e in empties], ["No episode recorded"], key)
            self.assertEqual(m.states[key], "NO_DATA")
            self.assertEqual(m.included[key], ())
            self.assertFalse(any(isinstance(b, (M.Record, M.CardRow)) for b in blocks), f"{key} must not show fallback records or statistics")
        self.assertFalse(any(s.key == "integrity" for s in m.sections))

    def test_empty_period_never_falls_back_to_older_episodes(self) -> None:
        blob = texts(model(req=self.EMPTY))
        for old in ("EPI-01092026-01", "cosine-0001", "mine-0001", "block0001", "mirl-episode-"):
            self.assertNotIn(old, blob)

    def test_overview_of_an_empty_period_is_truthful(self) -> None:
        m = model(req=self.EMPTY)
        cards = next(b for b in m.sections[0].blocks if isinstance(b, M.CardRow)).cards
        self.assertTrue(all(c.value == "0" and c.caption == "No episode recorded" for c in cards))

    def test_unavailable_organs_are_not_reported_as_zero(self) -> None:
        snap = snapshot(
            mirl_projection=None,
            cosine_projection=SimpleNamespace(available=False, status="READ_ERROR", read_error="OperationalError", status_message="COSINE event source could not be read.", episodes=(), structural_issues=()),
            mine_projection=SimpleNamespace(available=False, status="STRUCTURAL_ERROR", read_error=None, status_message="MINE structure invalid.", episodes=(), structural_issues=()),
        )
        m = model(snap, study=None)
        for key in ALL:
            self.assertEqual(m.states[key], "UNAVAILABLE", key)
            titles = [b.title for b in chapter(m, key).blocks if isinstance(b, M.EmptyState)]
            self.assertEqual(titles, ["Evidence unavailable"], key)
        cards = next(b for b in m.sections[0].blocks if isinstance(b, M.CardRow)).cards
        self.assertEqual({c.value for c in cards}, {"Unavailable"})
        self.assertNotIn("No episode recorded", texts(M.build_report(snap, request(("live-mirl",)), generated_at=NOW, tz=IST)))

    def test_reader_that_works_with_no_records_at_all_is_no_data_not_unavailable(self) -> None:
        m = model(snapshot(), study=())
        for key in ALL:
            self.assertEqual(m.states[key], "NO_DATA", key)

    def test_study_reader_failure_is_unavailable_and_hides_the_error_text(self) -> None:
        m = model(req=request(("study-mode",)), study=None, )
        self.assertEqual(m.states["study-mode"], "UNAVAILABLE")
        m2 = M.build_report(standard_snapshot(), request(("study-mode",)), generated_at=NOW, tz=IST, study_records=None, study_error="OperationalError")
        self.assertNotIn("OperationalError", texts(m2))

    def test_unreadable_start_times_are_disclosed_and_never_silently_included(self) -> None:
        snap = snapshot(cosine=[cosine_episode(1, "garbage-time", event_times=[D17, plus(D17, seconds=5)]), cosine_episode(2, D17)])
        m = model(snap, request(("cosine",)))
        self.assertEqual(m.included["cosine"], ("cosine-0002#1",))
        self.assertIn("1 COSINE episode(s) have no readable recorded start time", texts(m))

    def test_mirl_projection_cap_is_disclosed(self) -> None:
        eps = [mirl_episode(i, ist(2026, 8, 1, 10) if i > 1 else D17) for i in range(1, 102)]
        m = model(snapshot(mirl=eps), request(("live-mirl",)))
        self.assertIn("keeps at most 100 closed episodes", texts(m))


# --------------------------------------------------------------------------
# Evidence Integrity association
# --------------------------------------------------------------------------


class IntegrityTests(unittest.TestCase):
    def test_only_findings_for_selected_episodes_are_included(self) -> None:
        m = model()
        keys = [s.key for s in m.sections]
        self.assertIn("integrity", keys)
        appendix = chapter(m, "appendix-findings-1")
        rows = [r for b in appendix.blocks if isinstance(b, M.Table) for r in b.rows]
        self.assertEqual([r[2].text for r in rows], ["mirl-event-in-range"])
        blob = texts(m)
        self.assertNotIn("mirl-event-OLD", blob)
        self.assertNotIn("mirl-event-GLOBAL", blob)
        self.assertNotIn("CONTROL_EVENT_SCHEMA_MISMATCH", blob, "global findings are not classified as belonging to the period")
        self.assertIn("global findings", blob)

    def test_original_codes_and_identities_are_preserved(self) -> None:
        m = model()
        rows = [r for b in chapter(m, "appendix-findings-1").blocks if isinstance(b, M.Table) for r in b.rows]
        self.assertEqual(rows[0][1].sub, f"mirl-episode-{2:032x}")
        summary = table(m, "integrity", "Findings by code and severity")
        self.assertEqual((summary.rows[0][0].text, summary.rows[0][1].text, summary.rows[0][2].text), ("ERROR", "INVALID_WALL_TIMESTAMP", "1"))

    def test_exclusions_are_limited_to_selected_episodes(self) -> None:
        ex = [SimpleNamespace(metric="native_episode_metrics", reason="episode_integrity_degraded", detail="A; A; B", episode_id=f"mirl-episode-{2:032x}"),
              SimpleNamespace(metric="native_episode_metrics", reason="episode_integrity_degraded", detail="A", episode_id=f"mirl-episode-{3:032x}")]
        m = model(standard_snapshot(exclusions=ex))
        rows = next(b for b in chapter(m, "appendix-exclusions-1").blocks if isinstance(b, M.Table)).rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3].text, "A \u00d72; B \u00d71")

    def test_no_integrity_chapter_when_selected_episodes_have_no_findings(self) -> None:
        snap = snapshot(mirl=[mirl_episode(1, D17)], issues=[issue(episode=f"mirl-episode-{9:032x}", event="elsewhere")])
        m = model(snap, request(("live-mirl",)))
        self.assertFalse(any(s.key == "integrity" or s.appendix for s in m.sections))

    def test_integrity_is_not_added_without_mirl(self) -> None:
        m = model(req=request(("cosine", "mine")))
        self.assertFalse(any(s.key == "integrity" or s.appendix for s in m.sections))


# --------------------------------------------------------------------------
# PDF output
# --------------------------------------------------------------------------


@unittest.skipIf(pymupdf is None, "PyMuPDF is required for PDF inspection")
class PdfTests(_Tmp):
    def test_a4_pages_cover_page_numbers_and_outline(self) -> None:
        path, result = self.build()
        doc = self.open(path)
        self.assertEqual(len(doc), result.pages)
        for page in doc:
            self.assertAlmostEqual(page.rect.width, A4_PT[0], delta=0.5)
            self.assertAlmostEqual(page.rect.height, A4_PT[1], delta=0.5)
        cover = doc[0].get_text()
        for expected in ("MYELIN", "2.0", "Analytics Sheet", "17 Sep 2026 \u2013 19 Sep 2026", "MIRL", "COSINE", "MINE", "STUDY MODE"):
            self.assertIn(expected, cover)
        squeezed = re.sub(r"\s+", "", cover)
        self.assertIn("4selected", squeezed)
        self.assertNotIn("Metric Hub", cover)
        self.assertNotIn("Science Lab", cover)
        for i, page in enumerate(doc, 1):
            self.assertRegex(re.sub(r"\s+", "", page.get_text()), rf"PAGE{i}OF{len(doc)}(?!\d)")
        toc = doc.get_toc()
        self.assertEqual([t[1] for t in toc][:5], ["Report overview", "MIRL", "COSINE", "MINE", "STUDY MODE"])
        pages = [t[2] for t in toc]
        self.assertEqual(pages, sorted(pages))
        self.assertGreater(len(set(pages)), 3)

    def test_cover_lists_only_the_selected_organs_and_count(self) -> None:
        path, _ = self.build(req=request(("mine", "study-mode")))
        cover = self.open(path)[0].get_text()
        self.assertIn("MINE", cover)
        self.assertIn("STUDY MODE", cover)
        self.assertNotIn("COSINE", cover)
        self.assertIn("2selected", re.sub(r"\s+", "", cover))

    def test_unchecked_organs_do_not_appear_anywhere_in_the_pdf(self) -> None:
        path, _ = self.build(req=request(("live-mirl",)))
        text = self.text(path)
        for absent in ("COSINE", "STUDY MODE", "block0001", "cosine-0001"):
            self.assertNotIn(absent, text)
        self.assertIn("EPI-01092026-01", text)

    def test_pdf_contains_selected_records_and_no_older_ones(self) -> None:
        path, _ = self.build()
        text = self.text(path)
        compact = re.sub(r"\s+", "", text)
        for wanted in (f"mirl-episode-{1:032x}", f"mirl-episode-{2:032x}", "cosine-0001", "mine-0001", "block0001", "mirl-event-in-range"):
            self.assertIn(wanted, compact)
        for old in (f"mirl-episode-{3:032x}", "cosine-0002", "mine-0002", "block0002", "mirl-event-OLD", "mirl-event-GLOBAL"):
            self.assertNotIn(old, compact)
        for trap in LIFETIME_TRAPS:
            self.assertNotIn(trap, text)

    def test_empty_period_still_produces_a_valid_report_with_labelled_empty_states(self) -> None:
        path, result = self.build(req=request(start=date(2026, 1, 1), end=date(2026, 1, 2)))
        text = self.text(path)
        self.assertGreaterEqual(text.count("No episode recorded"), 8)  # 4 panels + 4 overview rows/cards
        self.assertIn("01 Jan 2026 \u2013 02 Jan 2026", text)
        self.assertNotIn("EPI-", text)
        self.assertGreaterEqual(result.pages, 6)

    def test_unavailable_organ_pdf_says_unavailable_not_zero(self) -> None:
        path, _ = self.build(snapshot(mirl_projection=None), req=request(("live-mirl",)))
        text = self.text(path)
        self.assertIn("Evidence unavailable", text)
        self.assertNotIn("No episode recorded", text)
        self.assertIn("Unavailable", text)

    def test_no_raw_json_or_python_repr(self) -> None:
        path, _ = self.build()
        text = self.text(path)
        for pattern in (r'\{"', r'"\s*:\s*[\[\{"0-9]', r"\[\{", r"mappingproxy", r"\{'", r"IntegrityStatus\."):
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_text_is_searchable_and_fonts_embedded(self) -> None:
        path, _ = self.build()
        doc = self.open(path)
        for page in doc:
            self.assertGreater(len(page.get_text("words")), 4)
        self.assertTrue({f[4] for p in doc for f in p.get_fonts()})

    def test_unicode_is_kept_and_missing_glyphs_are_disclosed(self) -> None:
        snap = snapshot(cosine=[cosine_episode(1, D17, title="Caf\u00e9 \u2014 Na\u00efve \u00d7 \u0915\u093e\u0932")])
        path, result = self.build(snap, req=request(("cosine",)))
        text = self.text(path)
        self.assertIn("Caf\u00e9 \u2014 Na\u00efve \u00d7", text)
        self.assertTrue(result.substituted)
        self.assertIn("Rendering note", text)

    def test_large_collections_paginate_without_clipping_or_overlap(self) -> None:
        start = ist(2026, 9, 17, 8)
        mirl = [mirl_episode(i, plus(start, minutes=i * 3), rows=30, degraded=(i % 3 == 0), issues=[issue(episode=f"mirl-episode-{i:032x}", event=f"mirl-event-{i:032x}")] if i % 3 == 0 else ()) for i in range(1, 41)]
        issues = [issue(episode=f"mirl-episode-{i:032x}", event=f"mirl-event-{i:032x}") for i in range(3, 41, 3)]
        cosine = [cosine_episode(i, plus(start, minutes=i * 5), events=25) for i in range(1, 15)]
        mine = [mine_episode(i, plus(start, minutes=i * 4)) for i in range(1, 12)]
        study = tuple(sum((study_block(i, plus(start, minutes=i * 6)) for i in range(1, 12)), []))
        path, result = self.build(snapshot(mirl=mirl, cosine=cosine, mine=mine, issues=issues), study=study, name="large.pdf")
        doc = self.open(path)
        self.assertGreater(len(doc), 30)
        for number, page in enumerate(doc, 1):
            words = page.get_text("words")
            for x0, y0, x1, y1, word, *_ in words:
                self.assertGreaterEqual(x0, 30, f"p{number} {word}")
                self.assertLessEqual(x1, page.rect.width - 30, f"p{number} {word}")
                self.assertGreaterEqual(y0, 10)
                self.assertLessEqual(y1, page.rect.height - 8)
            if number % 4:
                continue  # overlap scan on every 4th page keeps the suite fast
            boxes = sorted(words, key=lambda w: w[0])
            for i, a in enumerate(boxes):
                for b in boxes[i + 1:]:
                    if b[0] >= a[2]:
                        break
                    ow = min(a[2], b[2]) - max(a[0], b[0])
                    oh = min(a[3], b[3]) - max(a[1], b[1])
                    self.assertFalse(ow > 0.8 and oh > 1.5, f"p{number} overlap {a[4]!r}/{b[4]!r}")
        toc = doc.get_toc()
        self.assertEqual({t[1] for t in toc if t[0] == 1} >= {"MIRL", "COSINE", "MINE", "STUDY MODE", "Evidence Integrity"}, True)
        self.assertGreater(len({t[2] for t in toc}), 6)

    def test_sample_banner_marks_every_page(self) -> None:
        path, _ = self.build(sample_banner="SAMPLE LAYOUT \u2014 NOT REAL MYELIN DATA")
        for i, page in enumerate(self.open(path), 1):
            self.assertIn("NOT REAL MYELIN DATA", page.get_text(), f"page {i}")


# --------------------------------------------------------------------------
# Composer (real dialog, offscreen) and export lane
# --------------------------------------------------------------------------


class ComposerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PyQt6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        from CONTROL_STATION.analytics import AnalyticsSheetDialog

        self.dialog = AnalyticsSheetDialog()
        self.requests: list = []
        self.dialog.export_requested.connect(self.requests.append)

    def tearDown(self) -> None:
        self.dialog.close()
        self.dialog.deleteLater()
        self.app.processEvents()

    def test_exactly_the_four_organs_in_the_approved_order(self) -> None:
        from CONTROL_STATION.analytics import PAGE_COSINE, PAGE_LIVE_MIRL, PAGE_MINE, PAGE_STUDY_MODE

        self.assertEqual(list(self.dialog.sections), [PAGE_LIVE_MIRL, PAGE_COSINE, PAGE_MINE, PAGE_STUDY_MODE])
        self.assertEqual([c.text() for c in self.dialog.sections.values()], ["MIRL", "COSINE", "MINE", "STUDY MODE"])
        self.assertTrue(all(c.isChecked() for c in self.dialog.sections.values()))
        labels = " ".join(label.text() for label in self.dialog.findChildren(type(self.dialog.message)))
        for gone in ("Metric Hub", "Science Lab"):
            self.assertNotIn(gone, labels)

    def test_composer_mentions_selected_dates_only_and_the_empty_message(self) -> None:
        labels = [label.text() for label in self.dialog.findChildren(type(self.dialog.message))]
        self.assertIn("Four individual organs \u00b7 Selected dates only", labels)
        self.assertIn("Only records belonging to the selected period enter the report.", labels)
        self.assertIn("No episode recorded", labels)
        self.assertIn("FROM \u2192 TO", labels)

    def test_each_checkbox_controls_its_own_request_flag(self) -> None:
        from PyQt6.QtCore import QDate

        self.dialog.start_date.setDate(QDate(2026, 9, 17))
        self.dialog.end_date.setDate(QDate(2026, 9, 19))
        flags = {"live-mirl": "include_mirl", "cosine": "include_cosine", "mine": "include_mine", "study-mode": "include_study_mode"}
        for only, attr in flags.items():
            for key, box in self.dialog.sections.items():
                box.setChecked(key == only)
            self.dialog.export_button.click()
            request_ = self.requests[-1]
            self.assertEqual(request_.selected_sections(), (only,))
            self.assertTrue(getattr(request_, attr))
            self.assertEqual((request_.range_start, request_.range_end), (date(2026, 9, 17), date(2026, 9, 19)))

    def test_multiple_and_all_selections(self) -> None:
        boxes = self.dialog.sections
        boxes["cosine"].setChecked(False)
        self.dialog.export_button.click()
        self.assertEqual(self.requests[-1].selected_sections(), ("live-mirl", "mine", "study-mode"))
        boxes["cosine"].setChecked(True)
        self.dialog.export_button.click()
        self.assertEqual(self.requests[-1].selected_sections(), ("live-mirl", "cosine", "mine", "study-mode"))

    def test_at_least_one_organ_and_valid_dates_are_required(self) -> None:
        from PyQt6.QtCore import QDate

        for box in self.dialog.sections.values():
            box.setChecked(False)
        self.dialog.export_button.click()
        self.assertEqual(self.requests, [])
        self.assertIn("Select at least one organ", self.dialog.message.text())
        for box in self.dialog.sections.values():
            box.setChecked(True)
        self.dialog.start_date.setDate(QDate(2026, 9, 19))
        self.dialog.end_date.setDate(QDate(2026, 9, 17))
        self.dialog.export_button.click()
        self.assertEqual(self.requests, [])
        self.assertIn("From date must not be later than the To date", self.dialog.message.text())

    def test_clicking_a_card_toggles_its_checkbox(self) -> None:
        from PyQt6.QtCore import QPoint, Qt
        from PyQt6.QtTest import QTest

        card = self.dialog.choices["mine"]
        self.dialog.show()
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, pos=QPoint(card.width() - 8, card.height() - 8))
        self.assertFalse(self.dialog.sections["mine"].isChecked())

    def test_export_lane_stamps_the_selected_timezone_on_the_request(self) -> None:
        from CONTROL_STATION.analytics import AnalyticsSheetRequest, _AnalyticsExport

        seen: list = []

        class Access:
            def refusal(self):
                return None

            def begin_export(self, _name):
                return SimpleNamespace(release=lambda: None)

        lane = _AnalyticsExport(Access(), lambda snap, req: seen.append(req) or "out.pdf", timezone_key_provider=lambda: "Asia/Kolkata")
        lane.set_snapshot(object())
        self.assertTrue(lane.begin(AnalyticsSheetRequest(date(2026, 9, 17), date(2026, 9, 19), True, True, True, True)))
        lane._worker.join(5)
        lane.shutdown()
        self.assertEqual(seen[0].presentation_timezone, "Asia/Kolkata")
        self.assertEqual(seen[0].selected_sections(), ("live-mirl", "cosine", "mine", "study-mode"))

    def test_request_is_immutable_and_has_no_metric_hub_or_science_lab_flags(self) -> None:
        from CONTROL_STATION.analytics import AnalyticsSheetRequest

        r = AnalyticsSheetRequest(date(2026, 9, 17), date(2026, 9, 19), True, False, True, False)
        self.assertEqual(r.selected_sections(), ("live-mirl", "mine"))
        self.assertFalse(hasattr(r, "include_metric_hub") or hasattr(r, "include_science_lab"))
        with self.assertRaises(Exception):
            r.include_mirl = False  # type: ignore[misc]

    def test_original_analytics_entry_points_remain(self) -> None:
        root = Path(R.__file__).resolve().parent.parent
        source = (root / "CONTROL_STATION" / "analytics.py").read_text(encoding="utf-8")
        for needle in ('"EXPORT PDF"', "def open_composer(self) -> bool:", "class AnalyticsSheetRequest", "PAGE_METRIC_HUB", "PAGE_SCIENCE_LAB"):
            self.assertIn(needle, source, "the dashboards and the exporter entry point must be preserved")


class ExportTests(_Tmp):
    def _home(self):
        return patch.object(Path, "home", return_value=self.tmp)

    def _hub(self, ids):
        return SimpleNamespace(session_rows=tuple(SimpleNamespace(session_id=i) for i in ids))

    def _export(self, snap=None, req=None):
        from PERSISTENCE.storage import export_analytics_sheet

        return export_analytics_sheet(snapshot=snap or standard_snapshot(), request=req or request())

    def test_export_reads_study_mode_through_the_existing_per_session_reader(self) -> None:
        snap = standard_snapshot()
        snap.lifetime_metric_hub = self._hub([1, 2, 9])
        rows = {1: study_block(1, D17), 2: study_block(2, OLD), 9: []}
        calls: list = []

        def reader(session_id):
            calls.append(session_id)
            return tuple(rows[session_id])

        with self._home(), patch("PERSISTENCE.storage.read_science_lab_study_records", reader):
            path = Path(self._export(snap, request(("study-mode",))))
        self.assertEqual(calls, [1, 2, 9])
        if pymupdf is not None:
            text = "".join(p.get_text() for p in self.open(path))
            self.assertIn("block0001", re.sub(r"\s+", "", text))
            self.assertNotIn("block0002", re.sub(r"\s+", "", text))

    def test_study_read_failure_gives_an_unavailable_chapter_not_a_failed_export(self) -> None:
        snap = standard_snapshot()
        snap.lifetime_metric_hub = self._hub([1])

        def boom(_sid):
            raise sqlite3.OperationalError("secret path C:/x.db")

        with self._home(), patch("PERSISTENCE.storage.read_science_lab_study_records", boom):
            path = Path(self._export(snap, request(("study-mode",))))
        if pymupdf is not None:
            text = "".join(p.get_text() for p in self.open(path))
            self.assertIn("Evidence unavailable", text)
            self.assertNotIn("secret", text)
            self.assertNotIn("OperationalError", text)

    def test_missing_session_list_makes_study_mode_unavailable(self) -> None:
        with self._home():
            path = Path(self._export(standard_snapshot(), request(("study-mode",))))
        if pymupdf is not None:
            self.assertIn("Evidence unavailable", "".join(p.get_text() for p in self.open(path)))

    def test_export_without_study_mode_does_not_read_study_evidence(self) -> None:
        with self._home(), patch("PERSISTENCE.storage.read_science_lab_study_records", side_effect=AssertionError("must not read")):
            self.assertTrue(Path(self._export(standard_snapshot(), request(("live-mirl", "cosine", "mine")))).is_file())

    def test_export_writes_one_verified_pdf_with_no_temporary_file(self) -> None:
        snap = standard_snapshot()
        snap.lifetime_metric_hub = self._hub([])
        with self._home():
            path = Path(self._export(snap))
        self.assertRegex(path.name, r"^MYELIN_Analytics_\d{8}-\d{6}\.pdf$")
        self.assertTrue(path.read_bytes().startswith(b"%PDF"))
        self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])

    def test_failures_leave_no_file_and_never_overwrite(self) -> None:
        with self._home(), patch.object(R, "render_model", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self._export(standard_snapshot(), request(("live-mirl",)))
        downloads = self.tmp / "Downloads"
        self.assertEqual(list(downloads.iterdir()) if downloads.exists() else [], [])

        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 9, 19, 12, 0, 0)

        downloads.mkdir(exist_ok=True)
        existing = downloads / "MYELIN_Analytics_20260919-120000.pdf"
        existing.write_bytes(b"ORIGINAL")
        with self._home(), patch("PERSISTENCE.storage.datetime", Frozen):
            with self.assertRaises(FileExistsError):
                self._export(standard_snapshot(), request(("live-mirl",)))
        self.assertEqual(existing.read_bytes(), b"ORIGINAL")
        self.assertEqual([p.name for p in downloads.iterdir()], [existing.name])

    def test_invalid_period_fails_before_any_file_is_written(self) -> None:
        with self._home():
            with self.assertRaises(ValueError):
                self._export(standard_snapshot(), request(start=date(2026, 9, 19), end=date(2026, 9, 17)))
        downloads = self.tmp / "Downloads"
        self.assertEqual(list(downloads.iterdir()) if downloads.exists() else [], [])

    def test_missing_logo_and_truncated_pdf_fail_explicitly(self) -> None:
        with self.assertRaises(R.ReportAssetError):
            R.build_analytics_sheet_pdf(snapshot=standard_snapshot(), request=request(), output_path=self.tmp / "x.pdf", logo_path=self.tmp / "missing.png")
        bad = self.tmp / "bad.pdf"
        bad.write_bytes(b"%PDF-1.4\n/Type /Page\n")
        with self.assertRaises(R.ReportVerificationError):
            R.verify_pdf(bad, 1)

    def test_build_and_export_never_touch_a_database(self) -> None:
        snap = standard_snapshot()
        snap.lifetime_metric_hub = self._hub([])
        with self._home(), patch.object(sqlite3, "connect", side_effect=AssertionError("database access")):
            self.assertTrue(Path(self._export(snap, request(("live-mirl", "cosine", "mine", "study-mode")))).is_file())

    def test_presentation_package_only_imports_pure_libraries(self) -> None:
        root = Path(R.__file__).parent
        allowed = {"__future__", "io", "json", "math", "os", "re", "dataclasses", "datetime", "pathlib", "typing", "collections", "enum", "xml", "zoneinfo", "reportlab", "PIL", "time_projection"}
        for source in root.glob("*.py"):
            if source.name.startswith("test_"):
                continue
            for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:
                        continue
                    names = [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    self.assertIn(name, allowed, f"{source.name} imports {name}")

    def test_fixtures_match_the_real_projection_fields(self) -> None:
        import dataclasses

        from COSINE import read_model as cosine_rm
        from MINE import read_model as mine_rm
        from MIRL import read_model as mirl_rm

        def fields(cls):
            return {f.name for f in dataclasses.fields(cls)}

        expected = {
            mirl_rm.LiveMirlProjection: {"available", "metadata", "active_episodes", "recently_closed_episodes", "empty_state_reason", "integrity_issues"},
            mirl_rm.ProjectionMetadata: {"start_time", "end_time", "selected_range_label", "exclusions", "exclusion_count", "research_provenance"},
            mirl_rm.ResearchProvenance: {"limitation"},
            mirl_rm.LiveMirlEpisodeRow: {"episode_id", "short_display_id", "session_id", "candidate_uid", "started_at", "episode_status", "final_outcome", "return_intent_latency_seconds", "verified_return_latency_seconds", "stable_recovery_latency_seconds", "recovery_attempt_count", "relapse_count", "sine_stages_exposed", "sine_responses", "timeline", "integrity_status", "integrity_issues", "application", "trigger_fired_at"},
            mirl_rm.LiveMirlTimelineRow: {"episode_seq", "occurred_at", "event_name", "observed_or_derived", "reason_or_outcome_code", "reference", "integrity_status"},
            mirl_rm.IntegrityIssue: {"code", "severity", "detail", "episode_id", "event_id"},
            mirl_rm.MetricExclusion: {"metric", "reason", "detail", "episode_id"},
            cosine_rm.CosineAnalysisProjection: {"available", "overview", "episodes", "status", "status_message", "read_error", "structural_issues"},
            cosine_rm.CosineEpisodeProjection: {"cosine_session_id", "generation", "parent_session_id", "started_at_utc", "ended_at_utc", "starting_platform_label", "event_count", "user_choice", "chosen_break_minutes", "hopper_count", "closure_reason", "closure_outcome", "is_closed", "events", "hold_context"},
            cosine_rm.CosineEventProjection: {"event_id", "sequence", "event_name", "event_class", "occurred_at_utc", "platform_label", "content_title", "payload_display", "withheld_payload_field_count"},
            mine_rm.MineProjection: {"available", "episodes", "status", "status_message", "read_error", "structural_issues"},
            mine_rm.MineEpisodeProjection: {"session_id", "generation", "mine_episode_id", "display_episode_id", "started_at_utc", "ended_at_utc", "starting_platform_label", "branch", "important_duration_minutes", "closure_outcome", "closure_reason", "is_closed", "return_verified", "closure_confirmed", "event_count", "events", "messenger_hops", "dwell_records"},
            mine_rm.MineDisplayEvent: {"sequence", "event_name", "event_class", "occurred_at_utc", "platform_label", "payload_facts", "withheld_payload_field_count", "elapsed_from_previous_seconds"},
            mine_rm.MineDwellRecord: {"segment_order", "platform_label", "dwell_seconds", "mbi_band", "completed_at_utc"},
        }
        for cls, names in expected.items():
            self.assertLessEqual(names, fields(cls), f"{cls.__name__} lost {names - fields(cls)}")

    def test_study_records_have_the_fields_the_report_reads(self) -> None:
        import dataclasses

        from PERSISTENCE.storage import ScienceLabSourceRecord

        names = {f.name for f in dataclasses.fields(ScienceLabSourceRecord)}
        self.assertLessEqual({"source_event_id", "session_id", "kind", "payload_json", "created_at_utc"}, names)


# --------------------------------------------------------------------------
# Three-defect presentation patch: stranded heading, MINE "Events", COSINE UTC
# --------------------------------------------------------------------------


def stored_utc(iso: str, micro: int = 621028) -> str:
    """A timestamp as the databases really store it: 6-digit fraction and a ``+00:00`` offset (32 characters)."""

    return datetime.fromisoformat(iso.replace("Z", "+00:00")).replace(microsecond=micro).isoformat()


class PresentationPatchTests(_Tmp):
    START = ist(2026, 9, 17, 8)
    ONE_DAY = dict(start=date(2026, 9, 17), end=date(2026, 9, 17), tz_key="Asia/Kolkata")

    def organ_case(self, key: str, count: int, *, rows: int = 4):
        start = self.START
        if key == "live-mirl":
            return snapshot(mirl=[mirl_episode(i, plus(start, minutes=i * 3), rows=rows) for i in range(1, count + 1)]), "default"
        if key == "cosine":
            return snapshot(cosine=[cosine_episode(i, stored_utc(plus(start, minutes=i * 5)), events=rows) for i in range(1, count + 1)]), "default"
        if key == "mine":
            return snapshot(mine=[mine_episode(i, stored_utc(plus(start, minutes=i * 4))) for i in range(1, count + 1)]), "default"
        return snapshot(), tuple(sum((study_block(i, plus(start, minutes=i * 6)) for i in range(1, count + 1)), []))

    def stranded_headings(self, path, heading: str, first_title: str) -> list[int]:
        """Pages on which ``heading`` is not followed, on the same page, by the first record's title."""

        bad = []
        for number, page in enumerate(self.open(path), 1):
            for h in page.search_for(heading):
                if not [r for r in page.search_for(first_title) if r.y0 > h.y0]:
                    bad.append(number)
        return bad

    # -- Defect A: the record heading travels with its first record -------------------

    def test_record_heading_is_never_stranded_from_its_first_record_in_any_organ(self) -> None:
        sizes = {"live-mirl": (1, 3, 5, 7), "cosine": (1, 3, 5, 7, 9, 11), "mine": (1, 3, 5, 7, 9, 11), "study-mode": (1, 3, 5, 7)}
        seen_headings = builds = 0
        for key, counts in sizes.items():
            for count in counts:
                snap, study = self.organ_case(key, count)
                path, _ = self.build(snap, request(sections=(key,), **self.ONE_DAY), study=study, name=f"{key}-{count}.pdf")
                m = model(snap, request(sections=(key,), **self.ONE_DAY), study=study)
                blocks = chapter(m, key).blocks
                heading = next(b for b in blocks if isinstance(b, M.Heading))
                first_title = records(m, key)[0].title.split(" · ")[0]
                builds += 1
                seen_headings += sum(1 for page in self.open(path) if page.search_for(heading.text))
                self.assertEqual(self.stranded_headings(path, heading.text, first_title), [], f"{key} with {count} episodes strands its heading")
        self.assertEqual(seen_headings, builds, "every build shows its heading exactly once, so the sweep exercises it")

    def test_heading_stays_with_a_long_record_that_flows_across_pages(self) -> None:
        for count in (1, 2, 4, 6):
            snap, study = self.organ_case("mine", count)
            snap.mine.episodes = tuple(mine_episode(i, stored_utc(plus(self.START, minutes=i * 4)), event_times=[plus(self.START, minutes=i * 4, seconds=s * 10) for s in range(30)]) for i in range(1, count + 1))
            path, _ = self.build(snap, request(sections=("mine",), **self.ONE_DAY), name=f"long-{count}.pdf")
            self.assertEqual(self.stranded_headings(path, "Episode records", "MINE-01092026-01"), [], f"{count} long MINE records")

    def test_only_the_first_record_is_bound_to_the_heading_and_records_still_flow(self) -> None:
        snap, study = self.organ_case("cosine", 12, rows=3)
        path, result = self.build(snap, request(sections=("cosine",), **self.ONE_DAY), name="flow.pdf")
        doc = self.open(path)
        self.assertGreater(len(doc), 4, "records must continue across pages normally")
        titles_per_page = [sum(1 for i in range(1, 13) if page.search_for(f"Episode {i} ")) for page in doc]
        self.assertGreaterEqual(max(titles_per_page), 2, "later records are not forced onto their own pages")
        self.assertEqual(self.stranded_headings(path, "Episode records", "Episode 1"), [])

    def test_a_chapter_without_episodes_keeps_its_empty_state_and_has_no_heading(self) -> None:
        path, _ = self.build(snapshot(), request(start=date(2026, 1, 1), end=date(2026, 1, 2)), name="empty.pdf")
        text = self.text(path)
        self.assertEqual(text.count("No episode recorded") >= 4, True)
        self.assertNotIn("Episode records", text)
        self.assertNotIn("Study block records", text)

    def test_heading_flowables_are_measured_not_a_blanket_constant(self) -> None:
        """A leading heading is bound to the record (measured), not to the old blanket 230 pt spacer."""

        builder = R._Builder()
        story = builder.story(model(snapshot(cosine=[cosine_episode(1, stored_utc(self.START))]), request(sections=("cosine",), **self.ONE_DAY)))
        cond = [f for f in story if isinstance(f, R.CondPageBreak)]
        self.assertNotIn(230, [getattr(f, "height", None) for f in cond])
        bound = [f for f in story if isinstance(f, R.KeepTogether) and any(getattr(c, "text", "") == "Episode records" for c in f._content)]
        self.assertEqual(len(bound), 1, "the heading is inside the same keep-together block as its first record")

    def test_long_record_reserves_the_measured_height_of_its_head_and_first_rows(self) -> None:
        builder = R._Builder()
        m = model(snapshot(mine=[mine_episode(1, stored_utc(self.START), event_times=[plus(self.START, seconds=s * 20) for s in range(30)])]), request(sections=("mine",), **self.ONE_DAY))
        rec = records(m, "mine")[0]
        lead = builder.heading_flowables(next(b for b in chapter(m, "mine").blocks if isinstance(b, M.Heading)))
        plain = builder.record(rec)
        with_lead = builder.record(rec, lead=lead)
        first = lambda flows: next(f for f in flows if isinstance(f, R.CondPageBreak)).height
        self.assertGreaterEqual(first(with_lead), first(plain))
        self.assertGreater(first(with_lead), 160.0, "heading + record head + first table rows are measured, not assumed")
        self.assertLess(first(with_lead), 420.0, "the reservation stays modest (no arbitrary large spacer)")

    # -- Defect B: MINE "Events" -------------------------------------------------------

    def test_mine_events_heading_is_one_word_on_one_line(self) -> None:
        snap, study = self.organ_case("mine", 1)
        path, _ = self.build(snap, request(sections=("mine",), **self.ONE_DAY), name="mine.pdf")
        doc = self.open(path)
        index_page = next(p for p in doc if p.search_for("Episode index"))
        top = index_page.search_for("Episode index")[0].y0
        bottom = index_page.search_for("Episode records")[0].y0
        words = [w[4] for w in index_page.get_text("words") if top < w[1] < bottom]
        self.assertIn("Events", words)
        self.assertNotIn("Event", words, "the header must not be split into 'Event' / 's'")
        self.assertNotIn("s", words, "no stray 's' fragment inside the index table")

    def test_mine_events_column_is_wide_enough_and_the_table_width_is_preserved(self) -> None:
        snap, _ = self.organ_case("mine", 2)
        m = model(snap, request(sections=("mine",), **self.ONE_DAY), study=())
        index = table(m, "mine", "Episode index")
        widths = R._Builder().table(index)[1]._colWidths
        self.assertAlmostEqual(sum(widths), R.CONTENT_W, places=3)
        f = R.font_names()
        needed = R.pdfmetrics.stringWidth("Events", f["bold"], 7.8) + 9.0
        self.assertGreaterEqual(widths[index.columns.index("Events")], needed + 3.0)

    def test_mine_neighbouring_columns_still_hold_their_values(self) -> None:
        snap, _ = self.organ_case("mine", 1)
        path, _ = self.build(snap, request(sections=("mine",), **self.ONE_DAY), name="mine-cols.pdf")
        page = next(p for p in self.open(path) if p.search_for("Episode index"))
        lines = page.get_text().splitlines()
        for expected in ("MINE-01092026-01", "WhatsApp", "I will come back", "Yes"):
            self.assertIn(expected, lines)
        started = stored_utc(plus(self.START, minutes=4))
        self.assertIn(started, lines, "the whole UTC sub-line is on one line")
        self.assertTrue(any(l.startswith("17 Sep 2026 08:04") for l in lines))
        self.assertTrue(any(l.replace(" ", "").startswith("RETURNED_AFTER_CALLBACK") for l in lines))

    # -- Defect C: COSINE UTC sub-line --------------------------------------------------

    def test_cosine_utc_sub_line_is_never_split(self) -> None:
        cases = [
            stored_utc(self.START),                                            # normal, +00:00
            stored_utc(plus(self.START, minutes=59, seconds=59), 999999),      # longest fraction
            datetime(2026, 9, 17, 14, 59, 59, 999999, tzinfo=timezone(timedelta(hours=5, minutes=30))).isoformat(),  # longest with a non-UTC offset
            "2026-09-17T08:00:00Z",                                            # short form
        ]
        snap = snapshot(cosine=[cosine_episode(i, s, events=3) for i, s in enumerate(cases, 1)])
        path, _ = self.build(snap, request(sections=("cosine",), start=date(2026, 9, 17), end=date(2026, 9, 18), tz_key="Asia/Kolkata"), name="utc.pdf")
        page = next(p for p in self.open(path) if p.search_for("Episode index"))
        lines = {l.strip() for l in page.get_text().splitlines()}
        for stamp in cases:
            self.assertIn(stamp, lines, f"UTC sub-line {stamp} was split or dropped")

    def test_cosine_index_columns_fit_their_widest_values(self) -> None:
        snap = snapshot(cosine=[cosine_episode(1, stored_utc(self.START), events=3)])
        m = model(snap, request(sections=("cosine",), **self.ONE_DAY))
        index = table(m, "cosine", "Episode index")
        widths = R._Builder().table(index)[1]._colWidths
        self.assertAlmostEqual(sum(widths), R.CONTENT_W, places=3)
        f = R.font_names()
        utc = R.pdfmetrics.stringWidth(stored_utc(self.START), f["mono"], 6.2)
        self.assertGreaterEqual(widths[index.columns.index("Started")], utc + 9.0 + 3.0, "UTC sub-line fits with margin")
        for i, name in enumerate(index.columns):  # nothing collapsed to make room
            self.assertGreaterEqual(widths[i], R.pdfmetrics.stringWidth(name.split()[-1], f["bold"], 7.8) + 9.0, f"{name} header word fits")

    def test_utc_precision_and_offset_are_preserved_in_the_detailed_record(self) -> None:
        stamp = stored_utc(self.START, 123456)
        snap = snapshot(cosine=[cosine_episode(1, stamp, events=3)])
        m = model(snap, request(sections=("cosine",), **self.ONE_DAY))
        row = table(m, "cosine", "Episode index").rows[0]
        self.assertEqual(row[1].sub, stamp, "the model still carries the complete recorded timestamp")
        first_event = snap.cosine.episodes[0].events[0].occurred_at_utc
        self.assertEqual(records(m, "cosine")[0].table.rows[0][1].sub, first_event, "the detailed record keeps every event's full UTC instant")

    # -- Whole-report checks -------------------------------------------------------------

    def test_patch_keeps_a4_bookmarks_numbers_and_populations(self) -> None:
        path, result = self.build(standard_snapshot(), request(tz_key="Asia/Kolkata"), name="whole.pdf")
        doc = self.open(path)
        for number, page in enumerate(doc, 1):
            self.assertAlmostEqual(page.rect.width, A4_PT[0], delta=0.5)
            self.assertAlmostEqual(page.rect.height, A4_PT[1], delta=0.5)
            self.assertRegex(page.get_text(), rf"P\s*A\s*G\s*E\s+{number}\s+O\s*F\s+{len(doc)}")
        toc = doc.get_toc()
        self.assertEqual([t[1] for t in toc if t[0] == 1][:1], ["Report overview"])
        self.assertEqual({t[1] for t in toc} >= {"MIRL", "COSINE", "MINE", "STUDY MODE"}, True)
        text = re.sub(r"\s+", "", "\n".join(p.get_text() for p in doc))
        for kept in ("EPI-01092026-01", "EPI-02092026-01", "MINE-01092026-01"):
            self.assertIn(kept, text)
        for old in ("EPI-03092026-01", "MINE-02092026-01"):
            self.assertNotIn(old, text)


if __name__ == "__main__":
    unittest.main()
