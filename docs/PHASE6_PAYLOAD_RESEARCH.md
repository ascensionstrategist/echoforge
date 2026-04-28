# Phase 6 — Payload Research for 3CH0F0RG3

Research date: 2026-04-22
Target firmware baseline: Momentum mntm-012 (Next-Flip)
Scope: identify Flipper Zero payload / asset / tool repositories BEYOND the classic
baseline (UberGuidoZ/Flipper, I-Am-Jakoby/Flipper-Zero-BadUSB, Lucaslhm/Flipper-IRDB,
hak5/usbrubberducky-payloads, djsime1/awesome-flipperzero) — prioritising repos that
were actively maintained through 2025 and into 2026.

All metadata (stars, forks, last-push, license, size) was pulled live from the GitHub
REST API (`api.github.com/repos/<owner>/<repo>`) on 2026-04-22. "Size" is the GitHub
API `size` field (git tree size in KB); this approximates working-copy weight but can
be inflated by LFS / binary blobs.

Legend:
- ACTIVE = commits within the last 6 months (≥2025-10)
- WARM = last push within 12 months (≥2025-04)
- STALE = last push >12 months ago
- DEAD = no push in 2+ years

License shorthand: "None specified" on GitHub means All-Rights-Reserved by default
under US copyright law — treat as risky for redistribution unless the repo's README
explicitly grants permission, or contents are community-submitted under a commonly-
implied "share freely" norm (typical for .sub / .ir files).

---

## Executive summary — top 5 to ship with echoforge

Ranked by: recency + content breadth + license safety + Momentum fit.

1. **Next-Flip/Asset-Packs** — Momentum's own asset-pack bundle. 2026-01-01 push,
   ~102 MB, official Momentum project → zero compatibility risk, direct fit for a
   Momentum-targeted tool. Unlicensed metadata-wise but Momentum's own distribution
   channel explicitly publishes them for redistribution.
2. **Lucaslhm/Flipper-IRDB** — you already know it, but it is the *only* IR DB
   worth shipping as default. CC0-1.0 license (public domain), 41 MB, 4,043 stars,
   last push 2026-04-12. Every other IR repo is strictly a subset.
3. **Zero-Sploit/FlipperZero-Subghz-DB** — the biggest single SubGHz capture pack
   on GitHub: 13,717 .sub files, 149 MB, 1,215 stars, pushed 2025-04-22. No explicit
   license is a yellow flag — mitigate by shipping as optional downloadable pack,
   not bundled. Still the best "community captures" dataset available.
4. **bst04/payloads_flipperZero** — 374 stars, GPL-3.0 (redistribution safe),
   pushed 2026-03-16. A cleanly-structured modern DuckyScript 1.0 payload library
   that is MUCH smaller and easier to audit than Jakoby's or FalsePhilosopher's.
   GPL means 3CH0F0RG3 bundling it requires 3CH0F0RG3 shipping source of any
   modifications to those scripts — a tolerable constraint for a hobby project.
5. **jamisonderek/flipper-zero-tutorials** — MIT-licensed, 1,398 stars, pushed
   2026-03-31. Not a payload pack per se, but the single best *reference / example
   code* repo for Momentum-specific JavaScript BadUSB patterns (Momentum JS is
   unique and no other payload repo uses it). Ship the `/badusb/` and `/js/`
   directories as a "learn-by-example" tab in echoforge.

Honorable mentions for secondary / optional downloads: **Kuronons/FZ_graphics**
(CC0 dolphin animations, 546 stars, 2026-03-13), **wetox-team/flipperzero-goodies**
(MIT, intercom key dumps, 2025-10-17), **DarkFlippers/Multi_Fuzzer** (MIT, 125 kHz
RFID fuzzer data, 2025-10-24).

