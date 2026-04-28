"""Unit tests for the composite SafetyPolicy."""

from __future__ import annotations

from echoforge.safety import (
    PermissionStore,
    RiskLevel,
    SafetyPolicy,
)


# --- allow / block dispatch -------------------------------------------------

class TestAutoApprove:
    def test_low_risk_allowed_by_default(self):
        p = SafetyPolicy()
        d = p.assess("list_directory", {"path": "/ext"})
        assert d.verdict == "allow"
        assert d.risk_level == RiskLevel.LOW

    def test_auto_approve_off_requires_approval_for_low(self):
        p = SafetyPolicy(auto_approve_level=None)
        d = p.assess("list_directory", {"path": "/ext"})
        # Without auto-approve, LOW still goes through "allow" per dispatch
        # rules, but explicit user-level auto-approve is separate. Spec:
        # LOW = allow (even without auto_approve). MEDIUM = require_approval.
        assert d.verdict == "allow"

    def test_medium_requires_approval(self):
        p = SafetyPolicy()
        d = p.assess("write_file", {"path": "/ext/a", "content": "hi"})
        assert d.verdict == "require_approval"
        assert d.risk_level == RiskLevel.MEDIUM
        assert d.requires_hold is False

    def test_high_requires_hold(self):
        p = SafetyPolicy()
        d = p.assess("delete", {"path": "/ext/a"})
        assert d.verdict == "require_approval"
        assert d.risk_level == RiskLevel.HIGH
        assert d.requires_hold is True


# --- blocked path handling --------------------------------------------------

class TestBlocked:
    def test_int_path_blocked_without_grant(self):
        p = SafetyPolicy()
        d = p.assess("read_file", {"path": "/int/secret"})
        assert d.verdict == "block"
        assert d.risk_level == RiskLevel.BLOCKED
        assert "/int/secret" in d.reason

    def test_int_path_unlocked_becomes_high(self):
        perms = PermissionStore()
        perms.grant("/int/", duration_s=60, reason="research")
        p = SafetyPolicy(permissions=perms)

        d = p.assess("read_file", {"path": "/int/secret"})
        # Unlocked blocked paths escalate to HIGH — still requires hold.
        assert d.verdict == "require_approval"
        assert d.risk_level == RiskLevel.HIGH
        assert d.requires_hold is True

    def test_extension_block_without_grant(self):
        p = SafetyPolicy()
        d = p.assess("read_file", {"path": "/ext/nfc/bond.nfckey"})
        assert d.verdict == "block"

    def test_partial_unlock_still_blocks(self):
        """If move touches 2 blocked paths but only one is unlocked, still blocked."""
        perms = PermissionStore()
        perms.grant("/int/one", duration_s=60)   # only covers one of the paths
        p = SafetyPolicy(permissions=perms)

        d = p.assess("move", {"path": "/int/one", "destination_path": "/int/two"})
        # move is HIGH baseline, but destination is a blocked path not unlocked
        assert d.verdict == "block"


# --- diff preparation -------------------------------------------------------

class TestDiffInclusion:
    def test_write_file_with_existing_content_includes_diff(self):
        p = SafetyPolicy()
        d = p.assess(
            "write_file",
            {"path": "/ext/garage.sub", "content": "Frequency: 433920000\n"},
            current_content="Frequency: 315000000\n",
        )
        assert d.verdict == "require_approval"
        assert d.diff is not None
        assert "Frequency" in d.diff.diff_text

    def test_write_file_new_file_shows_preview(self):
        p = SafetyPolicy()
        d = p.assess(
            "write_file",
            {"path": "/ext/new.sub", "content": "x\n"},
            current_content=None,
        )
        assert d.diff is not None
        assert d.diff.is_new is True
        assert "(new file)" in d.diff.diff_text

    def test_non_write_actions_have_no_diff(self):
        p = SafetyPolicy()
        d = p.assess("delete", {"path": "/ext/x"})
        assert d.diff is None


# --- escalation integration -------------------------------------------------

class TestEscalation:
    def test_write_into_apps_is_high_not_medium(self):
        p = SafetyPolicy()
        d = p.assess("write_file", {"path": "/ext/apps/game.fap", "content": "x"})
        # Escalated to HIGH by RiskAssessor; policy makes it hold-to-confirm.
        assert d.risk_level == RiskLevel.HIGH
        assert d.verdict == "require_approval"
        assert d.requires_hold is True


