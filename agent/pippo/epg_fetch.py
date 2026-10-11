"""Fetches the full programme listings of every channel from Pluto's own guide API.

The guide page asks for the first five upcoming programmes only, and loads more per channel
(`Listing` GraphQL operation, 50 at a time) when the row is scrolled horizontally. To judge the
data and not just what happens to be on screen, the probe asks for the same `Listing` pages the
page itself would, from inside the browser (same cookies and headers) and a few at a time.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse as up
from dataclasses import dataclass, field

from playwright.sync_api import Page

from pippo.guide import GuideChannel
from pippo.profile import Profile

log = logging.getLogger(__name__)

# Apollo rejects GET requests without one of these as a CSRF precaution; the page's own client sends them.
APOLLO_HEADERS = {"x-apollo-operation-name": "Listing", "apollo-require-preflight": "true"}
PAGE_ROWS = 50
MAX_PAGES_PER_CHANNEL = 6


@dataclass
class EpgFetch:
    listings: dict[str, list[dict]] = field(default_factory=dict)  # slug -> raw listing dicts
    failures: list[str] = field(default_factory=list)

    @property
    def error(self) -> str | None:
        if not self.failures:
            return None
        return f"{len(self.failures)} guide request(s) failed, first: {self.failures[0]}"


def capture_template(page: Page, wait_ms: int = 4000) -> str | None:
    """URL of a real `Listing` request, triggered by scrolling a channel row into the future."""
    seen: list[str] = []
    page.on("request", lambda r: seen.append(r.url) if "operationName=Listing" in r.url else None)
    try:
        page.evaluate(
            """() => { for (const e of document.querySelectorAll('*')) { const s = getComputedStyle(e);
              if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && e.scrollWidth > e.clientWidth + 200) e.scrollTo(e.scrollWidth, 0); } }"""
        )
    except Exception as e:
        log.debug("could not scroll the guide to capture a Listing request: %s", e)
    page.wait_for_timeout(wait_ms)
    return seen[0] if seen else None


def fallback_template(profile: Profile) -> str | None:
    """Build a Listing URL from the hash stored in the profile when no request could be captured."""
    routes = profile.data.get("routes", {})
    digest = routes.get("listing_hash")
    if not digest:
        return None
    variables = {
        "channelSlug": "x",
        "params": {
            "userRegistrationCountry": profile.country,
            "userState": "ANONYMOUS",
            "packageCode": "NEW_FREE_PACKAGE",
            "userProfileType": "ADULT",
            "billingVendor": "cbscomp",
            "isPreviewMode": False,
            "rows": PAGE_ROWS,
            "start": 0,
        },
    }
    query = {
        "operationName": "Listing",
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({"tnPersistedDocumentHash": digest}, separators=(",", ":")),
    }
    return "https://pluto.tv/api/tn/video/graphql/?" + up.urlencode(query)


def _url_for(template: str, slug: str, start: int) -> str:
    parts = up.urlparse(template)
    q = dict(up.parse_qsl(parts.query))
    v = json.loads(q["variables"])
    v["channelSlug"] = slug
    v["params"]["rows"] = PAGE_ROWS
    v["params"]["start"] = start
    q["variables"] = json.dumps(v, separators=(",", ":"))
    return up.urlunparse(parts._replace(query=up.urlencode(q)))


def fetch_listings(
    page: Page,
    template: str,
    channels: list[GuideChannel],
    horizon_hours: float = 12.0,
    now_ms: int | None = None,
    request_timeout_ms: int = 20_000,
) -> EpgFetch:
    """Page through each channel's listings until `horizon_hours` ahead are covered or the list ends."""
    now_ms = now_ms or int(time.time() * 1000)
    horizon = now_ms + int(horizon_hours * 3_600_000)
    out = EpgFetch()
    for ch in channels:
        collected: list[dict] = []
        start = 0
        for _ in range(MAX_PAGES_PER_CHANNEL):
            try:
                resp = page.request.get(_url_for(template, ch.slug, start), headers=APOLLO_HEADERS, timeout=request_timeout_ms)
                if resp.status >= 400:
                    out.failures.append(f"{ch.slug}: HTTP {resp.status}")
                    break
                data = (resp.json().get("data") or {}).get("listings")
            except Exception as e:
                out.failures.append(f"{ch.slug}: {str(e).splitlines()[0][:100]}")
                break
            if not data:
                out.failures.append(f"{ch.slug}: empty or invalid response")
                break
            batch = data.get("listing") or []
            collected += batch
            total = data.get("total") or 0
            start += PAGE_ROWS
            last_end = max((int(b.get("endTimestamp") or 0) for b in batch), default=0)
            if not batch or start >= total or last_end >= horizon:
                break
        if collected:
            out.listings[ch.slug] = collected
    return out
