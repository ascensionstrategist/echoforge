# DuckyScript Linter — Code Review (Round 2 — fix-up review)

**Reviewer:** code-reviewer subagent (round-2, id `ab9e226095ea59edc`)
**Date:** 2026-04-23
**Verdict:** **APPROVED.** All four round-1 blockers (H1/H2/H3/M3) correctly resolved. Bonus E005 carve-out precisely scoped. Linter is **ready for README promotion.**

| Metric | Result |
|---|---|
| Overall Assessment | Excellent |
| Security Score | A |
| Maintainability | A |
| Test Coverage | 385 passed (was 341), +44 new |

---

## Verification per claim

### H1 ✅ — Momentum extensions correctly carved out
- `_MOMENTUM_EXTENSIONS` frozenset at `linter.py:191-264` covers HOLD, RELEASE, ALT-STRING, ALTSTRING, ALT-CHARS, WAIT_FOR_BUTTON_PRESS, DEFAULTCHARDELAY, SYSRQ, media keys.
- E001 carve-out at `linter.py:328-369` keys on exact-match frozenset membership.
- W010, W011, E004 are now reachable (no longer dead code).
- 7 net-new tests in `TestH1*` ratify each Momentum extension fix.

### Bonus — E005 carve-out for ALT-STRING (precisely scoped)
- Without it, ALT-STRING failed E005 even after H1's E001 fix (parser misclassifies `ALT-STRING` as a hyphen combo).
- Carve-out at `linter.py:489-491` keys on `c.command in _MOMENTUM_EXTENSIONS`.
- **Verified by tracing parser output:**
  - `ALT-STRING hi` → command `"ALT-STRING"` (in set) → E005 suppressed, W010 fires ✓
  - `ALT-EVIL_KEY hi` → command `"ALT-EVIL_KEY"` (NOT in set) → E005 fires correctly ✓
  - `CTRL-FROBNICATE` → E005 fires correctly ✓
- **No bypass attack surface.** Exact-match against a frozenset literal, not a prefix scan.

### H2 ✅ — Matrix reconciliation faithful
- `_SUPPORTED_PER_MATRIX` at `linter.py:249-270` covers all matrix-Y rows missing from parser's `RECOGNISED_COMMANDS`.
- `_UNSUPPORTED_CF_3_0` correctly narrowed from 7 entries to `{FOR, END_FOR, CALL}` per the matrix.
- Matrix-N items (`$_SYSTEM_BITS`, `$_HOST_*`, `IMPORT`, `REM_BLOCK`) correctly fall through to E001.
- `ELSE_IF` token included alongside `ELSE` + `IF` to handle both spellings.
- Inline citation comments back to `flipper-extensions.md` so future drift is caught.

### H3 ✅ — W002 `else: yield` branch correct
- Branch at `linter.py:624-636`. Yields with the previous command's name in the message.
- `prev` correctly excludes REM (filtered at line 597 by `commands = [c for c in ctx.parsed.commands if c.command != "REM"]`).
- Five new positive tests cover the failure-mode patterns: `ENTER → STRING`, `GUI r → STRING`, `CTRL c → STRING`, `HOLD → STRING`, `RELEASE → STRING`.

### M3 ✅ — Negative-case tests tightened
- `TestM3NegativeTestsTightened` (lines 797-829) covers W011/W010/E004/VAR-IF with `not report.has_errors`.
- The remaining `not in codes` matches in tests (lines 544, 551, 692, 703, 749, 750, 898) are all intentional — testing rule-specific suppression OR confirming carve-outs explicitly verify E001/E007 do NOT fire alongside whatever else is being tested.
- The pre-existing weak `test_w011_negative_delay_between` (line 309) is preserved alongside the parallel TestM3 case (line 802) supplying the stronger assertion. Acceptable: legacy preserved + regression net added.

### Pre-existing test rewrites ✅
- `test_e007_positive_while` renamed → `test_e007_positive_for_loop` (line 140). Semantically clearer, accurate to current behavior.
- `test_error_exits_two` (line 468) now uses FOR instead of WHILE. Still tests "error → exit 2." Coverage preserved.
- New positive: `test_e007_positive_call` (line 146).
- New negatives: `test_e007_negative_while_is_supported_per_matrix`, `test_e007_negative_function_is_supported_per_matrix` (lines 158, 168) lock in the matrix-reconciled behavior.

