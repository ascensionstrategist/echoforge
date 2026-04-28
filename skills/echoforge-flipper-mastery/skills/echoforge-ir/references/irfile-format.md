# Flipper `.ir` File Format

Plaintext UTF-8, LF or CRLF line endings. **Multi-signal container**: one file holds many named buttons (e.g., a whole TV remote's worth).

Source: `flipperdevices/flipperzero-firmware/lib/infrared/infrared_raw_file.c` and `infrared_signal.c`.

---

## 1. File header

```
Filetype: IR signals file
Version: 1
#
```

The trailing `#` is a required separator between header and the first signal block. Flipper's parser is strict about it.

---

## 2. Signal block

Each button has a multi-line block terminated by a `#` or EOF. Two signal types exist.

### 2a. Parsed signal (named protocol)

```
name: Power
type: parsed
protocol: NEC
address: 40 BF 00 00
command: 12 ED 00 00
#
```

Fields:
- `name` — button label (arbitrary, UTF-8 safe).
- `type` — literal `parsed`.
- `protocol` — one of: `NEC`, `NECext`, `NEC42`, `NEC42ext`, `Samsung32`, `RC5`, `RC5X`, `RC6`, `SIRC`, `SIRC15`, `SIRC20`, `Kaseikyo`, `RCA`, `Pioneer`.
- `address` — 4 bytes space-separated hex, big-endian. Most protocols only use the first 1-2 bytes.
- `command` — 4 bytes space-separated hex, big-endian.

### 2b. Raw signal (captured µs pulse train)

```
name: Unknown_Volume_Up
type: raw
frequency: 38000
duty_cycle: 0.330000
data: 9012 4480 558 558 558 1680 558 558 558 1680 558 558 558 1680 558 558 558 1680 558 558 558 558 558 1680 558 558 558 1680 558 558 558 40000
#
```

Fields:
- `name` — button label.
- `type` — literal `raw`.
- `frequency` — integer Hz, the carrier. `38000` / `40000` / `36000` / `37000` / `56000` typical.
- `duty_cycle` — LED duty cycle float, usually `0.33` (stock) or `0.50`.
- `data` — **space-separated microsecond integers**, alternating on/off. First value = initial on, second = first off, etc.

---

## 3. Full example — a mini TV remote file

```
Filetype: IR signals file
Version: 1
#
name: Power
type: parsed
protocol: NEC
address: 40 BF 00 00
command: 12 ED 00 00
#
name: Vol_up
type: parsed
protocol: NEC
address: 40 BF 00 00
command: 14 EB 00 00
#
name: Vol_dn
type: parsed
protocol: NEC
address: 40 BF 00 00
command: 15 EA 00 00
#
name: Mute
type: parsed
protocol: NEC
address: 40 BF 00 00
command: 16 E9 00 00
#
```

All four buttons share the same address `0x40BF` — that's the device ID, consistent across the remote's buttons. Commands differ per button.

---

## 4. Universal remote files

The Universal Remote app reads from a fixed set of paths:

- `/ext/infrared/universal/tv.ir` — power, volume, channel, source, mute, play/pause.
- `/ext/infrared/universal/audio.ir` — amp / AV receiver buttons.
- `/ext/infrared/universal/ac.ir` — air-conditioner modes.
- `/ext/infrared/universal/digital_tv.ir` — STB / cable box.
- `/ext/infrared/universal/fan.ir` — ceiling fans.

Each of these is a single `.ir` file with *many* signals under the same name (the app plays them in sequence, stopping when the TV responds). If the user adds their own brand's codes, they go into these files under the correct universal button name — the Universal Remote app sequences by `name` match.

---

## 5. Signal naming conventions (for Universal Remote to recognize)

For the bundled Universal Remote app to pick up custom additions, `name:` must match one of:

**TV:** `POWER`, `VOL+`, `VOL-`, `CH+`, `CH-`, `MUTE`.
**Audio:** `POWER`, `VOL+`, `VOL-`, `MUTE`, `PLAY`, `PAUSE`, `STOP`, `NEXT`, `PREV`.
**AC:** `OFF`, `Dh` (dehumidify), `Cool_lo`, `Cool_hi`, `Heat_lo`, `Heat_hi`.

Mismatched names (e.g., `Power ON`) will be visible in the regular Infrared app but ignored by Universal Remote.

---

## 6. Sidecar metadata (`<name>.echoforge.json`)

Echoforge's Payload Forge adds a sibling JSON:

```json
{
  "schema": "echoforge.payload.v1",
  "kind": "infrared",
  "name": "lg_oled_c2_tv",
  "description": "LG OLED C2 living-room TV, NEC-based",
  "author": "operator@example.com",
  "tags": ["personal", "tv"],
  "created_utc": "2026-04-22T18:00:00Z",
  "modified_utc": "2026-04-22T18:00:00Z",
  "source": {
    "tool": "payload_ir_import_capture",
    "content_hash": "sha256:..."
  },
  "policy_tag": null
}
```

The `.ir` is authoritative; sidecar is advisory.

---

## 7. Edit gotchas

- **No blank lines inside a signal block.** Parser treats blank line + next `name:` as a corrupt block.
- **`#` separator is mandatory** even before EOF. Missing trailing `#` means the last signal gets dropped on some firmwares.
- **Address/command fields always 4 bytes.** Even for NEC (which uses 1), pad with `00`. Using 2 bytes breaks parse.
- **`data:` is one line.** Don't wrap. Flipper's parser reads to EOL for the microsecond list. Very long raw captures (air-con, >100 samples) still go on one long line.
- **µs values are at most 6 digits** in practice (max ~100 ms between pulses). Longer gaps mean separate keypresses, not one signal.
