"""EPG rendering checks (docs/03-CHECK-CATALOG.md section C.2) and `player.now_playing_mismatch`.

What the live-guide page actually is (found with discovery on pluto.tv/it): a long vertical list of
channel rows, each row a horizontal carousel of programme tiles. The first tile is the programme
on air now, the next ones are upcoming. There is **no time axis and no "now" marker**, so the
catalog's `epg.now_marker_position` does not apply, and the timezone cannot be checked through a
marker either. What can be checked, and is: every API channel is rendered exactly once, the tile
highlighted as "now" matches the API's current programme, tiles are filled, and rows populate
quickly after a scroll.

The list is virtualized (rows leave the DOM when scrolled past), so rows are collected at every
scroll step and merged by channel id.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from playwright.sync_api import Page

from pippo.guide import GuideChannel
from pippo.probes.epg import Listing
from pippo.thresholds import Threshold, grade

TITLE_TOLERANCE_MS = 120_000   # a programme that just started or ended is still an acceptable "now"
POPULATE_TIMEOUT_SEC = 8.0
ID_RE = re.compile(r"/live-tv/(\d+)")

ROWS_JS = r"""
() => [...document.querySelectorAll('[role=row]')].map(r => {
  const a = r.querySelector('a[href*="/live-tv/"]');
  const fav = r.querySelector('[aria-label*="favorites"]');
  const tiles = [...r.querySelectorAll('[role=gridcell]')];
  // Artwork is either an <img> or a CSS background on a descendant (the guide uses both).
  const hasImage = (c) => !!c.querySelector('img') || [...c.querySelectorAll('*')].some(e => { const bg = getComputedStyle(e).backgroundImage; return bg && bg !== 'none'; });
  const lines = (c) => (c.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
  const box = r.getBoundingClientRect();
  const visible = tiles.filter(c => { const b = c.getBoundingClientRect(); return b.width > 0 && b.right > 0 && b.left < window.innerWidth && b.bottom > 0 && b.top < window.innerHeight; });
  const first = tiles[0] ? lines(tiles[0]) : [];
  // First tile text: title, then an accessibility hint sentence, then season/episode, episode title.
  const title = first.length ? first[0] : '';
  return {
    href: a ? a.getAttribute('href') : null,
    label: fav ? fav.getAttribute('aria-label') : null,
    title,
    // Only tiles inside the viewport count: the row is a lazily rendered carousel, so tiles scrolled
    // out of view are legitimately empty placeholders.
    tiles: visible.length,
    // Only the tile on air (the first one) carries artwork; upcoming tiles are text-only by design.
    emptyTiles: visible.filter(c => lines(c).length === 0 || (String(c.className).includes('isFirstItem') && !hasImage(c))).length,
    inView: box.bottom > 0 && box.top < window.innerHeight,
  };
})
"""

UNPOPULATED_IN_VIEW_JS = r"""
() => [...document.querySelectorAll('[role=row]')].filter(r => {
  const b = r.getBoundingClientRect();
  if (!(b.bottom > 0 && b.top < window.innerHeight)) return false;
  const t = r.querySelector('[role=gridcell]');
  return !t || (t.innerText || '').trim() === '';
}).length
"""


@dataclass
class UiRow:
    channel_id: str
    name: str
    title: str
    tiles: int
    empty_tiles: int
    seen_at_ms: int


@dataclass
class RowCollector:
    """Collects the rendered rows of the guide at every scroll step."""

    rows: dict[str, UiRow] = field(default_factory=dict)
    load_max_sec: float = 0.0

    def step(self, page: Page) -> None:
        start = time.monotonic()
        while time.monotonic() - start < POPULATE_TIMEOUT_SEC:
            if page.evaluate(UNPOPULATED_IN_VIEW_JS) == 0:
                break
            page.wait_for_timeout(250)
        self.load_max_sec = max(self.load_max_sec, time.monotonic() - start)
        self.ingest(page.evaluate(ROWS_JS), int(time.time() * 1000))

    def ingest(self, raw_rows: list[dict], now_ms: int) -> None:
        for r in raw_rows:
            m = ID_RE.search(r.get("href") or "")
            if not m:
                continue
            cid = m.group(1)
            label = r.get("label") or ""
            name = re.sub(r"^Add\s+|\s+to favorites$", "", label).strip() or r.get("title") or cid
            row = UiRow(cid, name, r.get("title") or "", int(r.get("tiles") or 0), int(r.get("emptyTiles") or 0), now_ms)
            prev = self.rows.get(cid)
            # Keep the observation with the most tiles; an earlier, emptier one must not hide problems,
            # so empty tiles are the maximum ever seen for this row.
            if prev is None or row.tiles >= prev.tiles:
                self.rows[cid] = UiRow(cid, row.name, row.title, row.tiles, max(row.empty_tiles, prev.empty_tiles if prev else 0), row.seen_at_ms)
            elif prev:
                prev.empty_tiles = max(prev.empty_tiles, row.empty_tiles)


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.casefold())).strip()


def titles_on_air(listings: list[Listing], at_ms: int, tolerance_ms: int = TITLE_TOLERANCE_MS) -> set[str]:
    """Normalized titles of programmes on air at `at_ms`, or within the tolerance of it."""
    return {normalize(l.title) for l in listings if l.start - tolerance_ms <= at_ms < l.end + tolerance_ms and l.title}


def title_matches(ui_title: str, accepted: set[str]) -> bool:
    ui = normalize(ui_title)
    if not ui or not accepted:
        return False
    return any(ui == a or ui in a or a in ui for a in accepted)


def _numeric_id(ch: GuideChannel) -> str | None:
    m = ID_RE.search(ch.href or "")
    return m.group(1) if m else None


def _check(check_id: str, value: float, overrides, detail: str | None, scope: str = "") -> dict:
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


def compute_render(
    rows: dict[str, UiRow],
    channels: list[GuideChannel],
    listings_by_slug: dict[str, list[Listing]],
    load_max_sec: float,
    overrides: dict[str, Threshold] | None = None,
) -> dict:
    """Run-level rendering metrics and checks, plus a highlight check per channel."""
    api_ids = {i: c for c in channels if (i := _numeric_id(c))}
    missing = sorted(api_ids[i].name for i in api_ids.keys() - rows.keys())
    extra = sorted(rows[i].name for i in rows.keys() - api_ids.keys())
    count_diff = len(missing) + len(extra)
    detail = "; ".join(
        p for p in (f"not rendered: {', '.join(missing[:5])}" if missing else "", f"not in the API: {', '.join(extra[:5])}" if extra else "") if p
    ) or None

    mismatches: list[str] = []
    channel_checks: dict[str, dict] = {}
    for cid, ch in api_ids.items():
        row = rows.get(cid)
        listings = listings_by_slug.get(ch.slug)
        if row is None or not listings:
            continue
        accepted = titles_on_air(listings, row.seen_at_ms)
        ok = title_matches(row.title, accepted) if accepted else True   # nothing on air: reported by epg.no_now_program
        if not ok:
            mismatches.append(ch.name)
        channel_checks[ch.slug] = {
            "metrics": {"epg.highlight_mismatch": int(not ok)},
            "checks": [
                _check(
                    "epg.highlight_mismatch",
                    float(not ok),
                    overrides,
                    None if ok else f"the guide highlights '{row.title}' but the API says {sorted(accepted)[:2]}",
                )
            ],
        }

    total_tiles = sum(r.tiles for r in rows.values())
    empty = sum(r.empty_tiles for r in rows.values())
    empty_ratio = empty / total_tiles if total_tiles else 0.0

    metrics = {
        "epg.rendered_channels": len(rows),
        "epg.render_channel_diff": count_diff,
        "epg.highlight_mismatches": len(mismatches),
        "epg.empty_tile_ratio": round(empty_ratio, 4),
        "epg.scroll_load_seconds": round(load_max_sec, 2),
    }
    checks = [
        _check("epg.render_channel_count", float(count_diff), overrides, detail),
        _check("epg.highlight_mismatch", float(len(mismatches)), overrides, ", ".join(mismatches[:5]) or None, "epg"),
        _check("epg.empty_cells", empty_ratio, overrides, f"{empty} of {total_tiles} tiles without text or image"),
        _check("epg.scroll_load_time", load_max_sec, overrides, None),
    ]
    issues = [{"channel": n, "type": "highlight_mismatch", "from": None, "to": None, "detail": "highlighted programme differs from the API"} for n in mismatches[:50]]
    issues += [{"channel": n, "type": "not_rendered", "from": None, "to": None, "detail": "in the API but missing from the rendered guide"} for n in missing[:50]]
    return {"metrics": metrics, "checks": checks, "issues": issues, "channel_checks": channel_checks}


def now_playing_check(
    ui_title: str | None,
    at_ms: int | None,
    listings: list[Listing] | None,
    overrides: dict[str, Threshold] | None = None,
) -> dict | None:
    """`player.now_playing_mismatch`: title shown on the channel page against the EPG programme on air.

    Returns None when it cannot be judged (no title read, or no listings to compare with).
    """
    if not ui_title or not at_ms or not listings:
        return None
    accepted = titles_on_air(listings, at_ms)
    if not accepted:
        return None
    ok = title_matches(ui_title, accepted)
    return _check(
        "player.now_playing_mismatch",
        float(not ok),
        overrides,
        None if ok else f"the page shows '{ui_title}' but the EPG says {sorted(accepted)[:2]}",
    )
