"""Measures images on the home page and the live guide; also captures the guide's channel list."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

from pippo import __version__
from pippo.browser import open_context
from pippo.config import AGENT_DIR
from pippo.epg_fetch import capture_template, fallback_template, fetch_listings
from pippo.guide import GuideCapture, GuideChannel
from pippo.health import SelectorHealthError, guide_selectors, missing_on_page
from pippo.probes.images import (
    NetworkImages,
    PageImages,
    compute_checks,
    crawl_page,
    fetch_hashes,
    load_placeholder_hashes,
)
from pippo.probes.epg import compute_epg, parse_listings
from pippo.probes.epg_render import RowCollector, compute_render
from pippo.probes.logos import channel_logo_checks
from pippo.profile import Profile
from pippo.thresholds import Threshold

log = logging.getLogger(__name__)

PAGES = (("home", "home"), ("epg", "live_tv"))  # (report name, profile page key)


@dataclass
class Measurement:
    report: dict                       # page-level images result: {pages, checks, ...}
    channels: list[GuideChannel]
    channel_results: dict[str, dict]   # slug -> {metrics, checks}
    guide_total: int | None
    epg: dict | None = None            # run-level EPG result {metrics, checks, issues}
    listings: dict | None = None       # slug -> parsed programme listings (for the player cross-check)
    epg_screenshot: Path | None = None  # picture of the guide as rendered, for the dashboard


def measure(
    country: str,
    headless: bool,
    profile: Profile | None = None,
    overrides: dict[str, Threshold] | None = None,
    guide_only: bool = False,
) -> Measurement:
    """Images checks on home and guide, plus the channel list.

    `guide_only` skips the images work and only loads the guide to learn the channels (used by
    on-demand tests that do not include images).
    """
    profile = profile or Profile.load()
    if profile.country != country:
        raise SystemExit(f"pluto_profile.yaml is for {profile.country}, not {country}")

    pages: list[PageImages] = []
    epg_fetch = None
    epg_shot: Path | None = None
    rows = RowCollector()
    ua = f"PippoAgent/{__version__}"
    guide = GuideCapture(route=profile.data["routes"]["guide"].split("?")[0])
    with sync_playwright() as p:
        ctx = open_context(p, country, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ua = page.evaluate("navigator.userAgent")
            net = NetworkImages(page)
            guide.attach(page)
            for name, key in (PAGES[1:] if guide_only else PAGES):
                url = profile.page_url(key)
                log.info("crawling %s: %s", name, url)
                pages.append(
                    crawl_page(page, net, name, url, progress=log.info, on_step=rows.step if name == "epg" else None)
                )
                if name == "epg":
                    missing = missing_on_page(page, guide_selectors(profile.data))
                    if missing:
                        raise SelectorHealthError("live guide", missing)
                if name == "epg" and not guide_only:
                    epg_shot = _screenshot_guide(page)
                    epg_fetch = _fetch_epg(page, profile, guide)
        finally:
            ctx.close()

    if guide_only:
        channels = sorted(guide.channels.values(), key=lambda c: c.name.lower())
        report = {"pages": {}, "checks": [], "country": country, "agentVersion": __version__}
        return Measurement(report, channels, {}, guide.total)

    urls = sorted({i.src for pg in pages for i in pg.items if i.kind == "img" and i.src.startswith("http")})
    placeholders = load_placeholder_hashes()
    hashes: dict = {}
    if placeholders:
        log.info("hashing %d images against %d placeholders", len(urls), len(placeholders))
        with httpx.Client(timeout=20, headers={"User-Agent": ua}) as client:
            hashes = fetch_hashes(urls, client)
    else:
        log.info("no placeholder library in agent/placeholders/: placeholder check skipped")

    report = compute_checks(pages, hashes, placeholders, overrides)
    report.update(country=country, agentVersion=__version__, measuredAt=datetime.now().astimezone().isoformat())

    channels = sorted(guide.channels.values(), key=lambda c: c.name.lower())
    if guide.total is not None and len(channels) < guide.total:
        log.warning("guide lists %d channels but only %d were captured while scrolling", guide.total, len(channels))
    epg = next((pg for pg in pages if pg.name == "epg"), None)
    logo = channel_logo_checks(channels, epg.items if epg else [], overrides)
    epg_result = None
    listings = None
    if epg_fetch is not None:
        parsed = {slug: parse_listings(raw) for slug, raw in epg_fetch.listings.items()}
        res = compute_epg(
            parsed,
            names={c.slug: c.name for c in channels},
            now_ms=int(time.time() * 1000),
            expected_language=profile.data.get("language"),
            api_error=epg_fetch.error,
            guide_total=guide.total,
            overrides=overrides,
        )
        render = compute_render(rows.rows, channels, parsed, rows.load_max_sec, overrides)
        epg_result = {
            "metrics": {**res["metrics"], **render["metrics"]},
            "checks": res["checks"] + render["checks"],
            "issues": (res["issues"] + render["issues"])[:300],
        }
        listings = parsed
        for slug, extra in {**res["channel_results"]}.items():
            mine = logo.setdefault(slug, {"metrics": {}, "checks": []})
            mine["metrics"].update(extra["metrics"])
            mine["checks"] += extra["checks"]
        for slug, extra in render["channel_checks"].items():
            mine = logo.setdefault(slug, {"metrics": {}, "checks": []})
            mine["metrics"].update(extra["metrics"])
            mine["checks"] += extra["checks"]
    return Measurement(report, channels, logo, guide.total, epg_result, listings, epg_shot)


def _screenshot_guide(page) -> Path | None:
    """Viewport picture of the guide (top of the list). Failure to take it never fails the measurement."""
    try:
        directory = AGENT_DIR / "reports"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"epg-guide-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
        page.screenshot(path=str(path), timeout=30_000)
        return path
    except Exception as e:
        log.warning("guide screenshot failed: %s", str(e).splitlines()[0])
        return None


def _fetch_epg(page, profile: Profile, guide: GuideCapture):
    """Programme listings of every channel the guide showed. Returns None when no request template exists."""
    template = capture_template(page) or fallback_template(profile)
    if not template:
        log.warning("no Listing request template: EPG data checks skipped")
        return None
    channels = sorted(guide.channels.values(), key=lambda c: c.name.lower())
    log.info("fetching programme listings for %d channels", len(channels))
    return fetch_listings(page, template, channels)


def run_images(country: str, headless: bool, out_dir: Path | None = None, profile: Profile | None = None) -> tuple[dict, Path]:
    """CLI helper (`pippo images`): measure and write the JSON report locally, nothing is uploaded."""
    m = measure(country, headless, profile)
    out_dir = out_dir or AGENT_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"images-{country}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(m.report, indent=1), encoding="utf-8")
    return m.report, out
