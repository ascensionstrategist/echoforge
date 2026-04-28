---
name: echoforge-duckyscript
description: Author, debug, and annotate DuckyScript payloads for Flipper Zero BadUSB — covering DuckyScript 1.0 legacy syntax, DuckyScript 3.0 extended language, Flipper firmware extensions (Momentum/Xtreme/Unleashed), and target-OS keyboard-layout gotchas. Use whenever the user writes, reads, or validates a .txt file destined for `/ext/badusb/` on a Flipper.
---

# DuckyScript for Flipper Zero BadUSB

You are the expert reference for writing DuckyScript payloads that run on a Flipper Zero's BadUSB app (HID-keyboard impersonation). Flipper's BadUSB runtime is **not** identical to a Hak5 USB Rubber Ducky — it accepts a superset of legacy DuckyScript 1.0 with most of DuckyScript 3.0's control-flow additions, plus Flipper-specific extensions like `ALT-STRING`, `WAIT_FOR_BUTTON_PRESS`, and `HOLD`/`RELEASE` separation.

## When to activate

Load this skill when the user:
- Asks to write, draft, or generate a DuckyScript / BadUSB payload (e.g. "write me a hello-world ducky", "make a payload that opens Notepad").
- Shares `.txt` content with `REM`, `STRING`, `DELAY`, `GUI`, `CTRL-ALT-DEL` and similar tokens.
- Asks what a DuckyScript payload does, whether it will run on a Flipper, or why it fails on one host OS but not another.
- Is using `payload_badusb_create` / `payload_badusb_validate` / `payload_badusb_run` (the echoforge Payload Forge tools).
- Mentions "BadUSB", "Rubber Ducky", "keystroke injection", or a file path like `/ext/badusb/*.txt`.

## Core knowledge

**Language family and which dialect Flipper speaks.** DuckyScript 1.0 (Hak5, c. 2011) is a line-oriented command-per-line imperative macro language. DuckyScript 3.0 (Hak5, 2022) added variables, functions, conditionals, loops, and extensive system functions — but those require a Ducky with a real CPU (Rubber Ducky Mark II). The Flipper Zero's `flipperdevices/flipperzero-firmware/applications/main/bad_usb/` runner implements a **hybrid**: all of DuckyScript 1.0, plus selected 3.0 features (`VAR`, `WHILE`, `IF`/`END_IF`, `FUNCTION`, arithmetic, `DEFINE`), minus most system functions (no `$_SYSTEM_BITS`, no filesystem `SAVE_HOST_KEYBOARD_LOCK_STATE`). Momentum and Xtreme firmwares extend further: `ALT-STRING` (Alt+keypad-numpad Unicode entry), `ALT-CHARS`, `WAIT_FOR_BUTTON_PRESS`, `HOLD <KEY>` / `RELEASE <KEY>` for sustained modifiers, and `SYSRQ` / `APP` for special keys. See `references/flipper-extensions.md` for the exact firmware matrix.

**The command inventory you will use 95% of the time.**

| Command | Syntax | Notes |
|---------|--------|-------|
| `REM` | `REM <text>` | Comment. Flipper-stock BadUSB **also** parses `REM` prefixed with dashes (`REM_BLOCK` is Hak5-only). |
| `DELAY` | `DELAY <ms>` | Pause. Typical: 200–1000 after `GUI r`; 500 after window focus change. |
| `DEFAULTDELAY` | `DEFAULTDELAY <ms>` | Delay inserted *between every command*. Use sparingly — it multiplies script length. |
| `STRING` | `STRING <text>` | Type string without trailing Enter. |
| `STRINGLN` | `STRINGLN <text>` | Type string + Enter. 3.0-derived; supported on Flipper stock. |
| `ENTER` / `SPACE` / `TAB` / `ESC` / `BACKSPACE` / `DELETE` | bare keyword | Single keystroke. |
| `GUI <key>` | `GUI r` | Windows/Command/Super + key. Bare `GUI` = just press the meta key. |
| `CTRL <key>` / `CONTROL <key>` | `CTRL c` | |
| `ALT <key>` | `ALT F4` | |
| `SHIFT <key>` | `SHIFT TAB` | |
| `CTRL-ALT <key>` | `CTRL-ALT DEL` | Hyphen joins modifiers. Order matters only stylistically. |
| `F1`–`F12` | bare | |
| Arrow keys | `UP` / `DOWN` / `LEFT` / `RIGHT` | |
| `HOME` / `END` / `PAGEUP` / `PAGEDOWN` / `INSERT` | bare | |
| `CAPSLOCK` / `NUMLOCK` / `SCROLLLOCK` / `PRINTSCREEN` / `PAUSE` | bare | |
| `REPEAT <n>` | `REPEAT 5` | Repeats the **previous** line n times. DuckyScript 3.0. |

