"""On-demand jobs: poll the web app for queued tests and run them one at a time."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from pippo.api_client import ApiClient, ApiError
from pippo.config import Settings
from pippo.scheduler import RunGate

log = logging.getLogger(__name__)


def slugs_from_channel_ids(channel_ids: list[str], country: str) -> set[str] | None:
    """Guide slugs for the job's channel ids (`<cc>-<slug>`); None means the entire country."""
    if not channel_ids:
        return None
    prefix = country.lower() + "-"
    return {cid[len(prefix):] if cid.lower().startswith(prefix) else cid for cid in channel_ids}


class JobPoller(threading.Thread):
    """Long-polls `GET /api/agent/jobs`. Never starts a job while another run holds the gate.

    The job is acknowledged only after the gate is taken, so a queued job waits in the web app
    (still `pending`, still expiring after 6 hours) while the agent is busy with the daily run.
    """

    def __init__(
        self,
        settings: Settings,
        gate: RunGate,
        handle: Callable[[dict], None],
        client: ApiClient | None = None,
    ):
        super().__init__(name="job-poller", daemon=True)
        self._settings, self._gate, self._handle = settings, gate, handle
        self._client = client or ApiClient(settings)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        idle = max(1, self._settings.poll_interval_sec)
        while not self._stop_event.is_set():
            if self._gate.busy:
                self._stop_event.wait(idle)
                continue
            try:
                jobs = self._client.next_jobs(wait=True)
            except ApiError as e:
                log.warning("job poll failed: %s", e)
                self._stop_event.wait(idle)
                continue
            if not jobs:
                self._stop_event.wait(1)
                continue
            self._process(jobs[0])

    def _process(self, job: dict) -> None:
        if not self._gate.acquire(timeout=0):
            return  # a run started meanwhile; the job stays pending and is picked up later
        try:
            try:
                self._client.ack_job(job["id"])
            except ApiError as e:
                log.info("job %s was not taken (%s)", job["id"], e)
                return
            log.info("job %s picked up: %s, %s", job["id"], job["countryCode"], f"{len(job['channelIds'])} channels" if job["channelIds"] else "entire country")
            try:
                self._handle(job)
            except Exception:
                log.exception("job %s failed", job["id"])
        finally:
            self._gate.release()
