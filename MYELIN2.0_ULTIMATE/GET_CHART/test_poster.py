"""Offscreen renderer, export and lifecycle tests for the MYELIN Neon Poster.

Fixtures build the real immutable ``PosterChartData`` contract.  Their values
are deliberately synthetic test inputs; nothing here is MYELIN measurement.
"""

from __future__ import annotations

import os
import re
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ["QT_QPA_PLATFORM"] == "offscreen" and Path(r"C:\Windows\Fonts").is_dir():
    # Offscreen Qt has no font database of its own; without this every glyph
    # is a box and text metrics are meaningless.
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PyQt6.QtCore import QObject, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QPushButton

from CONTROL_STATION.get_chart import GetChartController
from GET_CHART import poster as poster_module
from GET_CHART import read_model as rm
from GET_CHART.poster import (
    A3_LANDSCAPE_PX,
    CANVAS_H,
    CANVAS_W,
    NeonPosterWindow,
    build_poster_model,
    inspect_pdf,
    load_official_logo,
    render_poster_image,
    write_poster_pdf,
)
from METRIC_HUB.read_model import (
    AVAILABLE as METRIC_AVAILABLE,
    UNAVAILABLE as METRIC_UNAVAILABLE,
    BehaviourDistributionProjection,
    LifetimeMetricHubProjection,
    MetricValue,
    OrganMetric,
)

UTC = timezone.utc
FIXED_TZ = timezone(timedelta(hours=5, minutes=30))
T0 = datetime(2026, 9, 18, 3, 0, 0, tzinfo=UTC)


def _iso(offset_seconds: float) -> str:
    return (T0 + timedelta(seconds=offset_seconds)).isoformat().replace("+00:00", "Z")


def _metric(value: int | None) -> MetricValue:
    if value is None:
        return MetricValue(METRIC_UNAVAILABLE, None, "No certified evidence.", "test")
    return MetricValue(METRIC_AVAILABLE, value, "test fixture", "test", value)


def make_lifetime(triggers: int | None = 17) -> LifetimeMetricHubProjection:
    organs = tuple(
        OrganMetric(name, _metric(triggers), _metric(None), "trigger note", "return note")
        for name in ("SINE", "COSINE", "MINE", "COSECANT")
    )
    behaviour = BehaviourDistributionProjection(
        METRIC_UNAVAILABLE, None, None, None, None, None, None, None, 0, (),
        "test", "No certified evidence.",
    )
    return LifetimeMetricHubProjection(
        sessions=_metric(None), total_triggers=_metric(None), total_returned=_metric(None),
        sine=organs[0], cosine=organs[1], mine=organs[2], cosecant=organs[3],
        behaviour_distribution=behaviour,
        generated_at_utc="2026-09-18T06:30:00Z", snapshot_id="snapshot-fixture",
        source_path="read-only-test-source", read_only=True,
        status=METRIC_UNAVAILABLE, status_message="No certified evidence.",
    )


def make_sine(stage_counts=(10, 6, 3), returned=4) -> rm.SineChartProjection:
    total = stage_counts[0]
    episodes = []
    for index in range(total):
        reached = 1 + (index < stage_counts[1]) + (index < stage_counts[2])
        episodes.append(
            rm.SineEpisodeProjection(
                1, f"sine-{index}", f"cand-{index}", _iso(index * 60),
                tuple(range(1, reached + 1)), index < returned,
            )
        )
    funnel, denominator = [], total
    for stage in (1, 2, 3):
        ids = tuple(e.episode_id for e in episodes if stage in e.stages_reached)
        funnel.append(rm.SineFunnelStageProjection(stage, ids, len(ids), denominator))
        denominator = len(ids)
    verified = tuple(e.episode_id for e in episodes if e.verified_return)
    return rm.SineChartProjection(
        rm.AVAILABLE, tuple(episodes), tuple(funnel), verified, len(verified), total, "fixture"
    )


def make_mine(spec=None) -> rm.MineChartProjection:
    """spec: list of (choice, closure_outcome | None)."""

    spec = spec or (
        [("I_WILL_COME_BACK", "RETURNED_AFTER_INTENT")] * 5
        + [("I_WILL_COME_BACK", "INCOMPLETE")] * 2
        + [("I_WILL_COME_BACK", None)] * 1
        + [("ITS_IMPORTANT", "RETURNED_AFTER_CALLBACK")] * 3
        + [("ITS_IMPORTANT", "STUDY_PREEMPTION")] * 1
        + [("ITS_IMPORTANT", None)] * 2
    )
    choices = []
    for index, (choice, outcome) in enumerate(spec):
        choices.append(
            rm.MineChoiceOutcomeProjection(
                1, index + 1, f"mine-{index}", f"EPI-{index:02d}", choice, _iso(index * 30),
                outcome, "reason" if outcome else None, _iso(index * 30 + 20) if outcome else None,
                bool(outcome and outcome.startswith("RETURNED")),
            )
        )
    counts = {}
    for row in choices:
        counts[row.choice] = counts.get(row.choice, 0) + 1
    grouped: dict = {}
    for row in choices:
        if row.closure_outcome is not None:
            grouped.setdefault((row.choice, row.closure_outcome), []).append(row.mine_episode_id)
    buckets = tuple(
        rm.MineOutcomeBucketProjection(c, o, tuple(ids), len(ids), counts[c])
        for (c, o), ids in sorted(grouped.items())
    )
    documented = sum(row.closure_outcome is not None for row in choices)
    return rm.MineChartProjection(
        rm.AVAILABLE, tuple(choices), buckets, len(choices), documented, "fixture"
    )


