# Phase 6: Payload Forge — Tool API Specification

**Status:** Design (no implementation).
**Author:** api-architect.
**Audience:** python-expert (implementation), security-expert (content-safety review), testing-expert, code-reviewer.
**Scope:** BadUSB (DuckyScript), Sub-GHz (.sub), Infrared (.ir). NFC / RFID / iButton authoring is reserved for **Phase 6b** and intentionally excluded here.

---

## 1. Design Goals & Non-Goals

### Goals
- Let Claude author, validate, inspect, list, and (under gated approval) transmit Flipper payloads on behalf of the user via typed tools.
- Compose on top of the Phase 4 surface (`list_directory`, `read_file`, `write_file`, `subghz_transmit`, `ir_transmit`, `badusb_execute`) — **no duplicate transport code.**
- Every write / mutate / transmit flows through `SafetyPolicy.assess()` and `_with_recovery(flipper, _run)` — same contract as Phase 4.
- Schema-level content bounds that bite *before* SafetyPolicy is even called (max-size, whitelist charset, path confinement).
- Keep the tool count tight: 13 tools total, biased toward composition (a single `badusb_create` that takes either `script_text` or `script_ast` rather than a separate `badusb_build_from_ast`).

### Non-Goals
- Content-safety policy (what *strings* are malicious). Deferred to security-expert; the schema exposes hooks (`policy_tag`, `max_string_bytes`) but does not decide.
- NFC / RFID / iButton authoring tooling (Phase 6b — the underlying .nfc / .rfid / .ibtn file formats carry key material and need separate threat modeling).
- Sub-GHz crafting from scratch beyond parameter tweaks of an existing capture. Claude does **not** synthesize RAW_Data from first principles in this phase.
- Live RX capture orchestration. Phase 6 accepts *post-hoc* naming of a capture file the user has already saved on the device (see `payload_subghz_import_capture`).

### Platform Note
3CH0F0RG3 runs on Windows, but **every `path` argument in this API is Flipper-side POSIX** (`/ext/badusb/rickroll.txt`), never a Windows path. The TUI is the only place that ever sees `C:\…`. Tool descriptions MUST say "Flipper path" to prevent Claude from passing host paths.

---

## 2. Tool Inventory

All tools are registered as `mcp__echoforge__<name>` by `create_sdk_mcp_server`. Name column below is the bare tool name (what Claude sees in the system prompt registry).

