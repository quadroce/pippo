from pippo.probes.subtitles import compute_metrics, evaluate, measure_subtitles
from pippo.recorder import SubtitleConfig, subtitle_config_from_profile
from pippo.thresholds import Threshold

PLAYLIST = {"t": 1, "kind": "playlist", "path": "/ch/hls/channel/abc/subtitle/subs/en/playlist.m3u8", "status": 200}
PLACEHOLDER = {"t": 2, "kind": "segment", "path": "/playout/placeholder/subtitles/vtt/rev/1/pts/90000/subtitle.vtt", "status": 200}
REAL = {"t": 2, "kind": "segment", "path": "/ch/hls/channel/abc/subtitle/subs/en/seg_1.vtt", "status": 200}


def info(declared=True, enabled=True, error=None, lang="en"):
    return {"declared": [{"lang": lang, "label": "English", "mode": "disabled"}] if declared else [], "enabled": enabled, "enabledAtMs": 10_000, "enableError": error}


def samples(cues=0, active=None, dom=None, n=5):
    return [{"t": 12_000 + i * 2000, "ct": 20 + i * 2, "tracks": [{"lang": "en", "mode": "hidden", "cues": cues, "active": active or []}], "dom": dom} for i in range(n)]


def rec(network=None, subtitle_info=None, subs=None, cues=None, audio=None):
    return {
        "windowSec": 60,
        "buffer": {"events": [], "frames": [], "audio": audio or [], "info": {}, "subs": subs if subs is not None else samples(), "subCues": cues or []},
        "network": network if network is not None else [PLAYLIST, PLACEHOLDER],
        "subtitleInfo": subtitle_info if subtitle_info is not None else info(),
    }


def cue(start, end, text="Hello there"):
    return {"start": start, "end": end, "text": text}


def speech(n, start_ct=20.0, db=-30):
    return [{"t": i * 500, "db": db, "muted": False, "paused": False, "ct": start_ct + i * 0.5} for i in range(n)]


def test_nothing_declared_is_not_a_failure():
    m = compute_metrics(rec(network=[], subtitle_info=info(declared=False, enabled=False)))
    assert m == {"sub.declared": 0, "sub.state": "no_subtitles"}
    assert measure_subtitles(rec(network=[], subtitle_info=info(declared=False, enabled=False)))["checks"] == []


def test_a_manifest_only_declaration_still_counts_as_declared():
    m = compute_metrics(rec(network=[PLAYLIST], subtitle_info={"declared": [], "enabled": False, "enableError": "no menu"}))
    assert m["sub.declared"] == 1 and m["sub.state"] == "not_enabled"


def test_menu_that_could_not_be_driven_is_not_judged():
    out = measure_subtitles(rec(subtitle_info=info(enabled=False, error="menu button not found")))
    assert out["metrics"]["sub.state"] == "not_enabled" and "menu button" in out["metrics"]["sub.note"]
    assert out["checks"] == []                                           # no verdict on a track that was never switched on


def test_placeholder_only_is_its_own_state_and_not_critical():
    out = measure_subtitles(rec())
    m = out["metrics"]
    assert m["sub.state"] == "placeholder_only" and m["sub.placeholder_only"] == 1 and m["sub.declared_not_loaded"] == 0
    by = {c["checkId"]: c for c in out["checks"]}
    assert by["sub.declared_not_loaded"]["passed"] and by["sub.segment_errors"]["passed"]


def test_enabled_track_with_no_cues_and_failing_segments_is_critical():
    failing = {"t": 2, "kind": "segment", "path": "/ch/subtitle/subs/en/seg_1.vtt", "status": 404}
    out = measure_subtitles(rec(network=[PLAYLIST, failing]))
    assert out["metrics"]["sub.state"] == "not_loaded"
    by = {c["checkId"]: c for c in out["checks"]}
    assert by["sub.declared_not_loaded"]["severity"] == "critical" and not by["sub.declared_not_loaded"]["passed"]
    assert by["sub.segment_errors"]["severity"] == "warning" and "404" in by["sub.segment_errors"]["detail"]


def test_enabled_track_that_requested_nothing_is_not_loaded():
    assert compute_metrics(rec(network=[]))["sub.state"] == "not_loaded"   # enabled, silence from the CDN and the player


def test_aborted_subtitle_requests_are_not_errors():
    aborted = {"t": 2, "kind": "segment", "path": "/ch/subtitle/subs/en/seg_2.vtt", "status": 0, "failed": True, "error": "net::ERR_ABORTED"}
    assert compute_metrics(rec(network=[PLAYLIST, REAL, aborted], subs=samples(cues=3), cues=[cue(1, 2)]))["sub.segment_errors"] == 0


def test_cues_arriving_means_ok_and_cue_gap_counts_speech_without_a_cue():
    cues = [cue(20, 24), cue(26, 28)]                                    # nothing between 29.5 s and the end of the speech
    out = measure_subtitles(rec(network=[PLAYLIST, REAL], subs=samples(cues=2), cues=cues, audio=speech(80)))
    m = out["metrics"]
    assert m["sub.state"] == "ok" and m["sub.cues_loaded"] == 2
    assert m["sub.cue_gap"] > 5                                          # ~10 s of speech uncovered at 0.5 s per sample
    assert {c["checkId"]: c for c in out["checks"]}["sub.cue_gap"]["passed"]    # still below the 30 s threshold
    long_gap = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=1), cues=[cue(20, 21)], audio=speech(200)))
    assert long_gap["sub.cue_gap"] >= 30 and not {c["checkId"]: c for c in evaluate(long_gap)}["sub.cue_gap"]["passed"]


