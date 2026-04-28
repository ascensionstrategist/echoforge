"""
Tests for the DuckyScript linter (`echoforge.payload.linter`) and its CLI
(`echoforge.payload.lint_cli`).

Structure:
  - TestRuleInventory: every rule code in the spec has a positive +
    negative case (one triggers, one doesn't).
  - TestCanonicalPayloads: the rickroll / hello-world reference payloads
    from `skills/.../common-patterns.md` must produce zero ERROR findings.
  - TestExitCodes: main() returns 0 on clean, 1 on W-only, 2 on E.
  - TestJSONFormat: stable wire format (snapshot).
  - TestFilters: --rules / --ignore behavior.
  - TestValidateStrict: `payload_badusb_validate` with `strict=True`
    returns lint findings; baseline behavior unchanged with strict
    unset.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from echoforge.payload.linter import (
    ALL_RULE_CODES,
    LintSeverity,
    lint,
)
from echoforge.payload.lint_cli import main as lint_cli_main

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _codes(report) -> set[str]:
    """Return the set of rule codes fired by a LintReport."""
    return {f.code for f in report.findings}


# ---------------------------------------------------------------------------
# Rule inventory — positive + negative case per rule
# ---------------------------------------------------------------------------


class TestRuleInventory:
    """Each registered rule must have at least one positive + negative case."""

    def test_all_rule_codes_are_documented(self):
        # Every rule in the enforced spec list should be present.
        expected = {
            "E001", "E002", "E003", "E004", "E005", "E006", "E007",
            "W001", "W002", "W003", "W004", "W005", "W006", "W007",
            "W008", "W009", "W010", "W011",
            "I001", "I002", "I003", "I004",
        }
        missing = expected - ALL_RULE_CODES
        assert not missing, f"missing rule codes: {missing}"

    # E001 - unknown command --------------------------------------------------

    def test_e001_positive_unknown_command(self):
        report = lint(
            "REM Target: Windows author\nDELAY 1000\nFROBNICATE 3\n"
        )
        assert "E001" in _codes(report)

    def test_e001_negative_known_commands(self):
        report = lint(
            "REM Title: hello\nREM Target: Windows, US layout\n"
            "DELAY 1000\nGUI r\nSTRING hi\nENTER\n"
        )
        assert "E001" not in _codes(report)

    # E002 - malformed numeric -----------------------------------------------

    def test_e002_positive_delay_text_arg(self):
        report = lint("REM Target: Windows\nDELAY abc\n")
        assert "E002" in _codes(report)

    def test_e002_negative_valid_delay(self):
        report = lint("REM Target: Windows\nDELAY 1000\n")
        assert "E002" not in _codes(report)

    # E003 - empty STRING -----------------------------------------------------

    def test_e003_positive_empty_string(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING\n")
        assert "E003" in _codes(report)

    def test_e003_negative_string_with_payload(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nSTRING something\n"
        )
        assert "E003" not in _codes(report)

    # E004 - HOLD without RELEASE --------------------------------------------

    def test_e004_positive_unclosed_hold(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nDELAY 100\n"
        )
        assert "E004" in _codes(report)

    def test_e004_negative_matched_hold_release(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nDELAY 100\nRELEASE CTRL\n"
        )
        assert "E004" not in _codes(report)

    # E005 - unknown key in combo --------------------------------------------

    def test_e005_positive_typo(self):
        report = lint("REM Target: Windows\nDELAY 1000\nCTRL-ALT-DLEETE\n")
        assert "E005" in _codes(report)

    def test_e005_negative_known_combo(self):
        report = lint("REM Target: Windows\nDELAY 1000\nCTRL-ALT-DELETE\n")
        assert "E005" not in _codes(report)

    # E006 - DEFAULTDELAY out of range ---------------------------------------

    def test_e006_positive_huge_default_delay(self):
        report = lint(
            "REM Target: Windows\nDEFAULTDELAY 20000\nDELAY 1000\n"
        )
        assert "E006" in _codes(report)

    def test_e006_negative_sane_default_delay(self):
        report = lint(
            "REM Target: Windows\nDEFAULTDELAY 50\nDELAY 1000\n"
        )
        assert "E006" not in _codes(report)

    # E007 - unsupported control flow (FOR / END_FOR / CALL only) -----------

    def test_e007_positive_for_loop(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nFOR $i IN (1 2 3)\nSTRING x\nEND_FOR\n"
        )
        assert "E007" in _codes(report)

    def test_e007_positive_call(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nCALL myfunc\n"
        )
        assert "E007" in _codes(report)

    def test_e007_negative_no_control_flow(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nREPEAT 3\nSTRING x\n"
        )
        assert "E007" not in _codes(report)

    def test_e007_negative_while_is_supported_per_matrix(self):
        """WHILE is supported on stock ≥0.85 per `flipper-extensions.md`."""
        report = lint(
            "REM Target: Windows\nDELAY 1000\nWHILE ($i < 3)\nSTRING x\nEND_WHILE\n"
        )
        # WHILE/END_WHILE must NOT trigger E007 anymore.
        assert "E007" not in _codes(report)
        # Nor E001 (it's matrix-supported, not unknown).
        assert "E001" not in _codes(report)

    def test_e007_negative_function_is_supported_per_matrix(self):
        """FUNCTION/END_FUNCTION are supported on stock ≥0.85."""
        report = lint(
            "REM Target: Windows\nDELAY 1000\n"
            "FUNCTION mything\nSTRING hi\nEND_FUNCTION\n"
        )
        assert "E007" not in _codes(report)
        assert "E001" not in _codes(report)

    # W001 - missing REM header ----------------------------------------------

    def test_w001_positive_no_header(self):
        report = lint("DELAY 1000\nSTRING hi\nENTER\n")
        assert "W001" in _codes(report)

    def test_w001_negative_header_present(self):
        report = lint(
            "REM Title: Hello\nREM Target: Windows, US layout\n"
            "REM Author: shawn\nDELAY 1000\nSTRING hi\n"
        )
        assert "W001" not in _codes(report)

    # W002 - STRING without preceding DELAY ----------------------------------

    def test_w002_positive_string_first(self):
        report = lint("REM Target: Windows\nSTRING hi\n")
        assert "W002" in _codes(report)

    def test_w002_negative_string_after_delay(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING hi\n")
        assert "W002" not in _codes(report)

    # W003 - STRING > 120 chars ----------------------------------------------

    def test_w003_positive_long_string(self):
        long_str = "a" * 130
        report = lint(f"REM Target: Windows\nDELAY 1000\nSTRING {long_str}\n")
        assert "W003" in _codes(report)

    def test_w003_negative_short_string(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING short\n")
        assert "W003" not in _codes(report)

    # W004 - many STRINGs, no DEFAULTDELAY ----------------------------------

    def test_w004_positive_many_strings(self):
        lines = ["REM Target: Windows", "DELAY 1000"] + [
            f"STRING line{i}" for i in range(6)
        ]
        report = lint("\n".join(lines) + "\n")
        assert "W004" in _codes(report)

    def test_w004_negative_with_default_delay(self):
        lines = [
            "REM Target: Windows",
            "DEFAULTDELAY 50",
            "DELAY 1000",
        ] + [f"STRING line{i}" for i in range(6)]
        report = lint("\n".join(lines) + "\n")
        assert "W004" not in _codes(report)

    # W005 - Hak5-only command -----------------------------------------------

    def test_w005_positive_wait_for_host(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nWAIT_FOR_HOST\nSTRING hi\n"
        )
        assert "W005" in _codes(report)

    def test_w005_negative_only_flipper_commands(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING hi\n")
        assert "W005" not in _codes(report)

    # W006 - platform-specific combo without hint ---------------------------

    def test_w006_positive_gui_r_no_hint(self):
        report = lint(
            "REM Title: something generic\nDELAY 1000\nGUI r\n"
        )
        assert "W006" in _codes(report)

    def test_w006_negative_gui_r_with_windows_hint(self):
        report = lint(
            "REM Target: Windows 10/11\nDELAY 1000\nGUI r\n"
        )
        assert "W006" not in _codes(report)

    # W007 - mixed-case keyword ----------------------------------------------

    def test_w007_positive_lowercase_delay(self):
        report = lint("REM Target: Windows\ndelay 1000\nSTRING hi\n")
        assert "W007" in _codes(report)

    def test_w007_negative_all_caps(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING hi\n")
        assert "W007" not in _codes(report)

    # W008 - trailing whitespace ---------------------------------------------

    def test_w008_positive_trailing_space(self):
        report = lint("REM Target: Windows\nDELAY 1000   \nSTRING hi\n")
        assert "W008" in _codes(report)

    def test_w008_negative_clean_lines(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING hi\n")
        assert "W008" not in _codes(report)

    # W009 - CRLF line endings -----------------------------------------------

    def test_w009_positive_crlf(self):
        report = lint("REM Target: Windows\r\nDELAY 1000\r\nSTRING hi\r\n")
        assert "W009" in _codes(report)

    def test_w009_negative_lf_only(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING hi\n")
        assert "W009" not in _codes(report)

    # W010 - ALT-STRING without firmware hint --------------------------------

    def test_w010_positive_alt_string_no_hint(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nALT-STRING somestuff\n"
        )
        assert "W010" in _codes(report)

    def test_w010_negative_alt_string_with_hint(self):
        report = lint(
            "REM Target: Windows\nREM Firmware: Momentum\n"
            "DELAY 1000\nALT-STRING something\n"
        )
        assert "W010" not in _codes(report)

    # W011 - HOLD/RELEASE with no DELAY between ------------------------------

    def test_w011_positive_no_delay_between(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nRELEASE CTRL\n"
        )
        assert "W011" in _codes(report)

    def test_w011_negative_delay_between(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nDELAY 50\nRELEASE CTRL\n"
        )
        assert "W011" not in _codes(report)

    # I001 - script > 200 lines ----------------------------------------------

    def test_i001_positive_long_script(self):
        lines = ["REM Target: Windows", "DELAY 1000"] + [
            f"STRING line{i}" for i in range(250)
        ]
        report = lint(
            "\n".join(lines) + "\n", ignore={"W003", "W004"}
        )
        assert "I001" in _codes(report)

    def test_i001_negative_short_script(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING hi\n")
        assert "I001" not in _codes(report)

    # I002 - >5 consecutive REMs ---------------------------------------------

    def test_i002_positive_many_rems(self):
        rems = "\n".join(f"REM line {i}" for i in range(8))
        report = lint(f"{rems}\nDELAY 1000\nSTRING hi\n")
        assert "I002" in _codes(report)

    def test_i002_negative_few_rems(self):
        report = lint(
            "REM one\nREM two\nREM three\nDELAY 1000\nSTRING hi\n"
        )
        assert "I002" not in _codes(report)

    # I003 - duplicate consecutive -------------------------------------------

    def test_i003_positive_duplicate(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nSTRING hi\nSTRING hi\n"
        )
        assert "I003" in _codes(report)

    def test_i003_negative_no_duplicates(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nSTRING hi\nSTRING bye\n"
        )
        assert "I003" not in _codes(report)

    # I004 - non-ASCII in STRING ---------------------------------------------

    def test_i004_positive_unicode(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nSTRING héllo café\n"
        )
        assert "I004" in _codes(report)

    def test_i004_negative_ascii(self):
        report = lint("REM Target: Windows\nDELAY 1000\nSTRING hello\n")
        assert "I004" not in _codes(report)


# ---------------------------------------------------------------------------
# Canonical payloads from the skill reference — must be ERROR-clean.
# ---------------------------------------------------------------------------


class TestCanonicalPayloads:
    """Reference payloads from `common-patterns.md` must be ERROR-clean."""

    def test_rickroll_no_errors(self):
        # Verbatim copy of the rickroll payload from common-patterns.md.
        script = (
            "REM Title: rickroll\n"
            "REM Target: Windows, macOS, Linux (tested), US layout\n"
            "REM Opens the default browser to a YouTube URL. Classic demo.\n"
            "DELAY 1000\n"
            "GUI r\n"
            "DELAY 500\n"
            "STRING https://youtu.be/dQw4w9WgXcQ\n"
            "DELAY 200\n"
            "ENTER\n"
        )
        report = lint(script)
        errors = [f for f in report.findings if f.severity == LintSeverity.ERROR]
        assert errors == [], f"unexpected errors: {errors}"

    def test_hello_world_no_errors(self):
        script = (
            "REM Title: hello-world\n"
            "REM Target: Windows 10/11, US layout\n"
            "REM Opens Notepad, types one line.\n"
            "DELAY 1000\n"
            "GUI r\n"
            "DELAY 500\n"
            "STRING notepad\n"
            "ENTER\n"
            "DELAY 1500\n"
            "STRING Hello from Flipper Zero BadUSB\n"
        )
        report = lint(script)
        errors = [f for f in report.findings if f.severity == LintSeverity.ERROR]
        assert errors == [], f"unexpected errors: {errors}"

    def test_app_launcher_no_errors(self):
        script = (
            "REM Title: app-launcher\n"
            "REM Target: Windows 10/11, US layout\n"
            "REM Opens Calculator, switches to programmer mode.\n"
            "DELAY 1000\n"
            "GUI r\n"
            "DELAY 500\n"
            "STRING calc\n"
            "ENTER\n"
            "DELAY 2500\n"
            "CTRL 4\n"
            "DELAY 800\n"
            "ALT h\n"
            "DELAY 400\n"
            "STRING DEADBEEF\n"
            "DELAY 200\n"
            "CTRL c\n"
            "DELAY 200\n"
        )
        report = lint(script)
        errors = [f for f in report.findings if f.severity == LintSeverity.ERROR]
        assert errors == [], f"unexpected errors: {errors}"


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------


class TestExitCodes:
    """CLI exit semantics: 0 clean, 1 W-only, 2 E."""

    def test_clean_file_exits_zero(self, tmp_path: Path):
        f = tmp_path / "rick.txt"
        f.write_text(
            "REM Title: rickroll\n"
            "REM Target: Windows, US layout\n"
            "DELAY 1000\n"
            "GUI r\n"
            "DELAY 500\n"
            "STRING https://example.com\n"
            "ENTER\n",
            encoding="utf-8",
        )
        rc = lint_cli_main([str(f)])
        assert rc == 0

    def test_warning_only_exits_one(self, tmp_path: Path):
        f = tmp_path / "w.txt"
        # No header → W001; that's a warning, not an error.
        f.write_text("DELAY 1000\nSTRING hi\nENTER\n", encoding="utf-8")
        rc = lint_cli_main([str(f)])
        assert rc == 1

    def test_error_exits_two(self, tmp_path: Path):
        f = tmp_path / "err.txt"
        # FOR → E007 (unsupported on Flipper per the matrix).
        f.write_text(
            "REM Target: Windows\n"
            "DELAY 1000\n"
            "FOR $i IN (1 2 3)\n"
            "STRING x\n"
            "END_FOR\n",
            encoding="utf-8",
        )
        rc = lint_cli_main([str(f)])
        assert rc == 2

    def test_missing_file_exits_two(self, tmp_path: Path):
        rc = lint_cli_main([str(tmp_path / "does_not_exist.txt")])
        assert rc == 2

    def test_directory_walks_txt_files(self, tmp_path: Path):
        (tmp_path / "payload.txt").write_text(
            "REM Title: demo\nREM Target: Windows, US layout\n"
            "DELAY 1000\nSTRING hi\n",
            encoding="utf-8",
        )
        (tmp_path / "readme.txt").write_text(
            "This is a README, not DuckyScript.\n",
            encoding="utf-8",
        )
        rc = lint_cli_main([str(tmp_path)])
        # Only payload.txt is linted; it's clean → rc 0.
        assert rc == 0


# ---------------------------------------------------------------------------
# JSON output stability (snapshot)
# ---------------------------------------------------------------------------


class TestJSONFormat:
    """The JSON wire format should be stable."""

    def test_json_schema_shape(self, tmp_path: Path, capsys):
        f = tmp_path / "p.txt"
        f.write_text(
            "REM Target: Windows\nDELAY abc\n", encoding="utf-8"
        )
        lint_cli_main([str(f), "--format=json"])
        out = capsys.readouterr().out.strip()
        # Must be one JSON object per line.
        for line in out.splitlines():
            data = json.loads(line)
            assert set(data.keys()) == {"file", "findings"}
            for finding in data["findings"]:
                assert set(finding.keys()) == {
                    "code", "severity", "line", "column",
                    "message", "suggestion",
                }
                assert finding["severity"] in {"error", "warning", "info"}
                assert isinstance(finding["line"], int)


# ---------------------------------------------------------------------------
# --rules / --ignore filtering
# ---------------------------------------------------------------------------


class TestFilters:
    """--rules and --ignore correctly filter the rule set."""

    def test_rules_allowlist_only_runs_given(self, tmp_path: Path):
        f = tmp_path / "p.txt"
        # Missing header (W001) AND lowercase 'delay' (W007).
        f.write_text("delay 1000\nSTRING hi\n", encoding="utf-8")
        report = lint(f.read_text(encoding="utf-8"), rules={"W001"})
        codes = _codes(report)
        assert "W001" in codes
        assert "W007" not in codes

    def test_ignore_suppresses_given(self):
        report = lint(
            "delay 1000\nSTRING hi\n", ignore={"W001"}
        )
        codes = _codes(report)
        assert "W001" not in codes
        assert "W007" in codes

    def test_cli_ignore_flag(self, tmp_path: Path, capsys):
        f = tmp_path / "p.txt"
        f.write_text("delay 1000\nSTRING hi\n", encoding="utf-8")
        # Ignore both warnings → clean (exit 0).
        rc = lint_cli_main([str(f), "--ignore=W001,W002,W007"])
        # Exit 1 or 0 depending on which other warnings remain. But
        # W001/W002/W007 should not appear in output.
        out = capsys.readouterr().out
        assert "W001" not in out
        assert "W007" not in out
        # rc may be 0 or 1 depending on remaining warnings; just make
        # sure the flag didn't crash.
        assert rc in {0, 1}

    def test_cli_list_rules_exits_zero(self, capsys):
        rc = lint_cli_main(["--list-rules", "dummy"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "E001" in out
        assert "W001" in out


# ---------------------------------------------------------------------------
# `payload_badusb_validate` strict=True integration
# ---------------------------------------------------------------------------


class TestValidateStrict:
    """The existing `payload_badusb_validate` tool must gain a strict
    path that returns lint findings, while keeping all existing
    non-strict tests green (that's enforced by the unchanged test
    class in `test_payload_tools.py`).
    """

    @pytest.mark.asyncio
    async def test_strict_returns_lint_findings(self):
        from echoforge.agent.tools_payload import build_payload_tools

        # Minimal fake Flipper — validate is pure, we only need the
        # tool to instantiate.
        class _StubFlipper:
            storage = object()
            badusb = object()
            ir = object()
            subghz = object()

        tools = build_payload_tools(_StubFlipper())
        tool = next(t for t in tools if t.name == "payload_badusb_validate")
        r = await tool.handler(
            {"script_text": "delay 1000\nSTRING hi\n", "strict": True}
        )
        # _ok() emits two content blocks: [0] status line, [1] JSON blob.
        data = json.loads(r["content"][1]["text"])
        assert "lint_findings" in data
        codes = {f["code"] for f in data["lint_findings"]}
        assert "W007" in codes  # lowercase 'delay'

    @pytest.mark.asyncio
    async def test_non_strict_default_unchanged(self):
        from echoforge.agent.tools_payload import build_payload_tools

        class _StubFlipper:
            storage = object()
            badusb = object()
            ir = object()
            subghz = object()

        tools = build_payload_tools(_StubFlipper())
        tool = next(t for t in tools if t.name == "payload_badusb_validate")
        r = await tool.handler({"script_text": "DELAY 100"})
        data = json.loads(r["content"][1]["text"])
        # No lint_findings key when strict is omitted.
        assert "lint_findings" not in data


# ---------------------------------------------------------------------------
# Round-1 review follow-ups (H1, H2, H3, M3, M2, M4, plus assorted)
#
# These tests guard the fixes from `docs/DUCKY_LINTER_CODE_REVIEW.md`.
# Each is named after the review finding it covers so a future regression
# is easy to map back to the spec.
# ---------------------------------------------------------------------------


class TestH1MomentumExtensionsNotE001:
    """H1: HOLD / RELEASE / ALT-STRING / WAIT_FOR_BUTTON_PRESS / SYSRQ /
    DEFAULTCHARDELAY are Momentum/Xtreme extensions per the matrix; the
    linter must NOT flag them as E001. Before the fix, every one fell
    through and emitted E001 — making W010/W011/E004 unreachable."""

    def test_momentum_hold_release_not_flagged_as_e001(self):
        # Reproducer verbatim from the review doc.
        report = lint(
            "REM Firmware: Momentum\n"
            "REM Target: Windows, US layout\n"
            "DELAY 1000\n"
            "HOLD CTRL\n"
            "DELAY 50\n"
            "RELEASE CTRL\n"
        )
        assert "E001" not in _codes(report), report.findings

    def test_momentum_alt_string_not_flagged_as_e001(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nALT-STRING café\n"
        )
        assert "E001" not in _codes(report), report.findings

    def test_momentum_wait_for_button_press_not_flagged_as_e001(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nWAIT_FOR_BUTTON_PRESS\nSTRING hi\n"
        )
        assert "E001" not in _codes(report), report.findings

    def test_momentum_sysrq_not_flagged_as_e001(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Linux\n"
            "DELAY 1000\nSYSRQ b\n"
        )
        assert "E001" not in _codes(report), report.findings

    def test_momentum_defaultchardelay_not_flagged_as_e001(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DEFAULTCHARDELAY 5\nDELAY 1000\nSTRING hi\n"
        )
        assert "E001" not in _codes(report), report.findings

    def test_w011_now_reachable(self):
        """Before H1, this triggered E001 for HOLD/RELEASE and W011 was
        dead. After H1, W011 actually fires."""
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nRELEASE CTRL\n"
        )
        codes = _codes(report)
        assert "E001" not in codes, report.findings
        assert "W011" in codes

    def test_e004_now_reachable(self):
        """Before H1, E004 was dead (E001 fired first). After H1, E004
        fires for unclosed HOLD."""
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD SHIFT\nDELAY 100\n"
        )
        codes = _codes(report)
        assert "E001" not in codes, report.findings
        assert "E004" in codes


class TestH2VarIfElseSupported:
    """H2: VAR / IF / ELSE / END_IF / WHILE / FUNCTION / $_RANDOM_* are
    supported on stock ≥0.85 per the compatibility matrix. The linter
    must NOT flag them as E001 or E007."""

    def test_var_if_else_not_flagged_as_e001(self):
        report = lint(
            "REM Target: Windows\n"
            "VAR $x = 5\n"
            "IF ($x > 3) THEN\n"
            "STRING big\n"
            "END_IF\n"
        )
        assert not report.has_errors, report.findings

    def test_else_branch_not_flagged_as_e001(self):
        report = lint(
            "REM Target: Windows\n"
            "VAR $x = 5\n"
            "IF ($x > 10) THEN\n"
            "STRING big\n"
            "ELSE\n"
            "STRING small\n"
            "END_IF\n"
        )
        assert not report.has_errors, report.findings

    def test_random_substitution_not_flagged_as_e001(self):
        # $_RANDOM_* tokens used standalone are accepted per the matrix.
        report = lint(
            "REM Target: Windows\nDELAY 1000\n$_RANDOM_LOWERCASE_LETTER\n"
        )
        assert "E001" not in _codes(report), report.findings

    def test_while_function_not_flagged_as_e007(self):
        # WHILE / END_WHILE / FUNCTION / END_FUNCTION are MATRIX-supported.
        report = lint(
            "REM Target: Windows\nDELAY 1000\n"
            "WHILE ($i < 3)\nSTRING x\nEND_WHILE\n"
            "FUNCTION my_helper\nSTRING y\nEND_FUNCTION\n"
        )
        codes = _codes(report)
        assert "E001" not in codes, report.findings
        assert "E007" not in codes, report.findings


class TestH3W002RealisticPattern:
    """H3: W002 must fire on the realistic timing-bug pattern:
    `STRING` immediately after `GUI`, `ENTER`, `CTRL` combos, etc."""

    def test_w002_positive_string_after_enter(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nENTER\nSTRING hi\n"
        )
        assert "W002" in _codes(report), report.findings

    def test_w002_positive_string_after_gui(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nGUI r\nSTRING hi\n"
        )
        assert "W002" in _codes(report), report.findings

    def test_w002_positive_string_after_ctrl_combo(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nCTRL c\nSTRING hi\n"
        )
        assert "W002" in _codes(report), report.findings

    def test_w002_positive_string_after_hold(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nDELAY 50\nRELEASE CTRL\nSTRING hi\n"
        )
        assert "W002" in _codes(report), report.findings

    def test_w002_message_names_previous_command(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\nENTER\nSTRING hi\n"
        )
        w002 = next(f for f in report.findings if f.code == "W002")
        assert "ENTER" in w002.message

    def test_w002_negative_string_after_delay_still_clean(self):
        # Pre-existing positive case must still pass.
        report = lint(
            "REM Target: Windows\nDELAY 1000\nGUI r\nDELAY 500\nSTRING hi\n"
        )
        assert "W002" not in _codes(report)


class TestM3NegativeTestsTightened:
    """M3: All negative-case tests use `not report.has_errors` for
    firmware-legit payloads. These mirror the original negative tests
    but assert the stronger predicate."""

    def test_w011_negative_no_unrelated_errors(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nDELAY 50\nRELEASE CTRL\n"
        )
        assert not report.has_errors, report.findings

    def test_w010_negative_no_unrelated_errors(self):
        report = lint(
            "REM Target: Windows\nREM Firmware: Momentum\n"
            "DELAY 1000\nALT-STRING something\n"
        )
        assert not report.has_errors, report.findings

    def test_e004_negative_no_unrelated_errors(self):
        report = lint(
            "REM Firmware: Momentum\nREM Target: Windows\n"
            "DELAY 1000\nHOLD CTRL\nDELAY 100\nRELEASE CTRL\n"
        )
        assert not report.has_errors, report.findings

    def test_var_if_negative_no_unrelated_errors(self):
        report = lint(
            "REM Target: Windows\nDELAY 1000\n"
            "VAR $count = 3\n"
            "IF ($count > 0) THEN\nSTRING ok\nEND_IF\n"
        )
        assert not report.has_errors, report.findings


class TestM2HeuristicAccuracy:
    """M2: `_looks_like_duckyscript` must not match arbitrary `.txt`
    files starting with 'F' (e.g. email headers, Fortran code)."""

    def test_heuristic_does_not_match_random_F_prefix(self, tmp_path: Path):
        from echoforge.payload.lint_cli import _looks_like_duckyscript
        # Email-style file. Was incorrectly classified as DuckyScript pre-fix.
        f = tmp_path / "email.txt"
        f.write_text("From: alice@example.com\nTo: bob@example.com\n", encoding="utf-8")
        assert _looks_like_duckyscript(f) is False
        # Word starting with F that isn't an F-key.
        f2 = tmp_path / "foo.txt"
        f2.write_text("Foo bar\nbaz\n", encoding="utf-8")
        assert _looks_like_duckyscript(f2) is False
        # Fortran-ish.
        f3 = tmp_path / "fortran.txt"
        f3.write_text("Fortran is a language.\n", encoding="utf-8")
        assert _looks_like_duckyscript(f3) is False

    def test_heuristic_matches_real_F_keys(self, tmp_path: Path):
        from echoforge.payload.lint_cli import _looks_like_duckyscript
        for name, content in [
            ("a.txt", "F1\n"),
            ("b.txt", "F12\n"),
            ("c.txt", "F24\n"),
        ]:
            f = tmp_path / name
            f.write_text(content, encoding="utf-8")
            assert _looks_like_duckyscript(f) is True, name

    def test_heuristic_rejects_F_above_24(self, tmp_path: Path):
        from echoforge.payload.lint_cli import _looks_like_duckyscript
        f = tmp_path / "f25.txt"
        f.write_text("F25 is not a valid F-key\n", encoding="utf-8")
        assert _looks_like_duckyscript(f) is False


class TestM4SingleRemHeader:
    """M4: A single REM line declaring `Target:` should be enough to
    suppress W001."""

    def test_single_rem_with_target_does_not_trigger_w001(self):
        report = lint("REM Target: Windows, US layout\nDELAY 1000\nSTRING hi\n")
        assert "W001" not in _codes(report)

    def test_single_rem_with_author_does_not_trigger_w001(self):
        report = lint("REM Author: shawn\nDELAY 1000\nSTRING hi\n")
        assert "W001" not in _codes(report)

    def test_no_rem_still_triggers_w001(self):
        # The existing positive case — must still fire.
        report = lint("DELAY 1000\nSTRING hi\nENTER\n")
        assert "W001" in _codes(report)


class TestL3RulesIgnorePrecedence:
    """L3: When a code appears in both --rules and --ignore, ignore wins."""

    def test_ignore_wins_over_rules(self):
        # W001 in BOTH allowlist and denylist → must be skipped.
        report = lint(
            "DELAY 1000\nSTRING hi\n",
            rules={"W001", "W007"},
            ignore={"W001"},
        )
        codes = _codes(report)
        assert "W001" not in codes
        # W007 still active because it's in --rules and not in --ignore.
        # (In this fixture there's no lowercase keyword so W007 doesn't fire,
        # but rule presence is what we're asserting.)


class TestL4MacosDetection:
    """L4: W006 macOS detection should match macos / macOS / OSX /
    Darwin / macintosh / mac-os / mac, not the literal substring 'mac '."""

    def test_macos_lowercase_detected(self):
        report = lint("REM Target: macos\nDELAY 1000\nGUI SPACE\n")
        assert "W006" not in _codes(report)

    def test_macos_mixed_case_detected(self):
        report = lint("REM Target: macOS Sonoma\nDELAY 1000\nGUI SPACE\n")
        assert "W006" not in _codes(report)

    def test_osx_detected(self):
        report = lint("REM Target: OSX 10.15\nDELAY 1000\nGUI SPACE\n")
        assert "W006" not in _codes(report)

    def test_darwin_detected(self):
        report = lint("REM Target: Darwin\nDELAY 1000\nGUI SPACE\n")
        assert "W006" not in _codes(report)

    def test_macintosh_detected(self):
        report = lint("REM Target: Macintosh\nDELAY 1000\nGUI SPACE\n")
        assert "W006" not in _codes(report)


class TestI4GitHubFormat:
    """I4: GitHub Actions output format shape."""

    def test_format_github_output_shape(self, tmp_path: Path, capsys):
        f = tmp_path / "p.txt"
        # Trigger E002: malformed DELAY argument.
        f.write_text("REM Target: Windows\nDELAY abc\n", encoding="utf-8")
        rc = lint_cli_main([str(f), "--format=github"])
        out = capsys.readouterr().out
        assert rc == 2
        # GitHub annotation lines start with `::error|warning|notice `.
        lines = [line for line in out.splitlines() if line.startswith("::")]
        assert lines, f"no annotations: {out!r}"
        for line in lines:
            assert line.startswith(("::error ", "::warning ", "::notice "))
            # Must contain file=, line=, title=.
            assert "file=" in line
            assert "line=" in line
            assert "title=" in line


class TestIterRulesPublicAPI:
    """L2: `iter_rules()` is the public introspection accessor."""

    def test_iter_rules_yields_all_codes(self):
        from echoforge.payload.linter import ALL_RULE_CODES, iter_rules
        codes = {entry[0] for entry in iter_rules()}
        assert codes == ALL_RULE_CODES

    def test_iter_rules_tuple_shape(self):
        from echoforge.payload.linter import LintSeverity, iter_rules
        for code, severity, description in iter_rules():
            assert isinstance(code, str)
            assert isinstance(severity, LintSeverity)
            assert isinstance(description, str)
            assert description  # non-empty


# ---------------------------------------------------------------------------
# Canonical-payload non-regression — must hold across rule edits.
# ---------------------------------------------------------------------------


class TestCanonicalPayloadsZeroFindings:
    """All five canonical payloads from `common-patterns.md` must
    produce ZERO findings (zero errors AND zero warnings)."""

    HELLO = (
        "REM Title: hello-world\n"
        "REM Target: Windows 10/11, US layout\n"
        "REM Opens Notepad, types one line, saves nothing.\n"
        "DELAY 1000\n"
        "GUI r\n"
        "DELAY 500\n"
        "STRING notepad\n"
        "ENTER\n"
        "DELAY 1500\n"
        "STRING Hello from Flipper Zero BadUSB\n"
    )
    RICKROLL = (
        "REM Title: rickroll\n"
        "REM Target: Windows, macOS, Linux (tested), US layout\n"
        "REM Opens the default browser to a YouTube URL. Classic demo.\n"
        "DELAY 1000\n"
        "GUI r\n"
        "DELAY 500\n"
        "STRING https://youtu.be/dQw4w9WgXcQ\n"
        "DELAY 200\n"
        "ENTER\n"
    )
    CLIPBOARD = (
        "REM Title: clipboard-demo\n"
        "REM Target: Windows 10/11, US layout\n"
        "REM Demonstrates using PowerShell to stage a string on the clipboard without pasting.\n"
        "REM Useful as a building block; change the STRING to whatever you want staged.\n"
        "DELAY 1000\n"
        "GUI r\n"
        "DELAY 500\n"
        "STRING powershell -w hidden -NoProfile -c "
        "\"Set-Clipboard -Value 'demo-value-from-flipper'\"\n"
        "DELAY 200\n"
        "ENTER\n"
        "DELAY 800\n"
        "REM Window closes itself because the command completes "
        "and no further input is pending.\n"
    )
    BROWSER = (
        "REM Title: browser-open-crossplatform\n"
        "REM Target: Windows, macOS, Linux (GNOME/KDE)\n"
        "REM Uses platform-specific spotlight/run equivalents; "
        "relies on firmware-set keyboard layout.\n"
        "\n"
        "REM --- Windows path ---\n"
        "DELAY 1000\n"
        "GUI r\n"
        "DELAY 400\n"
        "STRING https://example.com\n"
        "ENTER\n"
        "DELAY 300\n"
        "\n"
        "REM If nothing happened (non-Windows target), fall through to macOS\n"
        "GUI SPACE\n"
        "DELAY 400\n"
        "STRING open https://example.com\n"
        "ENTER\n"
    )
    APP_LAUNCHER = (
        "REM Title: app-launcher\n"
        "REM Target: Windows 10/11, US layout\n"
        "REM Opens Calculator, switches to programmer mode, types a hex value.\n"
        "REM Showcases: modifier + key, CTRL-tab navigation inside app.\n"
        "\n"
        "DELAY 1000\n"
        "GUI r\n"
        "DELAY 500\n"
        "STRING calc\n"
        "ENTER\n"
        "DELAY 2500\n"
        "REM Calc UWP cold-start is slow; budget 2-3s.\n"
        "\n"
        "REM Switch to Programmer mode: Ctrl+4 in modern Calculator\n"
        "CTRL 4\n"
        "DELAY 800\n"
        "\n"
        "REM Switch to HEX: Alt+H (underlined in the mode toggle)\n"
        "ALT h\n"
        "DELAY 400\n"
        "\n"
        "REM Type a hex value\n"
        "STRING DEADBEEF\n"
        "DELAY 200\n"
        "\n"
        "REM Copy the decimal equivalent with Ctrl+C (decimal is shown in the sidebar)\n"
        "CTRL c\n"
        "DELAY 200\n"
    )

    @pytest.mark.parametrize(
        "name,script",
        [
            ("hello-world", HELLO),
            ("rickroll", RICKROLL),
            ("clipboard-demo", CLIPBOARD),
            ("browser-open-crossplatform", BROWSER),
            ("app-launcher", APP_LAUNCHER),
        ],
    )
    def test_canonical_payload_zero_findings(self, name: str, script: str):
        report = lint(script)
        assert report.findings == (), (
            f"{name} regressed — unexpected findings: {report.findings}"
        )