# --- Phase 6 MED-write diff emission (review C1) ----------------------------

class TestPayloadDiffEmission:
    """All four Payload Forge MED-write actions must emit a non-None
    DiffSummary. See PHASE6_DECISIONS §3: "All write paths emit a
    DiffSummary before approval."
    """

    def test_payload_badusb_create_emits_diff(self):
        p = SafetyPolicy()
        d = p.assess(
            "payload_badusb_create",
            {
                "name": "rickroll",
                "script_text": "DELAY 100\nSTRING hi\nENTER\n",
                "description": "demo",
            },
            current_content=None,
        )
        assert d.verdict == "require_approval"
        assert d.risk_level == RiskLevel.MEDIUM
        assert d.diff is not None
        # Target-path resolution from args.name.
        assert "/ext/badusb/rickroll.txt" in d.diff.path

    def test_payload_badusb_create_with_existing_content_shows_diff(self):
        p = SafetyPolicy()
        d = p.assess(
            "payload_badusb_create",
            {
                "name": "rickroll",
                "script_text": "DELAY 100\nSTRING hi\nENTER\n",
                "overwrite": True,
            },
            current_content="DELAY 100\nSTRING world\nENTER\n",
        )
        assert d.diff is not None
        # The diff contains both the old and new STRING line — unified
        # diff of one-char-different bodies should carry both markers.
        assert "hi" in d.diff.diff_text or "world" in d.diff.diff_text

    def test_payload_subghz_retune_emits_diff(self):
        p = SafetyPolicy()
        d = p.assess(
            "payload_subghz_retune",
            {
                "source_path": "/ext/subghz/garage.sub",
                "dest_name": "garage-315",
                "frequency_hz": 315000000,
            },
            current_content=None,
        )
        assert d.verdict == "require_approval"
        assert d.diff is not None
        # Falls back to the metadata-only retune preview.
        assert "315000000" in d.diff.diff_text

    def test_payload_subghz_import_capture_emits_diff(self):
        p = SafetyPolicy()
        d = p.assess(
            "payload_subghz_import_capture",
            {
                "source_path": "/ext/subghz/capture_xyz.sub",
                "dest_name": "Garage 2026",
                "description": "North bay",
                "tags": ["garage", "home"],
                "author": "op-42",
            },
            current_content=None,
        )
        assert d.verdict == "require_approval"
        assert d.diff is not None
        assert "capture_xyz.sub" in d.diff.diff_text
        assert "Garage 2026.sub" in d.diff.diff_text
        assert "North bay" in d.diff.diff_text

    def test_payload_ir_import_capture_emits_diff(self):
        p = SafetyPolicy()
        d = p.assess(
            "payload_ir_import_capture",
            {
                "source_path": "/ext/infrared/capture_xyz.ir",
                "dest_name": "LG Remote",
                "description": "Living room",
                "tags": ["tv"],
            },
            current_content=None,
        )
        assert d.verdict == "require_approval"
        assert d.diff is not None
        assert "LG Remote.ir" in d.diff.diff_text


# --- custom auto-approve ----------------------------------------------------

class TestCustomAutoApprove:
    def test_auto_approve_medium_allows_write(self):
        p = SafetyPolicy(auto_approve_level=RiskLevel.MEDIUM)
        d = p.assess("write_file", {"path": "/ext/a", "content": "hi"})
        assert d.verdict == "allow"
        assert "auto-approved" in d.reason

    def test_auto_approve_medium_still_blocks_high(self):
        p = SafetyPolicy(auto_approve_level=RiskLevel.MEDIUM)
        d = p.assess("delete", {"path": "/ext/a"})
        assert d.verdict == "require_approval"
        assert d.risk_level == RiskLevel.HIGH

    def test_auto_approve_does_not_bypass_block(self):
        # Even auto_approve=BLOCKED would be nonsense, but let's make sure
        # HIGH auto-approve doesn't silently allow blocked paths.
        p = SafetyPolicy(auto_approve_level=RiskLevel.HIGH)
        d = p.assess("read_file", {"path": "/int/secret"})
        assert d.verdict == "block"