| # | Tool name | One-line description | Input schema (key → type) | Output shape | Risk | `requires_hold` | Reasoning |
|---|-----------|----------------------|---------------------------|--------------|------|-----------------|-----------|
| 1 | `payload_badusb_create` | Compose a DuckyScript .txt in `/ext/badusb/`. Validates syntax, enforces size + charset limits, writes only after SafetyPolicy approves. Does **not** execute. | `name: str`, `script_text: str`, `description: str?`, `target_os: str?` (`windows`\|`macos`\|`linux`\|`cross`), `author: str?`, `tags: str[]?`, `overwrite: bool?` | `{path, bytes_written, validation: {ok, warnings[]}, sidecar_path}` | MED | n | Writes to SD but does not transmit/type. Diff shown. |
| 2 | `payload_badusb_validate` | Lint DuckyScript without writing. Returns line-by-line issues (unknown command, STRING out-of-charset, DELAY out of range). Cheap pre-flight before `payload_badusb_create`. | `script_text: str` | `{ok, issues: [{line, severity, code, message}], stats: {lines, strings, delays_ms_total}}` | LOW | n | Pure function; no device I/O. |
| 3 | `payload_badusb_run` | Execute a DuckyScript already on the Flipper. Thin alias over Phase 4 `badusb_execute` but re-classified under the Payload Forge namespace so Claude selects it alongside the authoring tools. | `script_path: str` (must match `^/ext/badusb/.+\.txt$`) | `{command, ack_output}` | HIGH | y | Types keystrokes into the host PC. |
| 4 | `payload_subghz_list` | List `.sub` files under `/ext/subghz/` (recursive one level). Includes parsed header fields (Frequency, Preset, Protocol) from the sidecar when available. | `subdir: str?` (relative, default `""`) | `{entries: [{name, path, size, frequency_hz, protocol, preset, has_sidecar, tags}]}` | LOW | n | Read-only. |
| 5 | `payload_subghz_inspect` | Parse one `.sub` file into a structured view (headers + RAW_Data stats: sample count, duration_us, min/max pulse). Detects malformed files. | `path: str` (must match `^/ext/subghz/.+\.sub$`) | `{headers: {Filetype, Version, Frequency, Preset, Protocol, ...}, raw_stats?: {samples, duration_us, min_pulse_us, max_pulse_us}, parsed?: {Bit, Key, ...}}` | LOW | n | Read-only parse. |
| 6 | `payload_subghz_retune` | Create a derived `.sub` by changing `Frequency` and/or `Preset` of an existing capture. Never rewrites RAW_Data or parsed Key bits. Writes as new file. | `source_path: str`, `dest_name: str`, `frequency_hz: int?`, `preset: str?` (one of allowlist), `description: str?` | `{path, source_path, diff: {frequency_hz: [old,new], preset: [old,new]}}` | MED | n | Derived write, not transmit. |
| 7 | `payload_subghz_import_capture` | Rename/tag a just-captured `.sub` (e.g. `/ext/subghz/capture_2026-04-22.sub`) to a human name with sidecar metadata. Uses Phase 4 `rename` under the hood. | `source_path: str`, `dest_name: str`, `description: str?`, `tags: str[]?`, `author: str?` | `{path, sidecar_path, moved_from}` | MED | n | Rename-in-place, classified with `rename` → MED escalated because Phase 4 `rename` itself is HIGH; see §3.3. |
| 8 | `payload_subghz_transmit` | Broadcast a stored `.sub`. Thin alias over Phase 4 `subghz_transmit` with the Payload Forge namespace, path confinement, and mandatory transmit-safety preamble in the tool description. | `signal_file: str`, `repeats: int?` (1–10) | `{command, ack_output}` | HIGH | y | Real RF emission. |
| 9 | `payload_ir_list` | List `.ir` files under `/ext/infrared/` (including `universal/`). Reports signal count per file (a file can hold many named buttons). | `subdir: str?` (default `""`), `include_universal: bool?` (default false) | `{entries: [{name, path, size, signal_count, has_sidecar}]}` | LOW | n | Read-only. |
| 10 | `payload_ir_inspect` | Parse one `.ir` file into its list of signals with `{name, type, protocol, address, command}` or `{name, type=raw, frequency, duty_cycle, samples}`. | `path: str` (must match `^/ext/infrared/.+\.ir$`) | `{signals: [{name, type, protocol?, address?, command?, frequency?, duty_cycle?, sample_count?}]}` | LOW | n | Read-only parse. |
| 11 | `payload_ir_import_capture` | Rename/tag a freshly-captured `.ir`. Same contract as `payload_subghz_import_capture`. | `source_path: str`, `dest_name: str`, `description: str?`, `tags: str[]?`, `author: str?` | `{path, sidecar_path, moved_from}` | MED | n | Rename. |
| 12 | `payload_ir_transmit` | Transmit one signal from a stored `.ir`. Wraps Phase 4 `ir_transmit`; adds button-name validation against the file's signal list first. | `signal_file: str`, `button_name: str?` | `{command, ack_output, resolved_button}` | MED | n | IR is line-of-sight and low-blast-radius vs Sub-GHz, but still actuates third-party hardware. |
| 13 | `payload_library_search` | Search all payload sidecars (badusb + subghz + infrared) by free-text match on `description`/`tags`/`author`. Useful when the user says "transmit that Ford key I captured last week." | `query: str`, `kinds: str[]?` (subset of `badusb`\|`subghz`\|`infrared`), `limit: int?` (default 20, max 100) | `{results: [{path, kind, name, description, tags, author, score}]}` | LOW | n | Read-only scan of sidecar JSON. |

