"""Integration tests for the Payload Forge MCP tools.

All tests run against a fake Flipper — no serial, no hardware. We
exercise each of the 13 tools end-to-end through the async callable
the `@tool` decorator returns, and verify the content-shape + error
codes documented in PHASE6_PAYLOAD_FORGE_API.md §4.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

import pytest

from echoforge.agent.tools_payload import (
    MAX_TX_DURATION_S,
    TOOL_PRIMARY_PATH_FIELD_PAYLOAD,
    TOOL_TO_RISK_ACTION_PAYLOAD,
    build_payload_tools,
)
from echoforge.payload.sidecar import Sidecar, dump_sidecar


# ---------------------------------------------------------------------------
# Fake Flipper / Storage — mirrors the real facade just enough for tools.
# ---------------------------------------------------------------------------


class _FileType(Enum):
    FILE = "FILE"
    DIR = "DIR"


@dataclass
class _FakeEntry:
    name: str
    type: _FileType
    size: int = 0


@dataclass
class _CliAck:
    command: str
    output: str = ""


@dataclass
class _FakeStorage:
    """Stand-in for `Storage` with list/read/write/rename/exists."""

    files: dict[str, bytes] = field(default_factory=dict)
    listings: dict[str, list[_FakeEntry]] = field(default_factory=dict)
    write_log: list[tuple[str, bytes]] = field(default_factory=list)
    rename_log: list[tuple[str, str]] = field(default_factory=list)

    def list(self, path: str, *, include_md5: bool = False):
        return self.listings.get(path, [])

    def read(self, path: str, *, timeout_s: float = 30.0) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write(self, path: str, content: bytes | str, *, timeout_s: float = 60.0):
        data = content.encode("utf-8") if isinstance(content, str) else content
        self.files[path] = data
        self.write_log.append((path, data))

    def rename(self, old_path: str, new_path: str):
        if old_path not in self.files:
            raise FileNotFoundError(old_path)
        self.files[new_path] = self.files.pop(old_path)
        self.rename_log.append((old_path, new_path))

    def exists(self, path: str) -> bool:
        return path in self.files


class _FakeBadUsb:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, path: str) -> _CliAck:
        self.calls.append(path)
        return _CliAck(command=f"loader open Bad KB {path}", output="ok")


class _FakeSubGhz:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def transmit_from_file(self, path: str, *, repeats: int = 1) -> _CliAck:
        self.calls.append((path, repeats))
        return _CliAck(command=f"subghz tx_from_file {path} {repeats}", output="ok")


class _FakeIr:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def transmit_from_file(
        self, path: str, *, button_name: str | None = None
    ) -> _CliAck:
        self.calls.append((path, button_name))
        cmd = f"ir tx_file {path}"
        if button_name:
            cmd += f" {button_name}"
        return _CliAck(command=cmd, output="ok")


@dataclass
class _FakeFlipper:
    """Minimal Flipper facade usable by the payload tools."""

    storage: _FakeStorage = field(default_factory=_FakeStorage)
    badusb: _FakeBadUsb = field(default_factory=_FakeBadUsb)
    subghz: _FakeSubGhz = field(default_factory=_FakeSubGhz)
    ir: _FakeIr = field(default_factory=_FakeIr)

    def reconnect(self) -> None:  # needed by _with_recovery's TimeoutError branch
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_by_name(tools, name: str):
    """Look up a built tool by its bare name (what Claude sees)."""
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(name)


def _text_of(response: dict) -> str:
    """Concatenate all text blocks in a tool response."""
    return "\n".join(b.get("text", "") for b in response.get("content", []))


def _data_blob(response: dict) -> dict:
    """Parse the second JSON block (structured data) a tool returns.

    Our `_ok()` helper emits [{text: summary}, {text: JSON(data)}]; this
    pulls out that JSON. Returns an empty dict if no data block.
    """
    blocks = response.get("content", [])
    if len(blocks) < 2:
        return {}
    return json.loads(blocks[1].get("text", "{}"))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_thirteen_tools_built(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        assert len(tools) == 13

    def test_all_tool_names_present(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        expected = set(TOOL_TO_RISK_ACTION_PAYLOAD.keys())
        assert {t.name for t in tools} == expected

    def test_risk_action_map_covers_all_tools(self):
        # Every tool must have a risk-action entry so hooks.py can gate it.
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        for t in tools:
            assert t.name in TOOL_TO_RISK_ACTION_PAYLOAD


# ---------------------------------------------------------------------------
# 1. payload_badusb_validate
# ---------------------------------------------------------------------------


class TestBadusbValidate:
    @pytest.mark.asyncio
    async def test_valid_script_returns_ok(self):
        tools = build_payload_tools(_FakeFlipper())
        tool = _tool_by_name(tools, "payload_badusb_validate")
        r = await tool.handler(
            {"script_text": "DELAY 100\nSTRING hi\nENTER"}
        )
        data = _data_blob(r)
        assert data["ok"] is True
        assert data["stats"]["strings"] == 1
        assert data["stats"]["delays_ms_total"] == 100

    @pytest.mark.asyncio
    async def test_malformed_delay_produces_error_issue(self):
        tools = build_payload_tools(_FakeFlipper())
        tool = _tool_by_name(tools, "payload_badusb_validate")
        r = await tool.handler({"script_text": "DELAY abc"})
        data = _data_blob(r)
        assert data["ok"] is False
        assert any(i["severity"] == "error" for i in data["issues"])

    @pytest.mark.asyncio
    async def test_rickroll_passes_cleanly(self):
        tools = build_payload_tools(_FakeFlipper())
        tool = _tool_by_name(tools, "payload_badusb_validate")
        script = (
            "DELAY 1000\n"
            "GUI r\n"
            "DELAY 500\n"
            "STRING https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
            "ENTER\n"
        )
        r = await tool.handler({"script_text": script})
        data = _data_blob(r)
        assert data["ok"] is True
        assert data["issues"] == []


# ---------------------------------------------------------------------------
# 2. payload_badusb_create
# ---------------------------------------------------------------------------


class TestBadusbCreate:
    @pytest.mark.asyncio
    async def test_create_writes_txt_and_sidecar(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler(
            {
                "name": "rickroll",
                "script_text": "DELAY 100\nSTRING hi\nENTER",
                "description": "demo",
                "tags": ["demo"],
                "overwrite": False,
            }
        )
        assert not r.get("isError")
        # Two writes: .txt and .echoforge.json
        paths = [w[0] for w in flipper.storage.write_log]
        assert "/ext/badusb/rickroll.txt" in paths
        assert "/ext/badusb/rickroll.echoforge.json" in paths

    @pytest.mark.asyncio
    async def test_refuse_overwrite_by_default(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/badusb/rickroll.txt"] = b"existing"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler(
            {
                "name": "rickroll",
                "script_text": "DELAY 100",
            }
        )
        assert r.get("isError")
        assert "E_PATH_EXISTS" in _text_of(r)

    @pytest.mark.asyncio
    async def test_overwrite_true_allowed(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/badusb/rickroll.txt"] = b"existing"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler(
            {
                "name": "rickroll",
                "script_text": "DELAY 100",
                "overwrite": True,
            }
        )
        assert not r.get("isError")

    @pytest.mark.asyncio
    async def test_reject_malformed_script(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler(
            {
                "name": "bad",
                "script_text": "DELAY not-a-number",
            }
        )
        assert r.get("isError")
        assert "E_VALIDATION_FAILED" in _text_of(r)

    @pytest.mark.asyncio
    async def test_missing_name_fails(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler({"script_text": "DELAY 100"})
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)


# ---------------------------------------------------------------------------
# 3. payload_badusb_run
# ---------------------------------------------------------------------------


class TestBadusbRun:
    @pytest.mark.asyncio
    async def test_runs_script(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_run")
        r = await tool.handler({"script_path": "/ext/badusb/rickroll.txt"})
        assert not r.get("isError")
        assert flipper.badusb.calls == ["/ext/badusb/rickroll.txt"]

    @pytest.mark.asyncio
    async def test_missing_path_fails(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_run")
        r = await tool.handler({})
        assert r.get("isError")


# ---------------------------------------------------------------------------
# 4. payload_subghz_list
# ---------------------------------------------------------------------------


class TestSubghzList:
    @pytest.mark.asyncio
    async def test_lists_sub_files(self):
        flipper = _FakeFlipper()
        flipper.storage.listings["/ext/subghz"] = [
            _FakeEntry("garage.sub", _FileType.FILE, 512),
            _FakeEntry("garage.echoforge.json", _FileType.FILE, 128),
            _FakeEntry("readme.txt", _FileType.FILE),
            _FakeEntry("captured", _FileType.DIR),
        ]
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_list")
        r = await tool.handler({})
        data = _data_blob(r)
        # Only the .sub file should show up.
        assert len(data["entries"]) == 1
        assert data["entries"][0]["name"] == "garage.sub"
        assert data["entries"][0]["has_sidecar"] is True

    @pytest.mark.asyncio
    async def test_empty_directory(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_list")
        r = await tool.handler({})
        data = _data_blob(r)
        assert data["entries"] == []


# ---------------------------------------------------------------------------
# 5. payload_subghz_inspect
# ---------------------------------------------------------------------------


_PRINCETON_SUB = (
    "Filetype: Flipper SubGhz Key File\n"
    "Version: 1\n"
    "Frequency: 433920000\n"
    "Preset: FuriHalSubGhzPresetOok650Async\n"
    "Protocol: Princeton\n"
    "Bit: 24\n"
    "Key: 00 00 00 00 00 C9 5E B0\n"
    "TE: 417\n"
)


class TestSubghzInspect:
    @pytest.mark.asyncio
    async def test_inspect_princeton(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/garage.sub"] = _PRINCETON_SUB.encode()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_inspect")
        r = await tool.handler({"path": "/ext/subghz/garage.sub"})
        data = _data_blob(r)
        assert data["headers"]["Frequency"] == 433920000
        assert data["headers"]["Protocol"] == "Princeton"

    @pytest.mark.asyncio
    async def test_inspect_missing_fails(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_inspect")
        r = await tool.handler({"path": "/ext/subghz/does-not-exist.sub"})
        # The underlying FileNotFoundError propagates; _with_recovery
        # turns it into a generic _err response.
        assert r.get("isError")


# ---------------------------------------------------------------------------
# 6. payload_subghz_retune
# ---------------------------------------------------------------------------


class TestSubghzRetune:
    @pytest.mark.asyncio
    async def test_retune_frequency(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/garage.sub"] = _PRINCETON_SUB.encode()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_retune")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/garage.sub",
                "dest_name": "garage-315",
                "frequency_hz": 315000000,
            }
        )
        assert not r.get("isError"), _text_of(r)
        data = _data_blob(r)
        assert data["diff"]["frequency_hz"] == [433920000, 315000000]
        # New file written.
        assert "/ext/subghz/garage-315.sub" in flipper.storage.files
        # Sidecar written.
        assert "/ext/subghz/garage-315.echoforge.json" in flipper.storage.files

    @pytest.mark.asyncio
    async def test_retune_requires_change(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/garage.sub"] = _PRINCETON_SUB.encode()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_retune")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/garage.sub",
                "dest_name": "garage-copy",
                # No freq or preset.
            }
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)

    @pytest.mark.asyncio
    async def test_retune_source_missing(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_retune")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/missing.sub",
                "dest_name": "new.sub",
                "frequency_hz": 315000000,
            }
        )
        assert r.get("isError")
        assert "E_PATH_NOT_FOUND" in _text_of(r)


# ---------------------------------------------------------------------------
# 7. payload_subghz_import_capture
# ---------------------------------------------------------------------------


class TestSubghzImportCapture:
    @pytest.mark.asyncio
    async def test_rename_and_sidecar(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/capture_xyz.sub"] = b"raw content"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_import_capture")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/capture_xyz.sub",
                "dest_name": "Garage 2026",
                "description": "North bay garage door",
                "tags": ["garage", "home"],
            }
        )
        assert not r.get("isError"), _text_of(r)
        # Rename happened.
        assert flipper.storage.rename_log == [
            ("/ext/subghz/capture_xyz.sub", "/ext/subghz/Garage 2026.sub")
        ]
        # Sidecar written.
        assert "/ext/subghz/Garage 2026.echoforge.json" in flipper.storage.files


# ---------------------------------------------------------------------------
# 8. payload_subghz_tx — 600s cap branch coverage
# ---------------------------------------------------------------------------


class TestSubghzTxCap:
    @pytest.mark.asyncio
    async def test_short_duration_allowed(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {
                "signal_file": "/ext/subghz/garage.sub",
                "duration_s": 10,
                "repeats": 1,
            }
        )
        assert not r.get("isError"), _text_of(r)

    @pytest.mark.asyncio
    async def test_exactly_cap_allowed(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {
                "signal_file": "/ext/subghz/garage.sub",
                "duration_s": MAX_TX_DURATION_S,
            }
        )
        assert not r.get("isError")

    @pytest.mark.asyncio
    async def test_over_cap_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {
                "signal_file": "/ext/subghz/garage.sub",
                "duration_s": MAX_TX_DURATION_S + 1,
            }
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)
        assert "600" in _text_of(r)
        # And the radio was not touched.
        assert flipper.subghz.calls == []

    @pytest.mark.asyncio
    async def test_negative_duration_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {
                "signal_file": "/ext/subghz/garage.sub",
                "duration_s": -1,
            }
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)

    @pytest.mark.asyncio
    async def test_no_duration_allowed(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler({"signal_file": "/ext/subghz/garage.sub"})
        assert not r.get("isError"), _text_of(r)

    @pytest.mark.asyncio
    async def test_bad_duration_type_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {
                "signal_file": "/ext/subghz/garage.sub",
                "duration_s": "not-a-number",
            }
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)

    @pytest.mark.asyncio
    async def test_missing_signal_file_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler({"repeats": 1})
        assert r.get("isError")


# ---------------------------------------------------------------------------
# 9. payload_ir_list
# ---------------------------------------------------------------------------


class TestIrList:
    @pytest.mark.asyncio
    async def test_lists_ir_files(self):
        flipper = _FakeFlipper()
        flipper.storage.listings["/ext/infrared"] = [
            _FakeEntry("lg.ir", _FileType.FILE, 1024),
            _FakeEntry("lg.echoforge.json", _FileType.FILE, 256),
            _FakeEntry("universal", _FileType.DIR),
        ]
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_list")
        r = await tool.handler({})
        data = _data_blob(r)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["has_sidecar"] is True


# ---------------------------------------------------------------------------
# 10. payload_ir_inspect
# ---------------------------------------------------------------------------


_PARSED_IR = (
    "Filetype: IR signals file\n"
    "Version: 1\n"
    "#\n"
    "name: Power\n"
    "type: parsed\n"
    "protocol: NECext\n"
    "address: 04 E0 00 00\n"
    "command: 08 F7 00 00\n"
    "#\n"
    "name: Volume_Up\n"
    "type: parsed\n"
    "protocol: NECext\n"
    "address: 04 E0 00 00\n"
    "command: 02 FD 00 00\n"
)


class TestIrInspect:
    @pytest.mark.asyncio
    async def test_inspect_returns_signals(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/infrared/lg.ir"] = _PARSED_IR.encode()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_inspect")
        r = await tool.handler({"path": "/ext/infrared/lg.ir"})
        data = _data_blob(r)
        names = [s["name"] for s in data["signals"]]
        assert names == ["Power", "Volume_Up"]


# ---------------------------------------------------------------------------
# 11. payload_ir_import_capture
# ---------------------------------------------------------------------------


class TestIrImportCapture:
    @pytest.mark.asyncio
    async def test_rename_and_sidecar(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/infrared/capture_xyz.ir"] = b"raw content"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_import_capture")
        r = await tool.handler(
            {
                "source_path": "/ext/infrared/capture_xyz.ir",
                "dest_name": "LG Remote",
                "description": "Living room",
                "tags": ["tv"],
            }
        )
        assert not r.get("isError"), _text_of(r)
        assert "/ext/infrared/LG Remote.ir" in flipper.storage.files


# ---------------------------------------------------------------------------
# 12. payload_ir_transmit
# ---------------------------------------------------------------------------


class TestIrTransmit:
    @pytest.mark.asyncio
    async def test_resolved_button_success(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/infrared/lg.ir"] = _PARSED_IR.encode()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_transmit")
        r = await tool.handler(
            {"signal_file": "/ext/infrared/lg.ir", "button_name": "Power"}
        )
        assert not r.get("isError"), _text_of(r)
        assert flipper.ir.calls == [("/ext/infrared/lg.ir", "Power")]

    @pytest.mark.asyncio
    async def test_unknown_button_returns_validation_failed(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/infrared/lg.ir"] = _PARSED_IR.encode()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_transmit")
        r = await tool.handler(
            {"signal_file": "/ext/infrared/lg.ir", "button_name": "NoSuchButton"}
        )
        assert r.get("isError")
        assert "E_VALIDATION_FAILED" in _text_of(r)
        # Radio NOT invoked.
        assert flipper.ir.calls == []

    @pytest.mark.asyncio
    async def test_no_button_name_transmits_default(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_transmit")
        r = await tool.handler({"signal_file": "/ext/infrared/lg.ir"})
        assert not r.get("isError")
        assert flipper.ir.calls == [("/ext/infrared/lg.ir", None)]


# ---------------------------------------------------------------------------
# 13. payload_library_search
# ---------------------------------------------------------------------------


class TestLibrarySearch:
    @pytest.mark.asyncio
    async def test_searches_across_kinds(self):
        flipper = _FakeFlipper()
        # Stage a subghz capture with a sidecar describing a garage.
        side = dump_sidecar(
            Sidecar(
                kind="subghz",
                name="Garage 2026",
                description="North bay garage door",
                tags=["garage"],
            )
        ).encode("utf-8")
        flipper.storage.listings["/ext/subghz"] = [
            _FakeEntry("garage.sub", _FileType.FILE),
            _FakeEntry("garage.echoforge.json", _FileType.FILE),
        ]
        flipper.storage.files["/ext/subghz/garage.echoforge.json"] = side
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_library_search")
        r = await tool.handler({"query": "garage"})
        data = _data_blob(r)
        assert any(row["name"] == "Garage 2026" for row in data["results"])

    @pytest.mark.asyncio
    async def test_empty_query_matches_everything(self):
        flipper = _FakeFlipper()
        flipper.storage.listings["/ext/subghz"] = [
            _FakeEntry("a.sub", _FileType.FILE),
            _FakeEntry("b.sub", _FileType.FILE),
        ]
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_library_search")
        r = await tool.handler({"query": ""})
        data = _data_blob(r)
        assert len(data["results"]) == 2

    @pytest.mark.asyncio
    async def test_limit_respected(self):
        flipper = _FakeFlipper()
        flipper.storage.listings["/ext/subghz"] = [
            _FakeEntry(f"f{i}.sub", _FileType.FILE) for i in range(10)
        ]
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_library_search")
        r = await tool.handler({"query": "", "limit": 3})
        data = _data_blob(r)
        assert len(data["results"]) == 3


# ---------------------------------------------------------------------------
# Risk-action map sanity
# ---------------------------------------------------------------------------


class TestRiskActionMap:
    def test_risk_action_entries_all_low_or_med_or_high(self):
        from echoforge.safety.risk import ACTION_RULES, RiskLevel

        for action in TOOL_TO_RISK_ACTION_PAYLOAD.values():
            assert action in ACTION_RULES, f"{action!r} missing from ACTION_RULES"
            level = ACTION_RULES[action]
            assert level in (RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH)

    def test_hold_actions_mapped_to_high(self):
        from echoforge.safety.risk import ACTION_RULES, RiskLevel

        # DECISIONS.md §5: payload_badusb_run and payload_subghz_tx HIGH+hold.
        assert ACTION_RULES["payload_badusb_run"] == RiskLevel.HIGH
        assert ACTION_RULES["payload_subghz_tx"] == RiskLevel.HIGH

    def test_create_actions_are_medium(self):
        from echoforge.safety.risk import ACTION_RULES, RiskLevel

        assert ACTION_RULES["payload_badusb_create"] == RiskLevel.MEDIUM
        assert ACTION_RULES["payload_subghz_retune"] == RiskLevel.MEDIUM
        assert ACTION_RULES["payload_subghz_import_capture"] == RiskLevel.MEDIUM
        assert ACTION_RULES["payload_ir_import_capture"] == RiskLevel.MEDIUM
        # IR transmit is MED (line-of-sight, per DECISIONS.md §5).
        assert ACTION_RULES["payload_ir_transmit"] == RiskLevel.MEDIUM

    def test_read_actions_are_low(self):
        from echoforge.safety.risk import ACTION_RULES, RiskLevel

        for action in (
            "payload_badusb_validate",
            "payload_subghz_list",
            "payload_subghz_inspect",
            "payload_ir_list",
            "payload_ir_inspect",
            "payload_library_search",
        ):
            assert ACTION_RULES[action] == RiskLevel.LOW, f"{action} not LOW"


class TestPathFieldMap:
    def test_primary_path_field_map_has_tx_entries(self):
        assert TOOL_PRIMARY_PATH_FIELD_PAYLOAD["payload_subghz_tx"] == "signal_file"
        assert TOOL_PRIMARY_PATH_FIELD_PAYLOAD["payload_ir_transmit"] == "signal_file"
        assert TOOL_PRIMARY_PATH_FIELD_PAYLOAD["payload_badusb_run"] == "script_path"


# ---------------------------------------------------------------------------
# Review C2.1 — Path confinement at the tool layer
# ---------------------------------------------------------------------------


class TestPathConfinement:
    """Every path/source_path/dest_name is gated by regex + traversal
    check before any storage RPC. Review C2.1.
    """

    @pytest.mark.asyncio
    async def test_badusb_create_traversal_name_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler(
            {"name": "../../int/foo", "script_text": "DELAY 100"}
        )
        assert r.get("isError")
        assert "E_PATH_OUTSIDE_ALLOWED" in _text_of(r)
        # And the radio/storage was not touched.
        assert flipper.storage.write_log == []

    @pytest.mark.asyncio
    async def test_subghz_retune_int_source_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_retune")
        r = await tool.handler(
            {
                "source_path": "/int/bondkeys.key",
                "dest_name": "copy",
                "frequency_hz": 315000000,
            }
        )
        assert r.get("isError")
        assert "E_PATH_OUTSIDE_ALLOWED" in _text_of(r)
        # Storage not touched.
        assert flipper.storage.write_log == []

    @pytest.mark.asyncio
    async def test_subghz_import_dest_name_traversal_rejected(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/capture.sub"] = b"raw"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_import_capture")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/capture.sub",
                "dest_name": "../../int/x",
            }
        )
        assert r.get("isError")
        assert "E_PATH_OUTSIDE_ALLOWED" in _text_of(r)
        # Rename was NOT called — the file stays where it was.
        assert flipper.storage.rename_log == []
        assert "/ext/subghz/capture.sub" in flipper.storage.files

    @pytest.mark.asyncio
    async def test_badusb_run_int_path_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_run")
        r = await tool.handler({"script_path": "/int/evil.txt"})
        assert r.get("isError")
        assert "E_PATH_OUTSIDE_ALLOWED" in _text_of(r)
        # Critical: the radio was never invoked.
        assert flipper.badusb.calls == []

    @pytest.mark.asyncio
    async def test_subghz_tx_signal_file_int_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler({"signal_file": "/int/bondkeys.sub"})
        assert r.get("isError")
        assert "E_PATH_OUTSIDE_ALLOWED" in _text_of(r)
        assert flipper.subghz.calls == []

    @pytest.mark.asyncio
    async def test_ir_inspect_wrong_extension_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_inspect")
        r = await tool.handler({"path": "/ext/infrared/x.txt"})
        assert r.get("isError")
        assert "E_PATH_OUTSIDE_ALLOWED" in _text_of(r)


# ---------------------------------------------------------------------------
# Review H1 — `repeats` cap (not just `duration_s`)
# ---------------------------------------------------------------------------


class TestSubghzTxRepeatsCap:
    """`duration_s` is not forwarded to the radio — `repeats` is. We
    must cap `repeats` too, or a million-repeat call trivially
    bypasses the 600-second hardware cap. Review H1.
    """

    @pytest.mark.asyncio
    async def test_repeats_at_cap_allowed(self):
        from echoforge.agent.tools_payload import MAX_TX_REPEATS

        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {"signal_file": "/ext/subghz/x.sub", "repeats": MAX_TX_REPEATS}
        )
        assert not r.get("isError"), _text_of(r)

    @pytest.mark.asyncio
    async def test_repeats_over_cap_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {"signal_file": "/ext/subghz/x.sub", "repeats": 1_000_000}
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)
        assert "100" in _text_of(r)
        # Radio was not touched.
        assert flipper.subghz.calls == []

    @pytest.mark.asyncio
    async def test_repeats_just_over_cap_rejected(self):
        """F2: explicit boundary test at MAX_TX_REPEATS + 1 to pin the
        cap semantics alongside the gross-over `1_000_000` case."""
        from echoforge.agent.tools_payload import MAX_TX_REPEATS

        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {"signal_file": "/ext/subghz/x.sub", "repeats": MAX_TX_REPEATS + 1}
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)
        # Radio was not touched.
        assert flipper.subghz.calls == []

    @pytest.mark.asyncio
    async def test_repeats_zero_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {"signal_file": "/ext/subghz/x.sub", "repeats": 0}
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)

    @pytest.mark.asyncio
    async def test_repeats_bad_type_rejected(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_tx")
        r = await tool.handler(
            {"signal_file": "/ext/subghz/x.sub", "repeats": "lots"}
        )
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)


# ---------------------------------------------------------------------------
# Review M1 — sidecar read-back failure must not silently hash b""
# ---------------------------------------------------------------------------


class _ReadBackFailStorage(_FakeStorage):
    """Rename succeeds but read-back on the new path fails."""

    def read(self, path: str, *, timeout_s: float = 30.0) -> bytes:
        if path.endswith(".echoforge.json"):
            raise FileNotFoundError(path)
        # Simulate an RPC error post-rename.
        raise RuntimeError(f"transport blew up reading {path}")


class TestSidecarReadBackFailure:
    @pytest.mark.asyncio
    async def test_read_back_failure_returns_sidecar_error(self):
        flipper = _FakeFlipper(storage=_ReadBackFailStorage())
        # Plant the source file so the rename can find it.
        flipper.storage.files["/ext/subghz/capture.sub"] = b"raw"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_import_capture")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/capture.sub",
                "dest_name": "mystery",
            }
        )
        assert r.get("isError")
        assert "E_SIDECAR_WRITE_FAILED" in _text_of(r)
        # The sidecar was never written with a hash-of-empty.
        for path, _bytes in flipper.storage.write_log:
            assert not path.endswith(".echoforge.json"), (
                "sidecar written despite read-back failure"
            )


# ---------------------------------------------------------------------------
# Review gap #7 — validate error/empty cases
# ---------------------------------------------------------------------------


class TestBadusbValidateEdgeCases:
    @pytest.mark.asyncio
    async def test_non_string_script_rejected(self):
        tools = build_payload_tools(_FakeFlipper())
        tool = _tool_by_name(tools, "payload_badusb_validate")
        r = await tool.handler({"script_text": 42})
        assert r.get("isError")
        assert "E_UNSUPPORTED_ARG" in _text_of(r)

    @pytest.mark.asyncio
    async def test_empty_string_is_ok(self):
        tools = build_payload_tools(_FakeFlipper())
        tool = _tool_by_name(tools, "payload_badusb_validate")
        r = await tool.handler({"script_text": ""})
        assert not r.get("isError")
        data = _data_blob(r)
        assert data["ok"] is True


# ---------------------------------------------------------------------------
# Review H3 — policy_tag round-trip (Claude auto-write per DECISIONS §4)
# ---------------------------------------------------------------------------


class TestPolicyTagRoundTrip:
    @pytest.mark.asyncio
    async def test_badusb_create_policy_tag_written_to_sidecar(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler(
            {
                "name": "demo",
                "script_text": "DELAY 100\n",
                "policy_tag": "prank",
            }
        )
        assert not r.get("isError"), _text_of(r)
        side_bytes = flipper.storage.files["/ext/badusb/demo.echoforge.json"]
        sidecar = json.loads(side_bytes.decode("utf-8"))
        assert sidecar["policy_tag"] == "prank"

    @pytest.mark.asyncio
    async def test_subghz_import_policy_tag_written(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/cap.sub"] = b"raw"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_import_capture")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/cap.sub",
                "dest_name": "Garage",
                "policy_tag": "vehicle-capture",
            }
        )
        assert not r.get("isError"), _text_of(r)
        side_bytes = flipper.storage.files["/ext/subghz/Garage.echoforge.json"]
        sidecar = json.loads(side_bytes.decode("utf-8"))
        assert sidecar["policy_tag"] == "vehicle-capture"

    @pytest.mark.asyncio
    async def test_ir_import_policy_tag_written(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/infrared/cap.ir"] = b"raw"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_import_capture")
        r = await tool.handler(
            {
                "source_path": "/ext/infrared/cap.ir",
                "dest_name": "TV",
                "policy_tag": "harmless-remote",
            }
        )
        assert not r.get("isError"), _text_of(r)
        side_bytes = flipper.storage.files["/ext/infrared/TV.echoforge.json"]
        sidecar = json.loads(side_bytes.decode("utf-8"))
        assert sidecar["policy_tag"] == "harmless-remote"

    @pytest.mark.asyncio
    async def test_policy_tag_none_when_omitted(self):
        flipper = _FakeFlipper()
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_badusb_create")
        r = await tool.handler(
            {"name": "demo", "script_text": "DELAY 100\n"}
        )
        assert not r.get("isError")
        side = json.loads(
            flipper.storage.files["/ext/badusb/demo.echoforge.json"].decode("utf-8")
        )
        assert side["policy_tag"] is None


# ---------------------------------------------------------------------------
# Review gap #9 — IR import_capture sidecar field round-trip
# ---------------------------------------------------------------------------


class TestIrImportCaptureFields:
    @pytest.mark.asyncio
    async def test_author_tags_description_persisted_in_sidecar(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/infrared/cap.ir"] = b"raw content"
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_ir_import_capture")
        r = await tool.handler(
            {
                "source_path": "/ext/infrared/cap.ir",
                "dest_name": "LG Remote",
                "description": "Living room LG OLED",
                "tags": ["tv", "home"],
                "author": "operator-42",
            }
        )
        assert not r.get("isError"), _text_of(r)
        side_bytes = flipper.storage.files[
            "/ext/infrared/LG Remote.echoforge.json"
        ]
        sidecar = json.loads(side_bytes.decode("utf-8"))
        assert sidecar["description"] == "Living room LG OLED"
        assert sidecar["tags"] == ["tv", "home"]
        assert sidecar["author"] == "operator-42"
        assert sidecar["kind"] == "ir"


# ---------------------------------------------------------------------------
# Review M3 — retune inherits author/tags/description from source sidecar
# ---------------------------------------------------------------------------


class TestRetuneInheritance:
    @pytest.mark.asyncio
    async def test_retune_inherits_source_author_tags_description(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/garage.sub"] = _PRINCETON_SUB.encode()
        # Plant a source sidecar.
        src_side = dump_sidecar(
            Sidecar(
                kind="subghz",
                name="Garage 2026",
                description="North bay door",
                tags=["garage", "home"],
                author="op-42",
                policy_tag="vehicle-capture",
            )
        ).encode("utf-8")
        flipper.storage.files["/ext/subghz/garage.echoforge.json"] = src_side
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_retune")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/garage.sub",
                "dest_name": "garage-315",
                "frequency_hz": 315000000,
            }
        )
        assert not r.get("isError"), _text_of(r)
        dst_side_bytes = flipper.storage.files[
            "/ext/subghz/garage-315.echoforge.json"
        ]
        dst_side = json.loads(dst_side_bytes.decode("utf-8"))
        assert dst_side["author"] == "op-42"
        assert "garage" in dst_side["tags"]
        assert dst_side["description"] == "North bay door"
        assert dst_side["policy_tag"] == "vehicle-capture"

    @pytest.mark.asyncio
    async def test_retune_description_override_wins(self):
        flipper = _FakeFlipper()
        flipper.storage.files["/ext/subghz/garage.sub"] = _PRINCETON_SUB.encode()
        src_side = dump_sidecar(
            Sidecar(
                kind="subghz",
                name="Garage 2026",
                description="Original",
                author="op-42",
            )
        ).encode("utf-8")
        flipper.storage.files["/ext/subghz/garage.echoforge.json"] = src_side
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_retune")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/garage.sub",
                "dest_name": "garage-315",
                "frequency_hz": 315000000,
                "description": "Overridden",
            }
        )
        assert not r.get("isError"), _text_of(r)
        dst_side = json.loads(
            flipper.storage.files[
                "/ext/subghz/garage-315.echoforge.json"
            ].decode("utf-8")
        )
        assert dst_side["description"] == "Overridden"
        assert dst_side["author"] == "op-42"  # Still inherited.


# ---------------------------------------------------------------------------
# Review M5 — payload_subghz_retune error-code reclassification
# ---------------------------------------------------------------------------


class _PermissionDeniedStorage(_FakeStorage):
    """Simulates a storage that raises PermissionError (not
    FileNotFoundError) for the source_path read. Should map to
    E_STORAGE_READ_FAILED, NOT E_PATH_NOT_FOUND.
    """

    def read(self, path: str, *, timeout_s: float = 30.0) -> bytes:
        if path == "/ext/subghz/garage.sub":
            raise PermissionError("EACCES")
        return super().read(path, timeout_s=timeout_s)


class TestRetuneErrorCodes:
    @pytest.mark.asyncio
    async def test_permission_error_on_source_read_is_storage_read_failed(self):
        flipper = _FakeFlipper(storage=_PermissionDeniedStorage())
        tools = build_payload_tools(flipper)
        tool = _tool_by_name(tools, "payload_subghz_retune")
        r = await tool.handler(
            {
                "source_path": "/ext/subghz/garage.sub",
                "dest_name": "garage-315",
                "frequency_hz": 315000000,
            }
        )
        assert r.get("isError")
        text = _text_of(r)
        assert "E_STORAGE_READ_FAILED" in text
        assert "E_PATH_NOT_FOUND" not in text