def test_silence_does_not_count_as_a_gap():
    m = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=1), cues=[cue(20, 21)], audio=speech(100, db=-70)))
    assert m["sub.cue_gap"] == 0


def test_language_mismatch_compares_cue_text_with_the_declared_language():
    english = [cue(i, i + 1, "I told you that we would go to the market tomorrow morning") for i in range(12)]
    ok = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=12), cues=english))
    assert ok["sub.language_mismatch"] == 0
    italian = [cue(i, i + 1, "Ti avevo detto che saremmo andati al mercato domani mattina presto") for i in range(12)]
    bad = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=12), cues=italian))
    assert bad["sub.language_mismatch"] == 1 and bad["sub.detected_language"] == "it"
    check = {c["checkId"]: c for c in evaluate(bad)}["sub.language_mismatch"]
    assert check["severity"] == "warning" and "it" in check["detail"] and "en" in check["detail"]
    few = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=3), cues=italian[:3]))
    assert "sub.language_mismatch" not in few                            # too little text to judge


def test_cues_not_rendered_needs_active_cues_and_a_known_text_element():
    active = samples(cues=5, active=["Hello"], dom="")
    m = compute_metrics(rec(network=[PLAYLIST, REAL], subs=active, cues=[cue(1, 2)]))
    assert m["sub.cues_not_rendered"] == 1
    shown = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=5, active=["Hello"], dom="Hello"), cues=[cue(1, 2)]))
    assert shown["sub.cues_not_rendered"] == 0
    unknown = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=5, active=["Hello"], dom=None), cues=[cue(1, 2)]))
    assert "sub.cues_not_rendered" not in unknown and "not checked" in unknown["sub.render_note"]
    idle = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=5, active=[], dom=""), cues=[cue(1, 2)]))
    assert "sub.cues_not_rendered" not in idle                           # no active cue, nothing to render


def test_overrides_change_the_grade():
    relaxed = {"sub.cue_gap": Threshold(warn=100)}
    m = compute_metrics(rec(network=[PLAYLIST, REAL], subs=samples(cues=1), cues=[cue(20, 21)], audio=speech(200)))
    assert {c["checkId"]: c for c in evaluate(m, relaxed)}["sub.cue_gap"]["passed"]


def test_subtitle_config_comes_from_the_profile_with_sane_defaults():
    cfg = subtitle_config_from_profile({})
    assert isinstance(cfg, SubtitleConfig) and cfg.menu_button == "button.btn-audio-cc" and cfg.consent_reject == ("Rifiuta",)
    custom = subtitle_config_from_profile(
        {"selectors": {"subtitles_menu_button": "#cc", "subtitles_off_words": ["aus"], "subtitle_text": ".cap"}, "consent": {"reject_button_text": ["Reject"]}}
    )
    assert (custom.menu_button, custom.off_words, custom.text_selector, custom.consent_reject) == ("#cc", ("aus",), ".cap", ("Reject",))


def test_real_segments_with_no_cues_are_loaded_empty_and_judged_through_the_speech_gap():
    quiet = compute_metrics(rec(network=[PLAYLIST, REAL], audio=speech(30, db=-70)))
    assert quiet["sub.state"] == "loaded_empty" and quiet["sub.declared_not_loaded"] == 0 and quiet["sub.cue_gap"] == 0
    talking = compute_metrics(rec(network=[PLAYLIST, REAL], audio=speech(200)))
    assert talking["sub.state"] == "loaded_empty" and talking["sub.cue_gap"] >= 30
    failed = {c["checkId"]: c for c in evaluate(talking)}["sub.cue_gap"]
    assert failed["severity"] == "warning" and not failed["passed"]


def test_language_served_by_the_cdn_is_compared_with_the_declared_one():
    italian_segment = {"t": 2, "kind": "segment", "path": "/20260614_030737/text/text_it/161269182450000.vtt", "status": 200}
    m = compute_metrics(rec(network=[PLAYLIST, italian_segment], subs=samples(cues=2), cues=[cue(1, 2, "Oh!")]))
    assert m["sub.served_language"] == "it" and m["sub.language_mismatch"] == 1
    detail = {c["checkId"]: c for c in evaluate(m)}["sub.language_mismatch"]["detail"]
    assert "declared 'en'" in detail and "served as 'it'" in detail
    english_segment = {"t": 2, "kind": "segment", "path": "/20260610_180121/text/text_en/161269168950000.vtt", "status": 200}
    ok = compute_metrics(rec(network=[PLAYLIST, english_segment], subs=samples(cues=2), cues=[cue(1, 2, "Oh!")]))
    assert ok["sub.served_language"] == "en" and "sub.language_mismatch" not in ok


def test_placeholder_paths_say_nothing_about_language():
    m = compute_metrics(rec())
    assert "sub.served_language" not in m and "sub.language_mismatch" not in m


def test_enable_subtitles_treats_a_remembered_choice_as_already_on():
    from pippo.recorder import enable_subtitles

    class P:
        def evaluate(self, js):
            if "textTracks" in js and "map" in js:
                return [{"lang": "en", "label": "English", "mode": "hidden"}]
            return 4242

    info = enable_subtitles(P(), SubtitleConfig())
    assert info["enabled"] is True and info["enabledAtMs"] == 4242 and info["enableError"] is None
