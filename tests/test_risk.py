"""Unit tests for the risk classifier."""

from __future__ import annotations

import pytest

from echoforge.safety.risk import RiskAssessor, RiskLevel, is_blocked_path


@pytest.fixture
def assessor() -> RiskAssessor:
    return RiskAssessor()


class TestBaselineRules:
    def test_read_ops_are_low(self, assessor):
        assert assessor.assess("list_directory", {"path": "/ext/subghz"}).level == RiskLevel.LOW
        assert assessor.assess("read_file", {"path": "/ext/subghz/g.sub"}).level == RiskLevel.LOW
        assert assessor.assess("get_device_info", {}).level == RiskLevel.LOW
        assert assessor.assess("get_storage_info", {"path": "/ext"}).level == RiskLevel.LOW

    def test_writes_are_medium(self, assessor):
        r = assessor.assess("write_file", {"path": "/ext/subghz/new.sub", "content": "x"})
        assert r.level == RiskLevel.MEDIUM

    def test_destructive_ops_are_high(self, assessor):
        assert assessor.assess("delete", {"path": "/ext/bad.sub"}).level == RiskLevel.HIGH
        assert assessor.assess("move", {"path": "/ext/a", "destination_path": "/ext/b"}).level == RiskLevel.HIGH
        assert assessor.assess("rename", {"path": "/ext/a"}).level == RiskLevel.HIGH

    def test_rf_actuation_is_high(self, assessor):
        assert assessor.assess("subghz_transmit", {"signal_file": "/ext/subghz/x.sub"}).level == RiskLevel.HIGH
        assert assessor.assess("badusb_execute", {"script_path": "/ext/badusb/x.txt"}).level == RiskLevel.HIGH
        assert assessor.assess("nfc_emulate", {"signal_file": "/ext/nfc/c.nfc"}).level == RiskLevel.HIGH
        # IR is lower-risk line-of-sight
        assert assessor.assess("ir_transmit", {"signal_file": "/ext/infrared/tv.ir"}).level == RiskLevel.MEDIUM

    def test_led_vibro_are_low(self, assessor):
        assert assessor.assess("led_control", {"color": "red", "state": True}).level == RiskLevel.LOW
        assert assessor.assess("vibro_control", {"state": True}).level == RiskLevel.LOW

    def test_unknown_action_fails_safe_to_high(self, assessor):
        r = assessor.assess("frobnicate_quantum", {})
        assert r.level == RiskLevel.HIGH
        assert "unknown action" in r.reason

    def test_factory_reset_is_blocked(self, assessor):
        # factory_reset is unconditionally BLOCKED — user must unlock.
        assert assessor.assess("factory_reset", {}).level == RiskLevel.BLOCKED


class TestBlockedPaths:
    def test_int_prefix_is_blocked(self, assessor):
        for action in ("read_file", "list_directory", "write_file"):
            r = assessor.assess(action, {"path": "/int/secret"})
            assert r.level == RiskLevel.BLOCKED
            assert r.blocked_paths == ("/int/secret",)

    def test_key_extensions_are_blocked(self, assessor):
        r = assessor.assess("read_file", {"path": "/ext/nfc/bond.nfckey"})
        assert r.level == RiskLevel.BLOCKED
        assert ".nfckey" in r.blocked_paths[0]

    def test_destination_path_also_checked(self, assessor):
        r = assessor.assess("copy", {"path": "/ext/a.txt", "destination_path": "/int/bad"})
        assert r.level == RiskLevel.BLOCKED
        assert "/int/bad" in r.blocked_paths

    def test_ext_top_level_is_not_blocked(self, assessor):
        r = assessor.assess("list_directory", {"path": "/ext/subghz"})
        assert r.level == RiskLevel.LOW

    def test_is_blocked_path_helper(self):
        assert is_blocked_path("/int/foo") is True
        assert is_blocked_path("/int") is True
        assert is_blocked_path("/ext/something.key") is True
        assert is_blocked_path("/ext/foo.KEY") is True  # case-insensitive
        assert is_blocked_path("/ext/foo.sub") is False


class TestEscalation:
    def test_write_into_update_dir_escalates(self, assessor):
        r = assessor.assess("write_file", {"path": "/ext/update/firmware.dfu", "content": "x"})
        assert r.level == RiskLevel.HIGH

    def test_write_into_apps_dir_escalates(self, assessor):
        r = assessor.assess("write_file", {"path": "/ext/apps/game.fap", "content": "x"})
        assert r.level == RiskLevel.HIGH

    def test_read_from_update_dir_does_not_escalate(self, assessor):
        # Reads are always safe; only writes/deletes get escalated.
        r = assessor.assess("read_file", {"path": "/ext/update/firmware.dfu"})
        assert r.level == RiskLevel.LOW


class TestPayloadSourcePathIntegration:
    """Review C2.2 fix: `source_path` was missing from `_PATH_ARG_FIELDS`
    so payload tools' `source_path` args slipped past blocked-prefix /
    extension checks. These tests lock in the fix.
    """

    def test_retune_source_path_in_int_blocks(self, assessor):
        r = assessor.assess(
            "payload_subghz_retune",
            {"source_path": "/int/bondkeys.key", "dest_name": "copy"},
        )
        assert r.level == RiskLevel.BLOCKED
        assert "/int/bondkeys.key" in r.blocked_paths

    def test_subghz_import_source_path_key_extension_blocks(self, assessor):
        r = assessor.assess(
            "payload_subghz_import_capture",
            {"source_path": "/ext/subghz/bond.nfckey", "dest_name": "x"},
        )
        assert r.level == RiskLevel.BLOCKED
        assert any(".nfckey" in p for p in r.blocked_paths)

    def test_ir_import_source_path_in_int_blocks(self, assessor):
        r = assessor.assess(
            "payload_ir_import_capture",
            {"source_path": "/int/secret.ir", "dest_name": "x"},
        )
        assert r.level == RiskLevel.BLOCKED


class TestPayloadEscalation:
    """Review C2.3 fix: payload MED-write actions must escalate when
    targeting `/ext/apps/` or `/ext/update/`.
    """

    def test_badusb_create_into_apps_escalates(self, assessor):
        r = assessor.assess(
            "payload_badusb_create",
            {"path": "/ext/apps/evil.txt", "script_text": "STRING x"},
        )
        assert r.level == RiskLevel.HIGH

    def test_subghz_retune_into_update_escalates(self, assessor):
        # source_path is legit; destination path synthesised in the
        # tool isn't seen by the risk assessor directly, but we add an
        # explicit `path` arg to simulate the tool passing it through.
        r = assessor.assess(
            "payload_subghz_retune",
            {
                "source_path": "/ext/subghz/garage.sub",
                "path": "/ext/update/fake.sub",
            },
        )
        assert r.level == RiskLevel.HIGH


class TestCustomRules:
    def test_can_override_rules(self):
        custom = RiskAssessor(rules={"read_file": RiskLevel.HIGH})
        assert custom.assess("read_file", {"path": "/ext/x"}).level == RiskLevel.HIGH

    def test_empty_rules_falls_back_to_high(self):
        empty = RiskAssessor(rules={})
        assert empty.assess("list_directory", {"path": "/ext"}).level == RiskLevel.HIGH
