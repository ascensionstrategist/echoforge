# IR Protocols — Bit Layout, Timing, Decoder Logic

Source: `flipperdevices/flipperzero-firmware/lib/infrared/encoder_decoder/` — one `.c` per protocol. Timings quoted below are the firmware defaults; real-world remotes drift ±5%.

---

## NEC (the canonical)

**Carrier:** 38 kHz. **Source:** `nec/infrared_decoder_nec.c`.

**Frame.**

```
[9 ms carrier on][4.5 ms off][32 bits][562 µs stop pulse]

Bit '0' = 562 µs on, 562 µs off
Bit '1' = 562 µs on, 1687 µs off
```

**Payload (standard NEC).**
- 8-bit address (LSB first)
- 8-bit inverted address (for checksum)
- 8-bit command
- 8-bit inverted command

Total 32 bits. Total frame duration ~67 ms.

**Repeat code.** If the key is held, the remote sends a 9 ms leader + 2.25 ms space + 562 µs pulse every 110 ms. Flipper recognizes this as a NEC repeat; `.ir` files store it implicitly.

**Addressing math.** Many "universal" NEC code databases list addresses as 16-bit even when the protocol is 8+~8. To match Flipper: take the hex you have, check if byte 2 is the bitwise inverse of byte 1. If yes → plain NEC, use byte 1 as `address`. If no → NECext, use both bytes as `address`.

---

## NEC-Extended (NECext)

Same carrier/timing as NEC. 32 bits structured as **16-bit address + 8-bit command + 8-bit inverted command** (the inverted-address checksum byte is dropped in favor of more address bits). Used when an 8-bit address space can't enumerate enough device models.

In a `.ir` file, a parsed NECext signal looks like:
```
protocol: NECext
address: AD 12 00 00
command: 45 BA 00 00
```
Even though the fields are shown as 4 bytes with leading zeros, the protocol truly only uses the first 2 bytes of each.

---

## RC5 (Philips)

**Carrier:** 36 kHz. **Source:** `rc5/infrared_decoder_rc5.c`.

**Manchester encoding.** Each bit is 1.778 ms long, split into two 889 µs half-bits.
- `0` = high-then-low (carrier 889 µs, silence 889 µs)
- `1` = low-then-high

**Frame.** 14 bits total:
- 2 start bits (always `11` in RC5; the 2nd is actually field/address extension `S2` in RC5X)
- 1 toggle bit `T`
- 5 address bits `A4..A0`
- 6 command bits `C5..C0`

**Toggle.** Flips (`T ^= 1`) on every *new* key press. If the user holds the key, the same frame (same T) is resent every ~113 ms. Receivers often filter: same T = held, different T = new press. If your replay keeps T constant, receiver may register only the first press.

**RC5X (extended).** 7 command bits by repurposing S2 as the command MSB. Supports more commands per address.

---

## RC6 (Philips)

**Carrier:** 36 kHz. **Source:** `rc6/infrared_decoder_rc6.c`.

Manchester-encoded, but **the 4th bit (toggle) is double-width** — 1.778 ms each half instead of 889 µs. This is the tell for RC6 vs RC5.

**Frame (Mode 0).** 2.666 ms on + 0.889 ms off leader + 1 start bit + 3 mode bits + 1 toggle + 8 addr + 8 cmd = 21 total.

**Frame (Mode 6 = MCE).** Used for the Microsoft Media Center Remote (Vista-era but still sold). 36-bit payload including a customer code and OEM bytes.

**Toggle bit on RC6.** Same semantic as RC5.

---

## Sony SIRC (12/15/20-bit)

**Carrier:** 40 kHz. **Source:** `sirc/infrared_decoder_sirc.c`.

**Frame.** 2.4 ms leader + pulse-length-encoded bits:
- `0` = 600 µs on, 600 µs off
- `1` = 1200 µs on, 600 µs off

**Payload variants.**
- **12-bit:** 7-bit command + 5-bit address (most common Sony TVs)
- **15-bit:** 7-bit command + 8-bit address
- **20-bit:** 7-bit command + 5-bit address + 8-bit extended (VCRs, camcorders)

