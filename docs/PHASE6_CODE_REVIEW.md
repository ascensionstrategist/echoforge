# Phase 6 Payload Forge — Code Review

**Round 2 — 2026-04-23 — fix-up review**
**Reviewer:** code-reviewer subagent (round-2 verification, id `ad065716bb44edd08`)
**Baseline under review:** round-1 verdict **BLOCKED** (id `a41fdc6a77474643d`) with 2 CRITICAL + 1 HIGH + 5 MEDIUM + 9 coverage gaps. Python-expert pass id `a4ecb2588446165c0` claimed all 15 items addressed.
**Tests:** 254 passed in ~1.2s locally. Ruff clean on all six modified files (`policy.py`, `risk.py`, `hooks.py`, `tools_payload.py`, `library.py`, `sidecar.py`).
**Baseline safety tests:** 81 (policy 20 + risk 22 + permissions 17 + diff 13 + audit 9). Matches author's claim. No existing-test modifications detected in baseline files.

## Verdict

**APPROVED WITH FOLLOW-UPS.** All 12 fix-up items are genuinely addressed. Two minor items (F1, F2 below) are worth tracking as Phase 6.1 but are not safety-critical. **Phase 6 can close.**

---

## Verification per claim

### C1 — DiffSummary for MED-write payload actions: VERIFIED
- `_DIFFABLE_ACTIONS` dict at `policy.py:47-53` lists all four payload MED-write actions plus `write_file`. Gate at line 160 correctly dispatches.
- `_build_diff` (policy.py:194-316) produces a populated `DiffSummary` via `summarize_write` for every branch. `summarize_write` always returns non-None — verified in `diff.py:133-188`.
- `hooks.py:_resolve_diff_target_path` (40-86) handles write_file + all four payload MED-write actions. Args without required keys return None correctly (no crash).
- Five new `TestPayloadDiffEmission` tests (`test_policy.py:124-215`) assert `diff is not None` for each action + path-content check (e.g. `"/ext/badusb/rickroll.txt" in d.diff.path`, `"315000000" in d.diff.diff_text`).

**F1 (follow-up, non-blocking):** `hooks.py:68-73` resolves `payload_subghz_retune` current_content from the *dest* path, not `source_path`. This is semantically correct (the diff represents the new file being written at dest; a fresh dest file means current_content=None → "new file" preview). The round-1 review's hint to read `source_path` would have produced a nonsense diff. Current implementation is better than the hint. **Recommend a clarifying comment** in `_resolve_diff_target_path` to prevent future "should we also read source?" confusion.

### C2.1 — Path confinement helpers: VERIFIED
- Regex in `tools_payload.py:95-99` matches API §3.1 **character-for-character** for all three kinds.
- `..` rejection at line 132 is a literal substring check — stricter than needed (also blocks `foo..bar`) but safe.
- **Call site audit:** 10 `_check_path` + 2 `_check_subdir` + 2 `_check_dest_name` = 14 total. Author claimed "12" — imprecise but coverage is complete. Every path-taking tool gates. `payload_library_search` takes no path; `payload_badusb_validate` is pure.
- **Post-synthesis re-check:** retune (611) and import_capture (1121) both re-apply `_check_path` on synthesized `dest_path`. ✓

### C2.2 — `source_path` in `_PATH_ARG_FIELDS`: VERIFIED
`risk.py:152-158` tuple now includes `"source_path"`. `TestPayloadSourcePathIntegration` (`test_risk.py:96-123`) locks in three scenarios (`/int/bondkeys.key`, `.nfckey` extension, `/int/secret.ir`), all asserting `RiskLevel.BLOCKED`.

### C2.3 — Escalation allowlist extended: VERIFIED
`risk.py:256-265` extends allowlist with `payload_badusb_create`, `payload_subghz_retune`, `payload_subghz_import_capture`, `payload_ir_import_capture` — all four MED-write action names match `ACTION_RULES` keys exactly. In practice this allowlist is largely redundant because `_check_path` rejects paths outside `/ext/<kind>/` *before* the RiskAssessor ever sees a synthesized path, but defense-in-depth is the right posture.

### H1 — `MAX_TX_REPEATS=100` hard cap: VERIFIED
- Module-level constant at `tools_payload.py:82`. Visible in `__all__`.
- Enforcement at lines 809-822 occurs **pre-hardware** — before `_run()` which contains `flipper.subghz.transmit_from_file` at line 825.
- `TestSubghzTxRepeatsCap`: `repeats=MAX_TX_REPEATS` (boundary allowed, 918), `repeats=1_000_000` (rejected, 929), `repeats=0` (rejected), bad type (rejected).
- Decision to hard-cap rather than compute from SubFile × repeats documented inline (77-82) and in DECISIONS §3.

**F2 (follow-up, non-blocking):** No test at `repeats=101` (just-over boundary). The `1_000_000` test exercises the same code path, so functional coverage is complete, but a `101` test would make boundary semantics explicit. One-line addition.

### H3 — `policy_tag` schema field: VERIFIED
Schema on `payload_badusb_create` (313), `payload_subghz_import_capture` (731), `payload_ir_import_capture` (953). Type validation at tool entry (348-352, 1129-1133). Claude supplies; Python never auto-generates. `TestPolicyTagRoundTrip` (`test_payload_tools.py:1033-1099`) covers all three tools + the None-when-omitted case.

### M1 — Sidecar read-back failure: VERIFIED
`_import_capture_generic` (1159-1172) returns `E_SIDECAR_WRITE_FAILED` on read-back exception. `TestSidecarReadBackFailure` (`test_payload_tools.py:981-1001`) plants a storage that raises on read of the renamed file and asserts (a) error code, (b) no sidecar written with hash-of-empty.

