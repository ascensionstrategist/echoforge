"""
DuckyScript parser / syntactic validator.

Why this exists: Phase 6 Payload Forge needs to know whether a BadUSB
script the agent (or the operator) authored is syntactically well-formed
before writing it to `/ext/badusb/`. Per PHASE6_DECISIONS.md §2, this
module performs **syntactic validation only** — no content-meaning
analysis, no charset restriction, no blocked-token list. Those have been
explicitly dropped in favour of the audit trail.

The parser recognises the canonical Hak5 command set plus widely-adopted
Flipper/Momentum extensions (arrow keys, F-keys, key combos like
`CTRL-ALT-DEL`, `GUI r`, `DEFAULTDELAY`). Unknown commands surface as a
`warning`-severity diagnostic rather than a hard error — firmware dialects
carry private extensions, and we don't want the linter to refuse a script
that would run fine on the target device.

Public API:
  - `DuckyCommand`    : parsed one command.
  - `Diagnostic`      : single validation issue with line, severity, code.
  - `ParseResult`     : the whole script's result (`commands`, `diagnostics`).
  - `parse_script()`  : parse + validate a raw script string.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal

__all__ = [
    "DuckyCommand",
    "Diagnostic",
    "ParseResult",
    "parse_script",
    "RECOGNISED_COMMANDS",
    "RECOGNISED_KEYS",
]


# ---------------------------------------------------------------------------
# Command / key tables
# ---------------------------------------------------------------------------

# Top-level commands: the first token on a non-REM line.
# Anything not in this set falls through to "treat as a key-name/modifier
# combo" which we then try to parse against RECOGNISED_KEYS.
RECOGNISED_COMMANDS: frozenset[str] = frozenset(
    {
        "REM",
        "DELAY",
        "DEFAULTDELAY",
        "DEFAULT_DELAY",  # snake variant some forks use
        "STRING",
        "STRINGLN",
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
        "GUI",
        "WINDOWS",
        "CTRL",
        "CONTROL",
        "ALT",
        "SHIFT",
        "MENU",
        "APP",
        "INSERT",
        "PAUSE",
        "BREAK",
        "NUMLOCK",
        "SCROLLLOCK",
        "REPEAT",
        "MEDIA_PLAY_PAUSE",
        "MEDIA_STOP",
        "MEDIA_NEXT",
        "MEDIA_PREVIOUS",
        "MEDIA_VOLUME_UP",
        "MEDIA_VOLUME_DOWN",
        "MEDIA_MUTE",
    }
)

# Recognised individual keys (for the RHS of a combo or when combined with
# modifiers). Letters/digits and F-keys are validated separately.
RECOGNISED_KEYS: frozenset[str] = frozenset(
    {
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
        "INSERT",
        "PAUSE",
        "MENU",
        "APP",
    }
)

# Aliases that all mean the same modifier.
_MODIFIER_ALIASES: frozenset[str] = frozenset(
    {"GUI", "WINDOWS", "CTRL", "CONTROL", "ALT", "SHIFT"}
)

Severity = Literal["info", "warning", "error"]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuckyCommand:
    """One parsed DuckyScript line.

    `line_no` is 1-based so diagnostics are human-friendly. `command` is
    the uppercase keyword (REM / DELAY / STRING / GUI / …). `args` is the
    raw remainder of the line with leading whitespace stripped — for
    `STRING`/`STRINGLN` this preserves the payload verbatim. For key
    combos (e.g. `CTRL-ALT-DEL`) the whole combo is kept in `command`
    and `args` is empty.
    """

    line_no: int
    raw: str
    command: str
    args: str = ""


@dataclass(frozen=True)
class Diagnostic:
    """One validation issue found during parsing.

    `code` is a short machine-readable tag (e.g. `D_UNKNOWN_COMMAND`).
    `severity` drives whether the caller treats this as a soft warning or
    a hard parse failure.
    """

    line_no: int
    severity: Severity
    code: str
    message: str


@dataclass
class ParseResult:
    """Full result of parsing a DuckyScript source.

    `ok` is True when no diagnostics at `error` severity were produced.
    Callers that want a strict lint (warnings-as-errors) can check
    `diagnostics` directly.
    """

    commands: list[DuckyCommand] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when no `error`-severity diagnostics were found."""
        return not any(d.severity == "error" for d in self.diagnostics)

    @property
    def line_count(self) -> int:
        """Total commands parsed (excluding blank / comment lines)."""
        return len(self.commands)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _is_identifier_token(tok: str) -> bool:
    """Return True if `tok` looks like a DuckyScript keyword or key-name.

    DuckyScript has no formal grammar, but all keywords and key-names use
    ASCII letters/digits and the `_` / `-` separators. Anything else means
    'almost certainly not a command.'
    """
    if not tok:
        return False
    return all(c.isalnum() or c in "_-" for c in tok)


