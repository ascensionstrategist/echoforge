# Sub-GHz Protocols — Bit Layout, Modulation, Known Attacks

Primary source: `flipperdevices/flipperzero-firmware/lib/subghz/protocols/` — each protocol has a `.c` and `.h`. When a claim here is firmware-specific, the file is named.

---

## Princeton PT2262 (fixed-code, 12-bit)

**Source:** `princeton.c` (also used by `came.c` and `nice_flo.c` as parent).

**Structure.** 12 trinary symbols (each '0', '1', or 'F') followed by a sync bit. Each trinary symbol is 4 pulses:
- `'0'` — short-high, long-low, short-high, long-low (`_--_--`)
- `'1'` — long-high, short-low, long-high, short-low (`--_-_-` inverted)
- `'F'` (floating) — short-high, long-low, long-high, short-low

Symbol time α is typically 400 µs; total frame = ~12 × 4α + sync ≈ 20 ms.

**Modulation.** OOK/AM (amplitude-shift keying), 433.92 MHz most common. Flipper preset `AM650` for bandwidth 650 kHz, `AM270` for 270 kHz. Try `AM650` first if decode fails.

**How the 12 bits are used.** 10 address bits + 2 data bits, or 8 address + 4 data depending on the chip variant. DIP-switch-configurable remotes expose this directly — the switches ARE the address bits.

**Attack.** Replay works unconditionally. Brute-force works against any DIP-switch remote in finite time: `3^12 = 531441` combinations, each takes ~20 ms to transmit, worst case ~3 hours full sweep. The `tobiabocchi/flipperzero-bruteforce` repo ships pre-generated `.sub` files for full sweeps of PT2262/HT12E/CAME/Nice Flo.

---

## Holtek HT12E / HT6P20B (fixed-code)

**Source:** `holtek_ht12x.c`.

HT12E is identical to PT2262 at the protocol level (12-bit trinary), different silicon. HT6P20B is a 24-bit variant. Same replay/brute-force attack surface.

---

## CAME (fixed-code 12/24-bit) & CAME ATOMO (rolling)

**Source:** `came.c`, `came_atomo.c`.

**CAME plain** — 12-bit Princeton-compatible for older TOP/TAM remotes, 24-bit for TOP-xxxEV.
**CAME ATOMO** — hopping code, 64-bit frame. Each press increments a counter. Flipper decodes but stores the captured frame as-is; replay fails because the counter advances.

**Attack on ATOMO.** Capture two consecutive presses, replay the newer one into the receiver once the legitimate remote has been out of range long enough that its counter hasn't advanced past it. Sketchy in practice. RollBack-style timing attack works on specific firmware revisions.

---

## Nice Flo / FloR / Smilo / Lince

**Source:** `nice_flo.c`, `nice_flor_s.c`.

Italian gate opener family. **Nice Flo** non-hopping is 12-bit fixed (PT2262-compatible); Flipper decodes and replays. **Nice FloR-S** is rolling, proprietary Motorola algorithm; Flipper decodes into the file but replay doesn't work. **Smilo** is a Nice sub-brand with its own rolling variant, also decoded but not replayed.

---

## KeeLoq (rolling, 66-bit, ubiquitous)

**Source:** `keeloq.c`, `keeloq_common.c`, `keeloq_mfcodes`.

Microchip IP, used in ~50% of rolling-code garage/gate remotes globally, and in many vehicle RKE systems pre-2010. **Bit layout** of the 66-bit transmitted frame:
- 32-bit encrypted portion: 4-bit button code + 2-bit OVR + 10-bit discrimination value + 16-bit sync counter, all encrypted under a 64-bit NLFSR cipher with the device key.
- 28-bit serial number (plaintext).
- 4-bit button code (plaintext, repeated).
- 2-bit VLOW + status.

**Cryptography.** KeeLoq is a 64-bit NLFSR (Non-Linear Feedback Shift Register) block cipher with a 32-bit block size and 64-bit key, 528 rounds. Theoretical break: Bogdanov 2007 (slide attack, 2^52 ops); practical break: Eisenbarth/Kasper/Moradi/Paar 2008 DPA side-channel from the fob itself; eprint/2011/242 consolidates. None of these are field-deployable against a rolling-code receiver you don't have a fob for.

