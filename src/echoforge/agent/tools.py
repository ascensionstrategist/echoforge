"""
Claude Agent SDK tool registry wrapping the Flipper facade.

Each action module on `Flipper` is exposed as one or more SDK tools.
`build_flipper_tools(flipper)` returns the full list ready to pass into
`create_sdk_mcp_server(tools=...)`.

All tools are read-only from the perspective of the *tool object itself*
— side-effecting calls happen on the captured `Flipper` instance which
must outlive the agent's query. Use `run_agent()` in `runner.py` which
manages lifetimes for you.

Error policy: tools never raise up to the SDK. Exceptions become
`isError: True` content blocks so Claude can reason about the failure.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from claude_agent_sdk import SdkMcpTool, tool

from echoforge.actions import Button
from echoforge.actions.gpio import PinMode
from echoforge.flipper import Flipper

log = logging.getLogger(__name__)


# Phase 4.5a: if the Flipper has been idle longer than this at the moment
# a tool call arrives, do a quick proactive ping BEFORE the real call to
# flush any stale USB-CDC buffers. Without this, the first RPC after a
# long Claude-think often times out and we pay a 300-500ms reconnect
# penalty in `_with_recovery`. The value is deliberately just above the
# keepalive interval (5.0s) so a healthy session never hits this path.
_WITH_RECOVERY_IDLE_PING_S = 10.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ok(text: str, **data: Any) -> dict[str, Any]:
    """Success response. Optional structured data goes as a second JSON block."""
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if data:
        content.append({"type": "text", "text": json.dumps(data, default=str, indent=2)})
    return {"content": content}


def _err(msg: str) -> dict[str, Any]:
    """Error response — Claude sees this and can recover."""
    return {"content": [{"type": "text", "text": f"ERROR: {msg}"}], "isError": True}


def _safe(fn: Callable[[], Any]) -> dict[str, Any]:
    """Wrap a sync action; convert exceptions to error responses."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return _err(f"{type(exc).__name__}: {exc}")


