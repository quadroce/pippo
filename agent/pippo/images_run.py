"""Runs the images probe on the home page and the live guide and writes a JSON report."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from pippo import __version__
from pippo.browser import open_context, robot_user_agent
from pippo.config import AGENT_DIR
from pippo.probes.images import (
    NetworkImages,
    PageImages,
    compute_checks,
    crawl_page,
    fetch_hashes,
    load_placeholder_hashes,
)
from pippo.profile import Profile

log = logging.getLogger(__name__)

PAGES = (("home", "home"), ("epg", "live_tv"))  # (report name, profile page key)


def run_images(country: str, headless: bool, out_dir: Path | None = None, profile: Profile | None = None) -> tuple[dict, Path]:
    profile = profile or Profile.load()
    if profile.country != country:
        raise SystemExit(f"pluto_profile.yaml is for {profile.country}, not {country}")

    pages: list[PageImages] = []
    ua = f"PippoAgent/{__version__}"
    with sync_playwright() as p:
        ctx = open_context(p, country, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ua = page.evaluate("navigator.userAgent")
            net = NetworkImages(page)
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

    out_dir = out_dir or AGENT_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"images-{country}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report, out
