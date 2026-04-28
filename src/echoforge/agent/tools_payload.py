"""
Payload Forge MCP tool surface.

Why this exists: Phase 6 of echoforge adds 13 authoring / inspection /
transmission tools for Flipper payloads (BadUSB, Sub-GHz, Infrared).
The parsers live in `echoforge.payload.*`; this module wraps them in
the Claude-Agent-SDK `@tool` form and composes them with the existing
`_with_recovery` resilience wrapper from `echoforge.agent.tools`.

Every tool follows the same contract as the Phase 4 surface:
  - async callable accepting a `dict[str, Any]` arg payload
  - returns `{"content": [{"type": "text", "text": ...}]}` (or `isError`)
  - wraps side-effect code in `_with_recovery(flipper, _run)`
  - declares its risk / hold gates exclusively via the ACTION_RULES +
    TOOL_TO_RISK_ACTION lookup — this module contains no safety logic.

Two hard implementation-layer rules live here (per
PHASE6_DECISIONS.md §3):
  1. `payload_subghz_tx` rejects any `duration_s > 600`.
  2. `payload_subghz_tx` rejects any `repeats > 100` (Phase 6 review
     fix: `duration_s` alone is trivially bypassed since the tool never
     forwards duration to the CC1101; `repeats` is the knob that
     actually loops on hardware).

Both caps are hardware-integrity safeguards, not safety-policy checks,
so they belong in the tool body.

Path confinement: every path argument (and every synthesised
`dest_path`) is gated by `_check_path(kind, path)` against the regexes
in PHASE6_PAYLOAD_FORGE_API.md §3.1. This is defense-in-depth layered
on top of `RiskAssessor`'s blocked-prefix check — both must agree
before any storage RPC fires.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from claude_agent_sdk import SdkMcpTool, tool

from echoforge.agent.tools import _ok, _with_recovery
from echoforge.flipper import Flipper
from echoforge.payload.duckyscript import parse_script
from echoforge.payload.irfile import find_signal, parse_ir
from echoforge.payload.linter import lint_parsed
from echoforge.payload.library import build_index, search
from echoforge.payload.sidecar import (
    Sidecar,
    SidecarSource,
    compute_content_hash_bytes,
    dump_sidecar,
    load_sidecar,
    sidecar_path_for,
    utcnow_iso,
)
from echoforge.payload.subfile import parse_sub, retune, serialize_sub
from echoforge.transport import RpcError

log = logging.getLogger(__name__)

__all__ = [
    "build_payload_tools",
    "TOOL_TO_RISK_ACTION_PAYLOAD",
    "TOOL_PRIMARY_PATH_FIELD_PAYLOAD",
    "MAX_TX_DURATION_S",
    "MAX_TX_REPEATS",
]

# Hard caps from PHASE6_DECISIONS.md §3. Not legal/policy checks —
# hardware-integrity safeguards to prevent stuck "transmit forever"
# loops from heating the CC1101 / draining the battery.
MAX_TX_DURATION_S: int = 600
# Review H1 fix: `repeats` has no firmware cap and loops on the radio
# until the count is exhausted. 100 replays is enough for any legitimate
# fuzz/replay scenario (operator re-issues the call for more airtime).
# Option (b) — "compute estimated runtime from SubFile sample count ×
# repeats and reject when > 600s" — was considered but the RAW_Data
# timing extraction requires protocol knowledge the tool layer
# deliberately doesn't have (per PHASE6_PAYLOAD_FORGE_API.md §3.3: "RAW_Data
# is never written by Claude"). Hard cap is the safer fallback.
MAX_TX_REPEATS: int = 100


# ---------------------------------------------------------------------------
# Path confinement (PHASE6_PAYLOAD_FORGE_API.md §3.1)
# ---------------------------------------------------------------------------

# One regex per kind. Matches the allowed path template:
#   /ext/<kind_root>/<name>.<ext>
# where <name> is 1..120 chars of `A-Z a-z 0-9 _ - . /` (space too).
# NOTE: `/` is allowed inside the body to support nested dirs
# (`/ext/subghz/captures/garage.sub`), but literal `..` is rejected
# explicitly below to prevent path traversal.
_PATH_REGEX: dict[str, re.Pattern[str]] = {
    "badusb": re.compile(r"^/ext/badusb/[A-Za-z0-9 _\-./]{1,120}\.txt$"),
    "subghz": re.compile(r"^/ext/subghz/[A-Za-z0-9 _\-./]{1,120}\.sub$"),
    "ir": re.compile(r"^/ext/infrared/[A-Za-z0-9 _\-./]{1,120}\.ir$"),
}

# Kinds that a `_check_path` call can validate against. The Payload
# Forge `_list` tools don't take a full file path (just a `subdir`),
# so they use `_check_subdir` instead.
_KIND_ROOTS: dict[str, str] = {
    "badusb": "/ext/badusb",
    "subghz": "/ext/subghz",
    "ir": "/ext/infrared",
}


def _check_path(kind: str, path: str, *, field_name: str = "path") -> dict[str, Any] | None:
    """Return an error response if `path` is outside the kind-specific allowlist.

    None means the path passed. A dict means the tool should return it
    immediately as its response.

    Rejects three classes of bad input:
      1. Non-string / empty (caught by individual tools' `isinstance`
         guards, but we sanity-check here too).
      2. Literal `..` substring (path traversal).
      3. Regex mismatch per §3.1 (wrong root, wrong extension,
         forbidden chars).

    `field_name` is echoed in the error text so Claude can tell which
    argument was wrong when a tool takes `source_path` + `dest_path`.
    """
    if not isinstance(path, str) or not path:
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            f"{field_name} is required and must be a non-empty string",
        )
    if ".." in path:
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            f"{field_name}={path!r}: '..' path segments are rejected",
        )
    regex = _PATH_REGEX.get(kind)
    if regex is None:  # programming error, not a user-facing case
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            f"{field_name}={path!r}: unknown kind {kind!r}",
        )
    if not regex.match(path):
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            (
                f"{field_name}={path!r}: must match {regex.pattern} "
                f"(per PHASE6_PAYLOAD_FORGE_API.md §3.1)"
            ),
        )
    return None


def _check_subdir(kind: str, subdir: str) -> dict[str, Any] | None:
    """Return an error response if a `_list` `subdir` arg attempts traversal.

    `subdir` is always relative to the kind root. Empty string is fine
    (means "root"). We reject `..`, leading `/`, and any char not
    matching `[A-Za-z0-9 _\\-./]` — i.e. same body charset as the full
    path regex, minus extension.
    """
    if not isinstance(subdir, str):
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            f"subdir must be a string, got {type(subdir).__name__}",
        )
    if subdir == "":
        return None
    if ".." in subdir or subdir.startswith("/"):
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            f"subdir={subdir!r}: rejected ('..' or leading '/')",
        )
    if not re.match(r"^[A-Za-z0-9 _\-./]+$", subdir):
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            f"subdir={subdir!r}: contains disallowed characters",
        )
    # Also reject if after joining with the root we escape the kind
    # root — impossible given the above guards, but defense-in-depth.
    root = _KIND_ROOTS.get(kind)
    if root is None:
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED", f"unknown kind {kind!r}"
        )
    return None


def _check_dest_name(dest_name: str) -> dict[str, Any] | None:
    """Return an error response if `dest_name` looks like a path.

    Per §3.1: `dest_name` in `_import_capture` / `_retune` is a filename
    only (`[A-Za-z0-9 _\\-.]{1,80}`), not a path. The tool joins it
    with the fixed target dir. We reject `/`, `..`, empty, and control
    chars here — the synthesised `dest_path` is re-checked with
    `_check_path` after joining, which catches anything we miss.
    """
    if not isinstance(dest_name, str) or not dest_name:
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            "dest_name is required and must be a non-empty string",
        )
    if "/" in dest_name or ".." in dest_name:
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            f"dest_name={dest_name!r}: must be a filename, not a path",
        )
    if not re.match(r"^[A-Za-z0-9 _\-.]{1,80}$", dest_name):
        return _err_code(
            "E_PATH_OUTSIDE_ALLOWED",
            (
                f"dest_name={dest_name!r}: must match "
                f"[A-Za-z0-9 _\\-.]{{1,80}}"
            ),
        )
    return None


def _err_code(code: str, msg: str) -> dict[str, Any]:
    """Return an error response with a machine-parseable bracketed code.

    Matches the error taxonomy in PHASE6_PAYLOAD_FORGE_API.md §4.
    """
    return {
        "content": [{"type": "text", "text": f"ERROR[{code}]: {msg}"}],
        "isError": True,
    }


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------


def build_payload_tools(flipper: Flipper) -> list[SdkMcpTool]:
    """Return the 13 Payload Forge MCP tools, bound to `flipper`.

    Caller is expected to merge the returned list into the MCP server
    tool registry alongside `build_flipper_tools(flipper)` — see
    `echoforge.agent.runner.build_runtime`.
    """
    tools: list[SdkMcpTool] = []

    # -----------------------------------------------------------------------
    # 1. payload_badusb_validate  (LOW, pure function)
    # -----------------------------------------------------------------------

    @tool(
        "payload_badusb_validate",
        "Syntactically validate a DuckyScript (BadUSB) payload. Returns "
        "a list of diagnostics (line, severity, code, message) and basic "
        "stats. Pure function — no device I/O, no side effects. Does not "
        "classify content meaning per phase-6 safety decisions. Pass "
        "strict=true to additionally run the Flipper-dialect linter "
        "(~25 rules: style, portability, idiom compliance); lint "
        "findings appear in `lint_findings`.",
        {"script_text": str, "strict": bool},
    )
    async def payload_badusb_validate(args: dict[str, Any]) -> dict[str, Any]:
        script_text = args.get("script_text", "")
        if not isinstance(script_text, str):
            return _err_code("E_UNSUPPORTED_ARG", "script_text must be a string")
        strict = bool(args.get("strict", False))
        result = parse_script(script_text)
        issues = [
            {
                "line": d.line_no,
                "severity": d.severity,
                "code": d.code,
                "message": d.message,
            }
            for d in result.diagnostics
        ]
        string_count = sum(
            1 for c in result.commands if c.command in {"STRING", "STRINGLN"}
        )
        delay_total_ms = 0
        for c in result.commands:
            if c.command in {"DELAY", "DEFAULTDELAY", "DEFAULT_DELAY"}:
                try:
                    delay_total_ms += int(c.args.strip())
                except (ValueError, AttributeError):
                    pass
        payload: dict[str, Any] = {
            "ok": result.ok,
            "issues": issues,
            "stats": {
                "lines": result.line_count,
                "strings": string_count,
                "delays_ms_total": delay_total_ms,
            },
        }
        if strict:
            report = lint_parsed(script_text, result)
            payload["lint_findings"] = [
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "line": f.line,
                    "column": f.column,
                    "message": f.message,
                    "suggestion": f.suggestion,
                }
                for f in report.findings
            ]
            # In strict mode, surfacing lint errors as non-ok helps
            # callers who pipeline `_validate` → `_create`: a lint
            # error (E007 unsupported control flow) is still a block.
            if report.has_errors:
                payload["ok"] = False
        return _ok(
            f"validated {result.line_count} commands, {len(issues)} issue(s)",
            **payload,
        )

    # -----------------------------------------------------------------------
    # 2. payload_badusb_create  (MED, writes .txt + sidecar)
    # -----------------------------------------------------------------------

    @tool(
        "payload_badusb_create",
        "Save a DuckyScript BadUSB payload to /ext/badusb/<name>.txt on "
        "the Flipper, plus a sibling .echoforge.json sidecar. Validates "
        "syntax before writing; refuses to overwrite unless "
        "overwrite=true. Path is Flipper-side (POSIX), not a host path. "
        "`policy_tag` is optional — Claude may supply a short identifier "
        "(e.g. 'prank', 'credential-demo', 'vehicle-capture') that is "
        "written into the sidecar verbatim; operator can edit it later.",
        {
            "name": str,
            "script_text": str,
            "description": str,
            "author": str,
            "tags": list,
            "policy_tag": str,
            "overwrite": bool,
        },
    )
    async def payload_badusb_create(args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name")
        script_text = args.get("script_text")
        if not isinstance(name, str) or not name:
            return _err_code("E_UNSUPPORTED_ARG", "name is required")
        if not isinstance(script_text, str):
            return _err_code("E_UNSUPPORTED_ARG", "script_text is required")
        # Validate syntax before writing.
        result = parse_script(script_text)
        if not result.ok:
            return _err_code(
                "E_VALIDATION_FAILED",
                f"{len(result.diagnostics)} issue(s); "
                f"{sum(1 for d in result.diagnostics if d.severity == 'error')} error(s)",
            )

        # `name` may be supplied with or without the `.txt` suffix, and
        # may itself contain sub-directories. Strip illegal chars by
        # letting `_check_path` reject the full synthesised path below.
        fname = name if name.endswith(".txt") else f"{name}.txt"
        path = f"/ext/badusb/{fname}"
        # Path confinement (§3.1 + review C2.1).
        err = _check_path("badusb", path, field_name="name(->path)")
        if err is not None:
            return err
        overwrite = bool(args.get("overwrite", False))
        description = args.get("description") or ""
        author = args.get("author") or ""
        tags = args.get("tags") or []
        if not isinstance(tags, list):
            return _err_code("E_UNSUPPORTED_ARG", "tags must be a list of strings")
        policy_tag_raw = args.get("policy_tag")
        if policy_tag_raw is not None and not isinstance(policy_tag_raw, str):
            return _err_code(
                "E_UNSUPPORTED_ARG", "policy_tag must be a string or omitted"
            )
        policy_tag: str | None = policy_tag_raw or None

        def _run() -> dict[str, Any]:
            # Existence check — avoid silent overwrites.
            #
            # Review M4: only swallow RpcError / FileNotFoundError here;
            # let TimeoutError propagate so `_with_recovery` can kick in
            # reconnect + retry.
            if not overwrite:
                try:
                    if flipper.storage.exists(path):
                        return _err_code(
                            "E_PATH_EXISTS",
                            f"{path} already exists; pass overwrite=true to replace",
                        )
                except (RpcError, FileNotFoundError):
                    # If existence check itself fails for a "not found"
                    # reason, fall through to write attempt; the storage
                    # layer will surface any real error.
                    pass
            payload_bytes = script_text.encode("utf-8")
            flipper.storage.write(path, payload_bytes)
            # Sidecar.
            side = Sidecar(
                kind="badusb",
                name=name,
                description=description,
                author=author,
                tags=[str(t) for t in tags],
                policy_tag=policy_tag,
                content_hash=compute_content_hash_bytes(payload_bytes),
                created_at=utcnow_iso(),
                updated_at=utcnow_iso(),
                source=SidecarSource(origin="created"),
            )
            side_path = sidecar_path_for(path)
            sidecar_failed: str | None = None
            try:
                flipper.storage.write(side_path, dump_sidecar(side).encode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                # Non-fatal per API.md §4 — payload is usable, sidecar can
                # be rewritten.
                sidecar_failed = f"{type(exc).__name__}: {exc}"
                log.warning("sidecar write failed for %s: %s", side_path, exc)

            validation = {
                "ok": result.ok,
                "warnings": [
                    {
                        "line": d.line_no,
                        "code": d.code,
                        "message": d.message,
                    }
                    for d in result.diagnostics
                    if d.severity != "error"
                ],
            }
            response = {
                "path": path,
                "bytes_written": len(payload_bytes),
                "validation": validation,
                "sidecar_path": side_path,
            }
            if sidecar_failed is not None:
                response["sidecar_error"] = sidecar_failed
            return _ok(
                f"wrote {len(payload_bytes)} B to {path}",
                **response,
            )

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 3. payload_badusb_run  (HIGH + hold, physical actuation)
    # -----------------------------------------------------------------------

    @tool(
        "payload_badusb_run",
        "Execute a DuckyScript BadUSB payload already on the Flipper. "
        "HIGH RISK — types real keystrokes into whatever host the Flipper "
        "is plugged into RIGHT NOW. Hold-to-confirm required. Path must "
        "be /ext/badusb/<name>.txt.",
        {"script_path": str},
    )
    async def payload_badusb_run(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("script_path")
        if not isinstance(path, str) or not path:
            return _err_code("E_UNSUPPORTED_ARG", "script_path is required")
        err = _check_path("badusb", path, field_name="script_path")
        if err is not None:
            return err

        def _run() -> dict[str, Any]:
            ack = flipper.badusb.run(path)
            return _ok(
                f"BadUSB started: {ack.command!r}",
                command=ack.command,
                ack_output=ack.output,
            )

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 4. payload_subghz_list  (LOW, directory read)
    # -----------------------------------------------------------------------

    @tool(
        "payload_subghz_list",
        "List .sub files under /ext/subghz (non-recursive). Each entry "
        "carries name, path, size, has_sidecar flag, and (when a sidecar "
        "is present) its tags.",
        {"subdir": str},
    )
    async def payload_subghz_list(args: dict[str, Any]) -> dict[str, Any]:
        subdir = args.get("subdir") or ""
        err = _check_subdir("subghz", subdir)
        if err is not None:
            return err
        root = "/ext/subghz"
        if subdir:
            root = f"{root}/{subdir.strip('/')}"

        def _run() -> dict[str, Any]:
            entries = flipper.storage.list(root)
            # Build a sidecar-name set for fast has_sidecar lookups.
            all_names = {getattr(e, "name", "") for e in entries}
            rows: list[dict[str, Any]] = []
            for e in entries:
                name = getattr(e, "name", "")
                type_attr = getattr(e, "type", None)
                type_name = getattr(type_attr, "name", None) or str(type_attr)
                if type_name != "FILE":
                    continue
                if not name.endswith(".sub"):
                    continue
                stem = name[:-4]
                sidecar_name = f"{stem}.echoforge.json"
                rows.append(
                    {
                        "name": name,
                        "path": f"{root}/{name}",
                        "size": getattr(e, "size", 0),
                        "has_sidecar": sidecar_name in all_names,
                    }
                )
            return _ok(f"{len(rows)} .sub file(s) in {root}", entries=rows)

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 5. payload_subghz_inspect  (LOW, parse headers)
    # -----------------------------------------------------------------------

    @tool(
        "payload_subghz_inspect",
        "Parse one .sub file into headers + RAW_Data stats. Headers are "
        "returned as a flat dict; raw_stats is present when the file "
        "carries RAW_Data lines.",
        {"path": str},
    )
    async def payload_subghz_inspect(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path")
        if not isinstance(path, str) or not path:
            return _err_code("E_UNSUPPORTED_ARG", "path is required")
        err = _check_path("subghz", path, field_name="path")
        if err is not None:
            return err

        def _run() -> dict[str, Any]:
            data = flipper.storage.read(path)
            try:
                sub = parse_sub(data)
            except Exception as exc:  # noqa: BLE001
                return _err_code(
                    "E_VALIDATION_FAILED", f"parse failed: {type(exc).__name__}: {exc}"
                )
            headers: dict[str, Any] = {"Filetype": sub.filetype}
            if sub.version is not None:
                headers["Version"] = sub.version
            for k, v in (
                ("Frequency", sub.frequency),
                ("Preset", sub.preset),
                ("Protocol", sub.protocol),
                ("Bit", sub.bit),
                ("TE", sub.te),
                ("Key", sub.key),
            ):
                if v is not None:
                    headers[k] = v
            headers.update(
                {k: v for k, v in sub.extra.items() if not k.startswith("__line_")}
            )
            raw_stats: dict[str, Any] | None = None
            if sub.has_raw_data:
                raw_stats = {
                    "samples": sub.sample_count,
                    "lines": len(sub.raw_data_lines),
                }
            payload: dict[str, Any] = {"headers": headers}
            if raw_stats is not None:
                payload["raw_stats"] = raw_stats
            return _ok(f"parsed {path}", **payload)

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 6. payload_subghz_retune  (MED, derived write)
    # -----------------------------------------------------------------------

    @tool(
        "payload_subghz_retune",
        "Create a derived .sub by rewriting Frequency and/or Preset on an "
        "existing capture. RAW_Data is preserved verbatim — never "
        "re-encoded. Writes as a new file at /ext/subghz/<dest_name>. "
        "Inherits author / tags / description from the source sidecar "
        "(if any); caller-supplied description overrides.",
        {
            "source_path": str,
            "dest_name": str,
            "frequency_hz": int,
            "preset": str,
            "description": str,
        },
    )
    async def payload_subghz_retune(args: dict[str, Any]) -> dict[str, Any]:
        source_path = args.get("source_path")
        dest_name = args.get("dest_name")
        if not isinstance(source_path, str) or not source_path:
            return _err_code("E_UNSUPPORTED_ARG", "source_path is required")
        if not isinstance(dest_name, str) or not dest_name:
            return _err_code("E_UNSUPPORTED_ARG", "dest_name is required")
        # Review C2.1: confine source_path to /ext/subghz/*.sub.
        err = _check_path("subghz", source_path, field_name="source_path")
        if err is not None:
            return err
        err = _check_dest_name(dest_name)
        if err is not None:
            return err
        freq = args.get("frequency_hz")
        preset = args.get("preset")
        if freq is None and preset is None:
            return _err_code(
                "E_UNSUPPORTED_ARG",
                "at least one of frequency_hz / preset must be provided",
            )
        if freq is not None:
            try:
                freq = int(freq)
            except (TypeError, ValueError):
                return _err_code(
                    "E_UNSUPPORTED_ARG", f"frequency_hz must be int, got {freq!r}"
                )

        dest_fname = dest_name if dest_name.endswith(".sub") else f"{dest_name}.sub"
        dest_path = f"/ext/subghz/{dest_fname}"
        # Re-check the synthesised dest_path — belt-and-braces against a
        # dest_name that slipped through (`_check_dest_name` is strict,
        # but the join + extension logic is worth a second pass).
        err = _check_path("subghz", dest_path, field_name="dest_path")
        if err is not None:
            return err

        def _run() -> dict[str, Any]:
            # Review M5: distinguish "source missing" from "source read
            # exploded for some other reason". Only FileNotFoundError /
            # RpcError with STORAGE_NOT_EXIST are truly PATH_NOT_FOUND.
            try:
                source_blob = flipper.storage.read(source_path)
            except FileNotFoundError as exc:
                return _err_code(
                    "E_PATH_NOT_FOUND",
                    f"{source_path}: {type(exc).__name__}: {exc}",
                )
            except RpcError as exc:
                if exc.status_name == "ERROR_STORAGE_NOT_EXIST":
                    return _err_code(
                        "E_PATH_NOT_FOUND",
                        f"{source_path}: {type(exc).__name__}: {exc}",
                    )
                return _err_code(
                    "E_STORAGE_READ_FAILED",
                    f"{source_path}: {type(exc).__name__}: {exc}",
                )
            except Exception as exc:  # noqa: BLE001
                return _err_code(
                    "E_STORAGE_READ_FAILED",
                    f"{source_path}: {type(exc).__name__}: {exc}",
                )
            try:
                sub = parse_sub(source_blob)
            except Exception as exc:  # noqa: BLE001
                return _err_code(
                    "E_VALIDATION_FAILED",
                    f"source parse failed: {type(exc).__name__}: {exc}",
                )
            old_freq = sub.frequency
            old_preset = sub.preset
            retuned = retune(
                sub,
                frequency=freq if freq is not None else None,
                preset=preset if isinstance(preset, str) else None,
            )
            out_text = serialize_sub(retuned)
            payload_bytes = out_text.encode("utf-8")
            flipper.storage.write(dest_path, payload_bytes)
            # Review M3: inherit author/tags/description from source
            # sidecar if present. Caller-supplied description overrides.
            inherited_author = ""
            inherited_tags: list[str] = []
            inherited_description = ""
            inherited_policy_tag: str | None = None
            source_side_path = sidecar_path_for(source_path)
            try:
                src_side_blob = flipper.storage.read(source_side_path)
                src_side = load_sidecar(src_side_blob)
                inherited_author = src_side.author
                inherited_tags = list(src_side.tags)
                inherited_description = src_side.description
                inherited_policy_tag = src_side.policy_tag
            except (FileNotFoundError, RpcError):
                # No source sidecar — fine, just use blanks.
                pass
            except Exception as exc:  # noqa: BLE001
                log.debug(
                    "retune: source sidecar parse failed for %s: %s",
                    source_side_path,
                    exc,
                )

            description = args.get("description") or inherited_description or ""
            side = Sidecar(
                kind="subghz",
                name=dest_name,
                description=description,
                author=inherited_author,
                tags=inherited_tags,
                policy_tag=inherited_policy_tag,
                content_hash=compute_content_hash_bytes(payload_bytes),
                source=SidecarSource(origin="imported", capture_freq_mhz=None),
            )
            side_path = sidecar_path_for(dest_path)
            try:
                flipper.storage.write(
                    side_path, dump_sidecar(side).encode("utf-8")
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("sidecar write failed for %s: %s", side_path, exc)
            diff = {
                "frequency_hz": [old_freq, retuned.frequency],
                "preset": [old_preset, retuned.preset],
            }
            return _ok(
                f"retuned {source_path} -> {dest_path}",
                path=dest_path,
                source_path=source_path,
                sidecar_path=side_path,
                diff=diff,
            )

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 7. payload_subghz_import_capture  (MED, rename + sidecar)
    # -----------------------------------------------------------------------

    @tool(
        "payload_subghz_import_capture",
        "Rename a just-captured .sub to a human-friendly name and write a "
        "sidecar with description/tags/author. Uses the Flipper's rename "
        "RPC (same file stays on device; just moves on the FS). "
        "`policy_tag` is optional — operator/Claude may tag the sidecar "
        "at import time.",
        {
            "source_path": str,
            "dest_name": str,
            "description": str,
            "tags": list,
            "author": str,
            "policy_tag": str,
        },
    )
    async def payload_subghz_import_capture(args: dict[str, Any]) -> dict[str, Any]:
        return _import_capture_generic(
            flipper=flipper,
            args=args,
            kind="subghz",
            root="/ext/subghz",
            ext=".sub",
        )

    # -----------------------------------------------------------------------
    # 8. payload_subghz_tx  (HIGH + hold, physical actuation)
    #    HARD CAPS: duration_s > 600 rejected AND repeats > 100 rejected.
    # -----------------------------------------------------------------------

    @tool(
        "payload_subghz_tx",
        "Broadcast a stored .sub file via the Flipper's CC1101. HIGH "
        "RISK: real RF emission visible to nearby receivers. Hold-to-"
        "confirm required. Hard caps: duration_s > 600 rejected "
        "(operator-declared duration); repeats > 100 rejected (hardware "
        "loop cap — the tool forwards `repeats` to `subghz tx_from_file` "
        "which replays on hardware, so an unbounded repeats value is "
        "the actual 'transmit forever' footgun). Re-issue the call if "
        "you truly need more airtime.",
        {"signal_file": str, "repeats": int, "duration_s": int},
    )
    async def payload_subghz_tx(args: dict[str, Any]) -> dict[str, Any]:
        signal_file = args.get("signal_file")
        if not isinstance(signal_file, str) or not signal_file:
            return _err_code("E_UNSUPPORTED_ARG", "signal_file is required")
        err = _check_path("subghz", signal_file, field_name="signal_file")
        if err is not None:
            return err
        # Optional operator-declared duration. When present, enforce the
        # 600s cap. When absent, we cannot bound the TX from host-side —
        # the firmware's own emission cycle terminates it — but we still
        # accept the call because sub-second TXs are overwhelmingly the
        # common case.
        duration_s = args.get("duration_s")
        if duration_s is not None:
            try:
                duration_s = int(duration_s)
            except (TypeError, ValueError):
                return _err_code(
                    "E_UNSUPPORTED_ARG",
                    f"duration_s must be int, got {duration_s!r}",
                )
            if duration_s < 0:
                return _err_code(
                    "E_UNSUPPORTED_ARG", f"duration_s must be >= 0, got {duration_s}"
                )
            if duration_s > MAX_TX_DURATION_S:
                return _err_code(
                    "E_UNSUPPORTED_ARG",
                    (
                        f"duration_s={duration_s} exceeds hardware cap of "
                        f"{MAX_TX_DURATION_S}s (PHASE6_DECISIONS §3). "
                        f"Re-issue the call for additional airtime."
                    ),
                )
        # Review H1: `repeats` is the knob that actually loops on the
        # radio. An unbounded value = stuck transmit-forever. Hard cap
        # at MAX_TX_REPEATS (100) regardless of `duration_s` value.
        # Default: 1 when omitted or None (the common "fire once" path).
        repeats_raw = args.get("repeats")
        if repeats_raw is None:
            repeats = 1
        else:
            try:
                repeats = int(repeats_raw)
            except (TypeError, ValueError):
                return _err_code(
                    "E_UNSUPPORTED_ARG",
                    f"repeats must be int, got {repeats_raw!r}",
                )
        if repeats < 1:
            return _err_code(
                "E_UNSUPPORTED_ARG",
                f"repeats must be >= 1, got {repeats}",
            )
        if repeats > MAX_TX_REPEATS:
            return _err_code(
                "E_UNSUPPORTED_ARG",
                (
                    f"repeats={repeats} exceeds hardware cap of "
                    f"{MAX_TX_REPEATS} (PHASE6_DECISIONS §3). Re-issue the "
                    f"call for more replays."
                ),
            )

        def _run() -> dict[str, Any]:
            ack = flipper.subghz.transmit_from_file(signal_file, repeats=repeats)
            return _ok(
                f"TX sent: {ack.command!r}",
                command=ack.command,
                ack_output=ack.output,
            )

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 9. payload_ir_list  (LOW, directory read)
    # -----------------------------------------------------------------------

    @tool(
        "payload_ir_list",
        "List .ir files under /ext/infrared. include_universal=true walks "
        "/ext/infrared/universal/ too.",
        {"subdir": str, "include_universal": bool},
    )
    async def payload_ir_list(args: dict[str, Any]) -> dict[str, Any]:
        subdir = args.get("subdir") or ""
        err = _check_subdir("ir", subdir)
        if err is not None:
            return err
        root = "/ext/infrared"
        if subdir:
            root = f"{root}/{subdir.strip('/')}"

        def _run() -> dict[str, Any]:
            entries = flipper.storage.list(root)
            names = {getattr(e, "name", "") for e in entries}
            rows: list[dict[str, Any]] = []
            for e in entries:
                name = getattr(e, "name", "")
                type_attr = getattr(e, "type", None)
                type_name = getattr(type_attr, "name", None) or str(type_attr)
                if type_name != "FILE":
                    continue
                if not name.endswith(".ir"):
                    continue
                stem = name[:-3]
                sidecar_name = f"{stem}.echoforge.json"
                rows.append(
                    {
                        "name": name,
                        "path": f"{root}/{name}",
                        "size": getattr(e, "size", 0),
                        "has_sidecar": sidecar_name in names,
                    }
                )
            return _ok(f"{len(rows)} .ir file(s) in {root}", entries=rows)

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 10. payload_ir_inspect  (LOW, parse blocks)
    # -----------------------------------------------------------------------

    @tool(
        "payload_ir_inspect",
        "Parse one .ir file into its list of named signals. Each signal "
        "has name / type ('parsed' or 'raw') and type-specific fields.",
        {"path": str},
    )
    async def payload_ir_inspect(args: dict[str, Any]) -> dict[str, Any]:
        path = args.get("path")
        if not isinstance(path, str) or not path:
            return _err_code("E_UNSUPPORTED_ARG", "path is required")
        err = _check_path("ir", path, field_name="path")
        if err is not None:
            return err

        def _run() -> dict[str, Any]:
            try:
                data = flipper.storage.read(path)
            except (FileNotFoundError, RpcError) as exc:
                return _err_code(
                    "E_PATH_NOT_FOUND", f"{path}: {type(exc).__name__}: {exc}"
                )
            except Exception as exc:  # noqa: BLE001
                return _err_code(
                    "E_STORAGE_READ_FAILED",
                    f"{path}: {type(exc).__name__}: {exc}",
                )
            try:
                ir = parse_ir(data)
            except Exception as exc:  # noqa: BLE001
                return _err_code(
                    "E_VALIDATION_FAILED",
                    f"parse failed: {type(exc).__name__}: {exc}",
                )
            signals: list[dict[str, Any]] = []
            for s in ir.signals:
                sig_data: dict[str, Any] = {"name": s.name, "type": s.type}
                if s.protocol is not None:
                    sig_data["protocol"] = s.protocol
                if s.address is not None:
                    sig_data["address"] = s.address
                if s.command is not None:
                    sig_data["command"] = s.command
                if s.frequency is not None:
                    sig_data["frequency"] = s.frequency
                if s.duty_cycle is not None:
                    sig_data["duty_cycle"] = s.duty_cycle
                sc = s.sample_count
                if sc is not None:
                    sig_data["sample_count"] = sc
                signals.append(sig_data)
            return _ok(
                f"parsed {path} ({len(signals)} signal(s))", signals=signals
            )

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 11. payload_ir_import_capture  (MED, rename + sidecar)
    # -----------------------------------------------------------------------

    @tool(
        "payload_ir_import_capture",
        "Rename a just-captured .ir to a human-friendly name and write a "
        "sidecar with description/tags/author. `policy_tag` is optional.",
        {
            "source_path": str,
            "dest_name": str,
            "description": str,
            "tags": list,
            "author": str,
            "policy_tag": str,
        },
    )
    async def payload_ir_import_capture(args: dict[str, Any]) -> dict[str, Any]:
        return _import_capture_generic(
            flipper=flipper,
            args=args,
            kind="ir",
            root="/ext/infrared",
            ext=".ir",
        )

    # -----------------------------------------------------------------------
    # 12. payload_ir_transmit  (MED, physical but line-of-sight)
    # -----------------------------------------------------------------------

    @tool(
        "payload_ir_transmit",
        "Transmit a named button from a stored .ir file via the "
        "Flipper's IR LED. If button_name is provided, it is first "
        "resolved against the file's signal list; validation_failed on "
        "miss. Line-of-sight ~10m — MED risk, one-tap approval.",
        {"signal_file": str, "button_name": str},
    )
    async def payload_ir_transmit(args: dict[str, Any]) -> dict[str, Any]:
        signal_file = args.get("signal_file")
        button_name = args.get("button_name") or None
        if not isinstance(signal_file, str) or not signal_file:
            return _err_code("E_UNSUPPORTED_ARG", "signal_file is required")
        err = _check_path("ir", signal_file, field_name="signal_file")
        if err is not None:
            return err

        def _run() -> dict[str, Any]:
            resolved: str | None = None
            if button_name:
                try:
                    data = flipper.storage.read(signal_file)
                    ir = parse_ir(data)
                    sig = find_signal(ir, button_name)
                except (FileNotFoundError, RpcError) as exc:
                    return _err_code(
                        "E_PATH_NOT_FOUND",
                        f"{signal_file}: {type(exc).__name__}: {exc}",
                    )
                except Exception as exc:  # noqa: BLE001
                    return _err_code(
                        "E_STORAGE_READ_FAILED",
                        f"{signal_file}: {type(exc).__name__}: {exc}",
                    )
                if sig is None:
                    return _err_code(
                        "E_VALIDATION_FAILED",
                        (
                            f"button {button_name!r} not found in {signal_file}. "
                            f"Available: {ir.names()}"
                        ),
                    )
                resolved = sig.name
            ack = flipper.ir.transmit_from_file(signal_file, button_name=button_name)
            return _ok(
                f"IR sent: {ack.command!r}",
                command=ack.command,
                ack_output=ack.output,
                resolved_button=resolved,
            )

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # 13. payload_library_search  (LOW, sidecar index scan)
    # -----------------------------------------------------------------------

    @tool(
        "payload_library_search",
        "Search .echoforge.json sidecars across /ext/badusb, /ext/subghz, "
        "/ext/infrared for a free-text match on name/description/tags. "
        "Useful when the operator says 'transmit that Ford key I "
        "captured last week.'",
        {"query": str, "kinds": list, "limit": int},
    )
    async def payload_library_search(args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query") or ""
        kinds = args.get("kinds") or None
        limit = int(args.get("limit", 20) or 20)

        def _run() -> dict[str, Any]:
            index = build_index(flipper.storage, kinds=kinds)
            hits = search(index, query, kinds=kinds, limit=limit)
            rows = [
                {
                    "path": h.path,
                    "kind": h.kind,
                    "name": h.name,
                    "description": h.description,
                    "tags": list(h.tags),
                    "author": h.author,
                    "source": h.source,
                    "drifted": h.drifted,
                }
                for h in hits
            ]
            return _ok(f"{len(rows)} match(es) for {query!r}", results=rows)

        return _with_recovery(flipper, _run)

    # -----------------------------------------------------------------------
    # Register the full surface.
    # -----------------------------------------------------------------------
    tools.extend(
        [
            payload_badusb_validate,
            payload_badusb_create,
            payload_badusb_run,
            payload_subghz_list,
            payload_subghz_inspect,
            payload_subghz_retune,
            payload_subghz_import_capture,
            payload_subghz_tx,
            payload_ir_list,
            payload_ir_inspect,
            payload_ir_import_capture,
            payload_ir_transmit,
            payload_library_search,
        ]
    )
    return tools


# ---------------------------------------------------------------------------
# Shared helper for subghz / ir import_capture (both have identical shape)
# ---------------------------------------------------------------------------


def _import_capture_generic(
    *,
    flipper: Flipper,
    args: dict[str, Any],
    kind: str,
    root: str,
    ext: str,
) -> dict[str, Any]:
    """Rename + sidecar-write helper shared by subghz / ir import tools.

    Factored out because the two tools differ only in `kind`, `root`,
    and the expected file extension — the logic (rename, compute hash,
    write sidecar) is identical. Kept as a free function (not a method)
    to mirror the pattern in `agent/tools.py`.
    """
    source_path = args.get("source_path")
    dest_name = args.get("dest_name")
    if not isinstance(source_path, str) or not source_path:
        return _err_code("E_UNSUPPORTED_ARG", "source_path is required")
    if not isinstance(dest_name, str) or not dest_name:
        return _err_code("E_UNSUPPORTED_ARG", "dest_name is required")
    # Review C2.1: confine source_path and dest_name before any RPC.
    err = _check_path(kind, source_path, field_name="source_path")
    if err is not None:
        return err
    err = _check_dest_name(dest_name)
    if err is not None:
        return err

    dest_fname = dest_name if dest_name.endswith(ext) else f"{dest_name}{ext}"
    dest_path = f"{root}/{dest_fname}"
    # Re-check synthesised dest_path. `_check_dest_name` already blocks
    # `/` and `..`, but we still want the kind-root regex match on the
    # full synthesised path.
    err = _check_path(kind, dest_path, field_name="dest_path")
    if err is not None:
        return err
    description = args.get("description") or ""
    author = args.get("author") or ""
    tags = args.get("tags") or []
    if not isinstance(tags, list):
        return _err_code("E_UNSUPPORTED_ARG", "tags must be a list of strings")
    policy_tag_raw = args.get("policy_tag")
    if policy_tag_raw is not None and not isinstance(policy_tag_raw, str):
        return _err_code(
            "E_UNSUPPORTED_ARG", "policy_tag must be a string or omitted"
        )
    policy_tag: str | None = policy_tag_raw or None

    def _run() -> dict[str, Any]:
        try:
            flipper.storage.rename(source_path, dest_path)
        except (FileNotFoundError, RpcError) as exc:
            return _err_code(
                "E_PATH_NOT_FOUND",
                f"rename {source_path} -> {dest_path}: "
                f"{type(exc).__name__}: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return _err_code(
                "E_STORAGE_READ_FAILED",
                f"rename {source_path} -> {dest_path}: "
                f"{type(exc).__name__}: {exc}",
            )
        # Read back the payload so we can hash it accurately.
        #
        # Review M1: if the read-back fails, DO NOT silently write a
        # sidecar with sha256(b"") — that hash will look valid but
        # never match the real file contents, permanently poisoning
        # drift-detection for that payload. Return E_SIDECAR_WRITE_FAILED
        # and tell the caller the payload is usable but the sidecar
        # needs to be rewritten once the device is reachable.
        try:
            payload_blob = flipper.storage.read(dest_path)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "sidecar skipped for %s: read-back failed (%s)", dest_path, exc
            )
            return _err_code(
                "E_SIDECAR_WRITE_FAILED",
                (
                    f"payload renamed to {dest_path} but post-rename read-back "
                    f"failed: {type(exc).__name__}: {exc}. Payload is usable; "
                    f"retry to generate the sidecar."
                ),
            )
        side = Sidecar(
            kind=kind,  # type: ignore[arg-type]
            name=dest_name,
            description=description,
            author=author,
            tags=[str(t) for t in tags],
            policy_tag=policy_tag,
            content_hash=compute_content_hash_bytes(payload_blob),
            source=SidecarSource(origin="captured"),
        )
        side_path = sidecar_path_for(dest_path)
        sidecar_err: str | None = None
        try:
            flipper.storage.write(
                side_path, dump_sidecar(side).encode("utf-8")
            )
        except Exception as exc:  # noqa: BLE001
            sidecar_err = f"{type(exc).__name__}: {exc}"
            log.warning("sidecar write failed for %s: %s", side_path, exc)
        response = {
            "path": dest_path,
            "sidecar_path": side_path,
            "moved_from": source_path,
        }
        if sidecar_err is not None:
            response["sidecar_error"] = sidecar_err
        return _ok(f"imported {source_path} -> {dest_path}", **response)

    return _with_recovery(flipper, _run)


# ---------------------------------------------------------------------------
# Lookup tables — mirrors the maps in agent/tools.py.
# ---------------------------------------------------------------------------

# Tool name (bare, as seen by Claude) → action name used by ACTION_RULES
# in echoforge.safety.risk. For Payload Forge, tool name and action name
# are identical (we picked them to match), so this is an identity map.
# Keeping it explicit documents the coupling and gives us a single
# place to rename if we ever want shorter risk-rule keys.
TOOL_TO_RISK_ACTION_PAYLOAD: dict[str, str] = {
    "payload_badusb_validate": "payload_badusb_validate",
    "payload_badusb_create": "payload_badusb_create",
    "payload_badusb_run": "payload_badusb_run",
    "payload_subghz_list": "payload_subghz_list",
    "payload_subghz_inspect": "payload_subghz_inspect",
    "payload_subghz_retune": "payload_subghz_retune",
    "payload_subghz_import_capture": "payload_subghz_import_capture",
    "payload_subghz_tx": "payload_subghz_tx",
    "payload_ir_list": "payload_ir_list",
    "payload_ir_inspect": "payload_ir_inspect",
    "payload_ir_import_capture": "payload_ir_import_capture",
    "payload_ir_transmit": "payload_ir_transmit",
    "payload_library_search": "payload_library_search",
}

# Primary path argument per tool (for SafetyPolicy path-escalation
# and `hooks.py` current-content fetch on MED-write diffs).
TOOL_PRIMARY_PATH_FIELD_PAYLOAD: dict[str, str] = {
    "payload_badusb_create": "path",  # synthesised in tool body
    "payload_badusb_run": "script_path",
    "payload_subghz_list": "subdir",
    "payload_subghz_inspect": "path",
    "payload_subghz_retune": "source_path",
    "payload_subghz_import_capture": "source_path",
    "payload_subghz_tx": "signal_file",
    "payload_ir_list": "subdir",
    "payload_ir_inspect": "path",
    "payload_ir_import_capture": "source_path",
    "payload_ir_transmit": "signal_file",
}
