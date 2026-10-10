"""Daily scheduled run: follows the schedule the web app sends in the heartbeat response."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)

JOB_ID = "daily-run"


@dataclass(frozen=True)
class Schedule:
    country: str
    hour: int
    minute: int
    timezone: str


def parse_schedule(reply: dict) -> Schedule | None:
    """Schedule from a heartbeat reply, or None when absent or malformed."""
    raw = reply.get("schedule")
    if not raw:
        return None
    try:
        hour, minute = (int(x) for x in str(raw["runHour"]).split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError("time out of range")
        return Schedule(str(raw["countryCode"]).upper(), hour, minute, str(raw["timezone"]))
    except (KeyError, ValueError, TypeError) as e:
        log.warning("ignoring invalid schedule %r: %s", raw, e)
        return None


class DailyScheduler:
    """One cron job at the active country's local run time. Runs never overlap."""

    def __init__(self, run_country: Callable[[str], None]):
        self._run_country = run_country
        self._scheduler = BackgroundScheduler()
        self._current: Schedule | None = None
        self._busy = threading.Lock()

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        self._scheduler.shutdown(wait=False)

    def apply(self, schedule: Schedule | None) -> bool:
        """Create, replace or remove the job. Returns True when something changed."""
        if schedule == self._current:
            return False
        if self._scheduler.get_job(JOB_ID):
            self._scheduler.remove_job(JOB_ID)
        if schedule:
            self._scheduler.add_job(
                self._fire,
                CronTrigger(hour=schedule.hour, minute=schedule.minute, timezone=schedule.timezone),
                args=[schedule.country],
                id=JOB_ID,
                coalesce=True,
                misfire_grace_time=3600,  # still run if the agent was busy or restarted within the hour
            )
            log.info("daily run scheduled for %s at %02d:%02d %s", schedule.country, schedule.hour, schedule.minute, schedule.timezone)
        else:
            log.info("no active country: daily run unscheduled")
        self._current = schedule
        return True

    @property
    def next_run(self):
        job = self._scheduler.get_job(JOB_ID)
        return job.next_run_time if job else None

    def _fire(self, country: str) -> None:
        if not self._busy.acquire(blocking=False):
            log.warning("a run is already in progress: skipping the scheduled run for %s", country)
            return
        try:
            log.info("scheduled run starting for %s", country)
            self._run_country(country)
        except Exception:
            log.exception("scheduled run for %s failed", country)
        finally:
            self._busy.release()