**Repeat.** Frame is resent every 45 ms on hold; Sony receivers require *at least 3* consecutive frames to register a press. Single-frame replays often fail — Flipper's Sony TX emits 3 frames by default; if you hand-crafted a raw version, don't forget this.

**MSB order.** Sony transmits LSB first but Flipper's `.ir` `command`/`address` fields show the value as big-endian hex. If you're matching against an LIRC config (LIRC stores LSB-first), bit-reverse the hex.

---

## Samsung32

**Carrier:** 38 kHz. **Source:** `samsung32/infrared_decoder_samsung32.c`.

**Frame.** 4.5 ms on + 4.5 ms off leader + 32 bits + 560 µs stop. Bit encoding is NEC-style pulse-distance.

**Payload.** 8-bit custom + 8-bit custom (again, for checksum) + 8-bit data + 8-bit ~data. Looks like NEC structurally, differs in the leader timings (NEC: 9ms+4.5ms; Samsung: 4.5ms+4.5ms).

**Collision with NEC.** A naive decoder sometimes labels Samsung as NEC. If a "NEC" `.ir` won't control a Samsung TV, try changing the protocol to `Samsung32` and retransmitting.

---

## Kaseikyo (Panasonic, Mitsubishi, JVC, Denon)

**Carrier:** 37 kHz. **Source:** `kaseikyo/infrared_decoder_kaseikyo.c`.

**Frame.** 3.4 ms leader + 1.7 ms space + 48 bits + stop pulse.

**Payload.** 16-bit manufacturer ID + 4 bits parity + 4 bits parity inverse + 24-bit data. Manufacturer IDs are fixed per vendor:
- Panasonic: `0x2002`
- Denon: `0x3254`
- Mitsubishi: `0xCB23`
- JVC: `0x0357`

If you have a `.ir` labeled "Panasonic" but the mfr ID is wrong, it's likely misidentified. Fix the field and retransmit.

---

## RAW (unknown / hand-crafted)

Any signal that doesn't decode falls into RAW. Stored as:
- `frequency` — the carrier (typically 38000 or 40000)
- `duty_cycle` — LED duty cycle, `0.33` default (33% on)
- `data` — space-separated microsecond integers, alternating on/off durations

RAW files are carrier-frequency sensitive. If you capture a 40 kHz Sony signal while Flipper's default IR RX is 38 kHz... Flipper's TSOP sensor is broadband enough that it still demodulates, but if you retransmit at 38 kHz, many Sony TVs won't respond because they expect 40 kHz. **Always check `frequency:` field on a RAW signal before retransmitting** — if it's 38000 but the device is Sony, change to 40000.

---

## Firmware source pointers

- `flipperdevices/flipperzero-firmware/lib/infrared/encoder_decoder/common/` — shared timing primitives.
- `flipperdevices/flipperzero-firmware/lib/infrared/encoder_decoder/<protocol>/` — per-protocol encoder + decoder.
- `flipperdevices/flipperzero-firmware/lib/infrared/infrared_raw_file.c` — RAW file IO.
- `flipperdevices/flipperzero-firmware/applications/main/infrared/` — app UI.

## Decoding an unknown capture

If the user asks "what protocol is this?":

1. **Carrier tells you a lot.** `frequency: 36000` → RC5/RC6. `40000` → Sony. `37000` → Kaseikyo. `38000` → NEC/Samsung32/generic.
2. **Leader tells you the rest.** First two positive integers in the `data:` list are the leader:
   - 9000/4500 → NEC
   - 4500/4500 → Samsung32
   - 3400/1700 → Kaseikyo
   - 2666/889 → RC6
   - 2400/600 → Sony
   - First bit of 889 µs without distinct leader → RC5
3. **Bit count for sanity check** — NEC 32, Samsung32 32, Sony 12/15/20, RC5 14, RC6 21, Kaseikyo 48. If you count pulses in `data:` and get ~65 = NEC (32 bits × 2 edges + leader + stop).
