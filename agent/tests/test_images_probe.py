from pippo.probes.images import (
    ImageItem,
    PageImages,
    aspect_problem,
    card_type,
    compute_checks,
    is_broken,
    merge_into,
)
from pippo.thresholds import grade

BASE = "https://img.test/thumbnails/photos/w400-q80/ptv"


def item(src="x", nw=400, nh=225, rw=200, rh=112.5, **kw):
    d = dict(kind="img", src=src, nw=nw, nh=nh, rw=rw, rh=rh, fit="cover", complete=True, alt="", ctx=None, shown=True)
    d.update(kw)
    return ImageItem(**d)


def test_card_type_from_url():
    assert card_type(f"{BASE}/channels/abc/solidLogoPNG_1") == "logo"
    assert card_type(f"{BASE}/episodes/abc/screenshot16_9_17901") == "thumb_16_9"
    assert card_type(f"{BASE}/series/abc/poster2_3.jpg") == "poster_2_3"
    assert card_type(f"{BASE}/misc/abc.png") == "other"


def test_broken_detection():
    assert is_broken(item(nw=0, nh=0))                      # loaded but empty
    assert is_broken(item(status=404))
    assert is_broken(item(failed=True))
    assert not is_broken(item(status=200))
    assert not is_broken(item(nw=0, nh=0, shown=False))     # hidden lazy image is not counted as broken


def test_aspect_checks():
    ok = item(src=f"{BASE}/episodes/a/screenshot16_9", nw=400, nh=225)
    wrong_asset = item(src=f"{BASE}/episodes/a/screenshot16_9", nw=400, nh=300)
    assert aspect_problem(ok) is None
    assert "expected 1.78" in aspect_problem(wrong_asset)
    stretched = item(src=f"{BASE}/misc/a.png", nw=400, nh=200, rw=200, rh=200, fit="fill")
    assert "rendered ratio" in aspect_problem(stretched)
    covered = item(src=f"{BASE}/misc/a.png", nw=400, nh=200, rw=200, rh=200, fit="cover")
    assert aspect_problem(covered) is None


def test_grade_boundaries():
    assert grade("img.broken_ratio", 0.01)[0] == "ok"          # warning is strictly above 1%
    assert grade("img.broken_ratio", 0.02) == ("warning", 0.01)
    assert grade("img.broken_ratio", 0.06) == ("critical", 0.05)
    assert grade("unknown.check", 99) == ("ok", None)


def test_compute_checks_severity_and_metrics():
    items = [item(src=f"{BASE}/misc/{n}.png") for n in range(94)] + [item(src=f"{BASE}/misc/b{n}.png", status=404) for n in range(6)]
    res = compute_checks([PageImages("home", "https://p.tv/it/", items, lazy_load_max_sec=6.5)])
    m = res["pages"]["home"]["metrics"]
    assert m["img.total_count"] == 100 and m["img.broken_ratio"] == 0.06
    by_id = {c["checkId"]: c for c in res["checks"]}
    assert by_id["img.broken_ratio"]["severity"] == "critical" and not by_id["img.broken_ratio"]["passed"]
    assert by_id["img.lazy_load_timeout"]["severity"] == "warning"
    assert by_id["img.placeholder_ratio"]["passed"]
    assert "no placeholder library" in by_id["img.placeholder_ratio"]["detail"]


def test_placeholder_ratio_uses_hash_distance():
    class H(int):
        def __sub__(self, other):  # Hamming distance stand-in
            return abs(int(self) - int(other))

    items = [item(src=f"{BASE}/misc/{n}.png") for n in range(10)]
    hashes = {i.src: H(100 if n < 3 else 5000) for n, i in enumerate(items)}
    res = compute_checks([PageImages("home", "u", items)], hashes, placeholders=[("fallback.png", H(102))])
    assert res["pages"]["home"]["metrics"]["img.placeholder_ratio"] == 0.3
    assert {c["checkId"]: c for c in res["checks"]}["img.placeholder_ratio"]["severity"] == "critical"


def test_merge_keeps_broken_and_unions_virtualized_rows():
    seen: dict = {}
    merge_into(seen, [item(src="a"), item(src="b", status=404)])
    merge_into(seen, [item(src="a"), item(src="c")])            # b scrolled out of the DOM
    merge_into(seen, [item(src="b")])                            # b seen OK later: stays broken
    assert set(k[1] for k in seen) == {"a", "b", "c"}
    assert is_broken(seen[("img", "b")])
