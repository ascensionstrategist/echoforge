# Phase 6 — Decisions Record

**Status:** Locked. Codifies operator decisions that **override** defaults proposed in `PHASE6_PAYLOAD_FORGE_API.md` and `PHASE6_CONTENT_SAFETY.md`. Authoritative source for Phase 6 implementation.

**Decided:** 2026-04-22
**Project:** 3CH0F0RG3 / echoforge — physical-layer red-team framework
**Mission context:** licensed commercial pentest engagements (peer category: Sliver / Mythic / Havoc / Caldera). Operator is a contracted red-team professional, not a hobbyist.

---

## 1. Design philosophy

Three principles drive every decision below:

1. **Trust the operator, rely on the audit trail.** echoforge is not a gatekeeper. It is a capable hardware controller with perfect telemetry. Accountability flows through the audit log, not through content classifiers.
2. **Classifiers decay; audit trails don't.** Any rule that can be trivially bypassed with encoding, paraphrasing, or renaming is **not** shipped — it generates security theatre and trains the operator to distrust the stamps of approval they do get.
3. **Physical action always deserves operator confirmation.** Keystrokes typed into a host and RF transmitted from a radio are irreversible side-effects on the physical world. Those actions always require hold-to-confirm, even on payloads the operator authored themselves.

---

## 2. Content safety — overrides to `PHASE6_CONTENT_SAFETY.md`

The content-safety spec proposed DuckyScript string-content classifiers, rolling-code gates, charset restrictions, and a frequency allowlist. Operator has **dropped all four** for the reasons under §1.

| Safety Spec Proposal | Decision | Rationale |
|---|---|---|
| DuckyScript STRING blocklist (D3–D12 rules) | **DROPPED** | Pentest payloads routinely contain `Invoke-WebRequest`, `vssadmin delete`, shellcode stagers. A blocklist blocks legitimate tradecraft and is bypassed with base64. Audit log records the exact content; operator owns it. |
| Rolling-code .sub special gate (KeeLoq / Somfy / CAME ATOMO / Security+) | **DROPPED** | Treated like any other .sub file. Replay is a core red-team primitive with a signed ROE. Jurisdictional legality is the operator's contractual problem, not echoforge's. |
| DuckyScript STRING charset restriction (ASCII vs UTF-8) | **DROPPED** | Full character set allowed, including control bytes. Legitimate international payloads (non-English passwords, Unicode domain tricks, emoji-based IDN homoglyphs) need this. |
| Frequency allowlist for Sub-GHz TX | **DROPPED** | Momentum firmware's region-unlock setting is **enabled** on the hardware under test — firmware does not gate frequencies. echoforge does not add a second layer. Practical consequence: operator can TX on any band the radio supports, including public-safety / aircraft / cellular / weather. This is the operator's legal responsibility under their engagement Rules of Engagement. |

## 3. Safety controls that SURVIVE

Kept from the safety spec. These are not content checks — they're **physical-action** and **hardware-integrity** safeguards that remain meaningful under every threat model.

| Control | Level | Rationale |
|---|---|---|
| `payload_badusb_run` requires hold-to-confirm | **HIGH + hold** | Typing into a host is an irreversible physical act. Even on a payload the operator wrote themselves, a Claude hallucination triggering `run` at the wrong moment is exactly the "Claude-initiated drift" case the audit trail cannot undo after the fact. |
| `payload_subghz_tx` requires hold-to-confirm | **HIGH + hold** | Same reasoning. RF propagates beyond the operator's physical control; a misfired TX can't be clawed back. |
| 600-second continuous-TX cap | **Hard cap** | **Not a legal check — a hardware protection.** Prevents a stuck loop or hallucinated "transmit until stopped" from heating the transmitter, draining battery, or stressing antenna matching. If a legitimate engagement needs >600s of continuous TX, operator re-issues the tool call; the interruption is intentional. |
| `repeats` cap on `payload_subghz_tx` (MAX_TX_REPEATS = 100) | **Hard cap** | **Closes spec gap S5 / Phase 6 review H1.** `duration_s` is an operator-declared upper bound but is NOT forwarded to the CC1101 by the current tool. `repeats` IS forwarded, and the firmware loops until the count is exhausted — so an unbounded `repeats` value trivially bypasses the 600s duration cap. We considered computing estimated runtime from `SubFile` sample count × repeats but that requires real protocol-specific timing extraction (RAW_Data timing is not authoritatively parseable at this layer — see `subfile.py` comment). Hard-cap at 100 replays is the safer fallback; operator re-issues the call for more airtime. Both caps (duration_s and repeats) are enforced. |
| `factory_reset` unconditionally **BLOCKED** | **BLOCKED** | Unchanged from Phase 3. Zero legitimate pentest use case. If the operator truly needs to factory-reset they can do it via Flipper's physical menu. |
| All write paths emit a **DiffSummary** before approval | **Required** | Before editing any file on `/ext/`, the approval prompt shows what's changing. Even `MED`-level edits let the operator see the diff, not just the filename. |

