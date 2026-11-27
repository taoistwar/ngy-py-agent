"""Cron expressions: what is accepted, what matches a minute, and what comes next.

The scheduler's whole correctness rests on these three questions, and each of them is
easy to get subtly wrong (a step of ``*/15`` that includes 0, Sunday spelled 0 *and* 7,
day-of-month/day-of-week combining with OR). They are tested here instead of through
the thread, so a failure names the field that broke.

Run from the repository root::

    uv run python test/agent/scheduling/cron_test.py -v
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.runtime.scheduling.cron import (  # noqa: E402
    cron_matches,
    next_fire_after,
    validate_cron,
)


def moment(text):
    return datetime.strptime(text, "%Y-%m-%d %H:%M")


class ValidateTest(unittest.TestCase):
    def test_the_everyday_shapes_are_accepted(self):
        for expression in (
            "* * * * *",
            "0 9 * * *",
            "*/5 * * * *",
            "0 9 * * 1-5",
            "0 0 1,15 * *",
            "30 8-18/2 * * 1,3,5",
            "0 0 * * 7",
        ):
            with self.subTest(expression=expression):
                self.assertIsNone(validate_cron(expression))

    def test_a_wrong_field_count_is_refused(self):
        self.assertIn("5 fields", validate_cron("0 9 * *"))

    def test_a_value_outside_its_range_is_refused(self):
        self.assertIn("hour", validate_cron("0 24 * * *"))
        self.assertIn("day of week", validate_cron("0 9 * * 8"))

    def test_a_zero_step_is_refused(self):
        self.assertIn("step", validate_cron("*/0 * * * *"))

    def test_a_word_is_refused(self):
        self.assertIn("minute", validate_cron("every * * * *"))


class MatchTest(unittest.TestCase):
    def test_star_matches_every_minute(self):
        self.assertTrue(cron_matches("* * * * *", moment("2026-11-27 13:47")))

    def test_a_daily_expression_matches_only_its_minute(self):
        self.assertTrue(cron_matches("0 9 * * *", moment("2026-11-27 09:00")))
        self.assertFalse(cron_matches("0 9 * * *", moment("2026-11-27 09:01")))
        self.assertFalse(cron_matches("0 9 * * *", moment("2026-11-27 10:00")))

    def test_a_step_lists_its_offsets_including_zero(self):
        for minute in (0, 15, 30, 45):
            with self.subTest(minute=minute):
                self.assertTrue(cron_matches("*/15 * * * *", moment(f"2026-11-27 10:{minute:02d}")))
        self.assertFalse(cron_matches("*/15 * * * *", moment("2026-11-27 10:07")))

    def test_a_range_on_the_weekday_field_means_workdays(self):
        # 2026-11-27 is a Friday; 28 is a Saturday.
        self.assertTrue(cron_matches("0 9 * * 1-5", moment("2026-11-27 09:00")))
        self.assertFalse(cron_matches("0 9 * * 1-5", moment("2026-11-28 09:00")))

    def test_sunday_is_both_zero_and_seven(self):
        self.assertTrue(cron_matches("0 9 * * 0", moment("2026-11-29 09:00")))
        self.assertTrue(cron_matches("0 9 * * 7", moment("2026-11-29 09:00")))

    def test_both_day_fields_restricted_matches_either_one(self):
        """Vixie cron: ``0 0 1 * 1`` is "the 1st, and every Monday"."""
        monday_not_first = moment("2026-11-30 00:00")
        first_not_monday = moment("2026-12-01 00:00")
        neither = moment("2026-12-02 00:00")

        self.assertTrue(cron_matches("0 0 1 * 1", monday_not_first))
        self.assertTrue(cron_matches("0 0 1 * 1", first_not_monday))
        self.assertFalse(cron_matches("0 0 1 * 1", neither))


class NextFireTest(unittest.TestCase):
    def test_a_daily_schedule_answers_later_the_same_day(self):
        self.assertEqual(
            datetime(2026, 11, 27, 9, 0),
            next_fire_after("0 9 * * *", moment("2026-11-27 08:00")),
        )

    def test_a_minute_that_just_passed_answers_tomorrow(self):
        self.assertEqual(
            datetime(2026, 11, 28, 9, 0),
            next_fire_after("0 9 * * *", moment("2026-11-27 09:00")),
        )

    def test_a_step_answers_the_next_offset(self):
        self.assertEqual(
            datetime(2026, 11, 27, 10, 15),
            next_fire_after("*/15 * * * *", moment("2026-11-27 10:07")),
        )

    def test_a_weekday_schedule_skips_the_weekend(self):
        # Friday after the fire time -> Monday.
        self.assertEqual(
            datetime(2026, 11, 30, 9, 0),
            next_fire_after("0 9 * * 1-5", moment("2026-11-27 10:00")),
        )

    def test_a_day_that_never_comes_has_no_next_run(self):
        self.assertIsNone(next_fire_after("0 0 31 2 *", moment("2026-11-27 10:00")))


if __name__ == "__main__":
    unittest.main()
