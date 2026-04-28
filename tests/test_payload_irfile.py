"""Unit tests for the Infrared `.ir` file parser."""

from __future__ import annotations

import pytest

from echoforge.payload.irfile import IrFileError, find_signal, parse_ir


# Multi-button parsed file (common for TV remotes).
PARSED_IR = """\
Filetype: IR signals file
Version: 1
#
name: Power
type: parsed
protocol: NECext
address: 04 E0 00 00
command: 08 F7 00 00
#
name: Volume_Up
type: parsed
protocol: NECext
address: 04 E0 00 00
command: 02 FD 00 00
#
name: Volume_Down
type: parsed
protocol: NECext
address: 04 E0 00 00
command: 03 FC 00 00
"""

# A raw-type signal.
RAW_IR = """\
Filetype: IR signals file
Version: 1
#
name: Unknown_Button
type: raw
frequency: 38000
duty_cycle: 0.330000
data: 9024 4512 564 564 564 1692 564 564 564 1692 564 564
"""

# Mixed parsed + raw blocks.
MIXED_IR = """\
Filetype: IR signals file
Version: 1
#
name: Power
type: parsed
protocol: NECext
address: 04 E0 00 00
command: 08 F7 00 00
#
name: Custom_Raw
type: raw
frequency: 38000
duty_cycle: 0.330000
data: 9024 4512 564 564
"""


class TestParsedType:
    def test_parse_multiple_signals(self):
        ir = parse_ir(PARSED_IR)
        assert ir.filetype == "IR signals file"
        assert ir.version == "1"
        assert len(ir.signals) == 3

    def test_signal_names_preserved(self):
        ir = parse_ir(PARSED_IR)
        names = ir.names()
        assert names == ["Power", "Volume_Up", "Volume_Down"]

    def test_parsed_fields_populated(self):
        ir = parse_ir(PARSED_IR)
        power = ir.signals[0]
        assert power.type == "parsed"
        assert power.protocol == "NECext"
        assert power.address == "04 E0 00 00"
        assert power.command == "08 F7 00 00"
        # Raw-only fields are None.
        assert power.frequency is None
        assert power.data is None

    def test_parsed_signal_sample_count_none(self):
        ir = parse_ir(PARSED_IR)
        assert ir.signals[0].sample_count is None


class TestRawType:
    def test_parse_raw_signal(self):
        ir = parse_ir(RAW_IR)
        assert len(ir.signals) == 1
        raw = ir.signals[0]
        assert raw.type == "raw"
        assert raw.frequency == 38000
        assert raw.duty_cycle == 0.33
        assert raw.data is not None
        assert "9024" in raw.data

    def test_raw_sample_count(self):
        ir = parse_ir(RAW_IR)
        raw = ir.signals[0]
        assert raw.sample_count == 12  # 12 whitespace-separated tokens


class TestMixed:
    def test_mixed_parsed_and_raw(self):
        ir = parse_ir(MIXED_IR)
        assert len(ir.signals) == 2
        assert ir.signals[0].type == "parsed"
        assert ir.signals[1].type == "raw"

    def test_find_signal_by_name(self):
        ir = parse_ir(MIXED_IR)
        power = find_signal(ir, "Power")
        assert power is not None
        assert power.type == "parsed"
        raw = find_signal(ir, "Custom_Raw")
        assert raw is not None
        assert raw.type == "raw"

    def test_find_signal_missing(self):
        ir = parse_ir(MIXED_IR)
        assert find_signal(ir, "NotAButton") is None

    def test_find_signal_case_sensitive(self):
        ir = parse_ir(MIXED_IR)
        # "power" != "Power"
        assert find_signal(ir, "power") is None


class TestErrorHandling:
    def test_missing_filetype(self):
        bad = "Version: 1\n#\nname: x\ntype: parsed\n"
        with pytest.raises(IrFileError):
            parse_ir(bad)

    def test_non_integer_frequency(self):
        bad = (
            "Filetype: IR signals file\n"
            "Version: 1\n"
            "#\n"
            "name: x\n"
            "type: raw\n"
            "frequency: not-a-number\n"
        )
        with pytest.raises(IrFileError):
            parse_ir(bad)

    def test_block_without_name_is_skipped(self):
        bad = (
            "Filetype: IR signals file\n"
            "Version: 1\n"
            "#\n"
            "type: parsed\n"
            "protocol: NEC\n"
        )
        ir = parse_ir(bad)
        # No name → block is dropped, not an error.
        assert ir.signals == []


class TestFormatTolerance:
    def test_bytes_input(self):
        ir = parse_ir(PARSED_IR.encode("utf-8"))
        assert len(ir.signals) == 3

    def test_crlf_line_endings(self):
        ir = parse_ir(PARSED_IR.replace("\n", "\r\n"))
        assert len(ir.signals) == 3

    def test_extra_blank_lines(self):
        padded = PARSED_IR.replace("#\n", "#\n\n\n")
        ir = parse_ir(padded)
        assert len(ir.signals) == 3
