"""A small, dependency-free 5-field cron parser.

Supports ``*``, ``a``, ``a-b``, ``a-b/n``, ``*/n`` and comma-separated lists in
the standard ``minute hour day-of-month month day-of-week`` order, plus the
usual ``@daily``/``@hourly`` style macros. Day-of-week accepts 0-7 (both 0 and
7 mean Sunday) and three-letter English names; months accept names too.

When both day-of-month and day-of-week are restricted, cron's historical OR
semantics apply (the job runs if either matches).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

MACROS: dict[str, str] = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}

_MONTH_NAMES = {
    name: index
    for index, name in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1
    )
}
_DOW_NAMES = {name: index for index, name in enumerate(["sun", "mon", "tue", "wed", "thu", "fri", "sat"])}

_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))
_FIELD_NAMES = ("minute", "hour", "day-of-month", "month", "day-of-week")


class CronError(ValueError):
    """Raised for an unparseable cron expression."""


@dataclass(frozen=True)
class CronExpression:
    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    expression: str
    day_restricted: bool = False
    weekday_restricted: bool = False

    def matches(self, moment: datetime) -> bool:
        if moment.minute not in self.minutes or moment.hour not in self.hours:
            return False
        if moment.month not in self.months:
            return False
        return self._day_matches(moment)

    def _day_matches(self, moment: datetime) -> bool:
        # Python's weekday() is Monday=0; cron uses Sunday=0.
        cron_weekday = (moment.weekday() + 1) % 7
        day_ok = moment.day in self.days
        weekday_ok = cron_weekday in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            return day_ok or weekday_ok
        return day_ok and weekday_ok

    def next_after(self, moment: datetime, *, horizon_days: int = 1500) -> datetime:
        """First matching minute strictly after ``moment`` (same tzinfo)."""

        candidate = moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = candidate + timedelta(days=horizon_days)
        while candidate <= limit:
            if candidate.month not in self.months or not self._day_matches(candidate):
                candidate = _next_day(candidate)
                continue
            if candidate.hour not in self.hours:
                candidate = _next_hour(candidate)
                continue
            if candidate.minute not in self.minutes:
                candidate += timedelta(minutes=1)
                continue
            return candidate
        raise CronError(f"no run time for {self.expression!r} within {horizon_days} days")


def _next_day(moment: datetime) -> datetime:
    return (moment + timedelta(days=1)).replace(hour=0, minute=0)


def _next_hour(moment: datetime) -> datetime:
    return (moment + timedelta(hours=1)).replace(minute=0)


def parse_cron(expression: str) -> CronExpression:
    raw = (expression or "").strip().lower()
    if not raw:
        raise CronError("cron expression is empty")
    raw = MACROS.get(raw, raw)

    fields = raw.split()
    if len(fields) != 5:
        raise CronError(f"cron expression must have 5 fields, got {len(fields)}: {expression!r}")

    parsed = [
        _parse_field(field, low, high, name)
        for field, (low, high), name in zip(fields, _FIELD_RANGES, _FIELD_NAMES, strict=True)
    ]
    return CronExpression(
        minutes=parsed[0],
        hours=parsed[1],
        days=parsed[2],
        months=parsed[3],
        weekdays=parsed[4],
        expression=raw,
        day_restricted=fields[2] not in ("*", "?"),
        weekday_restricted=fields[4] not in ("*", "?"),
    )


def _parse_field(field: str, low: int, high: int, name: str) -> frozenset[int]:
    if field in ("*", "?"):
        return frozenset(range(low, high + 1))

    values: set[int] = set()
    for part in field.split(","):
        values.update(_parse_part(part, low, high, name))
    if not values:
        raise CronError(f"{name} field {field!r} matches nothing")
    return frozenset(values)


def _parse_part(part: str, low: int, high: int, name: str) -> set[int]:
    step = 1
    if "/" in part:
        part, _, step_text = part.partition("/")
        try:
            step = int(step_text)
        except ValueError as exc:
            raise CronError(f"invalid step {step_text!r} in {name} field") from exc
        if step <= 0:
            raise CronError(f"step must be positive in {name} field")
        part = part or "*"

    if part == "*":
        start, end = low, high
    elif "-" in part.strip("-"):
        start_text, _, end_text = part.partition("-")
        start = _parse_value(start_text, low, high, name)
        end = _parse_value(end_text, low, high, name)
    else:
        start = end = _parse_value(part, low, high, name)
        if step > 1:
            end = high

    if start > end:
        raise CronError(f"range {part!r} is inverted in {name} field")
    return set(range(start, end + 1, step))


def _parse_value(text: str, low: int, high: int, name: str) -> int:
    token = text.strip()
    if name == "month" and token in _MONTH_NAMES:
        value = _MONTH_NAMES[token]
    elif name == "day-of-week" and token in _DOW_NAMES:
        value = _DOW_NAMES[token]
    else:
        try:
            value = int(token)
        except ValueError as exc:
            raise CronError(f"invalid value {text!r} in {name} field") from exc
        if name == "day-of-week" and value == 7:
            value = 0
    if not low <= value <= high:
        raise CronError(f"value {value} out of range {low}-{high} in {name} field")
    return value


def daily_times_to_cron(times: list[str]) -> str:
    """Turn ``["00:00", "12:30"]`` into a single cron expression."""

    minutes: set[int] = set()
    hours: set[int] = set()
    for entry in times:
        hour, minute = parse_time_of_day(entry)
        hours.add(hour)
        minutes.add(minute)

    # A single cron line is the cross product of hours x minutes, so it is only
    # equivalent when every time shares one minute value.
    if len(minutes) > 1:
        raise CronError("daily_times with differing minutes cannot be expressed as one cron line")
    minute = next(iter(minutes)) if minutes else 0
    return f"{minute} {','.join(str(h) for h in sorted(hours))} * * *"


def parse_time_of_day(text: str) -> tuple[int, int]:
    """Parse ``"HH:MM"`` (or ``"H"``) into an ``(hour, minute)`` pair."""

    token = (text or "").strip()
    if not token:
        raise CronError("time of day is empty")
    hour_text, _, minute_text = token.partition(":")
    try:
        hour = int(hour_text)
        minute = int(minute_text) if minute_text else 0
    except ValueError as exc:
        raise CronError(f"invalid time of day {text!r}, expected HH:MM") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise CronError(f"time of day out of range: {text!r}")
    return hour, minute
