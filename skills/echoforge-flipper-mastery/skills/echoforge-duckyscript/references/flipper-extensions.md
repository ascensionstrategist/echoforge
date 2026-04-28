# Flipper Firmware DuckyScript Extensions

A compatibility matrix for the four firmwares you will encounter in the wild, referenced against the Flipper BadUSB runner source at `flipperdevices/flipperzero-firmware/applications/main/bad_usb/helpers/ducky_script_*.c`.

Firmwares:
- **Stock** — the official `flipperdevices` mainline, currently `1.2.x` (2026). Reference implementation.
- **Momentum** (`Next-Flip/Momentum-Firmware`) — most popular community FW, baseline `mntm-012`. Adds extensions + layout files.
- **Xtreme** (`Flipper-XFW/Xtreme-Firmware`) — another community FW. Largely matches Momentum for BadUSB features.
- **Unleashed** (`DarkFlippers/unleashed-firmware`) — older community branch. BadUSB functionally equivalent to stock, missing some Momentum niceties.

---

## Command availability matrix

| Command | Stock | Momentum | Xtreme | Unleashed |
|---------|:-----:|:--------:|:------:|:---------:|
| **Core 1.0** (`DELAY`, `STRING`, `GUI`, `CTRL`, `ALT`, `SHIFT`, arrows, F1–F12) | Y | Y | Y | Y |
| `STRINGLN` | Y | Y | Y | Y |
| `DEFAULTDELAY` / `DEFAULT_DELAY` | Y | Y | Y | Y |
| `DEFAULTCHARDELAY` | Y | Y | Y | Y |
| `ALT-STRING` / `ALT-CHARS` (Alt+numpad Unicode on Windows) | N | **Y** | **Y** | N |
| `HOLD <KEY>` / `RELEASE <KEY>` | N | **Y** | **Y** | N |
| `WAIT_FOR_BUTTON_PRESS` | N | **Y** | **Y** | N |
| Media keys (`PLAY`, `VOLUMEUP`, …) | partial | Y | Y | partial |
| `APP` (context-menu key) | Y | Y | Y | Y |
| `SYSRQ` | N | Y | Y | N |
| `REPEAT <n>` | Y | Y | Y | Y |
| **3.0 control flow** | | | | |
| `VAR` | Y (≥0.85) | Y | Y | Y |
| `IF` / `ELSE` / `ELSE IF` / `END_IF` | Y | Y | Y | Y |
| `WHILE` / `END_WHILE` | Y | Y | Y | Y |
| `FUNCTION` / `END_FUNCTION` | Y | Y | Y | Y |
| `$_RANDOM_*` | Y | Y | Y | Y |
| `$_SYSTEM_BITS` / `$_HOST_*` | **N** | **N** | **N** | **N** |
| `IMPORT` | **N** | **N** | **N** | **N** |
| `REM_BLOCK` / `END_REM` | N (single-line REM only) | N | N | N |
| BLE HID output (send over Bluetooth instead of USB) | N | Y* | Y* | N |

*Momentum/Xtreme BLE HID: you write the same DuckyScript, and the BadUSB app has a "Connect BLE" mode that sends keystrokes to a paired device instead of the USB host. Useful for phones/tablets; payload author doesn't have to change anything.

---

## Keyboard-layout files

Momentum ships layout files at `/ext/badusb/assets/layouts/*.kl` for ~25 layouts. Stock ships US only. To force a specific layout without mutating device settings, put this at the top of your payload:

```
REM LAYOUT: us
```

…which Momentum parses on load. This is a **metadata comment**, not a command — stock firmware ignores it harmlessly. If you know the target is UK, set `REM LAYOUT: uk` and your `STRING @user@example.com` will type the right `@` (Shift+' vs Shift+2).

---

## Path conventions on Flipper SD

- Payloads live in `/ext/badusb/`. Flat or nested.
- Assets/layouts: `/ext/badusb/assets/`.
- Keymap override for a single payload: `/ext/badusb/<name>.kl` sidecar (Momentum).
- The BadUSB app lists `.txt` only — other extensions are hidden.

---

## echoforge-specific integration

The Payload Forge's `payload_badusb_create` writes to `/ext/badusb/<name>.txt` with path confinement `^/ext/badusb/[A-Za-z0-9 _\-./]{1,120}\.txt$`. It:

- Rejects files over 32 KiB or 2000 lines.
- Rejects `DELAY` / `DEFAULTDELAY` arguments outside `[0, 600000]`.
- Emits *warnings* (not errors) for unknown commands, because firmware-specific extensions are legitimate.
- Writes a `<name>.echoforge.json` sidecar with declared target_os, author, tags.

When authoring a payload that must be firmware-portable, restrict yourself to the "Stock" column of the matrix above. When authoring specifically for Momentum, feel free to use `ALT-STRING`/`HOLD`/`WAIT_FOR_BUTTON_PRESS`.
