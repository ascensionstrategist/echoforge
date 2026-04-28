# MIFARE Ultralight, NTAG21x, and DESFire EV1/EV2/EV3

Three NXP product families that look similar on the anti-collision layer (13.56 MHz ISO-14443A) but have wildly different security stories.

---

## MIFARE Ultralight (classic) and Ultralight-C

### Ultralight (MF0ICU1, 2005-era)

- 64 bytes total: 4 × 4-byte pages × 4 sectors, or equivalently 16 pages of 4 bytes.
- Pages 0-2: UID + BCC + serial prefix. Read-only at manufacture.
- Pages 3 OTP (one-time programmable).
- Pages 4-15: user data.
- **No authentication.** Anyone can read everything.

Used in disposable transit tickets, event wristbands. Flipper clones Ultralight in seconds.

### Ultralight-C (MF0ICU2, 2008-era)

- Same page layout but adds 3DES-based password protection on a configurable range of pages.
- 16-byte 3DES key, 3-round mutual auth.
- Brute-forcing 3DES is infeasible; unless you have the key or can sniff an auth, Ultralight-C is secure.

Used in a few transit systems (Seattle ORCA, historically). Not common.

---

## NTAG21x (NTAG213 / 215 / 216)

Successor to Ultralight for consumer NFC. Same physical layer. Bigger memory + optional password.

| Variant | Total memory | User memory | Pages |
|---------|--------------|-------------|-------|
| NTAG213 | 180 B | 144 B | 45 |
| NTAG215 | 540 B | 504 B | 135 |
| NTAG216 | 924 B | 888 B | 231 |

**Password protection (PACK + PWD).**
- PWD: 32-bit password (pages `E5` for NTAG213, `83` for 215, `E3` for 216).
- PACK: 16-bit password-ACK returned on successful auth.
- AUTH0: byte indicating first password-protected page.
- AUTHLIM: 3-bit counter, card locks after N failed auths (default 0 = no limit).

**Attack surface.**
- If AUTHLIM = 0 (common default), 32-bit password is brute-forceable at ~5 guesses/sec over NFC → worst case ~27 years, realistic targeted attacks use known-password dictionaries (Amiibo passwords are all public, for instance).
- If the card has never been password-protected, you can read everything without auth.
- **Amiibo (NTAG215)** — Nintendo ships them with a known PWD derivation from UID. Every Amiibo password can be derived; https://github.com/Gioman101/FlipperAmiibo has per-character dumps.

**Cloning NTAG21x.**
- Real NTAG UIDs are factory-locked. You cannot clone to a genuine NTAG.
- "Magic NTAG" clones exist (UFUID / NTAG21x-emulating Gen4 cards) — these allow UID write.
- For Amiibo specifically, blank NTAG215s with locked UIDs work if the reader doesn't check the NXP manufacturer signature (Nintendo Switch post-firmware-update started checking; older consoles don't).

---

## DESFire EV1 / EV2 / EV3

Modern NXP NFC smartcard. Completely different security story from Classic/Ultralight.

### Structure

- Hierarchical: **PICC (the chip) → Applications (up to 28) → Files (up to 32 per app)**.
- Each application has its own set of up to 14 keys.
- Each file has a read/write access policy referencing keys.

### Authentication

- **EV1**: 3DES (2K3DES or 3K3DES) or AES-128 mutual auth.
- **EV2**: 3DES + AES-128, adds **Secure Messaging** (CMAC + optional encryption on every APDU).
- **EV3**: AES + AES-192 option, adds **Transaction MAC** for proving transaction integrity.

The auth protocol is a random-nonce 3-pass exchange:
1. Reader sends AUTH command referencing key slot.
2. Card returns encrypted random nonce rndB.
3. Reader decrypts rndB, generates rndA, sends Enc(rndA || rot_left(rndB, 1)).
4. Card verifies, sends Enc(rot_left(rndA, 1)).

After auth, both sides share a session key for CMAC/encryption.

### Attack surface

- **None directly against EV1/EV2/EV3 crypto.** The algorithms are standard and correctly implemented. No practical break published.
- **Bias in DESFire EV1 TRNG** (ResearchGate 2016) — weakens the challenge nonce slightly, not enough for a break.
- **Implementation bugs in readers** — most DESFire "hacks" you see online are reader-side: reader stores keys in cleartext firmware (e.g., CVE-2024-29941 ICT Protege), reader key-diversification is weak, reader accepts downgraded cards, etc. Clone the reader, not the card.
- **APDU relay** — capture a legitimate session's APDUs (reader ↔ card) on one link, replay to another reader on another link in real-time. `leommxj/nfc_relay` on Flipper via BLE/WiFi between two devices. Works against transit readers that don't timestamp-bind the session.
- **Side-channel DPA on the fob itself** — same threat model as KeeLoq DPA: requires physical access to a valid card + oscilloscope + expertise. Academic, not field-deployable.

### `.nfc` fields for DESFire

```
Filetype: Flipper NFC device
Version: 4
Device type: Mifare DESFire
UID: 04 A1 B2 C3 D4 E5 F6
ATQA: 03 44
SAK: 20
ATS: 06 75 77 81 02 80
PICC Version: 01 01 01 00 1A 05
PICC Free memory: 6912
PICC Applications count: 2
Application IDs: 112233 A1B2C3
Application 112233 Files count: 3
Application 112233 File 01 type: Standard
Application 112233 File 01 data: DEAD BEEF...
```

Flipper's DESFire read pulls whatever the card will give without auth — generally just the PICC metadata, app IDs, and any files with free-read access. Encrypted files dump as "requires auth" with no contents.

---

## MIFARE Plus

Transitional product: drop-in physical replacement for MIFARE Classic 1K/4K with three security levels selectable in deployment:

- **SL0** — uninitialized; factory state.
- **SL1** — **Classic-compatible mode**, same Crypto1 weaknesses. Used for transit migrations.
- **SL2** — Classic commands with AES session keys for crypto only (rare, intermediate step).
- **SL3** — full AES-128, DESFire-like security.

**Big trap:** a "MIFARE Plus" badge may be running in SL1 and be as broken as Classic, or in SL3 and be effectively DESFire. You cannot tell from the outside without probing. Try Classic attacks first; if they fail but the card auths cleanly, it's SL3.

---

## Decision tree — "what am I looking at?"

```
SAK = 0x00?
├── Check ATQA and version bytes:
│   ├── ATQA 0x44, has CC/OTP pages → Ultralight family
│   │   ├── Responds to 0x1B AUTH → Ultralight-C (3DES)
│   │   ├── Responds to 0x1B PWD_AUTH → NTAG21x (32-bit pwd)
│   │   └── Otherwise → classic Ultralight (no auth)
│   └── Higher → Edge case, check datasheet
SAK = 0x08, 0x18 → MIFARE Classic (see mifare-classic.md) or MIFARE Plus SL1
SAK = 0x10, 0x11 → MIFARE Plus SL2
SAK = 0x20 → ISO-14443-4 capable
│   ATS first byte:
│   ├── 0x06-0x0A → DESFire (EV1/EV2/EV3 distinguished by VERSION command)
│   ├── 0x78 → JavaCard-based
│   └── Other → proprietary smartcard
```
