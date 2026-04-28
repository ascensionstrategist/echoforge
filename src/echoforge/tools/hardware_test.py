"""
Phase 2c-4 hardware smoke test.

Visible, safe actuation to validate the full Flipper.cli() helper stack:
  - LED: red, green, blue, then a 3-blink green pulse, then all off
  - Vibro: single 200 ms pulse
  - Buzzer: 200 ms tone at 880 Hz (firmware-dependent — may fail gracefully)

NO RF emission. NO file writes. NO app launches. Just peripherals you can
see and feel on your Flipper to confirm Phase 2 is end-to-end working.

Usage:
    python -m echoforge.tools.hardware_test
"""

from __future__ import annotations

import sys
import time

from echoforge.flipper import Flipper, FlipperConnectionError


def _step(n: int, total: int, label: str) -> None:
    print(f"[{n}/{total}] {label}")


def main() -> int:
    try:
        cm = Flipper.connect()
    except FlipperConnectionError as exc:
        print(f"[hardware_test] {exc}")
        return 1

    total = 7
    with cm as f:
        # Pre-check: RPC healthy
        _step(1, total, "RPC baseline (device_info)")
        di = f.system.device_info()
        print(f"      firmware={di.firmware_branch} commit={di.firmware_commit}")

        # LED static colors — each is one mode-switch cycle.
        _step(2, total, "LED red ON (watch your Flipper)")
        r = f.led.red(255)
        print(f"      cmd={r.command!r}  cli={r.duration_ms:.0f} ms")
        time.sleep(0.4)

        _step(3, total, "LED green ON")
        f.led.green(255)
        time.sleep(0.4)

        _step(4, total, "LED blue ON")
        f.led.blue(255)
        time.sleep(0.4)

        _step(5, total, "LED blink green x3 (watch the LED strobe)")
        wall0 = time.perf_counter()
        f.led.blink("g", count=3, period_ms=120, level=255)
        wall_ms = (time.perf_counter() - wall0) * 1000
        print(f"      3 blinks took {wall_ms:.0f} ms ({wall_ms/6:.0f} ms per state change)")
        f.led.off()

        # Vibro — 200 ms pulse
        _step(6, total, "Vibro pulse 200 ms (feel it)")
        try:
            f.vibro.pulse(duration_ms=200)
            print(f"      vibro pulse OK")
        except Exception as exc:  # noqa: BLE001
            print(f"      vibro skipped: {exc}")

        # Buzzer — may fail on firmwares without a tone CLI
        _step(7, total, "Buzzer tone 880 Hz for 200 ms (listen)")
        try:
            ack = f.buzzer.play(frequency_hz=880, duration_ms=200)
            print(f"      buzzer OK — cmd={ack.command!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"      buzzer skipped: {str(exc)[:100]}")

        # Post-check: RPC still healthy after all CLI round-trips
        print()
        print("[post] RPC after 8+ CLI round-trips ...")
        echo = f.system.ping(b"post-cli")
        assert echo == b"post-cli", f"ping mismatch: {echo!r}"
        print("      ping round-trip OK — RPC re-attach survived all mode switches")

    print("\n[hardware_test] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
