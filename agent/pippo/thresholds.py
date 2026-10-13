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
    # Player (docs/03-CHECK-CATALOG.md section B). Times in ms for ttff and stalls, seconds for the rest.
    "player.start_failed": Threshold(critical=0),    # any
    "player.ttff": Threshold(warn=4000, critical=10000),
    "player.stall_ratio": Threshold(warn=0.03, critical=0.15),
    "player.stall_count": Threshold(warn=2),         # catalog: warning at 3 or more
    "player.longest_stall": Threshold(warn=3000, critical=10000),
    "player.black_screen": Threshold(warn=3, critical=10),
    "player.frozen_frame": Threshold(warn=3, critical=10),
    "player.audio_silence": Threshold(warn=5, critical=20),
    "player.media_error": Threshold(critical=0),     # any
    "player.segment_errors": Threshold(warn=0, critical=4),  # catalog: warning at 1+, critical at 5+
    "player.rendition_switches": Threshold(warn=6),
    # EPG data (section C.1). Coverage is graded the other way round: lower is worse.
    "epg.api_failed": Threshold(critical=0),
    "epg.coverage_hours": Threshold(warn=6, critical=2),
    "epg.gap": Threshold(warn=0),
    "epg.overlap": Threshold(warn=0),
    "epg.no_now_program": Threshold(critical=0),
    "epg.missing_metadata": Threshold(warn=0.02),
    "epg.language_mismatch": Threshold(warn=0.20),
    # EPG rendering (section C.2) and the player/EPG cross-check.
    "epg.render_channel_count": Threshold(critical=0),   # any difference between API and rendered channels
    "epg.highlight_mismatch": Threshold(warn=0),
    "epg.empty_cells": Threshold(warn=0.01),
    "epg.scroll_load_time": Threshold(warn=5.0),
    "player.now_playing_mismatch": Threshold(warn=0),
    # Subtitles (section D).
    "sub.declared_not_loaded": Threshold(critical=0),   # any
    "sub.cues_not_rendered": Threshold(critical=0),     # any
    "sub.cue_gap": Threshold(warn=30),                  # seconds of speech without a cue
    "sub.segment_errors": Threshold(warn=0),            # any
    "sub.language_mismatch": Threshold(warn=0),         # any
    "sub.sync_offset": Threshold(warn=1.0, critical=2.5),  # seconds (step 4.2)
}

# Checks where a value BELOW the threshold is the failure (hours of programming left, for example).
LOWER_IS_WORSE = {"epg.coverage_hours"}


def grade(check_id: str, value: float, overrides: dict[str, Threshold] | None = None) -> tuple[str, float | None]:
    """Return (severity, threshold_crossed). Severity is "ok", "warning" or "critical"."""
    t = (overrides or {}).get(check_id) or DEFAULTS.get(check_id)
    if t is None:
        return "ok", None
    if check_id in LOWER_IS_WORSE:
        if t.critical is not None and value < t.critical:
            return "critical", t.critical
        if t.warn is not None and value < t.warn:
            return "warning", t.warn
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
