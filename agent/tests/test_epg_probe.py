import json

import httpx

from pippo.api_client import ApiClient
from pippo.config import Settings
from pippo.epg_fetch import _url_for, fallback_template, fetch_listings
from pippo.guide import GuideChannel
from pippo.images_run import Measurement
from pippo.probes.epg import Listing, analyse_channel, compute_epg, language_mismatch_ratio, parse_listings
from pippo.profile import Profile
from pippo.runner import execute_run
from pippo.thresholds import Threshold, grade

NOW = 1_800_000_000_000
H = 3_600_000
MIN = 60_000


def L(start_min, end_min, title="Show", desc="A description long enough to count as text", image="img.png"):
    return Listing(NOW + start_min * MIN, NOW + end_min * MIN, title, desc, image)


def raw(start_min, end_min, **kw):
    d = {"startTimestamp": NOW + start_min * MIN, "endTimestamp": NOW + end_min * MIN, "title": "Show", "description": "desc", "resolvedfilePathThumb": "img"}
    d.update(kw)
    return d


def test_parse_drops_bad_entries_and_sorts():
    out = parse_listings([raw(30, 60), raw(0, 30), {"startTimestamp": "x"}, raw(90, 80), {"endTimestamp": 1}])
    assert [(l.start - NOW) // MIN for l in out] == [0, 30]
    assert out[0].image == "img"


def test_analyse_channel_now_gaps_overlaps_and_coverage():
    ls = [L(-30, 30), L(30, 60), L(62, 90), L(85, 120)]        # 2 min gap, then a 5 min overlap
    a = analyse_channel(ls, NOW)
    assert a["hasNow"] and a["nowTitle"] == "Show"
    assert [g["seconds"] for g in a["gaps"]] == [120] and [o["seconds"] for o in a["overlaps"]] == [300]
    assert a["hoursAhead"] == 2.0
    tiny = analyse_channel([L(-30, 30), L(30.5, 60), L(59.5, 90)], NOW)    # 30 s deviations are within tolerance
    assert tiny["gaps"] == [] and tiny["overlaps"] == []
    assert not analyse_channel([L(10, 40)], NOW)["hasNow"]


def test_missing_metadata_detection():
    ls = [L(-30, 30, title="TBA"), L(30, 60, desc=""), L(60, 90, image=""), L(90, 120)]
    a = analyse_channel(ls, NOW)
    assert [m["missing"] for m in a["missing"]] == [["title"], ["description"], ["image"]]
    assert analyse_channel([L(-30, 30, title="Programma")], NOW)["missing"][0]["missing"] == ["title"]


def test_language_ratio_uses_the_detector_and_ignores_unknowns():
    det = lambda t: {"ciao": "it", "hello": "en", "": None}.get(t)
    ratio, n = language_mismatch_ratio(["ciao", "ciao", "hello", ""], "IT", det)
    assert (round(ratio, 3), n) == (0.333, 3)
    assert language_mismatch_ratio([""], "it", det) == (None, 0)


def names(slugs):
    return {s: s.upper() for s in slugs}


def healthy(n=12, hours=20):
    return {f"c{i}": [L(-30, 30), L(30, hours * 60)] for i in range(n)}


def test_healthy_guide_passes_every_check():
    res = compute_epg(healthy(), names=names(healthy()), now_ms=NOW, expected_language="it", detector=lambda t: "it")
    assert all(c["passed"] for c in res["checks"]) and res["issues"] == []
    assert res["metrics"]["epg.coverage_hours"] == 20.0 and res["metrics"]["epg.channel_count"] == 12
    assert all(all(c["passed"] for c in r["checks"]) for r in res["channel_results"].values())


def test_coverage_is_graded_lower_is_worse():
    data = healthy()
    data["c3"] = [L(-30, 30), L(30, 90)]                          # only 1.5 h ahead
    res = compute_epg(data, names=names(data), now_ms=NOW, expected_language=None)
    cov = next(c for c in res["checks"] if c["checkId"] == "epg.coverage_hours")
    assert cov["severity"] == "critical" and cov["value"] == 1.5 and "C3" in cov["detail"]
    data["c3"] = [L(-30, 30), L(30, 300)]                          # 4.5 h: between 2 and 6
    cov = next(c for c in compute_epg(data, names=names(data), now_ms=NOW, expected_language=None)["checks"] if c["checkId"] == "epg.coverage_hours")
    assert cov["severity"] == "warning" and cov["threshold"] == 6


def test_per_channel_checks_and_issue_rows():
    data = healthy()
    data["c1"] = [L(10, 40), L(45, 100)]                           # nothing on air now, plus a 5 min gap
    res = compute_epg(data, names=names(data), now_ms=NOW, expected_language=None)
    by = {c["checkId"]: c for c in res["channel_results"]["c1"]["checks"]}
    assert by["epg.no_now_program"]["severity"] == "critical" and not by["epg.no_now_program"]["passed"]
    assert by["epg.gap"]["severity"] == "warning"
    assert res["metrics"]["epg.channels_no_now"] == 1 and res["metrics"]["epg.channels_with_gaps"] == 1
    assert {i["type"] for i in res["issues"]} == {"no_now_program", "gap"}
    assert all(i["channel"] == "C1" for i in res["issues"])


def test_missing_metadata_and_language_checks_have_thresholds():
    data = healthy()
    data["c0"] = [L(-30, 30, title="TBA"), L(30, 90, desc="", image="")] + [L(90 + 60 * i, 150 + 60 * i) for i in range(0, 20)]
    res = compute_epg(data, names=names(data), now_ms=NOW, expected_language="it", detector=lambda t: "en")
    by = {c["checkId"]: c for c in res["checks"]}
    assert by["epg.missing_metadata"]["severity"] == "warning" and by["epg.missing_metadata"]["detail"] == "2 of 44 programmes"
    assert by["epg.language_mismatch"]["severity"] == "warning" and by["epg.language_mismatch"]["value"] == 1.0
    few = compute_epg({"a": [L(-30, 30), L(30, 400)]}, names={"a": "A"}, now_ms=NOW, expected_language="it", detector=lambda t: "en")
    assert "epg.language_mismatch" not in {c["checkId"] for c in few["checks"]}      # too few descriptions to judge


def test_api_failure_and_empty_guide_are_critical_and_stop_there():
    res = compute_epg({}, names={}, now_ms=NOW, expected_language="it")
    assert res["checks"][0]["checkId"] == "epg.api_failed" and res["checks"][0]["severity"] == "critical"
    assert res["channel_results"] == {}
    partial = compute_epg(healthy(), names=names(healthy()), now_ms=NOW, expected_language=None, api_error="3 guide request(s) failed, first: c1: HTTP 500")
    assert partial["checks"][0]["severity"] == "critical" and "HTTP 500" in partial["checks"][0]["detail"]


def test_threshold_overrides_apply_to_epg_checks():
    data = healthy(hours=5)                                        # 5 h ahead: warning by default
    relaxed = {"epg.coverage_hours": Threshold(warn=3, critical=1)}
    cov = next(c for c in compute_epg(data, names=names(data), now_ms=NOW, expected_language=None, overrides=relaxed)["checks"] if c["checkId"] == "epg.coverage_hours")
    assert cov["passed"]
    assert grade("epg.coverage_hours", 8) == ("ok", None) and grade("epg.coverage_hours", 1) == ("critical", 2)


# --- fetching -------------------------------------------------------------------------------

def test_url_template_replaces_slug_and_start_but_keeps_the_hash():
    tpl = "https://pluto.tv/api/tn/video/graphql/?operationName=Listing&variables=" + json.dumps(
        {"channelSlug": "x", "params": {"rows": 50, "start": 6, "userRegistrationCountry": "IT"}}, separators=(",", ":")
    ) + '&extensions={"tnPersistedDocumentHash":"abc"}'
    from urllib.parse import parse_qsl, urlparse

    q = dict(parse_qsl(urlparse(_url_for(tpl, "rai-news-it", 100)).query))
    v = json.loads(q["variables"])
    assert v["channelSlug"] == "rai-news-it" and v["params"]["start"] == 100 and v["params"]["userRegistrationCountry"] == "IT"
    assert "abc" in q["extensions"]


def test_fallback_template_uses_the_profile_hash():
    pr = Profile({"country": "IT", "entry_url": "https://pluto.tv/it/", "routes": {"listing_hash": "deadbeef"}})
    assert "deadbeef" in fallback_template(pr) and "userRegistrationCountry" in fallback_template(pr)
    assert fallback_template(Profile({"country": "IT", "entry_url": "https://pluto.tv/it/", "routes": {}})) is None


class FakePage:
    """Serves 50 listings per request until `total`, one hour each, starting now."""

    def __init__(self, total=130, fail_slugs=()):
        self.total, self.fail, self.calls = total, set(fail_slugs), []
        self.request = self

    def get(self, url, headers=None, timeout=None):
        from urllib.parse import parse_qsl, urlparse

        v = json.loads(dict(parse_qsl(urlparse(url).query))["variables"])
        slug, start = v["channelSlug"], v["params"]["start"]
        self.calls.append((slug, start))
        assert headers["apollo-require-preflight"] == "true"
        if slug in self.fail:
            return _Resp(500, {})
        batch = [{"startTimestamp": NOW + i * H, "endTimestamp": NOW + (i + 1) * H} for i in range(start, min(start + 50, self.total))]
        return _Resp(200, {"data": {"listings": {"listing": batch, "start": start, "total": self.total}}})


class _Resp:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def json(self):
        return self._body


TPL = "https://pluto.tv/api/tn/video/graphql/?operationName=Listing&variables=" + json.dumps(
    {"channelSlug": "x", "params": {"rows": 50, "start": 0}}, separators=(",", ":")
)
CH = lambda s: GuideChannel(s, s, None, None, None)


def test_fetch_pages_until_the_horizon_and_reports_failures():
    page = FakePage()
    out = fetch_listings(page, TPL, [CH("a")], horizon_hours=12, now_ms=NOW)
    assert page.calls == [("a", 0)] and len(out.listings["a"]) == 50          # 50 h of data covers a 12 h horizon at once
    page = FakePage()
    fetch_listings(page, TPL, [CH("a")], horizon_hours=120, now_ms=NOW)
    assert [c[1] for c in page.calls] == [0, 50, 100]                          # keeps paging until total
    page = FakePage(fail_slugs={"bad"})
    out = fetch_listings(page, TPL, [CH("a"), CH("bad")], horizon_hours=12, now_ms=NOW)
    assert "a" in out.listings and "bad" not in out.listings
    assert out.error.startswith("1 guide request(s) failed") and "bad: HTTP 500" in out.error


# --- runner uploads the EPG result --------------------------------------------------------------

def test_runner_uploads_epg_before_the_channels(tmp_path):
    S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0)
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path == "/api/agent/runs":
            return httpx.Response(201, json={"id": "run-1", "status": "running"})
        if req.url.path.endswith("/finish"):
            return httpx.Response(200, json={"counts": {}})
        return httpx.Response(201, json={"ok": True})

    ch = GuideChannel("a", "A", None, None, None)
    m = Measurement({"pages": {"epg": {"url": "u", "metrics": {}}}, "checks": []}, [ch], {}, 1, epg={"metrics": {}, "checks": [], "issues": []})
    api = ApiClient(S, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    execute_run(api, S, "IT", lambda: m, detect=lambda s: "IT", reports_dir=tmp_path)
    assert calls == ["/api/agent/runs", "/api/agent/runs/run-1/images", "/api/agent/runs/run-1/epg", "/api/agent/runs/run-1/channels", "/api/agent/runs/run-1/finish"]
