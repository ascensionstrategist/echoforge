# Phase 6 — Red-Team Research for 3CH0F0RG3

Research date: 2026-04-22
Target firmware baseline: Momentum `mntm-012` (Next-Flip)
Scope: catalog the bleeding edge of Flipper-applicable offensive-security research — academic papers (2023-2026), public CVEs, open-source POCs, commercial red-team framework lessons, and companion-hardware ecosystem — so 3CH0F0RG3 ships the most advanced licensed pentest payload library of its kind.

Companion to `PHASE6_PAYLOAD_RESEARCH.md` (bundled-content audit). That file answers "which repos do we redistribute?"; this file answers "which attacks do we *implement* as first-class actions?"

Conventions:
- Flipper-demonstrability: **N** = native hardware; **C** = needs companion board (WiFi Dev / NRF24 / LoRa / Proxmark); **S** = Flipper as side-channel/sniffer only (main exploit runs elsewhere); **X** = conceptual / not yet integrated
- `[UNVERIFIED]` tag on any claim not anchored in a primary source pulled live during this research pass
- CVE links go to NVD; paper links prefer arXiv or venue-hosted PDF

---

## Executive summary

**Top 5 must-integrate POCs** (detail in §2):
1. **Static-encrypted-nonce + FM11RF08S backdoor attack** (Teuwen, eprint/2024/1275) — shipped in Proxmark3 mainline. Ship as a echoforge `nfc.crack_rf08s` action that talks to either a connected Proxmark3 or, via Momentum's NFC plugin fork, the Flipper NFC stack for the nonce-collection half.
2. **BlueDucky / CVE-2023-45866** (Marc Newlin) — 0-click BLE HID injection on unpatched Android/Linux/iOS. Already feasible via Flipper+NRF24 (not native BT) or ESP32 dev board; ship as `ble.blueducky` action with a target-OS/version gating prompt.
3. **Apple Continuity BLE-spam / CVE-2023-42941** (ECTO-1A "AppleJuice") — canonical demo payload; fixed in iOS 17.2 but still valuable for wireless-policy enforcement testing. Ship the payload taxonomy as `ble.continuity_probe`.
4. **Tesla TPMS 0-click RCE** (Synacktiv, Hexacon 2024; Pwn2Own Automotive 2024) — out-of-scope to weaponize, but the *TPMS capture + decode* half is legitimate automotive-pentest tooling. Ship `subghz.tpms_decode` covering Schrader/Continental/Pacific/Huf formats.
5. **RollBack / RollJam family + 2025 RKE SoK** (Bianchi et al., arXiv:2505.02713; Csikor et al., RollBack ACM TCPS 2024) — the canonical rolling-code attacks with a 2025 systematization. Ship as `subghz.rollback` capture-and-replay orchestrator, gated behind explicit legal disclaimer.

**Top 3 architectural lessons from Sliver / Mythic / Havoc** (detail in §3):
1. **Operator-session-implant separation with mTLS/gRPC** (Sliver) — for echoforge, that maps to **operator ↔ echoforge-core ↔ Flipper-agent** with clear trust boundaries, and a multiplexed protocol between echoforge-core and the TUI so multiple operators can co-drive a hardware engagement. This is how Sliver does multiplayer and it's the cleanest pattern for echoforge's eventual team mode.
2. **Modular C2 profile / payload-type as containers** (Mythic) — Mythic's `Payload_Type` + `C2Profile` as separately versioned Docker containers is exactly the right shape for Flipper payload taxonomies. Ship each echoforge payload class (badusb, nfc, subghz, ble, ir, ibutton, gpio) as an independently versioned plugin with a declarative manifest, a sample set, a MITRE mapping, and a runner.
3. **Declarative YAML tests with ATT&CK mapping** (Atomic Red Team) — the `T1200.yaml` shape (technique ID → platform → prereqs → input args → exec block → cleanup) is the right primitive for echoforge's engagement reports. Every echoforge action emits a test-result artifact in that shape; the engagement-report generator just glues them.

**Biggest single differentiation opportunity:** a **Flipper-native, AI-orchestrated MITRE-ATT&CK-mapped engagement-report generator**. No existing Flipper tool does this; Caldera/Atomic do it for host-based testing but ignore hardware; commercial red-team reports are still written by hand. echoforge sits on top of a Claude agent and has perfect telemetry of every action the operator ran on the hardware — ship a `echoforge report` command that turns a session log into a Word/PDF engagement report with ATT&CK technique annotations, evidence screenshots (of the Flipper UI), and remediation guidance. That single feature is the "why buy echoforge vs. stock Momentum" answer.

---

## 1. State of the art — attack research 2023-2026

### 1.1 NFC / RFID — 13.56 MHz

