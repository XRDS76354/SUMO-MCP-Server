"""Unified structured result envelope for all SUMO-MCP tools (v0.2).

Every MCP tool returns a JSON-compatible dict with this shape::

    {
        "ok": bool,                # did the operation succeed
        "tool": str,               # tool name that produced this result
        "action": str | None,      # sub-action / target / method, if the tool has one
        "summary": str,            # human-readable outcome (v0.1's string return lives here)
        "data": dict,              # structured payload specific to the tool
        "artifacts": [             # files produced or expected
            {"path": str, "role": str, "exists": bool, "size_bytes": int | None}
        ],
        "metrics": dict,           # numeric results (waiting time, speeds, rewards, ...)
        "command": list[str],      # subprocess argv when one was executed
        "stdout_tail": str,        # last lines of captured stdout
        "stderr_tail": str,        # last lines of captured stderr
        "warnings": [str],         # non-fatal issues
        "error": {                 # present only when ok is False
            "code": str, "message": str, "remediation": str | None
        },
        "job_id": str,             # present only for async jobs (v0.2 stage 4+)
    }

Only ``ok``, ``tool`` and ``summary`` are always present; other keys are
omitted when empty so agent context stays compact.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence


class ErrorCode:
    """Stable machine-readable error codes shared by all tools."""

    SUMO_NOT_FOUND = "SUMO_NOT_FOUND"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    TIMEOUT = "TIMEOUT"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    SESSION_NOT_FOUND = "SESSION_NOT_FOUND"
    JOB_NOT_FOUND = "JOB_NOT_FOUND"
    GUI_BLOCKED = "GUI_BLOCKED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN = "UNKNOWN"


def artifact(path: str, role: str) -> Dict[str, Any]:
    """Describe one produced/expected file with existence + size stat."""
    exists = os.path.isfile(path)
    size: Optional[int] = None
    if exists:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = None
    return {"path": os.path.abspath(path), "role": role, "exists": exists, "size_bytes": size}


def make_result(
    tool: str,
    summary: str,
    *,
    ok: bool = True,
    action: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    artifacts: Optional[Sequence[Dict[str, Any]]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    command: Optional[Sequence[str]] = None,
    stdout_tail: Optional[str] = None,
    stderr_tail: Optional[str] = None,
    warnings: Optional[Sequence[str]] = None,
    error: Optional[Dict[str, Any]] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the canonical envelope, omitting empty optional fields."""
    result: Dict[str, Any] = {"ok": ok, "tool": tool, "summary": summary}
    if action is not None:
        result["action"] = action
    if data:
        result["data"] = data
    if artifacts:
        result["artifacts"] = list(artifacts)
    if metrics:
        result["metrics"] = metrics
    if command:
        result["command"] = list(command)
    if stdout_tail:
        result["stdout_tail"] = stdout_tail
    if stderr_tail:
        result["stderr_tail"] = stderr_tail
    if warnings:
        result["warnings"] = list(warnings)
    if error:
        result["error"] = error
    if job_id:
        result["job_id"] = job_id
    return result


def make_error(
    tool: str,
    message: str,
    *,
    code: str = ErrorCode.EXECUTION_FAILED,
    action: Optional[str] = None,
    remediation: Optional[str] = None,
    summary: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a failed envelope with a machine-readable error block."""
    error: Dict[str, Any] = {"code": code, "message": message}
    if remediation:
        error["remediation"] = remediation
    return make_result(
        tool,
        summary if summary is not None else message,
        ok=False,
        action=action,
        error=error,
        **extra,
    )


_ERROR_PREFIX = re.compile(r"^\s*(error\b|error:|training failed|failed to|fatal\b)", re.IGNORECASE)


def _infer_error_code(text: str) -> str:
    lowered = text.lower()
    if "sumo_home" in lowered or ("sumo" in lowered and ("locate" in lowered or "installed" in lowered)):
        return ErrorCode.SUMO_NOT_FOUND
    if "no module named" in lowered or "is not installed" in lowered:
        return ErrorCode.DEPENDENCY_MISSING
    if "timed out" in lowered or "timeout" in lowered:
        return ErrorCode.TIMEOUT
    if "not found" in lowered and (".xml" in lowered or "file" in lowered or "scenario" in lowered):
        return ErrorCode.FILE_NOT_FOUND
    if "required" in lowered or "must be" in lowered or "unknown action" in lowered \
            or "unknown workflow" in lowered or "unknown method" in lowered \
            or "unknown target" in lowered or "unknown variable" in lowered:
        return ErrorCode.INVALID_ARGUMENT
    if "connect" in lowered or "connection" in lowered:
        return ErrorCode.CONNECTION_ERROR
    return ErrorCode.EXECUTION_FAILED


def legacy_result(
    tool: str,
    text: str,
    *,
    action: Optional[str] = None,
    artifacts: Optional[Sequence[Dict[str, Any]]] = None,
    data: Optional[Dict[str, Any]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Wrap a v0.1 string return into the envelope.

    Success/failure is inferred from the v0.1 error conventions ("Error: ...",
    "Training failed: ...", per-line "Error" markers). The original string is
    preserved verbatim in ``summary`` so nothing a v0.1 client relied on is lost.
    """
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    failed = bool(_ERROR_PREFIX.match(first_line))
    if failed:
        return make_error(
            tool,
            first_line.strip(),
            code=_infer_error_code(text),
            action=action,
            summary=text,
            data=data,
        )
    return make_result(
        tool,
        text,
        action=action,
        data=data,
        artifacts=artifacts,
        metrics=metrics,
    )


ENVELOPE_ALWAYS_KEYS = ("ok", "tool", "summary")
ENVELOPE_OPTIONAL_KEYS = (
    "action", "data", "artifacts", "metrics", "command",
    "stdout_tail", "stderr_tail", "warnings", "error", "job_id",
)
ENVELOPE_KEYS: List[str] = [*ENVELOPE_ALWAYS_KEYS, *ENVELOPE_OPTIONAL_KEYS]
