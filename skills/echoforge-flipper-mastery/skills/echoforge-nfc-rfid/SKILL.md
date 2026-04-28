---
name: echoforge-nfc-rfid
description: Work with Flipper Zero NFC (13.56 MHz), 125 kHz RFID LF, and iButton (1-Wire) tags — ISO-14443 A/B framing, MIFARE Classic/Ultralight/DESFire, HID Prox and iClass, EM4100/EM4305, Dallas DS1990A. Use when the user shares a .nfc/.rfid/.ibtn file, asks why a MIFARE key crack takes minutes, or needs to know whether a specific card type is cloneable.
---

# Flipper Zero NFC, RFID, and iButton

You are the expert reference for Flipper's three close-proximity-ID subsystems: **NFC** at 13.56 MHz (ISO-14443 A/B/Felica), **125 kHz RFID LF** (EM4100/HID Prox/Indala/AWID), and **iButton / 1-Wire** (Dallas DS1990/DS1961/DS1971). Each has a separate app on the Flipper, a separate chip path (ST25R3916 for HF, RFID LF demodulator for LF, GPIO pin for 1-Wire), and a separate file format.

## When to activate

Load this skill when the user:
- Shares `.nfc`, `.rfid`, `.ibtn`, or `.picopass` file contents.
- Asks about a card/tag by type: MIFARE Classic, Ultralight, DESFire, NTAG213/215/216, HID iClass, EM4100, EM4305, T5577, Indala, AWID, Hitag, DS1990, iButton.
- Asks about a known attack: Darkside, Nested, Hardnested, mfcuk, mfoc, FM11RF08S backdoor (Teuwen eprint/2024/1275), Loclass (iClass).
- Asks "can I clone this badge?" / "why doesn't the clone work?"
- Uses card dumps, UIDs, sector keys, or access control in the question.
- Mentions 13.56 MHz or 125 kHz as a frequency.

## Core knowledge

**Three different radios, three different worlds.** NFC at 13.56 MHz is a short-range (≤ 10 cm) bidirectional RF link specified by ISO-14443 (Types A and B), ISO-15693 (vicinity cards like iClass), and JIS X 6319-4 (Felica). RFID LF at 125 kHz is a *unidirectional* asynchronous-modulation link — the reader powers the tag with a continuous 125 kHz carrier, the tag modulates its presence by shorting its coil (load modulation), reader demodulates the envelope. Tag can't really challenge the reader; almost all LF tags are fixed-ID broadcast. iButton at 1-Wire is not RF at all — it's a galvanic contact protocol where the iButton's stainless-steel can touches a probe and the protocol runs electrically.

**The replay-ability matrix.**

| Card / tag | Frequency | Auth? | Clonable with Flipper alone? | Notes |
|------------|-----------|-------|------------------------------|-------|
| **EM4100** | 125 kHz | No | YES | 64-bit fixed ID; defaults of cheap access control. T5577/EM4305 blanks accept the write. |
| **HID Prox H10301** | 125 kHz | No | YES (read + clone to T5577) | 26-bit fixed format, 8-bit facility + 16-bit card# + 2 parity. |
| **HID Prox Corp 1000** | 125 kHz | No | YES | 35-bit, 12-bit company + 20-bit card# + 2 parity. |
| **Indala** | 125 kHz | No | YES | Variable-length FSK, Flipper Momentum reads/writes. |
| **Indala HID 40134** | 125 kHz | No | YES | 26-bit, legacy. |
| **AWID** | 125 kHz | No | YES | 26-bit FSK variant. |
| **Hitag2** | 125 kHz | Yes | NO (direct) | Encrypted rolling, requires active crypto; Flipper captures, offline crack possible. See Verdult/Garcia USENIX 2012. |
| **MIFARE Classic 1K/4K** | 13.56 MHz | Yes (Crypto1) | YES if keys known | Classic is broken (Crypto1 weak). Default-key cards dump in 30s; hardened cards need `mfoc-hardnested`. See `references/mifare-classic.md`. |
| **MIFARE Classic on FM11RF08S (Fudan)** | 13.56 MHz | Yes | YES in minutes | Shanghai-Fudan backdoor (Teuwen eprint/2024/1275): single-bit change in the cmd field auths with a global backdoor key, leaks nonces. |
| **MIFARE Ultralight / NTAG21x** | 13.56 MHz | Optional password | YES for unprotected, sometimes for protected | Low-security NFC: NTAG213/215/216 common; password is 32-bit (brute-forceable with enough time, but rate-limited). |
| **MIFARE DESFire EV1/EV2/EV3** | 13.56 MHz | AES/3DES | NO (securely deployed) | Modern replacement for Classic; no practical crypto break. Cloning only if keys leak. |
| **HID iClass Legacy** | 13.56 MHz | Proprietary | YES with Proxmark or legacy-downgrade | Loclass attack (Garcia et al.) recovers master key. Flipper Momentum has iClass plugin that emulates legacy. |
| **HID iClass SE** | 13.56 MHz | Secure element | NO (directly); YES via legacy-downgrade | SE uses a secure element for key storage but many readers still accept legacy iClass — clone a legacy card to defeat SE. |
| **iClass SEOS** | 13.56 MHz | Secure element | NO | Modern iClass, hardened against downgrade. |
| **DS1990A iButton** | 1-Wire | No | YES | 64-bit fixed ROM; Flipper reads and emulates via GPIO pin. |
| **DS1961S / DS1971** | 1-Wire | SHA-1/RNG | NO directly | Authenticated iButton. |
| **Amiibo NTAG215** | 13.56 MHz | 32-bit pwd | YES (dumps are online) | Nintendo character data; Flipper emulates via .nfc file. |

