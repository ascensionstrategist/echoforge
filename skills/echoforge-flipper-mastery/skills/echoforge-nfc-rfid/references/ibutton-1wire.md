# iButton and 1-Wire

iButton is a Maxim/Dallas product line — a stainless-steel "canister" about the size of a coat button that holds an IC and talks 1-Wire protocol when it touches a probe. Common in access control (older systems), vending machines, industrial-equipment keys.

Physical: the button has two contacts (lid + base). The probe has two pogo pins. Touch = contact = conversation.

Protocol: **Dallas 1-Wire**. Half-duplex, bit-banged over a single data line (plus ground). Signaling is time-slot based: a reset pulse puts the button into listening mode, then master issues commands, button responds. Baud is slow (~16 kbps "standard speed", ~77 kbps "overdrive").

---

## Flipper's 1-Wire wiring

The iButton app uses **GPIO pin 1W / PC4** (labeled "iButton" on top of the Flipper). It's exposed at the top of the unit. Touching an iButton to the outside of Flipper's metal ring triggers read.

Voltage: 3.3V pull-up. The data line is actively pulled low by either master or slave; otherwise held at VDD by the pull-up.

---

## Product families (by 8-bit family code)

The first byte of an iButton's 64-bit ROM is the **family code**, identifying the chip type.

| Family byte | Chip | Type | Security |
|-------------|------|------|----------|
| **0x01** | **DS1990A / DS1990R** | Serial Number (Silicon) | None — pure fixed ROM |
| 0x02 | DS1991 | Multikey | Password, weak |
| 0x04 | DS1994 | Real-time clock + 4 KiB NV-RAM | None |
| 0x08 | DS1992 | 1 KiB NV-RAM | None |
| 0x09 | DS1982 | 1 KiB EPROM | None |
| 0x0C | DS1996 | 64 KiB NV-RAM | None |
| 0x14 | DS1971 | 256-bit EEPROM | None |
| 0x21 | DS1963S | Monetary iButton (SHA-1) | Strong (SHA-1 secrets) |
| 0x23 | **DS1973** | 4 KiB EEPROM | None |
| 0x33 | **DS1961S / DS2432** | SHA-1 authenticated 1 KiB | Strong (SHA-1 challenge-response) |
| 0x37 | DS1977 | 32 KiB password-protected EEPROM | Password only |

The overwhelming majority of "iButton access tokens" in the wild are **DS1990A (0x01)**: fixed 64-bit ROM, no security. These are clonable in seconds.

---

## The 64-bit ROM

```
[Family 1B] [Serial 6B] [CRC 1B]
     0x01     random       CRC-8 (polynomial 0x8C)
```

- Family code: 1 byte, identifies chip type.
- Serial: 6 bytes = 48 bits. Factory-programmed, unique per chip.
- CRC-8: Dallas/Maxim-specific polynomial `X^8 + X^5 + X^4 + 1`. Validates the 56-bit payload.

An example DS1990A ROM: `01 DE AD BE EF 00 01 CF`. Reader checks: family OK (0x01), CRC matches payload → valid.

---

## Cloning DS1990A

Three options:
1. **RW1990 / RW1990.1 / RW1990.2** — Chinese clone iButtons that **accept ROM overwrite** via a non-standard command. Flipper's iButton app has explicit "Write RW1990" mode.
2. **TM2004 / TM01** — similar generic writable clones.
3. **Emulate with Flipper directly** — no physical clone needed. Flipper's iButton app "Emulate" mode presents the fixed ID when probed.

When writing to RW1990, you need to know the chip's quirk: some variants require the magic byte `0x19` before the 64-bit ROM; others accept the 64 bits directly. Flipper figures this out by trying both.

---

## DS1961S / DS2432 (authenticated)

This is the hard one. DS1961S uses SHA-1 challenge-response:
- Master presents a challenge (random 64 bits).
- Slave combines challenge + its secret key + its ROM ID → SHA-1 → returns MAC.
- Reader verifies MAC against its copy of the key.

**Cloning DS1961S.** You need:
- The target's ROM ID (trivially read).
- The secret key (stored only in the button and the reader's back-end).

Without the key, you cannot clone. DS1961S keys are sometimes leaked via reader firmware extraction (similar to Loclass for iClass) but no generic break.

Commercial access systems using DS1961S: hospital/lab equipment, some industrial vending.

---

## `.ibtn` file

```
Filetype: Flipper iButton key
Version: 1
Key type: DS1990
Data: 01 DE AD BE EF 00 01 CF
```

For DS1961S:
```
Filetype: Flipper iButton key
Version: 1
Key type: DS1961S
Data: 33 AB CD EF 12 34 56 CC
Memory: ...256 bytes of hex...
```

---

## Read/clone decision tree

```
Read the iButton. First byte of ROM?
├── 0x01 → DS1990A. Clone to RW1990 (blank ~$1). Emulate directly on Flipper.
├── 0x04/0x08/0x0C/0x14/0x23 → Memory iButton, no auth. Clone ROM; may also need to clone memory (DS1973 etc.).
├── 0x33 → DS1961S. SHA-1 auth. Cannot clone without key.
├── 0x21 → DS1963S monetary. SHA-1. Cannot clone without key.
└── Other → rare, consult datasheet.
```

---

## Common confusion

- **"iButton" vs "1-Wire"** — iButton is a form factor (the stainless canister). 1-Wire is the protocol. Many non-iButton devices use 1-Wire (DS18B20 temperature sensors, DS2431 EEPROMs in PCB form). Flipper's iButton app works with any 1-Wire slave that talks the standard ROM commands.
- **iButton vs RFID LF** — iButton is **contact** (you touch it); RFID LF is **RF** (you hold it near). If the user has a "key" they can wave past a reader, it's almost certainly 125 kHz RFID, not iButton, even if visually similar.
- **DS1990 vs DS1990R** — `R` adds an additional ground contact for industrial reliability; electrically identical.
