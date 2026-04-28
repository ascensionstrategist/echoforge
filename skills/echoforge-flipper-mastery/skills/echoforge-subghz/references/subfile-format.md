# Flipper `.sub` File Format

The `.sub` is a plaintext UTF-8 file with LF or CRLF line endings. It is key-value, one pair per line, `Key: Value`. All Sub-GHz state needed to retransmit the signal is in this file — it is fully self-describing.

Sources: `flipperdevices/flipperzero-firmware/lib/subghz/subghz_file_encoder_worker.c`, `subghz_protocol_registry.c`, and the per-protocol `lib/subghz/protocols/<proto>.c`.

---

## 1. Common header (every `.sub`)

```
Filetype: Flipper SubGhz Key File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: Princeton
```

- `Filetype` — always the literal string `Flipper SubGhz Key File` (or for RAW captures, `Flipper SubGhz RAW File`).
- `Version` — currently `1`.
- `Frequency` — integer hertz. `433920000` = 433.92 MHz.
- `Preset` — one of the `FuriHalSubGhzPreset*` enum names (see list below).
- `Protocol` — one of the registered protocol names, or `RAW` if not decoded.

---

## 2. Preset allowlist

These are the four Flipper-shipped presets; custom firmwares (Momentum) add more. The echoforge `payload_subghz_retune` tool accepts only this allowlist:

| Preset string | Modulation | Notes |
|---------------|------------|-------|
| `FuriHalSubGhzPresetOok270Async` | OOK, 270 kHz BW | Narrow OOK. |
| `FuriHalSubGhzPresetOok650Async` | OOK, 650 kHz BW | Wide OOK. **Most common default.** |
| `FuriHalSubGhzPreset2FSKDev238Async` | 2-FSK, 2.38 kHz dev | Narrow FSK. |
| `FuriHalSubGhzPreset2FSKDev476Async` | 2-FSK, 4.76 kHz dev | Wider FSK. |
| `FuriHalSubGhzPresetMSK99_97KbAsync` | MSK, ~100 kbps | Rare; some TPMS sensors. |
| `FuriHalSubGhzPresetGFSK9_99KbAsync` | GFSK, ~10 kbps | Some weather stations. |
| `FuriHalSubGhzPresetCustom` | — | Must be followed by a `Custom_preset_module:` + `Custom_preset_data:` block that dumps raw CC1101 registers. Advanced; Momentum uses this for BinRAW captures. |

---

## 3. Protocol-specific payloads

### 3a. Princeton / Holtek / CAME / Nice Flo (fixed-code)

```
Filetype: Flipper SubGhz Key File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: Princeton
Bit: 24
Key: 00 00 00 00 00 4C 92 24
TE: 406
Repeat: 5
```

- `Bit` — decoded bit count. `12` or `24` for Princeton.
- `Key` — **big-endian** hex, space-separated bytes. Low-order `Bit` bits are the data; upper bits are padding zeros. Here `0x004C9224` is the actual key.
- `TE` — symbol duration in microseconds. 400 ± 50 µs typical.
- `Repeat` — transmitter repeats the frame this many times (legit remotes do 3-10).

### 3b. KeeLoq (rolling)

```
Filetype: Flipper SubGhz Key File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: KeeLoq
Bit: 64
Key: 0A 1B 2C 3D 4E 5F 6F 70
Seed: 00 00 00 00
Manufacture: Unknown
```

- `Key` — full 64-bit captured frame. For KeeLoq this is 32 encrypted + 28 serial + 4 button.
- `Seed` — initialization value used if the manufacturer key is known (for cloning). All-zero if unknown.
- `Manufacture` — string tag from `keeloq_mfcodes`. `Unknown` means Flipper couldn't match against its bundled manufacturer-key list. `Faac_SLH`, `Nice_Smilo`, etc. when matched.

### 3c. Security+ 2.0

```
Protocol: Security+ 2.0
Bit: 80
Key: 01 02 03 04 05 06 07 08 09 0A
Button: 2
Serial: 5A 6B 7C 8D 
```

### 3d. Somfy Telis

```
Protocol: Somfy Telis
Bit: 56
Key: 68 70 A1 B2 C3 D4 E5
```

### 3e. RAW (unrecognized or sampled capture)

```
Filetype: Flipper SubGhz RAW File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: RAW
RAW_Data: 410 -408 412 -810 406 -404 820 -406 402 -402 410 -400 ...
```

- `Filetype` is `Flipper SubGhz RAW File`, not the normal key file.
- `RAW_Data` — space-separated **signed** integers, microseconds. Positive = high (carrier on), negative = low (carrier off). Alternating. A typical capture has 50-300 samples; very long captures (weather beacons, some hopping remotes) run into the thousands.
- The file can have multiple `RAW_Data:` lines if the capture was long enough to wrap (each max ~512 samples).

**Why RAW matters.** Any signal Flipper's decoder doesn't recognize becomes RAW. Retuning RAW files to correct the Preset sometimes unlocks decode.

---

## 4. Full example — a CAME 12-bit garage remote

```
Filetype: Flipper SubGhz Key File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: CAME
Bit: 12
Key: 00 00 00 00 00 00 04 92
TE: 350
Repeat: 10
```

Decoded: `0x0492` = binary `0000 0100 1001 0010`. In CAME 12-bit trinary, the nybbles map to DIP-switch positions. If the gate's receiver has DIP switches `9` and `7` ON, that's your match.

---

## 5. Sidecar metadata (`<name>.echoforge.json`)

Echoforge's Payload Forge adds an optional sibling file:

```json
{
  "schema": "echoforge.payload.v1",
  "kind": "subghz",
  "name": "home-garage",
  "description": "My own garage door, CAME 12-bit fixed code",
  "author": "operator@example.com",
  "tags": ["personal", "garage"],
  "created_utc": "2026-04-22T18:00:00Z",
  "modified_utc": "2026-04-22T18:00:00Z",
  "source": {
    "tool": "payload_subghz_import_capture",
    "content_hash": "sha256:…"
  },
  "policy_tag": null
}
```

The sidecar is **advisory** — it does not override the `.sub`. If the sidecar claims `kind: subghz` but the `.sub` header says `Filetype: Flipper SubGhz RAW File`, Flipper will still transmit RAW. Payload Forge re-hashes the `.sub` on every write and flags drift.

---

## 6. Common parse errors

| Symptom | Cause |
|---------|-------|
| "Invalid file" on Flipper | `Filetype` or `Version` header missing |
| Decode is "RAW" but has bits | Preset mismatch; try retuning to a different preset |
| TX immediately ends with no signal | `Frequency` outside radio band, or outside region allowlist on stock FW |
| Decoded `Key` is all zeros | Capture picked up noise, not a real frame. Recapture closer |
| `RAW_Data` values all small (<100 µs) | Capture oversampled; low-quality signal. Recapture with antenna closer or more-gain external |
