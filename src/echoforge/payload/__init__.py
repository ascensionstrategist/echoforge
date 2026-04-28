"""
Payload Forge — parse, validate, and manage Flipper payload artifacts.

This package holds the pure-Python data-model / parsing layer for Phase 6
(BadUSB DuckyScripts, Sub-GHz `.sub` captures, Infrared `.ir` captures,
`.echoforge.json` sidecars, and the local payload library).

The MCP tool surface that exposes these to Claude lives in
`echoforge.agent.tools_payload`. Splitting "what is a payload" from "how
Claude calls it" keeps the parsers hardware-independent and easy to test.
"""

from __future__ import annotations

from echoforge.payload.duckyscript import (
    Diagnostic,
    DuckyCommand,
    ParseResult,
    RECOGNISED_COMMANDS,
    parse_script,
)
from echoforge.payload.linter import (
    ALL_RULE_CODES,
    LintFinding,
    LintReport,
    LintSeverity,
    lint,
    lint_parsed,
)
from echoforge.payload.irfile import (
    IrFile,
    IrFileError,
    IrSignal,
    find_signal,
    parse_ir,
)
from echoforge.payload.library import (
    DEVICE_ROOTS,
    LibraryEntry,
    LibraryIndex,
    build_index,
    search,
)
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
from echoforge.payload.subfile import (
    KNOWN_PRESETS,
    SubFile,
    SubFileError,
    parse_sub,
    retune,
    serialize_sub,
)

__all__ = [
    "ALL_RULE_CODES",
    "DEVICE_ROOTS",
    "Diagnostic",
    "DuckyCommand",
    "IrFile",
    "IrFileError",
    "IrSignal",
    "KNOWN_PRESETS",
    "LibraryEntry",
    "LibraryIndex",
    "LintFinding",
    "LintReport",
    "LintSeverity",
    "ParseResult",
    "RECOGNISED_COMMANDS",
    "SIDECAR_SCHEMA_VERSION",
    "SIDECAR_SUFFIX",
    "Sidecar",
    "SidecarSource",
    "SubFile",
    "SubFileError",
    "build_index",
    "compute_content_hash",
    "compute_content_hash_bytes",
    "dump_sidecar",
    "find_signal",
    "lint",
    "lint_parsed",
    "load_sidecar",
    "parse_ir",
    "parse_script",
    "parse_sub",
    "retune",
    "search",
    "serialize_sub",
    "sidecar_path_for",
    "utcnow_iso",
]
