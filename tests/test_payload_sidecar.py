"""Unit tests for the .echoforge.json sidecar reader/writer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from echoforge.payload.sidecar import (
    SIDECAR_SCHEMA_VERSION,
    SIDECAR_SUFFIX,
    Sidecar,
    SidecarSource,
    compute_content_hash,
    compute_content_hash_bytes,
    dump_sidecar,
    load_sidecar,
    sidecar_path_for,
    utcnow_iso,
)


class TestSidecarPathFor:
    def test_badusb_txt(self):
        assert sidecar_path_for("/ext/badusb/rickroll.txt") == (
            "/ext/badusb/rickroll.echoforge.json"
        )

    def test_subghz_sub(self):
        assert sidecar_path_for("/ext/subghz/Garage 2026.sub") == (
            "/ext/subghz/Garage 2026.echoforge.json"
        )

    def test_infrared_ir(self):
        assert sidecar_path_for("/ext/infrared/LG.ir") == (
            "/ext/infrared/LG.echoforge.json"
        )

    def test_no_extension(self):
        # No extension → whole filename is the stem.
        assert sidecar_path_for("/ext/foo/bar") == "/ext/foo/bar.echoforge.json"

    def test_no_directory(self):
        assert sidecar_path_for("bar.txt") == "bar.echoforge.json"


class TestContentHashing:
    def test_hash_bytes_matches_sha256(self):
        data = b"hello world"
        result = compute_content_hash_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert result == f"sha256:{expected}"

    def test_hash_empty_bytes(self):
        result = compute_content_hash_bytes(b"")
        # SHA-256 of empty string is well-known.
        assert (
            result
            == "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        )

    def test_hash_file_equivalent_to_bytes(self, tmp_path: Path):
        content = b"some payload content\nline 2"
        f = tmp_path / "payload.bin"
        f.write_bytes(content)
        assert compute_content_hash(f) == compute_content_hash_bytes(content)

    def test_hash_file_missing_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            compute_content_hash(tmp_path / "does-not-exist")

    def test_hash_is_stable_across_calls(self):
        data = b"determinism test"
        h1 = compute_content_hash_bytes(data)
        h2 = compute_content_hash_bytes(data)
        assert h1 == h2


class TestSidecarModel:
    def test_minimal_construction(self):
        s = Sidecar(kind="badusb", name="x")
        assert s.schema_version == SIDECAR_SCHEMA_VERSION
        assert s.kind == "badusb"
        assert s.name == "x"
        assert s.description == ""
        assert s.tags == []
        assert s.policy_tag is None
        assert s.created_at  # populated by default_factory
        assert s.updated_at

    def test_invalid_kind_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Sidecar(kind="nonsense", name="x")

    def test_round_trip_dump_load(self):
        s = Sidecar(
            kind="subghz",
            name="Garage 2026",
            description="North bay door",
            author="shawn@engagement42",
            tags=["garage", "capture-2026-04-22"],
            policy_tag="prank",
            content_hash="sha256:abcdef",
            source=SidecarSource(
                origin="captured",
                captured_on="2026-04-22T18:02:11+00:00",
                capture_freq_mhz=433.92,
                capture_protocol="Princeton",
            ),
        )
        text = dump_sidecar(s)
        # Validate JSON shape.
        parsed = json.loads(text)
        assert parsed["kind"] == "subghz"
        assert parsed["name"] == "Garage 2026"
        assert parsed["source"]["origin"] == "captured"
        assert parsed["source"]["capture_freq_mhz"] == 433.92
        # Round-trip through load.
        back = load_sidecar(text)
        assert back.kind == s.kind
        assert back.name == s.name
        assert back.description == s.description
        assert back.tags == s.tags
        assert back.policy_tag == s.policy_tag
        assert back.content_hash == s.content_hash
        assert back.source.origin == s.source.origin
        assert back.source.capture_freq_mhz == s.source.capture_freq_mhz

    def test_load_bytes(self):
        s = Sidecar(kind="ir", name="tv")
        text = dump_sidecar(s).encode("utf-8")
        back = load_sidecar(text)
        assert back.name == "tv"

    def test_unknown_extra_keys_preserved(self):
        # Forward-compatible schema (schema_version > current) should parse.
        blob = json.dumps(
            {
                "schema_version": 99,
                "kind": "badusb",
                "name": "test",
                "future_key": "future_value",
            }
        )
        back = load_sidecar(blob)
        assert back.schema_version == 99
        assert back.kind == "badusb"


class TestUtcNow:
    def test_utcnow_iso_shape(self):
        t = utcnow_iso()
        # Basic shape check: "YYYY-MM-DDTHH:MM:SS+00:00"
        assert "T" in t
        assert t.endswith("+00:00") or t.endswith("Z")
        assert len(t) >= 25  # reasonable ISO-8601 length


class TestFullRoundtripViaFiles:
    def test_write_and_read_sidecar_via_file(self, tmp_path: Path):
        payload = b"DELAY 100\nSTRING hi\nENTER\n"
        payload_path = tmp_path / "rickroll.txt"
        payload_path.write_bytes(payload)

        s = Sidecar(
            kind="badusb",
            name="rickroll",
            description="A test",
            content_hash=compute_content_hash(payload_path),
            tags=["test", "demo"],
        )

        side_path = tmp_path / (payload_path.stem + SIDECAR_SUFFIX)
        side_path.write_text(dump_sidecar(s), encoding="utf-8")

        # Read back.
        back = load_sidecar(side_path.read_text(encoding="utf-8"))
        assert back.name == "rickroll"
        assert back.content_hash == compute_content_hash(payload_path)
        assert back.tags == ["test", "demo"]

    def test_hash_changes_with_content(self, tmp_path: Path):
        p = tmp_path / "f"
        p.write_bytes(b"v1")
        h1 = compute_content_hash(p)
        p.write_bytes(b"v2")
        h2 = compute_content_hash(p)
        assert h1 != h2
