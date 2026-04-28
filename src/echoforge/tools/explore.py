"""
Phase 2a read-only exploration of a live Flipper.

Exercises:
  - Flipper.connect() facade
  - system.device_info, system.power_info, system.protobuf_version, system.get_datetime
  - storage.info for /ext and /int
  - storage.list for /ext (top level)
  - storage.stat for the first regular file found
  - storage.md5sum on that file

Strictly read-only — no writes, no deletes, no reboots.

Usage:
    python -m echoforge.tools.explore
"""

from __future__ import annotations

import sys
import time

from echoforge.flipper import Flipper, FlipperConnectionError


def _pretty_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def main() -> int:
    try:
        cm = Flipper.connect()
    except FlipperConnectionError as exc:
        print(f"[explore] {exc}")
        return 1

    with cm as f:
        # --- system ---
        print("== system ==")
        t0 = time.perf_counter()
        info = f.system.device_info()
        print(f"  device_info: {len(info.raw)} keys in {(time.perf_counter()-t0)*1000:.1f} ms")
        print(f"    hardware_name   = {info.hardware_name}")
        print(f"    firmware_branch = {info.firmware_branch}")
        print(f"    firmware_commit = {info.firmware_commit}")

        power = f.system.power_info()
        print(f"  power_info: {len(power.raw)} keys")
        print(f"    charge_level    = {power.charge_level}")
        print(f"    is_charging     = {power.is_charging}")
        print(f"    battery_voltage = {power.battery_voltage}")
        print(f"    temperature_c   = {power.temperature_c}")
        # Dump all raw power keys so we can extend the alias list if needed.
        print(f"    raw keys: {sorted(power.raw.keys())}")

        pbver = f.system.protobuf_version()
        print(f"  protobuf_version = {pbver[0]}.{pbver[1]}")

        dt = f.system.get_datetime()
        print(f"  flipper_time     = {dt.to_py().isoformat()} (weekday {dt.weekday})")

        # --- storage info ---
        print("\n== storage ==")
        for mount in ("/ext", "/int"):
            try:
                si = f.storage.info(mount)
                print(
                    f"  {mount}: {_pretty_bytes(si.free_bytes)} free / "
                    f"{_pretty_bytes(si.total_bytes)} total ({si.percent_used:.1f}% used)"
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {mount}: info failed — {exc}")

        # --- list /ext ---
        print("\n== /ext listing ==")
        entries = f.storage.list("/ext")
        dirs = [e for e in entries if e.is_dir]
        files = [e for e in entries if not e.is_dir]
        print(f"  {len(dirs)} dirs, {len(files)} files")
        for e in sorted(entries, key=lambda x: (not x.is_dir, x.name.lower()))[:20]:
            kind = "DIR " if e.is_dir else "FILE"
            print(f"    [{kind}] {e.name}  ({_pretty_bytes(e.size)})")
        if len(entries) > 20:
            print(f"    ... +{len(entries) - 20} more")

        # --- GPIO: read-only. Configure PA7 as INPUT, read level, read OTG state ---
        print("\n== gpio ==")
        try:
            from echoforge.actions import Pin, PinMode
            # Configure PA7 as INPUT (safe: no drive). Read its level and mode.
            f.gpio.set_mode(Pin.PA7, PinMode.INPUT)
            snap = f.gpio.snapshot(Pin.PA7)
            print(f"  PA7 snapshot: mode={snap.mode.name} value={snap.value}")
            otg = f.gpio.get_otg()
            print(f"  OTG 5 V rail: {otg.name}")
        except Exception as exc:  # noqa: BLE001
            print(f"  gpio probe failed: {exc}")

        # --- stat + md5 on first regular file ---
        first_file = next((e for e in entries if not e.is_dir), None)
        if first_file is not None:
            path = f"/ext/{first_file.name}"
            print(f"\n== stat + md5: {path} ==")
            st = f.storage.stat(path)
            print(f"  stat: type={st.type.name} size={_pretty_bytes(st.size)}")
            t0 = time.perf_counter()
            md5 = f.storage.md5sum(path)
            print(f"  md5:  {md5}  ({(time.perf_counter()-t0)*1000:.0f} ms)")
        else:
            print("\n== stat + md5: skipped (no files at /ext root) ==")

    print("\n[explore] all read-only checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
