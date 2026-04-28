"""
Phase 2c-3 CLI passthrough smoke test.

Exercises the RPC ↔ CLI ↔ RPC mode-switching path:
  1. Open Flipper in RPC mode, read device_info (proves RPC works)
  2. Call f.cli("help") — switches to CLI mode, runs help, returns output
  3. Call f.cli("device_info") — another CLI command for variety
  4. Verify RPC still works after CLI — read storage info
  5. All safe, read-only — no hardware actuation.

Usage:
    python -m echoforge.tools.cli_test
"""

from __future__ import annotations

import sys
import time

from echoforge.flipper import Flipper, FlipperConnectionError


def main() -> int:
    try:
        cm = Flipper.connect()
    except FlipperConnectionError as exc:
        print(f"[cli_test] {exc}")
        return 1

    with cm as f:
        # 1. RPC before — establishes baseline
        info = f.system.device_info()
        print(f"[1/4] RPC device_info OK — hardware_name={info.hardware_name!r}")

        # 2. CLI help — long output, many commands; validates prompt detection
        print("\n[2/4] f.cli('help') — switching RPC → CLI → RPC ...")
        wall0 = time.perf_counter()
        r = f.cli("help", timeout_s=5.0)
        wall_ms = (time.perf_counter() - wall0) * 1000
        print(f"  command only  : {r.duration_ms:.0f} ms (write→prompt round-trip)")
        print(f"  wall-clock    : {wall_ms:.0f} ms (full RPC→CLI→RPC mode switch)")
        print(f"  raw bytes     : {len(r.raw)}")
        print(f"  cleaned lines : {len(r.output.splitlines())}")
        # Show first 10 lines + last 3 for a sanity preview
        lines = r.output.splitlines()
        print("  --- help output (first 10 lines) ---")
        for line in lines[:10]:
            print(f"    {line}")
        if len(lines) > 13:
            print(f"    ... ({len(lines) - 13} lines) ...")
        for line in lines[-3:]:
            print(f"    {line}")

        # 3. CLI device_info — structured output
        print("\n[3/4] f.cli('device_info') ...")
        wall0 = time.perf_counter()
        r = f.cli("device_info", timeout_s=5.0)
        wall_ms = (time.perf_counter() - wall0) * 1000
        di_lines = r.output.splitlines()
        print(f"  command: {r.duration_ms:.0f} ms  wall: {wall_ms:.0f} ms  {len(di_lines)} lines")
        for line in di_lines[:6]:
            print(f"    {line}")

        # 4. RPC after — proves re-attach worked
        print("\n[4/4] RPC after CLI ...")
        si = f.storage.info("/ext")
        print(f"  storage /ext: {si.free_bytes:,} B free / {si.total_bytes:,} B total")
        ping_echo = f.system.ping(b"alive")
        print(f"  ping: echoed {ping_echo!r}")

    print("\n[cli_test] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
