"""Subtitle sync (docs/03-CHECK-CATALOG.md `sub.sync_offset`, `sub.sync_confidence`).

For a sample channel the recorder captures the audio (16 kHz mono PCM) while the subtitle track is on,
Whisper transcribes it with word timestamps, and each cue is matched to the stretch of the transcript
it most resembles; the offset is the cue start minus the moment those words are spoken. The median
over the matched cues is the channel's sync offset (positive = subtitles late).

What can and cannot be measured:
* Whisper and the cues must be in the **same language**. Pluto offers English subtitles on audio that
  is often Italian; that is a translation, words do not match and the check is skipped with a note
  instead of reporting nonsense.
* Below 40 % of the eligible cues matched the offset is not evaluated (`sub.sync_confidence` says why).
* Everything here is pure; the transcriber is injected (`pippo/transcribe.py`), so tests need no model.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol

from pippo.probes.epg import detect_language_confident
from pippo.thresholds import Threshold, grade

MIN_CUE_TOKENS = 4
SEARCH_RADIUS_SEC = 25.0       # how far from the cue start the matching speech may be
MIN_MATCH_RATIO = 0.55
MIN_CONFIDENCE = 0.40
MIN_MATCHED_FOR_OFFSET = 3


@dataclass(frozen=True)
class Word:
    word: str
    start: float   # seconds from the start of the captured audio
    end: float


@dataclass(frozen=True)
class Transcript:
    words: list[Word]
    language: str | None
    language_probability: float = 0.0


class Transcriber(Protocol):
    def transcribe(self, samples, language: str | None = None) -> Transcript: ...


_SPEAKER_LABEL = re.compile(r"^\s*[-–]?\s*(?:\([^)]*\)|[A-Z][A-Z .'’-]{1,30}):\s*")
_NON_WORD = re.compile(r"[^\w\s']", re.UNICODE)


def cue_tokens(text: str) -> list[str]:
    """Lower-cased words of a cue without speaker labels ("DAVID DANIEL:"), dashes and sound notes."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = _SPEAKER_LABEL.sub("", text.strip())
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|♪[^♪]*♪", " ", text)
    return _NON_WORD.sub(" ", text.casefold().replace("’", "'")).split()


def _word_token(w: Word) -> str:
    return _NON_WORD.sub("", w.word.casefold().replace("’", "'")).strip()


def match_cue(
    tokens: list[str], spoken: list[tuple[str, float]], cue_ct: float, audio_start_ct: float
) -> tuple[float, float, float] | None:
    """Best (ratio, first_word_media_time, last_word_media_time) for a cue among transcript tokens near its start."""
    n = len(tokens)
    best_ratio, best = 0.0, None
    for i in range(0, len(spoken) - n + 1):
        t = audio_start_ct + spoken[i][1]
        if abs(t - cue_ct) > SEARCH_RADIUS_SEC:
            continue
        ratio = SequenceMatcher(None, tokens, [w for w, _ in spoken[i : i + n]], autojunk=False).ratio()
        if ratio > best_ratio:
            best_ratio, best = ratio, (t, audio_start_ct + spoken[i + n - 1][1])
    if best is None or best_ratio < MIN_MATCH_RATIO:
        return None
    return best_ratio, best[0], best[1]


def is_rollup(cues: list[dict]) -> bool:
    """Roll-up (live) captions grow word by word: each cue repeats the previous one and adds a few words.

    Such a cue starts when its LAST word is typed, so it must be compared with the moment that word is
    spoken; a pop-on cue starts when its FIRST word is shown.
    """
    pairs = growing = 0
    prev: list[str] = []
    for c in cues:
        cur = cue_tokens(c.get("text", ""))
        if len(prev) >= 3 and len(cur) >= 3:
            pairs += 1
            overlap = len(set(prev) & set(cur)) / max(1, min(len(set(prev)), len(set(cur))))
            if overlap >= 0.7:
                growing += 1
        prev = cur
    return pairs >= 5 and growing / pairs >= 0.3


