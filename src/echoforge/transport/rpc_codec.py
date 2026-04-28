"""
Protobuf frame codec for Flipper Zero RPC.

Flipper RPC uses Google's varint-length-prefixed delimited protobuf framing
(the same format as `Message.writeDelimitedTo()` in Java / `_EncodeVarint`
in Python protobuf). Every frame is:

    [varint(len)] [protobuf bytes of PB.Main]

The codec is transport-agnostic: it reads bytes via any callable
`read(n) -> bytes` and writes via `write(bytes) -> None`.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from google.protobuf.internal.decoder import _DecodeVarint32  # type: ignore[attr-defined]
from google.protobuf.internal.encoder import _VarintBytes  # type: ignore[attr-defined]

from echoforge.proto import flipper_pb2

log = logging.getLogger(__name__)


class FrameError(RuntimeError):
    """Raised when an RPC frame cannot be decoded."""


class RpcCodec:
    """Encode/decode Flipper RPC protobuf frames over any byte stream.

    Thread-safety: `write_main` is internally locked so multiple threads can
    submit frames. `read_main` must only be called from a single reader
    thread — the RpcClient enforces that.
    """

    # Flipper frames in practice stay under a few KB; cap at 1 MiB as a
    # safety rail against a desynced stream claiming an absurd length.
    MAX_FRAME_BYTES = 1 << 20

    def __init__(
        self,
        read_fn: Callable[[int], bytes],
        write_fn: Callable[[bytes], None],
    ):
        self._read = read_fn
        self._write = write_fn
        self._write_lock = threading.Lock()
        # Rolling buffer for varint decode — varints are 1-5 bytes and we
        # need to peek before committing. We refill from the byte stream.
        self._rx_buf = bytearray()

    # -- write -------------------------------------------------------------

    def write_main(self, main: flipper_pb2.Main) -> None:
        """Serialize a PB.Main message and push it onto the wire."""
        payload = main.SerializeToString()
        frame = _VarintBytes(len(payload)) + payload
        with self._write_lock:
            self._write(frame)

    # -- read --------------------------------------------------------------

    def read_main(self) -> Optional[flipper_pb2.Main]:
        """Block until one full PB.Main frame arrives. Returns None on EOF."""
        length = self._read_varint()
        if length is None:
            return None
        if length == 0:
            # Zero-length frames occasionally appear as keepalives; skip.
            return self.read_main()
        if length > self.MAX_FRAME_BYTES:
            raise FrameError(f"refusing {length}-byte frame (max {self.MAX_FRAME_BYTES})")

        payload = self._read_exact(length)
        if payload is None:
            return None
        main = flipper_pb2.Main()
        try:
            main.ParseFromString(payload)
        except Exception as exc:  # protobuf.DecodeError
            raise FrameError(f"protobuf decode failed: {exc}") from exc
        return main

    # -- internals ---------------------------------------------------------

    def _read_varint(self) -> Optional[int]:
        """Consume bytes until a full varint is decoded. None on EOF."""
        # Varints are at most 10 bytes; in practice Flipper lengths are 1-3.
        # Pull bytes one at a time until the continuation bit clears.
        while True:
            try:
                value, consumed = _DecodeVarint32(bytes(self._rx_buf), 0)
            except IndexError:
                # Not enough bytes yet — pull more.
                chunk = self._read(1)
                if not chunk:
                    return None
                self._rx_buf.extend(chunk)
                continue
            # Successfully decoded — drop consumed bytes from buffer.
            del self._rx_buf[:consumed]
            return value

    def _read_exact(self, n: int) -> Optional[bytes]:
        """Read exactly n bytes, draining the rolling buffer first."""
        out = bytearray()
        if self._rx_buf:
            take = min(n, len(self._rx_buf))
            out.extend(self._rx_buf[:take])
            del self._rx_buf[:take]
            n -= take
        while n > 0:
            chunk = self._read(n)
            if not chunk:
                # EOF before full payload — treat as disconnection.
                return None
            out.extend(chunk)
            n -= len(chunk)
        return bytes(out)