**Total: 13 tools.** No separate `payload_badusb_list` / `payload_badusb_inspect` — DuckyScript is human-readable, and Claude already has `list_directory` + `read_file`. Forcing a dedicated BadUSB reader would duplicate the surface without adding value.

### 2.1 Namespacing convention

Phase 4 uses flat names (`subghz_transmit`, `badusb_execute`). Phase 6 prefixes everything with `payload_` to make the *authoring* intent obvious to Claude when it reads the tool registry:

- `payload_<kind>_<verb>` — e.g. `payload_badusb_create`, `payload_subghz_inspect`.
- `payload_library_<verb>` — cross-kind operations.

This is not a renaming of Phase 4 tools. Both surfaces coexist; Claude will naturally prefer `payload_badusb_create` over raw `write_file` because the description is more specific.

### 2.2 Sidecar file convention

Every payload has an **optional** sibling `<name>.echoforge.json`:

```json
{
  "schema": "echoforge.payload.v1",
  "kind": "badusb|subghz|infrared",
  "name": "rickroll",
  "description": "…",
  "author": "shawn@ascensionstrategies",
  "tags": ["demo", "harmless"],
  "target_os": "windows",
  "created_utc": "2026-04-22T18:00:00Z",
  "modified_utc": "2026-04-22T18:00:00Z",
  "source": { "tool": "payload_badusb_create", "content_hash": "sha256:…" },
  "policy_tag": null
}
```

- Sidecars are **advisory metadata**, not authoritative. If the sidecar and the payload disagree, the payload wins.
- `policy_tag` is reserved for security-expert. The Forge never sets it. A future policy layer can populate it (e.g. `"reviewed"`, `"contains_credentials_access"`).
- `content_hash` lets `payload_library_search` detect sidecar drift (payload edited outside echoforge).
- Sidecars live next to the payload, never in a separate index dir. Losing one is non-fatal; `payload_library_search` falls back to filename-only matching.

---

## 3. Content-Safety Boundaries (schema-level)

These are enforced in the tool input schema and in a thin pre-SafetyPolicy validator. They are *bounds*, not *content policy* — security-expert owns the latter.

### 3.1 Path confinement

Every `path` / `source_path` / `signal_file` / `script_path` argument MUST match one of:

| Tool group | Allowed regex |
|------------|---------------|
| BadUSB     | `^/ext/badusb/[A-Za-z0-9 _\-./]{1,120}\.txt$` |
| Sub-GHz    | `^/ext/subghz/[A-Za-z0-9 _\-./]{1,120}\.sub$` |
| Infrared   | `^/ext/infrared/[A-Za-z0-9 _\-./]{1,120}\.ir$` |

- No `..` segments (literal substring `..` rejected).
- No leading `/int/` or `/any/`. Those remain BLOCKED at the `RiskAssessor` layer too — this is defense in depth.
- `dest_name` in `_import_capture` / `_retune` is a filename only (`[A-Za-z0-9 _\-.]{1,80}`), not a path. The tool joins it with the fixed target dir.

### 3.2 DuckyScript (`payload_badusb_*`)

