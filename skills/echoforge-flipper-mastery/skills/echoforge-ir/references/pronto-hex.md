# Pronto Hex — The IR Lingua Franca

Pronto Hex (aka "CCF format") is the de-facto interchange format for IR signals, published by Philips for the Pronto learning-remote product line in the late 1990s. Every IR code database of note — RemoteCentral, LIRC, JP1, irdb.tk — publishes codes as Pronto Hex.

A Pronto string looks like:

```
0000 0067 0000 0015 0060 0018 0030 0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 0030 0018 0018 0018 03F6
```

Each 4-hex-digit "word" is a 16-bit big-endian value. Every Pronto Hex code has a structured header and a sequence of burst pairs.

---

## Structure

| Word index | Meaning |
|------------|---------|
| 0 | **Format code.** `0000` = learned (raw) code. `0100` = RC5. `0101` = RC5X. `0102` = RC6 Mode 0. Other non-zero values = UEI-proprietary variants. For Flipper interop, only `0000` is widely convertible. |
| 1 | **Carrier frequency divisor.** Carrier Hz = `1000000 / (word1 * 0.241246)` ≈ `4145146 / word1`. For a 38 kHz signal, word1 = `0x006D` (109 decimal). For 40 kHz, `0x0067` (103). |
| 2 | **Once-sequence pair count.** Number of (on-µs, off-µs) pairs that play exactly once (the "burst"). |
| 3 | **Repeat-sequence pair count.** Number of pairs that play once, then loop while the button is held. |
| 4..N | **Pair data.** Each pair is 2 words: first = carrier cycles ON, second = carrier cycles OFF. |

**Converting cycles to microseconds:** pair_µs = cycles × (1 / carrier_Hz) × 1e6.
At 38 kHz: 1 cycle = 26.3 µs. So Pronto word `0x0060` (96 cycles) = 2526 µs ≈ 2.5 ms leader — a NEC-ish leader.

---

## Parsing the example above

```
0000                   # learned format
0067                   # carrier = 4145146 / 103 = 40,244 Hz ≈ 40 kHz → Sony
0000                   # once-sequence has 0 pairs (all repeat)
0015                   # repeat-sequence has 21 pairs (42 words)
0060 0018              # 96 on, 24 off = 2400 µs on, 600 µs off → Sony leader
0030 0018              # 48 on, 24 off = 1200 µs on, 600 µs off → Sony '1' bit
0018 0018              # 24 on, 24 off = 600 µs on, 600 µs off → Sony '0' bit
...                    # 12 total bit-pairs → Sony 12-bit SIRC
03F6                   # final off — trailing silence before next repeat
```

Decoded: **Sony SIRC 12-bit**. The bit pattern reads out whichever command you captured.

---

## Converting Pronto → Flipper `.ir`

Two paths:

### Path 1: Decoded (clean `.ir`)

If the Pronto is a known protocol (NEC, NECext, RC5, RC6, SIRC, Samsung32, Kaseikyo), decode the Pronto bit-pattern into its protocol + address + command, then emit:

```
name: Power
type: parsed
protocol: SIRC
address: 01 00 00 00
command: 15 00 00 00
```

Flipper's Infrared app can then emit with the correct repeat count and carrier.

### Path 2: Raw (just-works)

If the protocol isn't recognized or you don't care, emit the Pronto as a RAW signal:

```
name: Power
type: raw
frequency: 40000
duty_cycle: 0.33
data: 2400 600 1200 600 600 600 1200 600 1200 600 600 600 1200 600 600 600 1200 600 600 600 600 600 600 600 600 600
```

Convert each Pronto pair (on-cycles, off-cycles) to microseconds using the carrier derived from word1. Flatten into the `data:` µs list.

---

## Converting Flipper `.ir` → Pronto

Rare, but useful if you want to upload a capture to a database like RemoteCentral.

For a **parsed** signal, re-encode from protocol + addr + cmd to the wire bit pattern, then to Pronto pairs.
For a **raw** signal, the µs list is already pair-form; convert to cycles at the carrier (e.g., divide each µs by 26.3 for 38 kHz), group into 2-word pairs, prepend the 4-word header (`0000 [carrier_divisor] 0000 [pair_count]`).

---

## Common Pronto gotchas

1. **Word1 bit 15.** Some Pronto codes set the high bit of word1 (e.g. `80E2`) — that's a "modulated by external carrier" flag used on UEI remotes. Strip it before computing carrier (`word1 & 0x7FFF`).
2. **Learned vs defined.** Format code `0000` is learned-from-air and encodes the raw burst. Format `0100-0102` are protocol-defined and need specific decoders. Most databases ship `0000`.
3. **Trailing silence.** Last pair's off-cycles are often long (`03F6` = ~27 ms at 38 kHz). Preserve it or receiving devices may reject repeated frames as "too fast".
4. **Multiple bursts in one code.** Air-con codes especially can have two burst sections (once + repeat). Both need to go into the µs list in order, or just pick `once` + one iteration of `repeat` for a single press.

---

## Reference tools

- **IrScrutinizer** (https://github.com/bengtmartensson/IrScrutinizer) — reads Pronto, produces `.ir`-compatible raw microsecond lists. Ground-truth for tricky conversions.
- **irdb** (https://github.com/probonopd/irdb) — canonical Pronto + CSV database of consumer codes.
