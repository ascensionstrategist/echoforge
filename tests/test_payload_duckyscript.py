"""Unit tests for the DuckyScript parser / validator."""

from __future__ import annotations

from echoforge.payload.duckyscript import (
    ParseResult,
    iter_strings,
    parse_script,
)


class TestBasicParsing:
    def test_empty_script(self):
        r = parse_script("")
        assert r.ok
        assert r.commands == []
        assert r.diagnostics == []

    def test_whitespace_only_script(self):
        r = parse_script("\n\n   \n\n")
        assert r.ok
        assert r.commands == []

    def test_single_rem_comment(self):
        r = parse_script("REM This is a comment")
        assert r.ok
        assert len(r.commands) == 1
        assert r.commands[0].command == "REM"
        assert r.commands[0].args == "This is a comment"

    def test_delay_integer(self):
        r = parse_script("DELAY 500")
        assert r.ok
        assert r.commands[0].command == "DELAY"
        assert r.commands[0].args == "500"

    def test_defaultdelay_both_spellings(self):
        r = parse_script("DEFAULTDELAY 100\nDEFAULT_DELAY 200")
        assert r.ok
        assert r.commands[0].command == "DEFAULTDELAY"
        assert r.commands[1].command == "DEFAULT_DELAY"

    def test_string_preserves_payload_verbatim(self):
        payload = "  Hello, 世界! 🚀 tabs\there"
        r = parse_script(f"STRING {payload}")
        assert r.ok
        # The `STRING ` prefix has been stripped. Leading whitespace in
        # the payload is preserved by the parser (partition on first space).
        assert r.commands[0].command == "STRING"
        # After `STRING `, the rest is captured as args — whitespace
        # after the separating space is retained.
        assert r.commands[0].args.endswith("tabs\there")

    def test_stringln_recognised(self):
        r = parse_script("STRINGLN hello")
        assert r.ok
        assert r.commands[0].command == "STRINGLN"

    def test_crlf_line_endings(self):
        r = parse_script("DELAY 500\r\nENTER\r\n")
        assert r.ok
        assert len(r.commands) == 2

    def test_blank_lines_are_skipped(self):
        r = parse_script("DELAY 500\n\n\nENTER")
        assert r.ok
        assert len(r.commands) == 2


class TestDelayDiagnostics:
    def test_missing_delay_arg(self):
        r = parse_script("DELAY")
        assert not r.ok
        codes = [d.code for d in r.diagnostics]
        assert "D_MISSING_ARG" in codes

    def test_non_numeric_delay_arg(self):
        r = parse_script("DELAY abc")
        assert not r.ok
        codes = [d.code for d in r.diagnostics]
        assert "D_BAD_DELAY_ARG" in codes

    def test_negative_delay_arg(self):
        r = parse_script("DELAY -5")
        assert not r.ok
        codes = [d.code for d in r.diagnostics]
        assert "D_NEGATIVE_DELAY" in codes

    def test_large_delay_is_accepted(self):
        # Per DECISIONS.md we do NOT cap delay values in the parser.
        r = parse_script("DELAY 99999999")
        assert r.ok


class TestCombos:
    def test_gui_r(self):
        r = parse_script("GUI r")
        assert r.ok

    def test_alt_f4(self):
        r = parse_script("ALT F4")
        assert r.ok

    def test_ctrl_alt_del_hyphenated(self):
        r = parse_script("CTRL-ALT-DEL")
        assert r.ok

    def test_ctrl_alt_del_spaced(self):
        r = parse_script("CTRL ALT DEL")
        assert r.ok

    def test_ctrl_shift_t(self):
        r = parse_script("CTRL SHIFT t")
        assert r.ok

    def test_unknown_key_in_combo_warns(self):
        r = parse_script("CTRL qqqqqq")
        # Warning, not error.
        assert r.ok
        codes = [d.code for d in r.diagnostics]
        assert "D_UNKNOWN_KEY" in codes