def compute_sync(
    cues: list[dict],
    transcript: Transcript,
    audio_start_ct: float,
    audio_seconds: float,
    cue_language: str | None,
) -> dict:
    """Sync metrics from cues (media-time start/end/text) and a transcript of the captured audio."""
    m: dict = {}
    spoken_lang = (transcript.language or "")[:2].lower() or None
    m["sub.spoken_language"] = spoken_lang
    cue_lang = (cue_language or "")[:2].lower() or None
    if spoken_lang and cue_lang and spoken_lang != cue_lang:
        m["sub.sync_note"] = f"audio is '{spoken_lang}' and the subtitles are '{cue_lang}': a translation cannot be aligned word for word"
        return m

    spoken = [(t, w.start) for w in transcript.words if (t := _word_token(w))]
    window_end = audio_start_ct + audio_seconds
    eligible = []
    for c in cues:
        toks = cue_tokens(c.get("text", ""))
        if len(toks) >= MIN_CUE_TOKENS and audio_start_ct <= c["start"] <= window_end - 1.0:
            eligible.append((c, toks))
    m["sub.sync_eligible"] = len(eligible)
    if not eligible or not spoken:
        m["sub.sync_note"] = "no cue with enough words inside the captured audio, or no speech recognised"
        return m

    rollup = is_rollup(cues)
    m["sub.sync_mode"] = "roll-up" if rollup else "pop-on"
    offsets = []
    for c, toks in eligible:
        hit = match_cue(toks, spoken, c["start"], audio_start_ct)
        if hit:
            offsets.append(c["start"] - (hit[2] if rollup else hit[1]))
    m["sub.sync_matched"] = len(offsets)
    m["sub.sync_confidence"] = round(len(offsets) / len(eligible), 3)
    if m["sub.sync_confidence"] < MIN_CONFIDENCE or len(offsets) < MIN_MATCHED_FOR_OFFSET:
        m["sub.sync_note"] = f"only {len(offsets)} of {len(eligible)} cues matched the speech: offset not evaluated"
        return m
    signed = statistics.median(offsets)
    m["sub.sync_offset_signed"] = round(signed, 3)
    m["sub.sync_spread"] = round(statistics.pstdev(offsets), 3)   # steady offset = delayed track; wide spread = live captions
    m["sub.sync_offset"] = round(abs(signed), 3)
    return m


def evaluate(metrics: dict, overrides: dict[str, Threshold] | None = None) -> list[dict]:
    value = metrics.get("sub.sync_offset")
    if value is None:
        return []
    severity, crossed = grade("sub.sync_offset", float(value), overrides)
    direction = "late" if metrics.get("sub.sync_offset_signed", 0) > 0 else "early"
    return [
        {
            "checkId": "sub.sync_offset",
            "severity": severity if severity != "ok" else "info",
            "passed": severity == "ok",
            "value": float(value),
            "threshold": crossed,
            "detail": f"subtitles {value:g} s {direction} (median of {metrics.get('sub.sync_matched')} cues, confidence {metrics.get('sub.sync_confidence')})",
        }
    ]


def pcm_to_samples(pcm: dict):
    """float32 mono samples from the recorder's base64 Int16 payload."""
    import base64

    import numpy as np

    return np.frombuffer(base64.b64decode(pcm["b64"]), dtype=np.int16).astype(np.float32) / 32768.0


def measure_sync(rec: dict, transcriber: Transcriber, overrides: dict[str, Threshold] | None = None) -> dict:
    """Sync metrics and checks for one recorded channel; empty when there is nothing to align."""
    pcm, cues = rec.get("pcm"), rec["buffer"].get("subCues") or []
    info = rec.get("subtitleInfo") or {}
    if not pcm or not cues or not info.get("enabled"):
        return {"metrics": {}, "checks": []}
    samples = pcm_to_samples(pcm)
    transcript = transcriber.transcribe(samples)
    declared = (info.get("declared") or [{}])[0].get("lang")
    distinct = list(dict.fromkeys(" ".join(cue_tokens(c.get("text", ""))) for c in cues))[:120]   # roll-up repeats: once each
    cue_lang = detect_language_confident(" ".join(distinct)) or declared
    m = compute_sync(cues, transcript, float(pcm.get("startCt") or 0.0), len(samples) / 16000.0, cue_lang)
    return {"metrics": m, "checks": evaluate(m, overrides)}
