"""OS detection, display server detection, and permission checks."""

import os
import sys
import grp
from pathlib import Path


def get_platform() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    elif sys.platform == "darwin":
        return "macos"
    elif sys.platform == "win32":
        return "windows"
    return "unknown"


def get_display_server() -> str:
    if get_platform() != "linux":
        return "unknown"
    session_type = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session_type == "wayland" or os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if session_type == "x11" or os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def check_input_group() -> bool:
    """Check if the current user is in the 'input' group (Linux only)."""
    if get_platform() != "linux":
        return True
    try:
        input_gid = grp.getgrnam("input").gr_gid
        return input_gid in os.getgroups()
    except KeyError:
        return False


def check_accessibility_permissions() -> bool:
    """Check if accessibility permissions are granted (macOS only)."""
    if get_platform() != "macos":
        return True
    try:
        import subprocess
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get name of first process'],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_config_dir() -> Path:
    platform = get_platform()
    if platform == "linux":
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    elif platform == "macos":
        base = Path.home() / "Library" / "Application Support"
    elif platform == "windows":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    new_dir = base / "talki"
    old_dir = base / "speech-injector"
    new_cfg = new_dir / "config.json"
    old_cfg = old_dir / "config.json"

    # One-time migration from the old project name to Talki.
    if old_cfg.exists() and not new_cfg.exists():
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            new_cfg.write_text(old_cfg.read_text())
        except Exception:
            pass

    new_dir.mkdir(parents=True, exist_ok=True)
    return new_dir


def get_evdev_keyboard_devices() -> list[str]:
    """Return paths to keyboard evdev devices (Linux only)."""
    if get_platform() != "linux":
        return []
    try:
        import evdev
        devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                # Avoid accidentally grabbing our own virtual devices.
                # Grabbing a uinput device we created can cause event loops.
                name = (dev.name or "").lower()
                if name.startswith("talki") or name.startswith("speech-injector"):
                    dev.close()
                    continue
                caps = dev.capabilities(verbose=False)
                # EV_KEY = 1; check for common keyboard keys (KEY_A=30, KEY_ENTER=28)
                if 1 in caps:
                    key_caps = caps[1]
                    if 30 in key_caps and 28 in key_caps:
                        devices.append(path)
                dev.close()
            except (PermissionError, OSError):
                continue
        return devices
    except ImportError:
        return []
