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
