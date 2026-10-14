import json
import time

import httpx

from pippo.api_client import ApiClient
from pippo.config import Settings
from pippo.guide import GuideChannel
from pippo.images_run import Measurement
from pippo.outbox import Outbox, flush, is_permanent
from pippo.players_run import ChannelOutcome
from pippo.runner import execute_run
from pippo.updates import announce_once, is_older, parse_version, update_notice

S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0)
PAYLOAD = {"channel": {"slug": "rai-news", "name": "Rai News", "category": "news"}, "metrics": {"player.ttff": 900}, "checks": [], "screenshots": []}


def api_with(handler):
    return ApiClient(S, transport=httpx.MockTransport(handler), sleep=lambda s: None)


class Web:
    """Fake of the result endpoints with switchable behaviour per channel path."""

    def __init__(self, channels_status=201, upload_status=201):
        self.channels_status, self.upload_status, self.calls = channels_status, upload_status, []

    def handler(self, req: httpx.Request):
        self.calls.append((req.url.path, dict(req.url.params), json.loads(req.content) if req.headers.get("content-type", "").startswith("application/json") else None))
        if req.url.path == "/api/agent/runs":
            return httpx.Response(201, json={"id": "run-1", "status": "running"})
        if req.url.path == "/api/agent/upload":
            return httpx.Response(self.upload_status, json={"url": f"https://blob/{req.url.params['name']}"} if self.upload_status < 300 else {})
        if req.url.path.endswith("/channels"):
            return httpx.Response(self.channels_status, json={"ok": True} if self.channels_status < 300 else {})
        return httpx.Response(200, json={"counts": {}})


def test_add_and_list_pending_entries_in_order(tmp_path):
    ob = Outbox(tmp_path / "ob")
    assert ob.count() == 0 and ob.pending() == []
    ob.add("run-1", "a", PAYLOAD, [], None)
    time.sleep(1.05)
    ob.add("run-2", "b", PAYLOAD, [], None)
    assert ob.count() == 2
    assert [e["slug"] for _, e in ob.pending()] == ["a", "b"]
    assert [e["slug"] for _, e in ob.pending("run-2")] == ["b"]


def test_flush_sends_waiting_results_and_removes_them(tmp_path):
    ob = Outbox(tmp_path / "ob")
    ob.add("run-1", "rai-news", PAYLOAD, [], None)
    web = Web()
    r = flush(api_with(web.handler), ob)
    assert (r.sent, r.kept, r.rejected) == (1, 0, 0) and ob.count() == 0
    assert web.calls[-1][0] == "/api/agent/runs/run-1/channels" and web.calls[-1][2]["metrics"] == {"player.ttff": 900}


def test_flush_uploads_local_evidence_first_and_links_it(tmp_path):
    shot, raw = tmp_path / "t10.png", tmp_path / "raw.json"
    shot.write_bytes(b"PNG-data")
    raw.write_text('{"a": 1}')
    ob = Outbox(tmp_path / "ob")
    ob.add("run-1", "rai-news", PAYLOAD, [{"tOffsetSec": 10, "kind": "periodic", "path": str(shot)}], str(raw))
    web = Web()
    flush(api_with(web.handler), ob)
    sent = web.calls[-1][2]
    assert sent["screenshots"] == [{"tOffsetSec": 10, "kind": "periodic", "blobUrl": "https://blob/rai-news-t10-periodic.png"}]
    assert sent["rawBufferUrl"] == "https://blob/rai-news-buffer.json.gz"


def test_flush_still_sends_the_result_when_the_evidence_store_is_unavailable(tmp_path):
    shot = tmp_path / "t10.png"
    shot.write_bytes(b"PNG-data")
    ob = Outbox(tmp_path / "ob")
    ob.add("run-1", "rai-news", PAYLOAD, [{"tOffsetSec": 10, "kind": "periodic", "path": str(shot)}], None)
    web = Web(upload_status=501)                                    # no Blob store: permanent, so skip the evidence
    r = flush(api_with(web.handler), ob)
    assert r.sent == 1 and web.calls[-1][2]["screenshots"] == []


def test_a_transient_failure_keeps_everything_and_stops_the_pass(tmp_path):
    ob = Outbox(tmp_path / "ob")
    ob.add("run-1", "a", PAYLOAD, [], None)
    time.sleep(1.05)
    ob.add("run-1", "b", PAYLOAD, [], None)
    web = Web(channels_status=503)
    r = flush(api_with(web.handler), ob)
    assert (r.sent, r.kept) == (0, 2) and ob.count() == 2
    assert len([c for c in web.calls if c[0].endswith("/channels")]) == 1      # did not hammer a server that is down
    assert [e["attempts"] for _, e in ob.pending()] == [1, 0]