def make_cosine(episode_count=3, events_each=6) -> rm.CosineChartProjection:
    names = (
        "COSINE_SESSION_STARTED", "OTT_PLATFORM_ENTERED", "CONTENT_OBSERVED",
        "INTENT_GATE_DISPLAYED", "BREAK_STARTED", "RETURN_CONFIRMED", "COSINE_SESSION_CLOSED",
    )
    episodes = []
    for index in range(episode_count):
        base = index * 86400.0
        events = tuple(
            rm.CosineRecordedEventProjection(
                f"ev-{index}-{n}", n + 1, names[n % len(names)], _iso(base + n * 240 + (n * n) * 7)
            )
            for n in range(events_each)
        )
        episodes.append(
            rm.CosineEpisodeTimelineProjection(
                f"cosine-{index}", 1, 1, _iso(base), _iso(base + events_each * 240), events
            )
        )
    return rm.CosineChartProjection(
        rm.AVAILABLE, tuple(episodes), len(episodes), episode_count * events_each, "fixture"
    )


def _milestone(seq, kind, effective, observed, wall_offset):
    return rm.CosecantMilestoneProjection(seq, kind, effective, observed, _iso(wall_offset), "")


def make_cosecant() -> rm.CosecantChartProjection:
    sec = 1_000_000_000
    breaks = []
    plans = (
        ("a", True, 600, 615),
        ("b", True, 300, 400),
        ("c", False, 300, None),
        ("d", False, None, None),
    )
    for index, (name, confirmed, complete_s, confirm_s) in enumerate(plans):
        base = 1_000 * sec * (index + 1)
        wall = index * 4000
        ms = [_milestone(1, "BREAK_STARTED", base, base, wall)]
        seq = 2
        if complete_s is not None:
            ms.append(_milestone(seq, "BREAK_COMPLETE", base + complete_s * sec, base + complete_s * sec + sec, wall + complete_s))
            seq += 1
            ms.append(_milestone(seq, "FINAL_LOCKED", base + (complete_s + 60) * sec, base + (complete_s + 61) * sec, wall + complete_s + 60))
            seq += 1
        if confirmed:
            ms.append(_milestone(seq, "RETURN_INTENT_RECORDED", base + (confirm_s - 30) * sec, base + (confirm_s - 30) * sec, wall + confirm_s - 30))
            seq += 1
            ms.append(_milestone(seq, "RETURN_CONFIRMED", base + confirm_s * sec, base + confirm_s * sec, wall + confirm_s))
        breaks.append(rm.CosecantBreakProjection(1, f"break-{name}", f"study-{name}", tuple(ms), confirmed))
    return rm.CosecantChartProjection(
        rm.AVAILABLE, tuple(breaks), len(breaks), sum(b.return_confirmed for b in breaks), "fixture"
    )


def make_data(**overrides) -> rm.PosterChartData:
    fields = dict(
        lifetime_summary=make_lifetime(),
        sine=make_sine(),
        mine=make_mine(),
        cosine=make_cosine(),
        cosecant=make_cosecant(),
        generated_at_utc="2026-09-18T06:30:00Z",
    )
    fields.update(overrides)
    return rm.PosterChartData(**fields)


# --------------------------------------------------------------------------
# Test doubles
# --------------------------------------------------------------------------


class _Engine(QObject):
    engine_status_changed = pyqtSignal(object)
    engine_stopped = pyqtSignal()
    engine_failed = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.active = False

    def is_session_active(self) -> bool:
        return self.active

    def publish(self, status: str, *, active: bool) -> None:
        self.active = active
        self.engine_status_changed.emit(status)


class _Lifecycle:
    def request_stop(self):
        return object()


class _Analytics:
    def __init__(self) -> None:
        self.open_calls = 0

    def open_composer(self) -> bool:
        self.open_calls += 1
        return True


def _texts(placements, *, region_prefix=None):
    return [
        item.text
        for item in placements
        if region_prefix is None or item.region.startswith(region_prefix)
    ]


def _render_log(model, width=1680):
    log: list = []
    image = render_poster_image(model, load_official_logo(), width, log=log)
    return image, log


def _dominant(color: QColor) -> str:
    r, g, b = color.red(), color.green(), color.blue()
    if g > r and g > b:
        return "green"
    if r > 180 and g > 60 and b < 90 and r > g > b:
        return "orange"
    if r > b > g:
        return "pink"
    if b > r > g:
        return "violet"
    return "other"


# --------------------------------------------------------------------------
# Presentation model: data integrity
# --------------------------------------------------------------------------


