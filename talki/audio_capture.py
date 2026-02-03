"""Audio recording via sounddevice with thread-safe buffer management (Talki)."""

import threading

import numpy as np
import sounddevice as sd
from scipy import signal

TARGET_SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "float32"


def list_input_devices() -> list[dict]:
    """Return list of available input devices."""
    devices = []
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_input_channels"] > 0:
            devices.append({
                "id": i,
                "name": dev["name"],
                "channels": dev["max_input_channels"],
                "default_samplerate": dev["default_samplerate"],
            })
    return devices


def get_device_sample_rate(device_id: int | None) -> int:
    if device_id is None:
        device_info = sd.query_devices(kind='input')
    else:
        device_info = sd.query_devices(device_id)
    return int(device_info["default_samplerate"])


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    if orig_sr == target_sr:
        return audio
    ratio = target_sr / orig_sr
    new_length = int(len(audio) * ratio)
    return signal.resample(audio, new_length).astype(np.float32)


class AudioCapture:
    def __init__(self):
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._recording = False
        self._sample_rate: int = TARGET_SAMPLE_RATE

    def _audio_callback(self, indata: np.ndarray, frames: int,
                        time_info, status):
        if status:
            pass
        with self._lock:
            self._chunks.append(indata.copy())

    def start_recording(self, device_id: int | None = None):
        self.clear_buffer()
        self._recording = True
        self._sample_rate = get_device_sample_rate(device_id)
        self._stream = sd.InputStream(
            samplerate=self._sample_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            device=device_id,
            callback=self._audio_callback,
        )
        self._stream.start()

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    def get_buffer(self) -> np.ndarray:
        """Return a copy of the current audio buffer for transcription."""
        with self._lock:
            if not self._chunks:
                return np.array([], dtype=np.float32)
            return np.concatenate(self._chunks, axis=0).flatten()

    def stop_recording(self) -> np.ndarray:
        """Stop recording and return the final complete buffer."""
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        return self.get_buffer()

    def clear_buffer(self):
        with self._lock:
            self._chunks.clear()

    @property
    def is_recording(self) -> bool:
        return self._recording
