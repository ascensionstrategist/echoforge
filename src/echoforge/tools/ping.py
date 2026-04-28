"""
Phase 1 smoke test: detect the Flipper, open RPC, ping, and read device info.

Usage:
    python -m echoforge.tools.ping            # auto-detect
    python -m echoforge.tools.ping COM5       # force a port
"""

from __future__ import annotations

import logging
import os
import secrets
import sys
import time
from typing import Optional

from echoforge.proto import flipper_pb2
from echoforge.transport import (
    RpcClient,
    RpcError,
    SerialLink,
    find_flipper_port,
    list_candidate_ports,
)


def _setup_logging() -> None:
    level = os.environ.get("VESPER_LOG", "WARNING").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _resolve_port(argv: list[str]) -> Optional[str]:
    if len(argv) > 1:
        return argv[1]
    info = find_flipper_port()
    return info.device if info else None


def _print_port_preamble(port: str) -> None:
    ports = list_candidate_ports()
    if not ports:
        print(f"[ping] using {port} (no Flipper VID/PID match — make sure cable is data, not power-only)")
        return
    print(f"[ping] detected {len(ports)} Flipper candidate(s):")
    for p in ports:
        marker = "*" if p.device == port else " "
        print(f"  {marker} {p.device}  vid=0x{p.vid:04x} pid=0x{p.pid:04x}  sn={p.serial_number or '-'}")


def _do_ping(client: RpcClient) -> None:
    payload = secrets.token_bytes(16)
    main = flipper_pb2.Main()
    main.system_ping_request.data = payload
    t0 = time.perf_counter()
    frames = client.request(main, timeout_s=5.0)
    dt_ms = (time.perf_counter() - t0) * 1000

    if not frames or not frames[-1].HasField("system_ping_response"):
        print(f"[ping] ERROR: unexpected response: {frames}")
        sys.exit(2)

    echo = frames[-1].system_ping_response.data
    if echo != payload:
        print(f"[ping] ERROR: echo mismatch. sent {payload.hex()}, got {echo.hex()}")
        sys.exit(2)
    print(f"[ping] OK — 16-byte echo round-trip in {dt_ms:.1f} ms")


def _do_device_info(client: RpcClient) -> None:
    main = flipper_pb2.Main()
    main.system_device_info_request.SetInParent()
    frames = client.request(main, timeout_s=5.0)
    # DeviceInfo is streamed as multiple frames, each carrying one key/value.
    info: dict[str, str] = {}
    for f in frames:
        if f.HasField("system_device_info_response"):
            r = f.system_device_info_response
            info[r.key] = r.value
    if not info:
        print("[device_info] no keys returned")
        return

    interesting = [
        "hardware_name",
        "hardware_model",
        "hardware_ver",
        "firmware_branch",
        "firmware_version",
        "firmware_commit",
        "protobuf_version",
        "radio_firmware",
    ]
    print(f"[device_info] {len(info)} keys returned:")
    for key in interesting:
        if key in info:
            print(f"  {key}: {info[key]}")
    # Tail-dump anything we didn't flag, so nothing is hidden.
    extras = {k: v for k, v in info.items() if k not in interesting}
    if extras:
        print(f"  (+{len(extras)} more: {', '.join(sorted(extras))})")


def main() -> int:
    _setup_logging()
    port = _resolve_port(sys.argv)
    if port is None:
        print("[ping] no Flipper Zero detected on USB.")
        print("       Plug in a data-capable USB-C cable and close qFlipper if it's running.")
        return 1

    _print_port_preamble(port)
    link = SerialLink(port)
    try:
        link.open()
    except Exception as exc:
        print(f"[ping] failed to open {port}: {exc}")
        print("       If another app (qFlipper, serial monitor) owns the port, close it first.")
        return 1

    try:
        banner = link.enter_rpc_mode()
        banner_preview = banner.decode("utf-8", errors="replace").strip().splitlines()
        if banner_preview:
            print(f"[ping] CLI banner: {banner_preview[0][:80]}")
        client = RpcClient(link)
        client.start()
        try:
            _do_ping(client)
            _do_device_info(client)
        except (RpcError, TimeoutError) as exc:
            print(f"[ping] RPC failure: {exc}")
            return 2
        finally:
            client.stop()
    finally:
        link.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
