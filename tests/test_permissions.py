"""Unit tests for the PermissionStore."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from echoforge.safety.permissions import Grant, PermissionStore


class TestGrants:
    def test_empty_store_locks_everything(self):
        s = PermissionStore()
        assert s.is_unlocked("/int/firmware") is False
        assert s.is_unlocked("/ext/foo.key") is False

    def test_exact_path_grant(self):
        s = PermissionStore()
        s.grant("/int/firmware.bin", duration_s=60, reason="flashing")
        assert s.is_unlocked("/int/firmware.bin") is True
        assert s.is_unlocked("/int/firmware.bin2") is False

    def test_recursive_directory_grant(self):
        s = PermissionStore()
        s.grant("/int/", duration_s=60)
        assert s.is_unlocked("/int/foo") is True
        assert s.is_unlocked("/int/sub/deep/file") is True
        assert s.is_unlocked("/ext/other") is False

    def test_extension_glob_grant(self):
        s = PermissionStore()
        s.grant("*.key", duration_s=60, reason="research")
        assert s.is_unlocked("/ext/nfc/bond.key") is True
        assert s.is_unlocked("/int/secret.key") is True
        assert s.is_unlocked("/ext/foo.sub") is False


class TestExpiry:
    def test_expired_grants_are_dropped(self):
        s = PermissionStore()
        s.grant("/int/", duration_s=0.01)  # 10 ms
        time.sleep(0.05)
        assert s.is_unlocked("/int/anything") is False

    def test_active_grants_prunes(self):
        s = PermissionStore()
        s.grant("/int/", duration_s=0.01)
        time.sleep(0.05)
        assert s.active_grants() == []

    def test_future_grants_alive(self):
        s = PermissionStore()
        g = s.grant("/int/", duration_s=3600)
        assert g in s.active_grants()


class TestRevocation:
    def test_revoke_by_exact_pattern(self):
        s = PermissionStore()
        s.grant("/int/", duration_s=60)
        assert s.revoke("/int/") is True
        assert s.is_unlocked("/int/foo") is False

    def test_revoke_nonexistent_returns_false(self):
        s = PermissionStore()
        assert s.revoke("/nope") is False

    def test_revoke_all(self):
        s = PermissionStore()
        s.grant("/int/", duration_s=60)
        s.grant("*.key", duration_s=60)
        assert s.revoke_all() == 2
        assert s.active_grants() == []


class TestValidation:
    def test_empty_pattern_rejected(self):
        s = PermissionStore()
        with pytest.raises(ValueError):
            s.grant("", duration_s=60)

    def test_non_positive_duration_rejected(self):
        s = PermissionStore()
        with pytest.raises(ValueError):
            s.grant("/int/", duration_s=0)
        with pytest.raises(ValueError):
            s.grant("/int/", duration_s=-5)


class TestPersistence:
    def test_round_trip_to_disk(self, tmp_path: Path):
        path = tmp_path / "grants.json"
        s1 = PermissionStore(path)
        s1.grant("/int/", duration_s=3600, reason="research")

        # New instance loading the same file should see the grant.
        s2 = PermissionStore(path)
        assert s2.is_unlocked("/int/anything") is True
        grants = s2.active_grants()
        assert len(grants) == 1
        assert grants[0].pattern == "/int/"
        assert grants[0].reason == "research"

    def test_expired_on_disk_is_dropped_on_load(self, tmp_path: Path):
        path = tmp_path / "grants.json"
        # Write an already-expired grant by hand.
        path.write_text(json.dumps({
            "grants": [
                {"pattern": "/int/", "expires_at": time.time() - 60, "reason": "stale", "granted_at": time.time() - 3600}
            ]
        }))
        s = PermissionStore(path)
        assert s.active_grants() == []


class TestGrantMatching:
    def test_grant_object_matches_exact(self):
        g = Grant(pattern="/int/foo", expires_at=time.time() + 60)
        assert g.matches("/int/foo") is True
        assert g.matches("/int/foo.bak") is False

    def test_grant_object_matches_recursive(self):
        g = Grant(pattern="/int/", expires_at=time.time() + 60)
        assert g.matches("/int/a/b") is True
        assert g.matches("/ext/a") is False

    def test_grant_object_matches_glob(self):
        g = Grant(pattern="*.key", expires_at=time.time() + 60)
        assert g.matches("/ext/bond.key") is True
        assert g.matches("/ext/bond.sub") is False
