"""Discovery mode: map how pluto.tv behaves for a country (docs/02-ARCHITECTURE.md §2.5).

Opens the country's entry page in the installed Google Chrome, records every network call
and a structural dump of the DOM, takes screenshots, and writes everything to
``agent/discovery/<country>/<timestamp>/``. A draft ``pluto_profile.yaml`` is derived from
what was seen; selectors always need human review.

The module only observes: it never clicks consent banners, logs in or changes any state.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

from pippo import __version__
from pippo.browser import open_context
from pippo.config import AGENT_DIR

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 400_000
STREAM_RE = re.compile(r"\.(m3u8|mpd)(\?|$)", re.I)
GUIDE_HINTS = ("guide", "timeline", "channels", "epg", "schedule")
BOOT_HINTS = ("boot", "session", "geo", "region", "config")

# DOM structure dump, evaluated in the page.
DOM_SCRIPT = """
() => {
  const count = (arr) => arr.reduce((m, k) => (k ? (m[k] = (m[k] || 0) + 1, m) : m), {});
  const all = [...document.querySelectorAll('*')];
  const imgs = [...document.images];
  return {
    title: document.title,
    url: location.href,
    lang: document.documentElement.lang,
    elementCount: all.length,
    testIds: count(all.map(e => e.getAttribute('data-testid'))),
    roles: count(all.map(e => e.getAttribute('role'))),
    ariaLabels: Object.entries(count(all.map(e => e.getAttribute('aria-label')))).slice(0, 80),
    headings: [...document.querySelectorAll('h1,h2,h3')].slice(0, 60).map(h => h.tagName + ': ' + h.innerText.trim().slice(0, 80)),
    links: count([...document.querySelectorAll('a[href]')].map(a => {
      try { const u = new URL(a.href); return u.pathname.split('/').slice(0, 4).join('/'); } catch { return null; }
    })),
    images: {
      total: imgs.length,
      broken: imgs.filter(i => i.complete && i.naturalWidth === 0).length,
      hosts: count(imgs.map(i => { try { return new URL(i.currentSrc || i.src).host; } catch { return null; } })),
      sample: imgs.slice(0, 12).map(i => ({ src: i.currentSrc || i.src, w: i.naturalWidth, h: i.naturalHeight, alt: i.alt })),
    },
    videos: [...document.querySelectorAll('video')].map(v => ({
      src: v.currentSrc, paused: v.paused, readyState: v.readyState, textTracks: v.textTracks.length,
    })),
    consentHints: [...document.querySelectorAll('button,[role=button]')]
      .map(b => b.innerText.trim()).filter(t => /accept|agree|consent|cookie|accett|rifiut|reject/i.test(t)).slice(0, 10),
    iframes: [...document.querySelectorAll('iframe')].map(f => f.src).slice(0, 10),
  };
}
"""


@dataclass
class Recorder:
    out: Path
    requests: list[dict] = field(default_factory=list)
    console: list[dict] = field(default_factory=list)
    bodies: dict[str, str] = field(default_factory=dict)  # url -> file name

    def attach(self, page: Page) -> None:
        page.on("response", self._on_response)
        page.on("console", lambda m: self.console.append({"type": m.type, "text": m.text[:300]}))
        page.on("pageerror", lambda e: self.console.append({"type": "pageerror", "text": str(e)[:300]}))

    def _on_response(self, resp: Response) -> None:
        try:
            req = resp.request
            ctype = resp.headers.get("content-type", "")
            entry = {
                "t": round(time.time(), 2),
                "method": req.method,
                "url": resp.url,
                "status": resp.status,
                "type": req.resource_type,
                "contentType": ctype,
                "length": resp.headers.get("content-length"),
            }
            self.requests.append(entry)
            if req.resource_type in ("xhr", "fetch") and "json" in ctype:
                body = resp.body()[:MAX_BODY_BYTES]
                name = hashlib.sha1(resp.url.encode()).hexdigest()[:12] + ".json"
                (self.out / "api").mkdir(exist_ok=True)
                (self.out / "api" / name).write_bytes(body)
                self.bodies[resp.url] = name
                entry["bodyFile"] = name
        except Exception as e:  # the page may navigate away while a body is being read
            log.debug("response not recorded: %s", e)


def _safe_goto(page: Page, url: str, wait: float) -> None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as e:
        log.warning("navigation to %s: %s", url, e)
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    page.wait_for_timeout(int(wait * 1000))


def _scroll(page: Page, steps: int = 6) -> None:
    for _ in range(steps):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(800)
    page.evaluate("window.scrollTo(0, 0)")


def _snapshot(page: Page, out: Path, name: str, record: dict) -> None:
    """Capture DOM first (cheap, most valuable), then HTML, then the screenshot; each step may fail alone."""
    for label, step in (
        ("dom", lambda: record.__setitem__(name, page.evaluate(DOM_SCRIPT))),
        ("html", lambda: (out / f"{name}.html").write_text(page.content(), encoding="utf-8")),
        ("screenshot", lambda: page.screenshot(path=str(out / f"{name}.png"), timeout=60_000)),
    ):
        try:
            step()
        except Exception as e:
            log.warning("%s %s failed: %s", name, label, str(e).splitlines()[0])


def sanitize_url(url: str) -> str:
    """Drop the query string (it carries JWTs and device ids) but keep GraphQL operation names."""
    u = urlparse(url)
    q = dict(pair.split("=", 1) for pair in u.query.split("&") if "=" in pair)
    op = q.get("operationName")
    base = f"{u.scheme}://{u.netloc}{u.path}"
    return f"{base}?operationName={op}" if op else base


def summarize(requests: list[dict]) -> dict:
    hosts = Counter(urlparse(r["url"]).netloc for r in requests)
    api = [r for r in requests if r["type"] in ("xhr", "fetch")]
    api_paths = Counter(f"{r['method']} {urlparse(r['url']).netloc}{urlparse(r['url']).path}" for r in api)
    guide = sorted({sanitize_url(r["url"]) for r in api if any(h in r["url"].lower() for h in GUIDE_HINTS)})
    boot = sorted({sanitize_url(r["url"]) for r in api if any(h in r["url"].lower() for h in BOOT_HINTS)})
    streams = sorted({sanitize_url(r["url"]) for r in requests if STREAM_RE.search(r["url"])})
    failures = [r for r in requests if r["status"] >= 400]
    return {
        "requestCount": len(requests),
        "hosts": hosts.most_common(40),
        "apiEndpoints": api_paths.most_common(60),
        "guideCandidates": guide[:30],
        "bootstrapCandidates": boot[:30],
        "streamUrls": streams[:20],
        "failures": [{"status": r["status"], "url": sanitize_url(r["url"])} for r in failures[:40]],
    }


def draft_profile(country: str, entry_url: str, summary: dict, dom: dict) -> str:
    """Render a draft pluto_profile.yaml. Everything marked TODO must be confirmed by a human."""
    def lines(items: list[str], limit: int = 8) -> str:
        return "\n".join(f"    - \"{u}\"" for u in items[:limit]) or "    []"

    test_ids = dom.get("home", {}).get("testIds", {})
    top_ids = ", ".join(f"{k} ({v})" for k, v in sorted(test_ids.items(), key=lambda kv: -kv[1])[:15])
    return f"""# DRAFT generated by `pippo discover --country {country}` (agent {__version__}).
