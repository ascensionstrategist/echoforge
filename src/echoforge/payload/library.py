"""
Local payload library search backend.

Why this exists: `payload_library_search` (tool #13 in
PHASE6_PAYLOAD_FORGE_API.md) needs a fast, offline way for the operator
to ask "find that Ford key I captured last week" without reading every
`.sub` file on the SD card. The answer is the `.echoforge.json` sidecar
layer: we index every sidecar under the live Flipper's
`/ext/badusb|subghz|infrared` directories, plus an optional local
manifest shipped with the repo, and fuzzy-match the operator's query
against name / description / tags.

Phase 6 is local-only. Remote-fetch mode (downloading payload bundles
from a public index) is deferred to Phase 6b per API.md §2.

The live-device code path asks the Flipper's `Storage` action module
for files. Tests exercise this with mock storages; no real Flipper is
required.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from .sidecar import (
    SIDECAR_SUFFIX,
    Sidecar,
    compute_content_hash_bytes,
)

log = logging.getLogger(__name__)

__all__ = [
    "LibraryEntry",
    "LibraryIndex",
    "build_index",
    "search",
    "PayloadKindLiteral",
]

PayloadKindLiteral = str  # Literal["badusb", "subghz", "ir"] but widened

# Where `.echoforge.json` sidecars live on a Flipper SD card.
DEVICE_ROOTS: dict[str, str] = {
    "badusb": "/ext/badusb",
    "subghz": "/ext/subghz",
    "ir": "/ext/infrared",
}

# Optional host-side manifest that `scripts/sync_payload_library.py`
# writes after pulling a public index. We read it here.
DEFAULT_LOCAL_MANIFEST: Path = Path.home() / "echoforge-payloads" / "manifest.json"


class StorageLike(Protocol):
    """Minimal duck-type over `echoforge.actions.storage.Storage`.

    Having a Protocol here (rather than importing the concrete class)
    keeps `library.py` testable without dragging the serial transport
    into test dependencies.
    """

    def list(self, path: str, *, include_md5: bool = False) -> Any: ...
    def read(self, path: str, *, timeout_s: float = 30.0) -> bytes: ...


@dataclass(frozen=True)
class LibraryEntry:
    """One search result / index entry.

    `path` is the Flipper-side path to the payload file (e.g.
    `/ext/subghz/Garage 2026.sub`). `sidecar_path` is its companion
    sidecar path. `source` records where we learnt about the entry so
    the caller can tell a live-device hit apart from a local-manifest
    hit. `sidecar` is None when the payload file exists on the device
    but has no sibling sidecar yet — still searchable by filename.
    """

    kind: str
    path: str
    sidecar_path: str
    sidecar: Sidecar | None
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()
    author: str = ""
    source: str = "device"  # "device" | "local_manifest"
    # Review M2: True if the sidecar's declared content_hash doesn't
    # match the actual payload file's sha256. Drift means either the
    # payload was edited outside echoforge, or the sidecar was written
    # before we introduced read-back hashing. Consumers surface this in
    # the TUI so the operator can rehash / investigate.
    drifted: bool = False


@dataclass
class LibraryIndex:
    """In-memory index of all known payload entries.

    Built once per search call; cheap at hobbyist scales (dozens to low
    hundreds of files). If we ever hit thousands, revisit with a proper
    search DB — for now, linear scan is fine and keeps the code obvious.
    """

    entries: list[LibraryEntry]

    def filter_by_kind(self, kinds: Iterable[str] | None) -> list[LibraryEntry]:
        """Return entries whose `kind` is in `kinds` (or all if None)."""
        if not kinds:
            return list(self.entries)
        allowed = {k.lower() for k in kinds}
        return [e for e in self.entries if e.kind in allowed]


def _payload_extension(kind: str) -> str:
    """Return the expected payload-file extension for a given kind.

    Used to distinguish payload files from sidecars and stray files
    inside the kind root.
    """
    return {"badusb": ".txt", "subghz": ".sub", "ir": ".ir"}[kind]


def _iter_device_entries(
    storage: StorageLike, kind: str, root: str
) -> Iterable[LibraryEntry]:
    """Yield every `LibraryEntry` for payloads under `root` on the device.

    Best-effort: storage errors (missing dir, read failures) are logged
    and skipped rather than raised, so a partially-broken SD card still
    produces useful search results.
    """
    ext = _payload_extension(kind)
    try:
        entries = storage.list(root)
    except Exception as exc:  # noqa: BLE001
        log.debug("library: failed listing %s: %s", root, exc)
        return

    # entries is a list of FileEntry-like objects with .name / .type /
    # .size — we only trust .name and the "FILE" type marker.
    payload_names: list[str] = []
    sidecar_names: set[str] = set()
    for e in entries:
        name = getattr(e, "name", None)
        if not name:
            continue
        type_attr = getattr(e, "type", None)
        type_name = getattr(type_attr, "name", None) or str(type_attr)
        if type_name == "DIR":
            continue
        if name.endswith(SIDECAR_SUFFIX):
            sidecar_names.add(name)
            continue
        if name.endswith(ext):
            payload_names.append(name)

    for pname in payload_names:
        path = f"{root}/{pname}"
        # Strip the payload extension and append the sidecar suffix.
        stem = pname[: -len(ext)]
        side_name = f"{stem}{SIDECAR_SUFFIX}"
        side_path = f"{root}/{side_name}"
        sidecar: Sidecar | None = None
        description = ""
        tags: tuple[str, ...] = ()
        author = ""
        display_name = stem
        drifted = False
        if side_name in sidecar_names:
            try:
                raw = storage.read(side_path)
                sidecar = Sidecar.model_validate_json(raw)
                description = sidecar.description
                tags = tuple(sidecar.tags)
                author = sidecar.author
                if sidecar.name:
                    display_name = sidecar.name
            except Exception as exc:  # noqa: BLE001
                log.debug("library: sidecar parse failed for %s: %s", side_path, exc)

        # Review M2 — drift detection. Compare the payload file's actual
        # sha256 against `sidecar.content_hash`. On mismatch, mark the
        # entry as drifted so the TUI can flag it. We skip drift check
        # when the sidecar is missing or its `content_hash` is empty
        # (legacy sidecars). One extra storage.read per payload — cheap
        # at hobbyist scale (dozens to low hundreds of files).
        if sidecar is not None and sidecar.content_hash:
            try:
                blob = storage.read(path)
            except Exception as exc:  # noqa: BLE001
                log.debug(
                    "library: payload read for drift check failed %s: %s",
                    path,
                    exc,
                )
            else:
                if compute_content_hash_bytes(blob) != sidecar.content_hash:
                    drifted = True

        yield LibraryEntry(
            kind=kind,
            path=path,
            sidecar_path=side_path,
            sidecar=sidecar,
            name=display_name,
            description=description,
            tags=tags,
            author=author,
            source="device",
            drifted=drifted,
        )


def _iter_local_manifest_entries(
    manifest_path: Path,
) -> Iterable[LibraryEntry]:
    """Yield every `LibraryEntry` described by a local manifest file.

    The manifest shape is a JSON document emitted by
    `scripts/sync_payload_library.py` (out of scope for this module).
    Expected shape:
        { "entries": [ { "kind":..., "path":..., "sidecar": {...} }, ... ] }
    Missing / malformed manifests are treated as "no local index".
    """
    if not manifest_path.is_file():
        return
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.debug("library: local manifest unreadable: %s", exc)
        return

    for row in data.get("entries", []):
        try:
            kind = row["kind"]
            path = row["path"]
        except (KeyError, TypeError):
            continue
        sidecar_blob = row.get("sidecar")
        sidecar: Sidecar | None = None
        description = ""
        tags: tuple[str, ...] = ()
        author = ""
        display_name = row.get("name") or path.rsplit("/", 1)[-1]
        if sidecar_blob:
            try:
                sidecar = Sidecar.model_validate(sidecar_blob)
                description = sidecar.description
                tags = tuple(sidecar.tags)
                author = sidecar.author
                if sidecar.name:
                    display_name = sidecar.name
            except Exception as exc:  # noqa: BLE001
                log.debug("library: local manifest sidecar invalid: %s", exc)
        sidecar_path = row.get("sidecar_path") or path
        yield LibraryEntry(
            kind=kind,
            path=path,
            sidecar_path=sidecar_path,
            sidecar=sidecar,
            name=display_name,
            description=description,
            tags=tags,
            author=author,
            source="local_manifest",
        )


def build_index(
    storage: StorageLike | None = None,
    *,
    local_manifest: Path | None = None,
    kinds: Iterable[str] | None = None,
) -> LibraryIndex:
    """Build a fresh `LibraryIndex` from live device + local manifest.

    `storage` is the Flipper storage facade (pass `flipper.storage`);
    when None, only the local manifest is scanned. `local_manifest`
    defaults to `~/echoforge-payloads/manifest.json` — pass an explicit
    Path to override (tests do this). `kinds` narrows which directories
    are walked on the device; passing None walks all three.
    """
    if kinds is None:
        kind_list = list(DEVICE_ROOTS.keys())
    else:
        kind_list = [k for k in kinds if k in DEVICE_ROOTS]

    entries: list[LibraryEntry] = []

    if storage is not None:
        for k in kind_list:
            root = DEVICE_ROOTS[k]
            entries.extend(_iter_device_entries(storage, k, root))

    manifest = local_manifest if local_manifest is not None else DEFAULT_LOCAL_MANIFEST
    entries.extend(_iter_local_manifest_entries(manifest))

    return LibraryIndex(entries=entries)


def _score(entry: LibraryEntry, query: str) -> float:
    """Return a relevance score for `entry` against `query`.

    Trivial case-insensitive-substring scorer. Exact name match scores
    highest; substring in description scores moderately; tag match
    scores as many points as the number of matching tags. Zero means no
    match (entry filtered out). Not remotely as sophisticated as a real
    search engine — intentional: the corpus is small and operator-owned.
    """
    if not query:
        return 1.0  # all entries match an empty query with equal relevance
    q = query.lower().strip()
    if not q:
        return 1.0
    name_l = entry.name.lower()
    score = 0.0
    if name_l == q:
        score += 100.0
    elif q in name_l:
        score += 50.0
    if q in entry.description.lower():
        score += 20.0
    if q in entry.author.lower():
        score += 10.0
    for tag in entry.tags:
        if q == tag.lower():
            score += 30.0
        elif q in tag.lower():
            score += 15.0
    # Also match against the filesystem path — operators search by file-
    # name frequently.
    if q in entry.path.lower():
        score += 5.0
    return score


def search(
    index: LibraryIndex,
    query: str,
    *,
    kinds: Iterable[str] | None = None,
    limit: int = 20,
) -> list[LibraryEntry]:
    """Return the top-`limit` entries in `index` matching `query`.

    Entries are filtered by `kinds` first, then scored against the
    query, sorted descending by score, and trimmed to `limit`. Entries
    with zero score are dropped (unless `query` is empty, in which case
    everything matches equally and we return the first `limit` items as
    an unordered slice).
    """
    limit = max(0, min(int(limit), 100))
    candidates = index.filter_by_kind(kinds)
    if not query or not query.strip():
        return candidates[:limit]
    scored = [(e, _score(e, query)) for e in candidates]
    scored = [(e, s) for e, s in scored if s > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [e for e, _ in scored[:limit]]