class PosterModelTests(unittest.TestCase):
    def test_sine_uses_projection_counts_and_keeps_returns_separate(self) -> None:
        model = build_poster_model(make_data(), tz=FIXED_TZ).sine
        self.assertEqual(
            [(s.label, s.count, s.denominator) for s in model.stages],
            [("SINE-1", 10, 10), ("SINE-2", 6, 10), ("SINE-3", 3, 6)],
        )
        self.assertEqual(len(model.stages), 3, "return must never be a fourth stage")
        self.assertFalse(any("4" in stage.label for stage in model.stages))
        self.assertEqual(model.returned, 4)
        self.assertEqual(sum(piece.count for piece in model.slices), model.total)
        self.assertEqual(model.total, 10)

    def test_mine_branch_outcomes_are_not_invented_or_merged(self) -> None:
        model = build_poster_model(make_data(), tz=FIXED_TZ).mine
        by_key = {c.key: c for c in model.choices}
        will = by_key["I_WILL_COME_BACK"]
        important = by_key["ITS_IMPORTANT"]
        self.assertEqual((will.count, important.count), (8, 6))
        self.assertEqual(
            {(o.label, o.count, o.denominator) for o in will.outcomes},
            {
                ("Returned after intent", 5, 8),
                ("Incomplete", 2, 8),
                ("No documented outcome", 1, 8),
            },
        )
        self.assertEqual(
            {(o.label, o.count, o.denominator) for o in important.outcomes},
            {
                ("Returned after callback", 3, 6),
                ("Study preemption", 1, 6),
                ("No documented outcome", 2, 6),
            },
        )
        for choice in model.choices:
            self.assertEqual(sum(o.count for o in choice.outcomes), choice.count)
        self.assertEqual(sum(piece.count for piece in model.slices), model.total)
        labels = " ".join(
            [o.label for c in model.choices for o in c.outcomes]
            + [piece.label for piece in model.slices]
        ).lower()
        self.assertNotIn("final mine-2", labels)
        self.assertNotIn("fail", labels)
        self.assertNotIn("missed", labels)

    def test_mine_branches_may_have_different_outcomes(self) -> None:
        spec = [("I_WILL_COME_BACK", "INCOMPLETE")] * 2 + [
            ("ITS_IMPORTANT", "RETURNED_AFTER_CALLBACK")
        ] * 3
        model = build_poster_model(make_data(mine=make_mine(spec)), tz=FIXED_TZ).mine
        will, important = model.choices
        self.assertEqual([o.label for o in will.outcomes], ["Incomplete"])
        self.assertEqual([o.label for o in important.outcomes], ["Returned after callback"])

    def test_mine_branch_with_no_choices_shows_zero_without_outcomes(self) -> None:
        spec = [("I_WILL_COME_BACK", "INCOMPLETE")] * 2
        model = build_poster_model(make_data(mine=make_mine(spec)), tz=FIXED_TZ).mine
        self.assertEqual((model.choices[1].count, model.choices[1].outcomes), (0, ()))
        self.assertEqual(model.choices[1].share_text, "0.0%")

    def test_cosine_positions_are_recorded_timestamp_offsets_only(self) -> None:
        model = build_poster_model(make_data(), tz=FIXED_TZ).cosine
        self.assertEqual(model.total_episodes, 3)
        self.assertEqual(model.total_events, 18)
        self.assertEqual(len(model.rows), 3)
        expected = tuple(float(n * 240 + n * n * 7) for n in range(6))
        self.assertEqual(model.rows[0].offsets_seconds, expected)
        self.assertEqual(model.tz_label, "UTC+05:30")
        self.assertEqual(model.rows[0].span_label, "08:30\u201308:52")
        self.assertEqual(sum(piece.count for piece in model.slices), 18)
        self.assertFalse(hasattr(model, "duration_seconds"))

    def test_cosine_selects_latest_episodes_and_says_how_many(self) -> None:
        data = make_data(cosine=make_cosine(episode_count=9))
        model = build_poster_model(data, tz=FIXED_TZ).cosine
        self.assertEqual(len(model.rows), poster_module.COSINE_MAX_ROWS)
        self.assertEqual(model.total_episodes, 9)
        _image, log = _render_log(build_poster_model(data, tz=FIXED_TZ))
        self.assertIn("LATEST 5 OF 9 EPISODES", _texts(log))

    def test_cosine_wall_clock_labels_use_the_stated_timezone(self) -> None:
        utc = build_poster_model(make_data(), tz=UTC).cosine
        self.assertEqual(utc.tz_label, "UTC+00:00")
        self.assertEqual(utc.rows[0].span_label, "03:00\u201303:22")

    def test_cosecant_ladder_counts_and_same_break_monotonic_medians(self) -> None:
        model = build_poster_model(make_data(), tz=FIXED_TZ).cosecant
        steps = {s.kind: s for s in model.steps}
        self.assertEqual(model.total, 4)
        self.assertEqual(steps["BREAK_STARTED"].count, 4)
        self.assertEqual(steps["BREAK_COMPLETE"].count, 3)
        self.assertEqual(steps["RETURN_CONFIRMED"].count, 2)
        self.assertEqual(model.confirmed, 2)
        # Breaks a/b complete at +600s / +300s (and c at +300s): median 300s.
        self.assertEqual(steps["BREAK_COMPLETE"].median_text, "+5m")
        self.assertEqual(steps["RETURN_CONFIRMED"].median_text, "+8m 28s")
        self.assertEqual(steps["BREAK_STARTED"].median_text, "\u2014")

    def test_cosecant_median_ignores_wall_clock_entirely(self) -> None:
        sec = 1_000_000_000

        def milestone(seq, kind, eff, wall):
            return rm.CosecantMilestoneProjection(seq, kind, eff, eff, wall, "")

        skewed = tuple(
            rm.CosecantBreakProjection(
                1, f"b{i}", f"s{i}",
                (
                    milestone(1, "BREAK_STARTED", 50 * sec, "2001-01-01T00:00:00Z"),
                    milestone(2, "BREAK_COMPLETE", 350 * sec, "2099-12-31T23:59:59Z"),
                ),
                False,
            )
            for i in range(2)
        )
        chart = rm.CosecantChartProjection(rm.AVAILABLE, skewed, 2, 0, "fixture")
        model = build_poster_model(make_data(cosecant=chart), tz=FIXED_TZ).cosecant
        step = {s.kind: s for s in model.steps}["BREAK_COMPLETE"]
        self.assertEqual(step.median_text, "+5m")

    def test_cosecant_negative_monotonic_delta_is_discarded(self) -> None:
        sec = 1_000_000_000
        breaks = (
            rm.CosecantBreakProjection(
                1, "x", "s",
                (
                    rm.CosecantMilestoneProjection(1, "BREAK_STARTED", 900 * sec, 900 * sec, "2026-09-18T00:00:00Z", ""),
                    rm.CosecantMilestoneProjection(2, "BREAK_COMPLETE", 100 * sec, 100 * sec, "2026-09-18T00:05:00Z", ""),
                ),
                False,
            ),
        )
        chart = rm.CosecantChartProjection(rm.AVAILABLE, breaks, 1, 0, "fixture")
        model = build_poster_model(make_data(cosecant=chart), tz=FIXED_TZ).cosecant
        self.assertEqual({s.kind: s for s in model.steps}["BREAK_COMPLETE"].median_text, "\u2014")

    def test_unconfirmed_break_is_not_called_a_failure(self) -> None:
        model = build_poster_model(make_data(), tz=FIXED_TZ).cosecant
        labels = [piece.label.lower() for piece in model.slices]
        self.assertIn("no return confirmation recorded", labels)
        self.assertFalse(any("fail" in label or "missed" in label for label in labels))

    def test_lifetime_metric_unavailable_is_never_zero(self) -> None:
        data = make_data(lifetime_summary=make_lifetime(triggers=None))
        model = build_poster_model(data, tz=FIXED_TZ)
        for panel in (model.sine, model.mine, model.cosine, model.cosecant):
            self.assertEqual(panel.cards[2].value, "UNAVAILABLE")

    def test_statuses_are_handled_independently(self) -> None:
        data = make_data(
            sine=rm._unavailable_sine("sqlite3.OperationalError: secret path C:/x.db"),
            mine=rm.MineChartProjection(rm.NO_DATA, (), (), 0, 0, "none"),
        )
        model = build_poster_model(data, tz=FIXED_TZ)
        self.assertEqual(model.sine.status, rm.UNAVAILABLE)
        self.assertEqual(model.mine.status, rm.NO_DATA)
        self.assertEqual(model.cosine.status, rm.AVAILABLE)
        self.assertEqual(model.cosecant.status, rm.AVAILABLE)
        self.assertEqual([c.value for c in model.sine.cards[:2]], ["UNAVAILABLE"] * 2)
        self.assertEqual([c.value for c in model.mine.cards[:2]], ["NO DATA"] * 2)


