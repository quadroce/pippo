from pippo.probes.player import compute_metrics, evaluate, longest_run, measure_buffer, stall_episodes
from pippo.thresholds import Threshold


def ev(t, type, ct=0.0, **kw):
    return {"t": t, "type": type, "ct": ct, "rs": 4, **kw}


def frames(n, lum=120, diff=0.05, start_ct=1.0, blocked=False):
    return [{"t": 3000 + i * 1000, "lum": lum, "diff": diff, "blocked": blocked, "ct": start_ct + i, "paused": False} for i in range(n)]


def audio(n, db=-30, muted=False):
    return [{"t": 3000 + i * 500, "db": db, "muted": muted, "ct": 1 + i * 0.5, "paused": False} for i in range(n)]


def rec(events=None, frame_list=None, audio_list=None, network=None, info=None, window=60, nav_error=None):
    healthy = [ev(500, "loadstart"), ev(900, "playing"), ev(1500, "timeupdate", 0.6), ev(2500, "timeupdate", 1.6)]
    return {
        "windowSec": window,
        "navError": nav_error,
        "buffer": {
            "events": healthy if events is None else events,
            "frames": frames(20) if frame_list is None else frame_list,
            "audio": audio(40) if audio_list is None else audio_list,
            "info": {"audioState": "running"} if info is None else info,
        },
        "network": network or [],
    }


def seg(status=200, path="/c/abc/1000/seg_1.ts", **kw):
    return {"t": 0, "kind": "segment", "path": path, "status": status, "bytes": 100_000, **kw}


def test_healthy_channel_passes_everything():
    out = measure_buffer(rec(network=[seg()]))
    assert out["metrics"]["player.start_failed"] == 0
    assert out["metrics"]["player.ttff"] == 1500
    assert all(c["passed"] for c in out["checks"])


def test_startup_buffering_is_not_a_stall_but_a_midplay_stall_is():
    # Pluto restarts its source at start-up: waiting before the first real frame is TTFF, not a stall.
    startup = [ev(900, "playing"), ev(1000, "waiting"), ev(6000, "playing"), ev(6100, "timeupdate", 0.5)]
    assert stall_episodes(startup, 60_000) == []
    mid = startup + [ev(20_000, "waiting", 3), ev(24_000, "playing", 3)]
    assert stall_episodes(mid, 60_000) == [(20_000, 24_000)]
    short = startup + [ev(20_000, "stalled", 3), ev(20_100, "playing", 3)]
    assert stall_episodes(short, 60_000) == []                      # under 250 ms is ignored
    open_ended = startup + [ev(50_000, "waiting", 3)]
    assert stall_episodes(open_ended, 60_000) == [(50_000, 60_000)]  # still stalled when the window ends


def test_stall_metrics_and_grading():
    events = [ev(900, "playing"), ev(1500, "timeupdate", 0.6), ev(10_000, "waiting", 5), ev(16_000, "playing", 5)]
    out = measure_buffer(rec(events=events))
    m = out["metrics"]
    assert m["player.stall_count"] == 1 and m["player.longest_stall"] == 6000 and m["player.stall_ratio"] == 0.1
    by = {c["checkId"]: c for c in out["checks"]}
    assert by["player.longest_stall"]["severity"] == "warning"       # > 3000 ms, below 10000
    assert by["player.stall_ratio"]["severity"] == "warning"         # 10 % is above 3 %, below 15 %


def test_start_failed_variants():
    assert measure_buffer(rec(events=[], frame_list=[], audio_list=[]))["metrics"]["player.start_failed"] == 1
    err = [ev(500, "loadstart"), ev(800, "error", err={"code": 4, "message": "no source"})]
    out = measure_buffer(rec(events=err, frame_list=[], audio_list=[]))
    assert out["metrics"]["player.start_failed"] == 1 and out["metrics"]["player.media_error"] == 1
    by = {c["checkId"]: c for c in out["checks"]}
    assert by["player.start_failed"]["severity"] == "critical" and "no source" in by["player.media_error"]["detail"]
    assert "player.ttff" not in by and "player.stall_ratio" not in by   # nothing meaningful to time
    assert measure_buffer(rec(nav_error="navigation failed"))["metrics"]["player.start_failed"] == 1


