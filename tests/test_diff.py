"""Unit tests for the diff service."""

from __future__ import annotations

import pytest

from echoforge.safety.diff import (
    binary_diff_summary,
    is_binary,
    summarize_write,
    unified_text_diff,
)


class TestIsBinary:
    def test_text_is_not_binary(self):
        assert is_binary(b"Hello echoforge\n") is False

    def test_nul_bytes_mean_binary(self):
        assert is_binary(b"abc\x00def") is True

    def test_invalid_utf8_is_binary(self):
        # Isolated 0xFF invalid in UTF-8.
        assert is_binary(b"\xff\xfe\xfa") is True


class TestUnifiedTextDiff:
    def test_identical_returns_empty(self):
        diff, added, removed = unified_text_diff("foo\nbar\n", "foo\nbar\n")
        assert diff == ""
        assert added == 0 and removed == 0

    def test_adds_a_line(self):
        old = "line1\nline2\n"
        new = "line1\nline2\nline3\n"
        diff, added, removed = unified_text_diff(old, new, path="x.txt")
        assert added == 1 and removed == 0
        assert "+line3" in diff
        assert "---" in diff and "+++" in diff

    def test_removes_a_line(self):
        diff, added, removed = unified_text_diff("a\nb\nc\n", "a\nc\n")
        assert added == 0 and removed == 1
        assert "-b" in diff

    def test_replacement(self):
        diff, added, removed = unified_text_diff(
            "Frequency: 315000000\n", "Frequency: 433920000\n", path="garage.sub"
        )
        assert added == 1 and removed == 1
        assert "-Frequency: 315000000" in diff
        assert "+Frequency: 433920000" in diff


class TestBinaryDiffSummary:
    def test_summary_contains_sizes_and_md5(self):
        old = b"\x00" * 100
        new = b"\x00" * 120
        out = binary_diff_summary(old, new, path="fw.bin")
        assert "fw.bin" in out
        assert "100" in out and "120" in out
        assert "+20" in out
        assert "md5:" in out

    def test_empty_old_is_handled(self):
        out = binary_diff_summary(b"", b"\x00\x01\x02", path="new.bin")
        assert "(empty)" in out
        assert "+3" in out


class TestSummarizeWrite:
    def test_new_text_file_shows_preview(self):
        content = "line 1\nline 2\nline 3\n"
        summary = summarize_write("/ext/new.txt", content)
        assert summary.is_new is True
        assert summary.is_binary is False
        assert summary.new_size == len(content.encode())
        assert summary.old_size == 0
        assert "(new file)" in summary.diff_text
        assert "line 1" in summary.diff_text

    def test_updating_text_file_produces_diff(self):
        old = "Hello\n"
        new = "Hello, World\n"
        summary = summarize_write("/ext/hi.txt", new, old_content=old)
        assert summary.is_new is False
        assert summary.lines_added == 1
        assert summary.lines_removed == 1
        assert "+Hello, World" in summary.diff_text

    def test_binary_file_uses_binary_summary(self):
        old = bytes(range(50))
        new = bytes(range(50)) + b"\x00\x01"
        summary = summarize_write("/ext/x.bin", new, old_content=old)
        assert summary.is_binary is True
        assert "md5:" in summary.diff_text
        assert summary.size_delta == 2

    def test_size_delta_sign(self):
        summary = summarize_write("/ext/hi.txt", "short", old_content="a longer blob of text")
        assert summary.size_delta < 0
