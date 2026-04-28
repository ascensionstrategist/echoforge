# Sub-GHz Frequencies — Bands, Regional Allocations, and Legality

Flipper's CC1101 covers three sub-bands:
- **300-348 MHz**
- **387-464 MHz**
- **779-928 MHz**

Stock firmware region-locks TX. Momentum/Xtreme/Unleashed unlock TX everywhere in hardware-supported bands. **That unlock is a firmware choice; the legal picture does not change.** This document is your reference for what is ISM (license-free), what is public-service (federal crime to transmit on), and what's in between.

> Your Rules of Engagement should explicitly permit any intended TX band. Reception is passive and generally legal in most jurisdictions. Transmission is tightly regulated. The bands flagged **DO NOT TRANSMIT** below are federally prohibited in the United States (47 CFR §§ 2, 90, 95) with analogous provisions in most other jurisdictions.

---

## ISM bands — license-free TX (short-range, low-power)

### 300-348 MHz sub-band

| Frequency | Region | Use | TX allowed by license? |
|-----------|--------|-----|------------------------|
| 300-315 MHz | US (Part 15.231/.235) | Remote controls, keyfobs, garage doors | Yes, low power |
| 315 MHz | US | Dominant US automotive RKE | Yes, low power |
| 318-330 MHz | US | Alarm systems, garage remotes | Yes |
| 330.4 MHz | Worldwide | CAME / some European garage remotes (uncommon) | Region-dependent |
| 340 MHz | Worldwide | Some Chinese remotes | Region-dependent |

### 387-464 MHz sub-band

| Frequency | Region | Use | TX allowed? |
|-----------|--------|-----|------------|
| 390 MHz | US | Automotive RKE variant | Yes, low power |
| 418 MHz | UK, EU | Older UK alarm / remote control | Yes, UK MPT 1340 |
| **433.05-434.79 MHz** | EU ITU Region 1, US Part 15 | **The big ISM band.** Garage doors, weather stations, TPMS, wireless sensors, toys, LoRa. Most `.sub` captures you'll see live here. | Yes, low power (EN 300 220, FCC Part 15) |
| 433.92 MHz | Global | Center of the 433 band; overwhelmingly the most common garage-remote freq | Yes |
| 446 MHz | EU | PMR446 (licensed-free voice walkie-talkies) — **DO NOT TRANSMIT** with Flipper, you'll clobber voice users | No (requires certified PMR446 radio) |
| 460-470 MHz | US | Business/industrial Part 90 (licensed) — **DO NOT TRANSMIT** | No |

### 779-928 MHz sub-band

| Frequency | Region | Use | TX allowed? |
|-----------|--------|-----|------------|
| 779-787 MHz | China | SRD ISM | Yes (China) |
| 863-870 MHz | EU ITU Region 1 | EU ISM (EN 300 220). Z-Wave, some LoRaWAN, Somfy, Hormann. | Yes, low power, duty-cycle limits |
| 868.3 MHz | EU | Z-Wave center | Yes |
| 902-928 MHz | US ITU Region 2, Canada | US ISM. Z-Wave US, LoRaWAN, 900 MHz cordless phones, RFID. | Yes, low power, frequency-hopping typical |
| 908.42 MHz | US | Z-Wave US center | Yes |
| 915 MHz | US/Americas | US ISM center | Yes |
| 920-923 MHz | Japan | Japan ISM (low-power, ARIB STD-T108) | Yes (JP) |

---

## **DO NOT TRANSMIT** bands (public-safety, aircraft, weather, licensed)

In the US, transmitting on any of these without the specific license is a federal offense under 47 USC § 333 (willful interference) and 47 CFR § 90. Fines up to $100k/day, criminal exposure. Analogous rules in CA/UK/EU/AU/JP.

