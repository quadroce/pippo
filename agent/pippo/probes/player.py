"""Player checks (docs/03-CHECK-CATALOG.md section B), computed from a recorder buffer.

Pure functions: a buffer in, metrics and check results out. Times in the buffer are
milliseconds since navigation start. Limits worth knowing:

* TTFF is measured from navigation start (page load included), not from a click, because live
  channels autoplay on load.
* Frozen-frame and black-screen checks are skipped for DRM content (frames are unreadable) and
  cannot tell a deliberate static slate from a frozen stream; ad slates are not detected yet.
* Audio silence is only evaluated when the AudioContext ran and the video was not muted.
"""

from __future__ import annotations

from pippo.thresholds import Threshold, grade

START_TIMEOUT_MS = 15_000
STALL_MIN_MS = 250
BLACK_LUMINANCE = 10.0       # of 255
FROZEN_DIFF = 0.005          # 0.5 %
SILENCE_DB = -60.0
FRAME_PERIOD_SEC = 1.0
AUDIO_PERIOD_SEC = 0.5


def _first(events: list[dict], pred) -> dict | None:
    return next((e for e in events if pred(e)), None)


def stall_episodes(events: list[dict], window_ms: int) -> list[tuple[int, int]]:
    """(start, end) of each stall after the first real frame (the first timeupdate with time > 0).

    Buffering before that point is start-up time, already covered by TTFF; Pluto also restarts its
    source once at start-up, so the first `playing` event is not a reliable start marker. A stall
    still open at the end is closed at the window end.
    """
    first_frame = _first(events, lambda e: e["type"] == "timeupdate" and e["ct"] > 0)
    if not first_frame:
        return []
    episodes, start = [], None
    for e in events:
        if e["t"] <= first_frame["t"]:
            continue
        if e["type"] in ("waiting", "stalled") and start is None:
            start = e["t"]
        elif e["type"] in ("playing", "ended") and start is not None:
            episodes.append((start, e["t"]))
            start = None
    if start is not None:
        episodes.append((start, max(window_ms, start)))
    return [(s, e) for s, e in episodes if e - s > STALL_MIN_MS]


def longest_run(flags: list[bool]) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best


def _advancing(samples: list[dict]) -> list[bool]:
    """True where the playback position moved since the previous sample (so the stream is really playing)."""
    out, prev = [], None
    for s in samples:
        out.append(prev is not None and s["ct"] > prev + 0.01 and not s.get("paused"))
        prev = s["ct"]
    return out


