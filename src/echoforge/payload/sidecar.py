"""
Payload sidecar (`.echoforge.json`) reader / writer.

Why this exists: every payload Claude authors or imports gets an
optional sibling `.echoforge.json` file that carries free-text metadata
(name, description, tags, policy tag, content hash). The sidecar is
advisory — payload is authoritative on conflict — but it enables
`payload_library_search` to find the operator's captures by
description without reading the underlying `.sub` / `.ir` / `.txt`.

Schema is normative per `PHASE6_DECISIONS.md §8`. We use Pydantic v2 so
round-trip validation is automatic and schema evolution (schema_version
bumps) is trivially additive.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Sidecar",
    "SidecarSource",
    "SIDECAR_SCHEMA_VERSION",
    "SIDECAR_SUFFIX",
    "compute_content_hash",
    "sidecar_path_for",
    "load_sidecar",
    "dump_sidecar",
    "utcnow_iso",
]

SIDECAR_SCHEMA_VERSION: int = 1
SIDECAR_SUFFIX: str = ".echoforge.json"

PayloadKind = Literal["badusb", "subghz", "ir"]
SourceOrigin = Literal["created", "captured", "imported"]


def utcnow_iso() -> str:
    """Return the current UTC time in ISO-8601 format (seconds precision).

    Centralised so every sidecar writer emits a stable timestamp shape
    regardless of caller's locale / clock settings.
    """
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


class SidecarSource(BaseModel):
    """Provenance metadata embedded inside a `Sidecar`.

    `origin` records how the artifact got on the SD card. For captures,
    `captured_on` / `capture_freq_mhz` / `capture_protocol` are useful
    even after the capture file has been renamed into a human-friendly
    form.
    """

    model_config = ConfigDict(extra="allow")

    origin: SourceOrigin = "created"
    captured_on: str | None = None
    capture_freq_mhz: float | None = None
    capture_protocol: str | None = None


class Sidecar(BaseModel):
    """The complete `.echoforge.json` schema.

    `schema_version` is an integer so legacy files can be detected and
    upgraded in-place. `content_hash` MUST be `sha256:<hex>` format and
    is computed over the artifact bytes (NOT the sidecar bytes). Tags
    are free-form; the `policy_tag` is Claude-auto-written at creation
    time and operator-editable afterwards (DECISIONS.md §4).

    The Pydantic model allows extra keys on deserialisation so forward-
    compatible sidecars (schema_version > current) won't crash a read.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: int = Field(default=SIDECAR_SCHEMA_VERSION)
    kind: PayloadKind
    name: str
    description: str = ""
    author: str = ""
    tags: list[str] = Field(default_factory=list)
    policy_tag: str | None = None
    content_hash: str = ""
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    source: SidecarSource = Field(default_factory=SidecarSource)
    engagement_ref: str | None = None


def compute_content_hash(path: str | Path) -> str:
    """Return `"sha256:<hex>"` for the raw bytes at `path`.

    Matches the sidecar schema convention. Raises `FileNotFoundError` if
    the file does not exist — callers writing a sidecar for a
    just-created artifact are expected to compute the hash *after* the
    artifact has been written.
    """
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def compute_content_hash_bytes(data: bytes) -> str:
    """Same as `compute_content_hash` but for an in-memory `bytes` blob.

    Used when the sidecar is written alongside a payload whose contents
    we already have in-RAM (e.g. right after `flipper.storage.write`).
    Avoids a round-trip read from the Flipper.
    """
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def sidecar_path_for(payload_path: str | Path) -> str:
    """Return the conventional sidecar path for a given payload path.

    Example: `/ext/badusb/rickroll.txt` -> `/ext/badusb/rickroll.echoforge.json`.
    The sidecar lives next to the artifact with the artifact's base stem
    plus `.echoforge.json`. We operate on strings (not `Path`) because
    Flipper-side paths are POSIX regardless of host OS.
    """
    s = str(payload_path)
    # Strip the last extension only; everything else is preserved.
    if "/" in s:
        directory, _, filename = s.rpartition("/")
    else:
        directory, filename = "", s
    if "." in filename:
        stem, _, _ = filename.rpartition(".")
    else:
        stem = filename
    if directory:
        return f"{directory}/{stem}{SIDECAR_SUFFIX}"
    return f"{stem}{SIDECAR_SUFFIX}"


def load_sidecar(content: str | bytes) -> Sidecar:
    """Parse a sidecar JSON blob into a `Sidecar` model.

    Accepts `str` or `bytes`. Raises `pydantic.ValidationError` if the
    payload doesn't match the schema, or `json.JSONDecodeError` if it
    isn't valid JSON.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8")
    data = json.loads(content)
    return Sidecar.model_validate(data)


def dump_sidecar(sidecar: Sidecar, *, indent: int = 2) -> str:
    """Serialise a `Sidecar` to pretty-printed JSON text.

    `indent=2` is the default for human-readable files on the SD card;
    set `indent=None` (via direct JSON) if you need compact output.
    """
    # Pydantic v2: mode='json' ensures enums / datetimes render as JSON-
    # compatible scalars. `exclude_none=False` keeps explicit nulls so
    # the sidecar is a faithful serialisation of the model.
    return json.dumps(
        sidecar.model_dump(mode="json"), indent=indent, sort_keys=False
    )
