from __future__ import annotations

from dataclasses import dataclass

import httpx

from pippo.config import Settings


@dataclass(frozen=True)
class PrecheckResult:
    ok: bool
    selected: str | None
    detected: str | None
    detail: str


def detect_ip_country(settings: Settings, client: httpx.Client | None = None) -> str:
    """Country code of the agent's public IP, from the configured geolocation provider."""
    own = client is None
    client = client or httpx.Client(timeout=settings.geoip_timeout_sec)
    try:
        resp = client.get(settings.geoip_url)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if own:
            client.close()
    country = data.get("country") or data.get("country_code") or data.get("countryCode")
    if not country:
        raise ValueError(f"geolocation response has no country field: {list(data)}")
    return str(country).upper()


def compare_countries(selected: str | None, detected: str | None) -> PrecheckResult:
    """FR-3: the run is allowed only when the detected country equals the selected one.

    The Pluto-resolved country (second source in the architecture doc) is added in step
    0.5 once discovery has found the bootstrap call; until then only the IP source is used.
    """
    if not selected:
        return PrecheckResult(False, None, detected, "no country selected in the web app")
    if not detected:
        return PrecheckResult(False, selected, None, "could not detect the current country")
    if selected.upper() != detected.upper():
        return PrecheckResult(False, selected, detected, f"selected {selected} but detected {detected}")
    return PrecheckResult(True, selected, detected, f"detected country matches {selected}")