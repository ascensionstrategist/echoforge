# Phase 6 — Skill Research for 3CH0F0RG3

**Mission:** Find Claude Code / Agent SDK skills that give Claude "cybersecurity mastery" when operating on a personal Flipper Zero — DuckyScript authoring, RF / IR / NFC protocol knowledge, CTF-style thinking, defensive analysis, reverse engineering.

**Scope guard applied throughout:** Defensive, dual-use, educational, and protocol-reference material only. No RATs, C2 frameworks, malware builders, stealers, or anything designed for unauthorized access to others' systems.

**Research date:** 2026-04-22.

---

## Section 1 — Marketplaces That Actually Exist

These are real, resolvable Claude skill / plugin / MCP directories as of April 2026.

### 1.1 Anthropic-operated

| Name | URL | What's on it | Security content? |
|------|-----|--------------|-------------------|
| **Official Agent Skills repo** | https://github.com/anthropics/skills | Document skills (docx, pdf, xlsx, pptx), canvas-design, mcp-builder, skill-creator, spec + template. | Almost none — hardware/security skills absent. No Flipper, DuckyScript, RF, IR, NFC, CTF. |
| **Agent Skills spec** | https://agentskills.io | The open spec Anthropic publishes. 26+ platforms support it (Claude, Codex, Gemini CLI, Copilot, Cursor). | Spec-only site, no skill catalog. |
| **Official Claude Plugins** | https://github.com/anthropics/claude-plugins-official | Anthropic's first-party plugin marketplace. | Broad productivity, no Flipper/RF. |

### 1.2 Third-party / community catalogs

| Name | URL | Notes |
|------|-----|-------|
| **claudemarketplaces.com** | https://claudemarketplaces.com | Community directory (explicitly not affiliated with Anthropic). Has category pages: `/skills/category/security` and `/mcp/category/security`. The listing pages themselves are sparse — they surface OWASP, Semgrep, and generic SAST skills. No Flipper/RF content visible in category listings. |
| **skills.sh** | https://skills.sh | Official agentskills.io directory. Mostly document / productivity / dev skills. No hardware-hacking category at time of survey. |
| **mcpmarket.com** | https://mcpmarket.com | MCP server marketplace. Has a "reverse-engineering" skill listing (wshobson) — see Section 3. |
| **claudepluginhub.com** | https://www.claudepluginhub.com | Third-party plugin hub. Carries wshobson's reverse-engineering plugin. |
| **aitmpl.com/plugins** | https://www.aitmpl.com/plugins/ | Plugin discovery. General, no hardware category. |

### 1.3 Curated "awesome" lists

| Name | URL | Security entries found |
|------|-----|------------------------|
| **hesreallyhim/awesome-claude-code** | https://github.com/hesreallyhim/awesome-claude-code | Only mentions Trail of Bits as a security entry. No hardware/Flipper. |
| **jmanhype/awesome-claude-code** | https://github.com/jmanhype/awesome-claude-code | Broad plugin/MCP list. No hardware content. |
| **ComposioHQ/awesome-claude-plugins** | https://github.com/ComposioHQ/awesome-claude-plugins | Curated plugin list. Same gap. |
| **Chat2AnyLLM/awesome-claude-plugins** | https://github.com/Chat2AnyLLM/awesome-claude-plugins | Same gap. |
| **quemsah/awesome-claude-plugins** | https://github.com/quemsah/awesome-claude-plugins | Automated adoption metrics (13k+ indexed plugins as of April 2026). |

### 1.4 Notable security-specialist marketplaces that DO exist

| Name | URL | What it ships |
|------|-----|---------------|
| **Trail of Bits Skills** | https://github.com/trailofbits/skills | CC-BY-SA-4.0. ~4.7k stars. Audit-grade skills: `yara-authoring`, `dwarf-expert`, `constant-time-analysis`, smart-contract security, `property-based-testing`. Closest-to-hardware entries: `dwarf-expert` (firmware RE) and `yara-authoring` (firmware/malware detection rules). No Flipper-specific content. |
| **mukul975/Anthropic-Cybersecurity-Skills** | https://github.com/mukul975/Anthropic-Cybersecurity-Skills | Apache 2.0. 754 skills mapped to MITRE ATT&CK / NIST CSF 2.0 / D3FEND / NIST AI RMF. 26 domains — including OT/ICS but NOT RF / NFC / BadUSB / hardware-debug. |
| **transilienceai/communitytools** | https://github.com/transilienceai/communitytools | MIT. 27 skills for the web-pentest lifecycle. No hardware. |
| **Eyadkelleh/awesome-claude-skills-security** | https://github.com/Eyadkelleh/awesome-claude-skills-security | MIT. SecLists wordlists + payloads + `pentest-advisor` / `ctf-assistant` / `bug-bounty-hunter` agents. Web-focused, not hardware. |
| **Orizon-eu/claude-code-pentest** | https://github.com/Orizon-eu/claude-code-pentest | MIT. 6 lifecycle skills (recon → exploit chains → report). Web/cloud focus. |
| **trilwu/secskills** | https://github.com/trilwu/secskills | MIT. 16 pentesting skills + 6 subagents. Includes a `wireless` skill (Wi-Fi/WPA2 — not sub-GHz). |

