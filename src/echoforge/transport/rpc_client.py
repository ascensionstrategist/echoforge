"""
RPC client for Flipper Zero.

Layers on top of SerialLink + RpcCodec:
  - assigns monotonic command IDs
  - runs a background reader thread that dispatches responses to waiters
  - supports multi-frame responses (has_next=True) by accumulating until
    the last frame, then delivering as a list of PB.Main
  - surfaces CommandStatus errors as RpcError exceptions

Every Flipper request gets a command_id. The reader correlates replies by
that id and hands them to the blocking `request()` caller. Unsolicited
frames (command_id == 0 — broadcasts like gui screen streams) are routed
through `on_unsolicited` if the caller registers a handler.
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from typing import Callable, Optional

from echoforge.proto import flipper_pb2
from echoforge.transport.rpc_codec import FrameError, RpcCodec
from echoforge.transport.serial_link import SerialLink

log = logging.getLogger(__name__)


class RpcError(RuntimeError):
    """Flipper returned a non-OK CommandStatus (or the transport died)."""

    def __init__(self, status: int, status_name: str, context: str = ""):
        self.status = status
        self.status_name = status_name
        msg = f"{status_name} ({status})"
        if context:
            msg = f"{context}: {msg}"
        super().__init__(msg)


class _PendingRequest:
    __slots__ = ("event", "frames", "error")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.frames: list[flipper_pb2.Main] = []
        self.error: Optional[BaseException] = None


class RpcClient:
    """Request/response RPC client with a single background reader.

    Usage:
        link = SerialLink(port)
        link.open()
        link.enter_rpc_mode()
        client = RpcClient(link)
        client.start()
        try:
            reply = client.request(main)  # PB.Main request → list[PB.Main]
        finally:
            client.stop()
    """

    # First 9 ids are reserved by the firmware for notifications — start at 10.
    _ID_START = 10

    def __init__(
        self,
        link: SerialLink,
        *,
        default_timeout_s: float = 5.0,
        on_unsolicited: Optional[Callable[[flipper_pb2.Main], None]] = None,
    ):
        self._link = link
        self._codec = RpcCodec(read_fn=link.read, write_fn=link.write)
        self._default_timeout = default_timeout_s
        self._on_unsolicited = on_unsolicited

        self._ids = itertools.count(self._ID_START)
        self._pending: dict[int, _PendingRequest] = {}
        self._pending_lock = threading.Lock()

        self._reader_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._reader_thread is not None:
            return
        self._stop.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="echoforge-rpc-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Closing the link unblocks a blocking read() in the reader thread.
        try:
            self._link.close()
        except Exception:
            pass
        if self._reader_thread:
            self._reader_thread.join(timeout=1.5)
            self._reader_thread = None
        # Fail any in-flight requests so callers don't hang.
        with self._pending_lock:
            for pending in self._pending.values():
                pending.error = RuntimeError("RpcClient stopped")
                pending.event.set()
            self._pending.clear()

    # -- request/response --------------------------------------------------

    def request(
        self,
        main: flipper_pb2.Main,
        *,
        timeout_s: Optional[float] = None,
    ) -> list[flipper_pb2.Main]:
        """
        Send a single-frame request and block for the response.

        The caller fills exactly one oneof on `main`. `command_id` and
        `has_next` are assigned here.
        """
        main.has_next = False
        return self.stream_request([main], timeout_s=timeout_s)

    def stream_request(
        self,
        frames: list[flipper_pb2.Main],
        *,
        timeout_s: Optional[float] = None,
    ) -> list[flipper_pb2.Main]:
        """
        Send a multi-frame request (chunked writes, tar extract, etc.).

        All supplied `frames` share one command_id; the caller is
        responsible for setting `has_next=True` on every frame except the
        last. This method overwrites `command_id` on all frames.

        Returns the ordered list of response frames for the shared id.
        """
        if not frames:
            raise ValueError("stream_request requires at least one frame")
        command_id = next(self._ids)
        pending = _PendingRequest()

        for f in frames:
            f.command_id = command_id

        with self._pending_lock:
            self._pending[command_id] = pending

        try:
            for f in frames:
                self._codec.write_main(f)
            timeout = timeout_s if timeout_s is not None else self._default_timeout
            if not pending.event.wait(timeout):
                raise TimeoutError(
                    f"Flipper RPC timed out after {timeout}s (cmd {command_id})"
                )
            if pending.error:
                raise pending.error
            return pending.frames
        finally:
            with self._pending_lock:
                self._pending.pop(command_id, None)

    # -- reader ------------------------------------------------------------

    def _reader_loop(self) -> None:
        log.debug("reader thread started")
        while not self._stop.is_set():
            try:
                frame = self._codec.read_main()
            except FrameError as exc:
                log.warning("frame decode failed: %s — resyncing by dropping 1 byte", exc)
                # Best-effort desync recovery: the codec's rolling buffer
                # is already empty after a FrameError, so just continue.
                continue
            except Exception as exc:
                if self._stop.is_set():
                    break
                log.error("reader I/O error: %s", exc)
                # Fail all pending and exit.
                with self._pending_lock:
                    for p in self._pending.values():
                        p.error = exc
                        p.event.set()
                    self._pending.clear()
                break

            if frame is None:
                # EOF — link closed.
                break

            self._dispatch(frame)
        log.debug("reader thread exiting")

    def _dispatch(self, frame: flipper_pb2.Main) -> None:
        cmd_id = frame.command_id
        if cmd_id == 0:
            # Unsolicited notification (e.g. gui screen stream).
            if self._on_unsolicited:
                try:
                    self._on_unsolicited(frame)
                except Exception as exc:
                    log.warning("unsolicited handler raised: %s", exc)
            return

        with self._pending_lock:
            pending = self._pending.get(cmd_id)
        if pending is None:
            log.warning("unmatched response for command_id=%s", cmd_id)
            return

        pending.frames.append(frame)
        if frame.has_next:
            # Keep accumulating.
            return

        # Final frame — check status.
        if frame.command_status != flipper_pb2.CommandStatus.OK:
            status_name = flipper_pb2.CommandStatus.Name(frame.command_status)
            pending.error = RpcError(frame.command_status, status_name)
        pending.event.set()


__all__ = ["RpcClient", "RpcError"]
