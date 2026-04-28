"""
Hardware action helpers that live on top of `Flipper.cli()`.

None of these have dedicated protobuf RPCs — they're exposed only through
the Flipper's text CLI, so every call incurs a ~400–600 ms RPC↔CLI mode
switch. That's fine for occasional actuation (LED blink, TX a signal)
but don't call these in a tight loop.

Covered here:
    LED — red / green / blue / backlight, on/off/brightness
    Vibro — on / off / pulse convenience
    Buzzer — play tone for duration
    SubGHz — transmit from .sub file
    IR — transmit from .ir file
    RFID — emulate from .rfid file
    iButton — emulate from .ibtn file
    NFC — emulate is GUI-only on most firmwares; exposed as loader launch
    BadUSB — run a .txt script via loader

Exact CLI syntax varies across stock / Momentum / Xtreme. This module
favors the Momentum convention (mntm-012 verified on COM7); other
firmwares may need minor adjustments.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from echoforge.flipper import Flipper
    from echoforge.transport.cli_session import CliResult


class LedColor(str, enum.Enum):
    RED = "r"
    GREEN = "g"
    BLUE = "b"
    BACKLIGHT = "bl"


# Flipper LED brightness is 0–255.
LED_MAX = 255


@dataclass(frozen=True)
class CliAck:
    """Thin wrapper so callers can see the raw CLI output (useful for
    debugging when a firmware-specific command fails)."""
    command: str
    output: str
    duration_ms: float

    @classmethod
    def _from_cli(cls, result: "CliResult") -> "CliAck":
        return cls(command=result.command, output=result.output, duration_ms=result.duration_ms)


class Led:
    """Control the RGB status LED and the screen backlight via `led` CLI."""

    def __init__(self, flipper: "Flipper"):
        self._f = flipper

    def set(self, color: LedColor | str, level: int) -> CliAck:
        """Set one channel's brightness (0–255). `led r 255` → full red."""
        ch = color.value if isinstance(color, LedColor) else color
        if ch not in {c.value for c in LedColor}:
            raise ValueError(f"LED color must be one of r/g/b/bl, got {ch!r}")
        level = max(0, min(LED_MAX, int(level)))
        return CliAck._from_cli(self._f.cli(f"led {ch} {level}"))

    def red(self, level: int = LED_MAX) -> CliAck:
        return self.set(LedColor.RED, level)

    def green(self, level: int = LED_MAX) -> CliAck:
        return self.set(LedColor.GREEN, level)

    def blue(self, level: int = LED_MAX) -> CliAck:
        return self.set(LedColor.BLUE, level)

    def backlight(self, level: int = LED_MAX) -> CliAck:
        return self.set(LedColor.BACKLIGHT, level)

    def off(self, *, include_backlight: bool = False) -> None:
        """Turn R/G/B off. Leaves backlight alone by default so you can
        still see the screen."""
        self.set(LedColor.RED, 0)
        self.set(LedColor.GREEN, 0)
        self.set(LedColor.BLUE, 0)
        if include_backlight:
            self.set(LedColor.BACKLIGHT, 0)

    def blink(self, color: LedColor | str = LedColor.GREEN, *, count: int = 3,
              period_ms: int = 150, level: int = LED_MAX) -> None:
        """Host-side blink. Uses a sticky CLI session so the full strobe
        costs ONE mode switch (on entry) + ONE (on exit), not 2×count.

        Per-state-change is then just the CLI command time (~20-60 ms)
        plus the host sleep — so period_ms is the real human-perceivable
        cadence."""
        ch = color.value if isinstance(color, LedColor) else color
        if ch not in {c.value for c in LedColor}:
            raise ValueError(f"LED color must be one of r/g/b/bl, got {ch!r}")
        level = max(0, min(LED_MAX, int(level)))
        sleep_s = period_ms / 1000.0
        with self._f.cli_session() as cli:
            for _ in range(count):
                cli.run(f"led {ch} {level}")
                time.sleep(sleep_s)
                cli.run(f"led {ch} 0")
                time.sleep(sleep_s)


class Vibro:
    """Control the vibration motor."""

    def __init__(self, flipper: "Flipper"):
        self._f = flipper

    def on(self) -> CliAck:
        return CliAck._from_cli(self._f.cli("vibro 1"))

    def off(self) -> CliAck:
        return CliAck._from_cli(self._f.cli("vibro 0"))

    def pulse(self, *, duration_ms: int = 200) -> None:
        """On, sleep, off — in a single CLI session (one mode-switch round-trip)."""
        with self._f.cli_session() as cli:
            cli.run("vibro 1")
            time.sleep(duration_ms / 1000.0)
            cli.run("vibro 0")


