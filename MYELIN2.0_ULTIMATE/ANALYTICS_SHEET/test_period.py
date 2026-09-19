"""Period arithmetic tests: inclusive local dates -> half-open UTC interval."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from time_projection import civil_day_window_utc

from ANALYTICS_SHEET.period import IN, OUT, UNPLACEABLE, make_period, parse_instant, select_by_start

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc


def utc(y, mo, d, h=0, mi=0, s=0, us=0):
    return datetime(y, mo, d, h, mi, s, us, tzinfo=UTC).isoformat().replace("+00:00", "Z")


class PeriodTests(unittest.TestCase):
    def test_one_day_selection_is_the_whole_local_day(self) -> None:
        p = make_period(date(2026, 9, 17), date(2026, 9, 17), zone=IST)
        self.assertEqual(p.start_utc, datetime(2026, 9, 16, 18, 30, tzinfo=UTC))
        self.assertEqual(p.end_utc, datetime(2026, 9, 17, 18, 30, tzinfo=UTC))
        self.assertEqual(p.label, "17 Sep 2026 – 17 Sep 2026")

    def test_multiple_days_are_inclusive_of_the_final_day(self) -> None:
        p = make_period(date(2026, 9, 17), date(2026, 9, 19), zone=IST)
        self.assertEqual(p.end_utc, datetime(2026, 9, 19, 18, 30, tzinfo=UTC), "TO is inclusive: the exclusive edge is 00:00 on the day after")
        self.assertEqual(p.classify(utc(2026, 9, 19, 18, 29, 59, 999999)), IN)  # 19 Sep 23:59:59.999999 IST
        self.assertEqual(p.classify(utc(2026, 9, 19, 12)), IN)

    def test_episode_exactly_at_from_midnight_is_included(self) -> None:
        p = make_period(date(2026, 9, 17), date(2026, 9, 19), zone=IST)
        self.assertEqual(p.classify(utc(2026, 9, 16, 18, 30)), IN)  # 17 Sep 00:00:00 IST
        self.assertEqual(p.classify(utc(2026, 9, 16, 18, 29, 59, 999999)), OUT)

    def test_episode_exactly_at_the_boundary_after_to_is_excluded(self) -> None:
        p = make_period(date(2026, 9, 17), date(2026, 9, 19), zone=IST)
        self.assertEqual(p.classify(utc(2026, 9, 19, 18, 30)), OUT)  # 20 Sep 00:00:00 IST
        self.assertFalse(p.contains(utc(2026, 9, 20, 3)))

    def test_local_time_and_utc_are_converted_before_comparing(self) -> None:
        # The UTC *date* of these instants is 17 Sep, their IST date is 18 Sep.
        p = make_period(date(2026, 9, 17), date(2026, 9, 17), zone=IST)
        self.assertEqual(p.classify(utc(2026, 9, 17, 20)), OUT)
        # ...and the same instant is inside for a UTC-based reader.
        self.assertEqual(make_period(date(2026, 9, 17), date(2026, 9, 17), zone=UTC).classify(utc(2026, 9, 17, 20)), IN)
        # Offsets other than Z are honoured.
        self.assertEqual(p.classify("2026-09-17T12:00:00+05:30"), IN)
        self.assertEqual(p.classify("2026-09-17T00:10:00+00:00"), IN)  # 05:40 IST

    def test_naive_timestamps_are_read_as_utc_and_garbage_is_unplaceable(self) -> None:
        self.assertEqual(parse_instant("2026-09-17T10:00:00").utcoffset(), timedelta(0))
        p = make_period(date(2026, 9, 17), date(2026, 9, 17), zone=UTC)
        for bad in (None, "", "not-a-date", 42, "2026-13-40T00:00:00Z"):
            self.assertEqual(p.classify(bad), UNPLACEABLE, bad)

    def test_membership_uses_the_start_not_later_events(self) -> None:
        p = make_period(date(2026, 9, 17), date(2026, 9, 17), zone=IST)
        episodes = [
            {"id": "before-midnight-start", "start": utc(2026, 9, 16, 18, 20), "events": [utc(2026, 9, 17, 3)]},  # 16 Sep 23:50 IST
            {"id": "starts-late-on-day", "start": utc(2026, 9, 17, 18, 20), "events": [utc(2026, 9, 17, 19)]},  # 17 Sep 23:50 IST, crosses midnight
        ]
        selection = select_by_start(episodes, lambda e: e["start"], p)
        self.assertEqual([e["id"] for e in selection.inside], ["starts-late-on-day"])
        self.assertEqual((selection.outside, selection.unplaceable, selection.source_total), (1, 0, 2))

    def test_selection_splits_every_record_exactly_once(self) -> None:
        p = make_period(date(2026, 9, 17), date(2026, 9, 18), zone=IST)
        items = [utc(2026, 9, d, 6) for d in range(10, 25)] + ["bad", None]
        selection = select_by_start(items, lambda v: v, p)
        self.assertEqual(selection.source_total, len(items))
        self.assertEqual(len(selection.inside), 2)
        self.assertEqual(selection.unplaceable, 2)

    def test_from_after_to_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            make_period(date(2026, 9, 19), date(2026, 9, 17), zone=IST)
        with self.assertRaises(TypeError):
            make_period("2026-09-17", date(2026, 9, 18), zone=IST)

    def test_matches_the_approved_civil_day_window_helper(self) -> None:
        for key in ("UTC", "Asia/Kolkata", "America/New_York", "Europe/London"):
            p = make_period(date(2026, 3, 7), date(2026, 3, 9), timezone_key=key)
            self.assertEqual(p.start_utc, civil_day_window_utc(date(2026, 3, 7), key)[0], key)
            self.assertEqual(p.end_utc, civil_day_window_utc(date(2026, 3, 9), key)[1], key)

    def test_dst_days_are_not_assumed_to_be_24_hours(self) -> None:
        p = make_period(date(2026, 3, 8), date(2026, 3, 8), timezone_key="America/New_York")  # spring forward: 23h day
        self.assertEqual(p.end_utc - p.start_utc, timedelta(hours=23))
        q = make_period(date(2026, 11, 1), date(2026, 11, 1), timezone_key="America/New_York")  # fall back: 25h day
        self.assertEqual(q.end_utc - q.start_utc, timedelta(hours=25))

    def test_timezone_key_changes_membership_of_the_same_instant(self) -> None:
        instant = utc(2026, 9, 17, 20)
        self.assertEqual(make_period(date(2026, 9, 17), date(2026, 9, 17), timezone_key="UTC").classify(instant), IN)
        self.assertEqual(make_period(date(2026, 9, 17), date(2026, 9, 17), timezone_key="Asia/Kolkata").classify(instant), OUT)
        self.assertEqual(make_period(date(2026, 9, 18), date(2026, 9, 18), timezone_key="Asia/Kolkata").classify(instant), IN)

    def test_local_key_uses_the_machine_zone(self) -> None:
        p = make_period(date(2026, 9, 17), date(2026, 9, 17), timezone_key="local")
        naive_start = datetime(2026, 9, 17).astimezone(UTC)
        self.assertEqual(p.start_utc, naive_start)
        self.assertIsNone(p.zone)


if __name__ == "__main__":
    unittest.main()
