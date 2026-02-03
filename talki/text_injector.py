"""Platform-dispatching text injection.

Linux: uinput keypress typing (default) with clipboard paste fallback.
Windows/macOS: pynput Controller.type() with clipboard fallback.
"""

import logging
import time
from collections import deque
from dataclasses import dataclass

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

from .platform_utils import get_platform

logger = logging.getLogger(__name__)


class BaseTextInjector:
    def inject(self, text: str):
        raise NotImplementedError

    def close(self):
        pass


class LinuxClipboardTextInjector(BaseTextInjector):
    """Linux text injector using clipboard + uinput Ctrl+V.

    Works on both Wayland and X11 because uinput events are injected
    at the kernel level, bypassing the display server.
    """

    def __init__(self):
        import evdev
        from evdev import ecodes
        self._uinput = evdev.UInput({
            ecodes.EV_KEY: [ecodes.KEY_LEFTCTRL, ecodes.KEY_V],
        }, name="talki-clipboard")
        self._queue: deque[str] = deque()
        self._busy = False
        self._saved_clipboard_text: str = ""

        # Tuned to work on both X11 and Wayland without blocking the Qt event loop.
        self._set_clipboard_delay_ms = 25
        self._post_paste_delay_ms = 175
        self._restore_delay_ms = 350

    def inject(self, text: str):
        if not text:
            return
        self._queue.append(text)
        if self._busy:
            return

        self._busy = True
        self._saved_clipboard_text = QApplication.clipboard().text()
        self._pump()

    def _pump(self):
        if not self._queue:
            QTimer.singleShot(self._restore_delay_ms, self._restore_clipboard)
            return

        next_text = self._queue.popleft()
        QApplication.clipboard().setText(next_text)
        QTimer.singleShot(self._set_clipboard_delay_ms, self._paste)

    def _paste(self):
        from evdev import ecodes

        # Simulate Ctrl+V via uinput. Avoid sleeps; keep Qt responsive so the
        # compositor/app can request clipboard data (especially on Wayland).
        self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 1)
        self._uinput.syn()
        self._uinput.write(ecodes.EV_KEY, ecodes.KEY_V, 1)
        self._uinput.syn()
        self._uinput.write(ecodes.EV_KEY, ecodes.KEY_V, 0)
        self._uinput.syn()
        self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTCTRL, 0)
        self._uinput.syn()

        QTimer.singleShot(self._post_paste_delay_ms, self._pump)

    def _restore_clipboard(self):
        QApplication.clipboard().setText(self._saved_clipboard_text)
        self._saved_clipboard_text = ""
        self._busy = False

        # If new text arrived while we were restoring, start a new batch.
        if self._queue:
            self._busy = True
            self._saved_clipboard_text = QApplication.clipboard().text()
            self._pump()

    def close(self):
        if self._uinput is not None:
            self._uinput.close()
            self._uinput = None
        self._queue.clear()
        self._busy = False


@dataclass(frozen=True)
class _Keypress:
    code: int
    shift: bool = False


