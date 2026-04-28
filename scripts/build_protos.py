"""
Compile Flipper .proto files into Python modules.

Requires `grpcio-tools` (installed via `pip install -e ".[dev]"`).
Reads from:  ./protos/*.proto
Writes to:   ./src/vesper/proto/*_pb2.py

Run: python scripts/build_protos.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO_SRC = ROOT / "protos"
PROTO_DST = ROOT / "src" / "vesper" / "proto"


def main() -> int:
    try:
        from grpc_tools import protoc  # type: ignore
    except ImportError:
        print(
            "[build_protos] grpc_tools not installed. Run: pip install grpcio-tools",
            file=sys.stderr,
        )
        return 1

    proto_files = sorted(PROTO_SRC.glob("*.proto"))
    if not proto_files:
        print(f"[build_protos] no .proto files in {PROTO_SRC} — run fetch_protos.py first")
        return 1

    PROTO_DST.mkdir(parents=True, exist_ok=True)

    # Clear stale generated files (keep __init__.py).
    for stale in PROTO_DST.glob("*_pb2*.py*"):
        stale.unlink()

    args = [
        "protoc",
        f"--proto_path={PROTO_SRC}",
        f"--python_out={PROTO_DST}",
        f"--pyi_out={PROTO_DST}",
        *(str(p) for p in proto_files),
    ]
    print(f"[build_protos] compiling {len(proto_files)} files")
    rc = protoc.main(args)
    if rc != 0:
        print(f"[build_protos] protoc failed with code {rc}", file=sys.stderr)
        return rc

    # Rewrite generated imports so they work as a package (protoc emits bare
    # `import foo_pb2` which breaks inside src/vesper/proto/). Patch to
    # relative-style that Python can resolve via sys.path manipulation, OR
    # convert to `from . import foo_pb2`.
    _patch_imports(PROTO_DST)

    generated = sorted(p.name for p in PROTO_DST.glob("*_pb2.py"))
    print(f"[build_protos] done — {len(generated)} modules")
    for name in generated:
        print(f"  {name}")
    return 0


def _patch_imports(pkg_dir: Path) -> None:
    """Rewrite `import foo_pb2` → `from . import foo_pb2` for package-safe imports."""
    pb2_names = {p.stem for p in pkg_dir.glob("*_pb2.py")}
    for py in pkg_dir.glob("*_pb2.py"):
        text = py.read_text(encoding="utf-8")
        original = text
        for name in pb2_names:
            text = text.replace(f"import {name}\n", f"from . import {name}\n")
            text = text.replace(f"import {name} as ", f"from . import {name} as ")
        if text != original:
            py.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