Red-flag avoid list: **UberGuidoZ/Flipper** (2.1 GB — too big to bundle, and it is
itself a mirror of dozens of upstreams; echoforge should link out, not redistribute),
**MuddledBox/FlipperZeroSub-GHz** (DEAD since 2022), **ADolbyB/flipper-zero-files**
(453 MB, last push 2024-06; contents largely duplicated from Lucaslhm+UberGuidoZ).

---

## 1. Advanced BadUSB / DuckyScript payloads

### Primary picks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [FalsePhilosopher/badusb](https://github.com/FalsePhilosopher/badusb) | 1,854 | 265 | 2026-04-01 | "Other" (custom — check LICENSE) | 59 MB | ACTIVE |
| [bst04/payloads_flipperZero](https://github.com/bst04/payloads_flipperZero) | 374 | 31 | 2026-03-16 | GPL-3.0 | 2.5 MB | ACTIVE |
| [Zarcolio/flipperzero](https://github.com/Zarcolio/flipperzero) | 476 | 30 | 2025-05-29 | GPL-3.0 | 625 KB | WARM |
| [UndedInside/DuckyScriptPayloads](https://github.com/UndedInside/DuckyScriptPayloads) | 339 | 25 | 2025-06-26 | None specified | 25 KB | WARM |
| [CharlesTheGreat77/BADUSB](https://github.com/CharlesTheGreat77/BADUSB) | 287 | 29 | 2025-02-22 | None specified | 326 KB | WARM |
| [SoggyCow/FlipperZero-BadUSB-Payloads](https://github.com/SoggyCow/FlipperZero-BadUSB-Payloads) | 23 | 3 | 2026-02-23 | None specified | 477 KB | ACTIVE |
| [FroggMaster/FlipperZero](https://github.com/FroggMaster/FlipperZero) | 1,161 | 62 | 2025-09-30 | GPL-3.0 | 88 KB | WARM |
| [hak5/usbrubberducky-payloads](https://github.com/hak5/usbrubberducky-payloads) | 5,677 | 1,637 | 2026-04-10 | None specified | 58 MB | ACTIVE (baseline — known) |
| [I-Am-Jakoby/Flipper-Zero-BadUSB](https://github.com/I-Am-Jakoby/Flipper-Zero-BadUSB) | 6,778 | 854 | 2024-06-15 | None specified | 26 KB | STALE (baseline — known) |

### Analysis

- **FalsePhilosopher/badusb** is the current heavyweight replacement for Jakoby's
  repo, which stopped in mid-2024. Heavy PowerShell orientation. 59 MB hints at
  bundled binaries/executables — audit before shipping.
- **bst04/payloads_flipperZero** is the best "clean slate" modern library: small,
  auditable, GPL-3.0 (compatible with 3CH0F0RG3 if echoforge is willing to publish
  any patches to those scripts). Active monthly commits through 2026.
- **Zarcolio/flipperzero** includes `Convert-Ps2Ducky.ps1` — a PowerShell→Ducky
  converter, which doubles as a useful echoforge-side tool.
- **SoggyCow** is small but niche — locked-phone brute-forcing + Bluetooth payloads;
  unusual angle.
- None of these repos specifically advertise Momentum-only DuckyScript extensions.
  For Momentum-specific constructs (`WAIT_FOR_BUTTON_PRESS`, `SYSRQ`, custom USB
  IDs, ALT+Numpad) the canonical reference is the firmware itself — see
  `flipperdevices/flipperzero-firmware/documentation/file_formats/BadUsbScriptFormat.md`.

### Not picked / red flags

- `laasso/FlipperZero` — 0 stars, abandoned May 2024, 72 MB. Just a personal dump.
- `nocomp/Flipper_Zero_Badusb_hack5_payloads` — referenced only via DeepWiki mirror;
  upstream appears to be a stale Hak5 re-upload.

---

## 2. SubGHz libraries

### Primary picks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [Zero-Sploit/FlipperZero-Subghz-DB](https://github.com/Zero-Sploit/FlipperZero-Subghz-DB) | 1,215 | 125 | 2025-04-22 | None specified | 149 MB | WARM |
| [tobiabocchi/flipperzero-bruteforce](https://github.com/tobiabocchi/flipperzero-bruteforce) | 2,444 | 162 | 2024-07-12 | None specified | 1.9 MB | STALE |
| [DarkFlippers/flipperzero-subbrute](https://github.com/DarkFlippers/flipperzero-subbrute) | 868 | 68 | 2026-01-05 | MIT | 574 KB | ACTIVE |
| [magikh0e/FlipperZero_Stuff](https://github.com/magikh0e/FlipperZero_Stuff) | 434 | 21 | 2025-02-10 | None specified | 95 KB | WARM |
| [MuddledBox/FlipperZeroSub-GHz](https://github.com/MuddledBox/FlipperZeroSub-GHz) | 1,433 | 109 | 2022-12-03 | None specified | 200 KB | DEAD |
| [alecigne/flipperzero-subghz-bruteforce](https://github.com/alecigne/flipperzero-subghz-bruteforce) | 19 | 3 | 2024-07-13 | None specified | 0 KB | STALE |

### Analysis

- **Zero-Sploit/FlipperZero-Subghz-DB** is the single largest community .sub
  archive on GitHub: ~13.7k files across 721 folders, including region-specific
  captures (EU 433/868, US 315/433, some 915 AU). README claims contents are
  aggregated from multiple public sources. NO license is the one clear concern —
  treat as optional download, not bundled default, and surface provenance to
  the user.
- **DarkFlippers/flipperzero-subbrute** is actively maintained (last push Jan 2026)
  and MIT-licensed — ship as core bruteforce engine. CAME 12-bit 433 MHz is default
  protocol; extensible.
- **tobiabocchi/flipperzero-bruteforce** is the widely-cited de Bruijn generator
  (Python) — stale but functionally complete. Generates bruteforce `.sub` files in
  split factors of 1/2/4/8/16/32 per protocol. Bundle the pre-generated output,
  not the script, since the algorithm is done.
- **magikh0e/FlipperZero_Stuff** is small but high signal: curated personal SubGHz
  + IR + remote dumps. Good for supplementing Zero-Sploit.
- **MuddledBox** is the OG 2022 SubGHz library — superseded by Zero-Sploit and
  UberGuidoZ. Don't use.

### Rolling-code research

Public rolling-code *captures* (not crackers) appear mostly inside the custom
firmware trees themselves (Unleashed / Xtreme / RogueMaster / Momentum) as
built-in decoders for FAAC SLH, BFT Mitto, Keeloq, Hörmann HSM, etc. There is
**no standalone GitHub repo** of rolling-code SubGHz captures that looks safer
than scraping DarkFlippers/unleashed-firmware's test vectors. (Rolling-code
cracking itself is legally sensitive and most functional tools circulate via
private channels.)

---

## 3. IR databases

### Primary picks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [Lucaslhm/Flipper-IRDB](https://github.com/Lucaslhm/Flipper-IRDB) | 4,043 | 1,335 | 2026-04-12 | CC0-1.0 | 41 MB | ACTIVE (baseline — known, but best-in-class) |
| [flipperdevices/IRDB](https://github.com/flipperdevices/IRDB) | 65 | 12 | 2025-07-15 | MIT | 17 MB | WARM (OFFICIAL — has device-catalog metadata) |
| [The-Flipper-Files/Infrared](https://github.com/The-Flipper-Files/Infrared) | 21 | 0 | 2023-11-10 | MIT | 121 KB | DEAD |
| [sosbgit/Flipper-Zero-IRDB](https://github.com/sosbgit/Flipper-Zero-IRDB) | 2 | 1 | 2023-01-07 | None specified | 26 MB | DEAD |

### Analysis

- **Lucaslhm/Flipper-IRDB** remains the apex IR repo. CC0 means echoforge can bundle
  freely. 1,335 forks → massive community contribution pipeline. 2025/2026 TVs,
  ACs, projectors, and smart-home IR remotes all land here within weeks of
  release. No competitor comes close.
- **flipperdevices/IRDB** is the *official* Flipper Devices repo and notably
  includes device-catalog metadata (brand/model → .ir mapping) that Lucaslhm's
  does not. Smaller content but better structured. SHIP BOTH: Lucaslhm as
  primary content, flipperdevices/IRDB as catalog index layer.
- All other candidates are proper subsets of or staler than the above.

---

## 4. NFC / RFID / iButton

### Primary picks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [noproto/xero-firmware](https://github.com/noproto/xero-firmware) | 131 | 10 | 2026-02-14 | GPL-3.0 | 73 MB | ACTIVE |
| [noproto/FlipperMfkey](https://github.com/noproto/FlipperMfkey) | 298 | 14 | 2024-07-13 | GPL-3.0 | 245 KB | STALE (but canonical) |
| [wetox-team/flipperzero-goodies](https://github.com/wetox-team/flipperzero-goodies) | 1,371 | 93 | 2025-10-17 | MIT | 146 KB | ACTIVE |
| [DarkFlippers/Multi_Fuzzer](https://github.com/DarkFlippers/Multi_Fuzzer) | 346 | 26 | 2025-10-24 | MIT | 109 KB | ACTIVE |
| [Clawzman/Flipper_ListEM](https://github.com/Clawzman/Flipper_ListEM) | 9 | 0 | 2026-03-30 | MIT | 786 KB | ACTIVE |
| [evillero/F0_EM4100_generator](https://github.com/evillero/F0_EM4100_generator) | 32 | 0 | 2025-01-30 | GPL-3.0 | 42 KB | WARM |
| [Leptopt1los/ibutton_converter](https://github.com/Leptopt1los/ibutton_converter) | 8 | 2 | 2025-05-07 | GPL-3.0 | 55 KB | WARM |
| [flipperdevices/flipperzero-nfc-tools](https://github.com/flipperdevices/flipperzero-nfc-tools) | — | — | — | — | — | (reference — Mfkey32 impl) |

### Analysis

- **noproto/xero-firmware** is the single biggest 2025-era leap in Flipper
  NFC capability. Includes MIFARE Classic accelerated dictionary attack,
  nested attack, static-nested attack, *static-encrypted* (which is new research,
  covers the MIFARE Classic EV1/Plus backdoor work), and Mfkey 4.1 with
  Mfkey32. Not a payload pack per se, but echoforge should ship the dictionary
  files from its `assets/dicts/` tree.
- **noproto/FlipperMfkey** is the canonical Mfkey32 port. Cracked nonces auto-
  added to user dict — integrate as a workflow in echoforge, ship binary.
- **wetox-team/flipperzero-goodies** is the apartment / intercom key research
  repo: Russian Metakom/Cyfral/Vizit key dumps, building intercom capture
  scripts, iButton sample vectors. MIT-licensed, actively maintained.
- **DarkFlippers/Multi_Fuzzer** — 125 kHz RFID reader fuzzer: EM4100, HIDProx,
  PAC/Stanley, H10301, Indala26 etc. Data + .fap source. Ideal RFID
  companion to subbrute for SubGHz.
- **Clawzman/Flipper_ListEM** and **Clawzman/flipper_fuzzgen** — RFID/NFC/iButton
  ID list generators with broad protocol coverage. Active in March 2026.
- **evillero/F0_EM4100_generator** — simple Python random EM4100 generator for
  fuzzer input.

No standalone "giant NFC dump" repo was found in the class of Zero-Sploit's
SubGHz DB; NFC dumps are generally uploaded by individuals per-card and live
in UberGuidoZ's playground at `UberGuidoZ/Flipper/tree/main/NFC/`.

---

## 5. Asset packs + GUI themes

### Primary picks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [Next-Flip/Asset-Packs](https://github.com/Next-Flip/Asset-Packs) | 142 | 16 | 2026-01-01 | None specified | 102 MB | ACTIVE (OFFICIAL MOMENTUM) |
| [Kuronons/FZ_graphics](https://github.com/Kuronons/FZ_graphics) | 546 | 33 | 2026-03-13 | CC0-1.0 | 6 MB | ACTIVE |
| [ablaran/Graphics4FZ](https://github.com/ablaran/Graphics4FZ) | 8 | 0 | 2025-12-13 | "Other" | 3.7 MB | ACTIVE |
| [HexxedBitHeadz/FlipperZeroWallpaper](https://github.com/HexxedBitHeadz/FlipperZeroWallpaper) | 65 | 4 | 2026-03-11 | None specified | 64 MB | ACTIVE |
| [cyberartemio/flipper-pirates-asset-pack](https://github.com/cyberartemio/flipper-pirates-asset-pack) | 34 | 2 | 2025-01-26 | GPL-3.0 | 46 MB | WARM |
| [hooker01/Flipper-Zero-Asset-Pack-Generator](https://github.com/hooker01/Flipper-Zero-Asset-Pack-Generator) | 10 | 0 | 2025-10-19 | None specified | 107 KB | ACTIVE |
| [IoriKesso/Flipper-Zero-Anime-Wallpapers](https://github.com/IoriKesso/Flipper-Zero-Anime-Wallpapers) | 68 | 2 | 2023-11-10 | None specified | 18.6 MB | DEAD |

### Analysis

- **Next-Flip/Asset-Packs** is the *killer feature* for a Momentum-targeted
  tool. It's Momentum's own asset pack bundle, published as part of their
  distribution chain (served via up.momentum-fw.dev/asset-packs). Ship it
  directly, no license concern — Momentum already redistributes it publicly.
- **Kuronons/FZ_graphics** — CC0-licensed custom animations / profile pics /
  passports. 546 stars, freshly pushed. Highest-quality individual creator pack.
- **ablaran/Graphics4FZ** is specifically optimised "for Momentum" per the
  README — recent (Dec 2025) but only 8 stars. Worth vetting.
- **hooker01/Flipper-Zero-Asset-Pack-Generator** — Python GUI tool that
  converts GIFs → Flipper asset packs. Perfect utility for a echoforge-side
  "Import your own GIF" feature. Integrate as a subprocess.
- Avoid IoriKesso's anime wallpapers (dead 2+ years; unlicensed).

---

## 6. Meta-tooling (linters / validators / converters / generators)

### Primary picks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [sacriphanius/Flipper-Zero-Ducky-Script-Generator](https://github.com/sacriphanius/Flipper-Zero-Ducky-Script-Generator) | 16 | 1 | 2026-02-05 | None specified | 48 KB | ACTIVE (on-device editor .fap) |
| [grugnoymeme/flipperducky-badUSB-payload-generator](https://github.com/grugnoymeme/flipperducky-badUSB-payload-generator) | 81 | 4 | 2023-07-29 | MIT | 25 KB | DEAD (but useful web-GUI) |
| [hooker01/Flipper-Zero-Asset-Pack-Generator](https://github.com/hooker01/Flipper-Zero-Asset-Pack-Generator) | 10 | 0 | 2025-10-19 | None specified | 107 KB | ACTIVE (asset GUI) |
| [Leptopt1los/ibutton_converter](https://github.com/Leptopt1los/ibutton_converter) | 8 | 2 | 2025-05-07 | GPL-3.0 | 55 KB | WARM (Metakom/Cyfral → Dallas) |
| [Zarcolio/flipperzero](https://github.com/Zarcolio/flipperzero) — Convert-Ps2Ducky.ps1 | 476 | 30 | 2025-05-29 | GPL-3.0 | 625 KB | WARM (.ps1 → ducky) |
| [alecigne/flipperzero-subghz-bruteforce](https://github.com/alecigne/flipperzero-subghz-bruteforce) | 19 | 3 | 2024-07-13 | None specified | 0 KB | STALE (Common Lisp .sub generator) |
| [tobiabocchi/flipperzero-bruteforce](https://github.com/tobiabocchi/flipperzero-bruteforce) | 2,444 | 162 | 2024-07-12 | None specified | 1.9 MB | STALE (Python .sub generator) |

### Analysis

**No dedicated DuckyScript *linter* exists** for the Flipper dialect as of this
research. This is a real gap echoforge could fill. The Flipper BadUSB extended
syntax (`WAIT_FOR_BUTTON_PRESS`, `SYSRQ`, `ALT+Numpad`, custom USB IDs, `ID`
directive) diverges from Hak5's DuckyScript 1.0 and 3.0 — a simple
parse-and-validate tool that diffs against
`flipperdevices/flipperzero-firmware/documentation/file_formats/BadUsbScriptFormat.md`
would be a echoforge differentiator.

- **DuckyGen (sacriphanius/Flipper-Zero-Ducky-Script-Generator)** — on-device
  .fap editor, not a PC-side tool. Still valuable to surface / link inside
  echoforge, and the repo's template library can be mined for seed payloads.
- **grugnoymeme/flipperducky-badUSB-payload-generator** — web-GUI that
  generates payload .txt from visual editing. MIT-licensed, but dead. Could
  be forked into echoforge's UI.
- `msfvenom` Metasploit PR #17279 added Flipper-compatible ducky-script format
  output in 2022 — check that rapid7/metasploit-framework supports a
  `flipper` format variant and plumb it in.

### Converters still missing from the ecosystem (echoforge could build):
- Hak5 DuckyScript 3.0 → Flipper DuckyScript downgrader
- `.sub` → raw protocol decoder (3CH0F0RG3 could leverage existing firmware C
  code via a Python wrapper)
- `.nfc` dump formatter (cross-firmware — Momentum vs OFW have subtle
  differences in MIFARE Ultralight C fields)

---

## 7. Alternative-firmware payload bundles

### Primary picks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [Next-Flip/Momentum-Firmware](https://github.com/Next-Flip/Momentum-Firmware) | 8,380 | 504 | 2026-04-19 | GPL-3.0 | 583 MB | ACTIVE |
| [DarkFlippers/unleashed-firmware](https://github.com/DarkFlippers/unleashed-firmware) | 21,444 | 1,860 | 2026-04-21 | GPL-3.0 | 100 MB | ACTIVE |
| [RogueMaster/flipperzero-firmware-wPlugins](https://github.com/RogueMaster/flipperzero-firmware-wPlugins) | 6,188 | 603 | 2026-04-22 | GPL-3.0 | 2.4 GB | ACTIVE (massive) |
| [Flipper-XFW/Xtreme-Firmware](https://github.com/Flipper-XFW/Xtreme-Firmware) | 9,885 | 714 | 2024-11-19 | GPL-3.0 | 594 MB | WARM (superseded by Momentum) |
| [BruceDevices/firmware](https://github.com/BruceDevices/firmware) | 5,397 | 1,826 | 2026-04-16 | AGPL-3.0 | 230 MB | ACTIVE (ESP32, Flipper-compatible CLI) |
| [jblanked/FlipperHTTP](https://github.com/jblanked/FlipperHTTP) | 770 | 56 | 2026-04-07 | MIT | 74 MB | ACTIVE (WiFi dev board enabler) |

### Analysis

Since echoforge targets Momentum directly, echoforge should:

- **Treat Momentum as the canonical firmware** — its `applications/` tree, `assets/`
  tree, and `documentation/file_formats/` directory are the authoritative
  references.
- **Mine RogueMaster's `payloads/` tree for bulk content** — RogueMaster ships
  with a huge curated .sub / .ir / BadUSB payload set preinstalled in the
  firmware SD image. At 2.4 GB the repo is too large to clone, but you can
  pull individual directories via GitHub's REST API (tree + blobs) and
  redistribute under GPL-3.0.
- **BruceDevices/firmware** is an ESP32 counterpart firmware whose CLI is
  intentionally Flipper-compatible — cross-pollination source for SubGHz /
  IR / BadUSB command syntax. AGPL-3.0 is viral — only include if echoforge
  itself is willing to AGPL anything that embeds it. Safer to read as
  reference, not as code to copy.
- **jblanked/FlipperHTTP** unlocks WiFi dev board workflows on Flipper; if
  echoforge supports the board, integrate FlipperHTTP's API.
- **Xtreme-Firmware** is WARM (last push Nov 2024). Momentum is Xtreme's
  continuation — no reason to pull from Xtreme unless backfilling historical
  payloads.

---

## 8. Curated-list / awesome-list checks

| Repo | Stars | Forks | Last push | License | Size | Status |
|------|-------|-------|-----------|---------|------|--------|
| [djsime1/awesome-flipperzero](https://github.com/djsime1/awesome-flipperzero) | 23,232 | 1,008 | 2024-09-27 | CC0-1.0 | 248 KB | WARM (baseline, getting stale) |
| [123fzero/flipper-zero-awesome](https://github.com/123fzero/flipper-zero-awesome) | 7 | 1 | 2026-04-22 | None specified | 981 KB | ACTIVE (tiny, but most up-to-date) |
| [RogueMaster/awesome-flipperzero-withModules](https://github.com/RogueMaster/awesome-flipperzero-withModules) | — | — | — | — | — | (RogueMaster-specific curation) |

**Notable:** `djsime1/awesome-flipperzero` — the community's default index — has
**not been pushed since Sep 2024**. That is THE gap in the ecosystem right now.
If you are building echoforge and want one high-leverage side-quest, it is to fork
djsime1 and produce a 2026-refreshed index. `123fzero/flipper-zero-awesome` is
attempting exactly this but has only 7 stars.

---

## 9. Non-GitHub mirrors surveyed

- **git.hackliberty.org/Awesome-Mirrors/awesome-flipperzero** — Forgejo mirror
  of djsime1, no independent content.
- **sourceforge.net/projects/flipper-zero-badusb.mirror/** — mirror of
  FalsePhilosopher's badusb repo, not an independent source.
- **gitlab.com** — several small personal Flipper repos exist but none with
  >50 stars or notable differentiation from the GitHub pool.
- **Codeberg / Gitea instances** — no significant Flipper-specific payload
  repositories found. The Flipper community is overwhelmingly GitHub-native.

---

## 10. Red flags / avoid list

| Repo | Reason |
|------|--------|
| `Lonebear69/https-github.com-UberGuidoZ-RogueMaster-FlipperZero` | Pointless mirror of UberGuidoZ's RogueMaster directory; unmaintained |
| `sasiplavnik/Flipper-IRDB` | Irplus conversion dump, no license, no attribution, abandoned |
| `merlinepedra/awesome-flipperzero` | Unattributed fork of djsime1, dead |
| `ImNoahDev/Flipper-IRDB` | Fork of Lucaslhm with outdated contents |
| `MCneverfly/flipperzero-firmware-wPlugins`, `xqqiww/flipperzero-firmware-wPlugins` | Unattributed forks of RogueMaster |
| `tehrabbitt/Flipper-Xtreme`, `yocvito/Flipper-Xtreme` | Forks of Xtreme with identical READMEs, no added value |
| `The-Flipper-Files/RogueMaster` | Static snapshot of RogueMaster circa 2023 |

**General pattern:** the Flipper repo ecosystem is *heavy* with re-uploads and
silent forks of the top-5 repos. When a candidate repo's star count is
<100 and its README matches another repo's README, assume it's a redundant
fork.

---

## 11. Licensing strategy for echoforge bundling

Grouped for quick triage:

- **Can bundle with zero concern (permissive / public domain):**
  Lucaslhm/Flipper-IRDB (CC0), Kuronons/FZ_graphics (CC0),
  flipperdevices/IRDB (MIT), DarkFlippers/flipperzero-subbrute (MIT),
  wetox-team/flipperzero-goodies (MIT), DarkFlippers/Multi_Fuzzer (MIT),
  Clawzman/Flipper_ListEM (MIT), jblanked/FlipperHTTP (MIT).

- **Can bundle if echoforge is GPL-compatible (it probably is; Flipper FW itself
  is GPL):** bst04/payloads_flipperZero (GPL-3.0), Zarcolio/flipperzero (GPL-3.0),
  noproto/FlipperMfkey (GPL-3.0), noproto/xero-firmware (GPL-3.0),
  FroggMaster/FlipperZero (GPL-3.0), cyberartemio/flipper-pirates-asset-pack
  (GPL-3.0), evillero/F0_EM4100_generator (GPL-3.0),
  Leptopt1los/ibutton_converter (GPL-3.0), Momentum, Unleashed, RogueMaster,
  Xtreme (all GPL-3.0).

- **AGPL-3.0 — avoid embedding, OK to reference:** BruceDevices/firmware.

- **"Other" / custom license — read LICENSE first:** FalsePhilosopher/badusb,
  Graphics4FZ.

- **None specified (legally ALL-RIGHTS-RESERVED) — ship as optional
  downloadable, not bundled default; attribute source:**
  Zero-Sploit/FlipperZero-Subghz-DB, hak5/usbrubberducky-payloads,
  I-Am-Jakoby/Flipper-Zero-BadUSB, Next-Flip/Asset-Packs (*Momentum publishes
  these publicly on their own CDN, so redistribution is intended*),
  UndedInside/DuckyScriptPayloads, CharlesTheGreat77/BADUSB,
  SoggyCow/FlipperZero-BadUSB-Payloads, magikh0e/FlipperZero_Stuff,
  MuddledBox/FlipperZeroSub-GHz, tobiabocchi/flipperzero-bruteforce,
  HexxedBitHeadz/FlipperZeroWallpaper,
  sacriphanius/Flipper-Zero-Ducky-Script-Generator,
  hooker01/Flipper-Zero-Asset-Pack-Generator, 123fzero/flipper-zero-awesome.

The pragmatic echoforge strategy: **bundle** the permissive/GPL content and use
the "None specified" sources as **on-demand community-pack downloads** that
the user opts into at first launch. Each download should show source
attribution and the (absent) license, so the responsibility/informed-consent
sits with the user — mirroring how tools like Fing or Kali's package manager
handle community-repo content.

---

## 12. Discovery gaps / unfinished threads

Worth chasing in a follow-up pass:

1. **2025-2026 rolling-code research repos** — likely exist in security-research
   GitHub orgs (e.g. GRSECgit, F-Secure, Trail of Bits) but none surfaced in
   these searches. Query "keeloq reverse engineering 2025" or "rolling code
   attack public captures" next round.
2. **Windows 11 24H2 / macOS Sonoma / macOS Sequoia–specific BadUSB payloads** —
   no dedicated repo found with explicit 2024-H2 OS targeting. This is a real
   gap: the Flipper community's BadUSB corpus is overwhelmingly Windows-10-era.
3. **Momentum-specific JavaScript payload library** — no payload-focused JS
   repo exists outside jamisonderek's tutorials wiki. Another echoforge
   build-it-yourself opportunity.
4. **Payload linter / validator** — confirmed absent. Build opportunity.
5. **5G / WiFi-dev-board payloads** — FlipperHTTP + the new ESP32-C5 boards
   (HoneyHoneyTeam/ESP32-Marauder-5G-Apex-5-Module) are opening a new payload
   category that nobody has aggregated yet.

---

## Appendix A — API metadata capture log

All stars/forks/pushed_at/license/size numbers in this document were pulled via
`GET https://api.github.com/repos/<owner>/<repo>` on 2026-04-22. Where only
README-level info was available (because the API call wasn't run for that repo),
it is noted with `—` in the table. Recommend re-running the same API call every
~30 days while echoforge's payload library is in active development, since the
Flipper community's repo churn is high.