def _is_single_key_token(tok: str) -> bool:
    """Return True if `tok` looks like a single key reference usable on the
    RHS of a modifier combo (e.g. the `r` in `GUI r`, or `F4` in `ALT F4`).
    """
    if not tok:
        return False
    if len(tok) == 1 and (tok.isalnum() or tok in "`-=[]\\;',./"):
        return True
    upper = tok.upper()
    if upper in RECOGNISED_KEYS:
        return True
    if upper in _MODIFIER_ALIASES:
        return True
    # F1..F24
    if upper.startswith("F") and upper[1:].isdigit():
        n = int(upper[1:])
        return 1 <= n <= 24
    return False


def _parse_delay(line_no: int, cmd: str, args: str) -> Diagnostic | None:
    """Return a Diagnostic if a DELAY / DEFAULTDELAY argument is malformed.

    Syntactic-only: the value must be a non-negative integer. The 600_000
    ms sanity cap from the API doc is **not** enforced here — that's a
    higher-level policy concern (PHASE6_DECISIONS.md §2 drops the cap as
    policy; we only reject obvious parse errors).
    """
    if not args:
        return Diagnostic(
            line_no=line_no,
            severity="error",
            code="D_MISSING_ARG",
            message=f"{cmd} requires a numeric argument (milliseconds)",
        )
    try:
        value = int(args.strip())
    except ValueError:
        return Diagnostic(
            line_no=line_no,
            severity="error",
            code="D_BAD_DELAY_ARG",
            message=f"{cmd} argument must be an integer, got {args!r}",
        )
    if value < 0:
        return Diagnostic(
            line_no=line_no,
            severity="error",
            code="D_NEGATIVE_DELAY",
            message=f"{cmd} argument must be >= 0, got {value}",
        )
    return None


def _parse_combo(line_no: int, tokens: list[str]) -> Diagnostic | None:
    """Validate a modifier-plus-key combo like `GUI r`, `CTRL ALT DEL`,
    `ALT F4`.

    Accepts both space-separated (`CTRL ALT DEL`) and hyphen-joined
    (`CTRL-ALT-DEL`) forms; the latter arrives here as a single token.
    Returns None on success, a Diagnostic on failure.
    """
    if not tokens:
        return Diagnostic(
            line_no=line_no,
            severity="error",
            code="D_EMPTY_COMBO",
            message="empty key combo",
        )
    # Split hyphen-joined forms like CTRL-ALT-DEL into individual pieces.
    flat: list[str] = []
    for t in tokens:
        flat.extend(x for x in t.split("-") if x)
    if not flat:
        return Diagnostic(
            line_no=line_no,
            severity="error",
            code="D_EMPTY_COMBO",
            message="empty key combo after splitting",
        )
    # All tokens except possibly the last must be modifier aliases.
    for t in flat[:-1]:
        if t.upper() not in _MODIFIER_ALIASES:
            return Diagnostic(
                line_no=line_no,
                severity="warning",
                code="D_UNKNOWN_MODIFIER",
                message=f"{t!r} is not a recognised modifier in combo {flat!r}",
            )
    # The last token may be another modifier (pure chord) or a key.
    last = flat[-1]
    if last.upper() in _MODIFIER_ALIASES:
        return None
    if _is_single_key_token(last):
        return None
    return Diagnostic(
        line_no=line_no,
        severity="warning",
        code="D_UNKNOWN_KEY",
        message=f"{last!r} is not a recognised key at end of combo {flat!r}",
    )


