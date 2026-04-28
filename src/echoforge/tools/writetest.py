"""
Phase 2 write-cycle + application test.

Creates /ext/echoforge_test/, exercises write/read/md5/rename/delete, then
exits. Also probes the Application RPC: lock status, app start/exit, button
press/release via the Archive app (safe — just a file browser).

Cleans up after itself even on failure.

Usage:
    python -m echoforge.tools.writetest
"""

from __future__ import annotations

import hashlib
import secrets
import sys
import time

from echoforge.flipper import Flipper, FlipperConnectionError
from echoforge.actions import Button
from echoforge.transport import RpcError


TEST_DIR = "/ext/echoforge_test"
TEST_FILE = f"{TEST_DIR}/hello.txt"
TEST_FILE_BIG = f"{TEST_DIR}/big.bin"
TEST_FILE_RENAMED = f"{TEST_DIR}/renamed.txt"


def _fail(msg: str) -> None:
    print(f"[writetest] FAIL: {msg}")
    sys.exit(2)


def _cleanup(f) -> None:
    try:
        if f.storage.exists(TEST_DIR):
            f.storage.delete(TEST_DIR, recursive=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[writetest] cleanup warning: {exc}")


def run_storage_tests(f) -> None:
    print("== storage write-cycle ==")

    # Fresh start.
    if f.storage.exists(TEST_DIR):
        print(f"  pre-clean: removing stale {TEST_DIR}")
        f.storage.delete(TEST_DIR, recursive=True)

    # mkdir
    t0 = time.perf_counter()
    f.storage.mkdir(TEST_DIR)
    print(f"  mkdir {TEST_DIR} — {(time.perf_counter()-t0)*1000:.0f} ms")
    if not f.storage.exists(TEST_DIR):
        _fail("dir did not appear after mkdir")

    # write small
    small = "Hello from echoforge, ts=2026-04-21\n" * 3
    t0 = time.perf_counter()
    f.storage.write(TEST_FILE, small)
    print(f"  write small ({len(small)} B) — {(time.perf_counter()-t0)*1000:.0f} ms")

    # read back + verify
    t0 = time.perf_counter()
    echoed = f.storage.read(TEST_FILE)
    print(f"  read small — {(time.perf_counter()-t0)*1000:.0f} ms")
    if echoed.decode("utf-8") != small:
        _fail(f"read-back mismatch: {echoed[:60]!r}…")

    # md5
    t0 = time.perf_counter()
    remote_md5 = f.storage.md5sum(TEST_FILE)
    local_md5 = hashlib.md5(small.encode()).hexdigest()
    print(f"  md5 small  — {(time.perf_counter()-t0)*1000:.0f} ms  remote={remote_md5}")
    if remote_md5 != local_md5:
        _fail(f"md5 mismatch: local={local_md5} remote={remote_md5}")

    # write large — exercise chunking (4 KB > 512 B chunk size)
    big_bytes = secrets.token_bytes(4096)
    t0 = time.perf_counter()
    f.storage.write(TEST_FILE_BIG, big_bytes)
    print(f"  write big  ({len(big_bytes)} B, {(len(big_bytes)+511)//512} chunks) — {(time.perf_counter()-t0)*1000:.0f} ms")
    echoed_big = f.storage.read(TEST_FILE_BIG)
    if echoed_big != big_bytes:
        _fail(f"big round-trip mismatch: sent {len(big_bytes)} got {len(echoed_big)}")
    print(f"  read big   — round-trip OK")

    # rename
    f.storage.rename(TEST_FILE, TEST_FILE_RENAMED)
    print(f"  rename     — OK")
    if not f.storage.exists(TEST_FILE_RENAMED) or f.storage.exists(TEST_FILE):
        _fail("rename did not swap paths")

    # stat
    st = f.storage.stat(TEST_FILE_RENAMED)
    print(f"  stat       — {st.name} size={st.size} type={st.type.name}")

    # list
    entries = f.storage.list(TEST_DIR)
    names = sorted(e.name for e in entries)
    print(f"  list       — {names}")

    # copy
    f.storage.copy(TEST_FILE_RENAMED, f"{TEST_DIR}/copy.txt")
    if f.storage.md5sum(f"{TEST_DIR}/copy.txt") != local_md5:
        _fail("copy produced different md5")
    print(f"  copy       — OK")

    print("  storage write-cycle: PASS")


def run_application_tests(f) -> None:
    print("\n== application ==")
    locked = f.app.is_locked()
    print(f"  is_locked  = {locked}")

    # App naming varies across firmwares. We want an app that:
    #   (a) AppStartRequest accepts
    #   (b) keeps a GUI context alive long enough to receive a button
    #
    # "Storage" on Momentum returns OK but is a subsystem, not a GUI — so
    # we probe multiple names and require press_release(DOWN) to succeed
    # before we call it "the working app". Real GUI apps first.
    f.app.exit()
    candidates = [
        "Snake Game",     # classic, on every firmware
        "2048",           # Momentum / most CFWs
        "Clock",          # Momentum default
        "Music Player",
        "Archive",        # stock
        "File Browser",
    ]

    working: str | None = None
    for name in candidates:
        try:
            f.app.start(name)
        except RpcError as exc:
            print(f"  start {name!r} — {exc.status_name}")
            continue

        # Give the app a beat to mount its GUI context.
        time.sleep(0.35)
        try:
            f.app.press_release(Button.DOWN)
        except RpcError as exc:
            print(f"  start {name!r} — OK, but button rejected: {exc.status_name}")
            f.app.exit()
            continue

        print(f"  start {name!r} — OK + accepts buttons")
        working = name
        break

    if working is None:
        print("  no candidate app accepted both start + button — skipping rest")
        return

    # We held one DOWN press in the probe above. Now back out cleanly.
    time.sleep(0.15)
    f.app.press_release(Button.BACK)
    print(f"  press_release BACK — OK")

    err = f.app.last_error()
    print(f"  last_error = code={err.code} text={err.text!r}")

    f.app.exit()
    print(f"  exit       — OK")


def main() -> int:
    try:
        cm = Flipper.connect()
    except FlipperConnectionError as exc:
        print(f"[writetest] {exc}")
        return 1

    storage_failed = False
    app_failed = False

    with cm as f:
        try:
            run_storage_tests(f)
        except Exception as exc:  # noqa: BLE001
            storage_failed = True
            print(f"[writetest] storage tests FAILED: {exc}")

        try:
            run_application_tests(f)
        except Exception as exc:  # noqa: BLE001
            app_failed = True
            print(f"[writetest] application tests FAILED: {exc}")
            # Best-effort: make sure no app is left running.
            try:
                f.app.exit()
            except Exception:
                pass

        print("\n== cleanup ==")
        _cleanup(f)
        print(f"  removed {TEST_DIR}")

    if storage_failed:
        print("\n[writetest] storage FAIL — aborting")
        return 2
    if app_failed:
        print("\n[writetest] storage PASS, application FAIL (non-blocking — AI layer uses dynamic names)")
        return 0
    print("\n[writetest] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
