"""
Flipper CLI text-mode session.

Opens a serial link in plain CLI mode (NO start_rpc_session), runs one text
command, reads back its output until the next prompt, and returns it.

Used by `Flipper.cli()` for operations that have no native protobuf RPC:
LED, vibro, subghz tx, ir tx, nfc/rfid/ibutton emulate, badusb run.

Flipper's CLI protocol (observed on stock + Momentum):
  - After reset / fresh connect, firmware emits a banner followed by ">: "
  - Each command is:
        command\\r  ->  (echo back) command\\n\\n  <output lines>  \\n>:
  - Some commands (like `led r 255`) produce no output — we still get the
    prompt back, so `read_until(">: ")` is reliable.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from echoforge.transport.serial_link import CLI_PROMPT, SerialLink

log = logging.getLogger(__name__)


@dataclass
class CliResult:
    command: str
    raw: bytes            # exact bytes returned (for debugging)
    output: str           # cleaned output: echo stripped, prompt stripped, trimmed
    duration_ms: float


class CliSession:
    """One-shot CLI command execution on a non-RPC serial link.

    The caller is responsible for making sure the link is in CLI mode
    (i.e., `enter_rpc_mode()` was NOT called on it). Typically constructed
    and discarded for a single command by `CliSession.exchange(port, cmd)`.
    """

    def __init__(self, link: SerialLink):
        self._link = link

    @classmethod
    def exchange(
        cls,
        port: str,
        command: str,
        *,
        command_timeout_s: float = 5.0,
    ) -> CliResult:
        """Open a fresh serial link, run `command`, return parsed result.

        The pyserial timeout governs how long read_until waits for the
        CLI prompt terminator — it returns the moment it sees ">: ", so
        this is a MAX wait, not a fixed cost.
        """
        link = SerialLink(port, timeout=command_timeout_s)
        link.open()
        try:
            # Give the firmware a beat after the CDC enumerate to settle.
            time.sleep(0.05)
            session = cls(link)
            session._wait_for_prompt()
            return session.run(command, timeout_s=command_timeout_s)
        finally:
            link.close()

    # -- primary entry -----------------------------------------------------

    # Cap raw CLI output. `help` is ~1.5 KB on Momentum, `ls` of /ext is
    # ~3 KB. 256 KB is a huge headroom for anything realistic.
    MAX_CLI_BYTES = 256 * 1024

    def run(self, command: str, *, timeout_s: float = 5.0) -> CliResult:
        """Send one command and read back until the next prompt.

        Uses pyserial's `read_until(terminator)` which returns IMMEDIATELY
        once the terminator is seen — unlike `read(n)` which blocks for the
        full port timeout when fewer than n bytes arrive.
        """
        self._link.drain_input()

        command = command.rstrip()  # no trailing \r — we'll add it
        sent_bytes = command.encode("utf-8") + b"\r"
        t0 = time.perf_counter()
        self._link.write(sent_bytes)

        raw = self._link.read_until(CLI_PROMPT, max_bytes=self.MAX_CLI_BYTES)
        dt_ms = (time.perf_counter() - t0) * 1000

        if not raw.endswith(CLI_PROMPT):
            raise TimeoutError(
                f"CLI command {command!r} did not return prompt within {timeout_s}s "
                f"(got {len(raw)} bytes, tail={raw[-32:]!r})"
            )

        cleaned = _clean_cli_output(raw, command=command)
        return CliResult(command=command, raw=raw, output=cleaned, duration_ms=dt_ms)

    # -- helpers -----------------------------------------------------------

    def _wait_for_prompt(self) -> bytes:
        """Wake the CLI with a CR and wait for the prompt. Uses read_until
        which exits immediately on terminator match."""
        self._link.write(b"\r")
        # read_until respects the port's total timeout; we rely on the caller
        # having opened SerialLink with a reasonable timeout. Pulling 4 KB
        # is plenty for the typical CLI banner + prompt.
        return self._link.read_until(CLI_PROMPT, max_bytes=4096)


def _clean_cli_output(raw: bytes, *, command: str) -> str:
    """
    Strip the command echo and the trailing prompt, return the human-readable
    body. Preserves internal newlines and formatting.
    """
    # Decode lenient — Flipper CLI is mostly ASCII but some commands emit
    # UTF-8 (e.g. the dolphin ASCII art).
    text = raw.decode("utf-8", errors="replace")

    # Normalize CRLF → LF for downstream processing.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Drop the command echo: find the first line that contains the command
    # and slice after it. Firmware echoes back `command\n` or `command\n\n`.
    lines = text.split("\n")
    cmd_echo_idx: Optional[int] = None
    for i, line in enumerate(lines):
        if line.strip() == command.strip():
            cmd_echo_idx = i
            break
    if cmd_echo_idx is not None:
        lines = lines[cmd_echo_idx + 1:]

    # Strip trailing prompt (">: ") and any blank lines that precede it.
    while lines and lines[-1].strip().rstrip(":") in {"", ">"}:
        lines.pop()

    return "\n".join(lines).strip("\n")
