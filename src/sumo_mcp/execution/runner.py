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
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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


ProcessCallback = Callable[[Dict[str, Any]], None]


def process_group_id(pid: int) -> Optional[int]:
    if sys.platform == "win32":
        return pid
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_process_tree(pid: int, pgid: Optional[int] = None) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True, timeout=10,
            )
        else:
            if pgid is not None:
                os.killpg(pgid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _kill_process(proc: subprocess.Popen[str]) -> None:
    kill_process_tree(proc.pid, process_group_id(proc.pid))


def run_cli(
    kind: str,
    name: str,
    args: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_s: Optional[float] = None,
    expected_outputs: Optional[List[Dict[str, str]]] = None,
    cancel_event: Optional[threading.Event] = None,
    process_callback: Optional[ProcessCallback] = None,
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

    pgid = process_group_id(proc.pid)
    if process_callback is not None:
        process_callback({"pid": proc.pid, "pgid": pgid, "command": command})

    stdout = ""
    stderr = ""
    cancelled = False
    timed_out = False
    try:
        while True:
            remaining = effective_timeout - (time.monotonic() - started)
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _kill_process(proc)
            if remaining <= 0:
                timed_out = True
                _kill_process(proc)
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancelled or timed_out:
                    continue
        returncode: Optional[int] = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        returncode = None
    duration = time.monotonic() - started

    stdout_tail = (stdout or "")[-_TAIL_CHARS:]
    stderr_tail = (stderr or "")[-_TAIL_CHARS:]
    artifacts = _infer_artifacts(args, cwd, expected_outputs)

    result: Dict[str, Any] = {
        "ok": (not timed_out) and (not cancelled) and returncode == 0,
        "name": name,
        "kind": kind,
        "command": command,
        "returncode": None if timed_out else returncode,
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
    elif cancelled:
        result["error"] = {
            "code": ErrorCode.EXECUTION_FAILED,
            "message": f"{name} was cancelled and its process tree was killed.",
        }
    elif returncode != 0:
        first_err = stderr_tail.strip().splitlines()[0] if stderr_tail.strip() else "no stderr"
        result["error"] = {
            "code": ErrorCode.EXECUTION_FAILED,
            "message": f"{name} exited with code {returncode}: {first_err}",
        }
    return result


def run_command(
    name: str,
    command: List[str],
    *,
    cwd: Optional[str] = None,
    timeout_s: Optional[float] = None,
    expected_outputs: Optional[List[Dict[str, str]]] = None,
    cancel_event: Optional[threading.Event] = None,
    process_callback: Optional[ProcessCallback] = None,
) -> Dict[str, Any]:
    """Run an internal argv command with the same cancellation/output semantics as ``run_cli``.

    This is intentionally not exposed as an MCP tool; public agent-supplied
    commands must still go through the SUMO catalog whitelist. Internal jobs
    (notably RL subprocess training) use this helper to get real process-tree
    cancellation and manifest pid tracking.
    """
    rejection = _validate_args(command)
    if rejection is not None:
        return _error(name, "process", ErrorCode.INVALID_ARGUMENT, rejection)

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    package_root = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = package_root + os.pathsep + env.get("PYTHONPATH", "")
    effective_timeout = timeout_s if timeout_s is not None else DEFAULT_TIMEOUT_S
    popen_kwargs: Dict[str, Any] = {}
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True

    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
            **popen_kwargs,
        )
    except OSError as exc:
        return _error(name, "process", ErrorCode.EXECUTION_FAILED, f"Failed to launch {name}: {exc}")

    pgid = process_group_id(proc.pid)
    if process_callback is not None:
        process_callback({"pid": proc.pid, "pgid": pgid, "command": command})

    stdout = ""
    stderr = ""
    cancelled = False
    timed_out = False
    try:
        while True:
            remaining = effective_timeout - (time.monotonic() - started)
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                _kill_process(proc)
            if remaining <= 0:
                timed_out = True
                _kill_process(proc)
            try:
                stdout, stderr = proc.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancelled or timed_out:
                    continue
        returncode: Optional[int] = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_process(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        returncode = None

    duration = time.monotonic() - started
    stdout_tail = (stdout or "")[-_TAIL_CHARS:]
    stderr_tail = (stderr or "")[-_TAIL_CHARS:]
    artifacts = _infer_artifacts(command[1:], cwd, expected_outputs)
    result: Dict[str, Any] = {
        "ok": (not timed_out) and (not cancelled) and returncode == 0,
        "name": name,
        "kind": "process",
        "command": command,
        "returncode": None if timed_out else returncode,
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
        }
    elif cancelled:
        result["error"] = {
            "code": ErrorCode.EXECUTION_FAILED,
            "message": f"{name} was cancelled and its process tree was killed.",
        }
    elif returncode != 0:
        first_err = stderr_tail.strip().splitlines()[0] if stderr_tail.strip() else "no stderr"
        result["error"] = {
            "code": ErrorCode.EXECUTION_FAILED,
            "message": f"{name} exited with code {returncode}: {first_err}",
        }
    return result
