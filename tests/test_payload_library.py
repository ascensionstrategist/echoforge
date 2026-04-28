"""Unit tests for the payload library search backend."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pytest

from echoforge.payload.library import (
    DEVICE_ROOTS,
    LibraryIndex,
    build_index,
    search,
)
from echoforge.payload.sidecar import Sidecar, dump_sidecar


# ---------------------------------------------------------------------------
# Fake Flipper storage — minimum surface the library needs.
# ---------------------------------------------------------------------------


class _FileType(Enum):
    FILE = "FILE"
    DIR = "DIR"


@dataclass
class _FakeEntry:
    name: str
    type: _FileType
    size: int = 0


class _FakeStorage:
    """In-memory stand-in for `Flipper.storage` with list/read surface.

    Initial state is a dict of directory paths to lists of `_FakeEntry`,
    plus a dict mapping full paths to raw bytes for `read`.
    """

    def __init__(
        self,
        *,
        listings: dict[str, list[_FakeEntry]] | None = None,
        files: dict[str, bytes] | None = None,
    ):
        self._listings = listings or {}
        self._files = files or {}

    def list(self, path: str, *, include_md5: bool = False):
        return self._listings.get(path, [])

    def read(self, path: str, *, timeout_s: float = 30.0) -> bytes:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]


def _make_sidecar_bytes(**overrides) -> bytes:
    kwargs: dict = {"kind": "subghz", "name": "test"}
    kwargs.update(overrides)
    return dump_sidecar(Sidecar(**kwargs)).encode("utf-8")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDeviceIndex:
    def test_empty_device(self):
        storage = _FakeStorage()
        index = build_index(storage, local_manifest=Path("/__no_such__"))
        assert index.entries == []

    def test_single_subghz_no_sidecar(self):
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("garage.sub", _FileType.FILE, 512),
                ],
            }
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert len(index.entries) == 1
        e = index.entries[0]
        assert e.kind == "subghz"
        assert e.path == "/ext/subghz/garage.sub"
        assert e.sidecar is None
        assert e.has_sidecar is False if hasattr(e, "has_sidecar") else True
        # Name falls back to filename stem when no sidecar.
        assert e.name == "garage"

    def test_subghz_with_sidecar(self):
        side_bytes = _make_sidecar_bytes(
            name="Garage 2026",
            description="North bay garage door",
            tags=["garage", "home"],
            kind="subghz",
        )
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("garage.sub", _FileType.FILE, 512),
                    _FakeEntry("garage.echoforge.json", _FileType.FILE, 128),
                ]
            },
            files={
                "/ext/subghz/garage.echoforge.json": side_bytes,
            },
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert len(index.entries) == 1
        e = index.entries[0]
        assert e.name == "Garage 2026"
        assert e.description == "North bay garage door"
        assert "garage" in e.tags
        assert e.sidecar is not None

    def test_all_three_kinds_indexed(self):
        storage = _FakeStorage(
            listings={
                "/ext/badusb": [_FakeEntry("a.txt", _FileType.FILE)],
                "/ext/subghz": [_FakeEntry("b.sub", _FileType.FILE)],
                "/ext/infrared": [_FakeEntry("c.ir", _FileType.FILE)],
            }
        )
        index = build_index(storage, local_manifest=Path("/__no_such__"))
        kinds = {e.kind for e in index.entries}
        assert kinds == {"badusb", "subghz", "ir"}

    def test_directories_are_skipped(self):
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("captured", _FileType.DIR),
                    _FakeEntry("garage.sub", _FileType.FILE),
                ],
            }
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert len(index.entries) == 1
        assert index.entries[0].path.endswith("garage.sub")

    def test_extension_mismatch_skipped(self):
        # .sub under subghz is a match; .txt under subghz is not.
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("garage.sub", _FileType.FILE),
                    _FakeEntry("readme.txt", _FileType.FILE),
                ]
            }
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert len(index.entries) == 1


class TestLocalManifest:
    def test_local_manifest_read(self, tmp_path: Path):
        manifest = {
            "entries": [
                {
                    "kind": "subghz",
                    "path": "/ext/subghz/shipped.sub",
                    "name": "Shipped Signal",
                    "sidecar": {
                        "kind": "subghz",
                        "name": "Shipped Signal",
                        "description": "Bundled demo",
                        "tags": ["demo"],
                    },
                }
            ]
        }
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps(manifest), encoding="utf-8")

        # Without device storage, only the local manifest is read.
        index = build_index(None, local_manifest=p)
        assert len(index.entries) == 1
        e = index.entries[0]
        assert e.source == "local_manifest"
        assert e.name == "Shipped Signal"
        assert e.description == "Bundled demo"

    def test_missing_local_manifest_is_fine(self, tmp_path: Path):
        index = build_index(None, local_manifest=tmp_path / "does-not-exist.json")
        assert index.entries == []

    def test_malformed_manifest_does_not_crash(self, tmp_path: Path):
        p = tmp_path / "manifest.json"
        p.write_text("{not valid json", encoding="utf-8")
        index = build_index(None, local_manifest=p)
        assert index.entries == []


class TestSearch:
    @pytest.fixture
    def populated_index(self) -> LibraryIndex:
        side_garage = _make_sidecar_bytes(
            name="Garage 2026",
            description="North bay garage door",
            tags=["garage", "home"],
            kind="subghz",
        )
        side_ford = _make_sidecar_bytes(
            name="Ford Fob",
            description="Ford F-150 key fob capture",
            tags=["car", "ford"],
            author="engagement-42",
            kind="subghz",
        )
        side_tv = _make_sidecar_bytes(
            name="LG TV Remote",
            description="Living room LG OLED",
            tags=["tv", "home"],
            kind="ir",
        )
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("garage.sub", _FileType.FILE),
                    _FakeEntry("garage.echoforge.json", _FileType.FILE),
                    _FakeEntry("ford.sub", _FileType.FILE),
                    _FakeEntry("ford.echoforge.json", _FileType.FILE),
                ],
                "/ext/infrared": [
                    _FakeEntry("lg.ir", _FileType.FILE),
                    _FakeEntry("lg.echoforge.json", _FileType.FILE),
                ],
            },
            files={
                "/ext/subghz/garage.echoforge.json": side_garage,
                "/ext/subghz/ford.echoforge.json": side_ford,
                "/ext/infrared/lg.echoforge.json": side_tv,
            },
        )
        return build_index(storage, local_manifest=Path("/__no_such__"))

    def test_empty_query_returns_all(self, populated_index):
        hits = search(populated_index, "")
        assert len(hits) == 3

    def test_exact_name_match_ranks_highest(self, populated_index):
        hits = search(populated_index, "Ford Fob")
        assert hits[0].name == "Ford Fob"

    def test_description_substring_match(self, populated_index):
        hits = search(populated_index, "living room")
        assert any("LG" in h.name for h in hits)

    def test_tag_match(self, populated_index):
        hits = search(populated_index, "garage")
        assert any(h.name == "Garage 2026" for h in hits)

    def test_kind_filter_subghz(self, populated_index):
        hits = search(populated_index, "", kinds=["subghz"])
        assert all(h.kind == "subghz" for h in hits)
        assert len(hits) == 2

    def test_kind_filter_ir(self, populated_index):
        hits = search(populated_index, "", kinds=["ir"])
        assert all(h.kind == "ir" for h in hits)
        assert len(hits) == 1

    def test_author_match(self, populated_index):
        hits = search(populated_index, "engagement-42")
        assert any(h.author == "engagement-42" for h in hits)

    def test_no_match_returns_empty(self, populated_index):
        hits = search(populated_index, "zzz-definitely-nothing")
        assert hits == []

    def test_limit_clamps_to_100(self, populated_index):
        # Request more than we have; we should get at most len(entries).
        hits = search(populated_index, "", limit=999)
        assert len(hits) == 3

    def test_limit_0_returns_nothing(self, populated_index):
        hits = search(populated_index, "", limit=0)
        assert hits == []


class TestDeviceRoots:
    def test_all_three_kinds_present(self):
        assert set(DEVICE_ROOTS.keys()) == {"badusb", "subghz", "ir"}
        assert DEVICE_ROOTS["badusb"] == "/ext/badusb"
        assert DEVICE_ROOTS["subghz"] == "/ext/subghz"
        assert DEVICE_ROOTS["ir"] == "/ext/infrared"


# ---------------------------------------------------------------------------
# Review M2 — sidecar drift detection
# ---------------------------------------------------------------------------


class TestDriftDetection:
    """Library search compares the on-disk file's sha256 against the
    sidecar's `content_hash`. On mismatch, the LibraryEntry is flagged
    `drifted=True` so the TUI can warn the operator. Review M2.
    """

    def test_matching_hash_no_drift(self):
        from echoforge.payload.sidecar import compute_content_hash_bytes

        payload_blob = b"RAW_Data: 123 456\n"
        side_bytes = _make_sidecar_bytes(
            kind="subghz",
            name="Clean",
            content_hash=compute_content_hash_bytes(payload_blob),
        )
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("clean.sub", _FileType.FILE, len(payload_blob)),
                    _FakeEntry("clean.echoforge.json", _FileType.FILE),
                ]
            },
            files={
                "/ext/subghz/clean.sub": payload_blob,
                "/ext/subghz/clean.echoforge.json": side_bytes,
            },
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert len(index.entries) == 1
        assert index.entries[0].drifted is False

    def test_mismatched_hash_flags_drift(self):
        side_bytes = _make_sidecar_bytes(
            kind="subghz",
            name="Drifted",
            # A fixed hash that will NOT match whatever bytes we plant.
            content_hash="sha256:" + ("0" * 64),
        )
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("drifted.sub", _FileType.FILE, 10),
                    _FakeEntry("drifted.echoforge.json", _FileType.FILE),
                ]
            },
            files={
                "/ext/subghz/drifted.sub": b"some different bytes",
                "/ext/subghz/drifted.echoforge.json": side_bytes,
            },
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert len(index.entries) == 1
        assert index.entries[0].drifted is True

    def test_no_hash_in_sidecar_no_drift_flag(self):
        # Legacy sidecar with empty `content_hash` must NOT be reported
        # as drifted — we just don't know. False-positive drift would
        # be worse than silent legacy tolerance.
        side_bytes = _make_sidecar_bytes(
            kind="subghz", name="Legacy", content_hash=""
        )
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [
                    _FakeEntry("legacy.sub", _FileType.FILE, 10),
                    _FakeEntry("legacy.echoforge.json", _FileType.FILE),
                ]
            },
            files={
                "/ext/subghz/legacy.sub": b"anything",
                "/ext/subghz/legacy.echoforge.json": side_bytes,
            },
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert index.entries[0].drifted is False

    def test_missing_sidecar_no_drift_flag(self):
        storage = _FakeStorage(
            listings={
                "/ext/subghz": [_FakeEntry("lone.sub", _FileType.FILE)],
            },
            files={"/ext/subghz/lone.sub": b"some bytes"},
        )
        index = build_index(
            storage, local_manifest=Path("/__no_such__"), kinds=["subghz"]
        )
        assert index.entries[0].drifted is False
        assert index.entries[0].sidecar is None
