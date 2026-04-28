"""Unit tests for the Sub-GHz `.sub` file parser / serializer / retuner."""

from __future__ import annotations

import pytest

from echoforge.payload.subfile import (
    KNOWN_PRESETS,
    SubFileError,
    parse_sub,
    retune,
    serialize_sub,
)


# A minimal but representative Princeton .sub file (parsed type).
PRINCETON_SUB = """\
Filetype: Flipper SubGhz Key File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: Princeton
Bit: 24
Key: 00 00 00 00 00 C9 5E B0
TE: 417
"""

# A RAW-type capture, with several RAW_Data lines.
RAW_SUB = """\
Filetype: Flipper SubGhz RAW File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Protocol: RAW
RAW_Data: 120 -280 -100 200 -240
RAW_Data: 300 -400 150 -150
RAW_Data: 180 -200
"""

# A file with an unknown header key, to verify round-trip preservation.
EXTRA_HEADER_SUB = """\
Filetype: Flipper SubGhz Key File
Version: 1
Frequency: 433920000
Preset: FuriHalSubGhzPresetOok650Async
Custom_Field: hello-world
Protocol: Princeton
Bit: 24
Key: 00 00 00 00 00 C9 5E B0
"""


class TestParseHappyPath:
    def test_parse_princeton(self):
        sub = parse_sub(PRINCETON_SUB)
        assert sub.filetype == "Flipper SubGhz Key File"
        assert sub.version == "1"
        assert sub.frequency == 433920000
        assert sub.preset == "FuriHalSubGhzPresetOok650Async"
        assert sub.protocol == "Princeton"
        assert sub.bit == 24
        assert sub.te == 417
        assert sub.key == "00 00 00 00 00 C9 5E B0"
        assert not sub.has_raw_data

    def test_parse_raw_data(self):
        sub = parse_sub(RAW_SUB)
        assert sub.protocol == "RAW"
        assert sub.has_raw_data
        assert len(sub.raw_data_lines) == 3
        # Sample count: 5 + 4 + 2 = 11
        assert sub.sample_count == 11

    def test_parse_accepts_bytes(self):
        sub = parse_sub(PRINCETON_SUB.encode("utf-8"))
        assert sub.frequency == 433920000

    def test_parse_accepts_crlf(self):
        sub = parse_sub(PRINCETON_SUB.replace("\n", "\r\n"))
        assert sub.frequency == 433920000

    def test_parse_preserves_unknown_headers(self):
        sub = parse_sub(EXTRA_HEADER_SUB)
        assert "Custom_Field" in sub.extra
        assert sub.extra["Custom_Field"] == "hello-world"


class TestParseErrors:
    def test_missing_filetype_raises(self):
        bad = "Version: 1\nFrequency: 433920000\n"
        with pytest.raises(SubFileError):
            parse_sub(bad)

    def test_non_integer_frequency_raises(self):
        bad = "Filetype: x\nVersion: 1\nFrequency: not-a-number\n"
        with pytest.raises(SubFileError):
            parse_sub(bad)

    def test_non_integer_bit_raises(self):
        bad = "Filetype: x\nVersion: 1\nBit: abc\n"
        with pytest.raises(SubFileError):
            parse_sub(bad)


class TestSerialise:
    def test_round_trip_princeton(self):
        sub = parse_sub(PRINCETON_SUB)
        out = serialize_sub(sub)
        re_parsed = parse_sub(out)
        assert re_parsed.frequency == sub.frequency
        assert re_parsed.preset == sub.preset
        assert re_parsed.protocol == sub.protocol
        assert re_parsed.key == sub.key

    def test_round_trip_raw(self):
        sub = parse_sub(RAW_SUB)
        out = serialize_sub(sub)
        re_parsed = parse_sub(out)
        assert re_parsed.raw_data_lines == sub.raw_data_lines
        assert re_parsed.sample_count == sub.sample_count

    def test_round_trip_with_extras(self):
        sub = parse_sub(EXTRA_HEADER_SUB)
        out = serialize_sub(sub)
        assert "Custom_Field: hello-world" in out
        re_parsed = parse_sub(out)
        assert re_parsed.extra.get("Custom_Field") == "hello-world"

    def test_serialise_starts_with_filetype(self):
        sub = parse_sub(PRINCETON_SUB)
        out = serialize_sub(sub)
        first_line = out.split("\n", 1)[0]
        assert first_line.startswith("Filetype:")


class TestRetune:
    def test_retune_frequency_only(self):
        sub = parse_sub(PRINCETON_SUB)
        new = retune(sub, frequency=315000000)
        assert new.frequency == 315000000
        # Preset preserved.
        assert new.preset == sub.preset
        # Key / protocol / RAW preserved.
        assert new.key == sub.key
        assert new.protocol == sub.protocol

    def test_retune_preset_only(self):
        sub = parse_sub(PRINCETON_SUB)
        new = retune(sub, preset="FuriHalSubGhzPresetOok270Async")
        assert new.preset == "FuriHalSubGhzPresetOok270Async"
        assert new.frequency == sub.frequency

    def test_retune_both(self):
        sub = parse_sub(PRINCETON_SUB)
        new = retune(
            sub,
            frequency=868_350_000,
            preset="FuriHalSubGhzPreset2FSKDev238Async",
        )
        assert new.frequency == 868_350_000
        assert new.preset == "FuriHalSubGhzPreset2FSKDev238Async"

    def test_retune_preserves_raw_data(self):
        """RAW_Data MUST be preserved verbatim — the core invariant."""
        sub = parse_sub(RAW_SUB)
        new = retune(sub, frequency=315000000)
        # New dataclass, but raw data list content is identical.
        assert new.raw_data_lines == sub.raw_data_lines
        # Round-trip confirms byte equivalence of the raw block.
        out = serialize_sub(new)
        re_parsed = parse_sub(out)
        assert re_parsed.raw_data_lines == sub.raw_data_lines

    def test_retune_no_args_raises(self):
        sub = parse_sub(PRINCETON_SUB)
        with pytest.raises(SubFileError):
            retune(sub)

    def test_retune_does_not_mutate_input(self):
        sub = parse_sub(PRINCETON_SUB)
        original_freq = sub.frequency
        _ = retune(sub, frequency=315000000)
        # Original untouched.
        assert sub.frequency == original_freq


class TestKnownPresets:
    def test_known_presets_contains_common_entries(self):
        assert "FuriHalSubGhzPresetOok650Async" in KNOWN_PRESETS
        assert "FuriHalSubGhzPresetOok270Async" in KNOWN_PRESETS
        assert "FuriHalSubGhzPresetCustom" in KNOWN_PRESETS