| Bound | Limit | Rationale |
|-------|-------|-----------|
| Total file size | ≤ 32 KiB | Flipper BadUSB runner is happy up to MB, but 32 KiB is enough for any legitimate payload and caps abuse of Claude as a keystroke-dump generator. |
| Line count | ≤ 2000 | Mirrors size bound. |
| Line length | ≤ 1024 chars | DuckyScript STRING blocks above this are almost always data exfil dumps. |
| `DELAY` argument | 0 ≤ n ≤ 600 000 ms | Prevents a 30-min silent payload. |
| `DEFAULTDELAY` | 0 ≤ n ≤ 10 000 ms | |
| Recognized commands | `REM`, `DELAY`, `DEFAULTDELAY`, `STRING`, `STRINGLN`, `ENTER`, `TAB`, `SPACE`, `BACKSPACE`, `DELETE`, `ESCAPE`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `HOME`, `END`, `PAGEUP`, `PAGEDOWN`, `CAPSLOCK`, `PRINTSCREEN`, `GUI`, `WINDOWS`, `CONTROL`, `CTRL`, `ALT`, `SHIFT`, `F1`–`F12` | Everything else → validation warning (not error, because firmware-specific extensions exist). |
| `STRING` charset | Printable ASCII 0x20–0x7E only by default | PowerShell-style non-ASCII payload detection; user can opt in to extended via a `charset="extended"` flag *surfaced in schema* but defaulted off. Security-expert decides the final allowlist (see Q2). |
| Banned tokens (literal substring in STRING, case-insensitive) | *Deferred to security-expert.* Schema exposes `policy_tag` on create so a future validator can flag `"cmd.exe /c del"`, `Invoke-WebRequest`, etc. without changing this spec. |

Violations return `validation_failed` (see §4) and do NOT write.

### 3.3 Sub-GHz (`payload_subghz_*`)

- `.sub` is parsed as a `Filetype: Flipper SubGhz …`-headed key=value plaintext plus optional `RAW_Data:` lines.
- `payload_subghz_retune` may only modify `Frequency` and `Preset`. `Frequency` must be in one of the ISM bands the Flipper SubGHz stack accepts: **300–348, 387–464, 779–928 MHz.** Anything else → validation error. (Security-expert confirms these bounds; upstream `subghz tx` rejects out-of-band.)
- `Preset` allowlist: `FuriHalSubGhzPresetOok270Async`, `FuriHalSubGhzPresetOok650Async`, `FuriHalSubGhzPreset2FSKDev238Async`, `FuriHalSubGhzPreset2FSKDev476Async`, `FuriHalSubGhzPresetMSK99_97KbAsync`, `FuriHalSubGhzPresetGFSK9_99KbAsync`, `FuriHalSubGhzPresetCustom`.
- Max `.sub` file size for write: 512 KiB.
- `RAW_Data` is **never written by Claude** in Phase 6. Retune only touches headers.
- Source `.sub` must already exist on device; `payload_subghz_retune` pre-reads it via Phase 4 `read_file` to confirm.

### 3.4 Infrared (`payload_ir_*`)

- `.ir` parses as a sequence of blocks separated by `#` lines, each with keys `name`, `type`, and either `{protocol, address, command}` or `{frequency, duty_cycle, data}`.
- No Forge tool crafts `.ir` content from scratch in Phase 6 — only import / retransmit. Creation is reserved for Phase 6b once the protocol allowlist is nailed down.
- `button_name` in `payload_ir_transmit` must be resolved against the file's parsed signal list before transmit. If not found, return `validation_failed`, not device error.

### 3.5 Sidecar bounds

- Sidecar JSON ≤ 8 KiB.
- `description` ≤ 500 chars.
- `tags`: ≤ 16, each `[a-z0-9_-]{1,32}`.
- `author`: ≤ 120 chars, no control characters.
- Sidecar is written via Phase 4 `write_file` (goes through SafetyPolicy → MED diff). A failed sidecar write does **not** roll back the payload write — Claude is told about it and can retry.

---

## 4. Error Taxonomy

Every tool returns the standard Phase 4 shape: `{"content": [{"type":"text","text": …}], "isError"?: True}`. Errors carry a machine-parseable prefix so Claude can recover.

