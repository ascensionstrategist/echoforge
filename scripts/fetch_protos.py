"""
Fetch Flipper Zero protobuf definitions from the official upstream repo.

Source: https://github.com/flipperdevices/Flipper-Protobuf
Target:  ./protos/*.proto

Run: python scripts/fetch_protos.py
"""

from __future__ import annotations

import io
import sys
import urllib.request
import zipfile
from pathlib import Path

UPSTREAM_ZIP = (
    "https://github.com/flipperdevices/flipperzero-protobuf/archive/refs/heads/dev.zip"
)
TARGET_DIR = Path(__file__).resolve().parent.parent / "protos"


def main() -> int:
    print(f"[fetch_protos] downloading {UPSTREAM_ZIP}")
    try:
        with urllib.request.urlopen(UPSTREAM_ZIP, timeout=60) as resp:
            blob = resp.read()
    except Exception as exc:
        print(f"[fetch_protos] ERROR: {exc}", file=sys.stderr)
        return 1

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for member in zf.namelist():
            if not member.endswith(".proto"):
                continue
            name = Path(member).name
            dest = TARGET_DIR / name
            with zf.open(member) as src, dest.open("wb") as dst:
                dst.write(src.read())
            count += 1
            print(f"  wrote {dest.relative_to(TARGET_DIR.parent)}")

    if count == 0:
        print("[fetch_protos] ERROR: no .proto files found in archive", file=sys.stderr)
        return 1

    print(f"[fetch_protos] done — {count} files in {TARGET_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