**Three rules that prevent 90% of payload failures.**

1. **First keystroke is eaten.** The host OS needs ~300 ms after USB enumeration to claim the new HID device. Always start with `DELAY 1000`. Cheap insurance.
2. **`STRING` is layout-sensitive.** DuckyScript types *scancodes*, not characters. A `"` on US layout is Shift+apostrophe; on UK layout the apostrophe key is on a different column; on DE layout it's `Shift+Ä`. If your Flipper's Badusb settings have the **wrong keyboard layout**, `STRING https://` becomes `STRING https:§§` or similar. Set the layout via `Settings → BadUSB → Keyboard layout` on the Flipper, or type an `ALT-STRING` on Windows targets for layout-independent Unicode entry.
3. **Modifier timing.** `CTRL-ALT DEL` sends Ctrl-down, Alt-down, Del-down, Del-up, Alt-up, Ctrl-up in one atomic burst. If the host's SAS (Secure Attention Sequence) is filtering HID keyboards, it will be ignored — that's `SAS_filter_keyboard` in Windows group policy, not your payload's bug.

**Canonical structure.** A real payload has three phases: **prime** (delays, set focus), **act** (keystrokes/mouse/string), **cleanup** (close window, clear clipboard, exit). See `references/common-patterns.md` for five fully-annotated reference payloads.

## Deep references

Load these on demand, not upfront:

- **Full DuckyScript 3.0 language spec** (variables, `IF`/`END_IF`, `WHILE`, `FUNCTION`, arithmetic, `$_RANDOM_INT`, `$_HOST_CONFIGURATION_LOCK`, etc.) → `references/duckyscript-3.0-spec.md`
- **Flipper-firmware-specific extensions** (Stock vs Momentum vs Xtreme vs Unleashed — what's actually supported where) → `references/flipper-extensions.md`
- **Canonical payload examples** with line-by-line annotations (rickroll, hello-world, clipboard demo, browser-open, app-launcher) → `references/common-patterns.md`

## Don't confuse with

- **DuckyScript 1.0 (Hak5 Rubber Ducky original, 2011)** — subset of what Flipper accepts; no variables, no control flow, no `STRINGLN`. A payload that runs on a Hak5 Ducky 1.0 will almost always run on a Flipper; the reverse is not true.
- **DuckyScript 3.0 (Hak5 Rubber Ducky Mark II, 2022)** — full version. Flipper implements ~60% of it; notably missing `$_SYSTEM_BITS`, `$_HOST_*` query variables that require a CPU on the Ducky side.
- **Arduino `Keyboard.h` / `USB_Keyboard` sketches** — similar semantics (HID keyboard impersonation) but a C++ API, not a markup language. If user shows you `Keyboard.press(KEY_LEFT_GUI)` they're writing Arduino, not DuckyScript.
- **AutoHotKey / AutoIt** — host-side automation, not keystroke injection from a peripheral. Runs as an executable, not a payload.
- **PowerShell one-liners** — the *body* of a payload's `STRING` is often a PowerShell command (e.g. `STRING powershell -w hidden -c "iwr ..."`), but PowerShell itself is not DuckyScript. You write DuckyScript to get a PowerShell prompt open; what you feed into it is a separate concern.
- **Flipper's `Infrared Universal Remote`, `Sub-GHz`, or `NFC` apps** — none of these execute DuckyScript. DuckyScript is *only* the BadUSB app's input format.
