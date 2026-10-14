import json
import threading
from contextlib import contextmanager

import httpx
import pytest

from pippo.api_client import ApiClient
from pippo.config import Settings
from pippo.guide import GuideChannel
from pippo.health import (
    SelectorHealthError,
    channel_selectors,
    consecutive_failures_abort,
    guide_selectors,
    missing_on_page,
)
from pippo.images_run import Measurement
from pippo.players_run import ChannelOutcome, PoolSummary, measure_players
from pippo.runner import execute_run

S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0)


class FakePage:
    def __init__(self, present):
        self.present = set(present)

    def evaluate(self, js, selector=None):
        if selector == "<<invalid>>":
            raise RuntimeError("not a selector")
        return selector in self.present


def test_missing_on_page_reports_labels_not_selectors():
    sels = {"guide rows": "[role='row']", "guide tiles": "[role='gridcell']"}
    assert missing_on_page(FakePage({"[role='row']", "[role='gridcell']"}), sels) == []
    assert missing_on_page(FakePage({"[role='row']"}), sels) == ["guide tiles"]
    assert missing_on_page(FakePage(set()), {"x": "<<invalid>>"}) == ["x"]               # a broken selector counts as missing


def test_selectors_come_from_the_profile_with_defaults():
    assert guide_selectors({})["guide rows"] == "[role='row']"
    assert guide_selectors({"selectors": {"epg_row": ".row", "epg_hero_player": "#hero"}}) == {
        "guide rows": ".row",
        "guide tiles": "[role='gridcell']",
        "guide hero player": "#hero",
    }
    assert channel_selectors({"selectors": {"video": "video.main"}})["video element"] == "video.main"


def test_the_error_names_what_is_missing_and_how_to_fix_it():
    e = SelectorHealthError("live guide", ["guide rows", "guide tiles"])
    assert "guide rows, guide tiles" in str(e) and "pippo discover" in str(e) and "pluto_profile.yaml" in str(e)


def test_abort_only_when_the_first_channels_all_look_broken():
    assert consecutive_failures_abort([True, True, True])
    assert not consecutive_failures_abort([True, True])                  # too few to say
    assert not consecutive_failures_abort([True, False, True, True])      # one healthy page among the first three
    assert not consecutive_failures_abort([False, False, False, True])
    assert consecutive_failures_abort([True, True, True, False, False])


# --- the pool stops measuring when the layout is gone ----------------------------------------------

@contextmanager
def fake_pw():
    yield object()


class Ctx:
    def close(self):
        pass


def chans(n):
    return [GuideChannel(f"c{i}", f"C{i}", None, None, f"/it/watch/live-tv/{i}/") for i in range(n)]


def run_pool(n, make_outcome, parallelism=1):
    got, lock = [], threading.Lock()

    def on_result(o):
        with lock:
            got.append(o)

    summary = measure_players(
        "IT", chans(n), on_result, window_sec=1, parallelism=parallelism, headless=True, profile=object(),
        open_ctx=lambda p, name, headless: Ctx(), playwright_factory=fake_pw,
        measure_one=lambda ctx, profile, ch, window, overrides, out_dir, **kw: make_outcome(ch),
    )
    return summary, got


def test_pool_stops_after_three_channels_with_a_broken_layout():
    summary, got = run_pool(20, lambda ch: ChannelOutcome(ch, selectors_missing=["video element"]))
    assert len(got) == 3                                                   # the other 17 were not even opened
    assert isinstance(summary, PoolSummary) and "video element" in summary.aborted and "layout" in summary.aborted


def test_pool_carries_on_when_only_some_pages_are_broken():
    summary, got = run_pool(8, lambda ch: ChannelOutcome(ch, selectors_missing=["video element"] if ch.slug == "c1" else []))
    assert len(got) == 8 and summary.aborted is None


# --- the run is failed with a reason the web app turns into a notice -------------------------------

def server(calls):
    def handler(req: httpx.Request):
        body = json.loads(req.content) if req.content else None
        calls.append((req.url.path, body))
        if req.url.path == "/api/agent/runs":
            return httpx.Response(201, json={"id": "run-1", "status": "running"})
        if req.url.path.endswith("/finish"):
            return httpx.Response(200, json={"counts": {}})
        return httpx.Response(201, json={"ok": True})

    return handler


def test_a_broken_guide_fails_the_run_with_the_selector_health_reason(tmp_path):
    calls = []
    api = ApiClient(S, transport=httpx.MockTransport(server(calls)), sleep=lambda s: None)

    def boom():
        raise SelectorHealthError("live guide", ["guide rows"])

    with pytest.raises(SelectorHealthError):
        execute_run(api, S, "IT", boom, detect=lambda s: "IT", reports_dir=tmp_path)
    path, body = calls[-1]
    assert path.endswith("/finish") and body["status"] == "failed" and body["reason"] == "selector_health"
    assert "guide rows" in body["log"][0]["msg"]


def test_a_pool_abort_fails_the_run_with_the_same_reason(tmp_path):
    calls = []
    api = ApiClient(S, transport=httpx.MockTransport(server(calls)), sleep=lambda s: None)
    m = Measurement({"pages": {}, "checks": []}, chans(3), {}, 3)

    def players(channels, cb):
        return PoolSummary(aborted="the first 3 channels all lacked video element")

    with pytest.raises(SelectorHealthError):
        execute_run(api, S, "IT", lambda: m, detect=lambda s: "IT", reports_dir=tmp_path, measure_players=players)
    path, body = calls[-1]
    assert path.endswith("/finish") and body["status"] == "failed" and body["reason"] == "selector_health"
    assert "pippo discover" in body["log"][0]["msg"]
    assert [p for p, _ in calls].count("/api/agent/runs/run-1/finish") == 1       # closed exactly once
