"""Orchestrates one run: pre-check, create run, measure, upload results, finish."""

from __future__ import annotations

import gzip
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from pippo import __version__
from pippo.api_client import ApiClient, ApiError
from pippo.config import AGENT_DIR, Settings
from pippo.images_run import Measurement
from pippo.players_run import ChannelOutcome
from pippo.precheck import detect_ip_country

log = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # the web app's request body limit

PlayerMeasure = Callable[[list, Callable[[ChannelOutcome], None]], None]


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


def _upload_files(api: ApiClient, run_id: str, outcome: ChannelOutcome) -> tuple[list[dict], str | None]:
    """Upload screenshots and the raw buffer. A file that cannot be uploaded is skipped, never fatal."""
    shots, raw_url = [], None
    slug = outcome.channel.slug
    for s in outcome.screenshots:
        try:
            data = Path(s["path"]).read_bytes()
            if len(data) > MAX_UPLOAD_BYTES:
                log.warning("%s: screenshot %s is over 4 MB, skipped", slug, s["kind"])
                continue
            up = api.upload_file(run_id, "screenshot", f"{slug}-t{s['tOffsetSec']}-{s['kind']}.png", data, "image/png")
            shots.append({"tOffsetSec": int(s["tOffsetSec"]), "kind": s["kind"], "blobUrl": up["url"]})
        except (ApiError, OSError) as e:
            log.warning("%s: screenshot upload failed: %s", slug, e)
    if outcome.raw_path:
        try:
            gz = gzip.compress(outcome.raw_path.read_bytes())
            if len(gz) <= MAX_UPLOAD_BYTES:
                raw_url = api.upload_file(run_id, "raw", f"{slug}-buffer.json.gz", gz, "application/gzip")["url"]
            else:
                log.warning("%s: raw buffer is %d bytes compressed, not uploaded", slug, len(gz))
        except (ApiError, OSError) as e:
            log.warning("%s: raw buffer upload failed: %s", slug, e)
    return shots, raw_url


def execute_run(
    api: ApiClient,
    settings: Settings,
    country: str,
    measure: Callable[[], Measurement],
    trigger: str = "on_demand",
    detect: Callable[[Settings], str] = detect_ip_country,
    reports_dir: Path | None = None,
    measure_players: PlayerMeasure | None = None,
    job_id: str | None = None,
) -> dict:
    """Run end to end. Returns {runId, counts, saved, failedUploads}. Raises RunBlocked on a country mismatch.

    The images measurement is written to agent/reports/ before anything is uploaded. Channel
    results are uploaded one by one as the player measurements finish, so a crash late in a long
    run keeps everything already reported. Without `measure_players` only the logo checks are
    uploaded per channel (images-only run).
    """
    try:
        detected: str | None = detect(settings)
    except Exception as e:
        log.warning("country detection failed: %s", e)
        detected = None

    payload = {"countryCode": country, "trigger": trigger, "detectedCountry": detected, "agentVersion": __version__}
    if job_id:
        payload["jobId"] = job_id
    run = api.create_run(payload)
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

    failed: list[str] = []
    lock = threading.Lock()

    def upload_channel(outcome: ChannelOutcome) -> None:
        ch = outcome.channel
        logo = m.channel_results.get(ch.slug, {"metrics": {}, "checks": []})
        try:
            shots, raw_url = _upload_files(api, run_id, outcome)
            payload = {
                "channel": {"slug": ch.slug, "name": ch.name, "category": ch.category},
                "metrics": {**logo["metrics"], **outcome.metrics},
                "checks": logo["checks"] + outcome.checks,
                "screenshots": shots,
            }
            if outcome.error:
                payload["error"] = outcome.error
            if raw_url:
                payload["rawBufferUrl"] = raw_url
            api.upload_channel(run_id, payload)
        except ApiError as e:
            log.error("upload of %s failed: %s", ch.slug, e)
            with lock:
                failed.append(f"{ch.slug}: {e}")

    try:
        if m.report["pages"]:  # empty for guide-only measurements
            api.upload_images(run_id, {"pages": m.report["pages"], "checks": m.report["checks"]})
        if measure_players is None:
            for ch in m.channels:
                upload_channel(ChannelOutcome(ch))
        else:
            measure_players(m.channels, upload_channel)
    except ApiError as e:
        log.error("upload failed: %s (results kept in %s)", e, saved)
        _safe_finish(api, run_id, "failed", f"upload failed: {e}")
        raise
    except BaseException as e:
        log.exception("player measurement failed")
        _safe_finish(api, run_id, "failed", f"player measurement failed: {e}")
        raise

    entries = [{"level": "error", "msg": f"channel upload failed: {f}"[:500]} for f in failed[:50]]
    done = api.finish_run(run_id, {"status": "completed", **({"log": entries} if entries else {})})
    return {"runId": run_id, "counts": done.get("counts", {}), "saved": str(saved), "failedUploads": failed}


def _safe_finish(api: ApiClient, run_id: str, status: str, msg: str) -> None:
    try:
        api.finish_run(run_id, {"status": status, "log": [{"level": "error", "msg": msg[:500]}]})
    except Exception as e:
        log.warning("could not close run %s: %s", run_id, e)
