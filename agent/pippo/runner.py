"""Orchestrates one run: pre-check, create run, measure, upload results, finish."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Callable

from pippo import __version__
from pippo.api_client import ApiClient, ApiError
from pippo.config import AGENT_DIR, Settings
from pippo.images_run import Measurement
from pippo.precheck import detect_ip_country

log = logging.getLogger(__name__)


class RunBlocked(Exception):
    """The country pre-check failed; the server stored a blocked run."""


def _save_local(measurement: Measurement, country: str, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"run-{country}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(
        json.dumps(
            {
                "images": measurement.report,
                "channels": [
                    {"slug": c.slug, "name": c.name, **measurement.channel_results.get(c.slug, {})}
                    for c in measurement.channels
                ],
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    return path


def execute_run(
    api: ApiClient,
    settings: Settings,
    country: str,
    measure: Callable[[], Measurement],
    trigger: str = "on_demand",
    detect: Callable[[Settings], str] = detect_ip_country,
    reports_dir: Path | None = None,
) -> dict:
    """Run end to end. Returns {runId, counts}. Raises RunBlocked on a country mismatch.

    The measurement is written to agent/reports/ before anything is uploaded, so a network
    failure never loses it (the offline queue that retries uploads arrives in Phase 5).
    """
    try:
        detected: str | None = detect(settings)
    except Exception as e:
        log.warning("country detection failed: %s", e)
        detected = None

    run = api.create_run(
        {"countryCode": country, "trigger": trigger, "detectedCountry": detected, "agentVersion": __version__}
    )
    run_id = run["id"]
    if run["status"] == "blocked":
        raise RunBlocked(f"selected {country} but detected {detected or 'unknown'}; run {run_id} stored as blocked")

    try:
        m = measure()
    except BaseException as e:
        log.exception("measurement failed")
        _safe_finish(api, run_id, "failed", f"measurement failed: {e}")
        raise

    saved = _save_local(m, country, reports_dir or AGENT_DIR / "reports")
    log.info("measurement saved to %s", saved)

    try:
        api.upload_images(run_id, {"pages": m.report["pages"], "checks": m.report["checks"]})
        for ch in m.channels:
            res = m.channel_results.get(ch.slug, {"metrics": {}, "checks": []})
            api.upload_channel(
                run_id,
                {
                    "channel": {"slug": ch.slug, "name": ch.name, "category": ch.category},
                    "metrics": res["metrics"],
                    "checks": res["checks"],
                },
            )
        done = api.finish_run(run_id, {"status": "completed"})
    except ApiError as e:
        log.error("upload failed: %s (results kept in %s)", e, saved)
        _safe_finish(api, run_id, "failed", f"upload failed: {e}")
        raise
    return {"runId": run_id, "counts": done.get("counts", {}), "saved": str(saved)}


def _safe_finish(api: ApiClient, run_id: str, status: str, msg: str) -> None:
    try:
        api.finish_run(run_id, {"status": status, "log": [{"level": "error", "msg": msg[:500]}]})
    except Exception as e:
        log.warning("could not close run %s: %s", run_id, e)