### M2 — Drift detection: VERIFIED
- `LibraryEntry.drifted: bool = False` (library.py:97).
- `_iter_device_entries` (192-203) reads the payload file, hashes via `compute_content_hash_bytes`, compares to `sidecar.content_hash`. Skips check when sidecar is None or content_hash is empty (legacy tolerance).
- `compute_content_hash` (path-based, sidecar.py:100) and `compute_content_hash_bytes` (in-memory, sidecar.py:116) both produce `sha256:<hex>`. Consistent.
- User-visible: `tools_payload.py:1051` propagates `"drifted": h.drifted` into `payload_library_search` results.
- Four drift tests in `TestDriftDetection` (match / mismatch / empty-hash legacy / no-sidecar).

### M3 — Retune sidecar inheritance: VERIFIED
Lines 658-691 load source sidecar if present, inherit author/tags/description/policy_tag. Caller-supplied description overrides (682). `TestRetuneInheritance` covers both full-inherit and description-override scenarios.

### M4 — Narrow exception catch: VERIFIED
Line 368: `except (RpcError, FileNotFoundError): pass`. `TimeoutError` propagates to `_with_recovery`.

### M5 — Error-code reclassification: VERIFIED
Lines 619-640 for retune split `FileNotFoundError` / `RpcError(ERROR_STORAGE_NOT_EXIST)` → `E_PATH_NOT_FOUND`, all other failures → `E_STORAGE_READ_FAILED`. `TestRetuneErrorCodes` plants `PermissionError` and asserts `E_STORAGE_READ_FAILED` appears and `E_PATH_NOT_FOUND` does not. `payload_ir_inspect` and `payload_ir_transmit` apply the same split. API.md §4 extended.

### Coverage gaps 1-9: VERIFIED
35 new tests present and genuinely exercise the right paths. Sampled:
- **Gap 2 (path confinement):** 6 tests across BadUSB/Sub-GHz/IR including synthesized-path escape (`dest_name="../../int/x"`). ✓
- **Gap 3 (repeats cap):** 4 tests including boundary + gross-over. ✓ (minor: `101` boundary not explicitly tested — F2).
- **Gap 4 (drift):** 4 tests. ✓
- **Gap 7 (validate edge cases):** non-string → E_UNSUPPORTED_ARG; empty string → ok=True. ✓
- **Gap 9 (IR import sidecar fields):** `test_author_tags_description_persisted_in_sidecar` round-trips all four fields + kind. ✓

Tests check behavior, not implementation details — they inspect sidecar JSON, storage write logs, and hardware call logs (the operator-visible surface).

### Regression check: VERIFIED
81 baseline safety tests all green. No modifications to existing test classes detected. New tests are additive (`TestPayloadDiffEmission`, `TestPayloadSourcePathIntegration`, `TestPayloadEscalation`).

---

## Positives

1. **Defense-in-depth layering** — `_check_path` at tool layer + `source_path` in `_PATH_ARG_FIELDS` + escalation allowlist. Three independent gates; any one would block the original C2 exploit path.
2. **Non-blocking sidecar semantics preserved** — `payload_badusb_create` treats sidecar write failure as non-fatal (logs + surfaces in response) because it has the bytes in hand; `_import_capture_generic` treats read-back failure as fatal (E_SIDECAR_WRITE_FAILED) because it doesn't. Correct distinction.
3. **Post-synthesis re-check on dest_path** — belt-and-braces means a regression in `_check_dest_name` or join logic can't silently produce an out-of-confinement path.
4. **Drift detection cost is bounded** — one extra `storage.read` per payload at search time, skipped when no sidecar or no hash. Documented as "cheap at hobbyist scale".
5. **Inline rationale for hard-cap over computed duration** (tools_payload.py:77-82) — future reviewers don't re-litigate the design.

---

## Follow-ups for Phase 6.1 (non-blocking)

- **F1** Add one-line comment in `hooks.py:_resolve_diff_target_path` retune branch clarifying dest_path (not source_path) is intentional.
- **F2** Add test `test_repeats_just_over_cap_rejected` with `repeats=101` to make boundary explicit alongside the `1_000_000` gross-over case.
- **F3** Consider removing the now-redundant escalation-allowlist entries for payload actions (C2.3) in a future cleanup pass, since `_check_path` makes those code paths unreachable. Optional — defense-in-depth is the safer posture.

---

## Verdict

**APPROVED WITH FOLLOW-UPS.** All 12 claimed fixes are genuinely in place and correctly address the round-1 findings. 254/254 tests green, ruff clean, baseline 81 safety tests intact. The two CRITICAL findings (C1 DiffSummary gap, C2 path-confinement bypass) and the HIGH finding (H1 repeats-cap bypass) are closed; the five MEDIUMs and nine coverage gaps are addressed with targeted tests that verify operator-visible behavior. **Phase 6 can close.**

---

## Round 1 (archived below — superseded by round 2 above)

_The original round-1 BLOCKED review content has been superseded. The full round-1 action checklist was:_

- C1 DiffSummary wiring for payload MED-writes
- C2.1 Path confinement helpers + `E_PATH_OUTSIDE_ALLOWED`
- C2.2 `source_path` in `_PATH_ARG_FIELDS`
- C2.3 Escalation allowlist OR synthesized-path
- H1 Cap `repeats` in `payload_subghz_tx`
- H3 `policy_tag` Claude-writable
- M1 `E_SIDECAR_WRITE_FAILED` (not `sha256(b"")`)
- M2 Drift detection in library
- M3 Retune inherits source sidecar
- M4 Narrow `except` catches
- M5 Error-code reclassification
- 9 coverage gaps

_All 12 items verified ✅ in round 2._
