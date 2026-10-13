"""EPG data checks (docs/03-CHECK-CATALOG.md section C.1), computed from the guide's listings.

Pure functions: listings in, metrics, issues and check results out. ``now`` is the agent clock in
epoch milliseconds (listing times are UTC epoch milliseconds, so no timezone conversion is needed).

Deliberately not implemented here:
* ``epg.timezone_offset``: Pluto's programme boundaries are not aligned to :00/:30 (for example
  16:25:18), so the catalog's alignment method cannot be evaluated; the timezone is verified through
  the now-marker comparison of the rendering checks instead.
* ``epg.channel_count_drop``: needs the previous run, so the web app evaluates it on upload.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pippo.thresholds import Threshold, grade

GAP_TOLERANCE_MS = 60_000
PLACEHOLDER_TITLE_RE = re.compile(r"^\s*(tba|tbd|tbc|programme?|programma|to be announced|da definire|no title|untitled|n/?a)\s*$", re.I)
MIN_DESCRIPTION_CHARS_FOR_LANGUAGE = 40
LANGUAGE_SAMPLE = 150
MAX_ISSUES = 300


@dataclass(frozen=True)
class Listing:
    start: int
    end: int
    title: str
    description: str
    image: str


def parse_listings(raw: list[dict]) -> list[Listing]:
    """Listings sorted by start time. Entries without usable times are dropped."""
    out = []
    for r in raw or []:
        try:
            start, end = int(r["startTimestamp"]), int(r["endTimestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        out.append(
            Listing(
                start=start,
                end=end,
                title=str(r.get("title") or r.get("episodeTitle") or "").strip(),
                description=str(r.get("description") or "").strip(),
                image=str(r.get("resolvedfilePathThumb") or r.get("filePathThumb") or "").strip(),
            )
        )
    return sorted(out, key=lambda x: x.start)


def analyse_channel(listings: list[Listing], now_ms: int) -> dict:
    """Per-channel EPG facts: current programme, hours ahead, gaps, overlaps and metadata problems."""
    current = next((l for l in listings if l.start <= now_ms < l.end), None)
    gaps, overlaps = [], []
    for prev, nxt in zip(listings, listings[1:]):
        if nxt.start - prev.end > GAP_TOLERANCE_MS:
            gaps.append({"from": prev.end, "to": nxt.start, "seconds": round((nxt.start - prev.end) / 1000)})
        elif prev.end - nxt.start > GAP_TOLERANCE_MS:
            overlaps.append({"from": nxt.start, "to": prev.end, "seconds": round((prev.end - nxt.start) / 1000)})
    ahead = (max((l.end for l in listings), default=now_ms) - now_ms) / 3_600_000
    missing = [
        {"title": l.title, "start": l.start, "missing": _missing_fields(l)} for l in listings if _missing_fields(l)
    ]
    return {
        "hasNow": current is not None,
        "nowTitle": current.title if current else None,
        "hoursAhead": round(max(ahead, 0.0), 2),
        "gaps": gaps,
        "overlaps": overlaps,
        "programs": len(listings),
        "missing": missing,
    }


def _missing_fields(l: Listing) -> list[str]:
    out = []
    if not l.title or PLACEHOLDER_TITLE_RE.match(l.title):
        out.append("title")
    if not l.description:
        out.append("description")
    if not l.image:
        out.append("image")
    return out


def detect_language(text: str) -> str | None:
    """ISO 639-1 code of the text, or None when it cannot be detected. Deterministic."""
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(text)
    except Exception:
        return None


def detect_language_confident(text: str, min_probability: float = 0.9) -> str | None:
    """Language of the text only when the detector is sure; noisy text (roll-up captions, short fragments) gives None."""
    try:
        from langdetect import DetectorFactory, detect_langs

        DetectorFactory.seed = 0
        best = detect_langs(text)[0]
        return best.lang if best.prob >= min_probability else None
    except Exception:
        return None


def language_mismatch_ratio(
    texts: list[str], expected: str, detector=detect_language
) -> tuple[float | None, int]:
    """Share of texts detected in another language than `expected`, and how many were evaluated."""
    expected = expected.lower()[:2]
    step = max(1, len(texts) // LANGUAGE_SAMPLE)  # spread the sample over all channels, not just the first ones
    results = [detector(t) for t in texts[::step][:LANGUAGE_SAMPLE]]
    known = [r for r in results if r]
    if not known:
        return None, 0
    return sum(1 for r in known if r[:2] != expected) / len(known), len(known)


def _check(check_id: str, value: float, overrides, detail: str | None = None, scope: str = "") -> dict:
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


def compute_epg(
    listings_by_channel: dict[str, list[Listing]],
    *,
    names: dict[str, str],
    now_ms: int,
    expected_language: str | None,
    api_error: str | None = None,
    guide_total: int | None = None,
    overrides: dict[str, Threshold] | None = None,
    detector=detect_language,
) -> dict:
    """Run-level EPG result plus per-channel checks.

    Returns ``{"metrics", "checks", "issues", "channel_results"}``. ``channel_results`` maps a channel
    slug to ``{"metrics", "checks"}`` that the runner merges into that channel's own result.
    """
    metrics: dict = {"epg.api_failed": int(bool(api_error) or not listings_by_channel)}
    checks = [
        _check(
            "epg.api_failed",
            float(metrics["epg.api_failed"]),
            overrides,
            api_error or ("the guide returned no channels" if not listings_by_channel else None),
        )
    ]
    if not listings_by_channel:
        return {"metrics": metrics, "checks": checks, "issues": [], "channel_results": {}}

    issues: list[dict] = []
    channel_results: dict[str, dict] = {}
    all_programs = 0
    missing_programs = 0
    hours: list[float] = []
    no_now = gap_channels = overlap_channels = 0
    texts: list[str] = []

    for slug, listings in sorted(listings_by_channel.items()):
        info = analyse_channel(listings, now_ms)
        name = names.get(slug, slug)
        hours.append(info["hoursAhead"])
        all_programs += info["programs"]
        missing_programs += len(info["missing"])
        texts += [l.description for l in listings if len(l.description) >= MIN_DESCRIPTION_CHARS_FOR_LANGUAGE]

        ch_checks = [
            _check("epg.no_now_program", 0.0 if info["hasNow"] else 1.0, overrides, None if info["hasNow"] else "no programme covers the current time"),
            _check("epg.gap", float(len(info["gaps"])), overrides, _summ(info["gaps"], "gap")),
            _check("epg.overlap", float(len(info["overlaps"])), overrides, _summ(info["overlaps"], "overlap")),
        ]
        channel_results[slug] = {
            "metrics": {
                "epg.hours_ahead": info["hoursAhead"],
                "epg.no_now_program": int(not info["hasNow"]),
                "epg.gap": len(info["gaps"]),
                "epg.overlap": len(info["overlaps"]),
            },
            "checks": ch_checks,
        }
        no_now += not info["hasNow"]
        gap_channels += bool(info["gaps"])
        overlap_channels += bool(info["overlaps"])
        for kind, items in (("gap", info["gaps"]), ("overlap", info["overlaps"])):
            for it in items[:3]:
                issues.append({"channel": name, "type": kind, "from": it["from"], "to": it["to"], "detail": f"{it['seconds']} s"})
        if not info["hasNow"]:
            issues.append({"channel": name, "type": "no_now_program", "from": now_ms, "to": now_ms, "detail": "no programme at the current time"})
        for m in info["missing"][:3]:
            issues.append({"channel": name, "type": "missing_metadata", "from": m["start"], "to": m["start"], "detail": f"{m['title'] or '(untitled)'}: no {', '.join(m['missing'])}"})

    coverage = min(hours)
    missing_ratio = missing_programs / all_programs if all_programs else 0.0
    metrics.update(
        {
            "epg.channel_count": len(listings_by_channel),
            "epg.guide_total": guide_total,
            "epg.coverage_hours": coverage,
            "epg.channels_no_now": no_now,
            "epg.channels_with_gaps": gap_channels,
            "epg.channels_with_overlaps": overlap_channels,
            "epg.programs": all_programs,
            "epg.missing_metadata_ratio": round(missing_ratio, 4),
        }
    )
    worst = min(listings_by_channel, key=lambda s: _hours(listings_by_channel[s], now_ms))
    checks.append(_check("epg.coverage_hours", coverage, overrides, f"shortest: {names.get(worst, worst)}"))
    checks.append(_check("epg.missing_metadata", missing_ratio, overrides, f"{missing_programs} of {all_programs} programmes"))

    if expected_language:
        ratio, evaluated = language_mismatch_ratio(texts, expected_language, detector)
        metrics["epg.language_mismatch_ratio"] = None if ratio is None else round(ratio, 4)
        metrics["epg.language_evaluated"] = evaluated
        if ratio is not None and evaluated >= 20:
            checks.append(_check("epg.language_mismatch", ratio, overrides, f"{evaluated} descriptions checked against '{expected_language}'"))

    return {"metrics": metrics, "checks": checks, "issues": issues[:MAX_ISSUES], "channel_results": channel_results}


def _hours(listings: list[Listing], now_ms: int) -> float:
    return (max((l.end for l in listings), default=now_ms) - now_ms) / 3_600_000


def _summ(items: list[dict], label: str) -> str | None:
    if not items:
        return None
    longest = max(i["seconds"] for i in items)
    return f"{len(items)} {label}(s), longest {longest} s"

