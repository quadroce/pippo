import threading
import time
from contextlib import contextmanager

import httpx

from pippo.api_client import ApiClient
from pippo.config import Settings
from pippo.guide import GuideChannel
from pippo.images_run import Measurement
from pippo.players_run import ChannelOutcome, measure_players, numeric_id
from pippo.runner import execute_run


def chans(n):
    return [GuideChannel(f"c{i}", f"Channel {i}", "news", "a" * 24, f"/it/watch/live-tv/{100 + i}/") for i in range(n)]


class FakeCtx:
    def __init__(self, name):
        self.name, self.closed = name, False

    def close(self):
        self.closed = True


@contextmanager
def fake_pw():
    yield object()


def run_pool(channels, measure_one, parallelism=2, open_ctx=None, profile=object()):
    got, opened = [], []

    def default_open(p, name, headless):
        ctx = FakeCtx(name)
        opened.append(ctx)
        return ctx

    lock = threading.Lock()

    def on_result(o):
        with lock:
            got.append(o)

    measure_players(
        "IT", channels, on_result, window_sec=1, parallelism=parallelism, headless=True, profile=profile,
        open_ctx=open_ctx or default_open, playwright_factory=fake_pw, measure_one=measure_one,
    )
    return got, opened


def test_numeric_id_from_href():
    assert numeric_id(chans(1)[0]) == "100"
    assert numeric_id(GuideChannel("x", "X", None, None, None)) is None


def test_every_channel_reported_in_parallel_with_one_profile_per_worker():
    seen_threads = set()

    def one(ctx, profile, ch, window, overrides, out_dir):
        seen_threads.add(threading.current_thread().name)
        time.sleep(0.05)
        return ChannelOutcome(ch, {"player.ttff": 1000})

    got, opened = run_pool(chans(8), one, parallelism=3)
    assert sorted(o.channel.slug for o in got) == sorted(c.slug for c in chans(8))
    assert len(seen_threads) == 3
    assert sorted(c.name for c in opened) == ["IT-w1", "IT-w2", "IT-w3"] and all(c.closed for c in opened)


def test_a_crash_on_one_channel_is_isolated_and_reported_as_error():
    def one(ctx, profile, ch, window, overrides, out_dir):
        if ch.slug == "c2":
            raise RuntimeError("Target closed\nsecond line")
        return ChannelOutcome(ch, {"player.ttff": 1000})

    got, _ = run_pool(chans(5), one, parallelism=2)
    by = {o.channel.slug: o for o in got}
    assert len(got) == 5 and by["c2"].error == "measurement crashed: Target closed"
    assert all(o.error is None for s, o in by.items() if s != "c2")


def test_channels_are_not_lost_when_every_worker_dies():
    def broken_open(p, name, headless):
        raise RuntimeError("chrome missing")

    got, _ = run_pool(chans(3), lambda *a: None, open_ctx=broken_open)
    assert len(got) == 3 and all("all browser workers stopped" in o.error for o in got)


# --- runner integration: files uploaded, one request per channel --------------------------

S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0)


def test_runner_uploads_screenshots_raw_buffer_and_error_outcomes(tmp_path):
    shot = tmp_path / "t10.png"
    shot.write_bytes(b"\x89PNG-data")
    raw = tmp_path / "raw.json"
    raw.write_text('{"a": 1}')
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.url.path, dict(req.url.params), req.content))
        if req.url.path == "/api/agent/runs":
            return httpx.Response(201, json={"id": "run-1", "status": "running"})
        if req.url.path == "/api/agent/upload":
            return httpx.Response(201, json={"url": f"https://blob/{req.url.params['name']}", "pathname": "p"})
        if req.url.path.endswith("/finish"):
            return httpx.Response(200, json={"counts": {"ok": 1, "warning": 0, "critical": 0, "error": 1}})
        return httpx.Response(201, json={"ok": True})

    cs = chans(2)

    def players(channels, cb):
        cb(ChannelOutcome(cs[0], {"player.ttff": 900}, [{"checkId": "player.ttff", "severity": "info", "passed": True}],
                          [{"tOffsetSec": 10, "kind": "periodic", "path": str(shot)}], raw))
        cb(ChannelOutcome(cs[1], error="measurement crashed: boom"))

    m = Measurement({"pages": {}, "checks": []}, cs, {}, 2)
    api = ApiClient(S, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    out = execute_run(api, S, "IT", lambda: m, detect=lambda s: "IT", reports_dir=tmp_path, measure_players=players)

    import json
    channel_posts = [json.loads(c[2]) for c in calls if c[0].endswith("/channels")]
    assert len(channel_posts) == 2 and out["failedUploads"] == []
    first, second = channel_posts
    assert first["screenshots"] == [{"tOffsetSec": 10, "kind": "periodic", "blobUrl": "https://blob/c0-t10-periodic.png"}]
    assert first["rawBufferUrl"] == "https://blob/c0-buffer.json.gz" and first["metrics"]["player.ttff"] == 900
    assert second["error"] == "measurement crashed: boom" and "screenshots" in second
    uploads = [c for c in calls if c[0] == "/api/agent/upload"]
    assert {u[1]["kind"] for u in uploads} == {"screenshot", "raw"}