**How NFC communication works on Flipper.** The ST25R3916 chip handles low-level ISO-14443 framing (anti-collision, SAK resolution, APDU transport). Flipper's `nfc/` app sits on top, providing "Read/Emulate/Detect Reader". Reading a card produces a `.nfc` file containing UID + SAK + ATQA + per-sector or per-block data + keys (if recovered). Emulating replays the file. Detect Reader captures reader nonces for offline crack (mfkey32, hardnested).

**The two big attack families on HF (13.56 MHz).**
1. **Crypto1 key recovery** (MIFARE Classic): Darkside (2008) → Nested (2009) → Hardnested (2015) → FM11RF08S backdoor (2024). See `references/mifare-classic.md` for the progression and which applies to which card.
2. **APDU relay** (DESFire, transit): capture APDUs on one side, replay on another. `leommxj/nfc_relay` on Flipper proves this works between two Flippers over BLE/WiFi.

**The canonical attack on LF (125 kHz).** Brute-force the ID. EM4100 is 64 bits but only the middle 40 are the ID — a targeted brute-force against a known facility code is ~minutes. `DarkFlippers/Multi_Fuzzer` generates sequential-ID sweep files.

## Deep references

- **ISO-14443 A/B frame structure** (anti-collision, UID size 4/7/10 bytes, SAK, ATQA, tag-select FSM) → `references/iso-14443.md`
- **MIFARE Classic** (Crypto1, sector structure, keys A/B, Darkside/Nested/Hardnested attacks, FM11RF08S backdoor) → `references/mifare-classic.md`
- **MIFARE Ultralight / NTAG21x / DESFire** (page layouts, OTP, counters, 3DES/AES auth, CMAC) → `references/mifare-ultralight-desfire.md`
- **HID Prox formats** (H10301 26-bit, Corporate 1000 35-bit, iClass Legacy/SE cryptographic attack surface) → `references/hid-prox.md`
- **125 kHz RFID LF** (EM4100, EM4305, Indala, AWID, T5577 blank-tag programming) → `references/low-freq-125khz.md`
- **iButton / 1-Wire** (Dallas DS1990A/DS1961S/DS1971 ROM codes, family codes, Flipper GPIO wiring) → `references/ibutton-1wire.md`

## Don't confuse with

- **Sub-GHz (300-928 MHz)** — totally different band and protocol stack. RKE/garage remotes are Sub-GHz, not NFC.
- **Wi-Fi (2.4/5 GHz)** — Flipper uses ESP32 dev-board companion, not the ST25R3916.
- **Bluetooth / BLE (2.4 GHz)** — Flipper has its own NRF chip, not the NFC subsystem.
- **iClass SE / SEOS / Mobile Access** — the HID family has ~5 generations. Each generation is a different attack surface; don't assume a Legacy attack applies to SE or SEOS.
- **MIFARE Plus** — a transitional product between Classic and DESFire, with "SL1/SL2/SL3" security levels. Often sold as Classic-compatible but running in SL3 (AES) mode — which makes it DESFire-grade secure. Check the actual security level in use.
- **NTAG versus MIFARE Ultralight** — NTAG is NXP's successor to Ultralight, same physical layer but more memory and stronger optional password. Many "MIFARE Ultralight" shorthand references actually mean NTAG21x.
- **Felica** (JIS X 6319-4) — common in Japan, uses the same 13.56 MHz carrier but incompatible framing from ISO-14443. Flipper can read Felica IDm/PMm but cannot fully emulate.
- **NFC Forum tags Type 1-5** — a logical abstraction (NDEF messages) layered on top of the physical tag. A Type 2 tag is usually an NTAG21x; Type 4 is usually DESFire.
