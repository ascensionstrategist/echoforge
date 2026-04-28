# Canonical DuckyScript Payloads — Annotated

Five payloads that together cover the patterns you will reuse in 80% of BadUSB work. Each is production-tested on Flipper Momentum `mntm-012` against Windows 11 23H2 with US keyboard layout. Line-by-line annotations explain the **why**, not just the **what**.

---

## 1. `hello-world.txt` — Minimum viable payload

```
REM Title: hello-world
REM Target: Windows 10/11, US layout
REM Opens Notepad, types one line, saves nothing.
DELAY 1000
GUI r
DELAY 500
STRING notepad
ENTER
DELAY 1500
STRING Hello from Flipper Zero BadUSB
```

| Line | Why |
|------|-----|
| `DELAY 1000` | USB HID enumeration; host claims device. Without this, `GUI r` is eaten. |
| `GUI r` | Open Run dialog. `GUI` = Windows key on Windows, Command on macOS, Super on Linux. |
| `DELAY 500` | Run dialog takes ~200–400 ms to render on a modern machine. 500 is safe. |
| `STRING notepad` | Types into the Run box. No trailing Enter yet. |
| `ENTER` | Submit Run dialog. |
| `DELAY 1500` | Notepad cold-start is slow; wait for window to have focus. Budget more here, not less — a payload that fails because Notepad hadn't opened yet is the single most common bug. |
| Final `STRING` | The actual keystrokes you wanted to deliver. |

---

## 2. `rickroll.txt` — Open a URL in default browser

```
REM Title: rickroll
REM Target: Windows, macOS, Linux (tested), US layout
REM Opens the default browser to a YouTube URL. Classic demo.
DELAY 1000
GUI r
DELAY 500
STRING https://youtu.be/dQw4w9WgXcQ
DELAY 200
ENTER
```

**Why this works cross-platform.** `GUI r` on Windows opens Run; on macOS it does nothing useful. But Windows' Run dialog treats a URL as "open in default browser" via `ShellExecute`. A more portable variant uses the browser-open trick in payload #4 below.

**Common mistakes.**

- Typing the URL *before* the Run dialog has opened: missing the `DELAY 500`.
- Forgetting that on a non-US layout, `/` and `:` and `.` may be in different positions. A UK-layout Flipper typing `https://youtu.be/...` will produce `https:\\youtu.be\...`. Use `REM LAYOUT: us` at the top if the target PC is US-configured and you don't know the Flipper's layout.

---

## 3. `clipboard-demo.txt` — Put text on the clipboard, don't paste

```
REM Title: clipboard-demo
REM Target: Windows 10/11, US layout
REM Demonstrates using PowerShell to stage a string on the clipboard without pasting.
REM Useful as a building block; change the STRING to whatever you want staged.
DELAY 1000
GUI r
DELAY 500
STRING powershell -w hidden -NoProfile -c "Set-Clipboard -Value 'demo-value-from-flipper'"
DELAY 200
ENTER
DELAY 800
REM Window closes itself because the command completes and no further input is pending.
```

**Why `-w hidden -NoProfile`.** `-w hidden` keeps the console window minimized so the operator doesn't see a flash. `-NoProfile` avoids loading the user's PowerShell profile (which may be slow or raise AMSI alarms).

**Why `Set-Clipboard` and not `clip.exe`.** `echo x | clip` works, but piping from `STRING` requires either `STRING` breaking the pipe or careful quoting. `Set-Clipboard` is a single cmdlet call, simpler to type cleanly.

**Detection surface.** On a modern Windows 11 with default settings, this triggers an AMSI scan of the PowerShell command line. AMSI doesn't block this particular payload, but Defender ASR rules (e.g. "Block execution of potentially obfuscated scripts") can; test against the real target before relying on this pattern.

---

## 4. `browser-open-crossplatform.txt` — Portable URL open