---

## Section 2 — Marketplaces Claimed But Did NOT Resolve as Claude Skill Hubs

Report these clearly so you don't chase ghosts.

| Domain | Status | What it actually is |
|--------|--------|---------------------|
| **skillhub.com** | Resolves — **NOT a Claude skill marketplace**. | Freelance content-writing platform. Articles, blogs, SEO copy, resumes. Zero overlap with AI skills / Claude / security. Ignore. |
| **skillsmp.com** | **403 Forbidden** at fetch time. | Could not verify content. No evidence it's a Claude skill marketplace — no inbound links from any Claude/Anthropic resource found during research. Treat as ghost until proven otherwise. |
| **"claude skill store"** (generic) | No such thing exists. | Anthropic has not launched a centralized skill store. Distribution is via `/plugin marketplace add <github-repo>` or directly copying to `~/.claude/skills/`. |

---

## Section 3 — Top 10 Skills / MCP Servers Ranked by echoforge Fit

Ranking is for **3CH0F0RG3 specifically**: DuckyScript authoring, sub-GHz, IR, NFC/RFID, hardware-debug protocols, defensive analysis of payloads. Fit scores 1–5.

### #1 — roostercoopllc/flipper-mcp — **Fit: 5/5**

- **URL:** https://github.com/roostercoopllc/flipper-mcp
- **What it gives Claude:** Direct MCP control of a Flipper Zero over WiFi (ESP32-S2 Dev Board v1). ~30 tools spanning **SubGHz** (TX/RX arbitrary freq, raw decode, file-based TX), **NFC** (read/emulate/field), **RFID LF** (read/write/emulate), **IR** (NEC + others, TX/RX), **BadUSB** (`badusb_run`, script listing, BLE HID keyboard/mouse), **iButton** (1-Wire), **GPIO** (read/write/mode), **BLE** beacons, file storage, app launching, dynamic FAP discovery.
- **Type:** MCP server (Rust, runs on-device) — not a skill, but composes naturally with any skill that knows Flipper semantics.
- **Install:**
  1. Flash ESP32-S2 Dev Board with `cargo` + Xtensa toolchain + `espflash`.
  2. Configure WiFi via SD card config or on-device FAP.
  3. Point Claude at `http://flipper-mcp.local:8080` (MCP Streamable HTTP) or via relay WebSocket.
- **License:** MIT. **Last activity:** 64 commits on main.
- **echoforge relevance:** This is the single most load-bearing external dependency for the whole project concept. Because 3CH0F0RG3 is a host-side controller, this is a direct alternative / comparison point — study it for protocol coverage patterns.

### #2 — ljagiello/ctf-skills — **Fit: 5/5**

- **URL:** https://github.com/ljagiello/ctf-skills
- **What it gives Claude:** 11 skills — `ctf-web`, `ctf-pwn`, `ctf-crypto`, `ctf-reverse`, `ctf-forensics`, `ctf-osint`, `ctf-malware`, `ctf-ai-ml`, `ctf-misc`, a `solve-challenge` orchestrator, and `ctf-writeup`. Covers ROP, heap, kernel pwn, shellcode, RSA/AES/ECC attacks, disk/memory forensics, stego, binary + VM + WASM + Android RE.
- **Install:** `npx skills add ljagiello/ctf-skills`
- **License:** MIT. **Stars:** 1.7k. **Activity:** 84 commits on main.
- **echoforge relevance:** `ctf-reverse`, `ctf-forensics`, `ctf-crypto` — gives Claude the mental model to reason about what a BadUSB payload is actually doing, what a captured sub-GHz dump means, and why a rolling-code capture fails on replay. This is the closest thing to a "red-team thinking" skill that's not offensive-only.

### #3 — wshobson reverse-engineering plugin — **Fit: 5/5**

