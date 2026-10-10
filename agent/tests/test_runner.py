import json

import httpx
import pytest

from pippo.api_client import ApiClient, ApiError
from pippo.config import Settings
from pippo.guide import GuideCapture, parse_channel
from pippo.images_run import Measurement
from pippo.probes.images import ImageItem
from pippo.probes.logos import channel_logo_checks
from pippo.runner import RunBlocked, execute_run

S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0)
H1, H2 = "a" * 24, "b" * 24
RAW = {
    "slug": "forensic-files-it",
    "channelName": "Forensic Files",
    "channelCategorySlugs": ["featured", "true-crime-it"],
    "filePathLogo": f"files/ptv/channels/{H1}/solidLogoPNG.png",
    "href": "/it/watch/live-tv/30712/",
}


def logo_item(h, **kw):
    d = dict(kind="img", src=f"https://img.test/ptv/channels/{h}/solidLogoPNG_1", nw=400, nh=133, rw=100, rh=33,
             fit="contain", complete=True, alt="", ctx=None, shown=True)
    d.update(kw)
    return ImageItem(**d)


def test_parse_channel_and_capture_pages():
    ch = parse_channel(RAW)
    assert (ch.slug, ch.name, ch.category, ch.logo_hash) == ("forensic-files-it", "Forensic Files", "featured", H1)
    assert parse_channel({"channelName": "no slug"}) is None
    cap = GuideCapture(route="/graphql/")
    cap.ingest({"data": {"channels": {"total": 2, "channels": [RAW]}}})
    cap.ingest({"data": {"channels": {"total": 2, "channels": [RAW, {**RAW, "slug": "other", "channelName": "Other"}]}}})
    assert cap.total == 2 and set(cap.channels) == {"forensic-files-it", "other"}


def test_logo_check_found_missing_and_broken():
    chans = [parse_channel(RAW), parse_channel({**RAW, "slug": "b", "channelName": "B", "filePathLogo": f"files/ptv/channels/{H2}/x.png"}),
             parse_channel({**RAW, "slug": "c", "channelName": "C", "filePathLogo": ""})]
    res = channel_logo_checks(chans, [logo_item(H1), logo_item(H2, status=404)])
    assert res["forensic-files-it"]["checks"][0]["passed"]
    assert not res["b"]["checks"][0]["passed"] and res["b"]["checks"][0]["severity"] == "warning"   # broken logo
    assert res["c"]["metrics"]["img.channel_logo_missing"] is True                                  # no logo declared


# --- runner -------------------------------------------------------------------------------

class Server:
    def __init__(self, run_status="running", fail_channels=False):
        self.calls, self.run_status, self.fail_channels = [], run_status, fail_channels

    def handler(self, req: httpx.Request):
        body = json.loads(req.content) if req.content else None
        self.calls.append((req.url.path, body))
        if req.url.path == "/api/agent/runs":
            return httpx.Response(201, json={"id": "run-1", "status": self.run_status})
        if self.fail_channels and req.url.path.endswith("/channels"):
            return httpx.Response(400, json={"error": "bad"})
        if req.url.path.endswith("/finish"):
            return httpx.Response(200, json={"id": "run-1", "status": "completed", "counts": {"ok": 1, "warning": 0, "critical": 0, "error": 0}})
        return httpx.Response(201, json={"ok": True})


def measurement():
    ch = parse_channel(RAW)
    return Measurement(
        report={"pages": {"home": {"url": "u", "metrics": {}}}, "checks": []},
        channels=[ch],
        channel_results=channel_logo_checks([ch], [logo_item(H1)]),
        guide_total=1,
    )


def run(server, tmp_path, detect=lambda s: "IT", measure=measurement):
    api = ApiClient(S, transport=httpx.MockTransport(server.handler), sleep=lambda s: None)
    return execute_run(api, S, "IT", measure, detect=detect, reports_dir=tmp_path)


def test_successful_run_uploads_in_order_and_saves_locally(tmp_path):
    srv = Server()
    out = run(srv, tmp_path)
    assert [p for p, _ in srv.calls] == [
        "/api/agent/runs", "/api/agent/runs/run-1/images", "/api/agent/runs/run-1/channels", "/api/agent/runs/run-1/finish",
    ]
    assert srv.calls[0][1]["detectedCountry"] == "IT"
    assert srv.calls[2][1]["channel"] == {"slug": "forensic-files-it", "name": "Forensic Files", "category": "featured"}
    assert out["counts"]["ok"] == 1 and list(tmp_path.glob("run-IT-*.json"))


def test_blocked_run_measures_nothing(tmp_path):
    srv = Server(run_status="blocked")
    called = []
    with pytest.raises(RunBlocked):
        run(srv, tmp_path, detect=lambda s: "FR", measure=lambda: called.append(1))
    assert called == [] and [p for p, _ in srv.calls] == ["/api/agent/runs"]


def test_measurement_crash_closes_run_as_failed(tmp_path):
    srv = Server()

    def boom():
        raise RuntimeError("chrome crashed")

    with pytest.raises(RuntimeError):
        run(srv, tmp_path, measure=boom)
    path, body = srv.calls[-1]
    assert path.endswith("/finish") and body["status"] == "failed" and "chrome crashed" in body["log"][0]["msg"]


def test_upload_failure_keeps_local_copy_and_marks_failed(tmp_path):
    srv = Server(fail_channels=True)
    with pytest.raises(ApiError):
        run(srv, tmp_path)
    assert srv.calls[-1][1]["status"] == "failed"
    assert list(tmp_path.glob("run-IT-*.json"))


def test_upload_file_sends_query_and_content_type():
    seen = {}

    def handler(req):
        seen.update(path=req.url.path, query=dict(req.url.params), ctype=req.headers["content-type"], body=req.content)
        return httpx.Response(201, json={"url": "u", "pathname": "p"})

    api = ApiClient(S, transport=httpx.MockTransport(handler))
    api.upload_file("rid", "screenshot", "a.png", b"\x89PNG", "image/png")
    assert seen["query"] == {"runId": "rid", "kind": "screenshot", "name": "a.png"}
    assert seen["ctype"] == "image/png" and seen["body"] == b"\x89PNG"
