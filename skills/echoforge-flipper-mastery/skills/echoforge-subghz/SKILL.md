---
name: echoforge-subghz
description: Read, interpret, retune, and reason about Flipper Zero .sub files and the Sub-GHz protocols they encode — KeeLoq, Princeton, CAME, Nice Flo, Somfy RTS, Security+, Holtek, HCS301, DoorHan, and raw captures across the 300-348 / 387-464 / 779-928 MHz bands. Use when the user shares a .sub file, asks why a rolling-code capture fails on replay, plans a retune, or needs the legal/regional frequency reference.
---

# Flipper Zero Sub-GHz

You are the expert reference for Flipper Zero's 300-928 MHz radio work — the CC1101-driven Sub-GHz subsystem that reads, decodes, and retransmits `.sub` files. This skill covers protocol semantics (why replay works on fixed-code and fails on rolling-code), the `.sub` file format, and the regional-allocation map you need to stay legal.

## When to activate

Load this skill when the user:
- Shares a `.sub` file or its contents (starts with `Filetype: Flipper SubGhz ...`).
- Asks about a Sub-GHz protocol by name: KeeLoq, Princeton / PT2262, CAME, Nice Flo, Somfy RTS, Security+ 1.0/2.0, Holtek, HCS301, HCS361, DoorHan, BinRAW, RAW.
- Asks "why did my replay attack fail?" on a garage door, gate, TPMS sensor, car key, or RKE.
- Mentions frequencies: `315 MHz`, `390 MHz`, `433.92 MHz`, `868 MHz`, `915 MHz`, or `AM650`, `AM270`, `FM238`, `FM476`.
- Uses the Payload Forge `payload_subghz_list` / `payload_subghz_inspect` / `payload_subghz_retune` / `payload_subghz_import_capture` / `payload_subghz_transmit` tools.
- Asks about regional legality of TX on a band (US vs EU vs JP).
- Asks about rolling-code attacks: RollJam, RollBack, Rolling-PWN.

## Core knowledge

**The Sub-GHz stack on Flipper.** The hardware is a Texas Instruments CC1101 transceiver wired to the MCU over SPI, frontended by an SMD antenna plus an SMA-female external option. The firmware at `flipperdevices/flipperzero-firmware/lib/subghz/` provides a protocol stack that decodes captured pulse-trains into named protocols. You interact with it via the **Sub-GHz** app on the device. Captures save to `/ext/subghz/<name>.sub`.

**Fixed-code vs rolling-code — the single most important distinction.**
- **Fixed-code** protocols (Princeton PT2262, Holtek HT12E, CAME, Nice Flo non-hopping, old garage doors before ~2005): the same bits go over the air every time you press the button. Capture once, replay forever. These are ~12-24 bits of trinary or binary data and almost always work on replay.
- **Rolling-code** protocols (KeeLoq HCS200/300/301/360/361, Security+ 1.0/2.0, Somfy RTS, CAME ATOMO, Nice FloR, DoorHan): each press increments a counter encrypted under a device-specific key, so the captured packet is consumed by the receiver and will be rejected on replay. To attack these you need either: (a) **RollJam** (jam the receiver while capturing two consecutive presses; release the second; the receiver still accepts the first); (b) **Rolling-PWN** (counter-resync vulns in specific firmwares — e.g. Honda 2012-2022); (c) **RollBack** (many receivers accept an old code if re-presented in a specific time window — Csikor et al. ACM TCPS 2024); (d) **DPA/cryptanalysis of the key** (academic, offline, not a field attack).

**Replay-ability cheat sheet.**

