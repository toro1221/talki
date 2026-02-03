"""Global hotkey management with per-key suppression.

Linux: evdev grab + uinput re-emission (Wayland/X11).
Windows: low-level keyboard hook.
macOS: Quartz event tap.
Fallback: pynput listener (if needed).
"""

import logging
import threading

from PySide6.QtCore import QObject, Signal, Slot, QMetaObject, Qt

from .platform_utils import get_platform, get_evdev_keyboard_devices

logger = logging.getLogger(__name__)


class BaseHotkeyManager(QObject):
    ptt_pressed = Signal()
    ptt_released = Signal()
    toggle_pressed = Signal()

    def __init__(
        self,
        ptt_key_name: str,
        toggle_key_name: str | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._ptt_key_name = ptt_key_name
        self._toggle_key_name = toggle_key_name or ""
        self._ptt_is_down = False
        self._toggle_is_down = False

    def start(self):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError

    def set_keys(self, ptt_key_name: str, toggle_key_name: str | None = None):
        self._ptt_key_name = ptt_key_name
        self._toggle_key_name = toggle_key_name or ""


class EvdevHotkeyManager(BaseHotkeyManager):

    def __init__(
        self,
        ptt_key_name: str,
        toggle_key_name: str | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(ptt_key_name, toggle_key_name, parent)
        self._thread: threading.Thread | None = None
        self._running = False
        self._devices = []
        self._grabbed_device_paths: set[str] = set()
        self._uinput = None

    def _key_name_to_code(self, key_name: str) -> int | None:
        import evdev.ecodes as ecodes
        if not key_name:
            return None
        # Try direct mapping: "F9" -> "KEY_F9"
        ecode_name = "KEY_" + key_name.upper()
        code = getattr(ecodes, ecode_name, None)
        if code is not None:
            return code
        # Try as-is (e.g. "KEY_F9")
        code = getattr(ecodes, key_name.upper(), None)
        if code is not None:
            return code
        # Handle special names
        special = {
            "ctrl": "KEY_LEFTCTRL",
            "alt": "KEY_LEFTALT",
            "shift": "KEY_LEFTSHIFT",
            "space": "KEY_SPACE",
            "enter": "KEY_ENTER",
            "tab": "KEY_TAB",
            "escape": "KEY_ESC",
            "esc": "KEY_ESC",
            "backspace": "KEY_BACKSPACE",
            "capslock": "KEY_CAPSLOCK",
            "caps_lock": "KEY_CAPSLOCK",
            "grave": "KEY_GRAVE",
            "backquote": "KEY_GRAVE",
            "minus": "KEY_MINUS",
            "equal": "KEY_EQUAL",
            "bracket_left": "KEY_LEFTBRACE",
            "bracket_right": "KEY_RIGHTBRACE",
            "backslash": "KEY_BACKSLASH",
            "semicolon": "KEY_SEMICOLON",
            "apostrophe": "KEY_APOSTROPHE",
            "comma": "KEY_COMMA",
            "period": "KEY_DOT",
            "dot": "KEY_DOT",
            "slash": "KEY_SLASH",
        }
        mapped = special.get(key_name.lower())
        if mapped:
            return getattr(ecodes, mapped, None)
        return None

    def start(self):
        import evdev
        from evdev import UInput
        self._running = True
        self._grabbed_device_paths.clear()
        device_paths = get_evdev_keyboard_devices()
        if not device_paths:
            logger.error("No keyboard devices found. Is user in 'input' group?")
            self._running = False
            return
        self._devices = [evdev.InputDevice(p) for p in device_paths]
        
        combined_caps = {}
        for dev in self._devices:
            for etype, ecodes_list in dev.capabilities().items():
                if etype == 0:
                    continue
                if etype not in combined_caps:
                    combined_caps[etype] = set()
                for item in ecodes_list:
                    code = item[0] if isinstance(item, tuple) else item
                    combined_caps[etype].add(code)
        combined_caps = {k: list(v) for k, v in combined_caps.items()}
        
        self._uinput = UInput(combined_caps, name="talki-kbd")
        
        for dev in self._devices:
            try:
                dev.grab()
                self._grabbed_device_paths.add(dev.path)
            except IOError as e:
                logger.warning("Could not grab %s: %s", dev.path, e)
        if not self._grabbed_device_paths:
            logger.warning(
                "Could not grab any keyboard devices; push-to-talk key will not be suppressed."
            )
        
        self._thread = threading.Thread(target=self._listener_loop, daemon=True)
        self._thread.start()

    def _listener_loop(self):
        import selectors
        import evdev

        ptt_code = self._key_name_to_code(self._ptt_key_name)
        if ptt_code is None:
            logger.error("Unknown push-to-talk key name: %s", self._ptt_key_name)
            return

        toggle_code = self._key_name_to_code(self._toggle_key_name)

        sel = selectors.DefaultSelector()
        for dev in self._devices:
            sel.register(dev, selectors.EVENT_READ)

        while self._running:
            for key, _mask in sel.select(timeout=0.5):
                device = key.fileobj
                try:
                    for event in device.read():
                        is_key_event = event.type == evdev.ecodes.EV_KEY
                        is_ptt_key = is_key_event and event.code == ptt_code
                        is_toggle_key = (
                            toggle_code is not None and is_key_event and event.code == toggle_code
                        )
                        
                        if is_ptt_key:
                            if event.value == 1 and not self._ptt_is_down:
                                self._ptt_is_down = True
                                QMetaObject.invokeMethod(
                                    self, "_emit_pressed",
                                    Qt.ConnectionType.QueuedConnection,
                                )
                            elif event.value == 0 and self._ptt_is_down:
                                self._ptt_is_down = False
                                QMetaObject.invokeMethod(
                                    self, "_emit_released",
                                    Qt.ConnectionType.QueuedConnection,
                                )
                        elif is_toggle_key:
                            if event.value == 1 and not self._toggle_is_down:
                                self._toggle_is_down = True
                                QMetaObject.invokeMethod(
                                    self, "_emit_toggle",
                                    Qt.ConnectionType.QueuedConnection,
                                )
                            elif event.value == 0 and self._toggle_is_down:
                                self._toggle_is_down = False
                        elif (self._uinput is not None and
                              device.path in self._grabbed_device_paths):
                            self._uinput.write_event(event)
                except OSError:
                    continue

        sel.close()
        for dev in self._devices:
            try:
                dev.ungrab()
            except Exception:
                pass
            try:
                dev.close()
            except Exception:
                pass

    @Slot()
    def _emit_pressed(self):
        self.ptt_pressed.emit()

    @Slot()
    def _emit_released(self):
        self.ptt_released.emit()

    @Slot()
    def _emit_toggle(self):
        self.toggle_pressed.emit()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._uinput is not None:
            try:
                self._uinput.close()
            except Exception:
                pass
            self._uinput = None


class WindowsHotkeyManager(BaseHotkeyManager):
    """Windows hotkey manager with per-key suppression via a low-level hook."""

    def __init__(
        self,
        ptt_key_name: str,
        toggle_key_name: str | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(ptt_key_name, toggle_key_name, parent)
        self._thread: threading.Thread | None = None
        self._running = False

        # Lazily initialized in start() to avoid importing ctypes on non-Windows.
        self._user32 = None
        self._kernel32 = None
        self._hook = None
        self._hook_proc = None
        self._thread_id: int | None = None
        self._ptt_vk: int | None = None
        self._toggle_vk: int | None = None

    @staticmethod
    def _key_name_to_vk(key_name: str) -> int | None:
        if not key_name:
            return None
        name = key_name.lower()

        if len(name) == 1 and "a" <= name <= "z":
            return ord(name.upper())
        if len(name) == 1 and "0" <= name <= "9":
            return ord(name)

        # Common named keys
        special = {
            "space": 0x20,
            "tab": 0x09,
            "enter": 0x0D,
            "return": 0x0D,
            "escape": 0x1B,
            "esc": 0x1B,
            "backspace": 0x08,
            "capslock": 0x14,
            "caps_lock": 0x14,

            # OEM keys (US layout)
            "grave": 0xC0,       # ` ~
            "backquote": 0xC0,
            "minus": 0xBD,       # - _
            "equal": 0xBB,       # = +
            "bracket_left": 0xDB,   # [ {
            "bracket_right": 0xDD,  # ] }
            "backslash": 0xDC,   # \ |
            "semicolon": 0xBA,   # ; :
            "apostrophe": 0xDE,  # ' "
            "comma": 0xBC,       # , <
            "period": 0xBE,      # . >
            "dot": 0xBE,
            "slash": 0xBF,       # / ?
        }
        if name in special:
            return special[name]

        # Function keys
        if name.startswith("f") and name[1:].isdigit():
            n = int(name[1:])
            if 1 <= n <= 24:
                return 0x6F + n  # VK_F1 = 0x70

        return None

    def start(self):
        import ctypes
        from ctypes import wintypes

        if self._thread is not None:
            return

        ptt_vk = self._key_name_to_vk(self._ptt_key_name)
        if ptt_vk is None:
            logger.error("Unknown push-to-talk key name for Windows: %s", self._ptt_key_name)
            return
        toggle_vk = self._key_name_to_vk(self._toggle_key_name)

        self._ptt_vk = ptt_vk
        self._toggle_vk = toggle_vk
        self._ptt_is_down = False
        self._toggle_is_down = False
        self._running = True

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32 = user32
        self._kernel32 = kernel32

        WH_KEYBOARD_LL = 13
        HC_ACTION = 0
        WM_KEYDOWN = 0x0100
        WM_KEYUP = 0x0101
        WM_SYSKEYDOWN = 0x0104
        WM_SYSKEYUP = 0x0105

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", wintypes.ULONG_PTR),
            ]

        LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
            wintypes.LRESULT,
            wintypes.INT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        def hook_proc(n_code, w_param, l_param):
            if n_code == HC_ACTION and self._running:
                msg = int(w_param)
                is_down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
                is_up = msg in (WM_KEYUP, WM_SYSKEYUP)

                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                vk = int(info.vkCode)

                if vk == self._ptt_vk:
                    if is_down and not self._ptt_is_down:
                        self._ptt_is_down = True
                        QMetaObject.invokeMethod(
                            self, "_emit_pressed",
                            Qt.ConnectionType.QueuedConnection,
                        )
                    elif is_up and self._ptt_is_down:
                        self._ptt_is_down = False
                        QMetaObject.invokeMethod(
                            self, "_emit_released",
                            Qt.ConnectionType.QueuedConnection,
                        )
                    return 1

                if self._toggle_vk is not None and vk == self._toggle_vk:
                    if is_down and not self._toggle_is_down:
                        self._toggle_is_down = True
                        QMetaObject.invokeMethod(
                            self, "_emit_toggle",
                            Qt.ConnectionType.QueuedConnection,
                        )
                    elif is_up and self._toggle_is_down:
                        self._toggle_is_down = False
                    return 1

            return user32.CallNextHookEx(self._hook, n_code, w_param, l_param)

        self._hook_proc = LowLevelKeyboardProc(hook_proc)

        def thread_main():
            self._thread_id = kernel32.GetCurrentThreadId()

            # Ensure this thread has a message queue so PostThreadMessageW works.
            msg = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0)

            h_mod = kernel32.GetModuleHandleW(None)
            self._hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._hook_proc, h_mod, 0
            )
            if not self._hook:
                err = ctypes.get_last_error()
                logger.error("SetWindowsHookExW failed: %s", err)
                self._running = False
                return

            while self._running:
                rv = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
                if rv == 0:
                    break  # WM_QUIT
                if rv == -1:
                    err = ctypes.get_last_error()
                    logger.error("GetMessageW failed: %s", err)
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

        self._thread = threading.Thread(target=thread_main, daemon=True)
        self._thread.start()

    @Slot()
    def _emit_pressed(self):
        self.ptt_pressed.emit()

    @Slot()
    def _emit_released(self):
        self.ptt_released.emit()

    @Slot()
    def _emit_toggle(self):
        self.toggle_pressed.emit()

    def stop(self):
        self._running = False
        if self._user32 is not None and self._thread_id is not None:
            try:
                WM_QUIT = 0x0012
                self._user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._hook_proc = None


