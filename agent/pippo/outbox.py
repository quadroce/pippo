"""Offline outbox: channel results that could not be uploaded wait here and are sent later.

The measurement of a channel is expensive (a minute of browser time) and the network or the web app can
be down for a while, so a result that cannot be uploaded is written to ``agent/outbox/`` instead of
being given up on. The agent retries on every heartbeat and ``pippo flush`` does it on demand. The web
app accepts late channel results for a run that has already been closed.

Entries the server refuses for good (the run is gone, the body is invalid) are moved to
``outbox/rejected/`` with the reason, and entries older than a week are dropped, so the folder cannot
grow without bound.
"""

from __future__ import annotations

import gzip
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from pippo.api_client import ApiClient, ApiError
from pippo.config import AGENT_DIR

log = logging.getLogger(__name__)

MAX_AGE_DAYS = 7
MAX_UPLOAD_BYTES = 4 * 1024 * 1024
PERMANENT_STATUS = {400, 404, 409, 413, 415, 422}  # retrying cannot help


def is_permanent(error: ApiError) -> bool:
    return error.status in PERMANENT_STATUS


@dataclass
class FlushResult:
    sent: int = 0
    kept: int = 0
    rejected: int = 0
    dropped: int = 0
    errors: list[str] = field(default_factory=list)


class Outbox:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or AGENT_DIR / "outbox"

    def add(self, run_id: str, slug: str, payload: dict, screenshots: list[dict], raw_path: str | None) -> Path:
        """Queue one channel result. `screenshots` are local files ({tOffsetSec, kind, path}) still to upload."""
        self.dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "runId": run_id,
            "slug": slug,
            "createdAt": time.time(),
            "attempts": 0,
            "payload": payload,
            "screenshots": screenshots,
            "rawPath": raw_path,
        }
        path = self.dir / f"{int(time.time())}-{run_id[:8]}-{slug}-{uuid.uuid4().hex[:6]}.json"
        path.write_text(json.dumps(entry), encoding="utf-8")
        return path

    def pending(self, run_id: str | None = None) -> list[tuple[Path, dict]]:
        out = []
        for f in sorted(self.dir.glob("*.json")) if self.dir.exists() else []:
            try:
                entry = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._reject(f, "unreadable entry")
                continue
            if run_id is None or entry.get("runId") == run_id:
                out.append((f, entry))
        return out

    def count(self) -> int:
        return len(list(self.dir.glob("*.json"))) if self.dir.exists() else 0

    def _reject(self, path: Path, reason: str) -> None:
        target = self.dir / "rejected"
        target.mkdir(parents=True, exist_ok=True)
        try:
            path.replace(target / path.name)
            (target / (path.name + ".reason.txt")).write_text(reason, encoding="utf-8")
        except OSError as e:
            log.warning("could not move %s to rejected: %s", path.name, e)


def _upload_evidence(api: ApiClient, run_id: str, slug: str, entry: dict) -> tuple[list[dict], str | None]:
    """(Re)upload the screenshots and raw buffer of an entry from their local files. Missing files are skipped."""
    shots, raw_url = [], None
    for s in entry.get("screenshots", []):
        p = Path(s["path"])
        if not p.exists():
            continue
        data = p.read_bytes()
        if len(data) <= MAX_UPLOAD_BYTES:
            up = api.upload_file(run_id, "screenshot", f"{slug}-t{s['tOffsetSec']}-{s['kind']}.png", data, "image/png")
            shots.append({"tOffsetSec": int(s["tOffsetSec"]), "kind": s["kind"], "blobUrl": up["url"]})
    raw = entry.get("rawPath")
    if raw and Path(raw).exists():
        gz = gzip.compress(Path(raw).read_bytes())
        if len(gz) <= MAX_UPLOAD_BYTES:
            raw_url = api.upload_file(run_id, "raw", f"{slug}-buffer.json.gz", gz, "application/gzip")["url"]
    return shots, raw_url


def flush(api: ApiClient, outbox: Outbox, run_id: str | None = None, limit: int = 25, now: float | None = None) -> FlushResult:
    """Send queued results. Stops at the first transient failure: the network is probably still down."""
    now = now or time.time()
    result = FlushResult()
    for path, entry in outbox.pending(run_id)[:limit]:
        if now - float(entry.get("createdAt", now)) > MAX_AGE_DAYS * 86_400:
            path.unlink(missing_ok=True)
            result.dropped += 1
            continue
        try:
            payload = dict(entry["payload"])
            # Evidence that failed before is retried here; if the store refuses again the result still goes up without it.
            try:
                shots, raw_url = _upload_evidence(api, entry["runId"], entry["slug"], entry)
                payload["screenshots"] = shots
                if raw_url:
                    payload["rawBufferUrl"] = raw_url
            except ApiError as e:
                if not is_permanent(e) and e.status in (None, 408, 429, 500, 502, 503, 504):
                    raise
                log.warning("%s: evidence not uploaded (%s), sending the result without it", entry["slug"], e)
            api.upload_channel(entry["runId"], payload)
        except ApiError as e:
            if is_permanent(e):
                outbox._reject(path, str(e))
                result.rejected += 1
                result.errors.append(f"{entry['slug']}: {e}")
                continue
            entry["attempts"] = int(entry.get("attempts", 0)) + 1
            path.write_text(json.dumps(entry), encoding="utf-8")
            result.errors.append(f"{entry['slug']}: {e}")
            break
        path.unlink(missing_ok=True)
        result.sent += 1
    result.kept = len(outbox.pending(run_id))   # what is still waiting
    return result
