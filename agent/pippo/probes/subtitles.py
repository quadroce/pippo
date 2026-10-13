"""Subtitle checks (docs/03-CHECK-CATALOG.md section D), computed from a recorder buffer.

What Pluto's player does (found on pluto.tv/it): every channel declares a subtitle track in the HLS
master playlist (`#EXT-X-MEDIA:TYPE=SUBTITLES`, here always English, DEFAULT=NO) and the `<video>`
carries it as a textTrack in mode `disabled`. Nothing is fetched until a viewer picks the track in
the "Audio and Subtitles" menu, so the recorder does exactly that, as a viewer would, and the track
then goes to mode `hidden` while the player renders the cues itself. When a programme has no
subtitles the CDN answers with a **placeholder** VTT (`/placeholder/subtitles/...`) and the track
stays at zero cues: that is how Pluto says "no subtitles here", not a loading failure, so it is
reported as its own state (`placeholder_only`, info) and never as the critical `declared_not_loaded`.

States of ``sub.state``: ``no_subtitles`` (nothing declared), ``not_enabled`` (the menu could not be
driven, nothing is judged), ``ok`` (cues arrived), ``placeholder_only``, ``loaded_empty`` (real WebVTT
arrived but no cue in the window: judged through `sub.cue_gap` against speech), ``not_loaded`` (enabled and
no usable subtitle data: the real failure).
"""

from __future__ import annotations

import re

from pippo.probes.epg import detect_language
from pippo.thresholds import Threshold, grade

SPEECH_DB = -45.0              # audio level above which the programme is taken to have speech
CUE_TOLERANCE_SEC = 1.5        # a cue is "present" this long after it ends
AUDIO_PERIOD_SEC = 0.5
MIN_CUES_FOR_LANGUAGE = 10
LOAD_WINDOW_MS = 30_000        # catalog: zero cues within 30 s of playback


def _subtitle_requests(network: list[dict]) -> list[dict]:
    return [n for n in network if "/subtitle/" in n.get("path", "") or n.get("path", "").endswith((".vtt", ".webvtt"))]


SEGMENT_LANG_RE = re.compile(r"/text_([a-z]{2,3})(?:[-_][A-Za-z]+)?/")


def _segment_language(segments: list[dict]) -> str | None:
    """Language the CDN actually serves, from the segment path (`.../text_it/...`), when it says so."""
    for n in segments:
        m = SEGMENT_LANG_RE.search(n["path"])
        if m:
            return m.group(1)
    return None


def _is_placeholder(path: str) -> bool:
    return "/placeholder/" in path


def _bad(n: dict) -> bool:
    return (bool(n.get("failed")) and "ABORTED" not in str(n.get("error"))) or n.get("status", 0) >= 400


def _max_cues(samples: list[dict]) -> int:
    best = 0
    for s in samples:
        for t in s.get("tracks", []):
            best = max(best, t.get("cues") or 0)
    return best


def _active_seen(samples: list[dict]) -> bool:
    return any(t.get("active") for s in samples for t in s.get("tracks", []))


