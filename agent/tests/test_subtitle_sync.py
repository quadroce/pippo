import base64

import numpy as np

from pippo.probes.subtitle_sync import (
    Transcript,
    Word,
    compute_sync,
    cue_tokens,
    evaluate,
    match_cue,
    measure_sync,
    pcm_to_samples,
)
from pippo.thresholds import Threshold


def words(text: str, start: float, step: float = 0.4) -> list[Word]:
    return [Word(w, start + i * step, start + i * step + 0.3) for i, w in enumerate(text.split())]


SENTENCES = [
    "we went to the market early this morning",
    "the weather was surprisingly warm for october",
    "nobody expected the train to arrive on time",
    "she opened the window and looked at the sea",
    "after dinner they decided to walk along the river",
]


def world(offset: float, ct0: float = 100.0, gap: float = 8.0):
    """Cues whose start is `offset` seconds after the words are spoken, audio starting at media time ct0."""
    spoken, cues, t = [], [], 2.0
    for s in SENTENCES:
        spoken += words(s, t)
        cues.append({"start": ct0 + t + offset, "end": ct0 + t + offset + 3.0, "text": s.capitalize() + "."})
        t += gap
    return cues, Transcript(spoken, "en", 0.99), ct0


def test_cue_tokens_drop_speaker_labels_dashes_and_sound_notes():
    assert cue_tokens("- Who says you're not romantic.") == ["who", "says", "you're", "not", "romantic"]
    assert cue_tokens("DAVID DANIEL: Two\npopular streaming") == ["two", "popular", "streaming"]
    assert cue_tokens("(both): Oh!") == ["oh"]
    assert cue_tokens("[applause] Thank you all") == ["thank", "you", "all"]
    assert cue_tokens("<i>Italics</i> and ♪ la la ♪ words") == ["italics", "and", "words"]
    assert cue_tokens("It’s fine") == ["it's", "fine"]


def test_match_cue_finds_the_best_window_near_the_cue_and_rejects_poor_matches():
    spoken = [(w.word, w.start) for w in words("one two three the quick brown fox jumps over the lazy dog", 0)]
    hit = match_cue(["the", "quick", "brown", "fox"], spoken, cue_ct=101.2, audio_start_ct=100.0)
    assert hit and hit[0] == 1.0 and abs(hit[1] - 101.2) < 1e-6
    assert match_cue(["completely", "different", "words", "here"], spoken, 101.0, 100.0) is None
    assert match_cue(["the", "quick", "brown", "fox"], spoken, cue_ct=500.0, audio_start_ct=100.0) is None   # outside the search radius


def test_in_sync_late_and_early_subtitles():
    for offset in (0.0, 1.8, -1.2):
        cues, tr, ct0 = world(offset)
        m = compute_sync(cues, tr, ct0, 45.0, "en")
        assert m["sub.sync_matched"] == 5 and m["sub.sync_confidence"] == 1.0
        assert abs(m["sub.sync_offset_signed"] - offset) < 0.01
        assert abs(m["sub.sync_offset"] - abs(offset)) < 0.01
        assert m["sub.sync_spread"] < 0.01                       # every cue is off by the same amount


def test_a_few_wrong_matches_do_not_move_the_median():
    cues, tr, ct0 = world(1.0)
    cues[0]["text"] = "totally unrelated sentence about something else"      # unmatched
    m = compute_sync(cues, tr, ct0, 45.0, "en")
    assert m["sub.sync_matched"] == 4 and abs(m["sub.sync_offset_signed"] - 1.0) < 0.01


def test_speech_recognition_errors_are_tolerated():
    cues, tr, ct0 = world(0.5)
    garbled = [Word("wen" if w.word == "went" else w.word, w.start, w.end) for w in tr.words]
    m = compute_sync(cues, Transcript(garbled, "en"), ct0, 45.0, "en")
    assert m["sub.sync_matched"] == 5 and abs(m["sub.sync_offset_signed"] - 0.5) < 0.01


def test_translation_is_not_aligned():
    cues, tr, ct0 = world(0.0)
    m = compute_sync(cues, Transcript(tr.words, "it"), ct0, 45.0, "en")
    assert "sub.sync_offset" not in m and "translation" in m["sub.sync_note"] and m["sub.spoken_language"] == "it"


def test_low_confidence_suppresses_the_offset():
    cues, tr, ct0 = world(0.0)
    for c in cues[:4]:
        c["text"] = "nothing like the audio at all today"
    m = compute_sync(cues, tr, ct0, 45.0, "en")
    assert m["sub.sync_confidence"] < 0.4 and "sub.sync_offset" not in m and "not evaluated" in m["sub.sync_note"]


def test_too_few_eligible_cues_or_no_speech():
    m = compute_sync([{"start": 105.0, "end": 106.0, "text": "Oh no"}], Transcript(words("oh no", 5), "en"), 100.0, 45.0, "en")
    assert m["sub.sync_eligible"] == 0 and "sub.sync_offset" not in m
    cues, _, ct0 = world(0.0)
    assert "no speech" in compute_sync(cues, Transcript([], "en"), ct0, 45.0, "en")["sub.sync_note"]
    outside = compute_sync(world(0.0)[0], world(0.0)[1], 900.0, 45.0, "en")       # audio window far from the cues
    assert outside["sub.sync_eligible"] == 0


