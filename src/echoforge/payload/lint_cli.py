"""
`echoforge-ducky-lint` — standalone CLI for the DuckyScript linter.

Usage:
    echoforge-ducky-lint [--format=text|json|github]
                         [--rules=W001,W002]
                         [--ignore=W007]
                         <file-or-dir> [<file-or-dir> ...]

Exit codes:
    0 : clean (no findings OR info-only)
    1 : at least one warning, no errors
    2 : at least one error

This is deliberately a separate entry point from the main `echoforge`
CLI so Flipper-community users can `pip install echoforge` and run
`echoforge-ducky-lint my-payload.txt` without touching the hardware
stack.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.text import Text

from echoforge.payload.linter import (
    ALL_RULE_CODES,
    LintFinding,
    LintReport,
    LintSeverity,
    iter_rules,
    lint,
)

# Match an F-key reference like F1, F12, F24. Used by the .txt heuristic
# so a file starting with "From:" or "Foo bar" doesn't get linted as if
# it were DuckyScript.
_F_KEY_RE = re.compile(r"^F([1-9]|1[0-9]|2[0-4])$")

# DuckyScript-ish commands we expect to see on the first meaningful
# line of a Flipper payload. Used to filter .txt files we walk under a
# directory argument — so the linter doesn't blow up on arbitrary
# README.txt or licence files.
_FIRST_LINE_HEURISTIC = (
    "REM",
    "DELAY",
    "DEFAULTDELAY",
    "DEFAULT_DELAY",
    "STRING",
    "STRINGLN",
    "GUI",
    "WINDOWS",
    "CTRL",
    "CONTROL",
    "ALT",
    "SHIFT",
    "ENTER",
    "TAB",
    "SPACE",
    "BACKSPACE",
    "DELETE",
    "ESCAPE",
    "ESC",
    "UP",
    "DOWN",
    "LEFT",
    "RIGHT",
    "HOME",
    "END",
    "PAGEUP",
    "PAGEDOWN",
    "CAPSLOCK",
    "PRINTSCREEN",
    "REPEAT",
    "HOLD",
    "RELEASE",
    "ALT-STRING",
    "ALTSTRING",
    "WAIT_FOR_BUTTON_PRESS",
)


def _looks_like_duckyscript(path: Path) -> bool:
    """Best-effort sniff: is this .txt actually a DuckyScript payload?

    Avoids linting arbitrary files that happen to share the extension.
    We read only the first non-blank line to keep this cheap.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if not stripped:
                    continue
                first = stripped.split(maxsplit=1)[0].upper()
                return first in _FIRST_LINE_HEURISTIC or bool(_F_KEY_RE.match(first))
        return False
    except OSError:
        return False


def _iter_paths(inputs: list[str]) -> list[Path]:
    """Expand CLI inputs into a flat list of .txt files.

    Files are always included even if they don't match the heuristic
    (explicit > implicit). Directories are walked, but only .txt files
    that pass `_looks_like_duckyscript` are included.
    """
    resolved: list[Path] = []
    seen: set[Path] = set()
    for raw in inputs:
        p = Path(raw)
        if p.is_file():
            if p not in seen:
                resolved.append(p)
                seen.add(p)
        elif p.is_dir():
            for candidate in sorted(p.rglob("*.txt")):
                if candidate in seen:
                    continue
                if _looks_like_duckyscript(candidate):
                    resolved.append(candidate)
                    seen.add(candidate)
        # Non-existent paths are surfaced later via an error.
    return resolved


def _format_text(
    console: Console, file_path: Path, report: LintReport
) -> None:
    """Human-readable colored output via `rich`."""
    if not report.findings:
        console.print(f"[green]OK[/green] {file_path}")
        return
    console.print(f"[bold]{file_path}[/bold]")
    for f in report.findings:
        color = {
            LintSeverity.ERROR: "red",
            LintSeverity.WARNING: "yellow",
            LintSeverity.INFO: "cyan",
        }[f.severity]
        col_bit = f":{f.column}" if f.column is not None else ""
        line = Text()
        line.append(f"  {f.severity.value:7} ", style=color)
        line.append(f"{f.code} ", style="bold")
        line.append(f"{file_path.name}:{f.line}{col_bit}", style="dim")
        line.append(f"  {f.message}")
        console.print(line)
        if f.suggestion:
            console.print(f"           [dim]hint: {f.suggestion}[/dim]")


def _format_json(
    console: Console, file_path: Path, report: LintReport
) -> None:
    """Newline-delimited JSON: one object per file, for streaming."""
    payload = {
        "file": str(file_path),
        "findings": [_finding_to_dict(f) for f in report.findings],
    }
    # Write JSON straight to stdout (bypassing rich) so the stream
    # stays machine-parseable — rich would otherwise soft-wrap long
    # lines based on the terminal width, which breaks `jq` and the
    # GitHub Actions streaming consumer.
    sys.stdout.write(json.dumps(payload))
    sys.stdout.write("\n")
    sys.stdout.flush()
    # Unused when json format — preserves signature for uniformity.
    _ = console