def compute_metrics(rec: dict) -> dict:
    buf = rec["buffer"]
    info = rec.get("subtitleInfo") or {}
    samples = buf.get("subs", [])
    cues = buf.get("subCues", [])
    network = rec.get("network", [])
    declared = info.get("declared", [])
    sub_requests = _subtitle_requests(network)
    declared_by_manifest = any("/subtitle/" in n["path"] and n["kind"] == "playlist" for n in sub_requests)

    m: dict = {"sub.declared": len(declared) or int(declared_by_manifest)}
    if not declared and not declared_by_manifest:
        m["sub.state"] = "no_subtitles"
        return m

    m["sub.enabled"] = bool(info.get("enabled"))
    m["sub.tracks"] = [{"lang": d.get("lang"), "label": d.get("label")} for d in declared][:5]
    if not info.get("enabled"):
        m["sub.state"] = "not_enabled"
        m["sub.note"] = info.get("enableError") or "the subtitle menu could not be driven"
        return m

    cue_count = max(_max_cues(samples), len(cues))
    segments = [n for n in sub_requests if n["kind"] == "segment"]
    real_segments = [n for n in segments if not _is_placeholder(n["path"])]
    bad = [n for n in sub_requests if _bad(n)]
    m["sub.cues_loaded"] = cue_count
    m["sub.segment_errors"] = len(bad)
    m["sub.segment_error_samples"] = sorted({f"{n.get('error') or n['status']} {n['path'].rsplit('/', 1)[-1]}" for n in bad})[:5]

    if cue_count > 0:
        m["sub.state"] = "ok"
    elif segments and not real_segments and not bad:
        m["sub.state"] = "placeholder_only"
    elif real_segments and not bad:
        m["sub.state"] = "loaded_empty"   # real WebVTT arrived but held no cue yet: judged through the speech gap
    else:
        m["sub.state"] = "not_loaded"
    m["sub.declared_not_loaded"] = int(m["sub.state"] == "not_loaded")
    m["sub.placeholder_only"] = int(m["sub.state"] == "placeholder_only")

    lang = (declared[0].get("lang") or "")[:2].lower() if declared else ""
    served = _segment_language(real_segments)
    if served:
        m["sub.served_language"] = served
        if lang and served[:2] != lang:        # the track says one language, the CDN serves another
            m["sub.language_mismatch"] = 1
    if m["sub.state"] in ("ok", "loaded_empty"):
        m["sub.cue_gap"] = _cue_gap(cues, buf.get("audio", []))
    if cue_count > 0:
        texts = [c["text"] for c in cues if c.get("text")]
        if lang and len(texts) >= MIN_CUES_FOR_LANGUAGE:
            detected = detect_language(" ".join(texts[:80]))
            m["sub.detected_language"] = detected
            if detected and detected[:2] != lang:
                m["sub.language_mismatch"] = 1
            else:
                m.setdefault("sub.language_mismatch", 0)
        if _active_seen(samples):
            shown = [s.get("dom") for s in samples if any(t.get("active") for t in s.get("tracks", []))]
            if any(d is not None for d in shown):
                m["sub.cues_not_rendered"] = int(not any(d for d in shown))
            else:
                m["sub.render_note"] = "no subtitle text selector configured: rendering not checked"
    return m


def _cue_gap(cues: list[dict], audio: list[dict]) -> float:
    """Longest stretch (seconds) of speech-like audio with no cue on screen (no cues at all counts as none shown)."""
    longest = run = 0
    for a in audio:
        speaking = a["db"] > SPEECH_DB and not a.get("muted") and not a.get("paused")
        covered = any(c["start"] - 0.1 <= a["ct"] <= c["end"] + CUE_TOLERANCE_SEC for c in cues)
        run = run + 1 if speaking and not covered else 0
        longest = max(longest, run)
    return longest * AUDIO_PERIOD_SEC


def evaluate(metrics: dict, overrides: dict[str, Threshold] | None = None) -> list[dict]:
    """Check results for every graded subtitle metric that has a value."""
    checks = []
    for check_id in ("sub.declared_not_loaded", "sub.cues_not_rendered", "sub.cue_gap", "sub.segment_errors", "sub.language_mismatch"):
        value = metrics.get(check_id)
        if value is None:
            continue
        severity, crossed = grade(check_id, float(value), overrides)
        detail = None
        if check_id == "sub.segment_errors" and metrics.get("sub.segment_error_samples"):
            detail = "; ".join(metrics["sub.segment_error_samples"])
        if check_id == "sub.cue_gap":
            detail = f"{value:g} s of speech-like audio without a cue on screen (track state: {metrics.get('sub.state')})"
        if check_id == "sub.language_mismatch" and value:
            declared_lang = (metrics.get("sub.tracks") or [{}])[0].get("lang")
            parts = []
            if metrics.get("sub.served_language"):
                parts.append(f"segments are served as '{metrics['sub.served_language']}'")
            if metrics.get("sub.detected_language"):
                parts.append(f"cue text looks '{metrics['sub.detected_language']}'")
            detail = f"track declared '{declared_lang}': " + ", ".join(parts)
        checks.append(
            {
                "checkId": check_id,
                "severity": severity if severity != "ok" else "info",
                "passed": severity == "ok",
                "value": float(value),
                "threshold": crossed,
                "detail": detail,
            }
        )
    return checks


def measure_subtitles(rec: dict, overrides: dict[str, Threshold] | None = None) -> dict:
    metrics = compute_metrics(rec)
    return {"metrics": metrics, "checks": evaluate(metrics, overrides)}