**Device key derivation.** The manufacturer owns a 64-bit **manufacturer key** and derives each device key from it by encrypting the device's serial number. If you capture the manufacturer key (which has leaked for several vendors — see eprint/2011/242), any device from that vendor can be cloned from just a sniff of two consecutive presses. Flipper's Momentum firmware ships a `keeloq_mfcodes` file with publicly-known manufacturer keys (Faac, Nice, etc.).

**Attacks that work in the field.**
- **RollJam** (Samy Kamkar 2015) — jam the receiver while the legitimate user presses; capture the press; block the press from reaching the receiver; on second press, let the second one through and keep the first to replay later. Needs two SDRs (jam + capture) + timing; Flipper-native implementation is possible but finicky.
- **RollBack** (Csikor et al. ACM TCPS 2024, https://dl.acm.org/doi/10.1145/3627827) — replay old codes within a timing window that many receivers mistakenly accept.
- **Rolling-PWN** (Honda 2012-2022) — specific implementation bug: consecutive counter values resync the receiver, so a two-frame capture replayed unlocks the car.

**HCS200 vs HCS300 vs HCS301 vs HCS360/361.** HCS200/300/301 are the canonical 66-bit-frame Microchip variants. HCS360/361 add IFF (Identification-Friend-or-Foe) challenge-response; still KeeLoq under the hood but extra bidirectional step, replay fails. DoorHan is a KeeLoq variant with slight framing differences (`doorhan.c`).

---

## Security+ 1.0 and 2.0 (Chamberlain / LiftMaster / Craftsman)

**Source:** `security_plus_1.c`, `security_plus_2.c`.

**Security+ 1.0** — pre-2011 US garage-door industry standard. 40-bit rolling code with a 8-bit counter increment per press. Flipper decodes and archives; replay fails.

**Security+ 2.0** — 2011+, AES-128-based rolling code. No public break. The only attack surface is RollJam and RollBack-family timing issues, and Security+ 2.0 receivers shipped after ~2015 generally close those windows. Assume Security+ 2.0 is replay-proof for practical purposes.

---

## Somfy RTS / Telis

**Source:** `somfy_telis.c`, `somfy_keytis.c`.

French shutter/blind/awning rolling-code remote. 56-bit frame, proprietary stream cipher. The interesting property: Somfy receivers have a **teach-in** mode (hold the PROG button for 2 s on an existing paired remote), after which the receiver accepts any new remote that presses for 2 s. Flipper can act as the "new remote" — this is a legitimate feature for users who own the receiver.

---

## Other commonly-encountered protocols

- **Linear / Multi-Code / DeltaMultiCode** — older US commercial gates, 10-bit fixed. Replay works.
- **Cenit** — Italian 12-bit fixed.
- **Gate TX** — various generic 24-bit fixed Asian garage remotes.
- **Hormann HSM** — German garage, rolling; `hormann.c`.
- **Magellen** — HomeLink-alike, fixed.
- **Star Line** — Russian car alarm brand, rolling.
- **TPMS (Tire Pressure Monitoring)** — Schrader, Continental, Pacific, Huf Hitag, Toyota. Periodic beacons ~2-10x/minute at 315 (US) / 433 (EU) MHz. Flipper decodes and logs pressure + sensor ID passively; this is pure RX, no TX/replay semantics.

---

## How to know which protocol a capture is

1. Open the `.sub` in a text editor. If the header line reads `Protocol: Princeton` / `Protocol: KeeLoq` / etc., Flipper already knows.
2. If the header says `Protocol: RAW`, the firmware couldn't identify it. Open the Sub-GHz Analyzer on the Flipper and press "Read" while you retransmit — sometimes decode succeeds on a second try with better signal-to-noise.
3. `payload_subghz_inspect` returns the same header info + `RAW_Data` pulse statistics. Pulse-count histograms are diagnostic: PT2262 has ~50 edges per frame; KeeLoq ~130; Somfy ~115.

---

## Integration with echoforge tools

- `payload_subghz_inspect <path>` returns parsed header + raw stats.
- `payload_subghz_retune <source> <dest> --frequency X --preset Y` changes tuning without touching the bit content. Use this to test whether a capture was mis-tuned (common: a 433.07 MHz capture sometimes needs to go out at 433.92 MHz, or an AM270 capture needs AM650).
- `payload_subghz_transmit <path>` broadcasts. The tool classifies this HIGH risk with `requires_hold=y` — actual RF emission.

Never synthesize RAW_Data from first principles in this phase of echoforge; always retune or replay an existing capture. Synthesis introduces a huge false-positive surface.
