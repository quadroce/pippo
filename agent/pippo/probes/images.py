"""Images & artwork probe (docs/03-CHECK-CATALOG.md section A).

Two layers: a browser layer that crawls a page and collects an image inventory, and a pure
layer (`compute_checks`) that turns inventories into metrics and check results. The pure
layer is what the unit tests cover.
"""

from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx
from playwright.sync_api import Page, Response

from pippo.config import AGENT_DIR
from pippo.thresholds import Threshold, grade

log = logging.getLogger(__name__)

ASPECT_TOLERANCE = 0.05
HAMMING_PLACEHOLDER = 6
PLACEHOLDER_DIR = AGENT_DIR / "placeholders"

# Expected natural aspect ratio (w/h) per card type, inferred from the artwork URL.
EXPECTED_RATIO = {"thumb_16_9": 16 / 9, "poster_2_3": 2 / 3}

COLLECT_JS = r"""
() => {
  const out = [];
  const near = (el) => { const t = el.closest('[data-testid]'); return t ? t.getAttribute('data-testid') : null; };
  for (const i of document.images) {
    const r = i.getBoundingClientRect();
    out.push({kind: 'img', src: i.currentSrc || i.src, nw: i.naturalWidth, nh: i.naturalHeight,
      rw: r.width, rh: r.height, fit: getComputedStyle(i).objectFit, complete: i.complete,
      alt: i.alt || '', ctx: near(i), shown: r.width > 0 && r.height > 0});
  }
  for (const el of document.querySelectorAll('*')) {
    const bg = getComputedStyle(el).backgroundImage;
    if (!bg || bg === 'none') continue;
    const m = bg.match(/url\(["']?(.*?)["']?\)/);
    if (!m || m[1].startsWith('data:')) continue;
    const r = el.getBoundingClientRect();
    out.push({kind: 'bg', src: m[1], nw: 0, nh: 0, rw: r.width, rh: r.height, fit: 'cover',
      complete: true, alt: '', ctx: near(el), shown: r.width > 0 && r.height > 0});
  }
  return out;
}
"""

PENDING_IN_VIEWPORT_JS = """
() => [...document.images].filter(i => {
  const r = i.getBoundingClientRect();
  return r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth && r.width > 0 && !i.complete;
}).length
"""

# Scroll every horizontally scrollable container (carousels) to its end, in steps.
SCROLL_CAROUSELS_JS = """
async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const boxes = [...document.querySelectorAll('*')].filter(e => {
    const s = getComputedStyle(e);
    return (s.overflowX === 'auto' || s.overflowX === 'scroll') && e.scrollWidth > e.clientWidth + 50;
  });
  for (const b of boxes) {
    for (let x = 0; x < b.scrollWidth; x += Math.max(300, b.clientWidth * 0.8)) {
      b.scrollTo(x, 0); await sleep(120);
    }
    b.scrollTo(0, 0);
  }
  return boxes.length;
}
"""


@dataclass
class ImageItem:
    kind: str
    src: str
    nw: int
    nh: int
    rw: float
    rh: float
    fit: str
    complete: bool
    alt: str
    ctx: str | None
    shown: bool
    status: int | None = None       # HTTP status from the network layer, when seen
    transfer: int | None = None     # bytes transferred
    content_type: str | None = None
    failed: bool = False            # request failed at network level


@dataclass
class PageImages:
    name: str
    url: str
    items: list[ImageItem]
    lazy_load_max_sec: float = 0.0
    load_error: str | None = None


def card_type(src: str) -> str:
    path = urlparse(src).path.lower()
    if re.search(r"(solid|color)logo", path):
        return "logo"
    if "16_9" in path or "screenshot" in path:
        return "thumb_16_9"
    if re.search(r"2_3|poster", path):
        return "poster_2_3"
    return "other"


def is_broken(it: ImageItem) -> bool:
    if it.failed or (it.status is not None and it.status >= 400):
        return True
    return it.kind == "img" and it.shown and it.complete and it.nw == 0