| # | Research / CVE | Year | Venue / Source | One-line summary | Flipper demo | POC |
|---|----------------|------|----------------|------------------|--------------|-----|
| 1 | **MIFARE Classic static-encrypted-nonce + FM11RF08S hardware backdoor** | 2024 | [eprint/2024/1275](https://eprint.iacr.org/2024/1275.pdf) (Teuwen, Quarkslab) | Single-bit command-field change authenticates with a global backdoor key on Shanghai Fudan FM11RF08S cards; keys recoverable in minutes. | N (nonce collection) / C (full crack via Proxmark) | [noproto gist](https://gist.github.com/noproto/63f5dea3f77cae4393a4aa90fc8ef427), upstream [Proxmark3](https://github.com/RfidResearchGroup/proxmark3) |
| 2 | **Dismantling iClass & iClass Elite** (foundational) | 2012 → still canonical | [USENIX WOOT](https://www.usenix.org/legacy/event/woot11/tech/final_files/Garcia.pdf) | 6 cryptographic weaknesses in HID iClass; loclass attack recovers master key from reader or repeated card reads. | N (Momentum iClass plugin) | [loclass](https://github.com/RfidResearchGroup/proxmark3/tree/master/client/src/loclass) |
| 3 | **HID iClass SE legacy-downgrade** | 2024 | [DEF CON 32 Javadi/Levy/Draffen](https://ipvm.com/reports/iclass-se-exploit) | iClass SE readers still process legacy iClass credentials → attacker clones a legacy card to defeat SE deployment. | N (read/emulate legacy tag) | DEF CON 32 media archive |
| 4 | **CVE-2024-29941 — ICT MIFARE/DESFire key leakage** | 2024 | [GHSA-wh7x-ww7q-h9hp](https://github.com/advisories/GHSA-wh7x-ww7q-h9hp) | ICT Protege firmware stored MIFARE/DESFire site encryption keys in cleartext in the binary, enabling credential forgery. | N (emulate crafted tag) | vendor advisory |
| 5 | **Bias in MIFARE DESFire EV1 TRNG** | 2016 → still open | [ResearchGate](https://www.researchgate.net/publication/311100971_Bias_in_the_TRNG_of_the_Mifare_DESFire_EV1) | Biased RNG in DESFire EV1 weakens the AES challenge protocol; no practical crack published but primitive is real. | S (Flipper capture, offline analysis) | [UNVERIFIED] no standalone POC |
| 6 | **MIFARE Classic hardnested** (foundational, still mainline) | 2015 → current | [mfoc-hardnested](https://github.com/nfc-tools/mfoc-hardnested), [Proxmark3 hardnested](https://deepwiki.com/RfidResearchGroup/proxmark3/6.1-key-recovery-attacks) | Statistical cryptanalysis of hardened Classic cards; SIMD-accelerated, required when PRNG is non-weak. | C | in Proxmark3 mainline |
| 7 | **NFC Relay (NFCA APDU)** | 2023-2025 | [leommxj/nfc_relay](https://github.com/leommxj/nfc_relay) | Relay NFC-A APDUs between two Flippers over BLE/WiFi; proven against transit and hotel readers. | N | GitHub repo |
| 8 | **Amiibo (NTAG215) emulation** | 2023-2026 | [Gioman101/FlipperAmiibo](https://github.com/Gioman101/FlipperAmiibo) | Emulates Nintendo Amiibo NTAG215 with per-character dumps; Switch occasionally rejects post-firmware-update. | N | GitHub repo |
| 9 | **Metrocard/transit card replay** | 2025 | [ZafkoGR/FlipperZero-MetroCard-Security](https://github.com/ZafkoGR/FlipperZero-MetroCard-Security) | Academic paper + PoC analyzing RFID cloning, NFC relay, and crypto weaknesses in transit cards. | N | GitHub repo |

### 1.2 RFID — 125 kHz (low-freq)

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 10 | **EM410x / EM4100 cloning** | canonical | [Flipper docs](https://docs.flipper.net/rfid) | Trivially cloneable 64-bit fixed-ID protocol; still the default in low-end access control. | N | built-in |
| 11 | **HID Prox / Pyramid / AWID decoder** | canonical | Momentum FW | Fixed-ID 125 kHz FSK formats; Flipper reads natively, can emulate if target reader accepts. | N | Momentum firmware built-in |
| 12 | **Indala format brute-force** | 2024 | [DarkFlippers/Multi_Fuzzer](https://github.com/DarkFlippers/Multi_Fuzzer) | 125 kHz RFID fuzzer generating sequential IDs across HID/EM/Indala formats. | N | GitHub repo, MIT |
| 13 | **EM4305/T5577 programming** | canonical | [Flipper docs](https://docs.flipper.net/rfid) | Cloning source for blank 125 kHz tags; supports EM4100, HID, Indala emulation. | N | built-in |
| 14 | **ESPKey Wiegand MITM** | 2017 → [2024 long-range variant](https://www.netspi.com/blog/technical-blog/adversary-simulation/a-new-tastic-thief/) | [octosavvi/ESPKey](https://github.com/octosavvi/ESPKey) | Implant between reader and controller logs/replays Wiegand credentials; 80k buffer, WiFi retrieve. NetSPI 2024 combined it with a long-range tastic-style reader for 3+ ft read. | S (Flipper provides portable power + UI) | GitHub repo |

### 1.3 SubGHz (300-928 MHz)

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 15 | **Hitag2 immobilizer break** | 2012 → canonical | [USENIX Sec 2012](https://www.usenix.org/system/files/conference/usenixsecurity12/sec12-final95.pdf) (Verdult/Garcia) | 48-bit stream cipher recoverable in <6 min; 200+ vehicle models use it. | S (capture) / C (needs Proxmark/PICC tools for active part) | in Proxmark3 |
| 16 | **Hitag2 RKE "One Car, Two Frames"** | 2018 | [ResearchGate](https://www.researchgate.net/publication/325946713_One_Car_Two_Frames_Attacks_on_Hitag-2_Remote_Keyless_Entry_Systems_Revisited) | Revisit of Hitag2 RKE attacks — 2 captured frames sufficient to clone. | S (capture) | academic |
| 17 | **KeeLoq DPA / FPGA break** | 2008 (still the canonical) | [eprint/2011/242](https://eprint.iacr.org/2011/242.pdf) | DPA recovers KeeLoq manufacturer key from 10 traces; pure-math attack with known plaintext recovers device key. | S (capture & replay) / X (full DPA needs oscilloscope) | academic |
| 18 | **Rolling-PWN (Honda RKE 2012-2022)** | 2022 | [rollingpwn.github.io](https://rollingpwn.github.io) | Consecutive counter values resync the receiver — replay unlocks Honda vehicles even with rolling codes. | N | public PoC |
| 19 | **RollBack — time-agnostic RKE replay** | 2024 | [ACM TCPS](https://dl.acm.org/doi/10.1145/3627827) (Csikor et al.) | Replay windows exist on many RKE counters — no jamming required, unlike RollJam. | N | academic |
| 20 | **SoK: Stealing Cars Since RKE** | 2025 | [arXiv:2505.02713](https://arxiv.org/abs/2505.02713) (Bianchi/Brighente/Conti/Pavan, USENIX VehicleSec 25) | Systematization of all RKE/PKES attacks through 2025; identifies persistent gaps (Relay, RollJam, API). | S (multiple sub-attacks demoable) | paper |
| 21 | **CAME ATOMO rolling-code decoder** | canonical | Momentum FW | Italian garage-door opener; Flipper has native decoder. | N | Momentum FW |
| 22 | **Nice Flo / FloR / Smilo / Lince** | canonical | Momentum FW | Italian gate openers, fixed + rolling variants. | N | Momentum FW |
| 23 | **Somfy RTS / Telis** | canonical | [Flipper forum](https://forum.flipper.net/t/furi-app-development-somfy-rts-remote/16561) | French blind/shutter controller, rolling code, Flipper can program new remote onto existing receiver. | N | Momentum FW + custom FAP |
| 24 | **Security+ 1.0 / 2.0 (Chamberlain/LiftMaster)** | canonical | Momentum FW | US garage-door rolling codes; Security+ 2.0 is post-2011. | N | Momentum FW |
| 25 | **Princeton / Holtek / PT2262** | canonical | Momentum FW | 12-bit fixed-code protocols; core of `tobiabocchi/flipperzero-bruteforce` generator. | N | [bruteforce repo](https://github.com/tobiabocchi/flipperzero-bruteforce) |
| 26 | **Tesla charge-port unlock (315/433 MHz)** | 2022-2024 | [Robbbbbbbbb/tesla-chargeport](https://github.com/Robbbbbbbbb/tesla-chargeport) | Fixed-ID-equivalent signal opens any Tesla charge port. Tesla has not filed CVE. | N | GitHub repo |
| 27 | **TPMS decoder (Schrader/Continental/Pacific/Huf)** | canonical + Momentum | Momentum FW | Passive capture of TPMS broadcasts for vehicle tracking & fleet-theft attacks. | N | Momentum FW |
| 28 | **Tesla TPMS 0-click RCE (Pwn2Own Auto 2024)** | 2024 | [Synacktiv Hexacon 2024](https://www.synacktiv.com/sites/default/files/2024-10/hexacon_0_click_rce_on_tesla_model_3_through_tpms_sensors_light.pdf), [CVE-2025-2082](https://undercodenews.com/tesla-model-3-hacked-via-tire-sensors-inside-the-cve-2025-2082-vulnerability/) | Out-of-bounds write via negative `startIndex` in TPMS setup → arbitrary code on Tesla VCSEC ECU. Fixed in firmware 2024.14. | S (capture only — RCE half out of scope) | Synacktiv slides |
| 29 | **Flipper-Zero Sub-GHz jamming** (content-free) | 2023-2025 | [SHUR1K-N/Flipper-Zero-Sub-GHz-Jamming-Files](https://github.com/SHUR1K-N/Flipper-Zero-Sub-GHz-Jamming-Files) | Removed-from-mainline jamming .sub files; legally restricted in most jurisdictions. | N | GitHub repo |

### 1.4 BLE / Bluetooth Classic

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 30 | **CVE-2023-45866 — BlueDucky 0-click HID** | 2024 POC by Marc Newlin | [CVE-2023-45866 NVD](https://nvd.nist.gov/vuln/detail/CVE-2023-45866), [pentestfunctions/BlueDucky](https://github.com/pentestfunctions/BlueDucky) | Unauthenticated BT pairing → HID keystroke injection on Android/Linux/iOS (w/ Magic Keyboard)/macOS. | C (needs BT adapter; Flipper BT stack too limited, use ESP32-S3 companion or Pi Zero) | GitHub |
| 31 | **CVE-2024-21306 — Windows BT HID spoof** | 2024 | [NVD](https://nvd.nist.gov/vuln/detail/CVE-2024-21306), [PhucHauDeveloper/BadBlue](https://github.com/PhucHauDeveloper/BadBlue) | L2CAP-19 connection without auth → keystroke injection on Win10/11/Server 2022. Patched Jan 2024. | C | GitHub |
| 32 | **CVE-2023-42941 — AppleJuice iOS freeze** | 2023-2024 | [ecto-1a writeup](https://ecto-1a.github.io/AppleJuice_CVE/) | Malformed Continuity BLE packet → iOS 17 freeze/crash/reboot. Fixed iOS 17.2. | N | Momentum BLE-spam app |
| 33 | **BLESA — reconnect spoofing** | 2020 → still canonical | [USENIX WOOT20](https://www.usenix.org/system/files/woot20-paper-wu-updated.pdf) | Post-pairing reconnect auth marked optional → spoof previously-paired peer. | C | academic |
| 34 | **KNOB — BT/BLE entropy downgrade** | 2019-2020 → still canonical | [francozappa KNOB](https://francozappa.github.io/publication/knob-ble/paper.pdf) | Entropy of BT LTK / BLE STK can be downgraded to 7 bytes. | C | academic |
| 35 | **BLURtooth — cross-transport key derivation** | 2020 [CVE-2020-15802](https://nvd.nist.gov/vuln/detail/CVE-2020-15802) | [hexhive BLUR](https://hexhive.epfl.ch/BLURtooth/), [francozappa/blur](https://github.com/francozappa/blur) | CTKD overwrites BLE/BT keys cross-transport → impersonation. | C | GitHub |
| 36 | **BLERP — BLE re-pairing** | 2026 | [NDSS 2026](https://www.ndss-symposium.org/wp-content/uploads/2026-f121-paper.pdf) | Forced re-pairing downgrade on Android 10-15; "affected millions of iPhones in 2024" per paper. | C | NDSS paper |
| 37 | **Fitness-tracker BLE MITM** | 2025 | [PMC 11945526](https://pmc.ncbi.nlm.nih.gov/articles/PMC11945526/) | Standards-compliant MITM on LTK/STK exchange during feature-exchange phase. | C | academic |
| 38 | **Apple Continuity BLE-spam (general)** | 2023-2025 | [EvanDebruyne/Flipper-Zero-BLE-Spam](https://github.com/EvanDebruyne/Flipper-Zero-BLE-Spam) | Fake AirDrop/Find My/AirPods packets → nuisance popups on nearby Apple devices. | N | GitHub repo |

### 1.5 2.4 GHz proprietary (NRF24)

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 39 | **MouseJack (Bastille, 2016 → still-open)** | 2016-2024 | [mousejack.com](https://www.mousejack.com), [BastilleResearch/mousejack](https://github.com/BastilleResearch/mousejack) | Unencrypted NRF24 HID dongles (Logitech/Dell/HP/Lenovo/Amazon) accept injected keystrokes from ~100m. | C (NRF24 module via GPIO) | GitHub |
| 40 | **KeyJack (SySS, AES-level)** | 2016-2024 | [syss paper](https://www.syss.de/fileadmin/dokumente/Publikationen/2017/2017_06_01_of-mice-and-keyboards_paper.pdf), [BastilleResearch/keyjack](https://github.com/BastilleResearch/keyjack) | AES-encrypted NRF24 sets still vulnerable — counter bypass, replay, key recovery. | C | GitHub |
| 41 | **JackIt automation wrapper** | 2017-2024 | [mothball187/flipperzero-nrf24](https://github.com/mothball187/flipperzero-nrf24) | DuckyScript-driven keystroke injection over NRF24 via Flipper+module. | C | GitHub |
| 42 | **Flipper NRF24 jammer (2.4 GHz)** | 2024-2025 | [W0rthlessS0ul/FZ_nRF24_jammer](https://github.com/W0rthlessS0ul/FZ_nRF24_jammer), [huuck/FlipperZeroNRFJammer](https://github.com/huuck/FlipperZeroNRFJammer) | BT/BLE/WiFi/Zigbee jamming via 2.4 GHz noise broadcast. Legally restricted. | C | GitHub |

### 1.6 IR / IrDA

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 43 | **IRDB universal remote superset** | 2020-2026 | [Lucaslhm/Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB) | 41 MB of captured IR codes; CC0 license; canonical library. | N | GitHub |
| 44 | **TV-B-Gone–style "all-off" broadcast** | 2004 → Flipper-ported | Momentum FW | Iterates known power-off codes across manufacturers. | N | Momentum FW built-in |
| 45 | **AC unit protocol analysis (Daikin/Mitsubishi)** | 2023-2025 | [HobbyTransform](https://github.com/unitedhobbyists) [UNVERIFIED exact repo] | Proprietary AC protocols reverse-engineered for capture + replay. | N | varies |

### 1.7 USB / HID / BadUSB

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 46 | **DuckyScript 3.0 (Hak5)** | 2022-2025 | [PayloadStudio](https://payloadstudio.hak5.org/), [hak5/usbrubberducky-payloads](https://github.com/hak5/usbrubberducky-payloads) | Feature-rich scripting language — variables, conditions, loops, randomization — superset of DS 1.0. Flipper supports DS 1.0; Momentum JS BadUSB is a separate runtime. | N (DS 1.0 only) / X (DS 3.0 not supported on Flipper) | GitHub |
| 47 | **Flipper BadUSB serial-exfil trick** | 2024 | [revers3everything](https://revers3everything.com/data-exfiltration-bypassing-usb-storage-restrictions-with-serial-communication-channel-with-flipper-zero-badusb/) | After HID phase, Flipper switches to CDC-serial and exfils over the same cable, bypassing USB-storage policy. | N | blog PoC |
| 48 | **Raspberry Pi Pico as BadUSB host** | 2023-2025 | [kacperbartocha/pico-badusb](https://github.com/kacperbartocha/pico-badusb), [RoganDawes/P4wnP1](https://github.com/RoganDawes/P4wnP1) | $4 Pico W replaces Hak5 Rubber Ducky with DS-alike syntax + WiFi OOB. | S (Flipper as power/UI) | GitHub |
| 49 | **Momentum JS BadUSB** | 2025 | [Momentum wiki](https://momentum-fw.dev/wiki) | JavaScript runtime for BadUSB allowing loops, conditionals, and runtime branch decisions that DS 1.0 can't express. Unique to Momentum. | N | Momentum FW |

### 1.8 iButton / 1-Wire

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 50 | **DS1990A / Cyfral / Metacom cloning** | canonical | [Flipper docs](https://docs.flipper.net/ibutton) | 1-Wire ID protocols with no auth; trivially clonable. | N | built-in |
| 51 | **Intercom key dumps (RU/CIS)** | 2025 | [wetox-team/flipperzero-goodies](https://github.com/wetox-team/flipperzero-goodies) | Russian/CIS apartment-intercom 1-Wire key database. | N | GitHub |

### 1.9 Physical / OOB / hardware-debug

| # | Research / CVE | Year | Source | Summary | Flipper demo | POC |
|---|----------------|------|--------|---------|--------------|-----|
| 52 | **JTAG/SWD via GPIO (DAP-Link)** | 2022-2025 | [SecureIdeas blog](https://www.secureideas.com/blog/flipper-zero-jtag-and-swd) | Flipper acts as a CMSIS-DAP JTAG/SWD probe, driving OpenOCD → Ghidra pipeline for firmware extraction. | N | Flipper DAP-Link FAP |
| 53 | **SWD pin-finder (`blueTag` / SWD Probe FAP)** | 2023-2025 | [Bus Pirate docs](https://docs.buspirate.com/docs/devices/jtag-swd-pin-finder/) | Systematically probes unknown header pins to identify JTAG/SWD. Integrated in Bus Pirate 5; also a Flipper FAP. | N | Flipper SWD Probe FAP |
| 54 | **UART sniffing / flash dumping via GPIO** | canonical | [HardBreak wiki](https://www.hardbreak.wiki/hardware-hacking/interface-interaction/jtag-swd/extract-firmware-using-jtag-swd) | 3.3V UART + GPIO 5V tolerant → console-access + bootloader-drop for embedded targets. | N | built-in GPIO app |

---

## 2. Top 15 POCs ranked for echoforge integration

Ranking weights: novelty × Flipper feasibility × POC availability × legitimate pentest utility.

| Rank | POC | What echoforge ships | Module | MCP tool |
|------|-----|-------------------|--------|----------|
| 1 | **FM11RF08S backdoor + static-nonce attack** (eprint/2024/1275) | Action to coordinate Proxmark3-over-serial **or** Flipper-NFC nonce collection, run Teuwen's `staticnested_*` tool chain, present cracked sector keys. | `actions/nfc/rf08s_crack.py` | `nfc.crack_rf08s` |
| 2 | **BlueDucky / CVE-2023-45866** | Script runner that drives an ESP32-S3 companion board (preferred) or flashed Raspberry Pi Zero W over UART — Flipper is operator UI only. Target-OS gating prompt, ROE confirm. | `actions/ble/blueducky.py` | `ble.blueducky` |
| 3 | **Apple Continuity BLE-spam taxonomy** | Wrap Momentum BLE-spam app with a typed Python facade: packet-class selector, duration gate, MAC-rotation rate, target-device-class heuristic. | `actions/ble/continuity_spam.py` | `ble.continuity_spam` |
| 4 | **TPMS capture + decode** (Schrader/Continental/Pacific/Huf) | Passive SubGHz listener that decodes all 4 major formats, logs VIN-linkable IDs, optional CSV export for fleet-asset inventory. | `actions/subghz/tpms_listen.py` | `subghz.tpms_listen` |
| 5 | **RollBack replay orchestrator** | Capture N consecutive RKE presses → replay in order. Explicit legal disclaimer gate (US: 47 CFR §15.5; EU: Directive 2014/53/EU). | `actions/subghz/rollback.py` | `subghz.rollback` |
| 6 | **NFC Relay (APDU-level)** | Port of `leommxj/nfc_relay` into a echoforge action. Pair Flipper-A (card-side) ↔ Flipper-B (reader-side) over echoforge-core relay with TLS. | `actions/nfc/relay.py` | `nfc.relay` |
| 7 | **MouseJack full suite** | NRF24-companion-driven injection against Logitech/Dell/HP/Lenovo/Amazon unencrypted dongles; ships JackIt-equivalent payload DB. | `actions/nrf24/mousejack.py` | `nrf24.mousejack` |
| 8 | **Hitag2 capture (academic/pentest only)** | Sniff Hitag2 handshake from legitimate key use; ship offline cracker wrapper. **Do not ship the "start car" half** — research-only scope. | `actions/subghz/hitag2_capture.py` | `subghz.hitag2_capture` |
| 9 | **MIFARE Classic hardnested** (Proxmark-backed) | Pass-through to connected Proxmark3 for hardnested; Flipper is the card-scan-orchestrator. | `actions/nfc/hardnested.py` | `nfc.hardnested` |
| 10 | **Wiegand interception (ESPKey integration)** | Flipper as portable power + UI for an ESPKey installed in a reader; retrieve buffered credentials, format as `.rfid` Flipper files for re-emulation. | `actions/physical/espkey_dump.py` | `physical.espkey_dump` |
| 11 | **JTAG/SWD enumerate + dump** | Unified `hw.jtag_probe` → pin-find → OpenOCD attach → Ghidra-ready `.bin` dump. Wraps existing Flipper DAP-Link + SWD Probe FAPs. | `actions/hw/jtag_probe.py` | `hw.jtag_probe` |
| 12 | **Pwnagotchi control plane** | Flipper as UART operator-console for a Pi Zero W pwnagotchi; display current handshake count, switch modes. | `actions/ble/pwnagotchi_ctl.py` | `hw.pwnagotchi_ctl` |
| 13 | **TV-B-Gone + IRDB universal-off** | Smart broadcast that iterates IRDB power-off codes, prioritized by captured-remote fingerprinting if any remote is held to Flipper IR first. | `actions/ir/universal_off.py` | `ir.universal_off` |
| 14 | **125 kHz fuzzer (EM/HID/Indala)** | Sequential + dictionary + pattern-based brute for low-security access control; rate-limited. | `actions/rfid/lf_fuzz.py` | `rfid.lf_fuzz` |
| 15 | **Momentum JS BadUSB payload studio** | A linter + runtime sim for Momentum's JavaScript BadUSB dialect (unique to Momentum, no other studio exists). Pairs with the "DuckyScript linter" gap already flagged. | `tools/js_badusb_lint/` + `actions/badusb/js_run.py` | `badusb.js_run` |

For each: echoforge ships a typed Pydantic `ActionRequest`, a `SafetyPolicy.assess` entry (risk level), a MITRE-ATT&CK mapping (see §4), and a test-vector fixture.

---

## 3. Red-team framework architecture lessons

### 3.1 Component ownership model

| Framework | Operator | Server | Agent/Implant | Protocol | Transport |
|-----------|----------|--------|----------------|----------|-----------|
| **Sliver** | Multiplayer CLI / console | Go server + BoltDB | "Sliver" (session) or "Beacon" (async) | gRPC + Protobuf | mTLS / HTTPS / DNS / WireGuard ([ref](https://medium.com/@lord_murak/sliver-c2-for-red-team-operations-153135648218)) |
| **Mythic** | Web UI | Python core + RabbitMQ + gRPC to containerized components | Per-payload-type Docker container | C2Profile = swappable container | HTTP / DNS / SMB / WebSocket ([ref](https://docs.mythic-c2.net/customizing/payload-type-development)) |
| **Havoc** | Qt client | Golang teamserver | "Demon" (C/ASM) | Custom binary + AES-256 | HTTP / HTTPS / SMB pipes ([ref](https://havocframework.com/docs/listeners)) |
| **Caldera** | Web UI | async Python core, REST API | Sandcat / Manx / Ragdoll / custom | YAML `abilities` + `adversaries` | HTTP / TCP / contact plugins ([ref](https://github.com/mitre/caldera)) |
| **Atomic Red Team** | CLI (Invoke-AtomicTest) | *none — library* | *none — local PS/Bash* | YAML manifest | local exec ([ref](https://github.com/redcanaryco/atomic-red-team)) |

### 3.2 Transferable lessons (ranked)

1. **Operator ↔ core ↔ agent separation with mTLS/gRPC (Sliver)**
   echoforge's current shape is single-operator ↔ echoforge-core ↔ Flipper, but the same tri-layer mTLS/gRPC pattern unlocks multi-operator teaming in Phase 7+ without re-architecting. Recommend: define a echoforge gRPC API now with future "Multiplayer" extensions reserved.

2. **Modular `PayloadType` + `C2Profile` as versioned plugins (Mythic)**
   Mythic treats every agent and every transport as a *separately versioned, containerized plugin* that the core dynamically loads at runtime. For echoforge that means each payload class (`nfc`, `subghz`, `ble`, `badusb`, `ir`, `ibutton`, `gpio`) becomes an independently versioned Python subpackage with a declarative manifest (`payload.yaml` — schema, MITRE mapping, sample fixtures, risk level) and a runner. Users can drop a community-contributed payload pack into `~/.echoforge/payloads/<name>` and echoforge picks it up on next start.

3. **Declarative YAML test + ATT&CK mapping (Atomic Red Team)**
   `atomics/T1200/T1200.yaml` format — (name, description, supported_platforms, input_arguments, dependencies, executor) is a clean minimal primitive. **Every echoforge action emits its execution record in exactly this shape**, which then gets glued by the engagement-report generator (§7). This is how the MITRE-mapped auto-report gets written "for free."

4. **Beacon vs. Session modes (Sliver)**
   Flipper is almost always an interactive session (operator present, button pressed), but *long-duration captures* (TPMS drive-by, Wiegand dump, pwnagotchi handshake collect) are effectively "beacon" jobs. Adopt Sliver's vocabulary: echoforge has `session` actions (immediate, operator-driven) and `beacon` actions (long-duration, scheduled, periodic check-in). TUI shows both in a unified timeline.

5. **Event timeline & engagement reporting (Caldera + Mythic)**
   Caldera's `operation` produces a linear timeline of `link`s; Mythic's task history is the authoritative artifact for report writing. echoforge already has `AuditService` — formalize it into an `Engagement` object that is the unit of reporting (start time, operator, scope-acknowledged-at, list of `Action` runs, list of `Finding`s, exit timestamp).

6. **OPSEC profiles (Havoc / Mythic malleable C2)**
   Physical red-team OPSEC is different from Windows C2 OPSEC, but the *pattern* transfers: define "quiet / normal / loud" profiles that tune transmission duty cycle, replay window, MAC-rotation rate, BadUSB typing delay, etc. The operator picks one per engagement; echoforge logs which profile was active for each action.

7. **Artifact → MITRE mapping (Caldera)**
   Every Caldera ability has `technique_id` + `technique_name` fields. echoforge adopts `mitre_id: list[str]` on every `ActionRequest` — a single action may exercise multiple techniques (e.g., `rollback` → T1200 + T1037 [UNVERIFIED mapping]).

### 3.3 What *doesn't* transfer

- Sliver/Mythic/Havoc agents are memory-resident post-exploitation implants on general-purpose OSes. Flipper is hardware-in-the-loop; there is no "shellcode" equivalent, no EDR to evade, no privilege escalation. Do not copy their *implant* architecture — copy their *control plane* architecture.
- Caldera's `chain mode` assumes abilities produce facts that subsequent abilities consume. Flipper actions mostly don't chain like that (a captured `.sub` feeds into a replay, but there's no deep fact graph). Keep chain support simple: linear playbooks, not Caldera's full planning system.

---

## 4. MITRE ATT&CK mapping

Primary reference: [MITRE ATT&CK Enterprise v15](https://attack.mitre.org/). Hardware-carrier techniques are sparse in ATT&CK — T1200 (Hardware Additions) is the umbrella, but Flipper operations map to a handful of non-obvious enterprise techniques.

| T-ID | Technique | Flipper capability | Protocol / HW | Evidence source |
|------|-----------|---------------------|----------------|------------------|
| [T1200](https://attack.mitre.org/techniques/T1200/) | Hardware Additions | Primary umbrella — any Flipper plug-in/relay/probe | Any | Flipper USB-CDC + action log |
| [T1078](https://attack.mitre.org/techniques/T1078/) | Valid Accounts | Cloned badge used at door reader | 125 kHz / 13.56 MHz | Access-control log + Flipper emulation record |
| [T1110](https://attack.mitre.org/techniques/T1110/) | Brute Force | LF RFID dictionary/sequential, SubGHz fixed-code brute | 125 kHz / SubGHz | `.rfid` / `.sub` file set + echoforge timing log |
| [T1557](https://attack.mitre.org/techniques/T1557/) | Adversary-in-the-Middle | NFC relay; Wiegand ESPKey; serial MITM on UART | NFC-A / Wiegand / UART | Relay pcap + Flipper log |
| [T1040](https://attack.mitre.org/techniques/T1040/) | Network Sniffing | TPMS passive listen, Sub-GHz sniff, WiFi Dev packet capture | SubGHz / 2.4 GHz | `.sub` / `.pcap` artifacts |
| [T1562.004](https://attack.mitre.org/techniques/T1562/004/) | Disable or Modify System Firewall | BadUSB scripted `netsh`/`iptables` tamper | USB-HID | DuckyScript transcript |
| [T1059.001](https://attack.mitre.org/techniques/T1059/001/) | PowerShell | BadUSB drops PowerShell payload | USB-HID | DuckyScript transcript |
| [T1059.003](https://attack.mitre.org/techniques/T1059/003/) | Windows Command Shell | BadUSB cmd.exe execution | USB-HID | DuckyScript transcript |
| [T1068](https://attack.mitre.org/techniques/T1068/) | Exploitation for Privilege Escalation | BadUSB UAC-bypass payload, JTAG debug takeover | USB-HID / JTAG | Script + Flipper log |
| [T1499.004](https://attack.mitre.org/techniques/T1499/004/) | Endpoint DoS — Application/System Exploitation | AppleJuice (CVE-2023-42941), BLE-spam reboot | BLE | Flipper log + target device screenshot |
| [T1036](https://attack.mitre.org/techniques/T1036/) | Masquerading | Flipper presents as USB keyboard with legitimate-looking VID/PID | USB | USB descriptor dump |
| [T1565.002](https://attack.mitre.org/techniques/T1565/002/) | Transmitted Data Manipulation | Sub-GHz replay/rollback, NFC replay | SubGHz / NFC | `.sub` / `.nfc` artifact |
| [T1541](https://attack.mitre.org/techniques/T1541/) | Foreground Persistence (mobile) | BLE-spam-induced stuck-modal DoS on iOS | BLE | Flipper log + target iOS version |
| [T1195.003](https://attack.mitre.org/techniques/T1195/003/) | Supply Chain — Hardware | (mapping only) documents an implanted ESPKey as ATT&CK-visible | Wiegand implant | Install photo + ESPKey buffer |
| [T1600](https://attack.mitre.org/techniques/T1600/) | Weaken Encryption (Network) | KNOB downgrade to 7-byte entropy | BT / BLE | Sniffer pcap |
| [T1001.003](https://attack.mitre.org/techniques/T1001/003/) | Data Obfuscation — Protocol Impersonation | AppleJuice spoofs Continuity format | BLE | Flipper payload file |

For ICS engagements echoforge should also reference **MITRE ATT&CK for ICS** (T0817 Drive-by Compromise via engineering WiFi, T0836 Modify Parameter via SubGHz command injection). That mapping is left for Phase 7 when the ICS subagent lands.

Output format: every `ActionRequest.mitre_id` is a list of these T-IDs; the engagement-report generator aggregates them into an ATT&CK Navigator layer (JSON) that the operator delivers alongside the PDF.

---

## 5. AI-augmentation state of the art

Survey of LLM-in-pentest projects, January 2026 cutoff. Grouped by maturity.

### 5.1 Academic / benchmark

| Project | Year | Source | What it is | Autonomy level |
|---------|------|--------|------------|----------------|
| **PentestGPT** | 2023-2024, USENIX Sec 2024 | [GreyDGL/PentestGPT](https://github.com/GreyDGL/PentestGPT) | LLM-guided plan/recon/exploit loop; operator copies commands. | Copilot (human executes) |
| **HackingBuddyGPT** | 2024 | [ipa-lab/hackingBuddyGPT](https://github.com/ipa-lab/hackingBuddyGPT) | LLM drives SSH/shell directly; ~50 LoC core; sandboxed Linux priv-esc. | Autonomous (sandbox) |
| **AutoAttacker** | 2024 | arXiv 2403.01038 [UNVERIFIED link] | Planner + Experience Manager (RAG) + Navigator; extends PentestGPT architecture. | Autonomous |
| **HackSynth** | 2024 | [arXiv:2412.01778](https://arxiv.org/abs/2412.01778) | Planner + Summarizer modules; iterative command generation. | Autonomous |
| **VulnBot** | 2025 | [arXiv:2501.13411](https://arxiv.org/pdf/2501.13411) | Multi-agent collaborative; 69% subtask completion on benchmark. | Autonomous (multi-agent) |
| **AutoPentest** | 2025 | [arXiv:2505.10321](https://arxiv.org/abs/2505.10321) | Vulnerability management + LLM agent integration. | Semi-autonomous |
| **CurriculumPT** | 2025 | [MDPI Applied Sciences](https://www.mdpi.com/2076-3417/15/16/9096) | Curriculum-guided task scheduling for multi-agent pentest. | Autonomous |
| **RapidPen** | 2025 | [UNVERIFIED arXiv link] | IP-to-shell fully autonomous pipeline. | Autonomous |
| **Automated Planning + LLM** | 2025 | [arXiv:2512.11143](https://arxiv.org/pdf/2512.11143) | Combines classical AI planning (PDDL) with LLM for pentest step selection. | Autonomous |

### 5.2 Safety / evaluation benchmark

| Project | Year | Source | Relevance to echoforge |
|---------|------|--------|---------------------|
| **AgentDojo** | 2024 (NeurIPS), 2025 (SafeBench winner) | [agentdojo.spylab.ai](https://agentdojo.spylab.ai/) | Prompt-injection robustness benchmark for tool-using agents. Every echoforge MCP tool should be hardened against AgentDojo-class injection attacks in its input descriptions. |
| **NIST AI Agent Hijacking Evaluations** | 2025 | [NIST blog](https://www.nist.gov/news-events/news/2025/01/technical-blog-strengthening-ai-agent-hijacking-evaluations) | Red-team methodology for LLM-controlling-tools systems. |
| **Cybench** | 2024-2025 | (SafeBench co-winner) | CTF-style LLM benchmark. Useful reference for echoforge's own evaluation harness. |

### 5.3 Commercial / hybrid

| Project | Maturity | Relevance |
|---------|----------|-----------|
| **Microsoft Security Copilot** | GA 2024 | Detection/response side, not offensive. Reference for human-in-loop UX. |
| **XBOW** | 2025 | Autonomous web-app pentester; 86.5% success on internal benchmark [per their own report — [UNVERIFIED]]. |
| **Penligent / PentestAI** | 2024-2025 | Minor commercial plays; no published benchmarks. |

### 5.4 What's working vs. hype

- **Working:** *Reasoning about output* (what does this nmap result mean? what does `authorized_keys` imply?); *synthesizing reports* (this is what echoforge's engagement-report generator rides on); *recon/enum automation* at a small scale.
- **Hype:** *fully autonomous 0-to-shell on realistic networks* — end-to-end pipelines hit ~31% success ([arXiv:2507.00829](https://arxiv.org/html/2507.00829v1)); *creative exploit dev*; *adversarial EDR evasion*; *multi-week campaigns*.

### 5.5 echoforge's differentiation

No other AI-pentest project operates on **physical/RF hardware**. Every framework above is software-only (web/Linux/Windows/cloud). echoforge's niche:

1. **Hardware operator loop.** Claude SDK + `can_use_tool` gives us a first-class hold-to-confirm path for *physical-world* risk (don't transmit on 433.92 MHz without ROE; don't fuzz a production reader without scope ack). No existing AI-pentest tool has this.
2. **Spectrum-aware planner.** The AI knows "we're in EU 868 region" (from operator declaration) and refuses to generate actions that violate local Sub-GHz TX rules (see §8). PentestGPT has no concept of this.
3. **Artifact-to-MITRE auto-mapping for hardware techniques.** Zero existing tools do this for T1200 / T1557 hardware-carrier subclasses.
4. **Engagement-report generator with photo evidence.** The Flipper has a screen; screenshot each action. Bolt that into a PDF. No competitor does this.

---

## 6. Companion hardware ecosystem

Pinout source: Flipper Zero [official GPIO pinout](https://docs.flipper.net/gpio/pinout).

Flipper GPIO header (18 pins, two rows):

```
 1  +5V        2  PC0 (A7)
 3  +3.3V      4  PC1 (A6)
 5  SWCLK      6  PB3 (A4)
 7  GND        8  PB2 (A3 / SPI MOSI)
 9  SWDIO     10  PA7 (A2 / SPI MISO)
11  GND       12  PA4 (A1 / SPI CS)
13  +5V TP    14  PB15 (A0 / TIM1)
15  PC3       16  PA6 / UART RX
17  GND       18  PA7 / UART TX
```

| Companion | Uses pins | Uses protocol | Conflicts with | Integration path |
|-----------|-----------|---------------|-----------------|-------------------|
| **ESP32 WiFi Dev Board (Marauder)** | 1, 8, 9, 11, 17, 18 | UART (115200-921600) | NRF24, LoRa (share UART) | Momentum has built-in Marauder companion app. echoforge proxies via `flipper_wifi_marauder` plugin IPC. |
| **ESP32 "Double Barrel 5G"** (2025, RTL8720DN) | same as above | UART | same | Same app flow; 5 GHz deauth in addition to 2.4. |
| **NRF24L01+ module** | 1, 8, 9, 10, 11, 12 | SPI | ESP32 (SPI bus shared if no separate CS) | `mothball187/flipperzero-nrf24` + `flipperzero-nrf24l01+` apps. |
| **LoRa / RFM95W board** | 1, 8, 9, 10, 11 | SPI | NRF24 (CS contention) | Community FAPs (Meshtastic, etc.). |
| **Raspberry Pi Pico (BadUSB host)** | 17, 18 (UART) or USB-passthrough | UART or USB-through | minimal | `kacperbartocha/pico-badusb` — Pico runs its own DS-alike runtime; Flipper is UI/power. |
| **Pwnagotchi-over-GPIO (Pi Zero W)** | 17, 18 (UART) | UART | any UART user | [Matt-London/pwnagotchi-flipper](https://github.com/Matt-London/pwnagotchi-flipper). |
| **ChameleonMini/Ultra** | *standalone USB/BLE* | n/a | n/a | Not GPIO-coupled; coexists as a peer tool. echoforge can drive both from the operator PC. |
| **Proxmark3 (RDV4/Easy)** | *standalone USB* | n/a | n/a | Same — peer tool. `client/proxmark3` speaks serial; echoforge can wrap it. |
| **FlipMods Combo (3-in-1)** | 1, 8-12, 15-18 | SPI + UART | all singletons | [CNX 2025-01-16](https://www.cnx-software.com/2025/01/16/flipmods-combo-is-a-3-in-1-flipper-zero-expansion-module-with-esp32-gps-and-cc1101-modules/) — ESP32 + GPS + CC1101 together. |
| **FEBERIS 3-in-1** | similar | SPI + UART | same | [mobile-hacker 2025-01-09](https://www.mobile-hacker.com/2025/01/09/boost-your-flipper-zero-with-feberis-3-in-1-subghz-nrf24-and-wifi-board/). |

### Conflict matrix

Two pairs of companions that *cannot co-exist on the same GPIO header*:
- **NRF24 + LoRa** share SPI; only one can hold CS.
- **ESP32 (UART) + Pwnagotchi-over-UART** share pins 17/18; pick one.

### echoforge recommendation

Ship *one* canonical config per attack class:
- **WiFi work** → ESP32 Marauder (Double Barrel 5G if available).
- **2.4 GHz HID work** → NRF24 module.
- **BLE-exploit work** → ESP32-S3 companion or host-side (BlueDucky on a Pi Zero W is fine; Flipper's native BT stack is too limited for CVE-2023-45866-style exploitation).
- **Firmware extraction** → native GPIO, no companion.
- **WiFi handshake collection during drive-by** → Pwnagotchi-over-UART.

echoforge hardware-plugin manifest declares which companion each action expects; the operator's `~/.echoforge/hardware.yaml` declares which companions are physically present today. Planner refuses actions whose hardware isn't present.

---

## 7. Gaps + differentiators

Things the Flipper community under-serves that echoforge can own:

1. **DuckyScript linter with live Flipper preview** (already flagged in team charter) — add Momentum-JS BadUSB support, which *nothing* currently lints. Ship as a echoforge subcommand and a VSCode extension.
2. **MITRE-ATT&CK-mapped engagement-report generator** — §4's table made concrete. Output: branded PDF + ATT&CK Navigator JSON layer. *This is the #1 differentiator.*
3. **Sub-GHz protocol diff tool** — capture A vs. capture B, show where they differ: bit count, preamble, TE timing, OOK vs FSK, sub-field interpretation. Accelerates unknown-protocol reverse engineering. No current tool.
4. **NFC dictionary orchestrator** — manages multiple keyfile dictionaries (`mfkey32`, `mfkey64`, `system_dict`, `user_dict`), deduplicates, tags by source, feeds the right dict to the right card type, learns keys across a campaign. Momentum has ad-hoc dict support but no orchestration.
5. **Campaign timeline stitcher** — ingest N Flipper `.log`s + operator notes + screenshots, output unified engagement timeline. Even with team engagements this is a huge manual job today.
6. **Spectrum-legality gate** — operator declares region at engagement start; echoforge refuses to TX on frequencies illegal in that region without a signed override. Critical for commercial defensibility. See §8.
7. **Auto-ROE preamble on every destructive action** — every "mutating" action (TX, emulate, inject, brute) requires an authenticated ROE document attached to the engagement. First action of each engagement is `engagement.bind_roe(scope.pdf)`.
8. **NFC-to-ATT&CK-technique auto-explainer** — read a captured card, classify it (badge/transit/hotel/gym/amiibo/toy/bank-card), pre-populate the MITRE mapping and risk framing. No tool does this today.
9. **Proxmark ↔ Flipper ↔ Chameleon Ultra orchestrator** — single echoforge session drives all three; each does what it's best at. No tool does this today.
10. **SubGHz protocol library contributions** — most new Sub-GHz decoders land in *Momentum* via FAPs. echoforge ships a "decoder-author" helper that takes N captures + a spec sheet and scaffolds a FAP.

---

## 8. Legal / licensing land mines

> echoforge is licensed red-team software. Operator is legally responsible. The sections below are research notes for what echoforge should **document and gate**, not legal advice.

### 8.1 Sub-GHz TX regulation by region

| Jurisdiction | Regulator | Salient rule | echoforge action |
|--------------|-----------|--------------|----------------|
| **US** | FCC (47 CFR Part 15) | §15.5: incidental radiators must not cause harmful interference; §15.231 permits periodic transmissions in specified bands for RKE/alarms. Intentional jamming is a federal crime ([Enforcement Advisory](https://www.fcc.gov/general/jammer-enforcement)). | Region-gate jamming actions behind legal-acknowledgement dialog. |
| **EU** | ETSI / Directive 2014/53/EU (RED) | 433.05-434.79 MHz SRD band; 868 MHz ISM; duty-cycle limits ~1-10% depending on sub-band. | Rate-limit TX to ≤1% duty cycle unless operator overrides with explicit justification log entry. |
| **UK** | Ofcom (post-Brexit, aligned with ETSI) | Same SRD bands; Ofcom IR 2030 interface requirement. Jamming illegal. | Same as EU. |
| **Germany** | BNetzA | Stricter TX power limits than EU minimum on some sub-bands; intentional jamming explicitly criminalized. | Same as EU, with a BNetzA-specific warning. |
| **Japan** | MIC / ARIB | 315 MHz and 426 MHz use different SRD bands than US/EU; 433 MHz TX *prohibited for consumer devices*. | Region-gate 433 MHz TX in JP locale. |
| **Australia** | ACMA | LIPD Class License; 433 MHz permitted at low power. | Same as EU. |

Flipper already implements region-based TX gating (`SubGhz region`); echoforge should **re-verify** on top rather than trust the Flipper setting, because operators sometimes run patched firmware that bypasses region lockout.

### 8.2 NFC / RFID emulation

- **US/EU:** No general prohibition on emulating tags. Emulating a tag you don't own credentials for is a CFAA / Computer Misuse Act issue (accessing a system without authorization), not an RF issue.
- **Payment cards (EMV):** Emulating an EMV card, even one you own, may violate payment-network rules (Visa / Mastercard operating rules); out of practical scope for echoforge and should be hard-gated.
- **Transit cards:** Public transit authorities have brought civil/criminal cases over cloning; region-dependent. Document.

### 8.3 Rolling-code research gray zone

Capturing rolling-code transmissions is passive reception — legal almost everywhere. *Replaying* a captured code to gain entry is CFAA / UK CMA 1990 / German §202a StGB (unauthorized access). echoforge's `subghz.rollback` action must display an ROE-scope confirmation and log consent before TX.

### 8.4 BLE-spam / DoS

- **US:** 47 USC §333 prohibits "willful or malicious interference" — BLE-spam can qualify.
- **EU:** RED + national unauthorized-access statutes.
- **Canada:** ISED rules similar to US.
BLE-spam actions in echoforge should default-disabled, unlock only with explicit `engagement.authorize_ble_spam()` + ROE check.

### 8.5 Wiretap / relay attacks

NFC relay that crosses the boundary between "test card" and "third-party card" is a wiretap-statute issue in most US states (e.g., NY Penal Law §250.05) and is explicitly criminalized in most EU member states. echoforge's `nfc.relay` must refuse to run without `--consent-file` pointing to a signed card-holder consent artifact.

### 8.6 License hygiene for bundled content

- **GPL-3.0 inheritance** (from V3SP3R upstream) — echoforge itself is GPL-3.0-or-later. Any bundled action runner must be GPL-3-compatible.
- **Proxmark3 client** — GPL-3.0, compatible.
- **Hak5 DuckyScript samples** — Hak5 licensing is unclear; echoforge should **link out**, not redistribute, pending a clarification from Hak5.
- **Momentum asset packs** — Momentum hosts them for redistribution; OK to link-fetch.
- **Hardnested tooling** (`mfoc-hardnested`) — GPL-3.0, compatible.

### 8.7 Operator accountability

Recommend: every echoforge engagement opens with a signed digital ROE envelope (operator identity + scope + timestamp) persisted to the audit log. The engagement cannot proceed without it. This is how Cobalt Strike teams handle it commercially and is the defensible posture.

---

## Appendix A — Primary sources quick index

### Academic papers cited
- Teuwen, P. *MIFARE Classic: exposing the static encrypted nonce variant* (2024) — [eprint/2024/1275](https://eprint.iacr.org/2024/1275.pdf)
- Bianchi/Brighente/Conti/Pavan. *SoK: Stealing Cars Since Remote Keyless Entry Introduction and How to Defend From It* (USENIX VehicleSec 2025) — [arXiv:2505.02713](https://arxiv.org/abs/2505.02713)
- Verdult/Garcia. *Gone in 360 Seconds: Hijacking with Hitag2* (USENIX Sec 2012) — [paper](https://www.usenix.org/system/files/conference/usenixsecurity12/sec12-final95.pdf)
- Antonioli/Tippenhauer. *KNOB — Key Negotiation Downgrade Attacks on BT/BLE* — [francozappa.github.io](https://francozappa.github.io/publication/knob-ble/paper.pdf)
- Wu et al. *BLESA: Spoofing Attacks against Reconnections in BLE* (USENIX WOOT 2020) — [paper](https://www.usenix.org/system/files/woot20-paper-wu-updated.pdf)
- Sacchetti et al. *BLERP: BLE Re-Pairing Attacks and Defenses* (NDSS 2026) — [paper](https://www.ndss-symposium.org/wp-content/uploads/2026-f121-paper.pdf)
- Synacktiv. *0-click RCE on Tesla Model 3 through TPMS Sensors* (Hexacon 2024) — [slides](https://www.synacktiv.com/sites/default/files/2024-10/hexacon_0_click_rce_on_tesla_model_3_through_tpms_sensors_light.pdf)
- Csikor et al. *RollBack: A New Time-Agnostic Replay Attack Against the Automotive Remote Keyless Entry Systems* (ACM TCPS 2024) — [paper](https://dl.acm.org/doi/10.1145/3627827)
- Deng et al. *HackSynth: LLM Agent and Evaluation Framework for Autonomous Penetration Testing* — [arXiv:2412.01778](https://arxiv.org/abs/2412.01778)

### CVEs cited
- [CVE-2023-42941](https://nvd.nist.gov/vuln/detail/CVE-2023-42941) — Apple Continuity iOS 17 freeze
- [CVE-2023-45866](https://nvd.nist.gov/vuln/detail/CVE-2023-45866) — BT HID injection (BlueDucky)
- [CVE-2024-21306](https://nvd.nist.gov/vuln/detail/CVE-2024-21306) — Microsoft BT driver spoof
- [CVE-2024-29941](https://github.com/advisories/GHSA-wh7x-ww7q-h9hp) — ICT Protege MIFARE/DESFire key leak
- [CVE-2020-15802](https://nvd.nist.gov/vuln/detail/CVE-2020-15802) — BLURtooth CTKD
- [CVE-2025-2082](https://undercodenews.com/tesla-model-3-hacked-via-tire-sensors-inside-the-cve-2025-2082-vulnerability/) — Tesla TPMS OOB write

### Frameworks referenced
- Sliver — [github.com/BishopFox/sliver](https://github.com/BishopFox/sliver)
- Mythic — [github.com/its-a-feature/Mythic](https://github.com/its-a-feature/Mythic), [docs](https://docs.mythic-c2.net/)
- Havoc — [github.com/HavocFramework/Havoc](https://github.com/HavocFramework/Havoc), [docs](https://havocframework.com/docs/)
- Caldera — [github.com/mitre/caldera](https://github.com/mitre/caldera), [caldera.mitre.org](https://caldera.mitre.org/)
- Atomic Red Team — [github.com/redcanaryco/atomic-red-team](https://github.com/redcanaryco/atomic-red-team)

### Firmware / platforms
- Momentum Firmware — [github.com/Next-Flip/Momentum-Firmware](https://github.com/Next-Flip/Momentum-Firmware), [momentum-fw.dev](https://momentum-fw.dev/)
- Unleashed — [github.com/DarkFlippers/unleashed-firmware](https://github.com/DarkFlippers/unleashed-firmware)
- Xtreme (discontinued Nov 2024) — superseded by Momentum
- Flipper Zero stock firmware — [github.com/flipperdevices/flipperzero-firmware](https://github.com/flipperdevices/flipperzero-firmware)
- Proxmark3 RRG — [github.com/RfidResearchGroup/proxmark3](https://github.com/RfidResearchGroup/proxmark3)

---

## Appendix B — Suggested next-phase work

Phase 7 priorities based on this research:

1. **Implement POCs #1-5** from §2 as first-class echoforge actions with safety gating.
2. **Build the engagement-report generator** (§7 item 2) — the single biggest differentiator.
3. **Formalize the `ActionRequest.mitre_id` schema** and backfill all existing actions.
4. **Region / legality gate** (§8) — operator sets region at engagement start; planner refuses illegal actions.
5. **Companion-hardware manifest** (§6) — `~/.echoforge/hardware.yaml` + planner integration.
6. **DuckyScript + Momentum-JS BadUSB linter** (§7 item 1).
7. **Sub-GHz protocol diff tool** (§7 item 3).
8. **Signed-ROE envelope** (§8.7) as the first-class engagement primitive.

Phase 8+:
- Multi-operator gRPC (§3.2 lesson 1).
- Modular payload-type plugins à la Mythic (§3.2 lesson 2).
- ICS / OT ATT&CK extension (§4 closing note).