| Band | Use | Why it matters |
|------|-----|----------------|
| **108-137 MHz AM** | Aircraft communications, ILS, VOR | Safety-critical. Interference can bring down a plane. |
| **118-137 MHz** | Air traffic control voice | Same. |
| **138-144 MHz** | Federal government, military | Licensed. |
| **144-148 MHz** | Amateur radio 2m | Needs ham license to TX. |
| **148-174 MHz** | Federal, public safety, marine | Licensed. |
| **156.025-157.425 MHz** | Marine VHF channels | Interference = maritime safety risk. |
| **162.4, 162.425, 162.45, 162.475, 162.5, 162.525, 162.55 MHz** | **NOAA/Environment Canada weather radio** | Public-safety broadcast. TX forbidden. |
| **225-399.9 MHz** | Military UHF | Flipper overlaps part of this in 300-348 band; the 300-315 ISM pocket is carved out of mil-UHF. Stay inside 300-315 on this sub-band. |
| **390 MHz (primary)** | Military; the ISM-RKE usage is a small secondary allocation | In the US, Part 15 low-power is OK; otherwise don't. |
| **400.15-406 MHz** | MetSat, weather balloons (radiosondes) | Avoid. |
| **406-406.1 MHz** | **COSPAS-SARSAT** (emergency distress beacons — PLB/EPIRB) | TX here can trigger a search-and-rescue launch. Criminal offense. |
| **420-450 MHz** | Amateur radio 70cm + federal radiolocation | 433 ISM is a tiny secondary allocation at 433.05-434.79; the rest of 420-450 is federal/ham, not ISM. Don't stray. |
| **470-698 MHz** | TV broadcast | |
| **698-806 MHz** | Cellular (LTE bands 12/13/17/29) | Interference with mobile networks. |
| **806-824, 851-869 MHz** | Public safety (police/fire/EMS trunked) | **CRIMINAL — do not transmit.** |
| **824-849, 869-894 MHz** | Cellular (GSM 850, LTE band 5) | |
| **896-901, 935-940 MHz** | Business-radio licensed | |
| **960-1215 MHz** | Aeronautical radionavigation (DME, TACAN) | |

---

## Flipper firmware TX-unlock behavior

- **Stock firmware** (`flipperdevices/flipperzero-firmware`) — ships with `subghz_frequency_analyzer_worker.c` enforcing region allowlists per the `region` setting in `/int/subghz/assets/regions.json`. Regions: `WORLD`, `EU`, `US`, `JP`. TX attempts outside the allowed sub-bands return error without keying the radio.
- **Momentum / Xtreme / Unleashed** — patch out the region enforcement. The CC1101 will key up at any frequency the MCU tells it. This DOES NOT make it legal — it just means the firmware no longer stops you.
- **Reception is unaffected in all firmwares** — the radio listens wherever you tune it.

---

## Frequency-to-protocol quick lookup

| Frequency | Most likely content |
|-----------|---------------------|
| 315 MHz | US garage opener, US RKE, US TPMS |
| 318 MHz | US alarm system |
| 390 MHz | Older US automotive, HomeLink |
| 433.92 MHz | EU RKE, garage, weather sensor, TPMS, LoRa, everything else |
| 868.3 MHz | Z-Wave EU, Somfy, some European garage systems |
| 915 MHz | Z-Wave US, LoRa US, cordless phone (pre-DECT) |
| 125 kHz | **Not Sub-GHz.** Low-freq RFID. See `echoforge-nfc-rfid`. |
| 13.56 MHz | **Not Sub-GHz.** NFC. See `echoforge-nfc-rfid`. |

---

## Presets (CC1101 bandwidth/modulation packages)

| Preset name | Modulation | Deviation | Bandwidth | Data rate | Typical use |
|-------------|------------|-----------|-----------|-----------|-------------|
| `AM270` | OOK/AM | — | 270 kHz | ~500 bps | Narrow-bandwidth OOK — KeeLoq, Somfy, generic 433 remotes |
| `AM650` | OOK/AM | — | 650 kHz | ~500 bps | Wider OOK — default for Princeton/CAME |
| `FM238` | 2-FSK | 2.38 kHz | 238 kHz | ~5 kbps | Narrowband FSK — weather sensors, TPMS |
| `FM476` | 2-FSK | 4.76 kHz | 476 kHz | ~5 kbps | Wider FSK |

If a capture decodes as `RAW` with the wrong preset, the pulse-train looks noisy or truncated. Retune with `payload_subghz_retune --preset AM650` and re-inspect — often that flips a RAW back into a recognized protocol.