def compute_metrics(rec: dict) -> dict:
    """Raw metrics from a recorder result ({windowSec, navError, buffer, network})."""
    window_ms = int(rec["windowSec"] * 1000)
    buf, net = rec["buffer"], rec.get("network", [])
    events, frames, audio = buf["events"], buf["frames"], buf["audio"]
    m: dict = {}

    errors = [e for e in events if e["type"] == "error"]
    first_play = _first(events, lambda e: e["type"] == "playing")
    first_time = _first(events, lambda e: e["type"] == "timeupdate" and e["ct"] > 0)
    advanced = any(s["ct"] > 0.5 for s in frames) or first_time is not None

    m["player.media_error"] = len(errors)
    m["media_errors"] = [e.get("err") for e in errors][:5]
    started = bool(first_play or first_time) and advanced
    first_error_before_frame = bool(errors) and (first_time is None or errors[0]["t"] < first_time["t"])
    m["player.start_failed"] = int(
        bool(rec.get("navError")) or first_error_before_frame or not started
    )
    m["player.ttff"] = first_time["t"] if first_time else None

    eps = stall_episodes(events, window_ms)
    total_stall = sum(e - s for s, e in eps)
    m["player.stall_count"] = len(eps)
    m["player.stall_ratio"] = round(total_stall / window_ms, 4) if window_ms else 0.0
    m["player.longest_stall"] = max((e - s for s, e in eps), default=0)

    drm = any(e["type"] == "encrypted" for e in events) or (bool(frames) and all(f.get("blocked") for f in frames))
    m["player.drm_detected"] = drm

    readable = [f for f in frames if not f.get("blocked") and f.get("lum") is not None]
    adv = _advancing(readable)
    if drm or not readable:
        m["player.black_screen"] = None
        m["player.frozen_frame"] = None
    else:
        m["player.black_screen"] = longest_run([a and f["lum"] < BLACK_LUMINANCE for f, a in zip(readable, adv)]) * FRAME_PERIOD_SEC
        m["player.frozen_frame"] = longest_run(
            [a and f["diff"] is not None and f["diff"] < FROZEN_DIFF for f, a in zip(readable, adv)]
        ) * FRAME_PERIOD_SEC

    info = buf.get("info", {})
    audible = [a for a in audio]
    if not audible or info.get("audioState") not in (None, "running") or info.get("audioError"):
        m["player.audio_silence"] = None
        m["audio_note"] = info.get("audioError") or f"audio context {info.get('audioState', 'not created')}"
    elif all(a["muted"] for a in audible):
        m["player.audio_silence"] = None
        m["audio_note"] = "video was muted"
    else:
        aadv = _advancing(audible)
        m["player.audio_silence"] = longest_run(
            [a and not s["muted"] and s["db"] < SILENCE_DB for s, a in zip(audible, aadv)]
        ) * AUDIO_PERIOD_SEC

    segs = [n for n in net if n["kind"] in ("segment", "playlist")]
    # Requests the player aborts itself (switching rendition, seeking, leaving) are not errors.
    bad = [n for n in segs if (n.get("failed") and "ABORTED" not in str(n.get("error"))) or n["status"] >= 400]
    m["player.segment_errors"] = len(bad)
    m["segment_error_samples"] = sorted(
        {f"{n.get('error') or n['status']} {n['path'].rsplit('/', 1)[-1]}" for n in bad}
    )[:5]

    media_secs = max((s["ct"] for s in frames), default=0.0)
    total_bytes = sum(n.get("bytes") or 0 for n in net if n["kind"] == "segment" and n["status"] < 400)
    m["player.bitrate_avg"] = round(total_bytes * 8 / media_secs) if media_secs > 5 and total_bytes else None

    variants = [_variant(n["path"]) for n in net if n["kind"] == "playlist" and "audio" not in n["path"] and _variant(n["path"])]
    m["player.rendition_switches"] = sum(1 for a, b in zip(variants, variants[1:]) if a != b)
    return m


def _variant(path: str) -> str | None:
    """Variant id of a media playlist path such as /channel/<id>/<variant>/playlist.m3u8."""
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2 and parts[-1].endswith(".m3u8") and parts[-1] != "master.m3u8":
        return parts[-2]
    return None


def evaluate(metrics: dict, overrides: dict[str, Threshold] | None = None) -> list[dict]:
    """Check results for every graded metric that has a value (skipped metrics produce no check)."""
    checks = []
    for check_id in (
        "player.start_failed",
        "player.ttff",
        "player.stall_ratio",
        "player.stall_count",
        "player.longest_stall",
        "player.black_screen",
        "player.frozen_frame",
        "player.audio_silence",
        "player.media_error",
        "player.segment_errors",
        "player.rendition_switches",
    ):
        value = metrics.get(check_id)
        if value is None:
            continue
        # With a failed start there is nothing to time: only the failure itself is meaningful.
        if metrics.get("player.start_failed") and check_id not in ("player.start_failed", "player.media_error", "player.segment_errors"):
            continue
        severity, crossed = grade(check_id, float(value), overrides)
        detail = None
        if check_id == "player.media_error" and metrics.get("media_errors"):
            detail = str(metrics["media_errors"][0])
        if check_id == "player.segment_errors" and metrics.get("segment_error_samples"):
            detail = "; ".join(metrics["segment_error_samples"])
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


def measure_buffer(rec: dict, overrides: dict[str, Threshold] | None = None) -> dict:
    """Metrics and checks for one recorded channel."""
    metrics = compute_metrics(rec)
    return {"metrics": metrics, "checks": evaluate(metrics, overrides)}