class TestUnknownCommands:
    def test_unknown_command_warns_not_errors(self):
        r = parse_script("BLARGHY_FLARGHY")
        assert r.ok  # warning severity, ok stays True
        assert len(r.diagnostics) == 1
        assert r.diagnostics[0].code == "D_UNKNOWN_COMMAND"
        assert r.diagnostics[0].severity == "warning"

    def test_unknown_command_is_still_recorded(self):
        r = parse_script("FROBNICATE_QUANTUM 42")
        assert len(r.commands) == 1


class TestRickrollClause:
    """The canonical Hak5 rickroll — MUST NOT produce any blocking errors.

    Per PHASE6_CONTENT_SAFETY.md §2.2 this is the calibration test for
    the false-positive budget. Per DECISIONS.md §2 we've additionally
    dropped content-meaning classification, so even the warning budget
    should be clean here (the parser is pure syntax).
    """

    def test_canonical_rickroll_parses_cleanly(self):
        script = (
            "DELAY 1000\n"
            "GUI r\n"
            "DELAY 500\n"
            "STRING https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "ENTER\n"
        )
        r = parse_script(script)
        assert r.ok
        # No diagnostics at all on this canonical script — if the parser
        # starts flagging it, the parser is wrong.
        assert r.diagnostics == []
        # Five actual command lines.
        assert len(r.commands) == 5

    def test_rem_header_does_not_break_parse(self):
        script = (
            "REM Classic rickroll demo\n"
            "DELAY 1000\n"
            "GUI r\n"
            "STRING https://youtu.be/dQw4w9WgXcQ\n"
            "ENTER\n"
        )
        r = parse_script(script)
        assert r.ok
        assert r.diagnostics == []


class TestStringEdgeCases:
    def test_string_with_no_payload_warns(self):
        r = parse_script("STRING")
        # No error, but should surface a warning.
        assert r.ok
        codes = [d.code for d in r.diagnostics]
        assert "D_EMPTY_STRING" in codes

    def test_string_with_control_bytes_allowed(self):
        # DECISIONS.md §2 explicitly drops charset restriction.
        r = parse_script("STRING \x01\x02\x03")
        assert r.ok

    def test_iter_strings_extracts_payloads(self):
        script = "STRING foo\nDELAY 10\nSTRINGLN bar\nENTER"
        r = parse_script(script)
        strings = list(iter_strings(r))
        assert len(strings) == 2
        assert strings[0][1] == "foo"
        assert strings[1][1] == "bar"


class TestFKeys:
    def test_f1_through_f12(self):
        for i in range(1, 13):
            r = parse_script(f"F{i}")
            assert r.ok, f"F{i} failed"

    def test_f24_accepted(self):
        # Some extended keyboards.
        r = parse_script("F24")
        assert r.ok

    def test_f99_warns(self):
        r = parse_script("F99")
        # Out of valid F-key range — falls through to unknown-command.
        codes = [d.code for d in r.diagnostics]
        assert "D_UNKNOWN_COMMAND" in codes


class TestResultShape:
    def test_parse_result_has_ok_property(self):
        r = parse_script("DELAY 100")
        assert isinstance(r, ParseResult)
        assert r.ok is True

    def test_parse_result_line_count(self):
        r = parse_script("REM a\nDELAY 1\nENTER")
        assert r.line_count == 3

    def test_ok_false_only_when_error_severity(self):
        # Warnings alone keep ok=True.
        r = parse_script("BLARGHY")
        assert r.ok
        # Error severity flips ok to False.
        r2 = parse_script("DELAY abc")
        assert not r2.ok

    def test_diagnostic_line_numbers_are_1_based(self):
        r = parse_script("DELAY 100\nDELAY abc\nENTER")
        errors = [d for d in r.diagnostics if d.severity == "error"]
        assert len(errors) == 1
        assert errors[0].line_no == 2
