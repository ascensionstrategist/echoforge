"""Tests for `_with_recovery`'s Phase 4.5a idle-ping guard.

`_with_recovery` wraps every tool RPC. If the Flipper has been idle
longer than `_WITH_RECOVERY_IDLE_PING_S`, it should do a cheap
proactive ping BEFORE the real call to warm the USB-CDC session. On
success, the real call proceeds. On ping failure, the wrapper
reconnects, then runs the real call.

These tests use a fake Flipper with a counter so we can assert on the
exact sequence: ping → request, ping-fail → reconnect → request, no
idle → no ping. No real serial required.
"""

from __future__ import annotations

from typing import Any

from echoforge.agent.tools import _WITH_RECOVERY_IDLE_PING_S, _with_recovery


class _FakeFlipper:
    """Fake Flipper that implements just the surface `_with_recovery` hits."""

    def __init__(
        self,
        *,
        idle: float,
        ping_raises: BaseException | None = None,
        reconnect_raises: BaseException | None = None,
    ):
        self._idle = idle
        self._ping_raises = ping_raises
        self._reconnect_raises = reconnect_raises
        self.ping_calls = 0
        self.reconnect_calls = 0

    def idle_seconds(self) -> float:
        return self._idle

    def proactive_ping(self, *, timeout_s: float = 2.0) -> None:
        self.ping_calls += 1
        if self._ping_raises is not None:
            raise self._ping_raises
        # A successful ping "warms" the link — the test simulates this
        # by dropping idle to 0 so subsequent checks see a live session.
        self._idle = 0.0

    def reconnect(self) -> None:
        self.reconnect_calls += 1
        if self._reconnect_raises is not None:
            raise self._reconnect_raises
        self._idle = 0.0


def _ok_fn_factory():
    """Produce a tool-body callable that counts its invocations and
    returns a minimal _ok-shaped response."""
    state = {"calls": 0}

    def fn() -> dict[str, Any]:
        state["calls"] += 1
        return {"content": [{"type": "text", "text": "ok"}]}

    return fn, state


class TestIdlePingGuard:
    def test_no_ping_when_session_is_fresh(self):
        """Idle < threshold: the wrapper must not spend RPC on a ping."""
        f = _FakeFlipper(idle=1.0)  # well under threshold
        fn, state = _ok_fn_factory()
        res = _with_recovery(f, fn)
        assert "content" in res and not res.get("isError")
        assert f.ping_calls == 0
        assert f.reconnect_calls == 0
        assert state["calls"] == 1

    def test_ping_fires_after_idle_threshold(self):
        """Idle > threshold: one ping, then the real call — no reconnect."""
        f = _FakeFlipper(idle=_WITH_RECOVERY_IDLE_PING_S + 5.0)
        fn, state = _ok_fn_factory()
        res = _with_recovery(f, fn)
        assert not res.get("isError")
        assert f.ping_calls == 1
        assert f.reconnect_calls == 0
        assert state["calls"] == 1

    def test_ping_timeout_triggers_reconnect_then_real_call(self):
        """If the proactive ping times out, the wrapper must reconnect
        BEFORE the real call (saves a full 5s RPC timeout)."""
        f = _FakeFlipper(
            idle=_WITH_RECOVERY_IDLE_PING_S + 5.0,
            ping_raises=TimeoutError("stale session"),
        )
        fn, state = _ok_fn_factory()
        res = _with_recovery(f, fn)
        assert not res.get("isError")
        assert f.ping_calls == 1
        assert f.reconnect_calls == 1
        assert state["calls"] == 1

    def test_ping_failure_and_reconnect_failure_returns_error(self):
        """Both pre-call ping AND reconnect fail — user sees a clean
        error, not a stack trace or a successful-looking response."""
        f = _FakeFlipper(
            idle=_WITH_RECOVERY_IDLE_PING_S + 5.0,
            ping_raises=TimeoutError("stale"),
            reconnect_raises=RuntimeError("USB unplugged"),
        )
        fn, state = _ok_fn_factory()
        res = _with_recovery(f, fn)
        assert res.get("isError") is True
        # Real call is NEVER reached if we can't even get a live link.
        assert state["calls"] == 0
        assert f.ping_calls == 1
        assert f.reconnect_calls == 1

    def test_threshold_is_module_constant(self):
        """Lock the threshold to its documented 10s — changes must be
        intentional and documented in tools.py near the constant."""
        assert _WITH_RECOVERY_IDLE_PING_S == 10.0

    def test_fn_timeout_still_triggers_legacy_reconnect_and_retry(self):
        """The original recovery behavior survives: if the REAL call
        times out (not the ping), reconnect once and retry."""
        # Fresh session (no pre-ping), but the real call times out once.
        f = _FakeFlipper(idle=1.0)
        state = {"calls": 0}

        def fn() -> dict[str, Any]:
            state["calls"] += 1
            if state["calls"] == 1:
                raise TimeoutError("first call stale")
            return {"content": [{"type": "text", "text": "ok"}]}

        res = _with_recovery(f, fn)
        assert not res.get("isError")
        assert state["calls"] == 2
        assert f.reconnect_calls == 1
        # No pre-ping path: idle was below threshold.
        assert f.ping_calls == 0