- **URL:** https://www.claudepluginhub.com/plugins/wshobson-reverse-engineering-plugins-reverse-engineering-2 (source: github.com/wshobson/agents, `reverse-engineering` subplugin)
- **What it gives Claude:** 3 agents (`firmware-analyst`, `malware-analyst`, `reverse-engineer`) + 4 skills (`anti-reversing-techniques`, `binary-analysis-patterns`, `memory-forensics`, `protocol-reverse-engineering`). Wraps Ghidra, IDA Pro, radare2, x64dbg, Volatility.
- **Install:** `npx claudepluginhub wshobson/agents --plugin reverse-engineering`
- **License:** MIT. **Updated:** Feb 2, 2026. **Parent repo:** 33k stars.
- **echoforge relevance:** `firmware-analyst` + `protocol-reverse-engineering` are gold. Flipper firmware is flashable, third-party .fap files are distributed widely, and "what does this .sub file actually decode to" is a constant question — this skill teaches Claude the right tools to reach for.

### #4 — Trail of Bits skills (selective) — **Fit: 4/5**

- **URL:** https://github.com/trailofbits/skills
- **Pick only these sub-skills for echoforge:** `yara-authoring` (detection rules for captured payloads / firmware blobs), `dwarf-expert` (read firmware debug symbols), `constant-time-analysis` (reason about KeeLoq / crypto weaknesses).
- **Install:** `/plugin marketplace add trailofbits/skills` then `/plugin install yara-authoring@trailofbits` etc.
- **License:** CC-BY-SA-4.0. **Stars:** 4.7k. Active.
- **echoforge relevance:** Audit-grade, reputable authors, narrow utility. Not Flipper-aware but gives Claude better reasoning tools for crypto/firmware questions.

### #5 — busse/flipperzero-mcp — **Fit: 4/5**

- **URL:** https://github.com/busse/flipperzero-mcp
- **What:** Python MCP server, USB + WiFi + BLE-stub transports, Protobuf RPC with nanopb-delimited framing. Modular architecture. Ships `systeminfo`, `badusb` (generate/validate/store/execute), `music`, `connection` modules.
- **Gap vs #1:** No sub-GHz / NFC / RFID / IR / iButton / GPIO in-tree yet. But the **module pattern is a perfect reference for 3CH0F0RG3's own module system.**
- **Install:** `git clone && pip install -e . && flipper-mcp` + Claude Desktop config.
- **License:** MIT. **Activity:** 38 commits.
- **echoforge relevance:** Best architectural reference for how to structure a Flipper host-side controller. Lower feature count than #1, but cleaner Python code and a transport-layer design worth copying.

### #6 — hak5/usbrubberducky-payloads — **Fit: 4/5**

- **URL:** https://github.com/hak5/usbrubberducky-payloads
- **What:** Not a Claude skill — the **official Hak5 payload library** and DuckyScript 3.0 reference. Thousands of curated payloads covering recon (defensive), exfil demonstrations, prank payloads, OS-detection helpers, credential-hygiene testing.
- **echoforge use:** Bundle the README, the DuckyScript 3.0 spec excerpt, and a vetted subset of reconnaissance / defensive / prank payloads as `references/` inside a custom echoforge skill (see Section 4). Apply scope-guard filter: skip anything labeled `cred-harvest`, `wifi-grab`, `rat-*`, etc.
- **License:** MIT. Actively maintained by Hak5.

### #7 — Eyadkelleh/awesome-claude-skills-security — **Fit: 3/5**

- **URL:** https://github.com/Eyadkelleh/awesome-claude-skills-security
- **What:** 7 plugin categories (security-fuzzing, security-passwords, security-patterns, security-payloads, security-usernames, security-webshells, llm-testing) + 3 agents (pentest-advisor, ctf-assistant, bug-bounty-hunter). Sourced from SecLists.
- **Install:** `/plugin marketplace add Eyadkelleh/awesome-claude-skills-security` → `/plugin install <name>@awesome-security-skills`
- **License:** MIT. **Stars:** 187.
- **echoforge relevance:** `ctf-assistant` agent helps with CTF-style reasoning. `security-patterns` (regex for secrets) is useful when analyzing what a payload might leak. Skip web-shells — not in scope.

### #8 — mukul975/Anthropic-Cybersecurity-Skills — **Fit: 3/5**