def aspect_problem(it: ImageItem) -> str | None:
    """Return a description when the artwork or its rendering has the wrong proportions."""
    if it.kind != "img" or it.nw <= 0 or it.nh <= 0:
        return None
    natural = it.nw / it.nh
    expected = EXPECTED_RATIO.get(card_type(it.src))
    if expected and abs(natural - expected) / expected > ASPECT_TOLERANCE:
        return f"natural ratio {natural:.2f} vs expected {expected:.2f}"
    if it.shown and it.rh > 0 and it.fit in ("fill", ""):
        rendered = it.rw / it.rh
        if abs(rendered - natural) / natural > ASPECT_TOLERANCE:
            return f"rendered ratio {rendered:.2f} vs natural {natural:.2f}"
    return None


# --- Placeholder library ----------------------------------------------------------------------

def load_placeholder_hashes(directory: Path = PLACEHOLDER_DIR) -> list:
    """pHashes of known fallback images (agent/placeholders/*.png|jpg|webp). Empty if none."""
    import imagehash
    from PIL import Image

    hashes = []
    for f in sorted(directory.glob("*")) if directory.exists() else []:
        if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            hashes.append((f.name, imagehash.phash(Image.open(f))))
    return hashes


def hash_image_bytes(data: bytes):
    import imagehash
    from PIL import Image

    return imagehash.phash(Image.open(io.BytesIO(data)))


def fetch_hashes(urls: list[str], client: httpx.Client, limit: int = 400) -> dict:
    """Download unique image URLs and compute their pHash. Failures map to None."""
    out: dict = {}
    for u in urls[:limit]:
        try:
            r = client.get(u)
            r.raise_for_status()
            out[u] = hash_image_bytes(r.content)
        except Exception as e:
            log.debug("hash failed for %s: %s", u, e)
            out[u] = None
    return out


# --- Pure computation -------------------------------------------------------------------------

def _check(check_id: str, value: float, overrides, detail: str = "", scope: str = "") -> dict:
    severity, crossed = grade(check_id, value, overrides)
    return {
        "checkId": check_id,
        "scope": scope,
        "severity": severity if severity != "ok" else "info",
        "passed": severity == "ok",
        "value": value,
        "threshold": crossed,
        "detail": detail,
    }


def compute_checks(
    pages: list[PageImages],
    hashes: dict | None = None,
    placeholders: list | None = None,
    overrides: dict[str, Threshold] | None = None,
) -> dict:
    """Metrics and check results per page. `hashes` maps URL -> pHash, `placeholders` is [(name, hash)]."""
    hashes = hashes or {}
    placeholders = placeholders or []
    result: dict = {"pages": {}, "checks": []}

    for pg in pages:
        shown = [i for i in pg.items if i.shown or i.kind == "img"]
        total = len(shown)
        broken = [i for i in shown if is_broken(i)]
        aspect = [(i, p) for i in shown if (p := aspect_problem(i))]

        placeholder_urls = []
        for i in shown:
            h = hashes.get(i.src)
            if h is not None and any(h - ph <= HAMMING_PLACEHOLDER for _, ph in placeholders):
                placeholder_urls.append(i.src)

        # Bytes per rendered pixel; > 2 B/px is far above what a compressed 8-bit image needs.
        oversized = [i for i in shown if i.transfer and i.rw > 0 and i.rh > 0 and i.transfer / (i.rw * i.rh) > 2.0]
        by_type: dict[str, int] = {}
        for i in shown:
            by_type[card_type(i.src)] = by_type.get(card_type(i.src), 0) + 1

        metrics = {
            "img.total_count": total,
            "img.broken_ratio": len(broken) / total if total else 0.0,
            "img.placeholder_ratio": len(placeholder_urls) / total if total else 0.0,
            "img.aspect_mismatch": len(aspect),
            "img.lazy_load_timeout": pg.lazy_load_max_sec,
            "img.oversized_payload": len(oversized),
            "by_type": by_type,
        }
        result["pages"][pg.name] = {"url": pg.url, "metrics": metrics, "loadError": pg.load_error}

        scope = pg.name
        placeholder_note = (
            f"library: {len(placeholders)} known placeholders" if placeholders else "no placeholder library configured"
        )
        result["checks"] += [
            _check("img.broken_ratio", metrics["img.broken_ratio"], overrides,
                   "; ".join(sorted({i.src for i in broken})[:5]), scope),
            _check("img.placeholder_ratio", metrics["img.placeholder_ratio"], overrides, placeholder_note, scope),
            _check("img.aspect_mismatch", metrics["img.aspect_mismatch"], overrides,
                   "; ".join(f"{p} ({i.src.rsplit('/', 2)[-2]})" for i, p in aspect[:5]), scope),
            _check("img.lazy_load_timeout", metrics["img.lazy_load_timeout"], overrides, "", scope),
        ]
    return result


