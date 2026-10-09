from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from pippo.api_client import ApiClient, ApiError
from pippo.config import Settings, validate_settings
from pippo.precheck import detect_ip_country

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def find_chrome() -> str | None:
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    return shutil.which("chrome") or shutil.which("google-chrome")


def run_doctor(settings: Settings) -> list[Check]:
    checks: list[Check] = []

    py_ok = sys.version_info >= (3, 12)
    checks.append(Check("python", py_ok, f"{sys.version.split()[0]} (3.12+ required)"))

    chrome = find_chrome()
    checks.append(Check("chrome", chrome is not None, chrome or "Google Chrome not found"))

    problems = validate_settings(settings)
    checks.append(Check("config", not problems, "; ".join(problems) or "API_BASE_URL and AGENT_API_KEY set"))

    try:
        country = detect_ip_country(settings)
        checks.append(Check("geolocation", True, f"IP country {country} via {settings.geoip_url}"))
    except Exception as e:  # network, bad JSON, missing field
        checks.append(Check("geolocation", False, str(e)))

    if problems:
        checks.append(Check("api", False, "skipped: fix config first"))
    else:
        client = ApiClient(settings)
        try:
            client.heartbeat({"agentVersion": "doctor", "probe": True})
            checks.append(Check("api", True, f"{settings.api_base_url} accepted the key"))
        except ApiError as e:
            hint = " (endpoint not deployed yet?)" if e.status == 404 else ""
            checks.append(Check("api", False, f"{e}{hint}"))
        finally:
            client.close()

    return checks