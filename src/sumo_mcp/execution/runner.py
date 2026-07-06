"""Structured subprocess runner for whitelisted SUMO commands.

Security model (the only way agent-supplied arguments reach a process):
- command names resolve through the catalog whitelist (never raw paths);
- arguments are an argv list handed to ``subprocess.Popen`` without a shell,
  so shell metacharacters are inert;
- a small flag blacklist stops arguments that would open sockets or execute
  arbitrary code from inside SUMO;
- GUI commands are refused unless ``SUMO_MCP_ALLOW_GUI`` is set (a headless
  MCP host would just hang a window nobody can see);
- stdout/stderr are captured (never inherited), keeping MCP stdio clean.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from sumo_mcp.catalog import resolve_command
from sumo_mcp.catalog.curated import GUI_COMMANDS
from sumo_mcp.models import ErrorCode, artifact

DEFAULT_TIMEOUT_S = 600.0
_TAIL_CHARS = 4000

# Flags that must never come from an agent: --remote-port opens a TraCI socket
# (session management owns that); --python-script executes arbitrary code.
FORBIDDEN_FLAGS = frozenset({"--remote-port", "--python-script"})

# CLI flags whose value names an output file — used to infer artifacts when
# the caller didn't declare expected_outputs explicitly.
KNOWN_OUTPUT_FLAGS: Dict[str, str] = {
    "-o": "output",
    "--output": "output",
    "--output-file": "output",
    "--output-prefix": "output",
    "--fcd-output": "fcd",
    "--tripinfo-output": "tripinfo",
    "--summary-output": "summary",
    "--summary": "summary",
    "--emission-output": "emission",
    "--queue-output": "queue",
    "--vehroute-output": "vehroute",
    "--netstate-dump": "netstate",
    "--statistic-output": "statistics",
    "--log": "log",
    "--error-log": "error_log",
    "--plain-output-prefix": "plain_output",
    "--route-output": "routes",
    "--weight-output": "weights",
}


def _error(name: str, kind: str, code: str, message: str,
           remediation: Optional[str] = None) -> Dict[str, Any]:
    error: Dict[str, Any] = {"code": code, "message": message}
    if remediation:
        error["remediation"] = remediation
    return {
        "ok": False, "name": name, "kind": kind, "command": [],
        "returncode": None, "duration_s": 0.0,
        "stdout_tail": "", "stderr_tail": "", "artifacts": [],
        "error": error,
    }


def _gui_allowed() -> bool:
    return os.environ.get("SUMO_MCP_ALLOW_GUI", "").lower() in ("1", "true", "yes")


def _validate_args(args: List[str]) -> Optional[str]:
    """Return a rejection message, or None if args are acceptable."""
    if not isinstance(args, list) or any(not isinstance(a, str) for a in args):
        return "args must be a list of strings (argv form, no shell parsing)"
    for arg in args:
        flag = arg.split("=", 1)[0].lower()
        if flag in FORBIDDEN_FLAGS:
            return (
                f"argument {arg!r} is not allowed: use the session tools for TraCI "
                "connections instead of raw --remote-port, and never --python-script"
            )
    return None


def _infer_artifacts(args: List[str], cwd: Optional[str],
                     expected_outputs: Optional[List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    base = Path(cwd) if cwd else Path.cwd()

    def _abs(p: str) -> str:
        path = Path(p)
        return str(path if path.is_absolute() else base / path)

    if expected_outputs:
        return [artifact(_abs(item["path"]), item.get("role", "output")) for item in expected_outputs]

    found: List[Dict[str, Any]] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if "=" in arg:
            flag, value = arg.split("=", 1)
            role = KNOWN_OUTPUT_FLAGS.get(flag)
            if role and value:
                found.append(artifact(_abs(value), role))
        else:
            role = KNOWN_OUTPUT_FLAGS.get(arg)
            if role and i + 1 < len(args) and not args[i + 1].startswith("-"):
                found.append(artifact(_abs(args[i + 1]), role))
                i += 1
        i += 1
    return found


def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True, timeout=10,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


def run_cli(
    kind: str,
    name: str,
    args: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_s: Optional[float] = None,
    expected_outputs: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Execute one whitelisted SUMO command and return a structured report.

    Returns a dict with: ok, name, kind, command, returncode, duration_s,
    stdout_tail, stderr_tail, artifacts, error (None on success).
    """
    if kind not in ("binary", "tool"):
        return _error(name, kind, ErrorCode.INVALID_ARGUMENT,
                      f"kind must be 'binary' or 'tool', got {kind!r}")

    rejection = _validate_args(args)
    if rejection is not None:
        return _error(name, kind, ErrorCode.INVALID_ARGUMENT, rejection)

    spec = resolve_command(name, kind=kind)
    if spec is None:
        return _error(
            name, kind, ErrorCode.INVALID_ARGUMENT,
            f"Unknown {kind} {name!r}: not in the SUMO command whitelist.",
            remediation="Use list_sumo_commands to browse available commands.",
        )
    if not spec.available or spec.path is None:
        return _error(
            name, kind, ErrorCode.SUMO_NOT_FOUND,
            f"{name!r} is not available in this SUMO installation.",
            remediation="Check get_sumo_info diagnostics; set SUMO_HOME or install SUMO.",
        )

    if name in GUI_COMMANDS and not _gui_allowed():
        return _error(
            name, kind, ErrorCode.GUI_BLOCKED,
            f"{name!r} opens a GUI window, which is blocked for headless MCP use.",
            remediation="Prefer the headless equivalent (sumo, netconvert). To really "
                        "allow GUIs, set SUMO_MCP_ALLOW_GUI=1 in the server environment.",
        )

    if kind == "binary":
        command = [spec.path, *args]
    else:
        command = [sys.executable, spec.path, *args]

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")

    effective_timeout = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
    popen_kwargs: Dict[str, Any] = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True  # own process group for tree-kill

    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **popen_kwargs,
        )
    except OSError as exc:
        return _error(name, kind, ErrorCode.EXECUTION_FAILED,
                      f"Failed to launch {name}: {exc}")

    try:
        stdout, stderr = proc.communicate(timeout=effective_timeout)
        returncode: Optional[int] = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        returncode = None
        timed_out = True
    duration = time.monotonic() - started

    stdout_tail = (stdout or "")[-_TAIL_CHARS:]
    stderr_tail = (stderr or "")[-_TAIL_CHARS:]
    artifacts = _infer_artifacts(args, cwd, expected_outputs)

    result: Dict[str, Any] = {
        "ok": (not timed_out) and returncode == 0,
        "name": name,
        "kind": kind,
        "command": command,
        "returncode": returncode,
        "duration_s": round(duration, 3),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "artifacts": artifacts,
        "error": None,
    }
    if timed_out:
        result["error"] = {
            "code": ErrorCode.TIMEOUT,
            "message": f"{name} timed out after {effective_timeout:.0f}s and was killed.",
            "remediation": "Increase timeout_s, or run it as a background job "
                           "(background=true) and poll manage_sumo_jobs.",
        }
    elif returncode != 0:
        first_err = stderr_tail.strip().splitlines()[0] if stderr_tail.strip() else "no stderr"
        result["error"] = {
            "code": ErrorCode.EXECUTION_FAILED,
            "message": f"{name} exited with code {returncode}: {first_err}",
        }
    return result