def _with_recovery(flipper: Flipper, fn: Callable[[], Any]) -> dict[str, Any]:
    """Run `fn()`; on TimeoutError, reconnect the Flipper and retry ONCE.

    The first RPC after a long Claude-think interval can fail because the
    Flipper / USB CDC session has gone stale. A full close/reopen of the
    serial forces a fresh CDC enumeration and almost always unsticks it.

    Phase 4.5a idle-guard: if the session has been idle longer than
    `_WITH_RECOVERY_IDLE_PING_S`, do a cheap 2s-timeout ping FIRST to
    warm the link. A failed pre-ping reconnects immediately instead of
    paying the full 5s RPC timeout on the real call.
    """
    # Proactive pre-call ping if the link has been idle.
    try:
        idle = flipper.idle_seconds()
    except Exception:  # noqa: BLE001
        idle = 0.0
    if idle > _WITH_RECOVERY_IDLE_PING_S:
        try:
            flipper.proactive_ping(timeout_s=2.0)
        except Exception as ping_exc:  # noqa: BLE001
            log.warning(
                "tool pre-call ping failed after %.1fs idle — reconnecting: %s",
                idle, ping_exc,
            )
            try:
                flipper.reconnect()
            except Exception as rc_exc:  # noqa: BLE001
                return _err(
                    f"pre-call ping failed and reconnect failed: "
                    f"{type(rc_exc).__name__}: {rc_exc}"
                )

    try:
        return fn()
    except TimeoutError:
        log.warning("tool RPC timed out — reconnecting Flipper and retrying once")
        try:
            flipper.reconnect()
        except Exception as rc_exc:  # noqa: BLE001
            return _err(
                f"RPC timed out and reconnect failed: {type(rc_exc).__name__}: {rc_exc}"
            )
        try:
            return fn()
        except Exception as retry_exc:  # noqa: BLE001
            return _err(
                f"RPC timed out; retry after reconnect also failed: "
                f"{type(retry_exc).__name__}: {retry_exc}"
            )
    except Exception as exc:  # noqa: BLE001
        return _err(f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Tool builder
# ---------------------------------------------------------------------------

def build_flipper_tools(flipper: Flipper) -> list[SdkMcpTool]:
    """Return the full set of echoforge tools bound to `flipper`."""
    tools: list[SdkMcpTool] = []

    # =======================================================================
    # STORAGE — reads
    # =======================================================================

    @tool(
        "list_directory",
        "List files and directories at a path on the Flipper (e.g. /ext/subghz). "
        "Entries include name, type (FILE/DIR), and size in bytes.",
        {"path": str},
    )
    async def list_directory(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            entries = flipper.storage.list(args["path"])
            rows = [
                {"name": e.name, "type": e.type.name, "size": e.size}
                for e in entries
            ]
            summary = f"{len(rows)} entries in {args['path']}"
            return _ok(summary, entries=rows)
        return _with_recovery(flipper, _run)

    @tool(
        "read_file",
        "Read a file on the Flipper. Returns text if UTF-8 decodable, else "
        "a hex preview of the first 256 bytes + total size.",
        {"path": str},
    )
    async def read_file(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            data = flipper.storage.read(args["path"])
            try:
                text = data.decode("utf-8")
                return _ok(f"{len(data)} bytes, UTF-8:\n{text}")
            except UnicodeDecodeError:
                preview = data[:256].hex(" ")
                return _ok(
                    f"{len(data)} bytes, binary. First 256B hex:\n{preview}",
                    size=len(data),
                )
        return _with_recovery(flipper, _run)

    @tool(
        "stat",
        "Get metadata for a file or directory on the Flipper (size, type, md5).",
        {"path": str},
    )
    async def stat_file(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            s = flipper.storage.stat(args["path"])
            return _ok(
                f"{args['path']}: type={s.type.name} size={s.size}",
                name=s.name, type=s.type.name, size=s.size, md5=s.md5,
            )
        return _with_recovery(flipper, _run)

    @tool(
        "md5",
        "Compute md5 of a file on the Flipper. Useful for integrity checks.",
        {"path": str},
    )
    async def md5_file(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            h = flipper.storage.md5sum(args["path"])
            return _ok(f"md5 {args['path']}: {h}", md5=h)
        return _with_recovery(flipper, _run)

    @tool(
        "get_storage_info",
        "Get free / total bytes for a Flipper mount point (/ext or /int).",
        {"path": str},
    )
    async def get_storage_info(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            si = flipper.storage.info(args["path"])
            return _ok(
                f"{si.path}: {si.free_bytes:,} B free / {si.total_bytes:,} B total",
                total_bytes=si.total_bytes,
                free_bytes=si.free_bytes,
                used_bytes=si.used_bytes,
                percent_used=round(si.percent_used, 2),
            )
        return _with_recovery(flipper, _run)

    # =======================================================================
    # STORAGE — writes (safety layer gates these)
    # =======================================================================

    @tool(
        "write_file",
        "Write text or binary content to a file on the Flipper. Creates or "
        "overwrites. Pass bytes as a UTF-8 string — for binary, use a hex-encoded "
        "string with 'encoding' set to 'hex'.",
        {"path": str, "content": str, "encoding": str},
    )
    async def write_file(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            encoding = args.get("encoding", "utf-8")
            content = args["content"]
            if encoding == "hex":
                payload = bytes.fromhex(content.replace(" ", ""))
            else:
                payload = content.encode("utf-8")
            flipper.storage.write(args["path"], payload)
            return _ok(f"wrote {len(payload)} B to {args['path']}")
        return _with_recovery(flipper, _run)

    @tool(
        "create_directory",
        "Create a directory on the Flipper (does not error if it already exists "
        "on most firmwares).",
        {"path": str},
    )
    async def create_directory(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.storage.mkdir(args["path"])
            return _ok(f"mkdir {args['path']} OK")
        return _with_recovery(flipper, _run)

    @tool(
        "delete",
        "Delete a file or directory. Set recursive=true to delete a directory "
        "and its contents. HIGH RISK — non-recoverable.",
        {"path": str, "recursive": bool},
    )
    async def delete_path(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.storage.delete(args["path"], recursive=bool(args.get("recursive", False)))
            return _ok(f"deleted {args['path']}")
        return _with_recovery(flipper, _run)

    @tool(
        "rename",
        "Rename or move a file/directory on the Flipper. The firmware uses the "
        "same operation for both.",
        {"path": str, "destination_path": str},
    )
    async def rename_path(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.storage.rename(args["path"], args["destination_path"])
            return _ok(f"renamed {args['path']} -> {args['destination_path']}")
        return _with_recovery(flipper, _run)

    @tool(
        "copy",
        "Copy a file on the Flipper. Host-driven — reads full source then "
        "writes destination. Not atomic.",
        {"path": str, "destination_path": str},
    )
    async def copy_path(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            n = flipper.storage.copy(args["path"], args["destination_path"])
            return _ok(f"copied {n} B: {args['path']} -> {args['destination_path']}")
        return _with_recovery(flipper, _run)

    # =======================================================================
    # SYSTEM
    # =======================================================================

    @tool(
        "get_device_info",
        "Get hardware + firmware info (hardware_name, firmware_branch, "
        "firmware_commit, hardware_uid, etc.). 50+ keys typical.",
        {},
    )
    async def get_device_info(_: dict[str, Any]) -> dict[str, Any]:
        def _run():
            di = flipper.system.device_info()
            # Include everything — Claude can pick what's relevant.
            summary = (
                f"hardware_name={di.hardware_name!r} "
                f"firmware={di.firmware_branch}@{di.firmware_commit}"
            )
            return _ok(summary, info=dict(di.raw))
        return _with_recovery(flipper, _run)

    @tool(
        "get_power_info",
        "Get battery state: charge level (0-100), charging state, voltage, "
        "temperature, and raw power keys.",
        {},
    )
    async def get_power_info(_: dict[str, Any]) -> dict[str, Any]:
        def _run():
            pi = flipper.system.power_info()
            return _ok(
                f"battery={pi.charge_level}% charging={pi.is_charging} "
                f"voltage={pi.battery_voltage} temp={pi.temperature_c}",
                charge_level=pi.charge_level,
                is_charging=pi.is_charging,
                battery_voltage=pi.battery_voltage,
                temperature_c=pi.temperature_c,
                raw=dict(pi.raw),
            )
        return _with_recovery(flipper, _run)

    @tool(
        "get_datetime",
        "Get the Flipper's real-time clock.",
        {},
    )
    async def get_datetime(_: dict[str, Any]) -> dict[str, Any]:
        def _run():
            dt = flipper.system.get_datetime()
            return _ok(f"flipper_time={dt.to_py().isoformat()} weekday={dt.weekday}")
        return _with_recovery(flipper, _run)

    @tool(
        "ping",
        "Round-trip a random payload to the Flipper — diagnoses transport health.",
        {},
    )
    async def ping_flipper(_: dict[str, Any]) -> dict[str, Any]:
        def _run():
            echo = flipper.system.ping()
            return _ok(f"pong ({len(echo)} B round-trip)")
        return _with_recovery(flipper, _run)

    @tool(
        "reboot",
        "Reboot the Flipper. mode='os' for normal reboot, 'dfu' for firmware "
        "flash mode, 'update' to run a pending update. HIGH RISK — disconnects "
        "the agent; user must reconnect.",
        {"mode": str},
    )
    async def reboot_flipper(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.system.reboot(mode=args.get("mode", "os"))
            return _ok(f"reboot mode={args.get('mode', 'os')} sent — RPC will disconnect")
        return _with_recovery(flipper, _run)

    # =======================================================================
    # APPLICATION
    # =======================================================================

    @tool(
        "is_locked",
        "Is the Flipper screen currently locked (PIN/lockscreen)? Apps can't "
        "be launched while locked.",
        {},
    )
    async def app_is_locked(_: dict[str, Any]) -> dict[str, Any]:
        def _run():
            return _ok(f"locked={flipper.app.is_locked()}")
        return _with_recovery(flipper, _run)

    @tool(
        "launch_app",
        "Launch a built-in or installed app by name. Common: 'Sub-GHz', "
        "'Infrared', 'NFC', '125 kHz RFID', 'iButton', 'Bad KB' (Momentum) / "
        "'Bad USB' (stock), 'Snake Game', 'Clock'. Optional `args` passes file "
        "path or params.",
        {"app_name": str, "args": str},
    )
    async def launch_app(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.app.start(args["app_name"], args.get("args", ""))
            return _ok(f"launched app {args['app_name']!r}")
        return _with_recovery(flipper, _run)

    @tool(
        "exit_app",
        "Exit the currently running app. Returns OK even if no app is running.",
        {},
    )
    async def exit_app(_: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.app.exit()
            return _ok("app exit requested")
        return _with_recovery(flipper, _run)

    @tool(
        "press_button",
        "Simulate a tap on UP/DOWN/LEFT/RIGHT/OK/BACK. Requires an app to be "
        "running with GUI focus — will fail with APP_NOT_RUNNING otherwise.",
        {"button": str},
    )
    async def press_button(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            btn = args["button"].upper()
            if btn not in {b.value for b in Button}:
                return _err(f"button must be one of UP/DOWN/LEFT/RIGHT/OK/BACK, got {btn!r}")
            flipper.app.press_release(btn)
            return _ok(f"pressed {btn}")
        return _with_recovery(flipper, _run)

    # =======================================================================
    # PERIPHERALS (LED / vibro / buzzer — routed via CLI mode switch)
    # =======================================================================

    @tool(
        "led_control",
        "Set one LED channel's brightness (0-255). color: 'r' (red), 'g' "
        "(green), 'b' (blue), 'bl' (backlight).",
        {"color": str, "level": int},
    )
    async def led_control(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.led.set(args["color"], int(args["level"]))
            return _ok(f"led {args['color']} = {args['level']}")
        return _with_recovery(flipper, _run)

    @tool(
        "vibro_control",
        "Turn the vibration motor on or off. If duration_ms > 0, pulses for "
        "that duration then stops.",
        {"state": bool, "duration_ms": int},
    )
    async def vibro_control(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            duration = int(args.get("duration_ms", 0) or 0)
            if duration > 0:
                flipper.vibro.pulse(duration_ms=duration)
                return _ok(f"vibro pulse {duration} ms")
            if args.get("state"):
                flipper.vibro.on()
                return _ok("vibro ON")
            flipper.vibro.off()
            return _ok("vibro OFF")
        return _with_recovery(flipper, _run)

    @tool(
        "buzzer_play",
        "Play a tone at `frequency_hz` for `duration_ms`. Firmware-dependent; "
        "returns error if none of the known buzzer CLI syntaxes are accepted.",
        {"frequency_hz": int, "duration_ms": int},
    )
    async def buzzer_play(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            ack = flipper.buzzer.play(
                frequency_hz=float(args["frequency_hz"]),
                duration_ms=int(args.get("duration_ms", 200)),
            )
            return _ok(f"tone sent: {ack.command!r}")
        return _with_recovery(flipper, _run)

    # =======================================================================
    # RF / HID (HIGH RISK — gated by SafetyPolicy)
    # =======================================================================

    @tool(
        "subghz_transmit",
        "Broadcast an RF signal from a .sub file. HIGH RISK — this is real "
        "RF emission visible to nearby receivers. Make sure the signal_file "
        "exists first.",
        {"signal_file": str, "repeats": int},
    )
    async def subghz_transmit(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            ack = flipper.subghz.transmit_from_file(
                args["signal_file"], repeats=int(args.get("repeats", 1) or 1)
            )
            return _ok(f"TX sent: {ack.command!r}")
        return _with_recovery(flipper, _run)

    @tool(
        "ir_transmit",
        "Transmit an IR signal from a .ir file. Optional button_name selects "
        "a named signal from multi-signal files.",
        {"signal_file": str, "button_name": str},
    )
    async def ir_transmit(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            ack = flipper.ir.transmit_from_file(
                args["signal_file"], button_name=args.get("button_name") or None
            )
            return _ok(f"IR sent: {ack.command!r}")
        return _with_recovery(flipper, _run)

    @tool(
        "nfc_emulate",
        "Launch NFC app with a .nfc file loaded. On most firmwares this "
        "requires the user to press OK on the Flipper to begin emulation.",
        {"signal_file": str},
    )
    async def nfc_emulate(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            ack = flipper.emulate.nfc(args["signal_file"])
            return _ok(f"NFC loader opened: {ack.command!r}")
        return _with_recovery(flipper, _run)

    @tool(
        "rfid_emulate",
        "Emulate a 125 kHz RFID tag from a .rfid file.",
        {"signal_file": str},
    )
    async def rfid_emulate(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            ack = flipper.emulate.rfid(args["signal_file"])
            return _ok(f"RFID emulate: {ack.command!r}")
        return _with_recovery(flipper, _run)

    @tool(
        "ibutton_emulate",
        "Emulate a 1-Wire iButton from a .ibtn file.",
        {"signal_file": str},
    )
    async def ibutton_emulate(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            ack = flipper.emulate.ibutton(args["signal_file"])
            return _ok(f"iButton emulate: {ack.command!r}")
        return _with_recovery(flipper, _run)

    @tool(
        "badusb_execute",
        "Run a BadUSB DuckyScript from a .txt file. HIGH RISK — injects "
        "keystrokes into the computer the Flipper is plugged into (i.e., the "
        "user's own machine right now).",
        {"script_path": str},
    )
    async def badusb_execute(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            ack = flipper.badusb.run(args["script_path"])
            return _ok(f"BadUSB started: {ack.command!r}")
        return _with_recovery(flipper, _run)

    # =======================================================================
    # GPIO
    # =======================================================================

    @tool(
        "gpio_read",
        "Read the current logic level (0 or 1) of a pin. Pin names: PA4, PA6, "
        "PA7, PB2, PB3, PC0, PC1, PC3.",
        {"pin": str},
    )
    async def gpio_read(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            value = flipper.gpio.read(args["pin"])
            return _ok(f"{args['pin']} = {value}", pin=args["pin"], value=value)
        return _with_recovery(flipper, _run)

    @tool(
        "gpio_write",
        "Drive a pin HIGH or LOW. Pin must be in OUTPUT mode first "
        "(gpio_set_mode).",
        {"pin": str, "value": int},
    )
    async def gpio_write(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.gpio.write(args["pin"], int(args["value"]))
            return _ok(f"{args['pin']} <- {args['value']}")
        return _with_recovery(flipper, _run)

    @tool(
        "gpio_set_mode",
        "Configure a pin as INPUT or OUTPUT.",
        {"pin": str, "mode": str},
    )
    async def gpio_set_mode(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            m = args["mode"].upper()
            if m not in {"INPUT", "OUTPUT"}:
                return _err(f"mode must be INPUT or OUTPUT, got {m!r}")
            flipper.gpio.set_mode(args["pin"], PinMode[m])
            return _ok(f"{args['pin']} mode = {m}")
        return _with_recovery(flipper, _run)

    @tool(
        "gpio_set_otg",
        "Toggle the 5 V OTG rail that powers external dev boards.",
        {"state": bool},
    )
    async def gpio_set_otg(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            flipper.gpio.set_otg(bool(args["state"]))
            return _ok(f"OTG 5 V {'ON' if args['state'] else 'OFF'}")
        return _with_recovery(flipper, _run)

    # =======================================================================
    # CLI PASSTHROUGH
    # =======================================================================

    @tool(
        "execute_cli",
        "Run any raw Flipper CLI command and return its text output. Use "
        "dedicated tools first — this is a fallback for commands without "
        "a native tool. Examples: 'free_blocks', 'uptime', 'log'.",
        {"command": str, "timeout_s": float},
    )
    async def execute_cli(args: dict[str, Any]) -> dict[str, Any]:
        def _run():
            result = flipper.cli(args["command"], timeout_s=float(args.get("timeout_s", 5.0)))
            return _ok(
                f"{args['command']!r} ({result.duration_ms:.0f} ms):\n{result.output}",
                command=result.command,
                duration_ms=result.duration_ms,
            )
        return _with_recovery(flipper, _run)

    # Register all tools defined above.
    tools.extend([
        # reads
        list_directory, read_file, stat_file, md5_file, get_storage_info,
        # writes / destructive
        write_file, create_directory, delete_path, rename_path, copy_path,
        # system
        get_device_info, get_power_info, get_datetime, ping_flipper, reboot_flipper,
        # application
        app_is_locked, launch_app, exit_app, press_button,
        # peripherals
        led_control, vibro_control, buzzer_play,
        # rf / hid
        subghz_transmit, ir_transmit,
        nfc_emulate, rfid_emulate, ibutton_emulate, badusb_execute,
        # gpio
        gpio_read, gpio_write, gpio_set_mode, gpio_set_otg,
        # cli
        execute_cli,
    ])

    return tools


# ---------------------------------------------------------------------------
# Name → action mapping (used by SafetyPolicy hook in hooks.py)
#
# Our SDK tool names don't always match the action names the risk rules
# use (e.g. tool "press_button" vs. rule "press_button", tool "rename"
# vs. rule "rename"). Keep this table in sync with risk.ACTION_RULES.
# ---------------------------------------------------------------------------

TOOL_TO_RISK_ACTION: dict[str, str] = {
    # reads
    "list_directory": "list_directory",
    "read_file": "read_file",
    "stat": "stat",
    "md5": "md5sum",
    "get_storage_info": "get_storage_info",
    "get_device_info": "get_device_info",
    "get_power_info": "get_device_info",   # same class of read
    "get_datetime": "get_device_info",
    "ping": "ping",
    "is_locked": "get_device_info",
    "gpio_read": "gpio_read",
    # modify
    "write_file": "write_file",
    "create_directory": "create_directory",
    "copy": "copy",
    "rename": "rename",
    "launch_app": "launch_app",
    "exit_app": "launch_app",
    "press_button": "launch_app",
    "ir_transmit": "ir_transmit",
    "led_control": "led_control",
    "vibro_control": "vibro_control",
    "buzzer_play": "buzzer_play",
    "gpio_write": "gpio_write",
    "gpio_set_mode": "gpio_set_mode",
    "gpio_set_otg": "gpio_set_otg",
    "execute_cli": "execute_cli",
    # destructive
    "delete": "delete",
    "subghz_transmit": "subghz_transmit",
    "nfc_emulate": "nfc_emulate",
    "rfid_emulate": "rfid_emulate",
    "ibutton_emulate": "ibutton_emulate",
    "badusb_execute": "badusb_execute",
    "reboot": "reboot",
}


TOOL_PRIMARY_PATH_FIELD: dict[str, str] = {
    # Which args field holds the primary path for SafetyPolicy assessment
    "list_directory": "path",
    "read_file": "path",
    "stat": "path",
    "md5": "path",
    "get_storage_info": "path",
    "write_file": "path",
    "create_directory": "path",
    "copy": "path",
    "rename": "path",
    "delete": "path",
    "subghz_transmit": "signal_file",
    "ir_transmit": "signal_file",
    "nfc_emulate": "signal_file",
    "rfid_emulate": "signal_file",
    "ibutton_emulate": "signal_file",
    "badusb_execute": "script_path",
}


# ---------------------------------------------------------------------------
# Phase 6 — Payload Forge tool mappings
#
# The payload tools live in `tools_payload.py` to keep this file focused
# on the Phase 4 surface. Their risk/path maps are merged into the
# module-level dicts below so `hooks.py` can keep its single-lookup flow.
# ---------------------------------------------------------------------------
from echoforge.agent.tools_payload import (  # noqa: E402 — circular-friendly
    TOOL_PRIMARY_PATH_FIELD_PAYLOAD,
    TOOL_TO_RISK_ACTION_PAYLOAD,
)

TOOL_TO_RISK_ACTION.update(TOOL_TO_RISK_ACTION_PAYLOAD)
TOOL_PRIMARY_PATH_FIELD.update(TOOL_PRIMARY_PATH_FIELD_PAYLOAD)
