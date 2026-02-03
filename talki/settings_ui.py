"""Settings dialog with tabs for audio, hotkey, and injection configuration."""

from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QPushButton, QLabel, QSlider, QDialogButtonBox, QGroupBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, Signal

from .config import Config
from .audio_capture import list_input_devices
from .platform_utils import get_platform, get_display_server, check_input_group


MODEL_SIZES = [
    ("tiny", "Fastest, lower accuracy"),
    ("base", "Good balance (recommended)"),
    ("small", "Better accuracy, slower"),
    ("medium", "Best accuracy, slowest"),
]

LANGUAGES = [
    ("en", "English"),
    ("auto", "Auto-detect"),
    ("zh", "Chinese"),
    ("de", "German"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("pt", "Portuguese"),
    ("ru", "Russian"),
    ("nl", "Dutch"),
]

INJECTION_MODES = [
    ("auto", "Auto (recommended)"),
    ("clipboard", "Clipboard paste (Ctrl+V)"),
    ("keypress", "Direct typing"),
]


class KeyCaptureButton(QPushButton):
    """Button that captures the next keypress when clicked."""
    key_captured = Signal(str)

    def __init__(self, current_key: str, parent=None):
        super().__init__(f"Key: {current_key}", parent)
        self._capturing = False
        self._current_key = current_key
        self.clicked.connect(self._start_capture)

    def _start_capture(self):
        self._capturing = True
        self.setText("Press a key...")
        self.setFocus()
        self.grabKeyboard()

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return

        key = event.key()
        if key in (Qt.Key.Key_Escape,):
            # Cancel capture
            self._capturing = False
            self.releaseKeyboard()
            self.setText(f"Key: {self._current_key}")
            return

        key_name = _qt_key_to_name(key)
        if key_name:
            self._current_key = key_name
            self._capturing = False
            self.releaseKeyboard()
            self.setText(f"Key: {key_name}")
            self.key_captured.emit(key_name)

    def get_key(self) -> str:
        return self._current_key


def _qt_key_to_name(key: int) -> str | None:
    """Convert a Qt key code to a portable key name string."""
    key_map = {
        Qt.Key.Key_F1: "F1", Qt.Key.Key_F2: "F2", Qt.Key.Key_F3: "F3",
        Qt.Key.Key_F4: "F4", Qt.Key.Key_F5: "F5", Qt.Key.Key_F6: "F6",
        Qt.Key.Key_F7: "F7", Qt.Key.Key_F8: "F8", Qt.Key.Key_F9: "F9",
        Qt.Key.Key_F10: "F10", Qt.Key.Key_F11: "F11", Qt.Key.Key_F12: "F12",
        Qt.Key.Key_Space: "space",
        Qt.Key.Key_Tab: "tab",
        Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter",
        Qt.Key.Key_Backspace: "backspace",
        Qt.Key.Key_CapsLock: "capslock",
        Qt.Key.Key_Control: "ctrl",
        Qt.Key.Key_Alt: "alt",
        Qt.Key.Key_Shift: "shift",
        Qt.Key.Key_Meta: "meta",
        Qt.Key.Key_Insert: "insert",
        Qt.Key.Key_Delete: "delete",
        Qt.Key.Key_Home: "home",
        Qt.Key.Key_End: "end",
        Qt.Key.Key_PageUp: "pageup",
        Qt.Key.Key_PageDown: "pagedown",
        Qt.Key.Key_Pause: "pause",
        Qt.Key.Key_ScrollLock: "scrolllock",
        Qt.Key.Key_Print: "print",

        # Punctuation / OEM-ish keys (stored as canonical names)
        Qt.Key.Key_QuoteLeft: "grave",
        Qt.Key.Key_AsciiTilde: "grave",
        Qt.Key.Key_Minus: "minus",
        Qt.Key.Key_Underscore: "minus",
        Qt.Key.Key_Equal: "equal",
        Qt.Key.Key_Plus: "equal",
        Qt.Key.Key_BracketLeft: "bracket_left",
        Qt.Key.Key_BraceLeft: "bracket_left",
        Qt.Key.Key_BracketRight: "bracket_right",
        Qt.Key.Key_BraceRight: "bracket_right",
        Qt.Key.Key_Backslash: "backslash",
        Qt.Key.Key_Bar: "backslash",
        Qt.Key.Key_Semicolon: "semicolon",
        Qt.Key.Key_Colon: "semicolon",
        Qt.Key.Key_Apostrophe: "apostrophe",
        Qt.Key.Key_QuoteDbl: "apostrophe",
        Qt.Key.Key_Comma: "comma",
        Qt.Key.Key_Less: "comma",
        Qt.Key.Key_Period: "period",
        Qt.Key.Key_Greater: "period",
        Qt.Key.Key_Slash: "slash",
        Qt.Key.Key_Question: "slash",
    }
    if key in key_map:
        return key_map[key]
    # Letters and digits
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return chr(key).lower()
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return chr(key)
    return None


class SettingsDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self._config = config
        self.setWindowTitle("Talki - Settings")
        self.setMinimumWidth(480)
        self._setup_ui()
        self._load_values()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._create_audio_tab(), "Audio && Speech")
        tabs.addTab(self._create_hotkey_tab(), "Push-to-Talk")
        tabs.addTab(self._create_injection_tab(), "Injection")
        layout.addWidget(tabs)

        # Platform info
        info_group = QGroupBox("Platform Info")
        info_layout = QVBoxLayout(info_group)
        platform = get_platform()
        display = get_display_server() if platform == "linux" else "N/A"
        info_layout.addWidget(QLabel(f"OS: {platform.capitalize()}  |  "
                                     f"Display: {display}"))

        if platform == "linux":
            if check_input_group():
                info_layout.addWidget(QLabel("Input group: OK"))
            else:
                warn = QLabel(
                    "Input group: NOT configured\n"
                    "Run: sudo usermod -aG input $USER  (then re-login)")
                warn.setStyleSheet("color: #e74c3c; font-weight: bold;")
                info_layout.addWidget(warn)

        layout.addWidget(info_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _create_audio_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        # Input device
        device_row = QHBoxLayout()
        self._device_combo = QComboBox()
        self._device_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents)
        device_row.addWidget(self._device_combo, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_devices)
        device_row.addWidget(refresh_btn)
        form.addRow("Input device:", device_row)

        # Model size
        self._model_combo = QComboBox()
        for value, desc in MODEL_SIZES:
            self._model_combo.addItem(f"{value} - {desc}", value)
        form.addRow("Model size:", self._model_combo)

        # Language
        self._lang_combo = QComboBox()
        for code, name in LANGUAGES:
            self._lang_combo.addItem(name, code)
        form.addRow("Language:", self._lang_combo)

        return tab

    def _create_hotkey_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        self._key_capture = KeyCaptureButton(self._config.push_to_talk_key)
        form.addRow("Push-to-talk key:", self._key_capture)

        self._toggle_key_capture = KeyCaptureButton(self._config.toggle_record_key)
        form.addRow("Toggle record key:", self._toggle_key_capture)

        # Transcription interval slider
        slider_row = QHBoxLayout()
        self._interval_slider = QSlider(Qt.Orientation.Horizontal)
        self._interval_slider.setMinimum(500)
        self._interval_slider.setMaximum(3000)
        self._interval_slider.setSingleStep(100)
        self._interval_slider.setTickInterval(500)
        self._interval_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._interval_label = QLabel()
        self._interval_slider.valueChanged.connect(
            lambda v: self._interval_label.setText(f"{v} ms"))
        slider_row.addWidget(self._interval_slider, 1)
        slider_row.addWidget(self._interval_label)
        form.addRow("Transcribe interval:", slider_row)

        layout.addLayout(form)

        info = QLabel(
            "Hotkeys:\n"
            "- Push-to-talk: hold to record, release to stop\n"
            "- Toggle record: press once to start, press again to stop\n\n"
            "The transcription interval controls how frequently audio is "
            "processed while speaking. Lower values give faster feedback "
            "but use more CPU."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(info)
        layout.addStretch()

        return tab

    def _create_injection_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self._injection_combo = QComboBox()
        for value, desc in INJECTION_MODES:
            self._injection_combo.addItem(desc, value)
        form.addRow("Injection mode:", self._injection_combo)

        platform = get_platform()
        if platform == "linux":
            info = QLabel(
                "On Linux, direct typing (uinput keypress events) is used by "
                "default. Clipboard paste (Ctrl+V) is available as an option "
                "and is used as a fallback for unsupported characters.")
        elif platform == "macos":
            info = QLabel(
                "On macOS, direct typing is used for ASCII text, "
                "with clipboard paste fallback for Unicode.")
        else:
            info = QLabel(
                "On Windows, direct typing is used for ASCII text, "
                "with clipboard paste fallback for Unicode.")
        info.setWordWrap(True)
        info.setStyleSheet("color: gray;")
        form.addRow(info)

        return tab

    def _refresh_devices(self):
        self._device_combo.clear()
        self._device_combo.addItem("System default", None)
        for dev in list_input_devices():
            self._device_combo.addItem(dev["name"], dev["id"])

    def _load_values(self):
        # Devices
        self._refresh_devices()
        if self._config.input_device_id is not None:
            for i in range(self._device_combo.count()):
                if self._device_combo.itemData(i) == self._config.input_device_id:
                    self._device_combo.setCurrentIndex(i)
                    break

        # Model
        for i in range(self._model_combo.count()):
            if self._model_combo.itemData(i) == self._config.model_size:
                self._model_combo.setCurrentIndex(i)
                break

        # Language
        for i in range(self._lang_combo.count()):
            if self._lang_combo.itemData(i) == self._config.language:
                self._lang_combo.setCurrentIndex(i)
                break

        # Interval
        self._interval_slider.setValue(self._config.transcribe_interval_ms)
        self._interval_label.setText(f"{self._config.transcribe_interval_ms} ms")

        # Injection mode
        for i in range(self._injection_combo.count()):
            if self._injection_combo.itemData(i) == self._config.injection_mode:
                self._injection_combo.setCurrentIndex(i)
                break

    def _save_and_accept(self):
        self._config.input_device_id = self._device_combo.currentData()
        self._config.push_to_talk_key = self._key_capture.get_key()
        self._config.toggle_record_key = self._toggle_key_capture.get_key()

        if (self._config.push_to_talk_key and self._config.toggle_record_key and
                self._config.push_to_talk_key == self._config.toggle_record_key):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("Talki - Settings")
            msg.setText("Hotkeys must be different.")
            msg.setInformativeText(
                "Choose different keys for push-to-talk and toggle record."
            )
            msg.exec()
            return

        self._config.model_size = self._model_combo.currentData()
        self._config.language = self._lang_combo.currentData()
        self._config.injection_mode = self._injection_combo.currentData()
        self._config.transcribe_interval_ms = self._interval_slider.value()
        self._config.save()
        self.accept()

    def get_config(self) -> Config:
        return self._config
