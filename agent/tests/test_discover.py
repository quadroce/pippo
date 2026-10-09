from pippo.discover import draft_profile, sanitize_url, summarize


def test_sanitize_drops_query_but_keeps_operation():
    u = "https://pluto.tv/api/tn/video/graphql/?operationName=ChannelsMany&variables=%7B%7D&jwt=SECRET"
    assert sanitize_url(u) == "https://pluto.tv/api/tn/video/graphql/?operationName=ChannelsMany"
    assert sanitize_url("https://x.test/a.m3u8?jwt=SECRET&sid=1") == "https://x.test/a.m3u8"


def test_summary_and_draft_never_contain_query_secrets():
    reqs = [
        {"method": "GET", "url": "https://p.tv/guide?jwt=SECRET", "status": 200, "type": "xhr", "contentType": "", "length": None},
        {"method": "GET", "url": "https://p.tv/x/playlist.m3u8?jwt=SECRET", "status": 200, "type": "media", "contentType": "", "length": None},
    ]
    s = summarize(reqs)
    assert "SECRET" not in str(s)
    assert "SECRET" not in draft_profile("IT", "https://pluto.tv/it/", s, {})
