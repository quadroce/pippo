"""Whisper transcription through faster-whisper (CPU, model `small`, int8).

Notes:
* The model (about 480 MB) is downloaded from HuggingFace on first use into `agent/models/` (git-ignored).
* Audio is passed as a 16 kHz float32 array, so faster-whisper's own decoder (PyAV) is never needed;
  `faster_whisper` imports `av` at module level, so a stand-in module is registered first. This also
  lets the transcriber work where PyAV's native library cannot be loaded (some Windows application
  control policies block it).
"""

from __future__ import annotations

import logging
import sys
import types

from pippo.config import AGENT_DIR
from pippo.probes.subtitle_sync import Transcript, Word

log = logging.getLogger(__name__)

MODEL_NAME = "small"


def whisper_available() -> tuple[bool, str]:
    """(usable, detail) for `pippo doctor`: the package imports and the model folder state."""
    try:
        _import_faster_whisper()
    except Exception as e:
        return False, f"faster-whisper not usable: {str(e).splitlines()[0]}"
    models = AGENT_DIR / "models"
    present = models.exists() and any(models.rglob("model.bin"))
    return True, "model present" if present else "package present, model will be downloaded on first use (about 480 MB)"


def _import_faster_whisper():
    sys.modules.setdefault("av", types.ModuleType("av"))
    from faster_whisper import WhisperModel

    return WhisperModel


class WhisperTranscriber:
    """Lazy: the model is loaded on the first `transcribe` call and reused."""

    def __init__(self, model_name: str = MODEL_NAME, download_root=None):
        self._name = model_name
        self._root = str(download_root or AGENT_DIR / "models")
        self._model = None

    def _load(self):
        if self._model is None:
            WhisperModel = _import_faster_whisper()
            log.info("loading Whisper '%s' (CPU, int8)", self._name)
            self._model = WhisperModel(self._name, device="cpu", compute_type="int8", download_root=self._root)
        return self._model

    def transcribe(self, samples, language: str | None = None) -> Transcript:
        segments, info = self._load().transcribe(
            samples,
            language=language,
            word_timestamps=True,
            vad_filter=True,
            beam_size=1,
            condition_on_previous_text=False,
        )
        words = [Word(w.word.strip(), float(w.start), float(w.end)) for s in segments for w in (s.words or [])]
        return Transcript(words, getattr(info, "language", None), float(getattr(info, "language_probability", 0.0) or 0.0))
