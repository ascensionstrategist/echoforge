"""
High-level Flipper facade — single entry point for all action modules.

Typical usage:
    from echoforge.flipper import Flipper

    with Flipper.connect() as f:
        print(f.system.device_info().hardware_name)
        for entry in f.storage.list("/ext"):
            print(entry.name, entry.size)
        # One-shot CLI command (mode-switches under the hood, then restores RPC):
        print(f.cli("help").output)
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Iterator, Optional

from echoforge.actions import Application, Storage, System
from echoforge.actions.gpio import Gpio
from echoforge.actions.hardware import BadUsb, Buzzer, Emulate, Infrared, Led, SubGhz, Vibro
from echoforge.transport import (
    ClientProxy,
    RpcClient,
    SerialLink,
    find_flipper_port,
    list_candidate_ports,
)
from echoforge.transport.cli_session import CliResult, CliSession  # noqa: F401 — CliSession re-exported for cli_session() users

log = logging.getLogger(__name__)


class FlipperConnectionError(RuntimeError):
    """Raised when auto-detect fails or the port can't be opened."""


class Flipper:
    """Composes SerialLink + RpcClient + action modules, with transparent
    RPC ↔ CLI mode switching for commands that have no native protobuf."""

    # Time to wait after closing the port before reopening. Windows can
    # hold the handle briefly after close(); 150 ms is conservative.
    REOPEN_DELAY_S = 0.15

    # Send a ping this often when nothing else is happening. Prevents the
    # Flipper firmware from going idle-asleep during long Claude thinks
    # (~15-30s of RPC silence is common mid-agent-loop).
    #
    # Phase 4.5a: tightened from 15.0s to 5.0s. At 15s, Claude-think
    # intervals of 10-12s were slipping past the keepalive window and
    # stale-ing the USB-CDC session on the NEXT tool call, forcing
    # `_with_recovery` to pay a 300-500ms reconnect penalty. Pings are
    # ~8 bytes over USB-CDC; 3x the rate is a trivial cost vs. the
    # human-visible stall. See tests/test_flipper.py for the lock-in.
    KEEPALIVE_INTERVAL_S = 5.0

    def __init__(
        self,
        link: SerialLink,
        client: RpcClient,
        *,
        rpc_timeout_s: float = 5.0,
        keepalive: bool = True,
    ):
        self._link = link
        self._client = client
        self._rpc_timeout_s = rpc_timeout_s
        # All action modules talk through this proxy. When CLI mode
        # switching replaces the client, the proxy swaps its reference
        # and the action modules continue to work unchanged.
        self._proxy = ClientProxy(client)
        self.storage = Storage(self._proxy)
        self.system = System(self._proxy)
        self.app = Application(self._proxy)
        self.gpio = Gpio(self._proxy)
        # Hardware helpers run on top of Flipper.cli() (RPC↔CLI mode switch).
        self.led = Led(self)
        self.vibro = Vibro(self)
        self.buzzer = Buzzer(self)
        self.subghz = SubGhz(self)
        self.ir = Infrared(self)
        self.emulate = Emulate(self)
        self.badusb = BadUsb(self)

        # Keep-alive plumbing.
        self._keepalive_enabled = keepalive
        self._keepalive_stop = threading.Event()
        self._keepalive_thread: Optional[threading.Thread] = None
        self._activity_lock = threading.Lock()
        self._last_activity_at = time.monotonic()
        if keepalive:
            self._start_keepalive()

    @property
    def port(self) -> str:
        return self._link.port

    # -- keep-alive --------------------------------------------------------

    def _start_keepalive(self) -> None:
        """Kick off the background pinger. No-op if already running."""
        if self._keepalive_thread is not None and self._keepalive_thread.is_alive():
            return
        self._keepalive_stop.clear()
        self._last_activity_at = time.monotonic()
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop,
            name="echoforge-keepalive",
            daemon=True,
        )
        self._keepalive_thread.start()

    def _stop_keepalive(self) -> None:
        self._keepalive_stop.set()
        t = self._keepalive_thread
        if t is not None:
            t.join(timeout=1.0)
            self._keepalive_thread = None

    def _keepalive_loop(self) -> None:
        """Send a cheap ping whenever we haven't seen activity recently.

        Uses a short-timeout ping via the System action; failures are
        logged, not raised. Stops cleanly when `_keepalive_stop` is set or
        when the proxy is detached (mid-CLI-mode switch)."""
        from echoforge.proto import flipper_pb2  # deferred to avoid init cost

        while not self._keepalive_stop.wait(1.0):
            try:
                idle = time.monotonic() - self._last_activity_at
            except Exception:  # noqa: BLE001
                continue
            if idle < self.KEEPALIVE_INTERVAL_S:
                continue

            try:
                main = flipper_pb2.Main()
                main.system_ping_request.data = b"\x01"
                # Use request() with a tight timeout — we don't want to
                # hang the keepalive on a bad link.
                self._proxy.request(main, timeout_s=2.5)
                with self._activity_lock:
                    self._last_activity_at = time.monotonic()
            except RuntimeError:
                # Proxy detached during a CLI mode switch — skip this tick.
                continue
            except Exception as exc:  # noqa: BLE001
                log.debug("keepalive ping failed: %s", exc)
                # Don't update activity; next tick will retry.

    def mark_activity(self) -> None:
        """Tool handlers call this after successful RPC to suppress the
        next scheduled ping. Opportunistic — missing a call is harmless."""
        with self._activity_lock:
            self._last_activity_at = time.monotonic()

    def idle_seconds(self) -> float:
        """Seconds since the last known RPC activity (ping or tool call).

        Used by the agent-runtime `_with_recovery` to decide whether to
        do a proactive pre-call ping before a real tool RPC (Phase 4.5a).
        """
        with self._activity_lock:
            return time.monotonic() - self._last_activity_at

    def proactive_ping(self, *, timeout_s: float = 2.0) -> None:
        """Send a tight-timeout ping to warm the USB-CDC session.

        Raises TimeoutError (or the underlying RPC error) on failure —
        caller decides whether to reconnect. On success updates the
        activity clock so the next idle-check sees a fresh session.
        """
        from echoforge.proto import flipper_pb2  # deferred — same as keepalive

        main = flipper_pb2.Main()
        main.system_ping_request.data = b"\x02"  # distinct from keepalive tag
        self._proxy.request(main, timeout_s=timeout_s)
        with self._activity_lock:
            self._last_activity_at = time.monotonic()

    # -- CLI passthrough ---------------------------------------------------

    @contextmanager
    def cli_session(self, *, timeout_s: float = 5.0) -> "Iterator[CliSession]":
        """
        Hold the Flipper in CLI mode for a batch of commands. One mode
        switch (RPC→CLI) on entry, one (CLI→RPC) on exit — use when you
        need to fire several CLI commands rapidly (LED blink, tone
        sequences, setup scripts).

        Usage:
            with f.cli_session() as cli:
                cli.run("led r 255")
                time.sleep(0.1)
                cli.run("led r 0")

        The yielded `CliSession` is a raw object — no auto-mode-switching,
        no RPC in-between. For one-off calls with RPC retained between
        them, use `f.cli(command)` instead.
        """
        port = self._link.port
        # 1. Tear down RPC side.
        self._proxy._clear()
        try:
            self._client.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("RpcClient.stop() raised during cli_session(): %s", exc)
        try:
            self._link.close()
        except Exception:
            pass
        time.sleep(self.REOPEN_DELAY_S)

        # 2. Open a fresh serial in CLI mode and wait for the first prompt.
        cli_link = SerialLink(port, timeout=timeout_s)
        cli_link.open()
        time.sleep(0.05)
        session = CliSession(cli_link)
        session._wait_for_prompt()

        try:
            yield session
        finally:
            try:
                cli_link.close()
            except Exception:
                pass
            time.sleep(self.REOPEN_DELAY_S)
            try:
                self._reattach_rpc(port)
            except Exception as reattach_exc:
                raise RuntimeError(
                    f"Failed to restore RPC after cli_session: {reattach_exc}"
                ) from reattach_exc

    def cli(self, command: str, *, timeout_s: float = 5.0) -> CliResult:
        """
        Temporarily switch to CLI mode, run `command`, restore RPC mode.

        Cost: ~250–400 ms of mode switching on top of the command itself.
        Use for operations that have no native protobuf RPC (LED, vibro,
        subghz tx/rx, ir tx/rx, nfc/rfid/ibutton emulate, badusb run).

        Returns a `CliResult` with .output (cleaned text) and .duration_ms.
        If RPC re-attach fails after the CLI exchange, a RuntimeError is
        raised — the Flipper object should be considered dead and you
        should open a fresh `Flipper.connect()`.
        """
        port = self._link.port
        # 0. Suspend keep-alive — we're about to close the RPC side.
        self._stop_keepalive()
        # 1. Tear down RPC side. Any in-flight RPC requests fail fast.
        self._proxy._clear()
        try:
            self._client.stop()
        except Exception as exc:  # noqa: BLE001
            log.warning("RpcClient.stop() raised during cli(): %s", exc)
        # SerialLink.close is called by stop(); be defensive.
        try:
            self._link.close()
        except Exception:
            pass

        # Windows sometimes needs a beat before the port can be reopened.
        time.sleep(self.REOPEN_DELAY_S)

        # 2. Run the CLI exchange on a fresh link.
        cli_err: Optional[BaseException] = None
        result: Optional[CliResult] = None
        try:
            result = CliSession.exchange(port, command, command_timeout_s=timeout_s)
        except BaseException as exc:  # noqa: BLE001
            cli_err = exc

        # 3. Re-attach RPC even if CLI failed. If re-attach fails we raise
        # a fresh error (CLI error is logged but not re-raised, to make the
        # failure surface unambiguous).
        time.sleep(self.REOPEN_DELAY_S)
        try:
            self._reattach_rpc(port)
        except Exception as reattach_exc:
            if cli_err:
                log.error("CLI also failed: %s", cli_err)
            raise RuntimeError(
                f"Failed to restore RPC after CLI command {command!r}: {reattach_exc}"
            ) from reattach_exc

        if cli_err:
            raise cli_err
        assert result is not None
        return result

    def _reattach_rpc(self, port: str) -> None:
        """Rebuild SerialLink + RpcClient (with ping-verify retry), swap
        the proxy reference to the new client."""
        new_link, new_client = _open_and_verify(
            port, self._rpc_timeout_s, verify_attempts=3
        )
        self._link = new_link
        self._client = new_client
        self._proxy._set(new_client)
        # Resume keep-alive now that RPC is live again.
        if self._keepalive_enabled:
            self._start_keepalive()

    def reconnect(self) -> None:
        """Close everything and reopen. Use after a TimeoutError to recover
        from a stale RPC session or a USB-level sleep/suspend."""
        port = self._link.port
        self._stop_keepalive()
        try:
            self._proxy._clear()
        except Exception:
            pass
        try:
            self._client.stop()
        except Exception:
            pass
        try:
            self._link.close()
        except Exception:
            pass
        time.sleep(self.REOPEN_DELAY_S)
        self._reattach_rpc(port)

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Stop the RPC reader, keep-alive, and close the serial. Idempotent."""
        self._stop_keepalive()
        try:
            self._proxy._clear()
        except Exception:
            pass
        try:
            self._client.stop()
        except Exception:
            pass
        try:
            self._link.close()
        except Exception:
            pass

    # -- construction ------------------------------------------------------

    @classmethod
    @contextmanager
    def connect(
        cls,
        port: Optional[str] = None,
        *,
        rpc_timeout_s: float = 5.0,
        verify_attempts: int = 3,
    ) -> "Iterator[Flipper]":
        """
        Auto-detect (or use `port=`) and return an open Flipper as a context
        manager. Guarantees the RPC session is live before returning — sends
        a probe ping and, if it fails, does a full close/reopen up to
        `verify_attempts` times. This catches the common case where the
        first RPC after a fresh enter_rpc_mode races the firmware's
        mode-switch.

        Cleanup is safe even after internal link/client swaps caused by
        `cli()` mode switching because the facade retains current refs.
        """
        if port is None:
            info = find_flipper_port()
            if info is None:
                candidates = list_candidate_ports()
                if candidates:
                    raise FlipperConnectionError(
                        f"multiple Flippers visible ({[c.device for c in candidates]}); "
                        "pass port= explicitly"
                    )
                raise FlipperConnectionError("no Flipper Zero detected on USB")
            port = info.device

        link, client = _open_and_verify(port, rpc_timeout_s, verify_attempts)

        flipper = cls(link, client, rpc_timeout_s=rpc_timeout_s)
        try:
            yield flipper
        finally:
            # IMPORTANT: use the facade's CURRENT refs, not the ones we
            # captured at entry — they may have been swapped by cli().
            flipper.close()


def _open_and_verify(
    port: str,
    rpc_timeout_s: float,
    verify_attempts: int,
) -> tuple[SerialLink, RpcClient]:
    """Open the port, enter RPC, and verify with a ping. Retries the whole
    sequence on failure — cheap enough (~300 ms per attempt) and fixes the
    common 'first RPC after mode-switch gets dropped' race.

    Returns (link, client) on success; raises FlipperConnectionError after
    `verify_attempts` failures.
    """
    from echoforge.proto import flipper_pb2

    last_error: Optional[BaseException] = None
    for attempt in range(1, verify_attempts + 1):
        link: Optional[SerialLink] = None
        client: Optional[RpcClient] = None
        try:
            link = SerialLink(port)
            link.open()
            link.enter_rpc_mode()
            client = RpcClient(link, default_timeout_s=rpc_timeout_s)
            client.start()

            # Probe ping — proves RPC reader + firmware are both alive.
            probe = flipper_pb2.Main()
            probe.system_ping_request.data = b"init"
            client.request(probe, timeout_s=3.0)
            return link, client
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.warning(
                "Flipper.connect probe attempt %d/%d failed: %s",
                attempt, verify_attempts, exc,
            )
            # Clean up before retrying.
            if client is not None:
                try:
                    client.stop()
                except Exception:
                    pass
            if link is not None:
                try:
                    link.close()
                except Exception:
                    pass
            if attempt < verify_attempts:
                time.sleep(Flipper.REOPEN_DELAY_S)

    raise FlipperConnectionError(
        f"RPC handshake to {port} failed after {verify_attempts} attempts: {last_error}"
    )
