"""
Flipper Sub-GHz `.sub` file parser and header rewriter.

Why this exists: Payload Forge's `payload_subghz_inspect` and
`payload_subghz_retune` tools need to read Flipper `.sub` captures
(headers + RAW_Data), parse them, and — for retune — rewrite the
`Frequency` and `Preset` headers **without touching RAW_Data**.
RAW_Data is authoritative physical-layer sample data; silently
re-encoding it would destroy the capture. This module makes that
separation explicit.

The `.sub` file format is a tiny key/value text protocol with a
mandatory `Filetype` leader and an optional `Data_RAW` multi-line
payload appended at the end. See Flipper firmware source at
`applications/main/subghz/helpers/subghz_file.c` for the authoritative
reader.

No content-meaning classification is performed here (per
PHASE6_DECISIONS.md §2 — no rolling-code gate). Rolling-code protocols
are parsed exactly like any other protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "SubFile",
    "parse_sub",
    "serialize_sub",
    "retune",
    "SubFileError",
]


class SubFileError(ValueError):
    """Raised when a `.sub` blob is structurally malformed.

    We use ValueError semantics (bad input) rather than RuntimeError so
    callers can catch it with a narrower `except` clause.
    """


@dataclass
class SubFile:
    """Parsed representation of a Flipper `.sub` file.

    `headers` preserves insertion order — important for round-trip
    serialisation. `raw_data_lines` holds every `RAW_Data:` line verbatim
    (Flipper's capture format splits long samples across many lines; we
    keep the exact split). `extra` holds any unknown `Key: Value` lines
    encountered in header position so we can write them back untouched.

    The canonical ordering during serialisation is:
      1. `Filetype` (always first)
      2. `Version`  (always second if present)
      3. Frequency, Preset, Protocol, Bit, TE, Key, and any unknowns
         (in the order they appeared in the source)
      4. Every `RAW_Data:` line appended at the end
    """

    filetype: str
    version: str | None = None
    frequency: int | None = None
    preset: str | None = None
    protocol: str | None = None
    bit: int | None = None
    te: int | None = None
    key: str | None = None
    # Remaining headers, in insertion order.
    extra: dict[str, str] = field(default_factory=dict)
    # RAW samples: each element is one `RAW_Data:` line's payload (without
    # the leading `RAW_Data: ` prefix). Empty list = file had no RAW block.
    raw_data_lines: list[str] = field(default_factory=list)

    @property
    def has_raw_data(self) -> bool:
        """Return True when the file carries at least one RAW_Data line."""
        return bool(self.raw_data_lines)

    @property
    def sample_count(self) -> int:
        """Rough count of pulse samples across all RAW_Data lines.

        Each RAW_Data line is whitespace-separated signed integers. We
        count tokens without re-parsing them.
        """
        total = 0
        for line in self.raw_data_lines:
            total += len([t for t in line.split() if t])
        return total


# Known header keys in canonical order — used by the serialiser to emit a
# deterministic file layout for retuned outputs.
_CANONICAL_HEADER_ORDER: tuple[str, ...] = (
    "Frequency",
    "Preset",
    "Protocol",
    "Bit",
    "TE",
    "Key",
)


def parse_sub(content: str | bytes) -> SubFile:
    """Parse a `.sub` file's text into a `SubFile` dataclass.

    Accepts `str` or `bytes`; bytes are decoded as UTF-8 (Flipper writes
    ASCII). Unknown keys in the header section are preserved in
    `SubFile.extra` so round-trip serialisation is lossless.

    Raises `SubFileError` if the file is missing the mandatory `Filetype`
    header or malformed beyond recovery.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    # Normalise line endings.
    normalised = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalised.split("\n")

    filetype: str | None = None
    version: str | None = None
    frequency: int | None = None
    preset: str | None = None
    protocol: str | None = None
    bit: int | None = None
    te: int | None = None
    key: str | None = None
    extra: dict[str, str] = {}
    raw_data_lines: list[str] = []

    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        # Split on the first colon only — values may contain further ':'.
        if ":" not in line:
            # Free-text line outside the key/value grammar; treat as extra.
            extra[f"__line_{idx}__"] = line
            continue
        k, _, v = line.partition(":")
        key_name = k.strip()
        value = v.lstrip()  # keep trailing whitespace for RAW_Data fidelity

        if key_name == "RAW_Data":
            raw_data_lines.append(value.rstrip())
            continue

        # Everything else is a header.
        if key_name == "Filetype":
            filetype = value.strip()
        elif key_name == "Version":
            version = value.strip()
        elif key_name == "Frequency":
            try:
                frequency = int(value.strip())
            except ValueError as exc:
                raise SubFileError(
                    f"Frequency must be integer Hz, got {value!r}"
                ) from exc
        elif key_name == "Preset":
            preset = value.strip()
        elif key_name == "Protocol":
            protocol = value.strip()
        elif key_name == "Bit":
            try:
                bit = int(value.strip())
            except ValueError as exc:
                raise SubFileError(f"Bit must be integer, got {value!r}") from exc
        elif key_name == "TE":
            try:
                te = int(value.strip())
            except ValueError as exc:
                raise SubFileError(f"TE must be integer, got {value!r}") from exc
        elif key_name == "Key":
            key = value.strip()
        else:
            # Unknown but well-formed header — keep it.
            extra[key_name] = value.strip()

    if filetype is None:
        raise SubFileError("missing mandatory 'Filetype' header")

    return SubFile(
        filetype=filetype,
        version=version,
        frequency=frequency,
        preset=preset,
        protocol=protocol,
        bit=bit,
        te=te,
        key=key,
        extra=extra,
        raw_data_lines=raw_data_lines,
    )