class Buzzer:
    """Play tones through the piezo speaker via `music_player play`.

    Falls back to `note` / `buzzer` depending on firmware naming.
    """

    def __init__(self, flipper: "Flipper"):
        self._f = flipper

    def play(self, frequency_hz: float, duration_ms: int = 200) -> CliAck:
        """Best-effort tone. Momentum uses `music_player play <note>` but not
        all firmwares expose a raw-frequency CLI. This tries a short list."""
        commands = [
            f"music_player play {int(frequency_hz)} {duration_ms}",
            f"buzzer {int(frequency_hz)} {duration_ms}",
            f"note {int(frequency_hz)} {duration_ms}",
        ]
        last_err: Optional[BaseException] = None
        for cmd in commands:
            try:
                result = self._f.cli(cmd)
                # Reject if firmware returned an "unknown command" message.
                if "Command not found" in result.output or "unknown" in result.output.lower():
                    last_err = RuntimeError(f"{cmd!r} rejected: {result.output.strip()[:80]}")
                    continue
                return CliAck._from_cli(result)
            except Exception as exc:  # noqa: BLE001
                last_err = exc
        raise RuntimeError(
            f"no known buzzer/tone command accepted on this firmware. "
            f"Tried: {[c.split()[0] for c in commands]}. Last error: {last_err}"
        )


class SubGhz:
    """SubGHz transmit helpers. RX live capture is a long-running op — not
    covered here; use `subghz rx` manually if needed."""

    def __init__(self, flipper: "Flipper"):
        self._f = flipper

    def transmit_from_file(self, path: str, *, repeats: int = 1) -> CliAck:
        """Replay a .sub file. Path must be absolute (e.g. /ext/subghz/x.sub)."""
        if repeats <= 0:
            raise ValueError("repeats must be >= 1")
        # Momentum convention: `subghz tx_from_file <path> [repeat]`
        cmd = f"subghz tx_from_file {path} {repeats}" if repeats > 1 else f"subghz tx_from_file {path}"
        return CliAck._from_cli(self._f.cli(cmd, timeout_s=30.0))


class Infrared:
    """Infrared transmit helpers."""

    def __init__(self, flipper: "Flipper"):
        self._f = flipper

    def transmit_from_file(self, path: str, *, button_name: Optional[str] = None) -> CliAck:
        """Transmit a signal from a .ir file. Some firmwares require a
        named button from the file; pass it via `button_name`."""
        if button_name:
            cmd = f"ir tx_file {path} {button_name}"
        else:
            cmd = f"ir tx_file {path}"
        return CliAck._from_cli(self._f.cli(cmd, timeout_s=30.0))

    def transmit_raw(self, protocol: str, address: str, command_hex: str) -> CliAck:
        """Transmit a parsed signal without a file. Example protocols:
        NEC / NECext / Sony / Samsung32 / RC5 / RC6."""
        cmd = f"ir tx {protocol} {address} {command_hex}"
        return CliAck._from_cli(self._f.cli(cmd, timeout_s=10.0))


class Emulate:
    """Emulate NFC / RFID / iButton credentials from stored files."""

    def __init__(self, flipper: "Flipper"):
        self._f = flipper

    def rfid(self, path: str) -> CliAck:
        """Emulate a 125 kHz RFID tag from a .rfid file."""
        return CliAck._from_cli(self._f.cli(f"rfid emulate {path}", timeout_s=10.0))

    def ibutton(self, path: str) -> CliAck:
        """Emulate a 1-Wire iButton from a .ibtn file."""
        return CliAck._from_cli(self._f.cli(f"ikey emulate {path}", timeout_s=10.0))

    def nfc(self, path: str) -> CliAck:
        """Launch NFC app with a file loaded. Most firmwares don't expose a
        fully-automated NFC emulate CLI — this opens the app and you press
        OK on the Flipper to begin emulation. If your firmware DOES support
        `nfc emulate <path>`, use `flipper.cli()` directly."""
        return CliAck._from_cli(self._f.cli(f"loader open NFC {path}", timeout_s=5.0))


class BadUsb:
    """Execute a BadUSB (Rubber Ducky-style) script via the loader."""

    def __init__(self, flipper: "Flipper"):
        self._f = flipper

    def run(self, path: str) -> CliAck:
        """Execute a .txt BadUSB script. Path must be a file already on the
        Flipper (push via storage.write() first if needed)."""
        # Momentum uses "Bad KB", stock uses "Bad USB". Try Bad KB first.
        for app_name in ('"Bad KB"', '"Bad USB"'):
            try:
                result = self._f.cli(f"loader open {app_name} {path}", timeout_s=5.0)
                if "not found" not in result.output.lower():
                    return CliAck._from_cli(result)
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError("neither 'Bad KB' nor 'Bad USB' loader name accepted")
