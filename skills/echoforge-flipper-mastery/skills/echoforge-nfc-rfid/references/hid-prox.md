# HID Prox and iClass — 125 kHz LF and 13.56 HF Access Control

HID Global (formerly HID Corp) dominates North American commercial access control. Two main product lines operate on different frequencies and use completely different protocols — it's critical to know which one you're looking at.

---

## HID Prox (125 kHz LF)

The legacy HID family: FSK-modulated 125 kHz, FIXED broadcast ID, no authentication. Any reader that supports the format accepts the card. Clonable to T5577 / EM4305 blanks in seconds.

### Format: H10301 (26-bit standard)

The overwhelming default. 26 bits total:

```
P  F F F F F F F F  C C C C C C C C C C C C C C C C  P
│  ├─────────────┤  ├───────────────────────────────┤  │
│   Facility code       Card number (0-65535)          │
│   (0-255)                                             │
│                                                       │
└ Even parity over bits 1-13                          Odd parity over bits 13-25
```

- **Facility code** — 8-bit vendor/site code. Programmed into the reader's "accepted facility" list.
- **Card number** — 16-bit card ID.
- **Parity** — even over top half, odd over bottom half. Simple integrity.

Sample capture in a Flipper `.rfid`:

```
Filetype: Flipper RFID key
Version: 1
Key type: H10301
Data: 00 AB CD
```

Decode: Facility `0x00`, Card `0xABCD` (43981 decimal). If the user's lanyard says "Card #43981 FC 0", that's the match.

### Format: 35-bit Corporate 1000

HID Corp's 35-bit extension for larger enterprises:

```
P  C C C C C C C C C C C C  N N N N N N N N N N N N N N N N N N N N  P
│  ├─────────────────────┤  ├─────────────────────────────────────────┤  │
│   Company code (12-bit)     Card # (20-bit, 0-1,048,575)               │
```

Company code is HID-assigned per customer (big companies get their own). Cloning-wise identical to H10301.

### Format: Other (35A, 37H, 48-bit, custom)

There are ~30 HID LF formats. The ones you'll see:

- **35A** (formerly Casi-Rusco) — 35-bit variant.
- **37-bit H10304** — 16-bit FC + 19-bit card #.
- **48-bit Identity** — reserved for higher-security LF, rare.

Flipper's RFID LF app auto-detects the most common; unrecognized formats fall back to the raw 64-bit EM-style capture.

### Brute-forcing HID Prox

For a known FC, card numbers are just 16-bit (H10301) or 20-bit (Corp 1000). A fuzzer emits sequential IDs:

- H10301: `2^16 = 65,536` combos. At ~200 ms/write-and-test, ~3.5 hours.
- Corp 1000: `2^20 = 1,048,576` combos. Infeasible in person, but ESPKey-style Wiegand implants can sweep from afar.

`DarkFlippers/Multi_Fuzzer` (MIT) does this on Flipper natively.

### ESPKey / Wiegand MITM

ESPKey is an implant that sits between a reader and the controller on the Wiegand bus. It logs every swipe (8000-credential buffer) and can replay arbitrary Wiegand frames — perfectly bypassing the card-vs-reader crypto because the attack is **downstream** of the reader. NetSPI's 2024 "Tastic Thief" combines ESPKey with a long-range LF reader that can sweep a lanyard from 3+ feet, capturing the FC+card# and then replaying into an ESPKey-implanted reader to unlock the door.

---

## HID iClass (13.56 MHz HF)

HID's successor to Prox, using 13.56 MHz ISO-15693 (not ISO-14443 like MIFARE). Security-via-obscurity until 2012 when Garcia et al. broke it.

### Generations

- **iClass Legacy** (early 2000s) — proprietary keyed authentication, 6 crypto weaknesses documented in Garcia/Verdult USENIX WOOT 2011 (https://www.usenix.org/legacy/event/woot11/tech/final_files/Garcia.pdf). Loclass attack (included in Proxmark3 `client/src/loclass/`) recovers the master key from either a reader or a collection of card reads.
- **iClass SE** (~2010) — uses a secure element for key storage. Mitigates Loclass. However, most SE readers are configured to **also accept Legacy cards** for backward compatibility → **Legacy downgrade attack** (DEF CON 32, Javadi/Levy/Draffen 2024): clone a Legacy card, present it to an SE reader, get in.
- **iClass SEOS** (~2013) — fully secure element, no Legacy compatibility by default. Practically secure unless misconfigured.
- **iClass Seos Mobile / HID Mobile Access** — phone-based via BLE or NFC; tokens are managed in HID's cloud.

### Flipper and iClass

Flipper's stock firmware does NOT support iClass natively (it's ISO-15693, not 14443). Momentum FW includes an iClass plugin that reads/emulates Legacy cards via the ST25R3916. SE / SEOS cards authenticate but Flipper can't clone them without a Proxmark3.

### `.picopass` file

Momentum saves iClass dumps as `.picopass`. Contains:
```
Filetype: Flipper Picopass device
Version: 2
Credential: 40 BF 12 ED 00 00 00 00
CSN: AB CD EF 12 34 56 78 90
Configuration: 12 FF FF FF 7F 1F FF 3C
E-purse: FF FF FF FF FF FF FF FF
...
```

The `Credential` field is the 8-byte HID Legacy wiegand-equivalent output. Clone into a Picopass "magic" card, present to an SE-misconfigured reader, and it accepts.

---

## Decision tree — LF vs HF access card

Hold the card up to a Flipper running "Read NFC" and "Read 125 kHz RFID" simultaneously (well, one at a time, but with minimal handling):

```
LF reads UID-equivalent within 1-2 sec → HID Prox / EM4100 / Indala family.
HF reads something → iClass (if SAK is ISO-15693 weird) or NFC (MIFARE family).
Both? → multi-technology card (e.g., HID iClass SE + Prox hybrid for migration).
Neither? → check frequency requirements; may be Hitag, Legic, or proprietary.
```

For HID specifically, the card's **printed text** usually tells you:
- "ProxCard II" / "DuoProx" / "ISOProx" → 125 kHz Prox.
- "iCLASS" / "iCLASS SE" / "iCLASS Seos" → 13.56 MHz iClass.
- "multiCLASS" → dual-frequency, both on.

---

## Summary: cloneability by HID product

| Product | Freq | Flipper clone? | Notes |
|---------|------|----------------|-------|
| HID ProxCard II (H10301) | 125 kHz | YES | Clone to T5577. Done in 30s. |
| HID Corp 1000 35-bit | 125 kHz | YES | Same, different parser. |
| HID iClass Legacy | 13.56 MHz | YES with Momentum FW iClass plugin | Emit via ST25R3916. |
| HID iClass SE | 13.56 MHz | NO directly; YES via Legacy downgrade if reader accepts Legacy | Most SE readers in the wild still accept Legacy. |
| HID iClass SEOS | 13.56 MHz | NO (no practical attack) | Use Loclass on a misconfig'd reader to get its master key if you can. |
| HID Mobile Access | BLE | N/A | Flipper doesn't emulate HID mobile tokens. |
