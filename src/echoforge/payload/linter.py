"""
DuckyScript style / idiom / compatibility linter for Flipper Zero dialect.

Why this exists: `duckyscript.py` parses and syntactically validates
DuckyScript. It catches the catastrophic stuff — malformed DELAY args,
unknown commands, unclosed combos — but not the long tail of
style/portability problems that bite real operators:

- A `STRING` with no preceding `DELAY` (host misses keystrokes).
- A DuckyScript 3.0 `WHILE`/`FOR` block sent to a Flipper (firmware
  silently skips the block).
- A Hak5-only `VID_`/`WAIT_FOR_HOST` (also silently skipped).
- Missing `REM` header identifying target OS and layout.
- Trailing whitespace, CRLF line endings, mixed-case keywords.

Per `docs/PHASE6_PAYLOAD_RESEARCH.md`, no DuckyScript linter exists for
the Flipper dialect today — this module is echoforge's contribution.
It operates on the existing `ParseResult` (so we never reimplement the
tokenizer) and layers rule functions on top.

Rule inventory (codes documented in README and `CLAUDE.md`):

E-rules (errors)   — malformed or non-functional on Flipper
W-rules (warnings) — style / idiom / compat issues
I-rules (info)     — cosmetic / organizational hints

Each rule is a small function registered via `@_rule(code, severity)`.
The engine walks the ParseResult once and dispatches to each rule.

Public API:
  - `LintSeverity`   : enum (ERROR / WARNING / INFO)
  - `LintFinding`    : one finding (code, severity, line, column, message)
  - `LintReport`     : list of findings + convenience predicates
  - `lint(source)`   : parse + lint a DuckyScript source string
  - `ALL_RULE_CODES` : frozenset of every rule code the engine knows
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from enum import Enum

from echoforge.payload.duckyscript import (
    DuckyCommand,
    ParseResult,
    parse_script,
)

__all__ = [
    "ALL_RULE_CODES",
    "LintFinding",
    "LintReport",
    "LintSeverity",
    "Rule",
    "iter_rules",
    "lint",
    "lint_parsed",
]


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


class LintSeverity(str, Enum):
    """Severity bucket for a LintFinding.

    String-backed so JSON serialisation is trivial and stable.
    """

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class LintFinding:
    """One lint finding.

    `line` is 1-indexed (matches the parser). `column` is 1-indexed when
    present, None for whole-file findings (e.g. missing REM header).
    `suggestion` is an optional one-line actionable fix the CLI can
    print beneath the finding.
    """

    code: str
    severity: LintSeverity
    line: int
    column: int | None
    message: str
    suggestion: str | None = None


@dataclass(frozen=True)
class LintReport:
    """Full result of linting a DuckyScript source."""

    findings: tuple[LintFinding, ...] = field(default_factory=tuple)

    @property
    def has_errors(self) -> bool:
        """Return True if any ERROR-severity finding is present."""
        return any(f.severity == LintSeverity.ERROR for f in self.findings)

    @property
    def has_warnings(self) -> bool:
        """Return True if any WARNING-severity finding is present."""
        return any(f.severity == LintSeverity.WARNING for f in self.findings)

    @property
    def has_infos(self) -> bool:
        """Return True if any INFO-severity finding is present."""
        return any(f.severity == LintSeverity.INFO for f in self.findings)


# ---------------------------------------------------------------------------
# Rule registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """A registered lint rule.

    `fn(ctx)` returns an iterable of LintFinding. The engine does no
    per-rule filtering beyond the `rules` / `ignore` sets passed to
    `lint()` — rules are expected to be cheap and self-contained.
    """

    code: str
    severity: LintSeverity
    description: str
    fn: Callable[["_LintContext"], Iterable[LintFinding]]


_RULES: list[Rule] = []


def _rule(
    code: str, severity: LintSeverity, description: str
) -> Callable[
    [Callable[["_LintContext"], Iterable[LintFinding]]],
    Callable[["_LintContext"], Iterable[LintFinding]],
]:
    """Decorator that registers a rule function with the engine."""

    def deco(
        fn: Callable[["_LintContext"], Iterable[LintFinding]],
    ) -> Callable[["_LintContext"], Iterable[LintFinding]]:
        _RULES.append(Rule(code=code, severity=severity, description=description, fn=fn))
        return fn

    return deco


# ---------------------------------------------------------------------------
# Lint context — everything a rule might need in one shared object
# ---------------------------------------------------------------------------


@dataclass
class _LintContext:
    """Shared state for a single lint pass.

    Holds the raw source (for whitespace / line-ending / column
    inspection), the parsed result (for command iteration), and the
    pre-split lines (index i = line i+1).
    """

    source: str
    parsed: ParseResult
    raw_lines: list[str]  # source split on '\n' AFTER \r normalisation

    def lines_indexed(self) -> list[tuple[int, str]]:
        """Yield (1-based line_no, line_text) pairs."""
        return [(i + 1, line) for i, line in enumerate(self.raw_lines)]


# ---------------------------------------------------------------------------
# Helpers shared across rules
# ---------------------------------------------------------------------------


# DuckyScript 3.0 control-flow keywords that Flipper's BadUSB runner
# does NOT support on stock firmware ≥0.85.
#
# source: skills/echoforge-flipper-mastery/skills/echoforge-duckyscript/
#         references/flipper-extensions.md compatibility matrix
#
# WHILE / END_WHILE / FUNCTION / END_FUNCTION are supported per the matrix
# (Y across Stock/Momentum/Xtreme/Unleashed) — they are NOT in this set.
# Only FOR / END_FOR / CALL remain genuinely unsupported on stock; the
# matrix lists no FOR-loop construct in DuckyScript 3.0 and CALL has no
# documented stock implementation.
_UNSUPPORTED_CF_3_0: frozenset[str] = frozenset(
    {
        "FOR",
        "END_FOR",
        "CALL",
    }
)

# Momentum / Xtreme firmware extensions. These are unknown to the parser's
# RECOGNISED_COMMANDS but legitimate on Momentum/Xtreme firmwares — we must
# not flag them as E001. W010 (ALT-STRING hint) and W011 (HOLD-without-DELAY)
# rules apply to the relevant subset.
#
# source: skills/echoforge-flipper-mastery/skills/echoforge-duckyscript/
#         references/flipper-extensions.md compatibility matrix
_MOMENTUM_EXTENSIONS: frozenset[str] = frozenset(
    {
        "HOLD",
        "RELEASE",
        "ALT-STRING",
        "ALTSTRING",
        "ALT-CHARS",
        "ALTCHARS",
        "WAIT_FOR_BUTTON_PRESS",
        "DEFAULTCHARDELAY",
        "DEFAULT_CHAR_DELAY",
        "SYSRQ",
        # Momentum-only media keys (the parser already knows the MEDIA_*
        # variants; these are the shorter aliases some Momentum payloads use).
        "MEDIA_PLAY_PAUSE",
        "MEDIA_PLAY",
        "MEDIA_PAUSE",
        "MEDIA_NEXT",
        "MEDIA_PREV",
        "MEDIA_PREVIOUS",
        "MEDIA_STOP",
        "VOLUME_UP",
        "VOLUME_DOWN",
        "VOLUMEUP",
        "VOLUMEDOWN",
        "MUTE",
        "PLAY",
    }
)

# Commands / tokens that the matrix lists as supported on stock firmware
# ≥0.85 but the parser's RECOGNISED_COMMANDS table doesn't enumerate.
# Surfacing them as E001 would directly contradict the skill reference.
#
# source: skills/echoforge-flipper-mastery/skills/echoforge-duckyscript/
#         references/flipper-extensions.md compatibility matrix
_SUPPORTED_PER_MATRIX: frozenset[str] = frozenset(
    {
        "VAR",
        "IF",
        "ELSE",
        "ELSE_IF",  # tokenizer would collapse "ELSE IF" — keep both forms.
        "END_IF",
        "THEN",
        "WHILE",
        "END_WHILE",
        "FUNCTION",
        "END_FUNCTION",
        # $_RANDOM_* substitution tokens that may appear standalone on a
        # line in some payload styles.
        "$_RANDOM_LOWERCASE_LETTER",
        "$_RANDOM_UPPERCASE_LETTER",
        "$_RANDOM_LETTER",
        "$_RANDOM_NUMBER",
        "$_RANDOM_SPECIAL",
        "$_RANDOM_CHAR",
    }
)

# Commands that only exist on Hak5 Ducky Mark II hardware. Flipper's
# runner treats them as unknown and moves on — the payload author
# usually doesn't notice until the payload fails to do anything.
_HAK5_ONLY: frozenset[str] = frozenset(
    {
        "VID_",
        "PID_",
        "MAN_",
        "PROD_",
        "SERIAL_",
        "WAIT_FOR_HOST",
        "WAIT_FOR_CAPS_ON",
        "WAIT_FOR_CAPS_OFF",
        "WAIT_FOR_NUM_ON",
        "WAIT_FOR_NUM_OFF",
        "WAIT_FOR_SCROLL_ON",
        "WAIT_FOR_SCROLL_OFF",
        "SAVE_HOST_KEYBOARD_LOCK_STATE",
        "RESTORE_HOST_KEYBOARD_LOCK_STATE",
        "INJECT_MOD",
    }
)

# Keywords whose canonical spelling is uppercase. We lint mixed-case
# spellings even though the parser accepts them — W007.
_CANONICAL_UPPER: frozenset[str] = frozenset(
    {
        "REM",
        "DELAY",
        "DEFAULTDELAY",
        "DEFAULT_DELAY",
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
        "HOLD",
        "RELEASE",
        "ALT-STRING",
        "ALTSTRING",
        "WAIT_FOR_BUTTON_PRESS",
    }
)

# Platform hints: `GUI r` only makes sense on Windows; `GUI SPACE` on
# macOS Spotlight. Used by W006 to suggest a REM hint.
_WINDOWS_ONLY_COMBOS: frozenset[str] = frozenset({"GUI-R", "GUI R"})
_MAC_ONLY_COMBOS: frozenset[str] = frozenset({"GUI-SPACE", "GUI SPACE"})


def _first_string_after_rem_block(commands: list[DuckyCommand]) -> DuckyCommand | None:
    """Return the first non-REM command in the script, or None."""
    for c in commands:
        if c.command != "REM":
            return c
    return None


def _header_rems(commands: list[DuckyCommand]) -> list[DuckyCommand]:
    """Return the leading run of REM commands (script header)."""
    hdr: list[DuckyCommand] = []
    for c in commands:
        if c.command == "REM":
            hdr.append(c)
        else:
            break
    return hdr


# ---------------------------------------------------------------------------
# E-rules
# ---------------------------------------------------------------------------


@_rule("E001", LintSeverity.ERROR, "Unknown command (surfaced by parser)")
def _e001_unknown_command(ctx: _LintContext) -> Iterable[LintFinding]:
    """Promote the parser's D_UNKNOWN_COMMAND warning to E001 when the
    unknown token is neither:
      - a Hak5-only command (handled by W005),
      - a DS3.0 control-flow token Flipper truly doesn't run (handled by E007),
      - a Momentum/Xtreme extension (handled by W010 / W011 / E004 / etc.),
      - a token the matrix lists as supported on stock ≥0.85
        (VAR / IF / ELSE / END_IF / WHILE / FUNCTION / $_RANDOM_*).
    """
    hak5_handled: set[int] = set()
    cf_handled: set[int] = set()
    momentum_handled: set[int] = set()
    matrix_handled: set[int] = set()
    for c in ctx.parsed.commands:
        if c.command in _HAK5_ONLY or c.command.split("_", 1)[0] + "_" in _HAK5_ONLY:
            hak5_handled.add(c.line_no)
        if c.command in _UNSUPPORTED_CF_3_0:
            cf_handled.add(c.line_no)
        if c.command in _MOMENTUM_EXTENSIONS:
            momentum_handled.add(c.line_no)
        # Tokens the matrix lists as supported on stock ≥0.85.
        # The parser uppercases the first token before raw-emitting an
        # unknown-command diagnostic, so compare against the upper form.
        # `$_RANDOM_*` survives uppercasing intact.
        if c.command in _SUPPORTED_PER_MATRIX:
            matrix_handled.add(c.line_no)
    for d in ctx.parsed.diagnostics:
        if d.code != "D_UNKNOWN_COMMAND":
            continue
        if (
            d.line_no in hak5_handled
            or d.line_no in cf_handled
            or d.line_no in momentum_handled
            or d.line_no in matrix_handled
        ):
            continue
        yield LintFinding(
            code="E001",
            severity=LintSeverity.ERROR,
            line=d.line_no,
            column=1,
            message=d.message,
            suggestion="Check spelling, or REM the line if this is a Flipper extension",
        )


@_rule("E002", LintSeverity.ERROR, "Malformed numeric argument to DELAY/DEFAULTDELAY")
def _e002_malformed_numeric(ctx: _LintContext) -> Iterable[LintFinding]:
    """Surface parser-side D_BAD_DELAY_ARG / D_NEGATIVE_DELAY / D_MISSING_ARG."""
    for d in ctx.parsed.diagnostics:
        if d.code in {"D_BAD_DELAY_ARG", "D_NEGATIVE_DELAY", "D_MISSING_ARG"}:
            yield LintFinding(
                code="E002",
                severity=LintSeverity.ERROR,
                line=d.line_no,
                column=1,
                message=d.message,
                suggestion="DELAY takes a non-negative integer in milliseconds",
            )


@_rule("E003", LintSeverity.ERROR, "STRING / STRINGLN with no payload")
def _e003_empty_string(ctx: _LintContext) -> Iterable[LintFinding]:
    """STRING by itself on a line almost always means the operator
    forgot the payload. The parser emits D_EMPTY_STRING as a warning;
    promote to error because an empty STRING typed at a host is never
    intentional.
    """
    for d in ctx.parsed.diagnostics:
        if d.code == "D_EMPTY_STRING":
            yield LintFinding(
                code="E003",
                severity=LintSeverity.ERROR,
                line=d.line_no,
                column=1,
                message="STRING/STRINGLN with no payload — did you drop the text?",
                suggestion="Type the text after the command on the same line",
            )


@_rule("E004", LintSeverity.ERROR, "HOLD without a matching RELEASE")
def _e004_unclosed_hold(ctx: _LintContext) -> Iterable[LintFinding]:
    """Momentum/Xtreme `HOLD <KEY>` requires a matching `RELEASE <KEY>`
    later in the script. Otherwise the modifier stays pressed when the
    payload ends — confuses the host OS for seconds afterwards.
    """
    held: dict[str, int] = {}  # key -> line_no of HOLD
    for c in ctx.parsed.commands:
        if c.command == "HOLD":
            key = c.args.strip().upper()
            if key:
                held[key] = c.line_no
        elif c.command == "RELEASE":
            key = c.args.strip().upper()
            held.pop(key, None)
    for key, line in held.items():
        yield LintFinding(
            code="E004",
            severity=LintSeverity.ERROR,
            line=line,
            column=1,
            message=f"HOLD {key} has no matching RELEASE",
            suggestion=f"Add `RELEASE {key}` before the script ends",
        )


@_rule("E005", LintSeverity.ERROR, "Unknown key name in key combo")
def _e005_unknown_key_in_combo(ctx: _LintContext) -> Iterable[LintFinding]:
    """Surface parser-side D_UNKNOWN_KEY / D_UNKNOWN_MODIFIER as errors.

    Suppresses the diagnostic when the offending line is a Momentum
    extension that the parser misclassifies as a hyphen-joined combo
    (e.g. `ALT-STRING`, `ALT-CHARS`). Those cases are handled by W010.
    """
    momentum_lines: set[int] = {
        c.line_no for c in ctx.parsed.commands if c.command in _MOMENTUM_EXTENSIONS
    }
    for d in ctx.parsed.diagnostics:
        if d.code not in {"D_UNKNOWN_KEY", "D_UNKNOWN_MODIFIER"}:
            continue
        if d.line_no in momentum_lines:
            continue
        yield LintFinding(
            code="E005",
            severity=LintSeverity.ERROR,
            line=d.line_no,
            column=1,
            message=d.message,
            suggestion="Check the key name (e.g. DEL not DLEETE)",
        )


@_rule("E006", LintSeverity.ERROR, "DEFAULTDELAY with invalid value")
def _e006_default_delay_bad(ctx: _LintContext) -> Iterable[LintFinding]:
    """Already covered by E002 via the parser, but we also flag any
    DEFAULTDELAY greater than 10_000 ms — the API contract in
    PHASE6_PAYLOAD_FORGE_API.md §3.2 caps DEFAULTDELAY at 10s.
    """
    for c in ctx.parsed.commands:
        if c.command not in {"DEFAULTDELAY", "DEFAULT_DELAY"}:
            continue
        try:
            value = int(c.args.strip())
        except ValueError:
            continue  # E002 already handled this
        if value > 10_000:
            yield LintFinding(
                code="E006",
                severity=LintSeverity.ERROR,
                line=c.line_no,
                column=1,
                message=f"DEFAULTDELAY={value} exceeds 10000ms cap (API.md §3.2)",
                suggestion="Lower DEFAULTDELAY or use per-step DELAY instead",
            )


@_rule("E007", LintSeverity.ERROR, "DuckyScript 3.0 FOR / END_FOR / CALL not supported on Flipper")
def _e007_unsupported_control_flow(ctx: _LintContext) -> Iterable[LintFinding]:
    """FOR / END_FOR / CALL are not supported by Flipper's BadUSB runner
    on stock firmware ≥0.85 per the compatibility matrix. The runner
    silently skips the block — the payload appears to 'run' but does
    nothing.

    WHILE / END_WHILE / FUNCTION / END_FUNCTION are SUPPORTED per the
    matrix and are NOT flagged here.

    source: skills/echoforge-flipper-mastery/skills/echoforge-duckyscript/
            references/flipper-extensions.md compatibility matrix
    """
    for c in ctx.parsed.commands:
        if c.command in _UNSUPPORTED_CF_3_0:
            yield LintFinding(
                code="E007",
                severity=LintSeverity.ERROR,
                line=c.line_no,
                column=1,
                message=(
                    f"{c.command} is not supported by Flipper's BadUSB runner; "
                    f"the firmware silently skips it"
                ),
                suggestion="Unroll the loop or use REPEAT N for simple cases",
            )


# ---------------------------------------------------------------------------
# W-rules
# ---------------------------------------------------------------------------


@_rule("W001", LintSeverity.WARNING, "Missing REM header (author / target OS / description)")
def _w001_missing_header(ctx: _LintContext) -> Iterable[LintFinding]:
    """A payload without a REM header is hard to audit later. Warn if
    the script has no leading REM lines OR the header doesn't mention
    target/os/layout/author anywhere. A single REM that declares
    `Target:` / `Author:` / etc. is enough.
    """
    header = _header_rems(ctx.parsed.commands)
    header_text = " ".join(c.args.lower() for c in header)
    has_signal = any(
        tok in header_text
        for tok in ("target", "os", "windows", "macos", "linux", "author", "layout", "title")
    )
    if len(header) < 1 or not has_signal:
        yield LintFinding(
            code="W001",
            severity=LintSeverity.WARNING,
            line=1,
            column=None,
            message="script has no REM header identifying target OS / author / layout",
            suggestion='Add `REM Title: ...`, `REM Target: Windows`, `REM Author: ...`',
        )


@_rule("W002", LintSeverity.WARNING, "STRING without preceding DELAY")
def _w002_string_without_delay(ctx: _LintContext) -> Iterable[LintFinding]:
    """The first STRING in a script typically needs a DELAY in front of
    it; without one, the host may miss keystrokes while claiming the
    HID device. We flag any STRING/STRINGLN where the *immediately
    preceding* executable command is neither DELAY/DEFAULTDELAY nor
    another STRING (consecutive STRINGs in the same input field are
    fine — flows from a single preceding DELAY).
    """
    commands = [c for c in ctx.parsed.commands if c.command != "REM"]
    has_default_delay = any(
        c.command in {"DEFAULTDELAY", "DEFAULT_DELAY"} for c in commands
    )
    if has_default_delay:
        # A DEFAULTDELAY inserts a delay between every command — suppress.
        return
    for i, c in enumerate(commands):
        if c.command not in {"STRING", "STRINGLN"}:
            continue
        prev = commands[i - 1] if i > 0 else None
        if prev is None:
            yield LintFinding(
                code="W002",
                severity=LintSeverity.WARNING,
                line=c.line_no,
                column=1,
                message="STRING is the first command; host may miss keystrokes",
                suggestion="Prepend `DELAY 1000` at the top to let USB enumeration finish",
            )
            continue
        if prev.command in {"DELAY", "DEFAULTDELAY", "DEFAULT_DELAY"}:
            continue
        if prev.command in {"STRING", "STRINGLN"}:
            continue
        # Anything else (GUI, ENTER, CTRL combos, HOLD, …) is the
        # realistic timing-bug pattern this rule exists to catch.
        yield LintFinding(
            code="W002",
            severity=LintSeverity.WARNING,
            line=c.line_no,
            column=1,
            message=(
                f"STRING after `{prev.command}` without an intervening DELAY — "
                "keystrokes may be dropped on the host."
            ),
            suggestion=(
                f"Insert `DELAY 200` (or longer) between `{prev.command}` and the STRING"
            ),
        )


@_rule("W003", LintSeverity.WARNING, "STRING line exceeds 120 chars (buffer concerns)")
def _w003_long_string(ctx: _LintContext) -> Iterable[LintFinding]:
    """Some firmware forks have a 128-byte line buffer. STRINGs above
    120 chars approach the limit.
    """
    for c in ctx.parsed.commands:
        if c.command not in {"STRING", "STRINGLN"}:
            continue
        if len(c.args) > 120:
            yield LintFinding(
                code="W003",
                severity=LintSeverity.WARNING,
                line=c.line_no,
                column=1,
                message=f"STRING payload is {len(c.args)} chars (>120); some forks buffer-truncate",
                suggestion="Split across multiple STRING lines with a short DELAY between",
            )


@_rule("W004", LintSeverity.WARNING, "Script with many STRINGs has no DEFAULTDELAY")
def _w004_missing_default_delay(ctx: _LintContext) -> Iterable[LintFinding]:
    """Five+ STRINGs without a DEFAULTDELAY typically produce jittery
    timing on slow hosts. Suggest adding one.
    """
    strings = [c for c in ctx.parsed.commands if c.command in {"STRING", "STRINGLN"}]
    defaults = [
        c for c in ctx.parsed.commands if c.command in {"DEFAULTDELAY", "DEFAULT_DELAY"}
    ]
    if len(strings) > 5 and not defaults:
        first = strings[0]
        yield LintFinding(
            code="W004",
            severity=LintSeverity.WARNING,
            line=first.line_no,
            column=None,
            message=(
                f"script has {len(strings)} STRING commands but no DEFAULTDELAY — "
                "timing may be jittery on slow hosts"
            ),
            suggestion="Add `DEFAULTDELAY 50` near the top",
        )


@_rule("W005", LintSeverity.WARNING, "Hak5-only command silently ignored by Flipper")
def _w005_hak5_only(ctx: _LintContext) -> Iterable[LintFinding]:
    """VID_/PID_/WAIT_FOR_HOST etc. are Hak5 Ducky Mark II only. The
    Flipper runner skips them without comment.
    """
    for c in ctx.parsed.commands:
        if c.command in _HAK5_ONLY:
            yield LintFinding(
                code="W005",
                severity=LintSeverity.WARNING,
                line=c.line_no,
                column=1,
                message=(
                    f"{c.command} is Hak5-only; Flipper BadUSB runner silently ignores it"
                ),
                suggestion="Remove the line or gate it behind a REM comment",
            )
            continue
        # Also catch VID_..., PID_... with a payload after the underscore.
        prefix = c.command.split("_", 1)[0] + "_"
        if prefix in _HAK5_ONLY and "_" in c.command:
            yield LintFinding(
                code="W005",
                severity=LintSeverity.WARNING,
                line=c.line_no,
                column=1,
                message=(
                    f"{c.command} starts with Hak5-only prefix {prefix!r}; "
                    f"Flipper ignores it"
                ),
                suggestion="Remove the line if you're targeting Flipper",
            )


@_rule("W006", LintSeverity.WARNING, "Platform-specific combo without platform REM hint")
def _w006_platform_without_hint(ctx: _LintContext) -> Iterable[LintFinding]:
    """`GUI r` works only on Windows Run dialog; `GUI SPACE` opens
    macOS Spotlight. Without a `REM Target:` hint mentioning the
    platform, a maintainer can't tell whether the wrong platform is a
    bug or the intent.
    """
    header = _header_rems(ctx.parsed.commands)
    header_text = " ".join(c.args.lower() for c in header)
    hints_windows = "windows" in header_text
    hints_mac = bool(re.search(r"\b(macos|mac|darwin|osx|macintosh)\b", header_text))
    for c in ctx.parsed.commands:
        combo = f"{c.command} {c.args.strip().upper()}".strip()
        hyphen = combo.replace(" ", "-")
        if combo in _WINDOWS_ONLY_COMBOS or hyphen in _WINDOWS_ONLY_COMBOS:
            if not hints_windows:
                yield LintFinding(
                    code="W006",
                    severity=LintSeverity.WARNING,
                    line=c.line_no,
                    column=1,
                    message=f"{combo!r} is Windows-specific; header doesn't declare target",
                    suggestion="Add `REM Target: Windows` to the header",
                )
        elif combo in _MAC_ONLY_COMBOS or hyphen in _MAC_ONLY_COMBOS:
            if not hints_mac:
                yield LintFinding(
                    code="W006",
                    severity=LintSeverity.WARNING,
                    line=c.line_no,
                    column=1,
                    message=f"{combo!r} is macOS-specific; header doesn't declare target",
                    suggestion="Add `REM Target: macOS` to the header",
                )


@_rule("W007", LintSeverity.WARNING, "Mixed-case command keyword")
def _w007_mixed_case(ctx: _LintContext) -> Iterable[LintFinding]:
    """`Delay 100` is accepted by the parser (it upper-cases) but the
    canonical form is `DELAY 100`. Flag for readability.
    """
    for line_no, raw in ctx.lines_indexed():
        stripped = raw.strip()
        if not stripped:
            continue
        first = stripped.split(maxsplit=1)[0]
        if first != first.upper() and first.upper() in _CANONICAL_UPPER:
            yield LintFinding(
                code="W007",
                severity=LintSeverity.WARNING,
                line=line_no,
                column=raw.find(first) + 1,
                message=f"command keyword {first!r} is not uppercase",
                suggestion=f"Write it as `{first.upper()}`",
            )


@_rule("W008", LintSeverity.WARNING, "Trailing whitespace on line")
def _w008_trailing_whitespace(ctx: _LintContext) -> Iterable[LintFinding]:
    """Trailing whitespace can silently make `STRING x ` type an extra
    space. Flag any non-blank line with trailing spaces or tabs.
    """
    for line_no, raw in ctx.lines_indexed():
        if raw.rstrip("\r\n") == "":
            continue
        # Skip lines that are pure whitespace; column math would be off
        # by one and the warning isn't actionable.
        if raw.rstrip() == "":
            continue
        if raw != raw.rstrip(" \t"):
            yield LintFinding(
                code="W008",
                severity=LintSeverity.WARNING,
                line=line_no,
                column=len(raw.rstrip(" \t")) + 1,
                message="trailing whitespace",
                suggestion="Strip the trailing spaces/tabs",
            )


@_rule("W009", LintSeverity.WARNING, "CRLF line endings detected")
def _w009_crlf(ctx: _LintContext) -> Iterable[LintFinding]:
    """Flipper prefers Unix line endings. CRLF doesn't actually break
    stock firmware but causes a stray ^M keystroke on some forks.
    """
    if "\r\n" in ctx.source:
        yield LintFinding(
            code="W009",
            severity=LintSeverity.WARNING,
            line=1,
            column=None,
            message="file uses CRLF line endings; Flipper prefers LF",
            suggestion="Convert the file to Unix line endings (LF only)",
        )


@_rule("W010", LintSeverity.WARNING, "ALT-STRING without Flipper/Momentum REM hint")
def _w010_alt_string_without_hint(ctx: _LintContext) -> Iterable[LintFinding]:
    """ALT-STRING is a Momentum/Xtreme extension. Stock firmware and
    Unleashed don't support it. Warn unless the header REM declares
    the target firmware.
    """
    header = _header_rems(ctx.parsed.commands)
    header_text = " ".join(c.args.lower() for c in header)
    hints_fork = any(
        tok in header_text for tok in ("momentum", "xtreme", "alt-string", "alt_string")
    )
    if hints_fork:
        return
    for c in ctx.parsed.commands:
        if c.command in {"ALT-STRING", "ALTSTRING", "ALTCHARS", "ALT-CHARS"}:
            yield LintFinding(
                code="W010",
                severity=LintSeverity.WARNING,
                line=c.line_no,
                column=1,
                message=(
                    f"{c.command} is a Momentum/Xtreme extension; "
                    "stock/Unleashed firmware ignore it"
                ),
                suggestion="Add `REM Firmware: Momentum` to the header if targeting that fork",
            )


@_rule("W011", LintSeverity.WARNING, "HOLD without DELAY before its RELEASE")
def _w011_hold_without_delay(ctx: _LintContext) -> Iterable[LintFinding]:
    """Some firmware forks don't register a HOLD -> RELEASE pair that
    has zero delay between them; the modifier press-release fires in
    the same USB tick and is collapsed.
    """
    commands = ctx.parsed.commands
    for i, c in enumerate(commands):
        if c.command != "HOLD":
            continue
        # Find the matching RELEASE for this HOLD's key.
        held_key = c.args.strip().upper()
        if not held_key:
            continue
        # Walk forward; if we see the RELEASE with no DELAY between, flag it.
        has_delay_between = False
        for j in range(i + 1, len(commands)):
            later = commands[j]
            if later.command in {"DELAY", "DEFAULTDELAY", "DEFAULT_DELAY"}:
                has_delay_between = True
                continue
            if (
                later.command == "RELEASE"
                and later.args.strip().upper() == held_key
            ):
                if not has_delay_between:
                    yield LintFinding(
                        code="W011",
                        severity=LintSeverity.WARNING,
                        line=c.line_no,
                        column=1,
                        message=(
                            f"HOLD {held_key} / RELEASE with no DELAY between; "
                            "some firmware collapses the press-release"
                        ),
                        suggestion=(
                            f"Add `DELAY 50` between HOLD {held_key} and RELEASE {held_key}"
                        ),
                    )
                break


# ---------------------------------------------------------------------------
# I-rules
# ---------------------------------------------------------------------------


@_rule("I001", LintSeverity.INFO, "Script exceeds 200 lines")
def _i001_long_script(ctx: _LintContext) -> Iterable[LintFinding]:
    """Long DuckyScripts are usually a copy-paste-dump and benefit
    from being split into functional chunks. Informational only.
    """
    n = len(ctx.raw_lines)
    # A file ending in a newline produces an empty last entry — ignore it.
    if ctx.raw_lines and ctx.raw_lines[-1] == "":
        n -= 1
    if n > 200:
        yield LintFinding(
            code="I001",
            severity=LintSeverity.INFO,
            line=1,
            column=None,
            message=f"script is {n} lines; consider breaking into smaller payloads",
            suggestion=None,
        )


@_rule("I002", LintSeverity.INFO, "Many consecutive REM comments (>5)")
def _i002_deep_rem_nesting(ctx: _LintContext) -> Iterable[LintFinding]:
    """More than 5 consecutive REM lines is usually copy-pasted
    boilerplate or a commented-out block that should be deleted.
    """
    streak = 0
    streak_start: int | None = None
    reported: set[int] = set()
    for c in ctx.parsed.commands:
        if c.command == "REM":
            if streak == 0:
                streak_start = c.line_no
            streak += 1
        else:
            if streak > 5 and streak_start is not None and streak_start not in reported:
                reported.add(streak_start)
                yield LintFinding(
                    code="I002",
                    severity=LintSeverity.INFO,
                    line=streak_start,
                    column=None,
                    message=f"{streak} consecutive REM comments",
                    suggestion="Consider collapsing or deleting commented-out blocks",
                )
            streak = 0
            streak_start = None
    if streak > 5 and streak_start is not None and streak_start not in reported:
        yield LintFinding(
            code="I002",
            severity=LintSeverity.INFO,
            line=streak_start,
            column=None,
            message=f"{streak} consecutive REM comments",
            suggestion="Consider collapsing or deleting commented-out blocks",
        )


@_rule("I003", LintSeverity.INFO, "Duplicate consecutive commands")
def _i003_duplicate_consecutive(ctx: _LintContext) -> Iterable[LintFinding]:
    """Two identical commands in a row are either a copy-paste mistake
    or an intentional reliability retry. Either way, info-worthy.
    REM and DELAY are excluded because intentional repeats are common.
    """
    prev: DuckyCommand | None = None
    for c in ctx.parsed.commands:
        if c.command in {"REM", "DELAY", "DEFAULTDELAY", "DEFAULT_DELAY"}:
            prev = c
            continue
        if (
            prev is not None
            and prev.command == c.command
            and prev.args == c.args
        ):
            yield LintFinding(
                code="I003",
                severity=LintSeverity.INFO,
                line=c.line_no,
                column=1,
                message=(
                    f"duplicate of line {prev.line_no}: {c.command} {c.args}".rstrip()
                ),
                suggestion="Remove the duplicate, or use `REPEAT 2` for intentional retries",
            )
        prev = c


@_rule("I004", LintSeverity.INFO, "STRING contains non-ASCII characters")
def _i004_non_ascii(ctx: _LintContext) -> Iterable[LintFinding]:
    """Non-ASCII characters depend on the Flipper's keyboard-layout
    setting and may not survive translation to HID scancodes.
    """
    for c in ctx.parsed.commands:
        if c.command not in {"STRING", "STRINGLN"}:
            continue
        try:
            c.args.encode("ascii")
        except UnicodeEncodeError:
            # Find the first non-ascii char's column for a useful caret.
            col = 1
            for idx, ch in enumerate(c.args):
                if ord(ch) > 0x7E:
                    col = idx + 1
                    break
            yield LintFinding(
                code="I004",
                severity=LintSeverity.INFO,
                line=c.line_no,
                column=col,
                message=(
                    "STRING contains non-ASCII chars; keyboard-layout setting "
                    "affects whether they survive"
                ),
                suggestion="Use ALT-STRING on Windows targets for layout-independent Unicode",
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


ALL_RULE_CODES: frozenset[str] = frozenset(r.code for r in _RULES)


def iter_rules() -> Iterator[tuple[str, LintSeverity, str]]:
    """Yield (code, severity, description) for every registered rule.

    Public read-only view over the rule registry. Stable ordering matches
    the registration order (which is also the order rules execute in).
    """
    for r in _RULES:
        yield (r.code, r.severity, r.description)


def lint(
    source: str, *, rules: set[str] | None = None, ignore: set[str] | None = None
) -> LintReport:
    """Parse `source` with the existing DuckyScript parser, then run all
    registered lint rules.

    `rules`  : if given, only run rules whose code is in the set.
    `ignore` : if given, skip rules whose code is in the set.
    """
    parsed = parse_script(source)
    return lint_parsed(source, parsed, rules=rules, ignore=ignore)


def lint_parsed(
    source: str,
    parsed: ParseResult,
    *,
    rules: set[str] | None = None,
    ignore: set[str] | None = None,
) -> LintReport:
    """Lint an already-parsed DuckyScript.

    Exposed separately so `payload_badusb_validate` can avoid
    re-parsing the source — it already has a `ParseResult` in hand.
    """
    normalised = source.replace("\r\n", "\n").replace("\r", "\n")
    ctx = _LintContext(
        source=source,
        parsed=parsed,
        raw_lines=normalised.split("\n"),
    )
    findings: list[LintFinding] = []
    for rule in _RULES:
        if rules is not None and rule.code not in rules:
            continue
        if ignore is not None and rule.code in ignore:
            continue
        findings.extend(rule.fn(ctx))
    # Sort findings by (line, severity, code) so output is stable.
    _severity_order = {
        LintSeverity.ERROR: 0,
        LintSeverity.WARNING: 1,
        LintSeverity.INFO: 2,
    }
    findings.sort(key=lambda f: (f.line, _severity_order[f.severity], f.code))
    return LintReport(findings=tuple(findings))
