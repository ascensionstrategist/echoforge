# 125 kHz RFID LF — EM4100, EM4305, Indala, AWID, T5577

Low-frequency RFID (125-134 kHz) is the 1990s-style access control: cheap passive tags that broadcast a fixed ID by load-modulating the reader's carrier field. Almost universally no authentication; cloning is near-trivial with a Flipper.

Flipper reads LF through its 125 kHz demodulator (peak frequency response ~125-134 kHz). Writes to blank T5577 or EM4305 tags via the same antenna in programming mode.

---

## EM4100 / EM4102 (the baseline)

**Manufacturer:** EM Microelectronic. The single most common LF format.

**Structure.** 64 bits of Manchester-encoded data at ~2 kbps:
- 9 header bits: `111111111` (always).
- 10 × (4 data nibbles + 1 row parity bit) = 50 bits.
- 4 column parity bits.
- 1 stop bit `0`.

The "real" ID is **40 bits** (8 version + 32 ID). Read as ASCII hex it looks like `0A0B0C0D0E`.

Flipper format:
```
Filetype: Flipper RFID key
Version: 1
Key type: EM4100
Data: 0A 0B 0C 0D 0E
```

**Cloning.** Trivial. Buy a $2 T5577 blank, use Flipper `Write` mode, done. Many access-control systems check only the 40-bit ID, so any EM4100 with the right ID opens the door.

**Related chips:**
- **EM4200** — 128-bit variant.
- **EM4305 / EM4469** — user-writable, password-protected LF tag; can be programmed to emulate EM4100, HID, Indala, AWID, or other formats.

---

## T5577 (the universal LF blank)

**Manufacturer:** Atmel (now Microchip). The go-to programmable LF tag.

**Capabilities.** 7 × 32-bit user blocks + 1 configuration block. The config block controls:
- Modulation (Manchester / Biphase / FSK / PSK).
- Data rate.
- Password protection.
- Starting block offset.

By correctly setting the config, a single T5577 can emulate:
- EM4100
- HID Prox H10301 / Corp 1000 / 37-bit
- Indala 26-bit / 224-bit
- AWID
- Paradox
- Nexwatch / Honeywell

Flipper handles this automatically — you `Read` a source card, then `Write T5577` and Flipper sets the right config block.

**Default password:** `0x51243648` on fresh T5577s, `0x00000000` once sanitized. If a T5577 has been password-locked by a previous owner, Flipper can't read or write it without the password (brute-forceable, but slow).

---

## Indala

**Manufacturer:** Motorola (acquired by HID). Older commercial access format.

**Structure.** Variable-length FSK modulation at 125 kHz.
- **Indala 26-bit** — HID-H10301 format carried over Indala FSK.
- **Indala 64-bit** — longer, proprietary site codes.
- **Indala 224-bit** — even longer, used in legacy high-security deployments.

Flipper recognizes Indala-26-FC (most common) out of the box, reads and clones to T5577 or EM4305.

---

## AWID

**Manufacturer:** AWID (Applied Wireless ID, now HID). 125 kHz FSK competitor to HID Prox.

**Structure.** 26-bit or 50-bit fixed ID, FSK modulation. Flipper clones like Indala — same mental model.

---

## Hitag family

**Manufacturer:** NXP. Wild outlier among LF: **encrypted** rolling-code LF.

- **Hitag1 / Hitag S** — 64-bit ID + crypto, moderately secured.
- **Hitag2** — 48-bit stream cipher, ~50% of European automotive immobilizers pre-2020. Broken: Verdult/Garcia USENIX Sec 2012 recovers the key in under 6 minutes given a few authentication traces. Flipper captures Hitag2 passively; offline crack via hitag2crack (https://github.com/kev169/hitag2crack).
- **Hitag μ (Hitag3)** — AES-128 successor, no practical break.

For vehicle immobilizers specifically: the transponder is a Hitag chip in the key plastic, the reader antenna is the ring around the ignition. Flipper has to be inches from the key and ignition. A Proxmark3 EASY with the right antenna is faster for this specific workflow.

---

## `.rfid` file examples

EM4100:
```
Filetype: Flipper RFID key
Version: 1
Key type: EM4100
Data: 01 23 45 67 89
```

HID Prox H10301 (also stored under `.rfid`):
```
Filetype: Flipper RFID key
Version: 1
Key type: H10301
Data: 12 34 56
```
(3 bytes = 24 bits = 1 parity + 8 FC + 16 card + 1 parity, packed.)

Raw LF capture (unknown format):
```
Filetype: Flipper RFID raw
Version: 1
Data rate: 64
Modulation: ASK
Raw data: ...hex dump...
```

---

## Practical cloning decision tree

```
Does the card read as a known format (EM4100, HID, Indala, AWID)?
├── Yes → Buy a T5577. Flipper Write → done.
└── No → Capture raw LF. Is the modulation ASK/FSK/PSK?
    ├── ASK at 64 bps → likely EM4100 variant.
    ├── FSK at 4/8/10 cycles → likely HID or Indala.
    └── PSK → rare, probably Hitag-family. Consult datasheet.
```

---

## Fuzzing IDs

`DarkFlippers/Multi_Fuzzer` (MIT, Flipper app) iterates through ID ranges for a given format. Practical for:
- Unknown but known-format FC (enumerate cards 0..65535).
- Brute-forcing access to test equipment / parking barriers when legally authorized.

Rate: ~200-400 ms per emission (Flipper has to modulate field each try). 2^16 IDs ~2 hours; 2^20 IDs ~2 days. Infeasible for unrestricted 2^32+.

---

## Why 125 kHz is going away

125 kHz LF is unambiguously broken: no crypto, trivially cloneable, predictable IDs. Replacements:
- **iClass SE / SEOS** at 13.56 MHz (see `hid-prox.md`).
- **MIFARE DESFire** at 13.56 MHz (see `mifare-ultralight-desfire.md`).
- **Bluetooth Mobile Access** (HID Mobile, Openpath, Kisi, Verkada).

Organizations that still run EM4100 or HID Prox in 2026 are typically small businesses, aging hardware, or haven't gotten around to migration. The lift is non-trivial (new reader heads + credential re-issuance for every employee), which is why LF persists.
