"""Phase-2 Study-family membership and separate-authority regression checks."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace
from pathlib import Path
import json
import sqlite3
import tempfile

from PyQt6.QtWidgets import QApplication

from ANALYTICS_SHEET.model import CardRow, Note, Record, build_report
from ANALYTICS_SHEET.test_report import snapshot, study_row
from CONTROL_STATION.analytics import AnalyticsSheetDialog, AnalyticsSheetRequest, PAGE_STUDY_MODE
from GET_CHART.poster import build_poster_model
from GET_CHART.read_model import secant_chart_from_family
from GET_CHART.study_family_evidence import StudyFamilyEvidence, _cosecant_breaks, read_study_family
from SECANT.dashboard_evidence import EvidenceSnapshot, EvidenceTable
from GET_CHART.test_poster import FIXED_TZ, _metric, _render_log, make_data, make_lifetime


IST = timezone(timedelta(hours=5, minutes=30))


def stamp(day: int, hour: int, minute: int = 0) -> str:
    return datetime(2026, 9, day, hour, minute, tzinfo=IST).astimezone(timezone.utc).isoformat()


def episode(alias: str, start: str, *, verified=False, recovered=False, closed=True):
    names = ["SECANT_EPISODE_FOUNDED", "SECANT_DISPLAYED", "SECANT_RETURN_STARTED"]
    if verified:
        names.append("SECANT_RETURN_VERIFIED")
    if recovered:
        names.append("SECANT_RECOVERY_CLOSED")
    if closed:
        names.append("SECANT_EPISODE_CLOSED")
    events = tuple(dict(event_name=name, occurred_monotonic_ns=index * 300_000_000_000,
                        stage=1 if index else 0,
                        reason="recovered" if name == "SECANT_EPISODE_CLOSED" and recovered else "evidence_gap" if name == "SECANT_EPISODE_CLOSED" else "")
                   for index, name in enumerate(names))
    return dict(session_id=1, context_id="1:study", alias=alias, start_utc=start,
                highest_stage=1, closed=closed,
                terminal_reason="recovered" if recovered else "evidence_gap" if closed else "Open / incomplete",
                recovered=recovered, source_kind="BROWSER", source_caption="Not recorded", events=events)


def break_record(alias: str, start: str, end: str):
    events = tuple(dict(kind=kind, payload=dict(occurred_wall_time_utc=when,
                                              evidence_token="proof" if kind == "RETURN_CONFIRMED" else ""))
                   for kind, when in (("BREAK_STARTED", start), ("BREAK_COMPLETE", end),
                                      ("RETURN_CONFIRMED", end)))
    return dict(session_id=1, alias=alias, start_utc=start, study_block_id="study-1",
                allowance=600, target_kind="BROWSER", target_caption="Not recorded",
                confirmed=True, cancelled=False, complete=True, events=events)


def request(*, secant=False, cosecant=False):
    return AnalyticsSheetRequest(date(2026, 9, 19), date(2026, 9, 19),
                                 False, False, False, True, "Asia/Kolkata", secant, cosecant)


def chapter(model, key):
    return next(section for section in model.sections if section.key == key)


def test_legacy_study_selection_and_explicit_children():
    default = AnalyticsSheetRequest(date(2026, 9, 19), date(2026, 9, 19),
                                    False, False, False, True)
    assert default.selected_sections() == ("study-mode", "secant", "cosecant")
    # An existing Study-only integration must now request that mode explicitly.
    assert request().selected_sections() == ("study-mode",)
    assert request(secant=True, cosecant=True).selected_sections() == ("study-mode", "secant", "cosecant")
    disabled = replace(request(secant=True, cosecant=True), include_study_mode=False)
    assert disabled.selected_sections() == ()


def test_dialog_study_is_one_selection_with_both_children():
    app = QApplication.instance() or QApplication([])
    dialog = AnalyticsSheetDialog()
    assert len(dialog.sections) == 4
    assert not hasattr(dialog, "secant_choice")
    captured = []
    dialog.export_requested.connect(captured.append)
    for key, choice in dialog.sections.items():
        if key != PAGE_STUDY_MODE:
            choice.setChecked(False)
    dialog.sections[PAGE_STUDY_MODE].setChecked(True)
    dialog._request_export()
    assert captured[-1].selected_sections() == ("study-mode", "secant", "cosecant")
    dialog.close()
    del app


def test_cosecant_session_sequence_can_start_later_break_above_one():
    rows = []
    for number, native in ((1, "first"), (2, "second")):
        payload = dict(break_id=native, sequence=number, kind="BREAK_STARTED",
                       occurred_wall_time_utc=stamp(19, 9 + number))
        rows.append(dict(id=number, session_id=1, break_id=native,
                         sequence=number, kind="BREAK_STARTED",
                         payload_json=json.dumps(payload)))
    tables = MappingProxyType({
        "cosecant_events": EvidenceTable(tuple(rows), "AVAILABLE"),
        "presentation_aliases": EvidenceTable((), "AVAILABLE"),
    })
    breaks = _cosecant_breaks(EvidenceSnapshot(1, tables))
    assert len(breaks) == 2
    assert [item["events"][0]["sequence"] for item in breaks] == [1, 2]


def test_secant_gap_is_disclosed_without_erasing_valid_episodes():
    family = StudyFamilyEvidence(
        secant=(episode("SEC-19092026-02", stamp(19, 10)),),
        secant_excluded=(dict(alias="SEC-19092026-01", start_utc=stamp(19, 9), reason="Recorder gap"),),
    )
    report = build_report(snapshot(), request(secant=True), study_records=(), study_family=family)
    assert report.states["secant"] == "AVAILABLE"
    assert report.included["secant"] == ("SEC-19092026-02",)
    assert any("excluded" in block.text and "recorder" in block.text
               for block in chapter(report, "secant").blocks if isinstance(block, Note))


def test_study_identity_and_unplaceable_are_not_silent():
    rows = (
        study_row(1, 1, "same-block", "START", "ACTIVE", stamp(19, 9), started=stamp(19, 9)),
        study_row(2, 2, "same-block", "START", "ACTIVE", stamp(19, 10), started=stamp(19, 10)),
        study_row(3, 3, "prepared-only", "PREPARE", "READY", stamp(19, 11)),
    )
    report = build_report(snapshot(), request(), study_records=rows)
    study = chapter(report, "study-mode")
    cards = next(block for block in study.blocks if isinstance(block, CardRow))
    assert cards.cards[0].value == "2"
    assert len([block for block in study.blocks if isinstance(block, Record)]) == 2
    assert any("unplaceable" in block.text for block in study.blocks if isinstance(block, Note))


def test_authoritative_start_membership_and_outside_events():
    inside = stamp(19, 23, 58)
    outside = stamp(20, 0, 5)
    older = stamp(18, 23, 58)
    family = StudyFamilyEvidence(
        secant=(episode("SEC-19092026-01", inside, verified=True),
                episode("SEC-18092026-01", older, recovered=True, verified=True)),
        cosecant=(break_record("COSEC-19092026-01", inside, outside),
                  break_record("COSEC-18092026-01", older, inside)),
    )
    report = build_report(snapshot(), request(secant=True, cosecant=True),
                          study_records=(), study_family=family)
    assert report.cover_items == ("STUDY MODE",)
    assert [section.key for section in report.sections if section.key != "overview"] == ["study-mode", "secant", "cosecant"]
    assert report.included["secant"] == ("SEC-19092026-01",)
    assert report.included["cosecant"] == ("COSEC-19092026-01",)
    secant_records = [b for b in chapter(report, "secant").blocks if isinstance(b, Record)]
    assert len(secant_records) == 1
    assert "outside selected period" in secant_records[0].table.rows[-1][1].sub
    assert "outside selected period" in [b for b in chapter(report, "cosecant").blocks if isinstance(b, Record)][0].table.rows[-1][1].sub


def test_verified_event_is_not_recovered_episode_and_states_are_distinct():
    family = StudyFamilyEvidence(secant=(episode("SEC-19092026-01", stamp(19, 9), verified=True),))
    report = build_report(snapshot(), request(secant=True), study_records=(), study_family=family)
    secant = chapter(report, "secant")
    cards = next(block for block in secant.blocks if isinstance(block, CardRow)).cards
    assert {card.label: card.value for card in cards}["Recovered episodes"] == "0"
    assert secant_chart_from_family(family).verified_events == 1
    assert secant_chart_from_family(family).recovered_episodes == 0
    empty = build_report(snapshot(), request(secant=True, cosecant=True), study_records=(),
                         study_family=StudyFamilyEvidence())
    assert empty.states["secant"] == empty.states["cosecant"] == "NO_DATA"
    missing = build_report(snapshot(), request(secant=True), study_records=(), study_family=None)
    assert missing.states["secant"] == "UNAVAILABLE"


def test_missing_alias_and_title_do_not_borrow_native_identity():
    family = StudyFamilyEvidence(secant=(episode("Unavailable", stamp(19, 9)),))
    report = build_report(snapshot(), request(secant=True), study_records=(), study_family=family)
    record = next(block for block in chapter(report, "secant").blocks if isinstance(block, Record))
    assert "Alias unavailable" in record.title
    assert dict(record.facts)["Recorded source caption"] == "Not recorded"


def test_unfinalized_or_mixed_recorder_domains_fail_closed():
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "evidence.sqlite"
        connection = sqlite3.connect(database)
        connection.executescript("""
            CREATE TABLE sessions (id INTEGER PRIMARY KEY, started_at_utc TEXT);
            CREATE TABLE secant_events (session_id INTEGER, recorder_run_id TEXT,
                episode_id TEXT, event_id TEXT, study_context_id TEXT);
            CREATE TABLE myelin_meta (key TEXT PRIMARY KEY, value TEXT);
            INSERT INTO sessions VALUES (1, '2026-09-19T00:00:00Z');
            INSERT INTO secant_events VALUES (1, 'run-a', 'episode-a', 'event-a', '1:study');
        """)
        status = dict(run_id="run-a", attached_session_ids=[1], contract_version=1,
                      coverage="BOUNDED_OBSERVATION", dropped=0, gap_reasons=[],
                      writer_state="ACTIVE", final_flush_committed=False, pending=0,
                      closed_at_utc=None)
        connection.execute("INSERT INTO myelin_meta VALUES (?, ?)",
                           ("passive_recorder:v1:run:run-a", json.dumps(status)))
        connection.commit()
        assert "secant" in read_study_family(database).errors
        status.update(writer_state="CLOSED", final_flush_committed=True,
                      closed_at_utc="2026-09-19T12:00:00Z")
        connection.execute("UPDATE myelin_meta SET value=?", (json.dumps(status),))
        connection.execute("INSERT INTO secant_events VALUES (1, 'run-b', 'episode-a', 'event-b', '1:study')")
        connection.commit()
        assert "secant" in read_study_family(database).errors
        connection.close()


def test_poster_exclusive_stages_sixth_step_and_safe_summary():
    app = QApplication.instance() or QApplication([])
    family = StudyFamilyEvidence(secant=(episode("SEC-19092026-01", stamp(19, 9), verified=True),))
    lifetime = replace(make_lifetime(), sessions=_metric(5))
    data = make_data(lifetime_summary=lifetime, secant=secant_chart_from_family(family),
                     study_blocks_started=2)
    model = build_poster_model(data, tz=FIXED_TZ)
    assert model.secant.stages == (1, 0, 0)
    assert model.system_counts == (5, 2, data.cosecant.break_denominator)
    assert len(model.cosecant.steps) == 6
    _image, log = _render_log(model)
    assert any(item.region == "panel:COSECANT" and item.text == "Return Confirmed" for item in log)
    assert any(item.region == "panel:SECANT" and "VERIFIED EVENTS 1" in item.text for item in log)
    del app
