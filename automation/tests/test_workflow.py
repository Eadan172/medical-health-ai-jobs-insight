from __future__ import annotations

from pathlib import Path

import pytest

from jobsinsight.config import ScheduleSettings
from jobsinsight.cron import CronError
from jobsinsight.workflow import schedule_to_utc_cron, sync_workflow_cron

WORKFLOW = """name: update-data
on:
  schedule:
    - cron: '0 16 * * *'
  workflow_dispatch:
jobs:
  run:
    runs-on: ubuntu-latest
"""


def test_daily_schedule_is_shifted_into_utc():
    # 00:00 Asia/Shanghai (UTC+8) == 16:00 UTC the previous day.
    settings = ScheduleSettings(mode="daily", daily_times=["00:00"], timezone="Asia/Shanghai")
    assert schedule_to_utc_cron(settings) == "0 16 * * *"


def test_multiple_daily_times_are_all_shifted():
    settings = ScheduleSettings(mode="daily", daily_times=["08:30", "20:30"], timezone="Asia/Shanghai")
    assert schedule_to_utc_cron(settings) == "30 0,12 * * *"


def test_utc_schedule_is_unchanged():
    settings = ScheduleSettings(mode="daily", daily_times=["09:00"], timezone="UTC")
    assert schedule_to_utc_cron(settings) == "0 9 * * *"


def test_sub_hourly_interval_needs_no_shift():
    settings = ScheduleSettings(mode="interval", interval_minutes=30, timezone="Asia/Shanghai")
    assert schedule_to_utc_cron(settings) == "*/30 * * * *"


def test_weekday_restrictions_survive_the_shift():
    settings = ScheduleSettings(mode="cron", cron="0 9 * * 1-5", timezone="UTC")
    assert schedule_to_utc_cron(settings) == "0 9 * * 1,2,3,4,5"


def test_manual_mode_has_no_cron():
    with pytest.raises(CronError):
        schedule_to_utc_cron(ScheduleSettings(mode="manual"))


def test_sync_rewrites_the_cron_line(tmp_path: Path):
    path = tmp_path / "update-data.yml"
    path.write_text(WORKFLOW, encoding="utf-8")
    settings = ScheduleSettings(mode="daily", daily_times=["07:00"], timezone="Asia/Shanghai")

    result = sync_workflow_cron(path, settings)

    assert result.changed
    assert result.previous == "0 16 * * *"
    assert result.expected == "0 23 * * *"
    assert "- cron: '0 23 * * *'" in path.read_text(encoding="utf-8")
    # The rest of the workflow is untouched.
    assert "workflow_dispatch:" in path.read_text(encoding="utf-8")


def test_sync_is_idempotent(tmp_path: Path):
    path = tmp_path / "update-data.yml"
    path.write_text(WORKFLOW, encoding="utf-8")
    settings = ScheduleSettings(mode="daily", daily_times=["00:00"], timezone="Asia/Shanghai")

    assert sync_workflow_cron(path, settings).changed is False
    assert path.read_text(encoding="utf-8") == WORKFLOW


def test_check_only_does_not_write(tmp_path: Path):
    path = tmp_path / "update-data.yml"
    path.write_text(WORKFLOW, encoding="utf-8")
    settings = ScheduleSettings(mode="daily", daily_times=["07:00"], timezone="Asia/Shanghai")

    result = sync_workflow_cron(path, settings, check_only=True)

    assert result.changed
    assert path.read_text(encoding="utf-8") == WORKFLOW


def test_missing_workflow_file(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        sync_workflow_cron(tmp_path / "absent.yml", ScheduleSettings())


def test_workflow_without_a_cron_line(tmp_path: Path):
    path = tmp_path / "update-data.yml"
    path.write_text("name: x\non:\n  workflow_dispatch:\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cron"):
        sync_workflow_cron(path, ScheduleSettings())
