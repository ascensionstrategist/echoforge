"""Mirror the top-5 curated Flipper payload repos to the host for offline authoring.

Destination (configurable via --dest): ``~/echoforge-payloads/``

Each source becomes a shallow git clone (depth=1). A top-level ``manifest.json`` tracks
source URL, commit hash, last-sync timestamp, license, and file count — read by
``payload_library_search`` at runtime.

Usage::

    python scripts/sync_payload_library.py              # clone missing + pull existing
    python scripts/sync_payload_library.py --status     # report last-sync + counts
    python scripts/sync_payload_library.py --force      # delete + reclone from scratch
    python scripts/sync_payload_library.py --only <id>  # sync just one source (see SOURCES)
    python scripts/sync_payload_library.py --dest PATH  # override destination root

Exit codes:
    0 — success
    1 — git not available
    2 — one or more sources failed (others may have succeeded)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# --- curated library ---------------------------------------------------------
# Ranked per docs/PHASE6_PAYLOAD_RESEARCH.md. Each entry must be a public repo
# with a license permissive enough to redistribute OR intended-for-sharing by
# the author. Sizes are approximate; "~NN MB" is the cloned-at-depth-1 estimate.


@dataclass(frozen=True)
class Source:
    id: str                # short directory / CLI --only identifier
    url: str               # git clone URL
    license: str           # SPDX identifier or "unlicensed (public corpus)"
    category: str          # one of: badusb / subghz / ir / asset-pack / meta
    description: str       # one-line description (shown in --status)
    approx_size_mb: int    # ballpark for the user's sanity before cloning


SOURCES: list[Source] = [
    Source(
        id="next-flip-asset-packs",
        url="https://github.com/Next-Flip/Asset-Packs.git",
        license="various (see each pack's LICENSE)",
        category="asset-pack",
        description="Momentum's official asset-pack bundle — Dolphin, icons, boot animations.",
        approx_size_mb=102,
    ),
    Source(
        id="flipper-irdb",
        url="https://github.com/Lucaslhm/Flipper-IRDB.git",
        license="CC0-1.0",
        category="ir",
        description="The canonical Flipper IR database (TVs, ACs, soundbars, projectors).",
        approx_size_mb=45,
    ),
    Source(
        id="zero-sploit-subghz-db",
        url="https://github.com/Zero-Sploit/FlipperZero-Subghz-DB.git",
        license="unlicensed (public corpus)",
        category="subghz",
        description="13,717 .sub files — largest community Sub-GHz capture pack.",
        approx_size_mb=149,
    ),
    Source(
        id="falsephilosopher-badusb",
        url="https://github.com/FalsePhilosopher/badusb.git",
        license="MIT",
        category="badusb",
        description="Modern Flipper BadUSB payload library (replaces stale Jakoby repo).",
        approx_size_mb=8,
    ),
    Source(
        id="bst04-payloads",
        url="https://github.com/bst04/payloads_flipperZero.git",
        license="GPL-3.0",
        category="badusb",
        description="Small, auditable modern DuckyScript library — good audit-trail reference.",
        approx_size_mb=3,
    ),
]

DEFAULT_DEST = Path.home() / "echoforge-payloads"
MANIFEST_NAME = "manifest.json"


# --- helpers -----------------------------------------------------------------


def _log(msg: str) -> None:
    print(msg, flush=True)


def _git_available() -> bool:
    return shutil.which("git") is not None


def _run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run git with consistent flags; raise on non-zero exit."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _current_commit(path: Path) -> str:
    try:
        return _run_git(["rev-parse", "HEAD"], cwd=path).stdout.strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _count_files(path: Path) -> int:
    """File count excluding .git/."""
    total = 0
    for p in path.rglob("*"):
        if p.is_file() and ".git" not in p.parts:
            total += 1
    return total


def _clone(src: Source, target: Path) -> None:
    _log(f"  cloning {src.url}  (~{src.approx_size_mb} MB)...")
    _run_git(["clone", "--depth=1", "--single-branch", src.url, str(target)])


def _pull(target: Path) -> tuple[str, str]:
    """Returns (before_commit, after_commit)."""
    before = _current_commit(target)
    _run_git(["fetch", "--depth=1", "origin"], cwd=target)
    # Reset to fetched head — shallow clones don't tolerate merge well.
    _run_git(["reset", "--hard", "FETCH_HEAD"], cwd=target)
    after = _current_commit(target)
    return before, after


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- manifest I/O ------------------------------------------------------------


def _manifest_path(dest: Path) -> Path:
    return dest / MANIFEST_NAME


def _load_manifest(dest: Path) -> dict:
    p = _manifest_path(dest)
    if not p.exists():
        return {"schema_version": 1, "sources": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _log(f"  WARN: manifest at {p} is malformed; rebuilding")
        return {"schema_version": 1, "sources": {}}


def _write_manifest(dest: Path, manifest: dict) -> None:
    manifest["updated_at"] = _now_iso()
    _manifest_path(dest).write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )


# --- operations --------------------------------------------------------------


def sync_one(src: Source, dest: Path, *, force: bool) -> dict:
    """Returns a manifest entry dict for this source."""
    target = dest / src.id
    record: dict = asdict(src)

    if force and target.exists():
        _log(f"  force: removing existing {target}")
        shutil.rmtree(target, ignore_errors=False)

    if target.exists():
        _log(f"[pull] {src.id}")
        before, after = _pull(target)
        if before == after:
            _log(f"  up to date at {after[:8]}")
        else:
            _log(f"  {before[:8]} → {after[:8]}")
    else:
        _log(f"[clone] {src.id}")
        _clone(src, target)

    record.update(
        {
            "commit": _current_commit(target),
            "file_count": _count_files(target),
            "synced_at": _now_iso(),
            "path": str(target),
        }
    )
    return record


def cmd_sync(dest: Path, only: list[str] | None, force: bool) -> int:
    if not _git_available():
        _log("ERROR: `git` is not on PATH. Install Git for Windows and retry.")
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest(dest)

    to_sync: Iterable[Source] = SOURCES
    if only:
        wanted = set(only)
        unknown = wanted - {s.id for s in SOURCES}
        if unknown:
            _log(f"ERROR: unknown source id(s): {', '.join(sorted(unknown))}")
            _log(f"       known ids: {', '.join(s.id for s in SOURCES)}")
            return 2
        to_sync = [s for s in SOURCES if s.id in wanted]

    failures: list[tuple[str, str]] = []
    for src in to_sync:
        try:
            manifest["sources"][src.id] = sync_one(src, dest, force=force)
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip().splitlines()[-3:]
            failures.append((src.id, " / ".join(stderr) or str(exc)))
            _log(f"  FAILED: {src.id}")
            for line in stderr:
                _log(f"    {line}")

    _write_manifest(dest, manifest)

    total_files = sum(r.get("file_count", 0) for r in manifest["sources"].values())
    _log("")
    _log(f"manifest: {_manifest_path(dest)}")
    _log(f"total files across library: {total_files:,}")
    if failures:
        _log(f"failures: {len(failures)} / {sum(1 for _ in to_sync)}")
        for name, reason in failures:
            _log(f"  - {name}: {reason}")
        return 2
    return 0


def cmd_status(dest: Path) -> int:
    if not dest.exists():
        _log(f"library not yet synced. Run: python scripts/sync_payload_library.py")
        return 0

    manifest = _load_manifest(dest)
    sources = manifest.get("sources", {})
    if not sources:
        _log(f"library at {dest} is empty (no manifest entries)")
        return 0

    _log(f"library root: {dest}")
    _log(f"manifest updated: {manifest.get('updated_at', 'never')}")
    _log("")
    _log(f"{'id':<28} {'category':<11} {'files':>7} {'last sync':<20} commit")
    _log(f"{'-'*28} {'-'*11} {'-'*7} {'-'*20} {'-'*8}")
    for src in SOURCES:
        rec = sources.get(src.id)
        if rec is None:
            _log(f"{src.id:<28} {src.category:<11} {'-':>7} {'(not synced)':<20}")
            continue
        _log(
            f"{src.id:<28} {src.category:<11} "
            f"{rec.get('file_count', 0):>7,} {rec.get('synced_at', ''):<20} "
            f"{rec.get('commit', '')[:8]}"
        )
    return 0


# --- CLI ---------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest", type=Path, default=DEFAULT_DEST,
        help=f"library root (default: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="print current library status and exit (no network activity)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="delete each repo before cloning (nuclear re-sync)",
    )
    parser.add_argument(
        "--only", action="append", default=None,
        help="sync only the given source id (repeatable). "
        "Valid: " + ", ".join(s.id for s in SOURCES),
    )
    args = parser.parse_args()

    if args.status:
        return cmd_status(args.dest)
    return cmd_sync(args.dest, args.only, args.force)


if __name__ == "__main__":
    sys.exit(main())
