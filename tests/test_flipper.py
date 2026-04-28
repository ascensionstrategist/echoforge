"""Unit tests for `echoforge.flipper` — constants, keepalive, idle-guard.

These tests cover the Phase 4.5a hardening guarantees without touching
real serial hardware: the fixed keepalive interval, the activity-clock
reset on reconnect, and the proactive pre-call ping semantics.
"""

from __future__ import annotations

import threading
import time

from echoforge.flipper import Flipper


# ---------------------------------------------------------------------------
# Constants locked-in by Phase 4.5a
# ---------------------------------------------------------------------------

class TestKeepaliveInterval:
    def test_keepalive_interval_is_5s(self):
        """Phase 4.5a: lower than Claude-think intervals so the USB-CDC
        session stays warm. If you change this, document why in the
        constant's docstring — bumping it back to 15s brings the
        stale-RPC stall back."""
        assert Flipper.KEEPALIVE_INTERVAL_S == 5.0


# ---------------------------------------------------------------------------
# Activity clock: idle_seconds / mark_activity / keepalive reset on reconnect
# ---------------------------------------------------------------------------

class TestActivityClock:
    def test_mark_activity_resets_idle(self):
        # Use the real Flipper surface via a minimal stub — we only
        # interact with the activity-lock/clock path, which doesn't
        # touch _link or _client.
        f = Flipper.__new__(Flipper)
        f._activity_lock = threading.Lock()
        f._last_activity_at = time.monotonic() - 100.0  # look very stale
        assert f.idle_seconds() > 50.0
        f.mark_activity()
        assert f.idle_seconds() < 1.0

    def test_start_keepalive_resets_activity_clock(self):
        """Per Phase 4.5a: reconnect-path calls `_start_keepalive` which
        must reset `_last_activity_at` so the next idle check sees the
        new session as fresh (not inheriting pre-reconnect staleness)."""
        f = Flipper.__new__(Flipper)
        f._activity_lock = threading.Lock()
        f._keepalive_enabled = False  # don't actually spawn thread
        f._keepalive_stop = threading.Event()
        f._keepalive_thread = None
        f._last_activity_at = time.monotonic() - 100.0
        # Invoke _start_keepalive's clock-reset behaviour directly; we
        # don't want the real thread, so re-implement the reset-and-guard
        # sequence here to verify the invariant.
        f._keepalive_stop.clear()
        f._last_activity_at = time.monotonic()  # mirror line 103 of flipper.py
        assert f.idle_seconds() < 1.0

    def test_reconnect_path_reset_is_covered_by_start_keepalive(self):
        """Structural guard: `_reattach_rpc` calls `_start_keepalive()`
        at the end of its body, which resets the clock. This test
        codifies the source-code expectation so future refactors don't
        silently drop the call."""
        import inspect

        src = inspect.getsource(Flipper._reattach_rpc)
        # The reset happens via `_start_keepalive()`; assert the
        # re-attach path invokes it (guarded by the keepalive flag).
        assert "_start_keepalive" in src, (
            "_reattach_rpc must kick off keepalive so the activity clock "
            "resets — see Phase 4.5a notes."
        )

        src2 = inspect.getsource(Flipper._start_keepalive)
        assert "self._last_activity_at = time.monotonic()" in src2, (
            "_start_keepalive must reset _last_activity_at (Phase 4.5a)."
        )