def parse_script(script: str) -> ParseResult:
    """Parse and syntactically validate a DuckyScript source.

    Parsing is line-oriented. Blank lines and `REM` comment lines are kept
    as `DuckyCommand` entries (so audit trails can reconstruct the exact
    original text) but contribute no diagnostics.

    `\\r\\n` and lone `\\r` line endings are both accepted — the parser
    normalises to Unix line endings before splitting.

    The returned `ParseResult.diagnostics` list is ordered by line
    number. Multiple diagnostics per line are possible (rare) and each
    carries its own severity.
    """
    result = ParseResult()
    # Normalise line endings.
    normalised = script.replace("\r\n", "\n").replace("\r", "\n")
    for idx, raw_line in enumerate(normalised.split("\n"), start=1):
        # Preserve the raw line (for audit reconstruction), but strip for
        # command matching.
        stripped = raw_line.strip()
        if not stripped:
            continue
        # Split the first token off; the remainder is the 'args' half.
        first, sep, rest = stripped.partition(" ")
        first_upper = first.upper()

        # REM = comment; everything after is a free-text comment body.
        if first_upper == "REM":
            result.commands.append(
                DuckyCommand(
                    line_no=idx, raw=raw_line, command="REM", args=rest
                )
            )
            continue

        # STRING / STRINGLN: the remainder is the literal payload. No
        # charset restriction per DECISIONS.md §2.
        if first_upper in {"STRING", "STRINGLN"}:
            if not rest and sep == "":
                # STRING with no argument is syntactically weird but
                # technically an empty string — warn, don't error.
                result.diagnostics.append(
                    Diagnostic(
                        line_no=idx,
                        severity="warning",
                        code="D_EMPTY_STRING",
                        message=f"{first_upper} with no payload",
                    )
                )
            result.commands.append(
                DuckyCommand(
                    line_no=idx, raw=raw_line, command=first_upper, args=rest
                )
            )
            continue

        # DELAY / DEFAULTDELAY / DEFAULT_DELAY: numeric argument.
        if first_upper in {"DELAY", "DEFAULTDELAY", "DEFAULT_DELAY"}:
            diag = _parse_delay(idx, first_upper, rest)
            if diag is not None:
                result.diagnostics.append(diag)
            result.commands.append(
                DuckyCommand(
                    line_no=idx, raw=raw_line, command=first_upper, args=rest
                )
            )
            continue

        # Single-token recognised commands with no argument (ENTER, TAB,
        # SPACE, arrow keys, F-keys…). If there IS an argument, it's a
        # combo like `GUI r` — parse it as such.
        is_fkey = (
            first_upper.startswith("F")
            and first_upper[1:].isdigit()
            and 1 <= int(first_upper[1:]) <= 24
        )
        # Hyphen-joined combo as a single token (e.g. CTRL-ALT-DEL).
        is_hyphen_combo = (
            "-" in first and _is_identifier_token(first) and first_upper not in {"DEFAULT_DELAY"}
        )

        if is_hyphen_combo:
            diag = _parse_combo(idx, [first])
            if diag is not None:
                result.diagnostics.append(diag)
            result.commands.append(
                DuckyCommand(
                    line_no=idx, raw=raw_line, command=first_upper, args=rest
                )
            )
            continue

        if first_upper in RECOGNISED_COMMANDS or is_fkey:
            if rest:
                # Command + args: treat as a combo starting with this
                # command (e.g. GUI r, ALT F4, CTRL SHIFT T).
                tokens = [first_upper, *rest.split()]
                diag = _parse_combo(idx, tokens)
                if diag is not None:
                    result.diagnostics.append(diag)
            result.commands.append(
                DuckyCommand(
                    line_no=idx, raw=raw_line, command=first_upper, args=rest
                )
            )
            continue

        # Unknown top-level token. Firmware forks ship private extensions;
        # downgrade to a warning rather than a hard error so legitimate
        # payloads aren't rejected.
        result.diagnostics.append(
            Diagnostic(
                line_no=idx,
                severity="warning",
                code="D_UNKNOWN_COMMAND",
                message=f"unknown command {first!r}",
            )
        )
        result.commands.append(
            DuckyCommand(line_no=idx, raw=raw_line, command=first_upper, args=rest)
        )

    return result


def iter_strings(result: ParseResult) -> Iterable[tuple[int, str]]:
    """Yield `(line_no, payload)` tuples for every STRING/STRINGLN command.

    Convenience helper for higher-level inspectors that want to surface
    the typed content without re-walking the commands list.
    """
    for cmd in result.commands:
        if cmd.command in {"STRING", "STRINGLN"}:
            yield cmd.line_no, cmd.args
