"""
Risk classification for Flipper tool calls.

Every AI-initiated action runs through this before execution. The
assessor considers both the *action name* and the *path(s) it touches*,
returning one of four levels:

    LOW      — auto-execute (reads, info queries)
    MEDIUM   — show diff (write_file) or one-tap approve (copy, launch_app)
    HIGH     — hold-to-confirm (delete, move, RF transmit, BadUSB run)
    BLOCKED  — refuse unless user has explicitly unlocked the path

Rules are intentionally hardcoded and fail-safe: unknown actions fall
back to HIGH, unknown paths in sensitive areas escalate to BLOCKED.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional


class RiskLevel(enum.IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    BLOCKED = 3

    def __str__(self) -> str:
        return self.name


# Paths that are always blocked regardless of action, unless explicitly
# unlocked by the PermissionService. The Flipper internal flash holds
# bond keys, OTP, and firmware — touching it can brick the device.
BLOCKED_PATH_PREFIXES: tuple[str, ...] = (
    "/int/",
    "/any/",        # firmware update staging on some forks
)

# File extensions considered sensitive (hold private key material).
BLOCKED_EXTENSIONS: tuple[str, ...] = (
    ".key",
    ".priv",
    ".secret",
    ".nfckey",
    ".keys",
)

# Paths that flag write/delete ops as HIGH even if the action would
# otherwise be MEDIUM. These are "unusual" write targets.
ESCALATE_TO_HIGH_PATHS: tuple[str, ...] = (
    "/ext/update/",
    "/ext/apps/",      # writing to installed apps can brick them
    "/ext/.obfw",      # obfw metadata
)

# Primary action → baseline risk mapping. For actions with no explicit
# entry, the assessor returns HIGH (fail-safe).
ACTION_RULES: Mapping[str, RiskLevel] = {
    # read-only
    "list_directory":    RiskLevel.LOW,
    "read_file":         RiskLevel.LOW,
    "get_device_info":   RiskLevel.LOW,
    "get_storage_info":  RiskLevel.LOW,
    "stat":              RiskLevel.LOW,
    "md5sum":            RiskLevel.LOW,
    "ping":              RiskLevel.LOW,

    # modify
    "write_file":        RiskLevel.MEDIUM,
    "create_directory":  RiskLevel.LOW,
    "copy":              RiskLevel.MEDIUM,
    "push_artifact":     RiskLevel.MEDIUM,

    # destructive
    "delete":            RiskLevel.HIGH,
    "move":              RiskLevel.HIGH,
    "rename":            RiskLevel.HIGH,

    # AI-generated content (doesn't deploy; user still chooses to save)
    "forge_payload":     RiskLevel.LOW,

    # CLI — arbitrary, so MED; CliSession operations escalate as needed.
    "execute_cli":       RiskLevel.MEDIUM,

    # RF / HID actuation — visible to the world, can trigger real devices
    "subghz_transmit":   RiskLevel.HIGH,
    "ir_transmit":       RiskLevel.MEDIUM,
    "nfc_emulate":       RiskLevel.HIGH,
    "rfid_emulate":      RiskLevel.HIGH,
    "ibutton_emulate":   RiskLevel.HIGH,
    "badusb_execute":    RiskLevel.HIGH,

    # apps
    "launch_app":        RiskLevel.MEDIUM,

    # peripherals (harmless feedback)
    "led_control":       RiskLevel.LOW,
    "vibro_control":     RiskLevel.LOW,
    "buzzer_play":       RiskLevel.LOW,

    # GPIO — reading is safe, writing can damage external circuits
    "gpio_read":         RiskLevel.LOW,
    "gpio_write":        RiskLevel.MEDIUM,
    "gpio_set_mode":     RiskLevel.MEDIUM,
    "gpio_set_otg":      RiskLevel.MEDIUM,  # turns 5 V rail on/off

    # faphub / github — network I/O, no Flipper actuation yet
    "search_faphub":     RiskLevel.LOW,
    "install_faphub_app": RiskLevel.MEDIUM,
    "browse_repo":       RiskLevel.LOW,
    "download_resource": RiskLevel.MEDIUM,
    "github_search":     RiskLevel.LOW,

    # glasses integration
    "request_photo":     RiskLevel.LOW,

    # system
    "reboot":            RiskLevel.HIGH,
    "factory_reset":     RiskLevel.BLOCKED,  # requires explicit user unlock

    # -------- Phase 6 Payload Forge actions -----------------------------
    # All 13 tools from PHASE6_PAYLOAD_FORGE_API.md / PHASE6_DECISIONS.md §5.
    # LOW = pure reads / pure parse. MED = derived write / rename + sidecar
    # (operator sees diff at approval time). HIGH = physical actuation
    # (hold-to-confirm enforced at the policy layer via RiskLevel.HIGH).
    "payload_badusb_validate":       RiskLevel.LOW,
    "payload_badusb_create":         RiskLevel.MEDIUM,
    "payload_badusb_run":            RiskLevel.HIGH,
    "payload_subghz_list":           RiskLevel.LOW,
    "payload_subghz_inspect":        RiskLevel.LOW,
    "payload_subghz_retune":         RiskLevel.MEDIUM,
    "payload_subghz_import_capture": RiskLevel.MEDIUM,
    "payload_subghz_tx":             RiskLevel.HIGH,
    "payload_ir_list":               RiskLevel.LOW,
    "payload_ir_inspect":            RiskLevel.LOW,
    "payload_ir_import_capture":     RiskLevel.MEDIUM,
    "payload_ir_transmit":           RiskLevel.MEDIUM,
    "payload_library_search":        RiskLevel.LOW,
}


# Args fields that may carry a path. We check every field present.
#
# `source_path` landed here in the Phase 6 review fix-up: payload tools
# accept `source_path` for retune / import / inspect-style reads, and
# without it in this list the RiskAssessor missed `/int/` prefix and
# `.key` extension gates for those args. Adding it at this layer is
# defense-in-depth; the tool layer also gates via `_check_path`.
_PATH_ARG_FIELDS: tuple[str, ...] = (
    "path",
    "destination_path",
    "source_path",
    "signal_file",
    "script_path",
)


@dataclass(frozen=True)
class RiskAssessment:
    """Result of assessing an action call."""
    action: str
    level: RiskLevel
    reason: str
    blocked_paths: tuple[str, ...] = ()


def is_blocked_path(path: str) -> bool:
    """Return True if `path` is always blocked unless explicitly unlocked."""
    if not path:
        return False
    # Normalize: strip trailing slash, lower-case for extension checks.
    p = path.rstrip("/")
    # Prefix match.
    for prefix in BLOCKED_PATH_PREFIXES:
        if p == prefix.rstrip("/") or p.startswith(prefix):
            return True
    # Extension match.
    lower = p.lower()
    for ext in BLOCKED_EXTENSIONS:
        if lower.endswith(ext):
            return True
    return False


def is_escalated_path(path: str) -> bool:
    """Return True if writes/deletes on this path should be HIGH regardless."""
    if not path:
        return False
    for prefix in ESCALATE_TO_HIGH_PATHS:
        if path.startswith(prefix):
            return True
    return False


def _extract_paths(args: Mapping[str, Any]) -> list[str]:
    """Collect every string path present in args."""
    out: list[str] = []
    for field in _PATH_ARG_FIELDS:
        v = args.get(field)
        if isinstance(v, str) and v:
            out.append(v)
    return out


class RiskAssessor:
    """Classifies tool calls by risk level."""

    def __init__(
        self,
        rules: Optional[Mapping[str, RiskLevel]] = None,
        *,
        blocked_prefixes: Iterable[str] = BLOCKED_PATH_PREFIXES,
        blocked_extensions: Iterable[str] = BLOCKED_EXTENSIONS,
        escalate_prefixes: Iterable[str] = ESCALATE_TO_HIGH_PATHS,
    ):
        self._rules = dict(rules) if rules is not None else dict(ACTION_RULES)
        self._blocked_prefixes = tuple(blocked_prefixes)
        self._blocked_extensions = tuple(blocked_extensions)
        self._escalate_prefixes = tuple(escalate_prefixes)

    def assess(self, action: str, args: Mapping[str, Any]) -> RiskAssessment:
        """Classify one tool call."""
        paths = _extract_paths(args)

        # 1. Blocked-path check first — hard gate regardless of action.
        blocked = tuple(p for p in paths if self._is_blocked_path(p))
        if blocked:
            return RiskAssessment(
                action=action,
                level=RiskLevel.BLOCKED,
                reason=f"path in protected area: {', '.join(blocked)}",
                blocked_paths=blocked,
            )

        # 2. Look up the base risk.
        base = self._rules.get(action)
        if base is None:
            return RiskAssessment(
                action=action,
                level=RiskLevel.HIGH,
                reason=f"unknown action {action!r} — defaulting to HIGH",
            )

        # 3. Escalate writes/deletes on sensitive paths.
        #
        # Phase 6 review fix: the payload Forge MED-write tools
        # (`payload_*_create`, `payload_*_retune`, `payload_*_import_capture`)
        # are also write-like and must be escalated to HIGH when they
        # target `/ext/apps/` / `/ext/update/`. We extend the allowlist
        # here rather than relying on those tools to synthesise a
        # `path` argument — explicit is better than implicit and
        # Phase 4 aliases (`subghz_transmit`, etc.) already live here.
        if base in (RiskLevel.LOW, RiskLevel.MEDIUM):
            if any(self._is_escalated_path(p) for p in paths) and action in {
                "write_file", "delete", "copy", "move", "rename", "create_directory",
                "push_artifact",
                # Phase 6 write-like actions.
                "payload_badusb_create",
                "payload_subghz_retune",
                "payload_subghz_import_capture",
                "payload_ir_import_capture",
            }:
                return RiskAssessment(
                    action=action,
                    level=RiskLevel.HIGH,
                    reason="escalated: path in sensitive area",
                )

        return RiskAssessment(
            action=action,
            level=base,
            reason=f"{action} → {base}",
        )

    def _is_blocked_path(self, path: str) -> bool:
        p = path.rstrip("/")
        for prefix in self._blocked_prefixes:
            if p == prefix.rstrip("/") or p.startswith(prefix):
                return True
        lower = p.lower()
        for ext in self._blocked_extensions:
            if lower.endswith(ext):
                return True
        return False

    def _is_escalated_path(self, path: str) -> bool:
        for prefix in self._escalate_prefixes:
            if path.startswith(prefix):
                return True
        return False
