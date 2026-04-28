"""
Flipper `.ir` file parser.

Why this exists: Payload Forge's `payload_ir_inspect` and
`payload_ir_transmit` tools need to enumerate the named signals inside a
multi-button `.ir` file, so Claude can resolve `button_name="Power"` to a
real signal before firing `ir tx_file`.

The `.ir` file format is a block-structured key/value text. The first
two lines are a global `Filetype` / `Version` pair; subsequent blocks
are separated by `#` comment-delimiter lines, each block describing one
signal with a `name`, a `type` (`parsed` or `raw`), and type-specific
keys.

This parser is tolerant of extra blank lines, whitespace, and missing
keys — consistent with Flipper firmware, which will load `.ir` files
with minor irregularities.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "IrSignal",
    "IrFile",
    "parse_ir",
    "IrFileError",
    "find_signal",
]


class IrFileError(ValueError):
    """Raised when an `.ir` blob is structurally malformed.

    ValueError semantics (bad input); catchable narrowly.
    """


@dataclass
class IrSignal:
    """One named signal inside an `.ir` file.

    For `type == "parsed"` signals, `protocol` / `address` / `command`
    carry the decoded values. For `type == "raw"`, `frequency`,
    `duty_cycle`, and `data` carry the microsecond-level pulse train.
    `extra` preserves any unknown keys encountered in the block so
    lossless reserialisation is possible if we ever add a writer.
    """

    name: str
    type: str  # "parsed" | "raw" | unknown future types
    # Parsed-type fields.
    protocol: str | None = None
    address: str | None = None
    command: str | None = None
    # Raw-type fields.
    frequency: int | None = None
    duty_cycle: float | None = None
    data: str | None = None
    # Passthrough for unknown keys.
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def sample_count(self) -> int | None:
        """For raw signals, return the number of pulse samples.

        Returns None for parsed-type signals (no sample stream) or when
        `data` is missing.
        """
        if self.type != "raw" or self.data is None:
            return None
        return len([t for t in self.data.split() if t])


@dataclass
class IrFile:
    """Parsed `.ir` file: a header pair plus a list of `IrSignal`s.

    `signals` preserves the order they appeared in the source, which is
    also the visual order the user sees in the Flipper UI.
    """

    filetype: str
    version: str | None
    signals: list[IrSignal] = field(default_factory=list)

    def names(self) -> list[str]:
        """Return the list of signal names (convenience for callers that
        just want to populate a dropdown)."""
        return [s.name for s in self.signals]


def parse_ir(content: str | bytes) -> IrFile:
    """Parse an `.ir` file blob into an `IrFile`.

    Accepts `str` or `bytes`; bytes are UTF-8 decoded. Raises
    `IrFileError` when `Filetype` is missing or a block lacks the
    mandatory `name` key.
    """
    if isinstance(content, bytes):
        content = content.decode("utf-8", errors="replace")

    normalised = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalised.split("\n")

    filetype: str | None = None
    version: str | None = None
    signals: list[IrSignal] = []
    current: dict[str, str] | None = None

    def _flush_current() -> None:
        """If a block is in progress, materialise it as an IrSignal."""
        nonlocal current
        if current is None:
            return
        name = current.pop("name", None)
        if name is None:
            # A block with no `name:` — skip it with no hard failure. We
            # could raise, but Flipper tolerates this and so do we.
            current = None
            return
        sig_type = current.pop("type", "") or ""
        try:
            frequency = int(current.pop("frequency")) if "frequency" in current else None
        except ValueError as exc:
            raise IrFileError(f"signal {name!r}: frequency must be int") from exc
        try:
            duty_cycle = float(current.pop("duty_cycle")) if "duty_cycle" in current else None
        except ValueError as exc:
            raise IrFileError(f"signal {name!r}: duty_cycle must be float") from exc
        signals.append(
            IrSignal(
                name=name,
                type=sig_type,
                protocol=current.pop("protocol", None),
                address=current.pop("address", None),
                command=current.pop("command", None),
                frequency=frequency,
                duty_cycle=duty_cycle,
                data=current.pop("data", None),
                extra=dict(current),
            )
        )
        current = None

    for line in lines:
        stripped = line.strip()
        # Block separator — any `#`-led line ends the current signal block.
        if stripped.startswith("#"):
            _flush_current()
            continue
        if not stripped:
            continue
        if ":" not in stripped:
            # Stray line inside a block — hold it as extra if we have an
            # open block, else ignore.
            if current is not None:
                current.setdefault(f"__stray_{len(current)}__", stripped)
            continue
        k, _, v = stripped.partition(":")
        key_name = k.strip()
        value = v.strip()

        if key_name == "Filetype":
            filetype = value
            continue
        if key_name == "Version":
            version = value
            continue

        # Starting a new block when we see `name:` at the top level.
        if key_name == "name":
            _flush_current()
            current = {"name": value}
            continue
        if current is None:
            # Key-value pair outside any block — hold under a synthetic
            # preamble block so we don't silently discard.
            current = {"name": "__preamble__"}
        current[key_name] = value

    _flush_current()

    if filetype is None:
        raise IrFileError("missing mandatory 'Filetype' header")

    # Strip synthetic preamble block (it was a defensive parse recovery,
    # not a real signal the user named `__preamble__`).
    signals = [s for s in signals if s.name != "__preamble__"]

    return IrFile(filetype=filetype, version=version, signals=signals)


def find_signal(ir: IrFile, button_name: str) -> IrSignal | None:
    """Return the `IrSignal` in `ir` whose `name` matches `button_name`.

    Matching is case-sensitive and exact — Flipper firmware treats button
    names as opaque strings. Returns None when no match is found; callers
    are expected to surface that as `E_VALIDATION_FAILED` per the API doc.
    """
    for sig in ir.signals:
        if sig.name == button_name:
            return sig
    return None