## 4. Metadata and audit granularity

| Aspect | Decision | Notes |
|---|---|---|
| Sidecar `.vesper.json` → renamed `.echoforge.json` | **Claude auto-writes `policy_tag`** | Operator can override. Sidecar travels with the payload on `/ext/`. |
| Audit log payload content — hobbyist mode (**default**) | **Hash-only** (SHA-256) | What's logged: tool name, args, file path, content hash, timestamp, risk level, approval outcome. Not the full DuckyScript / .sub / .ir body. Safe to share as proof-of-behavior without leaking payload internals. |
| Audit log payload content — operator mode (**opt-in, Phase 4.5c**) | **Full verbatim content** in `content_blob` BLOB column | Opt-in via `--audit-mode=operator` (REPL) or `AgentConfig.audit_mode=AuditMode.OPERATOR` (programmatic). Captures the exact bytes of `write_file` and `payload_badusb_create` payloads. Scope is intentionally narrow: only primary-payload writes are captured; reads, physical actuations, and rename/copy/delete stay hash-only because there's nothing new to record. No redaction / sanitization is performed — full fidelity is the contract. **Consequence:** the audit DB becomes sensitive and is the operator's responsibility to protect at rest and in transit. See `src/echoforge/safety/audit.py` module docstring for the full safety note. |
| Schema migration for pre-4.5c DBs | **Forward-only ALTER TABLE** | `AuditService.__init__` probes `PRAGMA table_info(actions)` and adds `content_blob BLOB` if absent. Existing rows keep NULL (= hobbyist semantics). Idempotent on repeat open. |

## 5. Risk level mapping — final for Phase 6 implementation

All 13 tools from `PHASE6_PAYLOAD_FORGE_API.md`. `requires_hold` = `true` means a press-and-hold approval gesture, not one-tap. `diff` = a unified diff is shown to the operator at approval time.

| Tool | Risk | Hold | Diff | Notes |
|---|---|---|---|---|
| `payload_badusb_validate` | LOW | — | — | Pure lint, no side effects. Auto-approve. |
| `payload_badusb_create` | MED | — | **yes** | Writes a new `.txt` + `.echoforge.json` sidecar. Diff shown. |
| `payload_badusb_run` | **HIGH** | **yes** | — | Physical keystroke injection. Always hold-to-confirm. |
| `payload_subghz_list` | LOW | — | — | Directory read. Auto-approve. |
| `payload_subghz_inspect` | LOW | — | — | Parses headers of a `.sub` file. Auto-approve. |
| `payload_subghz_retune` | MED | — | **yes** | Headers-only write (Frequency / Preset swap; RAW_Data immutable). Diff shown. |
| `payload_subghz_import_capture` | MED | — | **yes** | Rename + sidecar creation after a capture. Diff shown. |
| `payload_subghz_tx` | **HIGH** | **yes** | — | Physical RF transmission. Always hold-to-confirm. **Subject to 600s cap** — implementation MUST reject calls whose declared duration exceeds 600s. |
| `payload_ir_list` | LOW | — | — | Directory read. Auto-approve. |
| `payload_ir_inspect` | LOW | — | — | Parses `.ir` blocks. Auto-approve. |
| `payload_ir_import_capture` | MED | — | **yes** | Rename + sidecar. Diff shown. |
| `payload_ir_transmit` | MED | — | — | Line-of-sight, low blast radius. MED (not HIGH) is deliberate — IR can't escape the room. One-tap approval. |
| `payload_library_search` | LOW | — | — | Reads `.echoforge.json` sidecars across `/ext/badusb`, `/ext/subghz`, `/ext/infrared`. Auto-approve. |

