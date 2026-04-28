# echoforge-flipper-mastery

A Claude Code plugin that gives Claude first-party Flipper Zero protocol expertise — DuckyScript authoring, Sub-GHz radio, Infrared, NFC/RFID/iButton, hardware-debug interfaces, and defensive payload analysis. Writes, reads, and reasons about `.txt`, `.sub`, `.ir`, `.nfc`, `.rfid`, and `.ibtn` files with protocol-exact accuracy grounded in Flipper-firmware source, academic papers, and ISO standards — no more hallucinated pin numbers or wrong bit layouts.

## Installation

Assuming this plugin directory is committed at the root of an accessible git repository (or locally as a marketplace source):

```
# Add the repo (or local directory) as a marketplace
claude plugin marketplace add <path-or-url>

# Install
claude plugin install echoforge-flipper-mastery
```

Each of the six sub-skills activates automatically when Claude sees a matching trigger — no per-skill enable required.

## Sub-skills

| Skill | One-line purpose | Activates when |
|-------|------------------|----------------|
| **echoforge-duckyscript** | Author, debug, and annotate BadUSB `.txt` payloads | User writes, reads, or validates DuckyScript; mentions Flipper BadUSB |
| **echoforge-subghz** | Read, interpret, retune Flipper `.sub` captures | User shares a `.sub`, asks about KeeLoq / Princeton / CAME / Somfy / Security+ / 433 MHz / 915 MHz |
| **echoforge-ir** | Decode, build `.ir` signals across NEC / RC5 / RC6 / Sony SIRC / Samsung32 / Kaseikyo / Pronto Hex | User shares an `.ir`, builds a universal remote, asks why a TV won't respond |
| **echoforge-nfc-rfid** | NFC at 13.56 MHz, 125 kHz RFID LF, and iButton / 1-Wire | User shares `.nfc` / `.rfid` / `.ibtn`, asks about MIFARE Classic / Ultralight / DESFire / HID Prox / iClass / EM4100 |
| **echoforge-hardware-debug** | JTAG / SWD / UART / I2C / SPI interfaces on PCBs | User asks about debug headers, pin identification, baud detection, SPI flash dumping |
| **echoforge-payload-defender** | Analytical walkthrough of unknown payloads (read, explain — do not judge) | User shares a payload they did not write and asks "what does this do?" |

## Why this plugin exists

Per `docs/PHASE6_SKILL_RESEARCH.md` (the internal research pass that surveyed ~20 security/CTF skill repos and 5 marketplaces in April 2026), no existing Claude skill covers Flipper Zero protocol knowledge. The closest options — `ljagiello/ctf-skills`, `wshobson/reverse-engineering`, `roostercoopllc/flipper-mcp` — each cover one slice (CTF reasoning, firmware RE, on-device tool control) and none bundle the protocol reference Claude actually needs when a user asks "what does this `.sub` do?" or "write me a DuckyScript payload that opens Notepad on a UK-layout target".

This plugin fills that gap. It is grounded in:
- Flipper-firmware source (`flipperdevices/flipperzero-firmware/`).
- Academic papers where they apply (Teuwen eprint/2024/1275 for FM11RF08S, Garcia et al. for MIFARE Classic Crypto1, Csikor et al. for RollBack, Verdult/Garcia for Hitag2).
- Official standards (ISO-14443, IEEE 1149.1 JTAG, NEC datasheet, Pronto Hex specification).

## Standalone useful

This plugin is **standalone-useful**. You don't have to be running echoforge the framework to benefit. Any Claude Code user writing Flipper payloads, analyzing captures, or studying protocols can install it and get the knowledge — the skill bodies deliberately reference echoforge's Payload Forge tool vocabulary where applicable but remain protocol-centric, not framework-centric.

## Scope guard

The skills are **defensive, dual-use, educational, and protocol-reference** only. They explain how protocols work, why attacks succeed or fail, and what a captured signal means. They do not:

- Ship ransomware payload templates.
- Maintain DuckyScript string blocklists (the `payload-defender` skill is analytical, not judgmental — per `DECISIONS.md`).
- Recommend attacks against targets the user hasn't established authorization for.

Users operate under their own Rules of Engagement. The skills flag legal/ethical context where relevant (e.g. transmit bands where TX is federally prohibited), tied to the user's ROE rather than moralizing.

## Back to the main repo

The `echoforge` framework is at the repo root one level up. See `echoforge/CLAUDE.md` for the project overview and `echoforge/docs/PHASE6_*.md` for the architectural research that informed this plugin.

## License

MIT. See `LICENSE`.
