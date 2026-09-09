"""Keeps the GitHub Actions cron in sync with the user's schedule setting.

GitHub Actions cron lines are static YAML and always UTC, so the workflow
itself runs on a coarse trigger and ``run --if-due`` decides whether the local
schedule is actually due. This module additionally rewrites the cron line to
the closest UTC equivalent of the configured schedule, so the workflow fires
near the requested time instead of on an unrelated cadence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import ScheduleSettings
from .cron import parse_cron

_CRON_LINE = re.compile(
    r"^(?P<indent>\s*-\s*cron:\s*)(?P<quote>['\"]?)(?P<value>[^'\"\n]+)(?P=quote)\s*$", re.MULTILINE
)


@dataclass
class SyncResult:
    expected: str
    previous: str
    changed: bool


def schedule_to_utc_cron(settings: ScheduleSettings) -> str:
    """Cron expression for the schedule, shifted from its timezone into UTC."""

    local_cron = parse_cron(settings.as_cron())
    offset_minutes = _utc_offset_minutes(settings.timezone)

    minutes = sorted(local_cron.minutes)
    hours = sorted(local_cron.hours)
    if len(minutes) > 1 or len(hours) == 24:
        # Sub-hourly or hourly schedules need no shift.
        return settings.as_cron()

    minute = minutes[0]
    shifted_hours = set()
    for hour in hours:
        total = hour * 60 + minute - offset_minutes
        shifted_hours.add((total // 60) % 24)
    shifted_minute = (minute - offset_minutes) % 60

    day_of_month = _field(local_cron.days, 1, 31)
    month = _field(local_cron.months, 1, 12)
    day_of_week = _field(local_cron.weekdays, 0, 6)
    hour_field = ",".join(str(hour) for hour in sorted(shifted_hours))
    return f"{shifted_minute} {hour_field} {day_of_month} {month} {day_of_week}"


def _field(values: frozenset[int], low: int, high: int) -> str:
    if set(values) == set(range(low, high + 1)):
        return "*"
    return ",".join(str(value) for value in sorted(values))


def _utc_offset_minutes(timezone_name: str) -> int:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    offset = datetime.now(ZoneInfo(timezone_name)).utcoffset()
    return int(offset.total_seconds() // 60) if offset else 0


def sync_workflow_cron(path: Path, settings: ScheduleSettings, *, check_only: bool = False) -> SyncResult:
    if not path.is_file():
        raise FileNotFoundError(f"workflow 文件不存在: {path}")

    expected = schedule_to_utc_cron(settings)
    text = path.read_text(encoding="utf-8")
    match = _CRON_LINE.search(text)
    if match is None:
        raise ValueError(f"{path} 里没有找到 '- cron:' 行")

    previous = match.group("value").strip()
    if previous == expected:
        return SyncResult(expected=expected, previous=previous, changed=False)

    if not check_only:
        replacement = f"{match.group('indent')}'{expected}'"
        path.write_text(text[: match.start()] + replacement + text[match.end() :], encoding="utf-8")
    return SyncResult(expected=expected, previous=previous, changed=True)
