# DuckyScript 3.0 — Complete Language Reference

Sources:
- Hak5 official docs: https://docs.hak5.org/hak5-usb-rubber-ducky/
- Flipper BadUSB runner: `flipperdevices/flipperzero-firmware/applications/main/bad_usb/helpers/ducky_script.c` (and `ducky_script_commands.c`).

DuckyScript 3.0 is a superset of 1.0. On a Flipper, the intersection of the two runtimes is what you can rely on; anything in this doc tagged **[Hak5-only]** will be silently ignored or error out on Flipper.

---

## 1. Lexical structure

- One command per line. Line = `COMMAND` `<space>` `ARGUMENT(S)`.
- Leading whitespace is ignored.
- Empty lines are ignored.
- `REM` starts a comment — everything after `REM` to end-of-line is discarded.
- No multi-line statements (no `\` continuation, no heredocs).
- Case: commands are CASE-SENSITIVE on Flipper. `Delay 1000` will NOT match `DELAY`. Always uppercase.
- Line terminator: LF or CRLF accepted; CR-only (classic Mac) is not.

---

## 2. Comments & metadata

```
REM Title: Example payload
REM Author: Operator
REM Target: Windows 10/11, US layout
REM Description: opens Notepad and types a line.
REM_BLOCK                                       [Hak5-only, Flipper ignores]
REM This is a multi-line
REM comment block. Everything inside is ignored
REM until END_REM is seen.
END_REM                                         [Hak5-only]
```

On Flipper, prefer individual `REM` lines — `REM_BLOCK` works as a single-line REM only.

---

## 3. Timing

| Command | Args | Example | Notes |
|---------|------|---------|-------|
| `DELAY` | `<ms>` int 0–600000 | `DELAY 1000` | Sleep, no keystrokes. |
| `DEFAULTDELAY` / `DEFAULT_DELAY` | `<ms>` int | `DEFAULTDELAY 50` | Inserted between EVERY subsequent command. Accumulates with explicit `DELAY`. |
| `DEFAULTCHARDELAY` / `DEFAULT_CHAR_DELAY` | `<ms>` int | `DEFAULTCHARDELAY 10` | Per-character delay inside `STRING`. Defaults to ~5 ms. Raise to 30–50 for slow-polling targets (KVM switches, virtual machines, RDP sessions). |
| `HOLD` | `<KEY>` | `HOLD SHIFT` | **Flipper extension**. Presses and holds the key until `RELEASE`. |
| `RELEASE` | `<KEY>` | `RELEASE SHIFT` | **Flipper extension**. Releases a held key. |
| `WAIT_FOR_BUTTON_PRESS` | none | | **Flipper extension**. Pauses until operator presses the Flipper's center OK button. Useful for "verify focus before typing" payloads. |

---

## 4. Keystrokes

### 4.1 Modifiers (press & immediately release with the following key)

| Name | Alias(es) |
|------|-----------|
| `CTRL` | `CONTROL` |
| `ALT` | `OPTION` |
| `SHIFT` | |
| `GUI` | `WINDOWS` `COMMAND` `SUPER` |

Combine with hyphen: `CTRL-ALT-DEL`, `CTRL-SHIFT-ESC`. Order does not matter functionally — all modifiers go down before the final key, come up after.

### 4.2 Named keys

Arrows: `UP`, `DOWN`, `LEFT`, `RIGHT`.
Navigation: `HOME`, `END`, `PAGEUP`, `PAGEDOWN`, `INSERT`, `DELETE`.
Editing: `BACKSPACE`, `TAB`, `ENTER` (alias `RETURN`), `SPACE`, `ESCAPE` (alias `ESC`).
Function: `F1` through `F12` (Flipper also accepts `F13`–`F24` on firmwares that support extended USB HID).
Lock: `CAPSLOCK`, `NUMLOCK`, `SCROLLLOCK`.
Misc: `PRINTSCREEN`, `PAUSE` (aliases `BREAK`, `SYSRQ`), `APP` (context-menu key), `POWER`.

### 4.3 Media keys [Flipper: Momentum+ only]

`PLAY`, `PAUSE_MEDIA`, `NEXTTRACK`, `PREVTRACK`, `STOP_MEDIA`, `MUTE`, `VOLUMEUP`, `VOLUMEDOWN`.

### 4.4 Numpad

`NUM0`–`NUM9`, `NUMLOCK`, `NUMSLASH`, `NUMSTAR`, `NUMMINUS`, `NUMPLUS`, `NUMENTER`, `NUMDOT`.

---

## 5. Strings

```
STRING <text>          # types text, no trailing ENTER
STRINGLN <text>        # types text + ENTER       [Flipper: supported on stock]
STRING_DELAY <ms>      # per-character delay for next STRING only [Hak5-only]
ALT-STRING <text>      # types using ALT+numpad Unicode escapes   [Flipper extension]
ALT-CHARS <text>       # alias of ALT-STRING                      [Flipper extension]
```

`ALT-STRING` is the recommended way to type non-ASCII on a Windows target without relying on keyboard-layout match — it emits `ALT + <numpad digits>` for each character's decimal codepoint, which Windows always interprets as that Unicode char regardless of current layout. macOS and Linux do not respond to this sequence.

---

## 6. Variables, arithmetic & control flow (DuckyScript 3.0)

### 6.1 Variables

```
VAR $COUNTER = 0
VAR $MAX = 10
VAR $NAME = STRING_VALUE                  # string vars use unquoted tokens
```

Variable names **MUST** start with `$` and contain only `[A-Z0-9_]`. Scope is flat (global). Numeric vars hold signed 32-bit ints.

### 6.2 Arithmetic

```
$COUNTER = $COUNTER + 1
$COUNTER = ($MAX - 3) * 2
```

Operators: `+ - * / %`. Parentheses allowed. No bitwise ops.

### 6.3 Conditionals

```
IF ($COUNTER < 5) THEN
    STRING counter still low
    ENTER
END_IF

IF ($COUNTER < 5) THEN
    STRING low
ELSE IF ($COUNTER == 5) THEN
    STRING exactly five
ELSE
    STRING high
END_IF
```

Comparisons: `== != < <= > >=`. Logical: `&&` `||` `!`. Flipper supports all of these as of stock firmware ≥ 0.85.

### 6.4 Loops

```
WHILE ($COUNTER < $MAX)
    STRING row
    ENTER
    $COUNTER = $COUNTER + 1
END_WHILE
```

There is no `FOR`, `DO`/`UNTIL`, or `BREAK` on Flipper — fake them with `IF ... END_IF` inside `WHILE`.

### 6.5 Functions

```
FUNCTION TYPE_LINE()
    STRING hello
    ENTER
END_FUNCTION

TYPE_LINE()
DELAY 500
TYPE_LINE()
```

No arguments, no return values on Flipper (Hak5 Ducky Mark II supports arguments via `$_PARAM_N`; Flipper does not). Use globals.

### 6.6 Random values

```
VAR $R = $_RANDOM_INT(1,100)              # inclusive range
VAR $L = $_RANDOM_LCASE_LETTER            # a–z
VAR $U = $_RANDOM_UCASE_LETTER            # A–Z
VAR $N = $_RANDOM_LETTER                  # mixed case
VAR $S = $_RANDOM_SPECIAL                 # one of !@#$%^&*...
```

---

## 7. `REPEAT`

```
STRING row
ENTER
REPEAT 9
```

Repeats the **line immediately above** n more times. So this types "row\n" ten times total. `REPEAT 0` is a no-op.

---

## 8. System variables [Flipper partial]

Hak5 exposes `$_SYSTEM_BITS`, `$_HOST_CONFIGURATION`, `$_NUMLOCK`, `$_CAPSLOCK`, `$_SCROLLLOCK`, `$_EXFIL_MODE`, etc. Flipper implements essentially none of these as of mntm-012 — it cannot read the host's lock-key state because Flipper's USB stack doesn't parse HID IN reports for the lock LEDs. Scripts that rely on `$_CAPSLOCK == TRUE` for exfil-over-lockey-blink are Hak5-only.

---

## 9. `IMPORT` & sub-scripts [Hak5-only]

DuckyScript 3.0 `IMPORT another.dd3` is not implemented on Flipper. Keep payloads self-contained.

---

## 10. Error behavior

Flipper's parser is **forgiving** — it logs unknown commands to the Flipper's console but continues. A typo like `DELYA 1000` means the line is silently skipped, not crashed. Unknown commands inside a `FUNCTION` body abort that function's call. Your `payload_badusb_validate` tool should flag unknowns as warnings, not errors, because custom firmwares legitimately add commands.
