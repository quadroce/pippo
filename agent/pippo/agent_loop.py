from __future__ import annotations

import logging
import platform
import time

from pippo import __version__
from pippo.api_client import ApiClient, ApiError
from pippo.config import Settings
from pippo.precheck import PrecheckResult, compare_countries, detect_ip_country

log = logging.getLogger(__name__)


def heartbeat_once(settings: Settings, client: ApiClient) -> PrecheckResult:
    """Detect the current country, report it, and compare with the country the web app selected."""
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
    return result


def serve(settings: Settings) -> None:
    """Heartbeat loop. Job polling and runs are added in later steps."""
    client = ApiClient(settings)
    try:
        while True:
            try:
                heartbeat_once(settings, client)
            except ApiError as e:
                log.error("heartbeat failed: %s", e)
            time.sleep(settings.heartbeat_interval_sec)
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        client.close()