- **URL:** https://github.com/mukul975/Anthropic-Cybersecurity-Skills
- **What:** 754 skills across 26 domains, framework-mapped (MITRE ATT&CK / D3FEND / NIST). OT/ICS security is in-scope (adjacent to RF / embedded), and threat-hunting + malware-analysis domains are useful reasoning scaffolds.
- **Install:** `npx skills add mukul975/Anthropic-Cybersecurity-Skills`
- **License:** Apache 2.0. **Stars:** 5.5k. **Version:** 1.2.0 (April 6, 2026).
- **echoforge relevance:** Broad and well-structured, but nothing Flipper-specific. Install as a general "security reasoning" layer — don't expect RF/NFC depth from it.

### #9 — trilwu/secskills — **Fit: 2/5**

- **URL:** https://github.com/trilwu/secskills
- **What:** 16 pentest skills + 6 subagents. Has a `wireless` skill — but it's Wi-Fi / WPA2 focused, NOT sub-GHz or ISM-band.
- **Install:** `/plugin marketplace add trilwu/secskills` → `/plugin install trilwu/secskills`
- **License:** MIT.
- **echoforge relevance:** Weak. Listed for completeness because it's the only third-party skill to use the word "wireless" — but don't install expecting sub-GHz help.

### #10 — mahmutka/cybersecurity-claude-skills — **Fit: 2/5**

- **URL:** https://github.com/mahmutka/cybersecurity-claude-skills
- **What:** 4 skills — `web-hacking`, `pentest-recon`, `secure-code-review`, `ctf-solver`.
- **Install:** Download skill folder as ZIP → upload via Claude Code Settings.
- **License:** MIT. **Last release:** Feb 25, 2026.
- **echoforge relevance:** `ctf-solver` overlaps with #2 (ljagiello/ctf-skills) which is stronger. Lower priority unless you want a lightweight alternative.

### Honorable mentions (not in top 10 but on-radar)

- **Trail of Bits `dwarf-expert`** — pulled out in #4.
- **AgriciDaniel/claude-cybersecurity** — 8-agent code-review specialist. No hardware. Useful for reviewing 3CH0F0RG3's own source.
- **wshobson/agents (parent repo)** — 33k stars, many sub-plugins beyond RE.
- **anthropic-skills:penetration-tester-master** — already installed in Shawn's environment per system context. General offensive master skill, no Flipper specifics.
- **anthropic-skills:security-audit** — already installed. Source-code focus.

---

## Section 4 — Gaps: What Doesn't Exist and Should Be Built Custom

After surveying ~20 repos, 5 marketplaces, and 2 claimed domains, the conclusion is unambiguous:

