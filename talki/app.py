"""Core application controller - orchestrates all components."""

import logging

from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication

from .config import Config
from .audio_capture import AudioCapture
from .transcriber import Transcriber, TranscriptionWorker
from .hotkey_manager import create_hotkey_manager, BaseHotkeyManager
from .text_injector import create_text_injector, BaseTextInjector
from .tray_icon import TrayIcon, STATE_IDLE, STATE_LISTENING, STATE_PROCESSING
from .settings_ui import SettingsDialog

logger = logging.getLogger(__name__)


class SpeechInjectorApp(QObject):
    def __init__(self, config: Config, parent: QObject | None = None):
        super().__init__(parent)
        self._config = config

        # Components
        self._audio_capture = AudioCapture()
        self._transcriber: Transcriber | None = None
        self._worker: TranscriptionWorker | None = None
        self._hotkey_manager: BaseHotkeyManager | None = None
        self._text_injector: BaseTextInjector | None = None
        self._tray: TrayIcon | None = None
        self._session_source: str | None = None

    def initialize(self):
        """Initialize all components. Call after QApplication is ready."""
        # Tray icon
        self._tray = TrayIcon()
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.quit_requested.connect(self._quit)
        self._tray.show()

        # Show loading notification
        self._tray.showMessage(
            "Talki",
            f"Loading speech model ({self._config.model_size})...",
            TrayIcon.MessageIcon.Information,
            3000,
        )

        # Load transcription model
        self._transcriber = Transcriber(
            self._config.model_size,
            self._config.language,
        )

        # Text injector
        self._text_injector = create_text_injector(self._config.injection_mode)

        # Hotkey manager
        self._hotkey_manager = create_hotkey_manager(
            self._config.push_to_talk_key,
            self._config.toggle_record_key,
            self,
        )
        self._hotkey_manager.ptt_pressed.connect(self._on_ptt_pressed)
        self._hotkey_manager.ptt_released.connect(self._on_ptt_released)
        self._hotkey_manager.toggle_pressed.connect(self._on_toggle_pressed)
        self._hotkey_manager.start()

        key = self._config.push_to_talk_key
        toggle_key = self._config.toggle_record_key
        self._tray.showMessage(
            "Talki",
            f"Ready. Hold [{key}] to speak, or press [{toggle_key}] to toggle recording.",
            TrayIcon.MessageIcon.Information,
            3000,
        )

    @Slot()
    def _on_ptt_pressed(self):
        self._start_recording_session(source="ptt")

    @Slot()
    def _on_ptt_released(self):
        if self._session_source != "ptt":
            return
        self._stop_recording_session()

    @Slot()
    def _on_toggle_pressed(self):
        if self._audio_capture.is_recording:
            self._stop_recording_session()
        else:
            self._start_recording_session(source="toggle")

    def _start_recording_session(self, source: str):
        # Debounce / state safety: ignore extra presses while recording.
        if self._audio_capture.is_recording:
            return

        self._session_source = source
        logger.info("Recording started (%s)", source)
        self._tray.set_state(STATE_LISTENING)

        # If a previous worker is still finishing up, stop it and ignore its
        # outputs. (It may still take time to exit if mid-transcription.)
        if self._worker is not None:
            self._worker.request_stop()

        # Start recording (new buffer per session)
        self._audio_capture = AudioCapture()
        self._audio_capture.start_recording(self._config.input_device_id)

        # Start transcription worker
        worker = TranscriptionWorker(
            self._transcriber,
            self._audio_capture,
            self._config.transcribe_interval_ms,
        )
        worker.new_text_ready.connect(self._on_new_text)
        worker.transcription_finished.connect(self._on_transcription_done)
        self._worker = worker
        worker.start()

    def _stop_recording_session(self):
        logger.info("Recording stop requested (%s)", self._session_source)
        self._session_source = None
        self._tray.set_state(STATE_PROCESSING)

        # Stop recording
        self._audio_capture.stop_recording()

        # Signal worker to do final pass and stop
        if self._worker is not None:
            self._worker.request_stop()

    @Slot(str)
    def _on_new_text(self, text: str):
        worker = self.sender()
        if worker is not self._worker:
            return
        logger.info("Injecting text: %r", text)
        if self._text_injector is not None:
            self._text_injector.inject(text)

    @Slot()
    def _on_transcription_done(self):
        worker = self.sender()
        if not isinstance(worker, TranscriptionWorker):
            return
        logger.info("Transcription finished")
        # Always join the finished worker to avoid leaking threads.
        try:
            worker.wait(5000)
        except Exception:
            pass

        # Only update UI/state for the currently active session.
        if worker is self._worker:
            self._tray.set_state(STATE_IDLE)
            self._worker = None

    @Slot()
    def _open_settings(self):
        old_model = self._config.model_size
        old_key = self._config.push_to_talk_key
        old_toggle_key = self._config.toggle_record_key
        old_injection_mode = self._config.injection_mode

        dialog = SettingsDialog(self._config)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return

        self._config = dialog.get_config()

        # Reload model if size changed
        if self._config.model_size != old_model:
            self._tray.showMessage(
                "Talki",
                f"Loading model ({self._config.model_size})...",
                TrayIcon.MessageIcon.Information,
                3000,
            )
            self._transcriber.load_model(self._config.model_size)

        # Update language
        if self._transcriber is not None:
            self._transcriber.set_language(self._config.language)

        # Restart hotkey listener if key changed
        if (self._config.push_to_talk_key != old_key or
                self._config.toggle_record_key != old_toggle_key):
            if self._hotkey_manager is not None:
                self._hotkey_manager.stop()
            self._hotkey_manager = create_hotkey_manager(
                self._config.push_to_talk_key,
                self._config.toggle_record_key,
                self,
            )
            self._hotkey_manager.ptt_pressed.connect(self._on_ptt_pressed)
            self._hotkey_manager.ptt_released.connect(self._on_ptt_released)
            self._hotkey_manager.toggle_pressed.connect(self._on_toggle_pressed)
            self._hotkey_manager.start()

        # Restart text injector if mode changed
        if self._config.injection_mode != old_injection_mode:
            if self._text_injector is not None:
                self._text_injector.close()
            self._text_injector = create_text_injector(
                self._config.injection_mode
            )

        self._tray.showMessage(
            "Talki",
            "Settings saved.",
            TrayIcon.MessageIcon.Information,
            2000,
        )

    @Slot()
    def _quit(self):
        logger.info("Shutting down")

        # Stop recording if active
        if self._audio_capture.is_recording:
            self._audio_capture.stop_recording()

        # Stop transcription worker
        if self._worker is not None:
            self._worker.request_stop()
            self._worker.wait(3000)

        # Stop hotkey listener
        if self._hotkey_manager is not None:
            self._hotkey_manager.stop()

        # Close text injector
        if self._text_injector is not None:
            self._text_injector.close()

        # Hide tray
        if self._tray is not None:
            self._tray.hide()

        QApplication.quit()