def test_grading_thresholds_and_overrides():
    def check(off, overrides=None):
        return evaluate({"sub.sync_offset": abs(off), "sub.sync_offset_signed": off, "sub.sync_matched": 5, "sub.sync_confidence": 1.0}, overrides)[0]

    assert check(0.4)["passed"]
    assert check(1.5)["severity"] == "warning" and "late" in check(1.5)["detail"]
    assert check(-3.0)["severity"] == "critical" and "early" in check(-3.0)["detail"]
    assert check(1.5, {"sub.sync_offset": Threshold(warn=2.0, critical=4.0)})["passed"]
    assert evaluate({"sub.sync_note": "x"}) == []


def pcm_payload(seconds=2.0):
    data = (np.sin(np.linspace(0, 440, int(16000 * seconds))) * 12000).astype(np.int16)
    return {"b64": base64.b64encode(data.tobytes()).decode(), "rate": 16000, "samples": len(data), "startCt": 100.0}


def test_pcm_payload_roundtrip():
    s = pcm_to_samples(pcm_payload(1.0))
    assert s.dtype == np.float32 and len(s) == 16000 and 0.3 < float(abs(s).max()) < 0.4


class FakeTranscriber:
    def __init__(self, transcript):
        self.transcript, self.calls = transcript, []

    def transcribe(self, samples, language=None):
        self.calls.append(len(samples))
        return self.transcript


def test_measure_sync_end_to_end_with_a_fake_transcriber():
    cues, tr, ct0 = world(2.0)
    pcm = pcm_payload(45.0)
    pcm["startCt"] = ct0
    rec = {"pcm": pcm, "buffer": {"subCues": cues}, "subtitleInfo": {"enabled": True, "declared": [{"lang": "en"}]}}
    ft = FakeTranscriber(tr)
    out = measure_sync(rec, ft)
    assert ft.calls == [45 * 16000]
    assert abs(out["metrics"]["sub.sync_offset_signed"] - 2.0) < 0.01
    assert out["checks"][0]["severity"] == "warning"                            # 2.0 s is above 1.0 and below 2.5


def test_measure_sync_does_nothing_without_audio_cues_or_enabled_subtitles():
    cues, tr, ct0 = world(0.0)
    ft = FakeTranscriber(tr)
    base = {"pcm": pcm_payload(5.0), "buffer": {"subCues": cues}, "subtitleInfo": {"enabled": True, "declared": [{"lang": "en"}]}}
    for broken in ({**base, "pcm": None}, {**base, "buffer": {"subCues": []}}, {**base, "subtitleInfo": {"enabled": False}}):
        assert measure_sync(broken, ft) == {"metrics": {}, "checks": []}
    assert ft.calls == []                                                       # the model is never loaded for nothing


def rollup_world(lag: float, ct0: float = 100.0):
    """Live-style captions: every word of a sentence produces a new cue holding the sentence so far,
    starting `lag` seconds after that word was spoken."""
    spoken, cues, t = [], [], 2.0
    for s in SENTENCES:
        ws = words(s, t)
        spoken += ws
        for k in range(3, len(ws) + 1):
            cues.append({"start": ct0 + ws[k - 1].start + lag, "end": ct0 + ws[k - 1].start + lag + 1.0, "text": " ".join(w.word for w in ws[:k]).upper()})
        t += 9.0
    return cues, Transcript(spoken, "en", 0.99), ct0


def test_rollup_captions_are_recognised_and_measured_against_the_last_word():
    from pippo.probes.subtitle_sync import is_rollup

    cues, tr, ct0 = rollup_world(5.0)
    assert is_rollup(cues)
    m = compute_sync(cues, tr, ct0, 50.0, "en")
    assert m["sub.sync_mode"] == "roll-up"
    assert abs(m["sub.sync_offset_signed"] - 5.0) < 0.3          # comparing with the FIRST word would give 6 to 8 s
    assert m["sub.sync_spread"] < 0.5


def test_pop_on_subtitles_are_not_mistaken_for_rollup():
    from pippo.probes.subtitle_sync import is_rollup

    cues, tr, ct0 = world(0.0)
    assert not is_rollup(cues)
    assert compute_sync(cues, tr, ct0, 45.0, "en")["sub.sync_mode"] == "pop-on"
    assert not is_rollup(cues[:3])                                # too few pairs to say


def test_noisy_caption_text_cannot_overrule_the_declared_language(monkeypatch):
    import pippo.probes.subtitle_sync as ss

    cues, tr, ct0 = world(0.0)
    pcm = pcm_payload(45.0)
    pcm["startCt"] = ct0
    rec = {"pcm": pcm, "buffer": {"subCues": cues}, "subtitleInfo": {"enabled": True, "declared": [{"lang": "en"}]}}
    monkeypatch.setattr(ss, "detect_language_confident", lambda text: None)       # detector unsure: declared language is used
    assert "sub.sync_offset" in measure_sync(rec, FakeTranscriber(tr))["metrics"]
    monkeypatch.setattr(ss, "detect_language_confident", lambda text: "de")       # detector sure and different: it is a translation
    out = measure_sync(rec, FakeTranscriber(tr))
    assert "sub.sync_offset" not in out["metrics"] and "translation" in out["metrics"]["sub.sync_note"]


def test_detect_language_confident_returns_none_for_short_or_empty_text():
    from pippo.probes.epg import detect_language_confident

    assert detect_language_confident("") is None
    assert detect_language_confident("Il commissario di polizia viene trasferito a Roma per indagare sul caso") == "it"
