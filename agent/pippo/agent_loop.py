from __future__ import annotations

import logging
import platform
import time

from pippo import __version__
from pippo.api_client import ApiClient, ApiError
from pippo.config import Settings
from pippo.precheck import PrecheckResult, compare_countries, detect_ip_country
from pippo.jobs import JobPoller, slugs_from_channel_ids
from pippo.scheduler import DailyScheduler, RunGate, parse_schedule
from pippo.thresholds import Threshold, parse_thresholds

log = logging.getLogger(__name__)


def heartbeat_once(settings: Settings, client: ApiClient) -> tuple[PrecheckResult, dict]:
    """Detect the current country, report it, and compare with the country the web app selected.

    Returns the pre-check result and the raw reply (it carries the daily schedule).
    """
    try:
        detected: str | None = detect_ip_country(settings)
    except Exception as e:
        log.warning("country detection failed: %s", e)
        detected = None

    reply = client.heartbeat(
        {
            "agentVersion": __version__,
            "hostname": platform.node(),
            "detectedCountry": detected,
        }
    )
    result = compare_countries(reply.get("activeCountry"), detected)
    log.info("pre-check: %s", result.detail)
    return result, reply


def server_thresholds(settings: Settings, client: ApiClient) -> dict[str, Threshold]:
    """Global thresholds set in the web app's Settings. Falls back to the built-in defaults if unreachable."""
    try:
        _, reply = heartbeat_once(settings, client)
        found = parse_thresholds(reply)
        log.info("using %d thresholds from the web app", len(found))
        return found
    except ApiError as e:
        log.warning("could not fetch thresholds (%s): using built-in defaults", e)
        return {}


def _scheduled_run(settings: Settings, country: str) -> None:
    """Body of the daily job: a full run with trigger "scheduled" (this sends the daily report)."""
    from pippo.api_client import ApiClient
    from pippo.images_run import measure
    from pippo.players_run import player_measure_for
    from pippo.runner import RunBlocked, execute_run

    api = ApiClient(settings)
    try:
        overrides = server_thresholds(settings, api)
        out = execute_run(
            api,
            settings,
            country,
            lambda: measure(country, headless=True, overrides=overrides),
            trigger="scheduled",
            measure_players=player_measure_for(settings, country, True, overrides),
        )
        log.info("scheduled run %s completed: %s", out["runId"], out["counts"])
    except RunBlocked as e:
        log.error("scheduled run blocked: %s", e)
    finally:
        api.close()


def run_job(settings: Settings, job: dict) -> None:
    """Body of an on-demand job: the requested channels (or the whole country) with the requested window."""
    from pippo.images_run import measure
    from pippo.players_run import player_measure_for
    from pippo.runner import RunBlocked, execute_run

    country = job["countryCode"]
    only = slugs_from_channel_ids(job["channelIds"], country)
    api = ApiClient(settings)
    try:
        overrides = server_thresholds(settings, api)
        out = execute_run(
            api,
            settings,
            country,
            lambda: measure(country, headless=True, overrides=overrides, guide_only=not job["includeImages"]),
            trigger="on_demand",
            measure_players=player_measure_for(
                settings, country, True, overrides, window_sec=job["windowSec"], only_slugs=only
            ),
            job_id=job["id"],
        )
        log.info("job %s finished: run %s %s", job["id"], out["runId"], out["counts"])
    except RunBlocked as e:
        log.error("job %s blocked: %s", job["id"], e)
    finally:
        api.close()


def serve(settings: Settings) -> None:
    """Heartbeat loop, the daily scheduler and the on-demand job poller (they share one run gate)."""
    client = ApiClient(settings)
    gate = RunGate()
    scheduler = DailyScheduler(lambda country: _scheduled_run(settings, country), gate=gate)
    scheduler.start()
    poller = JobPoller(settings, gate, lambda job: run_job(settings, job))
    poller.start()
    try:
        while True:
            try:
                _, reply = heartbeat_once(settings, client)
                if scheduler.apply(parse_schedule(reply)):
                    log.info("next scheduled run: %s", scheduler.next_run)
            except ApiError as e:
                log.error("heartbeat failed: %s", e)
            time.sleep(settings.heartbeat_interval_sec)
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        poller.stop()
        scheduler.shutdown()
        client.close()