| Code | Surface text prefix | Meaning | Recommended Claude action |
|------|---------------------|---------|---------------------------|
| `E_PATH_OUTSIDE_ALLOWED` | `ERROR[E_PATH_OUTSIDE_ALLOWED]: …` | Path regex rejected; e.g. `/int/foo.txt` or `/ext/apps/x.fap`. | Tell user the path rule in one sentence; do not retry with a guessed path. |
| `E_PATH_NOT_FOUND` | `ERROR[E_PATH_NOT_FOUND]: …` | Source file missing (retune, inspect, transmit of non-existent file). | Offer to `list_directory` or `payload_*_list` to help find the real name. |
| `E_PATH_EXISTS` | `ERROR[E_PATH_EXISTS]: …` | `overwrite=false` and file exists. | Ask user, or retry with `overwrite=true`. Never silently overwrite. |
| `E_VALIDATION_FAILED` | `ERROR[E_VALIDATION_FAILED]: <n> issue(s); see details` | DuckyScript / .sub / .ir failed the schema-level bounds in §3. | Show issues verbatim, fix the offending lines, call the matching `_validate` tool before retrying `_create`. |
| `E_PAYLOAD_TOO_LARGE` | `ERROR[E_PAYLOAD_TOO_LARGE]: …` | Exceeded §3 size caps. | Explain the cap; do not truncate silently. |
| `E_SIDECAR_WRITE_FAILED` | `ERROR[E_SIDECAR_WRITE_FAILED]: …` | Payload wrote OK, sidecar did not (includes the post-rename read-back failure added in Phase 6 review M1 — we no longer silently hash `b""` as the file contents). | Non-fatal — tell the user the payload is usable, offer to rewrite sidecar. |
| `E_STORAGE_READ_FAILED` | `ERROR[E_STORAGE_READ_FAILED]: …` | Source read failed for a reason that is NOT "file missing" (e.g. `PermissionError`, transport-level RPC failure). Added in Phase 6 review M5 — previously `E_PATH_NOT_FOUND` was overloaded to cover both cases. | Surface the error verbatim; do not auto-retry the same path. |
| `E_DEVICE_BUSY` | `ERROR[E_DEVICE_BUSY]: …` | `_with_recovery` already retried once; subsequent call still timed out, or a prior RF TX is still in flight. | Suggest user unlock / exit app; back off at least 2s before retry. |
| `E_POLICY_BLOCKED` | `ERROR[E_POLICY_BLOCKED]: …` | `SafetyPolicy.assess()` returned `block` (e.g. path is in BLOCKED area and not unlocked). | Surface the unlock instruction Claude reads from the decision `reason`. Do not retry. |
| `E_APPROVAL_DENIED` | `ERROR[E_APPROVAL_DENIED]: user declined` | User declined MED/HIGH approval prompt. | Acknowledge; do not propose the same action again without a new user request. |
| `E_UNSUPPORTED_ARG` | `ERROR[E_UNSUPPORTED_ARG]: …` | E.g. `frequency_hz=900000000` (out of band), or `preset` not in allowlist. | Fix and retry. |
| `E_INTERNAL` | `ERROR[E_INTERNAL]: <type>: <msg>` | Unhandled Python exception. | Report to user; do not auto-retry. |

Error text MUST include the bracketed code. Claude is told in the system-prompt update (see §5.3) to route off the bracketed code, not off the freeform text.

---

## 5. Approval UX Implications

### 5.1 Auto-approve matrix (driven by `SafetyPolicy.auto_approve_level = LOW` default)

| Tool | Level | Auto? | Shown UX |
|------|-------|-------|----------|
| `payload_badusb_validate`, `*_list`, `*_inspect`, `payload_library_search` | LOW | yes | silent |
| `payload_badusb_create`, `payload_subghz_retune`, `payload_ir_transmit` | MED | **diff card + one-tap approve** | shows target path, proposed bytes, sidecar tags |
| `payload_subghz_import_capture`, `payload_ir_import_capture` | MED | one-tap approve | shows `rename from → to` + sidecar |
| `payload_badusb_run`, `payload_subghz_transmit` | HIGH | **hold-to-confirm** (`requires_hold=True`) | shows the *exact* script/.sub being executed, target PC warning for BadUSB, frequency + repeat count for Sub-GHz |

### 5.2 Rationale: why IR transmit is only MED

