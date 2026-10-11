import json

import httpx

from pippo.api_client import ApiClient
from pippo.config import Settings
from pippo.guide import GuideChannel
from pippo.images_run import Measurement
from pippo.players_run import ChannelOutcome
from pippo.probes.epg import Listing
from pippo.probes.epg_render import RowCollector, UiRow, compute_render, normalize, now_playing_check, title_matches, titles_on_air
from pippo.runner import execute_run
from pippo.thresholds import Threshold

NOW = 1_800_000_000_000
MIN = 60_000


def chan(i, name=None):
    return GuideChannel(f"c{i}", name or f"Channel {i}", None, None, f"/it/watch/live-tv/{100 + i}/")


def L(start_min, end_min, title):
    return Listing(NOW + start_min * MIN, NOW + end_min * MIN, title, "d", "i")


def row(i, title="Show", tiles=10, empty=0, at=NOW):
    return UiRow(str(100 + i), f"Channel {i}", title, tiles, empty, at)


def good_world(n=12):
    channels = [chan(i) for i in range(n)]
    rows = {str(100 + i): row(i) for i in range(n)}
    listings = {f"c{i}": [L(-10, 20, "Show"), L(20, 50, "Next")] for i in range(n)}
    return channels, rows, listings


def checks(res):
    return {c["checkId"]: c for c in res["checks"]}


def test_normalize_and_matching_is_forgiving_about_case_and_punctuation():
    assert normalize("  Forensic   Files!! ") == "forensic files"
    assert title_matches("FORENSIC FILES", {"forensic files"})
    assert title_matches("Forensic Files", {"forensic files: la serie"})      # one contains the other
    assert not title_matches("Other", {"forensic files"})
    assert not title_matches("", {"x"}) and not title_matches("x", set())


def test_titles_on_air_include_programmes_just_started_or_ended():
    ls = [L(-30, -1, "Ended"), L(-1, 30, "Now"), L(30, 60, "Later"), L(61, 90, "Much later")]
    assert titles_on_air(ls, NOW) == {"ended", "now"}                        # ended 1 min ago still counts; 30 min ahead does not


def test_healthy_guide_passes_every_rendering_check():
    channels, rows, listings = good_world()
    res = compute_render(rows, channels, listings, 1.2)
    assert all(c["passed"] for c in res["checks"]) and res["issues"] == []
    assert res["metrics"]["epg.rendered_channels"] == 12
    assert all(all(c["passed"] for c in r["checks"]) for r in res["channel_checks"].values())


def test_channel_count_difference_in_both_directions_is_critical():
    channels, rows, listings = good_world()
    del rows["103"]                                                          # missing from the page
    rows["999"] = UiRow("999", "Ghost", "x", 3, 0, NOW)                      # rendered but not in the API
    c = checks(compute_render(rows, channels, listings, 1.0))["epg.render_channel_count"]
    assert c["severity"] == "critical" and c["value"] == 2.0
    assert "not rendered: Channel 3" in c["detail"] and "not in the API: Ghost" in c["detail"]


def test_highlight_mismatch_is_per_channel_and_tolerates_a_boundary_crossing():
    channels, rows, listings = good_world()
    rows["101"].title = "Wrong programme"
    rows["102"].title = "Next"                                              # the next programme, but 20 min early: outside the tolerance
    res = compute_render(rows, channels, listings, 1.0)
    assert res["metrics"]["epg.highlight_mismatches"] == 2
    one = {c["checkId"]: c for c in res["channel_checks"]["c1"]["checks"]}["epg.highlight_mismatch"]
    assert one["severity"] == "warning" and "Wrong programme" in one["detail"]
    rows["102"].seen_at_ms = NOW + 19 * MIN + 30_000                          # 30 s before the boundary: "Next" is acceptable
    assert compute_render(rows, channels, listings, 1.0)["metrics"]["epg.highlight_mismatches"] == 1


def test_channels_without_listings_or_without_a_row_are_not_judged():
    channels, rows, listings = good_world(3)
    listings["c0"] = []
    del rows["101"]
    res = compute_render(rows, channels, listings, 1.0)
    assert "c0" not in res["channel_checks"] and "c1" not in res["channel_checks"] and "c2" in res["channel_checks"]