> **There is no Claude skill dedicated to Flipper Zero expertise, sub-GHz RF protocol reference, IR protocol reference, NFC/RFID reference, or DuckyScript authoring.** The closest tools (flipper-mcp #1, ctf-skills #2, wshobson RE #3) each cover one slice and none bundle the protocol knowledge 3CH0F0RG3 actually needs.

This is an opportunity, not a setback. Build a first-party echoforge skill bundle — it will be novel, likely marketplace-worthy, and tightly fit for purpose.

### 4.1 Proposed custom skill: `echoforge-flipper-mastery`

Single plugin, multiple skills under it, shipped with 3CH0F0RG3 and also publishable standalone.

| Sub-skill | Trigger | Contents |
|-----------|---------|----------|
| **echoforge-duckyscript** | User writes or debugs `.txt` DuckyScript, or BadUSB payload design. | DuckyScript 3.0 syntax reference, idioms (safe delays, OS detection via `DEFINE`, `WAIT_FOR_*`, variable + math support, functions), target-OS keyboard-layout gotchas (US vs ISO vs JIS), typical host behaviors (Windows focus-steal, macOS accessibility prompt, Linux input-method delays). `references/duckyscript-3.0-spec.md`, `scripts/validate-ducky.py` (syntax linter). |
| **echoforge-subghz** | Sub-GHz protocol discussion, `.sub` file analysis, rolling-code vs fixed-code questions. | Protocol cheatsheets: **KeeLoq** (hopping code structure, why replay fails, HCS301/HCS361), **Princeton PT2262** (fixed code, trinary encoding, CAME/Nice-Flo derivatives), **CAME TOP/TAM/ATOMO**, **Nice Flo/FloR/Smilo**, **Holtek HT6P20B/HT12E**, **Security+ 1.0 / 2.0** (Chamberlain/LiftMaster), **Somfy RTS/Telis**. Legal-band reference (315/390/433.92/868/915 MHz allocations by region). `references/subghz-protocols.md`, `references/flipper-sub-format.md`. |
| **echoforge-ir** | IR protocol work, `.ir` file analysis, universal-remote building. | **NEC** (32-bit, 9ms leader), **NEC Extended**, **RC5** (Manchester, 14-bit), **RC6** (Mode 0/6, trailer bit), **Sony SIRC** (12/15/20-bit variants, 40 kHz carrier, 2.4ms start, 1.2ms/0.6ms bits), **Kaseikyo/Panasonic** (48-bit), **Samsung36**, **Pronto Hex** format parsing. `references/ir-protocols.md` with decoder logic. |
| **echoforge-nfc-rfid** | NFC/RFID work: tag reading, cloning questions, emulation mode. | **ISO-14443A/B** frame structure, **MIFARE Classic** (key diversification, nested attack theory, why hardnested works, why UFUID exists), **MIFARE Ultralight + NTAG21x** (OTP pages, counters, password auth), **DESFire EV1/EV2/EV3** (3DES/AES authentication, application structure), **HID Prox** (26-bit H10301, 35-bit Corporate 1000, facility-code math), **EM4100/EM4305** (64-bit Manchester), **iClass Legacy/SE** (why SE is hardened), **iButton DS1990/DS1992**. `references/nfc-formats.md`, `references/rfid-formats.md`. |
| **echoforge-hardware-debug** | Questions about debug pins on a target device — educational only. | **JTAG** (TDI/TDO/TMS/TCK/TRST, chain discovery theory), **SWD** (2-wire, ARM Cortex), **UART** baud-rate hunting (common pinouts, voltage levels, why 3.3V vs 5V matters), **SPI flash dump** basics. Pure reference, no exploit payloads. |
| **echoforge-payload-defender** | Defensive/analytical mode — "what would this payload do if it ran on my machine?" | Walks a `.txt` or `.bin` payload, explains each line in plain English, flags OS-specific behavior, flags anything that writes to disk / opens network connection / tampers with security settings. Teaches the user defensive reasoning. |

### 4.2 Why this is worth building

1. **Zero competition** — verified across every marketplace in Section 1 and every awesome-list in 1.3.
2. **Natural fit with the tools you already have** — pair it with flipper-mcp (#1) or 3CH0F0RG3's own transport layer, and Claude becomes genuinely capable on Flipper.
3. **Publishable** — MIT-license it, submit PR to `hesreallyhim/awesome-claude-code`, list on `claudemarketplaces.com` under `/skills/category/security`, and 3CH0F0RG3 gets free distribution.
4. **Compounds with existing picks** — ctf-skills gives the reasoning, wshobson RE gives the RE tooling, flipper-mcp gives the device access. echoforge's own skill fills the protocol-knowledge middle layer none of them cover.

### 4.3 Implementation path

- Use `anthropic-skills:skill-creator` (already available in Shawn's env) to scaffold.
- Ship under `echoforge/skills/echoforge-flipper-mastery/` in the repo.
- Each sub-skill as `skills/<name>/SKILL.md` + `references/` + optional `scripts/`.
- Publish as `/plugin marketplace add <your-github>/echoforge-flipper-mastery` once stable.
- Apply the **scope-guard** filter during authoring: every bundled payload / code fragment must be defensible as educational, defensive, protocol-reference, or authorized-use. Exclude anything whose only plausible use is unauthorized access.

---

## Appendix — Sources

- https://github.com/anthropics/skills
- https://github.com/anthropics/claude-plugins-official
- https://agentskills.io
- https://skills.sh
- https://claudemarketplaces.com
- https://github.com/roostercoopllc/flipper-mcp
- https://github.com/busse/flipperzero-mcp
- https://github.com/ljagiello/ctf-skills
- https://github.com/wshobson/agents (reverse-engineering subplugin)
- https://www.claudepluginhub.com/plugins/wshobson-reverse-engineering-plugins-reverse-engineering-2
- https://github.com/trailofbits/skills
- https://github.com/mukul975/Anthropic-Cybersecurity-Skills
- https://github.com/transilienceai/communitytools
- https://github.com/Eyadkelleh/awesome-claude-skills-security
- https://github.com/Orizon-eu/claude-code-pentest
- https://github.com/trilwu/secskills
- https://github.com/mahmutka/cybersecurity-claude-skills
- https://github.com/AgriciDaniel/claude-cybersecurity
- https://github.com/hak5/usbrubberducky-payloads
- https://github.com/hesreallyhim/awesome-claude-code
- https://snyk.io/articles/top-claude-skills-cybersecurity-hacking-vulnerability-scanning/
