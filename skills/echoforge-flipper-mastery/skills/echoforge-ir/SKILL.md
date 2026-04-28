---
name: echoforge-ir
description: Decode, interpret, and build Flipper Zero .ir files across NEC, NEC-Extended, RC5, RC6, Sony SIRC, Samsung32, Kaseikyo/Panasonic, and Pronto Hex formats. Use when the user shares an .ir file, asks what a captured IR button does, wants to build a universal remote, or debugs a "TV won't respond" issue.
---

# Flipper Zero Infrared (IR)

You are the expert reference for Flipper's Infrared app — the 38 kHz / 40 kHz / 56 kHz modulated-IR subsystem that captures, decodes, and emits consumer-electronics remote signals. This skill covers the named protocols, `.ir` file format, Pronto Hex interop, and diagnostic questions like "why does my Samsung TV ignore my capture?".

## When to activate

Load this skill when the user:
- Shares a `.ir` file or its content (starts with `Filetype: IR signals file`).
- Asks about an IR protocol by name: NEC, NEC-Extended, NECext, RC5, RC5X, RC6, Sony SIRC, Samsung32, Kaseikyo, Panasonic.
- Asks about Pronto Hex codes or wants to convert Pronto → `.ir`.
- Is building a universal remote (`universal/tv.ir`, `universal/ac.ir`, `universal/audio.ir`, `universal/digital_tv.ir`).
- Uses the Payload Forge `payload_ir_list` / `payload_ir_inspect` / `payload_ir_import_capture` / `payload_ir_transmit` tools.
- Asks why an IR signal captures but doesn't control the device ("my TV won't turn on").

## Core knowledge

**The IR stack on Flipper.** An IR receiver (TSOP-compatible photodiode on the front) demodulates the 38/40/56 kHz carrier and produces a clean digital pulse-train to the MCU. TX is a pair of IR LEDs on the top driven by PWM at the same carrier. Both RX and TX are single-direction (point-and-fire), line-of-sight, ~5-10 m range outdoors, less through windows or off-axis.

The firmware at `flipperdevices/flipperzero-firmware/lib/infrared/` contains a protocol stack with parsers for the major CE-remote families. Captures save to `/ext/infrared/<name>.ir`. The Universal Remote app reads from a fixed set: `/ext/infrared/universal/tv.ir`, `audio.ir`, `ac.ir`, `digital_tv.ir`, `fan.ir` — each a bundled grab-bag of `POWER`, `VOL_UP`, `CH_UP`, etc. across many vendors. The user's own captures live flat in `/ext/infrared/`.

**The five protocols that cover 95% of consumer remotes.**

| Protocol | Carrier | Bit encoding | Frame | Range example |
|----------|---------|--------------|-------|---------------|
| **NEC** | 38 kHz | Pulse distance (~560 µs pulse, 560 µs or 1690 µs gap) | 9ms leader + 4.5ms space + 32 bits (8 addr + 8 ~addr + 8 cmd + 8 ~cmd) + stop pulse | TVs, most Asian CE |
| **NEC-Extended (NECext)** | 38 kHz | Same | 32 bits: 16 addr + 8 cmd + 8 ~cmd | When 8-bit addr is too few |
| **RC5** (Philips) | 36 kHz | Manchester (~889 µs half-bit) | 14 bits (2 start + toggle + 5 addr + 6 cmd), start bits are '1' so toggle = 3rd bit | Old Philips TVs |
| **RC6** (Philips) | 36 kHz | Manchester with a 2x-wide trailer bit | Mode-0: 21 bits incl. toggle; Mode-6 = MCE remote | Windows Media Center remote |
| **Sony SIRC** | 40 kHz | Pulse length (600 µs base, 1.2 ms for '1', 0.6 ms for '0') | 2.4 ms leader + 12/15/20 bits; 40 kHz carrier | Sony TVs, playstation |
| **Samsung32** | 38 kHz | Pulse distance (NEC-like) | 4.5ms leader + 4.5ms space + 32 bits (16 addr + 16 cmd, different from NEC) | Samsung TVs |
| **Kaseikyo (Panasonic / Mitsubishi / JVC / Denon)** | 37 kHz | Pulse distance | 3.4ms leader + 1.7ms space + 48 bits (16 mfr + 4 parity + 4 ~parity + 24 data) | Panasonic, Denon AV |

**Why captures fail to control the device.** Common causes, in order of likelihood:
1. **Carrier mismatch.** Capture at 38 kHz, TX at 38 kHz; but a Sony remote uses 40 kHz. Flipper's receiver is broadband, so captures work; Flipper's transmitter locks to one freq per protocol, and if the `.ir` file says `parsed` with protocol Sony, it knows to emit 40. But a **RAW** capture inherits the device's carrier at capture time and may not retune correctly — see `frequency` field below.
2. **Address/command byte-order confusion.** Some third-party `.ir` files list NEC addresses little-endian, others big-endian. Flipper stores them per its firmware convention; if you edit the hex by hand and flip endianness, the signal won't match.
3. **RC5/RC6 toggle bit stuck.** RC5 has a 1-bit toggle that flips on each keypress; a receiver may ignore two consecutive frames with the same toggle. If you're retransmitting the same capture repeatedly and it only works every other time, this is why.
4. **Off-axis / too far.** IR is line-of-sight with ±30° cone from the LED. Aim matters.
5. **The device is asleep and IR wakeup isn't in the same protocol.** Some TVs respond to wake-on-IR only on specific power commands; the capture might be a valid VOL_UP but won't wake the TV.

**The `.ir` file.** Multi-signal container. One file holds 1-N named buttons. Each button is either **parsed** (named protocol + address + command hex) or **raw** (frequency + duty cycle + timing µs list). See `references/irfile-format.md`.

## Deep references

- **Protocol deep-dive** — bit layouts, timings, decoder logic, firmware source pointers for NEC/NECext/RC5/RC6/SIRC/Samsung32/Kaseikyo → `references/protocols.md`
- **Pronto Hex** — parsing, converting to `.ir`, why Pronto is the lingua franca of IR code databases → `references/pronto-hex.md`
- **`.ir` file format** — multi-signal container schema, parsed vs raw signals, Flipper firmware parser behavior → `references/irfile-format.md`

## Don't confuse with

- **Sub-GHz radio** — 300-928 MHz RF, totally different stack. See `echoforge-subghz`.
- **IrDA** — the 1990s-2000s bidirectional data protocol (laptops, PDAs). Flipper does *not* speak IrDA; it's a one-way CE-remote emitter only.
- **IR laser / IR cameras** — wildly different use cases; Flipper's IR is ~940 nm LED diffuse emission, not coherent.
- **Bluetooth HID "remote"** (Apple TV Siri remote, newer Samsung remotes) — these do NOT use IR. Flipper can't capture or emit these; you need the BLE stack.
- **"Smart TV" RF remotes** (some LG Magic Remote, Amazon Fire TV) — these use 2.4 GHz BLE or Zigbee, not IR. Flipper's IR app won't see them at all.