# --------------------------------------------------------------------------
# Painter: composition, geometry, evidence states
# --------------------------------------------------------------------------


class PosterPaintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        cls.model = build_poster_model(make_data(), tz=FIXED_TZ)
        cls.image, cls.log = _render_log(cls.model)

    def test_canvas_matches_reference_and_a3_target_keeps_its_size(self) -> None:
        self.assertAlmostEqual(CANVAS_W / CANVAS_H, 16.0 / 9.0, places=3)
        self.assertAlmostEqual(A3_LANDSCAPE_PX[0] / A3_LANDSCAPE_PX[1], 420.0 / 297.0, places=3)
        from PyQt6.QtGui import QPainter

        image = QImage(400, 400, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        poster_module.paint_poster(painter, self.model, load_official_logo(), width=400, height=400)
        painter.end()

    def test_five_panels_and_system_summary_follow_reference_geometry(self) -> None:
        rects = poster_module.POSTER_RECTS
        expectations = {"SINE": poster_module.ORANGE, "MINE": poster_module.PINK,
                        "COSINE": poster_module.VIOLET, "SECANT": poster_module.BLUE,
                        "COSECANT": poster_module.GREEN}
        self.assertEqual(set(rects), {"SINE", "MINE", "COSINE", "SECANT", "COSECANT", "SYSTEM"})
        self.assertLess(rects["SINE"].x(), rects["MINE"].x())
        self.assertLess(rects["SINE"].y(), rects["COSINE"].y())
        self.assertLess(rects["COSINE"].y(), rects["SECANT"].y())
        self.assertEqual(rects["SECANT"].y(), rects["SYSTEM"].y())
        for organ, tone in expectations.items():
            self.assertEqual(poster_module.ORGAN_COLOR[organ], tone)

    def test_panels_do_not_overlap_each_other_or_the_footer(self) -> None:
        rects = poster_module.POSTER_RECTS
        organs = list(rects)
        for i, a in enumerate(organs):
            self.assertTrue(QRectF(0, 0, CANVAS_W, CANVAS_H).contains(rects[a]))
            for b in organs[i + 1:]:
                self.assertFalse(rects[a].intersects(rects[b]), f"{a} overlaps {b}")
            self.assertLess(rects[a].bottom(), 884)

    def test_official_logo_is_drawn_with_native_proportions(self) -> None:
        logo = load_official_logo()
        self.assertEqual((logo.width(), logo.height()), (1024, 1024))
        self.assertTrue(logo.hasAlphaChannel())
        xs, ys = [], []
        for y in range(20, 72):
            for x in range(606, 656):
                color = self.image.pixelColor(x, y)
                if color.blue() > 150 and (color.blue() - color.green() > 30 or color.red() > 120):
                    xs.append(x)
                    ys.append(y)
        self.assertGreater(len(xs), 40, "logo pixels not found")
        drawn = (max(xs) - min(xs)) / (max(ys) - min(ys))
        nx, ny = [], []
        for y in range(0, logo.height(), 4):
            for x in range(0, logo.width(), 4):
                if logo.pixelColor(x, y).alpha() > 128:
                    nx.append(x)
                    ny.append(y)
        native = (max(nx) - min(nx)) / (max(ny) - min(ny))
        self.assertAlmostEqual(drawn, native, delta=native * 0.1)

    def test_required_headings_and_titles_are_present(self) -> None:
        texts = set(_texts(self.log))
        for expected in (
            "MYELIN", "2.0",
            "OBSERVE  \u00b7  UNDERSTAND  \u00b7  NUDGE  \u00b7  RECOVER  \u00b7  REPEAT",
            "BEHAVIOUR INTELLIGENCE FOR A FOCUSED TOMORROW",
            "FIVE ORGANS  \u00b7  ONE SYSTEM  \u00b7  A BRIGHTER YOU",
            "SINE", "MINE", "COSINE", "SECANT", "COSECANT",
            "INTERVENTION STAGES", "DECISION PATHWAY",
            "RECORDED EVENT TIMELINE", "RETURN LADDER",
            "STAGE DISTRIBUTION", "RECOVERY JOURNEY", "SYSTEM SUMMARY",
            "PRODUCTIVE USE", "SELF-CONTROL", "BETTER HABITS", "A CALMER MIND",
            "A BRIGHTER TOMORROW",
        ):
            self.assertIn(expected, texts)

    def test_excluded_features_never_appear(self) -> None:
        blob = " ".join(_texts(self.log)).lower()
        for banned in ("sensehub", "session health", "coming soon", "sine-4"):
            self.assertNotIn(banned, blob)

    def test_no_text_is_clipped_or_off_canvas(self) -> None:
        canvas = QRectF(-1.5, -1.5, CANVAS_W + 3, CANVAS_H + 3)
        for item in self.log:
            self.assertTrue(canvas.contains(item.rect), f"off canvas: {item.text!r} {item.rect}")
            if item.region_rect is not None:
                region = item.region_rect.adjusted(-2, -2, 2, 2)
                self.assertTrue(region.contains(item.rect), f"{item.text!r} escapes {item.region}")

    def test_text_is_never_shrunk_to_illegibility(self) -> None:
        # The wide window still needs readable labels at 1600 x 850.
        for item in self.log:
            self.assertGreaterEqual(item.size, 9.5, f"{item.text!r} shrunk to {item.size:.1f}")

    def test_footer_is_complete_and_inside_the_canvas(self) -> None:
        footer = [item for item in self.log if item.region == "footer"]
        texts = [item.text for item in footer]
        self.assertTrue(any(t.startswith("Recorded MYELIN data") for t in texts))
        self.assertTrue(any("snapshot-fixture" in t for t in texts))
        self.assertTrue(any("read separately" in t for t in texts))
        self.assertTrue(any("2026-09-18 12:00 UTC+05:30" in t for t in texts))
        for item in footer:
            self.assertLessEqual(item.rect.bottom(), CANVAS_H + 1.5)
            self.assertGreaterEqual(item.rect.top(), 884)

    def test_text_runs_do_not_collide_inside_a_panel(self) -> None:
        by_region: dict[str, list] = {}
        for item in self.log:
            if item.region.startswith(("panel:", "card", "mine-node")):
                by_region.setdefault(item.region + str(item.region_rect), []).append(item)
        for items in by_region.values():
            for i, a in enumerate(items):
                for b in items[i + 1:]:
                    overlap = a.rect.intersected(b.rect)
                    if overlap.isEmpty():
                        continue
                    self.assertLess(
                        overlap.width() * overlap.height(), 6.0,
                        f"{a.text!r} collides with {b.text!r}",
                    )

    def test_all_unavailable_evidence_prints_no_measurement_at_all(self) -> None:
        data = make_data(
            lifetime_summary=make_lifetime(triggers=None),
            sine=rm._unavailable_sine("SECRET-ERR"),
            mine=rm._unavailable_mine("SECRET-ERR"),
            cosine=rm._unavailable_cosine("SECRET-ERR"),
            cosecant=rm._unavailable_cosecant("SECRET-ERR"),
        )
        model = build_poster_model(data, tz=FIXED_TZ)
        _image, log = _render_log(model)
        chrome = {"SINE", "MINE", "COSINE", "SECANT", "COSECANT", "SYSTEM SUMMARY"}
        for item in log:
            if item.region.startswith(("panel:", "card", "mine-node")) and item.text not in chrome:
                # SECANT stage identifiers are labels, not measurements.
                stripped = re.sub(r"(SINE|MINE|SECANT)-\d", "", item.text)
                self.assertFalse(
                    any(ch.isdigit() for ch in stripped), f"fabricated figure: {item.text!r}"
                )
        blob = " ".join(_texts(log))
        self.assertNotIn("SECRET-ERR", blob)
        self.assertNotIn("sqlite", blob.lower())
        self.assertEqual(blob.count("EVIDENCE UNAVAILABLE"), 4)
        self.assertIn("AWAITING APPROVED SECANT ANALYTICS", blob)
        self.assertIn("Interventions and returns await shared definitions", blob)

    def test_no_data_state_is_a_neon_message_not_zero(self) -> None:
        data = make_data(
            sine=rm.SineChartProjection(
                rm.NO_DATA, (),
                tuple(rm.SineFunnelStageProjection(n, (), 0, 0) for n in (1, 2, 3)),
                (), 0, 0, "none",
            ),
            mine=rm.MineChartProjection(rm.NO_DATA, (), (), 0, 0, "none"),
            cosine=rm.CosineChartProjection(rm.NO_DATA, (), 0, 0, "none"),
            cosecant=rm.CosecantChartProjection(rm.NO_DATA, (), 0, 0, "none"),
        )
        _image, log = _render_log(build_poster_model(data, tz=FIXED_TZ))
        blob = _texts(log)
        for noun in ("SINE EPISODES", "MINE-1 CHOICES", "COSINE EPISODES", "COSECANT BREAKS"):
            self.assertIn(f"NO RECORDED {noun}", blob)
        self.assertEqual(sum(t.startswith("NO RECORDED") for t in blob), 4)
        self.assertNotIn("0%", blob)

    def test_missing_cosine_does_not_stop_the_other_organs(self) -> None:
        data = make_data(cosine=rm._unavailable_cosine("boom"))
        _image, log = _render_log(build_poster_model(data, tz=FIXED_TZ))
        blob = _texts(log)
        self.assertIn("SINE-1", blob)
        self.assertIn("I WILL COME BACK", blob)
        self.assertIn("EVIDENCE UNAVAILABLE", blob)
        self.assertIn("RETURN OUTCOME", blob)

    def test_missing_logo_fails_explicitly_instead_of_substituting(self) -> None:
        from unittest.mock import patch

        with patch.object(poster_module, "resource_path", return_value=Path("missing.png")):
            with self.assertRaises(poster_module.PosterAssetError):
                load_official_logo()

    def test_painting_does_no_database_access(self) -> None:
        import sqlite3
        from unittest.mock import patch

        with patch.object(sqlite3, "connect", side_effect=AssertionError("db access")):
            model = build_poster_model(make_data(), tz=FIXED_TZ)
            render_poster_image(model, load_official_logo(), 400)

    def test_mine_branches_fit_with_many_outcomes(self) -> None:
        for spec in (
            [("I_WILL_COME_BACK", o) for o in ("RETURNED_AFTER_CALLBACK", "RETURNED_AFTER_INTENT", "INCOMPLETE", "COSINE_HANDOFF")]
            + [("I_WILL_COME_BACK", None)] + [("ITS_IMPORTANT", "RETURNED_AFTER_CALLBACK")],
            None,
        ):
            model = build_poster_model(make_data(mine=make_mine(spec)), tz=FIXED_TZ)
            _image, log = _render_log(model)
            self.assertIn("Each choice has its own outcome path.", _texts(log))
            for item in log:
                if item.region == "panel:MINE":
                    self.assertTrue(poster_module.POSTER_RECTS["MINE"].adjusted(-2, -2, 2, 2).contains(item.rect))

    def test_folded_mine_outcomes_still_reconcile_with_their_branch(self) -> None:
        outcomes = ["RETURNED_AFTER_INTENT", "RETURNED_AFTER_CALLBACK", "STUDY_PREEMPTION", "INCOMPLETE", "EMERGENCY", "COSINE_HANDOFF"]
        spec = [("I_WILL_COME_BACK", o) for o in outcomes for _ in range(2)] + [("I_WILL_COME_BACK", None)]
        spec += [("ITS_IMPORTANT", "INCOMPLETE")]
        model = build_poster_model(make_data(mine=make_mine(spec)), tz=FIXED_TZ).mine
        branch = model.choices[0]
        self.assertLessEqual(len(branch.outcomes), poster_module.MINE_MAX_BRANCH_NODES)
        self.assertEqual(sum(o.count for o in branch.outcomes), branch.count)
        self.assertTrue(any(o.label.startswith("Other documented (") for o in branch.outcomes))
        self.assertEqual(branch.outcomes[-1].label, "No documented outcome")
        # The donut still lists every documented outcome individually.
        self.assertGreaterEqual(len([s for s in model.slices if s.label != "No documented outcome"]), 6)

    def test_long_snapshot_digest_is_shortened_in_the_footer_only(self) -> None:
        digest = "a3e84595e0a6bf21d7b4dc8080e2873272d6e98ae7aaf7902e22563f4efdec48"
        lifetime = replace(make_lifetime(), snapshot_id=digest)
        model = build_poster_model(make_data(lifetime_summary=lifetime), tz=FIXED_TZ)
        self.assertEqual(model.snapshot_id, digest)
        self.assertEqual(model.snapshot_label, digest[:12] + "…")
        _image, log = _render_log(model)
        footer = next(i.text for i in log if i.text.startswith("Recorded MYELIN data"))
        self.assertIn(digest[:12], footer)
        self.assertNotIn(digest, footer)

    def test_many_mine_outcomes_still_fit(self) -> None:
        outcomes = [
            "RETURNED_AFTER_INTENT", "EARLY_RETURN_DURING_IMPORTANT_ALLOWANCE",
            "RETURNED_AFTER_CALLBACK", "STUDY_PREEMPTION", "INCOMPLETE", "EMERGENCY",
        ]
        spec = [("I_WILL_COME_BACK", o) for o in outcomes] + [("I_WILL_COME_BACK", None)]
        spec += [("ITS_IMPORTANT", o) for o in outcomes] + [("ITS_IMPORTANT", None)]
        model = build_poster_model(make_data(mine=make_mine(spec)), tz=FIXED_TZ)
        _image, log = _render_log(model)
        canvas = QRectF(-1.5, -1.5, CANVAS_W + 3, CANVAS_H + 3)
        for item in log:
            self.assertTrue(canvas.contains(item.rect))
            if item.region_rect is not None:
                self.assertTrue(item.region_rect.adjusted(-2, -2, 2, 2).contains(item.rect), item.text)


# --------------------------------------------------------------------------
# Window: lifecycle and export
# --------------------------------------------------------------------------


class _WindowCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.engine = _Engine()
        self.analytics = _Analytics()
        self.data = make_data()
        self.loads = 0

        def provider():
            self.loads += 1
            return self.data

        self.button = QPushButton("GET CHART")
        self.poster = NeonPosterWindow()
        self.controller = GetChartController(
            engine=self.engine,
            lifecycle=_Lifecycle(),
            analytics_opener=self.analytics.open_composer,
            data_provider=provider,
        )
        self.controller.register_button(self.button)
        self.controller.register_poster(self.poster)
        for signal in (
            self.engine.engine_status_changed,
            self.engine.engine_stopped,
            self.engine.engine_failed,
        ):
            signal.connect(self.controller.lifecycle_changed)
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.controller.shutdown()
        self.button.deleteLater()
        self.app.processEvents()
        self.tmp.cleanup()

    def open_loaded(self) -> None:
        self.assertTrue(self.controller.open_poster())
        self.app.processEvents()
        self.assertIsNotNone(self.poster.model)

    def chooser(self, name: str):
        target = str(self.dir / name)
        return lambda _kind, _default, _filter: target

    def leftovers(self) -> list[str]:
        return sorted(item.name for item in self.dir.iterdir())


class PosterLifecycleTests(_WindowCase):
    def test_opens_when_stopped_and_loads_the_guarded_snapshot(self) -> None:
        self.open_loaded()
        self.assertTrue(self.poster.isVisible())
        self.assertEqual(self.loads, 1)
        self.assertTrue(self.poster.canvas.has_poster)
        self.assertEqual(self.poster.model.sine.total, 10)
        self.assertEqual(self.poster.model.snapshot_id, "snapshot-fixture")

    def test_control_bar_has_exactly_the_three_approved_actions(self) -> None:
        self.assertEqual(self.poster.analytics_button.text(), "OPEN ANALYTICS SHEET")
        self.assertEqual(self.poster.pdf_button.text(), "EXPORT A3 PDF")
        self.assertEqual(self.poster.jpg_button.text(), "EXPORT HIGH-RES JPG")
        self.assertEqual(len(self.poster.findChildren(QPushButton)), 3)
        self.assertFalse(self.poster.canvas.findChildren(QPushButton))

    def test_locked_in_every_running_state_and_never_loads_data(self) -> None:
        for state in ("STARTING", "ACTIVE", "PAUSED", "STOPPING", "EMERGENCY"):
            with self.subTest(state=state):
                self.engine.publish(state, active=True)
                self.assertFalse(self.controller.open_poster())
                self.assertFalse(self.poster.isVisible())
        self.app.processEvents()
        self.assertEqual(self.loads, 0)

    def test_open_poster_disappears_and_forgets_data_when_session_starts(self) -> None:
        self.open_loaded()
        self.engine.publish("STARTING", active=True)
        self.assertFalse(self.poster.isVisible())
        self.assertIsNone(self.poster.model)
        self.assertFalse(self.poster.canvas.has_poster)
        self.assertFalse(self.poster.pdf_button.isEnabled())

    def test_async_result_cannot_reopen_a_revoked_poster(self) -> None:
        self.assertTrue(self.controller.open_poster())  # the load is still queued
        self.assertTrue(self.poster.isVisible())
        self.engine.publish("ACTIVE", active=True)
        self.assertFalse(self.poster.isVisible())
        self.app.processEvents()
        self.assertFalse(self.poster.isVisible())
        self.assertIsNone(self.poster.model)
        self.assertEqual(self.loads, 0, "a revoked open must not read data")

    def test_session_starting_during_the_data_read_discards_the_result(self) -> None:
        def racing():
            self.engine.publish("STARTING", active=True)
            return self.data

        self.controller._data_provider = racing
        self.assertTrue(self.controller.open_poster())
        self.app.processEvents()
        self.assertFalse(self.poster.isVisible())
        self.assertIsNone(self.poster.model)

    def test_read_failure_shows_unavailable_without_raw_error(self) -> None:
        def broken():
            raise RuntimeError("sqlite3 secret C:/private/path.db")

        self.controller._data_provider = broken
        self.assertTrue(self.controller.open_poster())
        self.app.processEvents()
        self.assertTrue(self.poster.isVisible())
        self.assertIsNone(self.poster.model)
        self.assertNotIn("secret", self.poster.status_label.text())
        self.assertFalse(self.poster.pdf_button.isEnabled())

    def test_reopening_reuses_the_single_window_and_refreshes_data(self) -> None:
        self.open_loaded()
        first = self.controller.poster
        self.open_loaded()
        self.assertIs(self.controller.poster, first)
        self.assertEqual(self.loads, 2)

    def test_original_analytics_sheet_stays_reachable_from_the_poster(self) -> None:
        self.open_loaded()
        self.poster.analytics_button.click()
        self.assertEqual(self.analytics.open_calls, 1)
        self.assertTrue(self.poster.isVisible())

    def test_canvas_keeps_aspect_ratio_at_any_window_size(self) -> None:
        self.open_loaded()
        for size in ((900, 700), (1500, 820), (700, 1100)):
            self.poster.resize(*size)
            self.app.processEvents()
            target = self.poster.canvas._target()
            self.assertAlmostEqual(target.width() / target.height(), CANVAS_W / CANVAS_H, places=3)
            self.assertLessEqual(target.width(), self.poster.canvas.width() + 0.5)
            self.assertLessEqual(target.height(), self.poster.canvas.height() + 0.5)


class PosterExportTests(_WindowCase):
    def test_a3_pdf_is_one_landscape_a3_page_from_the_canonical_painter(self) -> None:
        self.open_loaded()
        self.poster.path_chooser = self.chooser("poster.pdf")
        self.assertTrue(self.controller.export_a3_pdf())
        pdf = self.dir / "poster.pdf"
        self.assertTrue(pdf.is_file())
        pages, (width, height) = inspect_pdf(pdf)
        self.assertEqual(pages, 1)
        self.assertAlmostEqual(width, 420 / 25.4 * 72, delta=2.0)
        self.assertAlmostEqual(height, 297 / 25.4 * 72, delta=2.0)
        self.assertGreater(width, height)
        self.assertEqual(self.leftovers(), ["poster.pdf"])

    def test_pdf_rasterises_with_all_panels_and_no_alpha_gradient_artifacts(self) -> None:
        try:
            import pymupdf
        except ImportError:
            self.skipTest("PyMuPDF not installed")
        self.open_loaded()
        self.poster.path_chooser = self.chooser("poster.pdf")
        self.assertTrue(self.controller.export_a3_pdf())
        document = pymupdf.open(str(self.dir / "poster.pdf"))
        self.assertEqual(len(document), 1)
        pixmap = document[0].get_pixmap(dpi=48, alpha=False)
        self.assertAlmostEqual(pixmap.width / pixmap.height, 420.0 / 297.0, places=2)
        image = QImage(
            pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888
        ).copy()
        # Regression: PDF radial gradients with alpha stops once painted an
        # opaque orange slab behind the footer.
        footer = [
            image.pixelColor(x, y)
            for x in range(5, pixmap.width, 40)
            for y in range(int(pixmap.height * 0.985), pixmap.height)
        ]
        brightness = sum(c.red() + c.green() + c.blue() for c in footer) / (3 * len(footer))
        self.assertLess(brightness, 70)
        self.assertGreater(pixmap.width, pixmap.height)
        document.close()

    def test_high_res_jpg_is_300dpi_a3_decodes_and_matches_the_canvas_painting(self) -> None:
        self.open_loaded()
        self.poster.path_chooser = self.chooser("poster.jpg")
        self.assertTrue(self.controller.export_high_resolution_jpg())
        path = self.dir / "poster.jpg"
        decoded = QImage(str(path))
        self.assertFalse(decoded.isNull())
        self.assertEqual((decoded.width(), decoded.height()), A3_LANDSCAPE_PX)
        self.assertAlmostEqual(decoded.dotsPerMeterX() * 0.0254, 300, delta=1.5)
        # Same painter, no control bar, no window chrome: compare with a fresh render.
        reference = render_poster_image(
            self.poster.model, load_official_logo(), decoded.width(), height_px=decoded.height()
        )
        diff = samples = 0
        for y in range(0, decoded.height(), 97):
            for x in range(0, decoded.width(), 89):
                a, b = decoded.pixelColor(x, y), reference.pixelColor(x, y)
                diff += abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
                samples += 3
        self.assertLess(diff / samples, 6.0)
        self.assertEqual(self.leftovers(), ["poster.jpg"])

    def test_both_exports_use_the_same_snapshot_without_reloading(self) -> None:
        self.open_loaded()
        model = self.poster.model
        self.poster.path_chooser = self.chooser("a.pdf")
        self.assertTrue(self.controller.export_a3_pdf())
        self.assertIn("snapshot-fixture", self.poster.status_label.text())
        self.poster.path_chooser = self.chooser("b.jpg")
        self.assertTrue(self.controller.export_high_resolution_jpg())
        self.assertIs(self.poster.model, model)
        self.assertEqual(self.loads, 1)

    def test_export_is_blocked_while_running(self) -> None:
        self.open_loaded()
        self.poster.path_chooser = self.chooser("x.pdf")
        self.engine.publish("ACTIVE", active=True)
        self.assertFalse(self.controller.export_a3_pdf())
        self.assertFalse(self.controller.export_high_resolution_jpg())
        self.assertEqual(self.leftovers(), [])

    def test_revocation_during_file_selection_cancels_and_writes_nothing(self) -> None:
        self.open_loaded()
        target = str(self.dir / "late.pdf")
        token = self.poster.access_token

        def choose_then_start(_kind, _default, _filter):
            self.engine.publish("STARTING", active=True)
            return target

        self.poster.path_chooser = choose_then_start
        self.assertFalse(self.poster.export_a3_pdf(token, self.controller.access_is_current))
        self.assertEqual(self.leftovers(), [])

    def test_every_access_check_point_cancels_without_a_partial_file(self) -> None:
        self.open_loaded()
        token = self.poster.access_token
        for kind, name, method in (
            ("PDF", "sweep.pdf", self.poster.export_a3_pdf),
            ("JPG", "sweep.jpg", self.poster.export_high_resolution_jpg),
        ):
            self.poster.path_chooser = self.chooser(name)
            outcomes = []
            for allowed_checks in range(0, 7):
                calls = {"n": 0}

                def predicate(_token, allowed=allowed_checks, calls=calls):
                    calls["n"] += 1
                    return calls["n"] <= allowed

                result = method(token, predicate)
                outcomes.append(result)
                if not result:
                    self.assertEqual(self.leftovers(), [], f"{kind} leaked after {allowed_checks} checks")
                else:
                    self.assertEqual(self.leftovers(), [name])
                    (self.dir / name).unlink()
            first_success = outcomes.index(True)
            self.assertTrue(all(not r for r in outcomes[:first_success]))
            self.assertTrue(all(outcomes[first_success:]))
            self.assertGreaterEqual(
                first_success, 4,
                "must check before initiating, using the snapshot, after selection and before publishing",
            )

    def test_last_moment_revocation_leaves_an_existing_file_untouched(self) -> None:
        self.open_loaded()
        existing = self.dir / "keep.pdf"
        existing.write_bytes(b"ORIGINAL")
        self.poster.path_chooser = self.chooser("keep.pdf")
        token = self.poster.access_token
        calls = {"n": 0}

        def predicate(_token):
            calls["n"] += 1
            return calls["n"] <= 3  # only the publish-time check fails

        self.assertFalse(self.poster.export_a3_pdf(token, predicate))
        self.assertEqual(existing.read_bytes(), b"ORIGINAL")
        self.assertEqual(self.leftovers(), ["keep.pdf"])

    def test_render_failure_discards_partial_output_and_keeps_old_file(self) -> None:
        from unittest.mock import patch

        self.open_loaded()
        existing = self.dir / "poster.pdf"
        existing.write_bytes(b"ORIGINAL")
        self.poster.path_chooser = self.chooser("poster.pdf")

        def partial_then_fail(_model, _logo, path):
            Path(path).write_bytes(b"%PDF-partial")
            raise OSError("disk full")

        with patch.object(poster_module, "write_poster_pdf", partial_then_fail):
            self.assertFalse(self.controller.export_a3_pdf())
        self.assertEqual(existing.read_bytes(), b"ORIGINAL")
        self.assertEqual(self.leftovers(), ["poster.pdf"])
        self.assertIn("no file was published", self.poster.status_label.text())

    def test_cancelled_file_dialog_writes_nothing(self) -> None:
        self.open_loaded()
        self.poster.path_chooser = lambda *_a: ""
        self.assertFalse(self.controller.export_a3_pdf())
        self.assertEqual(self.leftovers(), [])

    def test_wrong_extension_is_corrected_not_mislabelled(self) -> None:
        self.open_loaded()
        self.poster.path_chooser = self.chooser("poster.txt")
        self.assertTrue(self.controller.export_high_resolution_jpg())
        self.assertEqual(self.leftovers(), ["poster.jpg"])

    def test_export_without_a_loaded_snapshot_does_nothing(self) -> None:
        self.assertTrue(self.controller.open_poster())  # load not yet delivered
        self.poster.path_chooser = self.chooser("early.pdf")
        self.assertFalse(self.controller.export_a3_pdf())
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