# Review every entry, remove noise, then save as pluto_profile.yaml.
country: {country}
entry_url: "{entry_url}"

# Network routes seen while loading the pages. Pick the real ones and turn the query
# strings into patterns (e.g. "/v2/channels"); the agent matches by substring.
routes:
  guide_candidates:
{lines(summary["guideCandidates"])}
  bootstrap_candidates:
{lines(summary["bootstrapCandidates"])}
  stream_examples:
{lines(summary["streamUrls"], 3)}

# Selectors: TODO. data-testid values found on the home page (most frequent first):
#   {top_ids or "none found"}
selectors:
  home_rail: null          # TODO
  channel_card: null       # TODO
  epg_grid: null           # TODO
  epg_row: null            # TODO
  epg_now_marker: null     # TODO
  player_video: "video"
  player_title: null       # TODO
  subtitle_text: null      # TODO
"""


def run_discovery(country: str, entry_url: str, headless: bool, extra_wait: float, out_root: Path | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = (out_root or AGENT_DIR / "discovery") / country / stamp
    out.mkdir(parents=True, exist_ok=True)
    dom: dict = {}
    with sync_playwright() as p:
        ctx: BrowserContext = open_context(p, country, headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            rec = Recorder(out)
            rec.attach(page)

            log.info("home: %s", entry_url)
            _safe_goto(page, entry_url, extra_wait)
            _snapshot(page, out, "home", dom)
            _scroll(page)
            _snapshot(page, out, "home_scrolled", dom)

            # Follow links the page itself offers for the live guide and a channel; nothing is clicked.
            hrefs = page.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.href)")
            guide_url = next((h for h in hrefs if re.search(r"/live-tv(/|$)", h)), None)
            if guide_url:
                log.info("guide: %s", guide_url)
                _safe_goto(page, guide_url, extra_wait + 3)
                _snapshot(page, out, "guide", dom)
                _scroll(page, 4)
                hrefs = page.evaluate("[...document.querySelectorAll('a[href]')].map(a => a.href)")
            chan_url = next((h for h in hrefs if re.search(r"/live-tv/\d+", h)), None)
            if chan_url:
                log.info("channel: %s", chan_url)
                _safe_goto(page, chan_url, extra_wait + 8)
                _snapshot(page, out, "channel", dom)
                page.wait_for_timeout(10_000)
                try:
                    page.screenshot(path=str(out / "channel_after10s.png"), timeout=60_000)
                except Exception as e:
                    log.warning("channel_after10s screenshot failed: %s", str(e).splitlines()[0])
                dom["channel_playback"] = page.evaluate(DOM_SCRIPT)["videos"]
            dom["discoveredLinks"] = {"guide": guide_url, "channel": chan_url}
        finally:
            ctx.close()

    summary = summarize(rec.requests)
    (out / "requests.json").write_text(json.dumps(rec.requests, indent=1), encoding="utf-8")
    (out / "console.json").write_text(json.dumps(rec.console, indent=1), encoding="utf-8")
    (out / "dom.json").write_text(json.dumps(dom, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out / "pluto_profile.draft.yaml").write_text(draft_profile(country, entry_url, summary, dom), encoding="utf-8")
    log.info("discovery written to %s", out)
    return out
