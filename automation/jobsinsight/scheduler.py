"""Turns :class:`~jobsinsight.config.ScheduleSettings` into actual run times.

Three concerns live here:

* :func:`next_run_after` / :func:`upcoming_runs` — pure time arithmetic, so the
  CLI can print the plan and the tests can assert on it without waiting.
* :func:`is_due` — used by ``run-once --if-due`` so a coarse CI cron (hourly)
  can still honour a fine-grained user schedule.
* :class:`Scheduler` — the long-running daemon that sleeps until the next slot,
  supports missed-window catch-up, jitter, and a manual trigger from the API.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from random import uniform
from zoneinfo import ZoneInfo

from .config import ScheduleSettings
from .cron import parse_cron, parse_time_of_day

LOGGER = logging.getLogger(__name__)

RunCallback = Callable[[str], object]


def tz_of(settings: ScheduleSettings) -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def to_local(moment: datetime, settings: ScheduleSettings) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(tz_of(settings))


def next_run_after(settings: ScheduleSettings, moment: datetime) -> datetime | None:
    """First scheduled run strictly after ``moment``, or ``None`` when manual."""

    if not settings.enabled or settings.mode == "manual":
        return None
    local = to_local(moment, settings).replace(second=0, microsecond=0)

    if settings.mode == "cron":
        return parse_cron(settings.cron).next_after(local)

    if settings.mode == "interval":
        return local + timedelta(minutes=settings.interval_minutes)

    candidates: list[datetime] = []
    for entry in settings.daily_times:
        hour, minute = parse_time_of_day(entry)
        today = local.replace(hour=hour, minute=minute)
        candidates.append(today if today > local else today + timedelta(days=1))
    return min(candidates) if candidates else None


def upcoming_runs(settings: ScheduleSettings, moment: datetime, count: int = 5) -> list[datetime]:
    runs: list[datetime] = []
    cursor = moment
    for _ in range(count):
        nxt = next_run_after(settings, cursor)
        if nxt is None:
            break
        runs.append(nxt)
        cursor = nxt
    return runs


def missed_runs(settings: ScheduleSettings, since: datetime, until: datetime) -> Iterator[datetime]:
    """Scheduled slots in ``(since, until]`` — the catch-up window."""

    cursor = since
    guard = 0
    while guard < 1000:
        guard += 1
        nxt = next_run_after(settings, cursor)
        if nxt is None or nxt > to_local(until, settings):
            return
        yield nxt
        cursor = nxt


def is_due(settings: ScheduleSettings, *, last_run_at: datetime | None, now: datetime | None = None) -> bool:
    """Whether a run is owed right now, given when the last one happened."""

    if not settings.enabled or settings.mode == "manual":
        return False
    moment = now or datetime.now(UTC)
    if last_run_at is None:
        return True
    return any(True for _ in missed_runs(settings, last_run_at, moment))


class Scheduler:
    """Sleeps until the next slot and invokes ``callback(trigger)``.

    ``stop()`` and ``trigger_now()`` are safe to call from another thread,
    which is how the HTTP API drives manual runs.
    """

    def __init__(
        self,
        settings: ScheduleSettings,
        callback: RunCallback,
        *,
        last_run_at: datetime | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        max_iterations: int | None = None,
    ) -> None:
        self.settings = settings
        self.callback = callback
        self.last_run_at = last_run_at
        self._clock = clock
        self._max_iterations = max_iterations
        self._wakeup = threading.Event()
        self._manual = threading.Event()
        self._stopped = threading.Event()
        self.runs_completed = 0

    # ------------------------------------------------------------- lifecycle

    def stop(self) -> None:
        self._stopped.set()
        self._wakeup.set()

    def trigger_now(self) -> None:
        self._manual.set()
        self._wakeup.set()

    def refresh(self) -> None:
        """Recompute the sleep target now — call after changing ``settings``."""

        self._wakeup.set()

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def next_run(self) -> datetime | None:
        # Interval schedules count from the previous run so a restart does not
        # silently reset the cadence; the others are absolute wall-clock slots.
        if self.settings.mode == "interval":
            return next_run_after(self.settings, self.last_run_at or self._clock())
        return next_run_after(self.settings, self._clock())

    # ------------------------------------------------------------------- loop

    def run_forever(self) -> int:
        if self.settings.mode == "manual" or not self.settings.enabled:
            LOGGER.info("调度已关闭（mode=%s），仅等待手动触发", self.settings.mode)

        if self.settings.catch_up and self.last_run_at is not None:
            pending = list(missed_runs(self.settings, self.last_run_at, self._clock()))
            if pending:
                LOGGER.info("检测到 %d 个错过的运行窗口，先补跑一次", len(pending))
                self._fire("catch_up")

        if self.settings.run_on_start and self.runs_completed == 0:
            self._fire("startup")

        iterations = 0
        while not self._stopped.is_set():
            if self._max_iterations is not None and iterations >= self._max_iterations:
                break
            iterations += 1

            target = self.next_run()
            now = self._clock()
            if target is None:
                delay = 3600.0
            else:
                delay = max(0.0, (target - to_local(now, self.settings)).total_seconds())
                if self.settings.jitter_seconds:
                    delay += uniform(0, self.settings.jitter_seconds)  # noqa: S311 - spread load only
                LOGGER.info("下一次运行：%s（%.0f 秒后）", target.isoformat(timespec="minutes"), delay)

            interrupted = self._wakeup.wait(delay)
            self._wakeup.clear()

            if self._stopped.is_set():
                break
            if self._manual.is_set():
                self._manual.clear()
                self._fire("manual")
                continue
            if interrupted:
                continue  # settings changed: recompute the next slot
            if target is not None:
                self._fire("schedule")
        return self.runs_completed

    def _fire(self, trigger: str) -> None:
        LOGGER.info("触发运行（%s）", trigger)
        try:
            self.callback(trigger)
        except Exception:  # noqa: BLE001 - a failed run must not kill the daemon
            LOGGER.exception("运行失败，等待下一个窗口")
        finally:
            self.last_run_at = self._clock()
            self.runs_completed += 1