def test_a_permanent_refusal_moves_the_entry_aside_with_its_reason(tmp_path):
    ob = Outbox(tmp_path / "ob")
    ob.add("run-gone", "a", PAYLOAD, [], None)
    r = flush(api_with(Web(channels_status=404).handler), ob)
    assert (r.sent, r.rejected, r.kept) == (0, 1, 0) and ob.count() == 0
    reasons = list((tmp_path / "ob" / "rejected").glob("*.reason.txt"))
    assert len(reasons) == 1 and "404" in reasons[0].read_text()


def test_old_entries_are_dropped(tmp_path):
    ob = Outbox(tmp_path / "ob")
    ob.add("run-1", "a", PAYLOAD, [], None)
    r = flush(api_with(Web().handler), ob, now=time.time() + 8 * 86_400)
    assert (r.dropped, r.sent) == (1, 0) and ob.count() == 0


def test_unreadable_entries_do_not_stop_the_queue(tmp_path):
    ob = Outbox(tmp_path / "ob")
    (tmp_path / "ob").mkdir()
    (tmp_path / "ob" / "0-broken.json").write_text("{not json")
    ob.add("run-1", "a", PAYLOAD, [], None)
    assert flush(api_with(Web().handler), ob).sent == 1
    assert (tmp_path / "ob" / "rejected" / "0-broken.json").exists()


def test_which_statuses_are_permanent():
    from pippo.api_client import ApiError

    assert all(is_permanent(ApiError("x", s)) for s in (400, 404, 409, 413))
    assert not any(is_permanent(ApiError("x", s)) for s in (None, 408, 429, 500, 503))


# --- the runner queues what it could not upload and retries before closing --------------------

def run_with(web, tmp_path):
    ch = GuideChannel("rai-news", "Rai News", "news", None, "/it/watch/live-tv/1/")
    m = Measurement({"pages": {}, "checks": []}, [ch], {}, 1)

    def players(channels, cb):
        cb(ChannelOutcome(ch, {"player.ttff": 900}))

    return execute_run(api_with(web.handler), S, "IT", lambda: m, detect=lambda s: "IT", reports_dir=tmp_path,
                       measure_players=players, outbox=Outbox(tmp_path / "ob"))


def test_runner_queues_a_result_the_server_could_not_take_and_the_run_still_closes(tmp_path):
    out = run_with(Web(channels_status=503), tmp_path)
    assert len(out["failedUploads"]) == 1 and "rai-news" in out["failedUploads"][0]
    assert Outbox(tmp_path / "ob").count() == 1                      # kept for later, not lost


def test_runner_does_not_queue_a_result_the_server_refuses_for_good(tmp_path):
    out = run_with(Web(channels_status=400), tmp_path)
    assert len(out["failedUploads"]) == 1 and Outbox(tmp_path / "ob").count() == 0


def test_runner_recovers_a_result_on_the_last_try_before_closing(tmp_path):
    class Flaky(Web):
        def handler(self, req):
            if req.url.path.endswith("/channels"):
                self.channels_status = 503 if not any(c[0].endswith("/channels") for c in self.calls) else 201
            return super().handler(req)

    out = run_with(Flaky(), tmp_path)
    assert out["failedUploads"] == [] and Outbox(tmp_path / "ob").count() == 0


# --- update check ------------------------------------------------------------------------------

def test_version_comparison():
    assert parse_version("1.2.3") == (1, 2, 3) and parse_version("v0.10.0") == (0, 10, 0) and parse_version("1.2") is None
    assert is_older("0.1.0", "0.2.0") and is_older("0.9.0", "0.10.0") and not is_older("0.2.0", "0.2.0") and not is_older("1.0.0", "0.9.9")
    assert not is_older("0.1.0", None) and not is_older("0.1.0", "garbage")


def test_update_notice_only_when_a_newer_version_is_announced():
    assert "0.2.0" in update_notice({"latestAgentVersion": "0.2.0"}, "0.1.0")
    assert update_notice({"latestAgentVersion": "0.1.0"}, "0.1.0") is None
    assert update_notice({}, "0.1.0") is None
    assert update_notice({"latestAgentVersion": 3}, "0.1.0") is None


def test_the_update_is_announced_once_per_version(caplog):
    import logging

    caplog.set_level(logging.WARNING)
    reply = {"latestAgentVersion": "9.9.9"}
    assert announce_once(reply, "0.1.0") is not None and announce_once(reply, "0.1.0") is not None
    assert len([r for r in caplog.records if "update available" in r.message]) == 1