class MacHotkeyManager(BaseHotkeyManager):
    """macOS hotkey manager with per-key suppression via a Quartz event tap."""

    def __init__(
        self,
        ptt_key_name: str,
        toggle_key_name: str | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(ptt_key_name, toggle_key_name, parent)
        self._thread: threading.Thread | None = None
        self._running = False

        self._event_tap = None
        self._tap_callback = None
        self._ptt_keycode: int | None = None
        self._toggle_keycode: int | None = None

    @staticmethod
    def _key_name_to_keycode(key_name: str) -> int | None:
        if not key_name:
            return None
        name = key_name.lower()

        # Function keys (Apple virtual key codes)
        fkeys = {
            "f1": 122, "f2": 120, "f3": 99, "f4": 118,
            "f5": 96, "f6": 97, "f7": 98, "f8": 100,
            "f9": 101, "f10": 109, "f11": 103, "f12": 111,
            "f13": 105, "f14": 107, "f15": 113, "f16": 106,
            "f17": 64, "f18": 79, "f19": 80, "f20": 90,
        }
        if name in fkeys:
            return fkeys[name]

        # Letters (US layout)
        letters = {
            "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
            "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
            "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
            "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
            "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "enter": 36,
            "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43,
            "/": 44, "n": 45, "m": 46, ".": 47, "tab": 48, "space": 49,
            "grave": 50, "backspace": 51, "esc": 53, "escape": 53, "capslock": 57,
        }
        if name in letters:
            return letters[name]

        # Canonical names used in this project (preferred)
        special = {
            "return": 36,
            "caps_lock": 57,
            "backquote": 50,
            "minus": 27,
            "equal": 24,
            "bracket_left": 33,
            "bracket_right": 30,
            "backslash": 42,
            "semicolon": 41,
            "apostrophe": 39,
            "comma": 43,
            "period": 47,
            "dot": 47,
            "slash": 44,
        }
        if name in special:
            return special[name]

        # Single-character fallback for letters/digits already handled above.
        return None

    def start(self):
        if self._thread is not None:
            return

        keycode = self._key_name_to_keycode(self._ptt_key_name)
        if keycode is None:
            logger.error("Unknown push-to-talk key name for macOS: %s", self._ptt_key_name)
            return
        toggle_keycode = self._key_name_to_keycode(self._toggle_key_name)

        self._ptt_keycode = keycode
        self._toggle_keycode = toggle_keycode
        self._ptt_is_down = False
        self._toggle_is_down = False
        self._running = True

        def thread_main():
            try:
                import Quartz  # pyobjc-framework-Quartz
                import CoreFoundation
            except Exception as e:
                logger.error("macOS hotkeys require pyobjc-framework-Quartz: %s", e)
                self._running = False
                return

            kCGEventKeyDown = Quartz.kCGEventKeyDown
            kCGEventKeyUp = Quartz.kCGEventKeyUp
            kCGEventTapDisabledByTimeout = getattr(
                Quartz, "kCGEventTapDisabledByTimeout", None
            )
            kCGEventTapDisabledByUserInput = getattr(
                Quartz, "kCGEventTapDisabledByUserInput", None
            )

            def tap_callback(proxy, type_, event, refcon):
                if not self._running:
                    return event

                if kCGEventTapDisabledByTimeout is not None and type_ == kCGEventTapDisabledByTimeout:
                    Quartz.CGEventTapEnable(self._event_tap, True)
                    return event
                if kCGEventTapDisabledByUserInput is not None and type_ == kCGEventTapDisabledByUserInput:
                    Quartz.CGEventTapEnable(self._event_tap, True)
                    return event

                if type_ not in (kCGEventKeyDown, kCGEventKeyUp):
                    return event

                code = Quartz.CGEventGetIntegerValueField(
                    event, Quartz.kCGKeyboardEventKeycode
                )
                is_down = type_ == kCGEventKeyDown
                is_up = type_ == kCGEventKeyUp

                if self._ptt_keycode is not None and code == self._ptt_keycode:
                    if is_down and not self._ptt_is_down:
                        self._ptt_is_down = True
                        QMetaObject.invokeMethod(
                            self, "_emit_pressed",
                            Qt.ConnectionType.QueuedConnection,
                        )
                    elif is_up and self._ptt_is_down:
                        self._ptt_is_down = False
                        QMetaObject.invokeMethod(
                            self, "_emit_released",
                            Qt.ConnectionType.QueuedConnection,
                        )
                    return None

                if self._toggle_keycode is not None and code == self._toggle_keycode:
                    if is_down and not self._toggle_is_down:
                        self._toggle_is_down = True
                        QMetaObject.invokeMethod(
                            self, "_emit_toggle",
                            Qt.ConnectionType.QueuedConnection,
                        )
                    elif is_up and self._toggle_is_down:
                        self._toggle_is_down = False
                    return None

                return event

            self._tap_callback = tap_callback

            mask = (
                Quartz.CGEventMaskBit(kCGEventKeyDown) |
                Quartz.CGEventMaskBit(kCGEventKeyUp)
            )

            self._event_tap = Quartz.CGEventTapCreate(
                Quartz.kCGHIDEventTap,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionDefault,
                mask,
                tap_callback,
                None,
            )
            if self._event_tap is None:
                logger.error("CGEventTapCreate failed (missing Accessibility permission?)")
                self._running = False
                return

            run_loop_source = Quartz.CFMachPortCreateRunLoopSource(
                None, self._event_tap, 0
            )
            run_loop = CoreFoundation.CFRunLoopGetCurrent()
            CoreFoundation.CFRunLoopAddSource(
                run_loop, run_loop_source, CoreFoundation.kCFRunLoopCommonModes
            )
            Quartz.CGEventTapEnable(self._event_tap, True)

            # Run loop with periodic wakeups so stop() can end the thread.
            while self._running:
                CoreFoundation.CFRunLoopRunInMode(
                    CoreFoundation.kCFRunLoopDefaultMode, 0.25, True
                )

            try:
                Quartz.CGEventTapEnable(self._event_tap, False)
            except Exception:
                pass
            self._event_tap = None

        self._thread = threading.Thread(target=thread_main, daemon=True)
        self._thread.start()

    @Slot()
    def _emit_pressed(self):
        self.ptt_pressed.emit()

    @Slot()
    def _emit_released(self):
        self.ptt_released.emit()

    @Slot()
    def _emit_toggle(self):
        self.toggle_pressed.emit()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._tap_callback = None


class PynputHotkeyManager(BaseHotkeyManager):
    """Windows/macOS hotkey manager using pynput."""

    def __init__(
        self,
        ptt_key_name: str,
        toggle_key_name: str | None = None,
        parent: QObject | None = None,
    ):
        super().__init__(ptt_key_name, toggle_key_name, parent)
        self._listener = None

    def _parse_key(self, key_name: str):
        from pynput.keyboard import Key, KeyCode
        key_name = (key_name or "").lower()
        if not key_name:
            return None
        # Try as a named key (F1-F12, ctrl, alt, etc.)
        pynput_key = getattr(Key, key_name, None)
        if pynput_key is not None:
            return pynput_key
        # Try function keys with different naming
        for attr in dir(Key):
            if attr.lower() == key_name:
                return getattr(Key, attr)
        # Single character key
        if len(key_name) == 1:
            return KeyCode.from_char(key_name)
        return None

    def start(self):
        from pynput.keyboard import Listener
        ptt_key = self._parse_key(self._ptt_key_name)
        if ptt_key is None:
            logger.error("Unknown push-to-talk key name for pynput: %s", self._ptt_key_name)
            return
        toggle_key = self._parse_key(self._toggle_key_name)

        def on_press(key):
            if key == ptt_key and not self._ptt_is_down:
                self._ptt_is_down = True
                QMetaObject.invokeMethod(
                    self, "_emit_pressed",
                    Qt.ConnectionType.QueuedConnection,
                )
            elif toggle_key is not None and key == toggle_key and not self._toggle_is_down:
                self._toggle_is_down = True
                QMetaObject.invokeMethod(
                    self, "_emit_toggle",
                    Qt.ConnectionType.QueuedConnection,
                )

        def on_release(key):
            if key == ptt_key and self._ptt_is_down:
                self._ptt_is_down = False
                QMetaObject.invokeMethod(
                    self, "_emit_released",
                    Qt.ConnectionType.QueuedConnection,
                )
            elif toggle_key is not None and key == toggle_key and self._toggle_is_down:
                self._toggle_is_down = False

        self._listener = Listener(on_press=on_press, on_release=on_release)
        self._listener.start()

    @Slot()
    def _emit_pressed(self):
        self.ptt_pressed.emit()

    @Slot()
    def _emit_released(self):
        self.ptt_released.emit()

    @Slot()
    def _emit_toggle(self):
        self.toggle_pressed.emit()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


def create_hotkey_manager(
    ptt_key_name: str,
    toggle_key_name: str | None = None,
                          parent: QObject | None = None) -> BaseHotkeyManager:
    platform = get_platform()
    if platform == "linux":
        return EvdevHotkeyManager(ptt_key_name, toggle_key_name, parent)
    if platform == "windows":
        return WindowsHotkeyManager(ptt_key_name, toggle_key_name, parent)
    if platform == "macos":
        return MacHotkeyManager(ptt_key_name, toggle_key_name, parent)
    else:
        return PynputHotkeyManager(ptt_key_name, toggle_key_name, parent)