def _finding_to_dict(f: LintFinding) -> dict[str, object]:
    """Serialize a LintFinding to the JSON wire format."""
    return {
        "code": f.code,
        "severity": f.severity.value,
        "line": f.line,
        "column": f.column,
        "message": f.message,
        "suggestion": f.suggestion,
    }


def _format_github(
    console: Console, file_path: Path, report: LintReport
) -> None:
    """GitHub Actions annotation format.

    https://docs.github.com/en/actions/using-workflows/workflow-commands-for-github-actions#setting-a-warning-message
    """
    gh_severity = {
        LintSeverity.ERROR: "error",
        LintSeverity.WARNING: "warning",
        LintSeverity.INFO: "notice",
    }
    for f in report.findings:
        # Escape special characters per the GitHub spec.
        msg = f.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        parts = [f"file={file_path}", f"line={f.line}"]
        if f.column is not None:
            parts.append(f"col={f.column}")
        parts.append(f"title={f.code}")
        # Write direct to stdout — GitHub Actions expects the exact
        # `::severity file=...::message` line unwrapped.
        sys.stdout.write(
            f"::{gh_severity[f.severity]} {','.join(parts)}::{msg}\n"
        )
    sys.stdout.flush()
    _ = console


def _parse_rule_list(value: str | None) -> set[str] | None:
    """Turn `--rules=W001,W002` into `{"W001","W002"}` (or None)."""
    if value is None:
        return None
    return {part.strip() for part in value.split(",") if part.strip()}


def _validate_rule_codes(
    codes: set[str] | None,
) -> tuple[set[str] | None, list[str]]:
    """Return the set unchanged plus a list of unknown codes (for a warning)."""
    if codes is None:
        return None, []
    unknown = [c for c in codes if c not in ALL_RULE_CODES]
    return codes, unknown


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser."""
    p = argparse.ArgumentParser(
        prog="echoforge-ducky-lint",
        description=(
            "Lint DuckyScript (BadUSB) payloads for Flipper Zero. "
            "Detects style issues, portability bugs, and Flipper-specific "
            "dialect mismatches that the core parser won't catch."
        ),
    )
    p.add_argument(
        "paths",
        nargs="+",
        help="One or more files or directories. Directories are walked recursively.",
    )
    p.add_argument(
        "--format",
        choices=("text", "json", "github"),
        default="text",
        help="Output format (default: text).",
    )
    p.add_argument(
        "--rules",
        metavar="CODES",
        help=(
            "Comma-separated allowlist (e.g. W001,W002). Only these run. "
            "When combined with --ignore, ignore wins (codes in both are skipped)."
        ),
    )
    p.add_argument(
        "--ignore",
        metavar="CODES",
        help=(
            "Comma-separated denylist (e.g. W007). These rules are skipped. "
            "Takes precedence over --rules when a code appears in both."
        ),
    )
    p.add_argument(
        "--list-rules",
        action="store_true",
        help="Print every registered rule code with its severity and exit 0.",
    )
    return p


def _print_rule_list(console: Console) -> None:
    """Dump the registered rule codes (for `--list-rules`)."""
    for code, severity, description in iter_rules():
        console.print(f"  {code}  {severity.value:7}  {description}")


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `echoforge-ducky-lint` console script.

    Returns the process exit code (0 clean, 1 warnings, 2 errors).
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    console = Console()

    if args.list_rules:
        _print_rule_list(console)
        return 0

    rules = _parse_rule_list(args.rules)
    ignore = _parse_rule_list(args.ignore)
    rules, unknown_rules = _validate_rule_codes(rules)
    ignore, unknown_ignore = _validate_rule_codes(ignore)
    for code in unknown_rules:
        console.print(f"[yellow]warn:[/yellow] --rules references unknown code {code!r}")
    for code in unknown_ignore:
        console.print(f"[yellow]warn:[/yellow] --ignore references unknown code {code!r}")

    # Early-out: missing files (surface cleanly, don't crash).
    missing: list[str] = [p for p in args.paths if not Path(p).exists()]
    for m in missing:
        console.print(f"[red]error:[/red] no such file or directory: {m}")
    if missing:
        return 2

    files = _iter_paths(args.paths)
    if not files:
        console.print("[yellow]warn:[/yellow] no DuckyScript files found")
        return 0

    any_error = False
    any_warning = False

    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            console.print(f"[red]error:[/red] reading {path}: {exc}")
            any_error = True
            continue
        report = lint(source, rules=rules, ignore=ignore)
        if args.format == "text":
            _format_text(console, path, report)
        elif args.format == "json":
            _format_json(console, path, report)
        elif args.format == "github":
            _format_github(console, path, report)
        if report.has_errors:
            any_error = True
        elif report.has_warnings:
            any_warning = True

    if any_error:
        return 2
    if any_warning:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