def serialize_sub(sub: SubFile) -> str:
    """Serialise a `SubFile` back to the Flipper text format.

    Output is deterministic: `Filetype` first, `Version` second, then the
    canonical header order, then any `extra` keys (sorted for stability),
    then every `RAW_Data:` line verbatim. Lines are Unix-terminated.
    """
    lines: list[str] = []
    lines.append(f"Filetype: {sub.filetype}")
    if sub.version is not None:
        lines.append(f"Version: {sub.version}")
    for key in _CANONICAL_HEADER_ORDER:
        attr = {
            "Frequency": sub.frequency,
            "Preset": sub.preset,
            "Protocol": sub.protocol,
            "Bit": sub.bit,
            "TE": sub.te,
            "Key": sub.key,
        }[key]
        if attr is None:
            continue
        lines.append(f"{key}: {attr}")
    # Extras — sort the real keys, skip synthetic __line_N__ placeholders
    # (those were free-text lines we preserved but can't round-trip
    # without their position).
    for k in sorted(sub.extra):
        if k.startswith("__line_"):
            continue
        lines.append(f"{k}: {sub.extra[k]}")
    for raw in sub.raw_data_lines:
        lines.append(f"RAW_Data: {raw}")
    return "\n".join(lines) + "\n"


# Presets the Flipper SubGHz stack accepts. Non-exhaustive — we keep this
# as a reference for higher layers; per DECISIONS.md we don't enforce a
# strict allowlist as a safety gate.
KNOWN_PRESETS: frozenset[str] = frozenset(
    {
        "FuriHalSubGhzPresetOok270Async",
        "FuriHalSubGhzPresetOok650Async",
        "FuriHalSubGhzPreset2FSKDev238Async",
        "FuriHalSubGhzPreset2FSKDev476Async",
        "FuriHalSubGhzPresetMSK99_97KbAsync",
        "FuriHalSubGhzPresetGFSK9_99KbAsync",
        "FuriHalSubGhzPresetCustom",
    }
)


def retune(
    sub: SubFile,
    *,
    frequency: int | None = None,
    preset: str | None = None,
) -> SubFile:
    """Return a new `SubFile` with `Frequency` and/or `Preset` rewritten.

    RAW_Data, protocol key bits, and every other header are preserved
    verbatim. Passing `None` for either argument leaves that header
    untouched. Raises `SubFileError` if **both** arguments are `None`
    (no-op retunes are a caller bug, not a legitimate operation).

    The returned `SubFile` is a shallow copy — `extra` and
    `raw_data_lines` are aliased, not cloned, since the retune operation
    doesn't mutate them.
    """
    if frequency is None and preset is None:
        raise SubFileError("retune requires at least one of frequency / preset")
    return SubFile(
        filetype=sub.filetype,
        version=sub.version,
        frequency=frequency if frequency is not None else sub.frequency,
        preset=preset if preset is not None else sub.preset,
        protocol=sub.protocol,
        bit=sub.bit,
        te=sub.te,
        key=sub.key,
        extra=dict(sub.extra),
        raw_data_lines=list(sub.raw_data_lines),
    )