Original Phase 4 rules: `ir_transmit` = MED. We keep it. Sub-GHz propagates through walls and has been used to open cars/garages; IR is line-of-sight, range ~10m, and a typo is low-blast-radius. BadUSB types into the user's own machine — that *is* destructive from the user's perspective (any DuckyScript can exfil or wipe) — so HIGH+hold.

### 5.3 Required system-prompt update

When Phase 6 ships, `prompts.py` SYSTEM_PROMPT gets a new section listed under "AVAILABLE ACTIONS":

```
### Payload Forge — Authoring
- payload_badusb_validate — lint a DuckyScript (LOW)
- payload_badusb_create — save a DuckyScript to /ext/badusb/ (MED, diff)
- payload_badusb_run — execute a saved DuckyScript (HIGH, hold)
- payload_subghz_list / _inspect / _retune / _import_capture / _transmit
- payload_ir_list / _inspect / _import_capture / _transmit
- payload_library_search — find payloads by description/tags
```

Plus one line in CORE PRINCIPLES: *"Prefer `payload_badusb_create` over raw `write_file` for `/ext/badusb/*.txt` — it validates and writes a sidecar atomically."*

### 5.4 Risk-rule additions for `risk.py`

`ACTION_RULES` gains entries (names here are the `TOOL_TO_RISK_ACTION`-mapped action names, not the raw MCP names):

```
"payload_forge_validate":       LOW,
"payload_forge_list":           LOW,
"payload_forge_inspect":        LOW,
"payload_forge_search":         LOW,
"payload_forge_create_badusb":  MED,   # write-like
"payload_forge_retune_subghz":  MED,   # derived write
"payload_forge_import":         MED,   # rename + sidecar
"payload_forge_transmit_subghz":HIGH,  # alias of subghz_transmit
"payload_forge_transmit_ir":    MED,   # alias of ir_transmit
"payload_forge_run_badusb":     HIGH,  # alias of badusb_execute
```

`TOOL_TO_RISK_ACTION` map is extended accordingly. All existing path-escalation rules (`ESCALATE_TO_HIGH_PATHS`) continue to apply — e.g. a DuckyScript under `/ext/apps/` (nonsensical but bounds-wise possible) would be escalated to HIGH.

---

## 6. Open Questions for `security-expert`

These are intentionally un-answered in this spec. Each needs a concrete verdict before Phase 6 implementation lands.

1. **STRING-block content policy.** The schema caps size/charset but does not veto *strings*. What substrings should `payload_badusb_validate` flag (warn) vs. refuse (error)? Proposed starter list: `Invoke-WebRequest`, `certutil -urlcache`, `bitsadmin`, `mshta http`, `reg delete HKLM`, `wmic shadowcopy delete`, `vssadmin delete`. Who owns this list going forward?
2. **Charset policy for STRING.** Is printable ASCII 0x20–0x7E the right default? Many legitimate scripts use Unicode (em-dash, international usernames). Should we instead allow UTF-8 and veto only C0/C1 control bytes? The Flipper BadUSB HID layer is ASCII-limited on stock but Momentum handles Unicode with layout hints.
3. **Frequency allowlist for Sub-GHz retune.** Our proposed bands (300–348 / 387–464 / 779–928 MHz) follow Flipper's firmware-enforced regional limits. Should echoforge enforce a stricter US-only subset (e.g. exclude 433.92 MHz unmodulated continuous carrier), or defer wholly to firmware? Relevant because `retune` makes it trivial to park a carrier on a sensitive band.
4. **Sub-GHz rolling-code files.** A `.sub` with `Protocol: KeeLoq` or `Protocol: Security+ 2.0` captured from someone's car is a vehicle key. Should `payload_subghz_retune` refuse these protocols outright (forcing the user to edit manually)? Should `payload_subghz_transmit` gate them behind an additional unlock?
5. **Sidecar `policy_tag` ownership.** Who writes tags? Options: (a) the validator, auto, from the banned-token list; (b) the user, manually in the TUI; (c) an LLM grader running out-of-band. If (a), define the tag vocabulary.
6. **Audit-log granularity.** `AuditService` already logs tool calls. Should Payload Forge create/transmit emit a dedicated audit record with the full payload content, or just the hash + sidecar? Keystroke-level logs of exfil payloads could themselves become a leak vector.
7. **Anti-abuse on `payload_library_search`.** If sidecars contain `author: <email>` and echoforge indexes them, does `search(query="*")` become a way for Claude to enumerate PII offline? Propose redaction rules.
8. **Handling of BadUSB scripts that target the *Flipper itself*.** Nothing in the current schema prevents a DuckyScript that uses `GUI r` → `STRING flipper-update-url…` against the user's machine to re-flash the Flipper. Is this worth a separate heuristic, or is it subsumed by Q1?