| Protocol | Fixed/Rolling | Replay works? | Notes |
|----------|---------------|---------------|-------|
| Princeton PT2262 | Fixed, 12-bit trinary | Yes, always | Default for el-cheapo 433 remotes; CAME/Nice non-hopping derive from this |
| Holtek HT12E / HT6P20B | Fixed, 12/24-bit | Yes | Same niche |
| CAME 12-bit / 24-bit | Fixed | Yes | Italian gate remotes ~1990s-2010s |
| Nice Flo 12/24-bit | Fixed | Yes | Italian shutter remotes |
| CAME ATOMO | Rolling | No | Italian hopping variant; Flipper decodes but replay fails |
| Nice FloR (rolling) | Rolling | No | Hopping sibling of Flo |
| KeeLoq HCS301/361 | Rolling 66-bit | No | Microchip; used in ~50% of rolling-code remotes globally |
| Security+ 1.0 (Chamberlain) | Rolling | No | Pre-2011 Liftmaster/Chamberlain |
| Security+ 2.0 | Rolling | No | 2011+; AES-based; extremely hardened |
| Somfy RTS / Telis | Rolling | No | French shutter/blind; but Flipper can *program a new remote* onto an existing receiver via the teach-in sequence |
| DoorHan | Rolling | No | Ukrainian/Russian garage openers |
| Linear Megacode | Fixed 24-bit | Yes | US commercial gates, aging |
| TPMS (Schrader/Continental/Pacific/Huf) | Broadcast beacon | N/A — receive-only | Flipper can decode and track tire sensors; no useful replay |

**Frequency bands you will see.** Flipper's CC1101 supports three sub-bands: `300-348 MHz`, `387-464 MHz`, `779-928 MHz`. Out-of-the-box the firmware ships with region-locked TX allowlists (`subghz_frequency_analyzer_worker.c`). An `Unleashed`/`Momentum`/`Xtreme` firmware unlocks all TX — legal on YOUR property, illegal on public bands (see `references/frequencies.md` for the full allocation table and the public-safety/aircraft/weather bands that are federal crimes to transmit on).

**The `.sub` file.** Plaintext key-value header + either a decoded `Key: ` line (for named protocols) or a `RAW_Data: ` numeric list of pulse durations in microseconds (for unrecognized captures). The header is authoritative: `Frequency`, `Preset`, `Protocol`, plus protocol-specific fields. Retuning = rewriting `Frequency` and/or `Preset` without touching the data. See `references/subfile-format.md`.

## Deep references

- **Protocol deep-dive** — bit-layout, modulation, known attacks, firmware source pointers for KeeLoq, Princeton, CAME, Nice Flo, Somfy, Security+, Holtek, HCS301, DoorHan → `references/protocols.md`
- **Frequency bands & regional legality** — ISM band allocations by region, public-safety/aircraft/weather bands that are off-limits, firmware TX-unlock behavior → `references/frequencies.md`
- **.sub file format** — full header schema, RAW_Data microsecond encoding, Preset allowlist, how Flipper parses it → `references/subfile-format.md`

## Don't confuse with

- **LoRa (LoRaWAN)** — 433/868/915 MHz long-range chirp-spread. Flipper's CC1101 does **not** support LoRa; you'd need the 2.4 GHz or LoRa dev-board companions. If a user says "LoRa", Sub-GHz knowledge doesn't apply.
- **Wi-Fi 2.4/5 GHz** — wildly different band and protocol stack; Flipper uses the ESP32 dev-board companion, not CC1101.
- **Bluetooth / BLE** — Flipper has a native NRF51822 BLE radio, a separate subsystem entirely. `.sub` files don't exist for BLE.
- **NFC (13.56 MHz) / RFID (125 kHz)** — different frequency range, different app (`NFC` / `125 kHz RFID`), different file extensions (`.nfc`, `.rfid`). Sub-GHz is strictly 300-928 MHz.
- **IR (~38 kHz carrier)** — also separate app and file format (`.ir`). See `echoforge-ir`.
- **Sub-GHz jamming files** — a grey-zone category of `.sub` files that transmit continuous-wave garbage to deny a receiver. Removed from Flipper mainline; exist on GitHub as `SHUR1K-N/Flipper-Zero-Sub-GHz-Jamming-Files`. Transmitting these is illegal in most jurisdictions. Skill does not author them; it can explain what they do.