### Canonical-payload non-regression ✅
- `TestCanonicalPayloadsZeroFindings` (lines 972-1080) parametrizes all 5 patterns from `common-patterns.md`.
- All 5 produce zero findings (assertion is `report.findings == ()` — strictly zero, not just zero errors).
- Bodies are inlined as class-level constants. Diff-checked against `references/common-patterns.md`: all 5 match verbatim modulo whitespace.
- **Minor follow-up (non-blocking):** consider loading from disk in a future PR for drift-resistance.

### MEDIUM/LOW spot-checks ✅
- **M2** — `r"^F([1-9]|1[0-9]|2[0-4])$"` at `lint_cli.py:44`. Rejects F0/F25/From:/Foo, accepts F1/F12/F24.
- **M4** — `len(header) < 1` at `linter.py:577`. 1-REM-with-Target payload no longer trips W001.
- **L4** — `r"\b(macos|mac|darwin|osx|macintosh)\b"` with `.lower()` upstream (line 724). Functionally case-insensitive.
- **I2** — `LintReport.findings: tuple[LintFinding, ...]` immutable, `frozen=True` confirmed. No tests mutate.
- **I4** — `test_format_github_output_shape` (line 932) asserts `::error|::warning|::notice ` prefix, `file=`/`line=`/`title=` present. Exit code 2 confirmed.

### Regression ✅
- 385 passed, 0 failed (verified locally).
- `ruff check src/echoforge/payload/ tests/test_duckyscript_linter.py` → "All checks passed!".
- 71 baseline + 81 Phase 6 tests untouched.

---

## Minor Suggestions (non-blocking — Phase 6.2 or later)

1. **Canonical-payload bodies inlined** in `TestCanonicalPayloadsZeroFindings` — load from disk in a future PR to prevent drift if `references/common-patterns.md` is edited.
2. **W007 `_CANONICAL_UPPER` set** doesn't include `IF`/`ELSE`/`END_IF`/`WHILE`/`FUNCTION`/`VAR` — lowercase forms of these will silently slip through. Bundle into next style-rule pass.
3. **Old weak `test_w011_negative_delay_between`** (line 309) is now redundant; safe to delete in a cleanup PR alongside #1.

---

## Positive Highlights

- E005 carve-out scoping is **exact-match against a frozenset** — not a prefix or substring check — closing the obvious bypass concern. Defensive design.
- `_SUPPORTED_PER_MATRIX` and `_UNSUPPORTED_CF_3_0` carry inline citation comments back to `flipper-extensions.md`. Future drift caught at review time.
- 7 net-new tests in `TestH1*` directly ratify each Momentum extension fix, making future regressions trivial to localize.
- W002 message names the offending previous command (`"STRING after \`ENTER\`..."`) — actionable for the operator.
- Suite went from 341 → 385 (+44 tests) with no drops or skips.

---

## Verdict

**APPROVED. Linter is ready for README promotion.** All round-1 blockers correctly fixed, bonus E005 catch precisely scoped, matrix reconciliation faithful to `flipper-extensions.md`, canonical payloads still zero-finding, ruff clean.

Relevant files reviewed:
- `src/echoforge/payload/linter.py`
- `src/echoforge/payload/lint_cli.py`
- `src/echoforge/payload/duckyscript.py` (untouched per spec, verified)
- `src/echoforge/payload/__init__.py`
- `tests/test_duckyscript_linter.py`
- `skills/echoforge-flipper-mastery/skills/echoforge-duckyscript/references/flipper-extensions.md`
- `skills/echoforge-flipper-mastery/skills/echoforge-duckyscript/references/common-patterns.md`

---

## Round 1 (archived — see git history for the full original review)

Round-1 verdict was APPROVED WITH FOLLOW-UPS, blocking on H1 (Momentum extensions falsely flagged E001), H2 (VAR/IF/ELSE contradicting skill matrix), H3 (W002 missing else-yield branch), M3 (negative tests too weak). All resolved in this round + bonus E005 carve-out + bundled M1/M2/M4/L1-L5/I1-I4.