def test_empty_cells_and_load_time_thresholds_and_overrides():
    channels, rows, listings = good_world()
    rows["100"].empty_tiles = 5                                              # 5 of 120 tiles = 4.2 %
    res = compute_render(rows, channels, listings, 6.5)
    by = checks(res)
    assert by["epg.empty_cells"]["severity"] == "warning" and by["epg.scroll_load_time"]["severity"] == "warning"
    relaxed = compute_render(rows, channels, listings, 6.5, {"epg.empty_cells": Threshold(warn=0.10), "epg.scroll_load_time": Threshold(warn=10)})
    assert all(c["passed"] for c in relaxed["checks"])


def test_row_collector_merges_virtualized_rows_and_keeps_the_worst_empty_count():
    rc = RowCollector()
    r = lambda href, tiles, empty, title="A": {"href": href, "label": f"Add {title} to favorites", "title": title, "tiles": tiles, "emptyTiles": empty}
    rc.ingest([r("/it/watch/live-tv/1/", 5, 2), r(None, 3, 0)], NOW)          # a row without a channel link is ignored
    rc.ingest([r("/it/watch/live-tv/1/", 8, 0), r("/it/watch/live-tv/2/", 4, 0, "B")], NOW + 1000)
    assert set(rc.rows) == {"1", "2"}
    assert rc.rows["1"].tiles == 8 and rc.rows["1"].empty_tiles == 2 and rc.rows["1"].name == "A"
    rc.ingest([r("/it/watch/live-tv/1/", 3, 9)], NOW + 2000)                  # an emptier, later view must not replace the fuller one
    assert rc.rows["1"].tiles == 8 and rc.rows["1"].empty_tiles == 9


# --- now playing ----------------------------------------------------------------------------------

def test_now_playing_check():
    ls = [L(-10, 20, "Forensic Files"), L(20, 50, "Next")]
    assert now_playing_check("Forensic Files", NOW, ls)["passed"]
    bad = now_playing_check("Something else", NOW, ls)
    assert bad["severity"] == "warning" and not bad["passed"] and "Something else" in bad["detail"]
    assert now_playing_check(None, NOW, ls) is None and now_playing_check("x", NOW, []) is None and now_playing_check("x", NOW, None) is None
    assert now_playing_check("x", NOW, [L(500, 600, "Far")]) is None          # nothing on air: reported elsewhere


def test_runner_adds_the_now_playing_check_to_the_channel_result(tmp_path):
    S = Settings(api_base_url="https://x.test", agent_api_key="k", http_retries=0)
    posted = []

    def handler(req: httpx.Request):
        if req.url.path == "/api/agent/runs":
            return httpx.Response(201, json={"id": "run-1", "status": "running"})
        if req.url.path.endswith("/finish"):
            return httpx.Response(200, json={"counts": {}})
        if req.url.path.endswith("/channels"):
            posted.append(json.loads(req.content))
        return httpx.Response(201, json={"ok": True})

    ch = GuideChannel("a", "A", None, None, "/it/watch/live-tv/1/")
    m = Measurement({"pages": {}, "checks": []}, [ch], {}, 1, listings={"a": [L(-10, 20, "Forensic Files")]})
    now = int(__import__("time").time() * 1000)
    m.listings = {"a": [Listing(now - 10 * MIN, now + 20 * MIN, "Forensic Files", "d", "i")]}

    def players(channels, cb):
        cb(ChannelOutcome(ch, {"player.ttff": 900}, [], [], None, None, "Not the show", now))

    api = ApiClient(S, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    execute_run(api, S, "IT", lambda: m, detect=lambda s: "IT", reports_dir=tmp_path, measure_players=players)
    sent = posted[0]
    check = next(c for c in sent["checks"] if c["checkId"] == "player.now_playing_mismatch")
    assert check["severity"] == "warning" and sent["metrics"]["player.now_playing_mismatch"] == 1
