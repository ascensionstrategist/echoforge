"""
USB-CDC serial transport for Flipper Zero.

Flipper Zero shows up as a CDC-ACM serial device on Windows:
    VID 0x0483 (STMicroelectronics), PID 0x5740 or 0x5741

Auto-detects the COM port via pyserial's list_ports USB metadata.
Used by RpcCodec for the protobuf RPC layer, and by raw CLI passthrough.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional

import serial
from serial.tools import list_ports

log = logging.getLogger(__name__)

FLIPPER_VID = 0x0483
FLIPPER_PIDS: tuple[int, ...] = (0x5740, 0x5741)

# Flipper's CLI banner ends with ">: " once the shell is ready. We send a
# newline to kick it, then look for this. RPC mode is entered by sending
# "start_rpc_session\r" and waiting for the response.
CLI_PROMPT = b">: "
RPC_START_COMMAND = b"start_rpc_session\r"


@dataclass(frozen=True)
class FlipperPortInfo:
    device: str          # e.g. "COM3"
    description: str     # e.g. "USB Serial Device (COM3)"
    hwid: str            # VID:PID:SERIAL blob from pyserial
    vid: int
    pid: int
    serial_number: Optional[str]


def find_flipper_port() -> Optional[FlipperPortInfo]:
    """Return the first attached Flipper, or None if none are connected."""
    for port in list_ports.comports():
        if port.vid is None or port.pid is None:
            continue
        if port.vid == FLIPPER_VID and port.pid in FLIPPER_PIDS:
            return FlipperPortInfo(
                device=port.device,
                description=port.description or "",
                hwid=port.hwid or "",
                vid=port.vid,
                pid=port.pid,
                serial_number=port.serial_number,
            )
    return None


def list_candidate_ports() -> list[FlipperPortInfo]:
    """Return every attached Flipper (supports multi-device setups)."""
    out: list[FlipperPortInfo] = []
    for port in list_ports.comports():
        if port.vid == FLIPPER_VID and port.pid in FLIPPER_PIDS:
            out.append(
                FlipperPortInfo(
                    device=port.device,
                    description=port.description or "",
                    hwid=port.hwid or "",
                    vid=port.vid,
                    pid=port.pid,
                    serial_number=port.serial_number,
                )
            )
    return out


class SerialLink:
    """Thread-safe wrapper around a pyserial connection to a Flipper Zero.

    Handles:
      - opening the COM port (baud is ignored by CDC but pyserial requires one)
      - switching the CLI shell into RPC mode
      - synchronized read/write primitives for higher layers
    """

    # CDC-ACM ignores baud rate but pyserial needs *something*.
    BAUD = 230_400

    def __init__(self, port: str, *, timeout: float = 1.0):
        self.port = port
        self.timeout = timeout
        self._serial: Optional[serial.Serial] = None
        self._write_lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def open(self) -> None:
        if self._serial and self._serial.is_open:
            return
        log.debug("opening %s", self.port)
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.BAUD,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout,
            write_timeout=self.timeout,
            rtscts=False,
            dsrdtr=False,
        )

    def close(self) -> None:
        if self._serial and self._serial.is_open:
            log.debug("closing %s", self.port)
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def __enter__(self) -> "SerialLink":
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- raw I/O -----------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def write(self, data: bytes) -> None:
        if not self._serial:
            raise RuntimeError("SerialLink not open")
        with self._write_lock:
            self._serial.write(data)
            self._serial.flush()

    def read(self, n: int) -> bytes:
        if not self._serial:
            raise RuntimeError("SerialLink not open")
        return self._serial.read(n)

    def read_until(self, terminator: bytes, max_bytes: int = 4096) -> bytes:
        """Read until `terminator` is seen or timeout/max_bytes hits."""
        if not self._serial:
            raise RuntimeError("SerialLink not open")
        return self._serial.read_until(expected=terminator, size=max_bytes)

    def drain_input(self) -> bytes:
        """Pull whatever is currently buffered in the OS input queue."""
        if not self._serial:
            return b""
        n = self._serial.in_waiting
        return self._serial.read(n) if n else b""

    # -- mode switching ----------------------------------------------------

    def enter_rpc_mode(self, *, banner_wait_s: float = 1.5) -> bytes:
        """
        Drop the Flipper CLI into RPC mode.

        After boot / reconnect the Flipper is in interactive CLI mode and
        emits a welcome banner. We:
          1. flush whatever is in the buffer
          2. send CR to force a prompt
          3. wait for ">: "
          4. send "start_rpc_session\\r"
          5. drain residual CLI text — after this point the stream is pure
             protobuf frames and the RPC codec takes over.

        Returns the raw banner text captured, for debugging.
        """
        self.drain_input()
        self.write(b"\r")
        # Give the firmware a beat to respond with its prompt.
        deadline = time.monotonic() + banner_wait_s
        banner = bytearray()
        while time.monotonic() < deadline:
            chunk = self.read(256)
            if chunk:
                banner.extend(chunk)
                if CLI_PROMPT in banner:
                    break
            else:
                time.sleep(0.02)

        self.write(RPC_START_COMMAND)
        # After start_rpc_session the firmware prints a short ack, then
        # switches to binary. Drain anything remaining for ~150ms.
        drain_deadline = time.monotonic() + 0.15
        while time.monotonic() < drain_deadline:
            chunk = self.drain_input()
            if chunk:
                banner.extend(chunk)
            time.sleep(0.02)
        return bytes(banner)
