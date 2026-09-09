from __future__ import annotations

from datetime import datetime

import pytest

from jobsinsight.cron import CronError, daily_times_to_cron, parse_cron, parse_time_of_day


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


def test_every_field_wildcard_matches_every_minute():
    expression = parse_cron("* * * * *")
    assert expression.next_after(at("2026-03-01T10:30:15")) == at("2026-03-01T10:31")


def test_daily_midnight():
    expression = parse_cron("0 0 * * *")
    assert expression.next_after(at("2026-03-01T10:30")) == at("2026-03-02T00:00")


def test_macro_and_step():
    assert parse_cron("@hourly").next_after(at("2026-03-01T10:30")) == at("2026-03-01T11:00")
    assert parse_cron("*/15 * * * *").next_after(at("2026-03-01T10:04")) == at("2026-03-01T10:15")


def test_list_and_range_of_hours():
    expression = parse_cron("30 8,20 * * *")
    assert expression.next_after(at("2026-03-01T09:00")) == at("2026-03-01T20:30")
    assert expression.next_after(at("2026-03-01T21:00")) == at("2026-03-02T08:30")


def test_weekday_restriction_uses_sunday_zero():
    # 1-5 == Monday..Friday; 2026-03-07 is a Saturday.
    expression = parse_cron("0 9 * * 1-5")
    assert expression.next_after(at("2026-03-07T10:00")) == at("2026-03-09T09:00")


def test_weekday_names_and_seven_as_sunday():
    assert parse_cron("0 9 * * mon").weekdays == frozenset({1})
    assert parse_cron("0 9 * * 7").weekdays == frozenset({0})


def test_day_of_month_and_weekday_are_ored():
    expression = parse_cron("0 0 1 * 1")  # 每月 1 号 或 每周一
    assert expression.matches(at("2026-04-01T00:00"))  # Wednesday the 1st
    assert expression.matches(at("2026-04-06T00:00"))  # Monday the 6th
    assert not expression.matches(at("2026-04-07T00:00"))


def test_month_restriction_skips_ahead():
    expression = parse_cron("0 0 1 1 *")
    assert expression.next_after(at("2026-03-01T00:00")) == at("2027-01-01T00:00")


@pytest.mark.parametrize("bad", ["", "* * * *", "60 * * * *", "* 25 * * *", "a * * * *", "5-1 * * * *", "*/0 * * * *"])
def test_invalid_expressions_are_rejected(bad: str):
    with pytest.raises(CronError):
        parse_cron(bad)


def test_daily_times_to_cron():
    assert daily_times_to_cron(["00:00"]) == "0 0 * * *"
    assert daily_times_to_cron(["08:30", "20:30"]) == "30 8,20 * * *"


def test_daily_times_with_mixed_minutes_cannot_be_one_cron_line():
    with pytest.raises(CronError):
        daily_times_to_cron(["08:30", "20:45"])


def test_parse_time_of_day():
    assert parse_time_of_day("7") == (7, 0)
    assert parse_time_of_day(" 23:59 ") == (23, 59)
    with pytest.raises(CronError):
        parse_time_of_day("24:00")
