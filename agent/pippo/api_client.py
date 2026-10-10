from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx

from pippo import __version__
from pippo.config import Settings

log = logging.getLogger(__name__)

RETRY_STATUS = {408, 429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ApiClient:
    """Thin client for the web app's agent API (docs/02-ARCHITECTURE.md §3.2).

    Every request carries the Bearer key and a dedicated User-Agent. Transient failures
    (network errors, 408/429/5xx) are retried with exponential backoff; other 4xx raise
    ApiError immediately.
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._s = settings
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=settings.api_base_url,
            timeout=settings.http_timeout_sec,
            transport=transport,
            headers={
                "Authorization": f"Bearer {settings.agent_api_key}",
                "User-Agent": f"PippoAgent/{__version__} (+QoE monitor)",
            },
        )

    def close(self) -> None:
        self._http.close()

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        attempts = self._s.http_retries + 1
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                resp = self._http.request(method, path, **kwargs)
                if resp.status_code in RETRY_STATUS:
                    last = ApiError(f"{method} {path} -> {resp.status_code}", resp.status_code)
                elif resp.status_code >= 400:
                    raise ApiError(f"{method} {path} -> {resp.status_code}: {resp.text[:200]}", resp.status_code)
                else:
                    return resp
            except httpx.TransportError as e:
                last = ApiError(f"{method} {path} failed: {e}")
            if attempt < attempts - 1:
                delay = self._s.http_backoff_base_sec * (2**attempt)
                log.warning("%s (attempt %d/%d), retrying in %.1fs", last, attempt + 1, attempts, delay)
                self._sleep(delay)
        assert last is not None
        raise last

    def heartbeat(self, payload: dict) -> dict:
        """POST /api/agent/heartbeat. Response: {activeCountry, pollIntervalSec?}."""
        return self.request("POST", "/api/agent/heartbeat", json=payload).json()

    def create_run(self, payload: dict) -> dict:
        """POST /api/agent/runs. Response: {id, status} where status is "running" or "blocked"."""
        return self.request("POST", "/api/agent/runs", json=payload).json()

    def upload_channel(self, run_id: str, payload: dict) -> dict:
        return self.request("POST", f"/api/agent/runs/{run_id}/channels", json=payload).json()

    def upload_images(self, run_id: str, payload: dict) -> dict:
        return self.request("POST", f"/api/agent/runs/{run_id}/images", json=payload).json()

    def finish_run(self, run_id: str, payload: dict | None = None) -> dict:
        return self.request("POST", f"/api/agent/runs/{run_id}/finish", json=payload or {}).json()

    def upload_file(self, run_id: str, kind: str, name: str, data: bytes, content_type: str) -> dict:
        """POST /api/agent/upload (max 4 MB). Returns {url, pathname}."""
        return self.request(
            "POST",
            "/api/agent/upload",
            params={"runId": run_id, "kind": kind, "name": name},
            content=data,
            headers={"Content-Type": content_type},
        ).json()

    def next_jobs(self, wait: bool = True) -> list[dict]:
        """GET /api/agent/jobs: pending on-demand jobs, oldest first. Long-polls up to ~20 s when `wait`."""
        params = {} if wait else {"wait": "0"}
        return self.request("GET", "/api/agent/jobs", params=params).json().get("jobs", [])

    def ack_job(self, job_id: str) -> None:
        """POST /api/agent/jobs/:id/ack. Raises ApiError(409) when another caller already took the job."""
        self.request("POST", f"/api/agent/jobs/{job_id}/ack")

