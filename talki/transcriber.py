"""Speech recognition with faster-whisper, chunked transcription worker (Talki)."""

import logging
import threading
import re

import numpy as np
from PySide6.QtCore import QThread, Signal, QObject

from faster_whisper import WhisperModel

from .audio_capture import AudioCapture, TARGET_SAMPLE_RATE, resample_audio

logger = logging.getLogger(__name__)


class Transcriber:
    def __init__(self, model_size: str = "base", language: str = "en"):
        self._model: WhisperModel | None = None
        self._language = language
        self.load_model(model_size)

    def set_language(self, language: str):
        self._language = language

    def load_model(self, model_size: str):
        logger.info("Loading faster-whisper model: %s", model_size)
        self._model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
        )
        logger.info("Model loaded: %s", model_size)

    def transcribe(self, audio: np.ndarray) -> str:
        if self._model is None or len(audio) == 0:
            return ""
        kwargs = {}
        if self._language and self._language != "auto":
            kwargs["language"] = self._language
        segments, _info = self._model.transcribe(
            audio,
            beam_size=5,
            vad_filter=True,
            **kwargs,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()


_TRIM_EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$")


def _normalize_word(word: str) -> str:
    # Normalize only for matching stability; keep original tokens for injection.
    # Strip edge punctuation so "test," and "test" are treated the same.
    return _TRIM_EDGE_PUNCT_RE.sub("", word).lower()


def _stable_prefix_len(prev_words: list[str], curr_words: list[str]) -> int:
    """Return number of leading words that appear stable between passes.

    Stability is computed with a light normalization so punctuation changes don't
    cause rewinds (which would lead to duplicated injection).
    """
    limit = min(len(prev_words), len(curr_words))
    stable = 0
    for i in range(limit):
        a = prev_words[i]
        b = curr_words[i]
        if a == b:
            stable = i + 1
            continue
        na = _normalize_word(a)
        nb = _normalize_word(b)
        if na and nb and na == nb:
            stable = i + 1
            continue
        break
    return stable


class TranscriptionWorker(QThread):
    new_text_ready = Signal(str)
    transcription_finished = Signal()

    def __init__(self, transcriber: Transcriber, audio_capture: AudioCapture,
                 interval_ms: int = 1500, parent: QObject | None = None):
        super().__init__(parent)
        self._transcriber = transcriber
        self._audio_capture = audio_capture
        self._interval_ms = interval_ms
        self._committed_len = 0
        self._last_words: list[str] | None = None
        self._stop_event = threading.Event()

    def run(self):
        self._committed_len = 0
        self._last_words = None
        self._stop_event.clear()

        interval_s = max(self._interval_ms, 50) / 1000.0
        while not self._stop_event.wait(timeout=interval_s):
            self._do_transcription_pass(final=False)

        # Final pass
        self._do_transcription_pass(final=True)
        self.transcription_finished.emit()

    def _do_transcription_pass(self, *, final: bool):
        audio = self._audio_capture.get_buffer()
        source_sr = self._audio_capture.sample_rate
        min_samples = int(source_sr * 0.3)
        if len(audio) < min_samples:
            return

        audio_16k = resample_audio(audio, source_sr, TARGET_SAMPLE_RATE)
        full_text = self._transcriber.transcribe(audio_16k)
        if not full_text:
            return

        words = full_text.split()
        if not words:
            return

        # Commit only stable text while recording to avoid duplicating content
        # when the model revises earlier words (common with "retranscribe buffer"
        # strategies). On the final pass, commit everything remaining.
        if final:
            commit_upto = len(words)
        else:
            if self._last_words is None:
                self._last_words = words
                return
            stable_upto = _stable_prefix_len(self._last_words, words)
            commit_upto = max(self._committed_len, stable_upto)

        if commit_upto > self._committed_len:
            new_words = words[self._committed_len:commit_upto]
            if new_words:
                prefix = "" if self._committed_len == 0 else " "
                self.new_text_ready.emit(prefix + " ".join(new_words))
            self._committed_len = commit_upto

        self._last_words = words

    def request_stop(self):
        self._stop_event.set()
