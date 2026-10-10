"""Default thresholds from docs/03-CHECK-CATALOG.md and the grading rule.

Thresholds are global defaults here; per-country overrides come from the web app later (Phase 5).
A value is graded against ``critical`` first, then ``warn``; ``None`` disables that level.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Threshold:
    warn: float | None = None
    critical: float | None = None


# checkId -> thresholds (values: ratios as 0..1, seconds, counts)
DEFAULTS: dict[str, Threshold] = {
    "img.broken_ratio": Threshold(warn=0.01, critical=0.05),
    "img.placeholder_ratio": Threshold(warn=0.02, critical=0.10),
    "img.lazy_load_timeout": Threshold(warn=5.0),
    "img.aspect_mismatch": Threshold(warn=0),       # any mismatch (> 0 items)
    "img.channel_logo_missing": Threshold(warn=0),  # any
}


def grade(check_id: str, value: float, overrides: dict[str, Threshold] | None = None) -> tuple[str, float | None]:
    """Return (severity, threshold_crossed). Severity is "ok", "warning" or "critical"."""
    t = (overrides or {}).get(check_id) or DEFAULTS.get(check_id)
    if t is None:
        return "ok", None
    if t.critical is not None and value > t.critical:
        return "critical", t.critical
    if t.warn is not None and value > t.warn:
        return "warning", t.warn
    return "ok", None


def parse_thresholds(reply: dict) -> dict[str, Threshold]:
    """Effective thresholds from a heartbeat reply ({checkId: {warn, critical}}). Bad entries are skipped."""
    out: dict[str, Threshold] = {}
    for check_id, raw in (reply.get("thresholds") or {}).items():
        if not isinstance(raw, dict):
            continue
        warn, critical = raw.get("warn"), raw.get("critical")
        ok = lambda v: v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0)  # noqa: E731
        if ok(warn) and ok(critical):
            out[check_id] = Threshold(warn=warn, critical=critical)
    return out