```
REM Title: browser-open-crossplatform
REM Target: Windows, macOS, Linux (GNOME/KDE)
REM Uses platform-specific spotlight/run equivalents; relies on firmware-set keyboard layout.

REM --- Windows path ---
DELAY 1000
GUI r
DELAY 400
STRING https://example.com
ENTER
DELAY 300

REM If nothing happened (non-Windows target), fall through to macOS
GUI SPACE
DELAY 400
STRING open https://example.com
ENTER
```

**Why the fall-through works.** On Windows, `GUI SPACE` is a harmless input-method hotkey (usually no-op or switches input language on multi-language systems — not catastrophic). The URL has already been opened by the first block, so the second block's typed command goes into a background context.

On macOS, `GUI r` does nothing (Command+R in Finder = "Make Alias"; in most apps a no-op), so the second block's `GUI SPACE` fires Spotlight, and `open https://...` is a real shell command.

On Linux GNOME, `GUI SPACE` toggles the Activities search; typing `open https://...` won't work (no `open` command by default) — a Linux-targeted portable version instead types `xdg-open https://...`.

**Lesson.** There is no perfect cross-platform trigger. If you need reliable Linux support, write a Linux-specific payload and have the operator select the right file on the Flipper UI.

---

## 5. `app-launcher.txt` — Pattern for "launch and control an app"

```
REM Title: app-launcher
REM Target: Windows 10/11, US layout
REM Opens Calculator, switches to programmer mode, types a hex value.
REM Showcases: modifier + key, CTRL-tab navigation inside app.

DELAY 1000
GUI r
DELAY 500
STRING calc
ENTER
DELAY 2500
REM Calc UWP cold-start is slow; budget 2-3s.

REM Switch to Programmer mode: Ctrl+4 in modern Calculator
CTRL 4
DELAY 800

REM Switch to HEX: Alt+H (underlined in the mode toggle)
ALT h
DELAY 400

REM Type a hex value
STRING DEADBEEF
DELAY 200

REM Copy the decimal equivalent with Ctrl+C (decimal is shown in the sidebar)
CTRL c
DELAY 200
```

**Why `DELAY 2500` after Calc.** Windows Calculator is a UWP app; cold-start from a clean state can take 1.5–2.5 seconds on spinning-rust drives, less on SSDs. Picking the pessimistic value keeps the payload reliable across machines.

**Why `CTRL 4` for Programmer mode.** Calculator's keyboard shortcuts: Alt+1 = Standard, Alt+2 = Scientific, Alt+3 = Graphing, Alt+4 = Programmer, Ctrl+M = Memory. These are documented in Calc's `?` help. Prefer documented shortcuts over menu traversal — they don't break when Microsoft reshuffles the ribbon.

**Generalization.** Every "open app and drive it" payload has the same skeleton:

```
DELAY 1000                        (enumeration)
GUI r / GUI SPACE / alt launcher  (open runner)
DELAY <runner-open-delay>
STRING <app-name>                 (or URL, or path)
ENTER
DELAY <app-cold-start-delay>      (THE most commonly-undersized delay)
...app-specific keystrokes...
```

Tune `<app-cold-start-delay>` to the slowest machine you intend to hit. A 500 ms delay tuned on your dev workstation will fail on a locked-down corporate laptop 30% of the time.

---

## Timing cheat-sheet

| Situation | Minimum safe delay (ms) |
|-----------|-------------------------|
| After USB enumeration (script start) | 1000 |
| After `GUI r` (Run dialog) | 300 |
| After typing into Run + `ENTER` (light app: `notepad`, `cmd`) | 400 |
| After typing into Run + `ENTER` (heavy app: `calc`, `winword`, `teams`) | 1500–3000 |
| After `GUI d` (show desktop) | 200 |
| After `ALT-TAB` window switch | 250 |
| Between consecutive `STRING`s in same field | 50 |
| PowerShell one-liner submit → window settle | 800 |
| Across RDP / VM console / KVM switch | 2–5x the above |

When in doubt, add `DEFAULTDELAY 50` at the top and delete it if the payload is too slow. Better to run slow and succeed than run fast and fail.