Answers land in `docs/PHASE6_PAYLOAD_FORGE_SECURITY.md` (owned by security-expert) and are referenced back into §3.2 before implementation begins.

---

## 7. Dependencies on Existing Modules

Payload Forge is a composition layer. No new transport, no new CLI syntax, no re-implementation of what Phase 4 already ships.

### 7.1 Phase 4 MCP tools reused (imported via the facade, not re-invoked across MCP)

| Phase 6 tool | Phase 4 primitive(s) it composes on |
|--------------|-------------------------------------|
| `payload_badusb_create` | `flipper.storage.write(path, bytes)` (same path as `write_file` tool) — twice: once for the .txt, once for the sidecar .json |
| `payload_badusb_validate` | none — pure function |
| `payload_badusb_run` | `flipper.badusb.run(path)` (same as `badusb_execute`) |
| `payload_subghz_list` | `flipper.storage.list(path)` + per-entry `flipper.storage.read` for sidecar |
| `payload_subghz_inspect` | `flipper.storage.read(path)` |
| `payload_subghz_retune` | `flipper.storage.read` (source) → parse → `flipper.storage.write` (dest) + sidecar |
| `payload_subghz_import_capture` | `flipper.storage.rename(source, dest)` (same as `rename` tool) + `flipper.storage.write` sidecar |
| `payload_subghz_transmit` | `flipper.subghz.transmit_from_file(path, repeats=…)` (same as `subghz_transmit`) |
| `payload_ir_list` | `flipper.storage.list` + sidecar read |
| `payload_ir_inspect` | `flipper.storage.read` |
| `payload_ir_import_capture` | `flipper.storage.rename` + sidecar write |
| `payload_ir_transmit` | `flipper.storage.read` (to resolve button_name) → `flipper.ir.transmit_from_file(path, button_name=…)` |
| `payload_library_search` | `flipper.storage.list` (recursive) + `flipper.storage.read` on each `.echoforge.json` |

### 7.2 Safety layer integration

- Every tool wraps its work in `_with_recovery(flipper, _run)` — identical to Phase 4.
- Every mutating tool calls `SafetyPolicy.assess(action, args, current_content=…)` **before** calling into `flipper.storage.*`. `action` is the `payload_forge_*` rule name from §5.4, not the raw MCP tool name.
- `current_content` is passed for retune / create-with-overwrite so the TUI gets a real `DiffSummary`.
- Path-confinement regex in §3.1 is enforced *before* SafetyPolicy (cheap reject; avoids even telling SafetyPolicy about obviously-wrong paths). SafetyPolicy's own `BLOCKED_PATH_PREFIXES` remains the authoritative gate.

### 7.3 Hardware modules touched

`src/echoforge/actions/hardware.py`:
- `BadUsb.run(path)` — reused directly; no changes.
- `SubGhz.transmit_from_file(path, repeats=…)` — reused directly.
- `Infrared.transmit_from_file(path, button_name=…)` — reused directly; Forge adds button-name resolution *before* calling.
- `Infrared.transmit_raw(...)` — **not** exposed by Phase 6. Reserved for Phase 6b when a proper protocol allowlist exists.

