"""
echoforge safety layer — risk classification, permission grants, diffs,
audit logging, and the composite SafetyPolicy. Pure Python, no hardware.
"""

from echoforge.safety.audit import ActionRecord, AuditMode, AuditService
from echoforge.safety.diff import (
    DiffSummary,
    binary_diff_summary,
    is_binary,
    summarize_write,
    unified_text_diff,
)
from echoforge.safety.permissions import Grant, PermissionStore
from echoforge.safety.policy import Decision, SafetyPolicy, Verdict
from echoforge.safety.risk import (
    ACTION_RULES,
    BLOCKED_EXTENSIONS,
    BLOCKED_PATH_PREFIXES,
    ESCALATE_TO_HIGH_PATHS,
    RiskAssessment,
    RiskAssessor,
    RiskLevel,
)

__all__ = [
    "ACTION_RULES",
    "ActionRecord",
    "AuditMode",
    "AuditService",
    "BLOCKED_EXTENSIONS",
    "BLOCKED_PATH_PREFIXES",
    "Decision",
    "DiffSummary",
    "ESCALATE_TO_HIGH_PATHS",
    "Grant",
    "PermissionStore",
    "RiskAssessment",
    "RiskAssessor",
    "RiskLevel",
    "SafetyPolicy",
    "Verdict",
    "binary_diff_summary",
    "is_binary",
    "summarize_write",
    "unified_text_diff",
]