class LinuxKeypressTextInjector(BaseTextInjector):
    """Linux text injector using direct uinput keypress events.

    Notes:
    - Uses a US keyboard layout mapping for punctuation.
    - Falls back to a clipboard injector for unsupported characters (Unicode).
    """

    def __init__(self, fallback: BaseTextInjector | None = None):
        import evdev
        from evdev import ecodes

        self._fallback = fallback
        self._ecodes = ecodes
        self._char_map = self._build_char_map(ecodes)

        required_keys = {ecodes.KEY_LEFTSHIFT}
        for mapping in self._char_map.values():
            required_keys.add(mapping.code)
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            required_keys.add(getattr(ecodes, f"KEY_{letter}"))
        for digit in "0123456789":
            required_keys.add(getattr(ecodes, f"KEY_{digit}"))

        self._uinput = evdev.UInput(
            {ecodes.EV_KEY: sorted(required_keys)},
            name="talki-keypress",
        )

    def inject(self, text: str):
        if not text:
            return

        # Fast path: only attempt keypress typing if every character is mappable.
        presses: list[_Keypress] = []
        for ch in text:
            mapping = self._char_to_keypress(ch)
            if mapping is None:
                if self._fallback is not None:
                    logger.debug(
                        "Falling back to clipboard injection for unmappable text"
                    )
                    self._fallback.inject(text)
                else:
                    logger.warning("Dropped unmappable text: %r", text)
                return
            presses.append(mapping)

        for kp in presses:
            self._type_keypress(kp)

    def _type_keypress(self, kp: _Keypress):
        ecodes = self._ecodes
        if kp.shift:
            self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 1)
            self._uinput.syn()

        self._uinput.write(ecodes.EV_KEY, kp.code, 1)
        self._uinput.syn()
        self._uinput.write(ecodes.EV_KEY, kp.code, 0)
        self._uinput.syn()

        if kp.shift:
            self._uinput.write(ecodes.EV_KEY, ecodes.KEY_LEFTSHIFT, 0)
            self._uinput.syn()

    def _char_to_keypress(self, ch: str) -> _Keypress | None:
        if not ch:
            return None
        if ch in self._char_map:
            return self._char_map[ch]

        # ASCII letters: KEY_A..KEY_Z (+ shift for uppercase)
        if "a" <= ch <= "z":
            code = getattr(self._ecodes, f"KEY_{ch.upper()}", None)
            return _Keypress(code=code, shift=False) if code is not None else None
        if "A" <= ch <= "Z":
            code = getattr(self._ecodes, f"KEY_{ch}", None)
            return _Keypress(code=code, shift=True) if code is not None else None

        # Basic digits
        if "0" <= ch <= "9":
            code = getattr(self._ecodes, f"KEY_{ch}", None)
            return _Keypress(code=code, shift=False) if code is not None else None

        # Non-ASCII / unsupported
        return None

    @staticmethod
    def _build_char_map(ecodes) -> dict[str, _Keypress]:
        # US keyboard layout mapping for common punctuation.
        # Keep this intentionally small; fall back to clipboard for the rest.
        return {
            " ": _Keypress(code=ecodes.KEY_SPACE),
            "\n": _Keypress(code=ecodes.KEY_ENTER),
            "\t": _Keypress(code=ecodes.KEY_TAB),

            "-": _Keypress(code=ecodes.KEY_MINUS),
            "_": _Keypress(code=ecodes.KEY_MINUS, shift=True),
            "=": _Keypress(code=ecodes.KEY_EQUAL),
            "+": _Keypress(code=ecodes.KEY_EQUAL, shift=True),

            "[": _Keypress(code=ecodes.KEY_LEFTBRACE),
            "{": _Keypress(code=ecodes.KEY_LEFTBRACE, shift=True),
            "]": _Keypress(code=ecodes.KEY_RIGHTBRACE),
            "}": _Keypress(code=ecodes.KEY_RIGHTBRACE, shift=True),
            "\\": _Keypress(code=ecodes.KEY_BACKSLASH),
            "|": _Keypress(code=ecodes.KEY_BACKSLASH, shift=True),

            ";": _Keypress(code=ecodes.KEY_SEMICOLON),
            ":": _Keypress(code=ecodes.KEY_SEMICOLON, shift=True),
            "'": _Keypress(code=ecodes.KEY_APOSTROPHE),
            "\"": _Keypress(code=ecodes.KEY_APOSTROPHE, shift=True),
            "`": _Keypress(code=ecodes.KEY_GRAVE),
            "~": _Keypress(code=ecodes.KEY_GRAVE, shift=True),

            ",": _Keypress(code=ecodes.KEY_COMMA),
            "<": _Keypress(code=ecodes.KEY_COMMA, shift=True),
            ".": _Keypress(code=ecodes.KEY_DOT),
            ">": _Keypress(code=ecodes.KEY_DOT, shift=True),
            "/": _Keypress(code=ecodes.KEY_SLASH),
            "?": _Keypress(code=ecodes.KEY_SLASH, shift=True),

            "!": _Keypress(code=ecodes.KEY_1, shift=True),
            "@": _Keypress(code=ecodes.KEY_2, shift=True),
            "#": _Keypress(code=ecodes.KEY_3, shift=True),
            "$": _Keypress(code=ecodes.KEY_4, shift=True),
            "%": _Keypress(code=ecodes.KEY_5, shift=True),
            "^": _Keypress(code=ecodes.KEY_6, shift=True),
            "&": _Keypress(code=ecodes.KEY_7, shift=True),
            "*": _Keypress(code=ecodes.KEY_8, shift=True),
            "(": _Keypress(code=ecodes.KEY_9, shift=True),
            ")": _Keypress(code=ecodes.KEY_0, shift=True),
        }

    def close(self):
        if self._uinput is not None:
            self._uinput.close()
            self._uinput = None
        if self._fallback is not None:
            try:
                self._fallback.close()
            except Exception:
                pass


class PynputTextInjector(BaseTextInjector):
    """Windows/macOS text injector using pynput."""

    def __init__(self, mode: str = "auto"):
        from pynput.keyboard import Controller
        self._controller = Controller()
        self._mode = mode

    def inject(self, text: str):
        if not text:
            return

        if self._mode == "clipboard":
            self._clipboard_paste(text)
            return

        # Check if text is pure ASCII - use direct typing
        if all(ord(c) < 128 for c in text):
            self._controller.type(text)
        else:
            self._clipboard_paste(text)

    def _clipboard_paste(self, text: str):
        from pynput.keyboard import Key

        clipboard = QApplication.clipboard()
        saved_text = clipboard.text()

        clipboard.setText(text)
        time.sleep(0.05)

        # Cmd+V on macOS, Ctrl+V on Windows
        modifier = Key.cmd if get_platform() == "macos" else Key.ctrl
        with self._controller.pressed(modifier):
            self._controller.press("v")
            self._controller.release("v")

        time.sleep(0.15)
        if saved_text:
            clipboard.setText(saved_text)

    def close(self):
        pass


def create_text_injector(mode: str = "auto") -> BaseTextInjector:
    platform = get_platform()
    if platform == "linux":
        mode = (mode or "auto").lower()
        if mode == "clipboard":
            return LinuxClipboardTextInjector()
        clipboard = LinuxClipboardTextInjector()
        return LinuxKeypressTextInjector(fallback=clipboard)
    else:
        mode = (mode or "auto").lower()
        return PynputTextInjector(mode=mode)