# --- Browser layer ----------------------------------------------------------------------------

class NetworkImages:
    """Collects status, size and failures of image requests while a page loads."""

    def __init__(self, page: Page):
        self.by_url: dict[str, dict] = {}
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_failed)

    def _on_response(self, resp: Response) -> None:
        if resp.request.resource_type != "image":
            return
        size = resp.headers.get("content-length")
        self.by_url[resp.url] = {
            "status": resp.status,
            "transfer": int(size) if size and size.isdigit() else None,
            "ctype": resp.headers.get("content-type"),
        }

    def _on_failed(self, req) -> None:
        if req.resource_type == "image":
            self.by_url.setdefault(req.url, {})["failed"] = True


def _settle(page: Page, timeout: float = 8.0) -> float:
    """Seconds until every image in the viewport has finished loading (capped at timeout)."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if page.evaluate(PENDING_IN_VIEWPORT_JS) == 0:
            return time.monotonic() - start
        page.wait_for_timeout(250)
    return timeout


def _collect(page: Page, net: NetworkImages) -> list[ImageItem]:
    items = []
    for raw in page.evaluate(COLLECT_JS):
        it = ImageItem(
            kind=raw["kind"], src=raw["src"], nw=raw["nw"], nh=raw["nh"], rw=raw["rw"], rh=raw["rh"],
            fit=raw["fit"], complete=raw["complete"], alt=raw["alt"], ctx=raw["ctx"], shown=raw["shown"],
        )
        info = net.by_url.get(it.src)
        if info:
            it.status, it.transfer, it.content_type = info.get("status"), info.get("transfer"), info.get("ctype")
            it.failed = bool(info.get("failed"))
        items.append(it)
    return items


def merge_into(seen: dict, items: list[ImageItem]) -> None:
    """Union of inventories across scroll steps (virtualized lists drop rows from the DOM).

    One entry per (kind, src). A broken observation is sticky: if an image was ever seen broken
    it stays broken, otherwise the latest loaded observation wins.
    """
    for it in items:
        key = (it.kind, it.src)
        prev = seen.get(key)
        if prev is None or is_broken(it) or (it.complete and it.nw > 0 and not is_broken(prev)):
            seen[key] = it


def crawl_page(
    page: Page,
    net: NetworkImages,
    name: str,
    url: str,
    settle_wait: float = 3.0,
    progress: Callable[[str], None] = lambda m: None,
) -> PageImages:
    """Open a page, scroll vertically to the end and every carousel to its end, inventory all images."""
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception as e:
        return PageImages(name, url, [], load_error=f"navigation failed: {str(e).splitlines()[0]}")
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    page.wait_for_timeout(int(settle_wait * 1000))

    lazy_max = 0.0
    last_height = -1
    steps = 0
    seen: dict[tuple[str, str], ImageItem] = {}
    for steps in range(1, 41):  # hard cap: ~40 viewports
        page.mouse.wheel(0, 900)
        lazy_max = max(lazy_max, _settle(page))
        merge_into(seen, _collect(page, net))
        height = page.evaluate("document.documentElement.scrollHeight")
        at_bottom = page.evaluate("window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4")
        if at_bottom and height == last_height:
            break
        last_height = height
    progress(f"{name}: scrolled {steps} steps")
    page.evaluate("window.scrollTo(0, 0)")
    n_boxes = page.evaluate(SCROLL_CAROUSELS_JS)
    progress(f"{name}: {n_boxes} carousels scrolled")
    page.wait_for_timeout(1500)
    lazy_max = max(lazy_max, _settle(page))

    merge_into(seen, _collect(page, net))
    items = list(seen.values())
    return PageImages(name, page.url, items, lazy_load_max_sec=round(lazy_max, 2))
