from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from jobsinsight.config import ScheduleSettings
from jobsinsight.scheduler import Scheduler, is_due, missed_runs, next_run_after, upcoming_runs

SHANGHAI = ZoneInfo("Asia/Shanghai")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_daily_schedule_is_evaluated_in_the_configured_timezone():
    settings = ScheduleSettings(mode="daily", daily_times=["00:00"], timezone="Asia/Shanghai")
    # 2026-03-01T10:00Z == 18:00 in Shanghai, so the next midnight is the 2nd.
    assert next_run_after(settings, utc("2026-03-01T10:00")) == datetime(2026, 3, 2, tzinfo=SHANGHAI)


def test_multiple_daily_times_pick_the_nearest():
    settings = ScheduleSettings(mode="daily", daily_times=["08:30", "20:30"], timezone="Asia/Shanghai")
    assert next_run_after(settings, utc("2026-03-01T02:00")) == datetime(2026, 3, 1, 20, 30, tzinfo=SHANGHAI)


def test_cron_mode():
    settings = ScheduleSettings(mode="cron", cron="0 */6 * * *", timezone="UTC")
    assert next_run_after(settings, utc("2026-03-01T07:10")).hour == 12


def test_interval_mode():
    settings = ScheduleSettings(mode="interval", interval_minutes=90, timezone="UTC")
    assert next_run_after(settings, utc("2026-03-01T07:10")) == utc("2026-03-01T08:40")


def test_manual_and_disabled_never_run():
    assert next_run_after(ScheduleSettings(mode="manual"), utc("2026-03-01T07:10")) is None
    assert next_run_after(ScheduleSettings(enabled=False), utc("2026-03-01T07:10")) is None


def test_upcoming_runs_are_ordered_and_distinct():
    settings = ScheduleSettings(mode="daily", daily_times=["08:30", "20:30"], timezone="Asia/Shanghai")
    runs = upcoming_runs(settings, utc("2026-03-01T00:00"), 4)
    assert len(runs) == 4
    assert runs == sorted(runs)


def test_missed_runs_lists_every_skipped_window():
    settings = ScheduleSettings(mode="daily", daily_times=["00:00"], timezone="UTC")
    skipped = list(missed_runs(settings, utc("2026-03-01T01:00"), utc("2026-03-04T01:00")))
    assert [moment.day for moment in skipped] == [2, 3, 4]


def test_is_due_only_after_a_window_passed():
    settings = ScheduleSettings(mode="daily", daily_times=["00:00"], timezone="UTC")
    assert is_due(settings, last_run_at=None) is True
    assert is_due(settings, last_run_at=utc("2026-03-01T00:05"), now=utc("2026-03-01T12:00")) is False
    assert is_due(settings, last_run_at=utc("2026-03-01T00:05"), now=utc("2026-03-02T00:30")) is True


def test_is_due_is_false_for_manual_mode():
    assert is_due(ScheduleSettings(mode="manual"), last_run_at=None) is False


def test_scheduler_runs_once_then_stops():
    settings = ScheduleSettings(mode="interval", interval_minutes=1, timezone="UTC")
    triggers: list[str] = []
    now = datetime.now(UTC)

    scheduler = Scheduler(
        settings,
        triggers.append,
        # A last run far in the past makes the next slot immediately due.
        last_run_at=now - timedelta(hours=5),
        max_iterations=1,
    )
    settings.catch_up = False
    assert scheduler.run_forever() == 1
    assert triggers == ["schedule"]


def test_scheduler_catches_up_on_start():
    settings = ScheduleSettings(mode="daily", daily_times=["00:00"], timezone="UTC", catch_up=True)
    triggers: list[str] = []
    scheduler = Scheduler(
        settings,
        triggers.append,
        last_run_at=datetime.now(UTC) - timedelta(days=3),
        max_iterations=0,
    )
    scheduler.run_forever()
    assert triggers == ["catch_up"]


def test_scheduler_manual_trigger_wins():
    settings = ScheduleSettings(mode="manual", timezone="UTC")
    triggers: list[str] = []
    scheduler = Scheduler(settings, triggers.append, max_iterations=1)
    scheduler.trigger_now()
    scheduler.run_forever()
    assert triggers == ["manual"]


def test_a_failing_run_does_not_kill_the_loop():
    settings = ScheduleSettings(mode="manual", timezone="UTC")

    def boom(_trigger: str) -> None:
        raise RuntimeError("collector exploded")

    scheduler = Scheduler(settings, boom, max_iterations=1)
    scheduler.trigger_now()
    assert scheduler.run_forever() == 1
