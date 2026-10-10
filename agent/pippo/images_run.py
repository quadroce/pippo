"""Measures images on the home page and the live guide; also captures the guide's channel list."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from pippo import __version__
from pippo.browser import open_context
from pippo.config import AGENT_DIR
from pippo.guide import GuideCapture, GuideChannel
from pippo.probes.images import (
    NetworkImages,
    PageImages,
    compute_checks,
    crawl_page,
    fetch_hashes,
    load_placeholder_hashes,
)
from pippo.probes.logos import channel_logo_checks
from pippo.profile import Profile

log = logging.getLogger(__name__)

PAGES = (("home", "home"), ("epg", "live_tv"))  # (report name, profile page key)


@dataclass
class Measurement:
    report: dict                       # page-level images result: {pages, checks, ...}
    channels: list[GuideChannel]
    channel_results: dict[str, dict]   # slug -> {metrics, checks}
    guide_total: int | None


def measure(country: str, headless: bool, profile: Profile | None = None) -> Measurement:
    profile = profile or Profile.load()
    if profile.country != country:
        raise SystemExit(f"pluto_profile.yaml is for {profile.country}, not {country}")

    pages: list[PageImages] = []
    ua = f"PippoAgent/{__version__}"
    guide = GuideCapture(route=profile.data["routes"]["guide"].split("?")[0])
    with sync_playwright() as p:
        ctx = open_context(p, country, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ua = page.evaluate("navigator.userAgent")
            net = NetworkImages(page)
            guide.attach(page)
            for name, key in PAGES:
                url = profile.page_url(key)
                log.info("crawling %s: %s", name, url)
                pages.append(crawl_page(page, net, name, url, progress=log.info))
        finally:
            ctx.close()

    urls = sorted({i.src for pg in pages for i in pg.items if i.kind == "img" and i.src.startswith("http")})
    placeholders = load_placeholder_hashes()
    hashes: dict = {}
    if placeholders:
        log.info("hashing %d images against %d placeholders", len(urls), len(placeholders))
        with httpx.Client(timeout=20, headers={"User-Agent": ua}) as client:
            hashes = fetch_hashes(urls, client)
    else:
        log.info("no placeholder library in agent/placeholders/: placeholder check skipped")

    report = compute_checks(pages, hashes, placeholders)
    report.update(country=country, agentVersion=__version__, measuredAt=datetime.now().astimezone().isoformat())

    channels = sorted(guide.channels.values(), key=lambda c: c.name.lower())
    if guide.total is not None and len(channels) < guide.total:
        log.warning("guide lists %d channels but only %d were captured while scrolling", guide.total, len(channels))
    epg = next((pg for pg in pages if pg.name == "epg"), None)
    logo = channel_logo_checks(channels, epg.items if epg else [])
    return Measurement(report, channels, logo, guide.total)


def run_images(country: str, headless: bool, out_dir: Path | None = None, profile: Profile | None = None) -> tuple[dict, Path]:
    """CLI helper (`pippo images`): measure and write the JSON report locally, nothing is uploaded."""
    m = measure(country, headless, profile)
    out_dir = out_dir or AGENT_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"images-{country}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(m.report, indent=1), encoding="utf-8")
    return m.report, out