`src/echoforge/actions/storage.py` (not re-read but referenced by Phase 4 tools):
- `storage.write`, `storage.read`, `storage.list`, `storage.rename`, `storage.stat` — all reused through `flipper.storage.*`.

No new proto files. No new CLI commands. No changes to `transport/`.

### 7.4 Module layout proposal (non-normative)

```
src/echoforge/payload/                 (NEW)
  __init__.py
  badusb.py      # DuckyScriptParser, DuckyScriptValidator, Issue model
  subghz.py      # SubFileParser, retune logic, band allowlist
  infrared.py    # IrFileParser, signal resolver
  sidecar.py     # Sidecar model (pydantic v2), load / dump / hash
  library.py     # PayloadLibrary: search across sidecars
src/echoforge/agent/tools_payload.py   (NEW)
  # register_payload_tools(flipper, policy) — called from agent/tools.py
```

`agent/tools.py` gets one new line in `build_flipper_tools`:

```python
tools.extend(build_payload_tools(flipper, policy))
```

…and corresponding entries in `TOOL_TO_RISK_ACTION` / `TOOL_PRIMARY_PATH_FIELD`. Nothing else in Phase 4 is modified.

---

## 8. Validation & Acceptance

- `ruff check` clean with repo config.
- `pytest tests/payload/` covers: DuckyScript parser happy/sad paths, SubGHz retune header-only guarantee, IR button-name resolution, sidecar round-trip, path-confinement regex (positive + 20 adversarial negatives including `/int/.`, `../x.sub`, `/ext/badusb/../subghz/x.sub`, unicode-normalisation tricks).
- `testing-expert` writes property-based fuzz tests for the three parsers with `hypothesis`.
- `security-expert` signs off on §6 Q1–Q8 before any `_create` / `_retune` tool is wired into `build_flipper_tools`.
- `code-reviewer` does the final pass with explicit focus on: (a) no path unchecked before SafetyPolicy, (b) no `storage.write` without a matching `_with_recovery`, (c) no new CLI syntax introduced.

---

## 9. Example Flows (for implementers + prompt authors)

### 9.1 "Make me a rickroll BadUSB for my laptop"

```
Claude → payload_badusb_validate(script_text="REM Rickroll\nDELAY 1000\nGUI r\n…")
         ← LOW, ok, stats={lines:6, strings:1, delays_ms_total:1200}
Claude → payload_badusb_create(
             name="rickroll",
             script_text="…",
             description="Opens browser to a music video",
             target_os="windows",
             tags=["demo","harmless"])
         ← MED diff card → user approves
         ← {path: "/ext/badusb/rickroll.txt", bytes_written: 92, sidecar_path: "/ext/badusb/rickroll.echoforge.json"}
Claude: "Saved to /ext/badusb/rickroll.txt. Run it with payload_badusb_run when you're plugged into the target."
```

### 9.2 "I just captured my garage — save it as 'Garage 2026'"

```
Claude → payload_subghz_list()
         ← sees capture_2026-04-22_18-02-11.sub
Claude → payload_subghz_inspect(path="/ext/subghz/capture_2026-04-22_18-02-11.sub")
         ← 433.92 MHz, OOK 650, RAW, 412 samples
Claude → payload_subghz_import_capture(
             source_path="/ext/subghz/capture_2026-04-22_18-02-11.sub",
             dest_name="Garage 2026.sub",
             description="North bay garage door, captured 2026-04-22",
             tags=["garage","home"])
         ← MED, user approves
         ← {path: "/ext/subghz/Garage 2026.sub", sidecar_path: "…Garage 2026.echoforge.json"}
```

### 9.3 "Retransmit the garage signal 3 times"

```
Claude → payload_library_search(query="garage")
         ← 1 hit: /ext/subghz/Garage 2026.sub
Claude → payload_subghz_transmit(signal_file="/ext/subghz/Garage 2026.sub", repeats=3)
         ← HIGH, hold-to-confirm UX → user holds → TX
         ← {command: "subghz tx_from_file …", ack_output: "…"}
```

---

*End of spec.*
