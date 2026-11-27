"""Five-field cron expressions: validation, matching and the next fire time.

The fields are minute, hour, day of month, month and day of week - the shape everybody
writes by hand. Each field accepts ``*``, ``*/N``, ``N``, ``N-M``, ``N-M/S`` and lists of
those (``1,15,30``). Day of week is 0-7 with both 0 and 7 meaning Sunday.

Times are **naive local** datetimes on purpose: the scheduler fires against the host's
clock, and a timezone conversion here would only add a way for "09:00" to mean
something else than what the person who wrote it reads on their watch.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache

# Inclusive bounds of the five fields, in expression order.
FIELD_BOUNDS = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
FIELD_NAMES = ("minute", "hour", "day of month", "month", "day of week")

# How far ahead "next fire" looks before answering "never". A schedule whose month
# never matches (``0 9 31 2 *``) is valid syntax but has no next run.
_NEXT_FIRE_HORIZON_DAYS = 366


class CronError(ValueError):
    """An expression that cannot be parsed, with the field that was wrong."""


def _parse_field(text: str, bounds: tuple[int, int], name: str) -> set[int] | None:
    """The allowed values of one field; ``None`` means "every value" (``*``)."""
    low, high = bounds
    if text == "*":
        return None

    values: set[int] = set()
    for part in text.split(","):
        item = part.strip()
        if not item:
            raise CronError(f"{name}: empty entry in '{text}'.")

        step = 1
        if "/" in item:
            item, _, raw_step = item.partition("/")
            if not raw_step.isdigit() or int(raw_step) <= 0:
                raise CronError(f"{name}: step '{raw_step}' must be a positive number.")
            step = int(raw_step)

        if item == "*":
            start, end = low, high
        elif "-" in item:
            raw_start, _, raw_end = item.partition("-")
            if not raw_start.isdigit() or not raw_end.isdigit():
                raise CronError(f"{name}: range '{part}' is not numeric.")
            start, end = int(raw_start), int(raw_end)
        else:
            if not item.isdigit():
                raise CronError(f"{name}: '{part}' is not a number.")
            start = end = int(item)

        if start < low or end > high or start > end:
            raise CronError(f"{name}: '{part}' is outside {low}-{high}.")

        values.update(range(start, end + 1, step))

    if not values:
        raise CronError(f"{name}: '{text}' matches no value.")
    return values


@lru_cache(maxsize=256)
def _parse(expression: str) -> tuple[set[int] | None, ...]:
    text = " ".join(str(expression or "").split())
    fields = text.split(" ")
    if len(fields) != 5:
        raise CronError(
            f"Expected 5 fields (minute hour day month weekday), got {len(fields)} in '{text}'."
        )
    return tuple(
        _parse_field(field, FIELD_BOUNDS[index], FIELD_NAMES[index])
        for index, field in enumerate(fields)
    )


def validate_cron(expression: str) -> str | None:
    """The problem with this expression, or ``None`` when it can be scheduled."""
    try:
        _parse(expression)
    except CronError as exc:
        return str(exc)
    return None


def _month_day_matches(specs: tuple[set[int] | None, ...], moment: datetime) -> bool:
    """Day of month, month and weekday - everything except hour and minute."""
    months, days, weekdays = specs[3], specs[2], specs[4]
    if months is not None and moment.month not in months:
        return False

    day_hit = days is None or moment.day in days
    if weekdays is None:
        return day_hit

    # Vixie cron: with both day fields restricted, either one matching is enough.
    weekday = _weekday_of(moment)
    weekday_hit = weekday in weekdays or (weekday == 0 and 7 in weekdays)
    if days is None:
        return weekday_hit
    return day_hit or weekday_hit


def _weekday_of(moment: datetime) -> int:
    """Cron weekday: 0 is Sunday (Python's ``weekday()`` starts on Monday)."""
    return (moment.weekday() + 1) % 7


def cron_matches(expression: str, moment: datetime) -> bool:
    """Whether the expression names this minute.

    Day of month and day of week follow Vixie cron: when both are restricted, either
    one matching is enough (``0 0 1 * 1`` means "the 1st, and every Monday").
    """
    specs = _parse(expression)
    minutes, hours = specs[0], specs[1]

    if minutes is not None and moment.minute not in minutes:
        return False
    if hours is not None and moment.hour not in hours:
        return False
    return _month_day_matches(specs, moment)


def _allowed(values: set[int] | None, low: int, high: int) -> list[int]:
    if values is None:
        return list(range(low, high + 1))
    return sorted(values)


def next_fire_after(expression: str, after: datetime) -> datetime | None:
    """The first minute strictly after ``after`` that the expression matches.

    Returns ``None`` when nothing matches within a year (``0 9 31 2 *``). The search
    walks days, not minutes: a daily schedule answers on the first day it looks at.
    """
    specs = _parse(expression)
    minutes = _allowed(specs[0], 0, 59)
    hours = _allowed(specs[1], 0, 23)

    day = after.date()
    for offset in range(_NEXT_FIRE_HORIZON_DAYS + 1):
        candidate_day: date = day + timedelta(days=offset)
        probe = datetime.combine(candidate_day, time(0, 0))
        # Day level only: probing the whole expression would reject every day whose
        # 00:00 is not itself a fire time, and a daily 09:30 schedule would never
        # find its next run.
        if not _month_day_matches(specs, probe):
            continue
        for hour in hours:
            for minute in minutes:
                candidate = datetime.combine(candidate_day, time(hour, minute))
                if candidate > after:
                    return candidate
    return None