def test_black_and_frozen_runs_only_count_while_time_advances():
    black = frames(15, lum=2) + frames(5, start_ct=16)
    m = compute_metrics(rec(frame_list=black))
    assert m["player.black_screen"] == 14.0                           # first sample has no previous position
    paused = [{**f, "paused": True} for f in frames(10, lum=0, diff=0)]
    m = compute_metrics(rec(frame_list=paused))
    assert m["player.black_screen"] == 0.0 and m["player.frozen_frame"] == 0.0
    frozen = compute_metrics(rec(frame_list=frames(12, diff=0.0)))
    assert frozen["player.frozen_frame"] == 11.0
    assert evaluate(frozen)[0]["checkId"] == "player.start_failed"


def test_drm_skips_frame_checks():
    m = compute_metrics(rec(events=[ev(900, "playing"), ev(1500, "timeupdate", 0.6), ev(1000, "encrypted")]))
    assert m["player.drm_detected"] is True and m["player.black_screen"] is None
    m = compute_metrics(rec(frame_list=frames(10, lum=None, diff=None, blocked=True)))
    assert m["player.drm_detected"] is True and m["player.frozen_frame"] is None


def test_audio_silence_and_skips():
    silent = compute_metrics(rec(audio_list=audio(30, db=-90)))
    assert silent["player.audio_silence"] == 14.5                     # 29 advancing samples * 0.5 s
    muted = compute_metrics(rec(audio_list=audio(30, db=-90, muted=True)))
    assert muted["player.audio_silence"] is None and "muted" in muted["audio_note"]
    suspended = compute_metrics(rec(info={"audioState": "suspended"}))
    assert suspended["player.audio_silence"] is None
    assert "player.audio_silence" not in {c["checkId"] for c in evaluate(muted)}


def test_segment_errors_ignore_aborted_requests():
    net = [seg(404), seg(500), seg(0, failed=True, error="net::ERR_ABORTED"), seg(0, failed=True, error="net::ERR_CONNECTION_RESET")]
    m = compute_metrics(rec(network=net))
    assert m["player.segment_errors"] == 3
    out = measure_buffer(rec(network=net))
    assert {c["checkId"]: c for c in out["checks"]}["player.segment_errors"]["severity"] == "warning"   # 3 is below the critical 5
    five = {c["checkId"]: c for c in measure_buffer(rec(network=[seg(500)] * 5))["checks"]}
    assert five["player.segment_errors"]["severity"] == "critical"


def test_rendition_switches_and_bitrate():
    pl = lambda v: {"t": 0, "kind": "playlist", "path": f"/channel/abc/{v}/playlist.m3u8", "status": 200}
    net = [pl("1"), pl("1"), pl("2"), pl("1"), {"t": 0, "kind": "playlist", "path": "/channel/abc/audio/audio/Italian/audio.m3u8", "status": 200}]
    m = compute_metrics(rec(network=net + [seg()]))
    assert m["player.rendition_switches"] == 2
    assert m["player.bitrate_avg"] == round(100_000 * 8 / 20.0)       # 20 s of media (last frame position)


def test_overrides_change_the_grade():
    events = [ev(900, "playing"), ev(1500, "timeupdate", 0.6)]
    slow = rec(events=[ev(900, "playing"), ev(12_000, "timeupdate", 1.0)])
    assert {c["checkId"]: c for c in measure_buffer(slow)["checks"]}["player.ttff"]["severity"] == "critical"
    relaxed = {"player.ttff": Threshold(warn=20_000, critical=None)}
    assert {c["checkId"]: c for c in measure_buffer(slow, relaxed)["checks"]}["player.ttff"]["passed"]
    assert events and longest_run([True, True, False, True]) == 2
