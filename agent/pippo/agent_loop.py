from __future__ import annotations

import logging
import platform
import time

from pippo import __version__
from pippo.api_client import ApiClient, ApiError
from pippo.config import Settings
from pippo.precheck import PrecheckResult, compare_countries, detect_ip_country
from pippo.scheduler import DailyScheduler, parse_schedule
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


def serve(settings: Settings) -> None:
    """Heartbeat loop plus the daily scheduler. Job polling for on-demand runs arrives in Phase 2."""
    client = ApiClient(settings)
    scheduler = DailyScheduler(lambda country: _scheduled_run(settings, country))
    scheduler.start()
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
        scheduler.shutdown()
        client.close()
