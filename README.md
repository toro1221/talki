# Talki

Talki turns speech into text and injects it into whatever app currently has keyboard focus.

You can:
- **Hold-to-talk**: hold one hotkey to record, release to stop.
- **Toggle record**: press a second hotkey to start/stop recording hands-free.

## Install

From source (recommended while developing):

- `python3 -m venv .venv`
- `source .venv/bin/activate`
- `pip install -r requirements.txt`
- (Optional) install as a package: `pip install -e .`

Then run:

- `python -m talki`
  - or, after `pip install -e .`, just `talki`

## Usage

1. Focus the target app (cursor in a text field).
2. Hold the **push-to-talk** key to speak (or press the **toggle** key to start).
3. Text is injected into the focused app as it becomes stable.

Choose hotkeys you don’t need for normal typing: the app suppresses those keys system-wide while it is running.

## Configuration

Open the tray icon menu → **Settings** to change:
- Input device
- Model size / language
- Push-to-talk key
- Toggle record key
- Injection mode
- Transcribe interval

Config file locations:
- Linux: `~/.config/talki/config.json` (or `$XDG_CONFIG_HOME`)
- macOS: `~/Library/Application Support/talki/config.json`
- Windows: `%APPDATA%\\talki\\config.json`

## Platform notes

Linux:
- Permissions: global hotkeys and kernel-level keyboard injection require access to `/dev/input/*`.
  Add your user to the `input` group: `sudo usermod -aG input $USER` (then log out/in).
- Hotkey suppression: uses `evdev` device grabs and re-emits all keys except the configured hotkeys.
- Injection:
  - Default: direct typing via uinput keypress events (US layout mapping for punctuation)
  - Fallback/option: clipboard paste (`Ctrl+V`)

macOS:
- Requires **Accessibility** permission for hotkeys and text injection.
- Hotkey suppression uses a Quartz event tap (`pyobjc-framework-Quartz`).

Windows:
- Hotkey suppression uses a low-level keyboard hook (suppresses only the configured hotkeys).

## Limitations

- Some punctuation keys are named canonically (e.g. the `~/` key is stored as `grave`).
- Direct keypress injection on Linux assumes a US layout for punctuation; use **Clipboard** injection mode if punctuation is wrong for your layout.