## 6. Explicit non-goals for Phase 6

Stated here so future contributors don't re-relitigate:

1. echoforge **will not** detect obfuscated or encoded payloads with any claim of confidence. If a payload is base64-encoded or routed through a PowerShell encoded-command block, the classifier cannot be trusted; the operator is accountable via the audit trail.
2. echoforge **will not** prevent a determined operator from running any payload they write manually via raw `Flipper.cli()` or direct RPC calls — those pathways deliberately bypass Payload Forge's typed interface. Payload Forge exists for Claude-mediated operator ergonomics, not as a security boundary between the operator and the hardware.
3. echoforge **will not** enforce jurisdictional legality of RF transmission frequencies, transmission durations beyond the 600s hardware cap, NFC emulation of third-party credentials, or BadUSB execution on hosts the operator does not own or has not been contracted to assess. These are engagement-level (ROE / SOW / authorization letter) concerns, not framework concerns.
4. echoforge **will not** ship an exploit library. It ships a payload *library* (authored artifacts: DuckyScripts, captured .sub files, IR dumps, NFC dictionaries) plus an *agent-orchestration* surface. Exploits live in external research repos; operator bundles what they need per engagement.

## 7. Forward-looking flags (not Phase 6 scope, but decisions will be revisited)

These items were raised during Phase 6 design and deferred:

1. **Operator/hobbyist audit-mode switch** — **DELIVERED in Phase 4.5c.** `AuditMode.HOBBYIST` (default) / `AuditMode.OPERATOR` (opt-in via `--audit-mode=operator`). See §4 for the tradeoff. Original target was Phase 4.5 and it landed there.
2. **Rules-of-Engagement envelope** — signed-JWT or PGP-signed `roe.json` at the engagement root that declares authorized targets, allowed frequencies, allowed duration, client authority. Before any HIGH action, tool checks the current target against the envelope. Target: **Phase 7** (ties into the engagement-report generator).
3. **Region profile for TX** — if future engagements have clients with strict "don't TX outside FCC Part 15" requirements, add an opt-in `region=US|EU|...` profile that echoforge enforces even when firmware would allow wider bands. Default stays: **no profile, pass through**. Target: **Phase 7 or later**.
4. **Multi-operator teamserver mode** — Sliver/Mythic pattern (operator ↔ core ↔ implant over mTLS/gRPC). Lets two operators co-drive an engagement. Target: **Phase 8+**.

## 8. Sidecar schema — normative for Phase 6 implementation

```json
{
  "schema_version": 1,
  "kind": "badusb" | "subghz" | "ir",
  "name": "Display name — free text.",
  "description": "One-paragraph description of what this payload does / where it came from / caveats.",
  "author": "Operator-provided. May be an engagement handle, not a real name.",
  "tags": ["rickroll", "demo", "capture-2026-04-22"],
  "policy_tag": "auto-generated by Claude at creation time. Short identifier (e.g. 'prank', 'credential-demo', 'vehicle-capture'). Operator-editable.",
  "content_hash": "sha256:<hex>",
  "created_at": "ISO-8601 UTC",
  "updated_at": "ISO-8601 UTC",
  "source": {
    "origin": "created" | "captured" | "imported",
    "captured_on": "ISO-8601 UTC (if captured)",
    "capture_freq_mhz": 433.92,
    "capture_protocol": "Princeton" (if known)
  },
  "engagement_ref": "optional — operator's engagement identifier; ties artifact to ROE envelope once §7.2 lands"
}
```

**Note on sidecar filename:** renamed from `.vesper.json` (per earlier spec) to `.echoforge.json` to match the rebrand.

---

## Approval chain summary

| Action shape | Gate | Operator experience |
|---|---|---|
| Read / list / inspect / search | LOW | Auto-approved silently (session-level `auto_approve_level >= LOW`). |
| Create / edit / rename / import | MED + diff | Approval panel shows unified diff + sidecar metadata; one-tap approve. |
| Run / transmit (physical action) | HIGH + hold | Approval panel shows the artifact content + target context; operator holds to confirm for ~800ms before the tool runs. |
| Factory reset | BLOCKED | Tool call fails with a clear message pointing to the Flipper's physical menu. |

End of decisions record.
