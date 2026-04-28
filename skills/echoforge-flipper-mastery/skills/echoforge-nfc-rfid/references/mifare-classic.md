# MIFARE Classic — Sectors, Keys, Crypto1, and the Attack Progression

MIFARE Classic is the most-studied broken-cryptography deployment in commercial electronics. Still everywhere in 2026 because retrofitting readers is expensive. Understanding the progression of attacks is key to diagnosing "can I clone this?" questions quickly.

Primary sources:
- Garcia/de Koning Gans/Verdult et al., *Dismantling MIFARE Classic* (ESORICS 2008) and follow-ups.
- Teuwen / Quarkslab, *A backdoor in the MIFARE Classic FM11RF08S*, eprint/2024/1275 (https://eprint.iacr.org/2024/1275.pdf).
- Proxmark3 mainline source — `client/src/mifare/*.c` (gold-standard implementation).

---

## 1. Physical layout

### 1K cards (most common)

- 16 sectors × 4 blocks × 16 bytes = **1024 bytes total**.
- Sector 0 block 0 is the **manufacturer block**: UID (4 bytes) + BCC + SAK + ATQA + 8 bytes of manufacturer data. Read-only on genuine tags; writable on "magic" clones.
- Sector N block 3 (last block of sector) is the **sector trailer**: 6-byte Key A + 4-byte Access Bits (+ 1 byte user data) + 6-byte Key B.

### 4K cards

- First 32 sectors: 4 blocks each (same as 1K). 
- Sectors 32-39: 16 blocks each = 256 bytes per sector.
- Total 4096 bytes.

---

## 2. Authentication and Crypto1

Each sector has its own Key A and Key B (6 bytes = 48 bits each). Access bits in the trailer define whether Key A or Key B is required for read/write per block. Common deployments use Key A = read, Key B = write.

**Crypto1** is the NXP-proprietary stream cipher from 1994:
- 48-bit LFSR.
- 20 non-linear filter bits feed a quadratic output function.
- Initialized from card UID + sector key + reader nonce + card nonce.

Broken in 2008 (ESORICS) via algebraic and brute-force attacks. Multiple practical attacks followed, each faster than the last.

---

## 3. Attack progression

### 3a. Default-key dump (2008-2026, still a winner)

Try these keys against every sector:
```
FFFFFFFFFFFF                    # out-of-factory NXP default
A0A1A2A3A4A5                    # NDEF public sector key
D3F7D3F7D3F7                    # MAD sector
000000000000                    # sometimes sector 0
A1A2A3A4A5A6, B0B1B2B3B4B5      # transport / access-control vendor defaults
```

The `nfc_dict` on Flipper ships ~600 known keys. Many deployments never rotated past defaults. ~30% of small-business access-control MIFARE Classic cards in the wild still open with defaults as of 2024 research.

On Flipper: `NFC` app → `Read` → after UID/ATQA/SAK it auto-tries the dict. Dump time ~10-30s per sector.

### 3b. Darkside attack (Courtois 2009, eprint/2009/137)

If you have ONE sector's key and the card doesn't support "hardened nonces" (pre-2011 Classic), Nested attack (below) works. If you have ZERO keys, Darkside recovers one in ~5-40 min by exploiting the card's response to invalid commands. Implemented in `mfcuk` (https://github.com/nfc-tools/mfcuk).

### 3c. Nested attack (Garcia et al. 2009)

Once you have ONE sector's key, Nested exploits the fact that Crypto1's internal state after an authentication can be derived from the card's nonce. Requests auth to another sector reveals enough of its key to brute-force in seconds. Implemented in `mfoc` (https://github.com/nfc-tools/mfoc).

### 3d. Hardnested attack (Carlo Meijer / Roel Verdult 2015)

NXP post-2011 "hardened" MIFARE Classic cards (EV1 / 1K Plus in SL1 mode) fixed the PRNG weakness Nested exploits. Hardnested uses statistical cryptanalysis of the filter function with a precomputed rainbow table; needs 2-20k acquisition traces + 1-6 minutes compute on a modern CPU. Implemented in `mfoc-hardnested` (https://github.com/nfc-tools/mfoc-hardnested), native in Proxmark3. Flipper's NFC app doesn't run hardnested directly (CPU is too slow); it captures nonces and exports them for offline hardnested on a laptop.

### 3e. mfkey32 (reader-side attack)

If you can only sniff the reader's side of an auth (e.g., an employee tapping in a legitimate card), mfkey32 recovers the key from two authentications' challenge pairs. Flipper has `Detect Reader` mode specifically for this. https://github.com/equipter/mfkey32.

### 3f. FM11RF08S backdoor (Teuwen / Quarkslab 2024)

The bombshell of recent years. Shanghai-Fudan's FM11RF08S is a MIFARE-Classic-compatible counterfeit that has **a hardware backdoor**: flipping one specific bit in the AUTH command causes the card to authenticate using a **global backdoor key** instead of the programmed sector key, and leaks static nonces in the process.

- Paper: https://eprint.iacr.org/2024/1275.pdf
- PoC: https://gist.github.com/noproto/63f5dea3f77cae4393a4aa90fc8ef427
- Upstream tooling: Proxmark3 `hf mf fm11rf08s_recovery`

Practical impact: any FM11RF08S card can be fully dumped in 2-5 minutes without needing the legitimate keys. Shanghai-Fudan has shipped millions of these as a cheap alternative to real NXP MIFARE Classic; many "MIFARE Classic 1K" cards in low-cost access-control deployments are actually FM11RF08S. Identify via the MAGIC nonce leak pattern — Proxmark + Flipper plugins both detect it.

**How to tell if a card is FM11RF08S vs genuine NXP:**
- ATQA = `0x0004`, SAK = `0x08` — same as genuine. You can't tell from anti-collision alone.
- The `fm11rf08s_recovery` probe succeeds → it's Fudan.
- Some batches have a detectable `SIGNATURE` fingerprint via a read-signature APDU.

---

## 4. Magic cards (for cloning UID-locked content)

Genuine MIFARE Classic block 0 is factory-locked — the UID cannot be changed after manufacture. To clone a card, you need a **Magic** card:

- **Gen1a / UID / Chinese Magic** — responds to non-standard commands `40 / 43` to unlock writes. Classic way to clone. Readers that check for this vulnerability reject the card.
- **Gen2 / CUID** — block 0 writable via standard `A0` command after normal auth. Looks identical to a genuine card to most readers.
- **Gen3 / APDU** — custom APDU commands for block-0 write, preserves backdoor hiddenness.
- **Gen4 / Ultimate / UFUID** — writable block 0, configurable ATQA/SAK/ATS, can emulate cards other than MIFARE Classic (GTU). Most versatile.
- **FUID** — Gen2-style but the backdoor disappears after first write, becoming indistinguishable from a genuine card.

Flipper can write to all of these; Momentum FW has explicit dialogs for each gen.

---

## 5. `.nfc` file field layout (MIFARE Classic)

```
Filetype: Flipper NFC device
Version: 4
Device type: Mifare Classic 1k
UID: 04 A1 B2 C3
ATQA: 00 04
SAK: 08
Mifare Classic type: 1K
Data format version: 2
# Mifare Classic blocks, '??' means unknown data
Block 0: 04 A1 B2 C3 74 08 04 00 62 63 64 65 66 67 68 69
Block 1: 00 01 02 03 04 05 06 07 08 09 0A 0B 0C 0D 0E 0F
...
Block 3: FF FF FF FF FF FF FF 07 80 69 FF FF FF FF FF FF
```

- Block 3 (trailer of sector 0): `FFFFFFFFFFFF` (Key A) + `FF078069` (access bits + user byte) + `FFFFFFFFFFFF` (Key B). This is the default unlocked state.
- Blocks with `??` in their hex were unreadable — either read failed or key unknown.

---

## 6. Decision tree for "can I clone this card?"

```
Does the card read on Flipper and give UID?
├── Yes
│   Does SAK = 0x08 or 0x18 (Classic)?
│   ├── Yes
│   │   Try default-key read. Did all sectors dump?
│   │   ├── Yes → Clone to Gen2 / Gen4 magic card. Done.
│   │   └── No → Try FM11RF08S backdoor. Works?
│   │       ├── Yes → Dump, clone as above.
│   │       └── No → Try mfkey32 via reader sniff, else hardnested.
│   └── No (SAK = 0x20, DESFire/MIFARE Plus SL3)
│       STOP. No practical clone without key leak.
└── No (card doesn't respond)
    Card is maybe passive-mode-only near a different reader type, or frequency mismatch (this is 13.56 MHz). Check.
```
