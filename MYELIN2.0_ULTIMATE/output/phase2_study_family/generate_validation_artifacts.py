"""Generate clearly labelled synthetic Phase-2 visual validation artifacts."""
from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from ANALYTICS_SHEET.render import build_analytics_sheet_pdf
from ANALYTICS_SHEET.test_report import D17, standard_snapshot, study_block
from CONTROL_STATION.analytics import AnalyticsSheetRequest
from GET_CHART.poster import (A3_LANDSCAPE_PX, build_poster_model,
                              load_official_logo, render_poster_image, write_poster_pdf)
from GET_CHART.read_model import (CosecantBreakProjection, CosecantChartProjection,
                                  CosecantMilestoneProjection, secant_chart_from_family)
from GET_CHART.test_poster import FIXED_TZ, _metric, make_data, make_lifetime
from GET_CHART.study_family_evidence import StudyFamilyEvidence


ROOT = Path(__file__).resolve().parent
LABEL = "SYNTHETIC VALIDATION FIXTURE - NOT REAL MYELIN DATA"
UTC = timezone.utc


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


START = datetime.fromisoformat(D17.replace("Z", "+00:00"))


def secant_episode(index: int, stage: int, *, recovered=False, closed=True, verified=False, interrupted=False):
    start = START + timedelta(minutes=12 * index)
    base = 1_000_000_000 * (index + 1)
    events = []
    def add(name, sec, level=0, reason=""):
        events.append(dict(event_name=name, occurred_monotonic_ns=base + sec * 1_000_000_000,
                           stage=level, reason=reason))
    add("SECANT_EPISODE_FOUNDED", 0)
    for level in range(1, stage + 1):
        add("SECANT_DISPLAYED", level, level)
    add("SECANT_RETURN_STARTED", 10, stage)
    if verified:
        add("SECANT_RETURN_VERIFIED", 25, stage)
    if interrupted:
        add("SECANT_RECOVERY_INTERRUPTED", 30, stage, "interrupted")
    if recovered:
        add("SECANT_RECOVERY_CLOSED", 75, stage)
    if closed:
        add("SECANT_EPISODE_CLOSED", 75 if recovered else 45, stage,
            "recovered" if recovered else "evidence_gap")
    return dict(session_id=1, context_id=f"1:study-{index}",
                alias=f"SEC-17092026-{index:02d}", start_utc=iso(start), highest_stage=stage,
                closed=closed, terminal_reason="recovered" if recovered else "evidence_gap" if closed else "Open / incomplete",
                recovered=recovered, source_status="AVAILABLE", source_caption="Recorded Study source",
                source_kind="BROWSER", events=tuple(events))


def cosecant_break(index: int, *, confirmed=False):
    start = START + timedelta(hours=index)
    kinds = ("BREAK_STARTED", "BREAK_COMPLETE", "BREAK_ALREADY_OVER", "FINAL_LOCKED",
             "RETURN_INTENT_RECORDED", "RETURN_CONFIRMATION_STARTED")
    if confirmed:
        kinds += ("RETURN_CONFIRMED",)
    events = tuple(dict(kind=kind, payload=dict(occurred_wall_time_utc=iso(start + timedelta(minutes=i * 5)),
                                          evidence_token="recorded-proof" if kind == "RETURN_CONFIRMED" else ""))
                   for i, kind in enumerate(kinds))
    return dict(session_id=1, alias=f"COSEC-17092026-{index:02d}", start_utc=iso(start),
                study_block_id="block0001", allowance=600, target_kind="BROWSER",
                target_caption="Recorded return target", confirmed=confirmed, cancelled=False,
                complete=True, events=events)


def family_fixture() -> StudyFamilyEvidence:
    resource = dict(session_id=1, study_block_id="block0001", study_generation=1,
                    role="PRIMARY", title="Recorded Study source", qualified_at_utc=iso(START))
    visit = dict(session_id=1, study_block_id="block0001", study_generation=1,
                 title="Recorded Study source", supported_duration_ns=300_000_000_000,
                 effective=dict(classification="STUDY_ALIGNED", user_confirmation="STUDY"))
    return StudyFamilyEvidence(
        studies=((1, dict(resources=[resource], visits=[visit], jumps=[])),),
        secant=(secant_episode(1, 1, recovered=True, verified=True),
                secant_episode(2, 2, verified=True),
                secant_episode(3, 3, closed=False, interrupted=True)),
        cosecant=(cosecant_break(1, confirmed=True), cosecant_break(2)),
    )


def poster_cosecant(family: StudyFamilyEvidence) -> CosecantChartProjection:
    breaks = []
    for row in family.cosecant:
        milestones = tuple(CosecantMilestoneProjection(index, event["kind"],
            index * 300_000_000_000, index * 300_000_000_000,
            event["payload"]["occurred_wall_time_utc"], event["payload"].get("evidence_token", ""))
            for index, event in enumerate(row["events"], 1))
        breaks.append(CosecantBreakProjection(row["session_id"], row["alias"],
                                               row["study_block_id"], milestones, row["confirmed"]))
    return CosecantChartProjection("AVAILABLE", tuple(breaks), len(breaks),
                                   sum(row["confirmed"] for row in family.cosecant), "Synthetic validation fixture")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    family = family_fixture()
    request = AnalyticsSheetRequest(date(2026, 9, 17), date(2026, 9, 19),
                                    True, True, True, True, "Asia/Kolkata", True, True)
    build_analytics_sheet_pdf(snapshot=standard_snapshot(), request=request,
        output_path=ROOT / "MYELIN_Phase2_Analytics_Sheet_SYNTHETIC.pdf",
        study_records=tuple(study_block(1, D17)), study_family=family,
        sample_banner=LABEL)

    lifetime = replace(make_lifetime(), sessions=_metric(6))
    data = make_data(lifetime_summary=lifetime, cosecant=poster_cosecant(family),
                     secant=secant_chart_from_family(family),
                     study_blocks_started=1)
    model = build_poster_model(data, tz=FIXED_TZ, sample_banner=LABEL)
    logo = load_official_logo()
    png = ROOT / "MYELIN_Phase2_Poster_1600x850_SYNTHETIC.png"
    poster_pdf = ROOT / "MYELIN_Phase2_Poster_A3_SYNTHETIC.pdf"
    jpg = ROOT / "MYELIN_Phase2_Poster_300DPI_SYNTHETIC.jpg"
    assert render_poster_image(model, logo, 1600, height_px=850).save(str(png), "PNG")
    write_poster_pdf(model, logo, poster_pdf)
    assert render_poster_image(model, logo, A3_LANDSCAPE_PX[0],
                               height_px=A3_LANDSCAPE_PX[1], dpi=300).save(str(jpg), "JPEG", 94)
    print(png)
    print(poster_pdf)
    print(jpg)
    print(ROOT / "MYELIN_Phase2_Analytics_Sheet_SYNTHETIC.pdf")
    del app


if __name__ == "__main__":
    main()
