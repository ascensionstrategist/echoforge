"""
Time-limited, path-scoped permission grants.

When the user wants the AI to touch a normally-blocked path
(e.g. `/int/firmware.bin` or `*.key`), they grant temporary access via
this service. Grants expire automatically after their duration elapses.

Grants can be:
  - exact path: "/int/foo"           — exactly that path
  - recursive:  "/int/subdir/"       — that path and everything under it
  - extension:  "*.key"              — all files with this extension

Thread-safe. Persists to a simple JSON file when a `store_path` is given,
so unlocks survive app restarts (up to their expiry).
"""

from __future__ import annotations

import fnmatch
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, Optional


@dataclass
class Grant:
    pattern: str          # e.g. "/int/", "/ext/foo.key", "*.key"
    expires_at: float     # Unix seconds
    reason: str = ""
    granted_at: float = field(default_factory=time.time)

    def is_expired(self, *, now: Optional[float] = None) -> bool:
        return (now or time.time()) >= self.expires_at

    def matches(self, path: str) -> bool:
        # Exact or recursive directory match.
        if self.pattern.endswith("/"):
            return path == self.pattern.rstrip("/") or path.startswith(self.pattern)
        if self.pattern == path:
            return True
        # Glob extension or wildcard.
        if "*" in self.pattern or "?" in self.pattern:
            return fnmatch.fnmatch(path, self.pattern)
        return False


class PermissionStore:
    """Holds active grants. Optionally persists to disk."""

    def __init__(self, store_path: Optional[Path] = None):
        self._store_path = store_path
        self._grants: list[Grant] = []
        self._lock = threading.Lock()
        if store_path is not None and store_path.exists():
            self._load()

    # -- queries -----------------------------------------------------------

    def is_unlocked(self, path: str, *, now: Optional[float] = None) -> bool:
        """True if any live grant covers this path."""
        if not path:
            return False
        now = now or time.time()
        with self._lock:
            self._prune_expired(now=now)
            return any(g.matches(path) for g in self._grants)

    def active_grants(self, *, now: Optional[float] = None) -> list[Grant]:
        """Snapshot of non-expired grants."""
        now = now or time.time()
        with self._lock:
            self._prune_expired(now=now)
            return list(self._grants)

    def find_covering(self, path: str, *, now: Optional[float] = None) -> Optional[Grant]:
        """Return the first grant covering `path`, or None."""
        now = now or time.time()
        with self._lock:
            self._prune_expired(now=now)
            for g in self._grants:
                if g.matches(path):
                    return g
        return None

    # -- mutations ---------------------------------------------------------

    def grant(
        self,
        pattern: str,
        *,
        duration_s: float = 3600.0,
        reason: str = "",
    ) -> Grant:
        """Create a grant for `pattern` that expires in `duration_s`."""
        if duration_s <= 0:
            raise ValueError("grant duration must be positive")
        if not pattern:
            raise ValueError("grant pattern cannot be empty")
        g = Grant(
            pattern=pattern,
            expires_at=time.time() + duration_s,
            reason=reason,
        )
        with self._lock:
            # Replace any existing grant for this exact pattern.
            self._grants = [x for x in self._grants if x.pattern != pattern]
            self._grants.append(g)
            self._persist_locked()
        return g

    def revoke(self, pattern: str) -> bool:
        """Remove a grant by exact pattern. Returns True if removed."""
        with self._lock:
            before = len(self._grants)
            self._grants = [g for g in self._grants if g.pattern != pattern]
            removed = len(self._grants) != before
            if removed:
                self._persist_locked()
            return removed

    def revoke_all(self) -> int:
        with self._lock:
            n = len(self._grants)
            self._grants.clear()
            self._persist_locked()
            return n

    # -- persistence -------------------------------------------------------

    def _prune_expired(self, *, now: float) -> None:
        """Drop expired grants. Caller must hold the lock."""
        alive = [g for g in self._grants if not g.is_expired(now=now)]
        if len(alive) != len(self._grants):
            self._grants = alive
            self._persist_locked()

    def _persist_locked(self) -> None:
        if self._store_path is None:
            return
        try:
            self._store_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"grants": [asdict(g) for g in self._grants]}
            tmp = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self._store_path)
        except OSError:
            # Don't let persistence failure crash runtime; the grants are
            # already in memory and still enforceable for this session.
            pass

    def _load(self) -> None:
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        grants = raw.get("grants", [])
        now = time.time()
        with self._lock:
            for g in grants:
                try:
                    grant = Grant(
                        pattern=g["pattern"],
                        expires_at=float(g["expires_at"]),
                        reason=g.get("reason", ""),
                        granted_at=float(g.get("granted_at", now)),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if not grant.is_expired(now=now):
                    self._grants.append(grant)
