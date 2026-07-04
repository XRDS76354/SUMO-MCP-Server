"""MCP stdio protocol smoke tests.

Verifies that every supported launch mode completes the JSON-RPC ``initialize``
handshake and that ``tools/list`` still exposes the full v0.1 tool surface —
i.e. nothing pollutes stdout and no tool got lost in a refactor.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

V01_TOOLS = {
    "manage_network",
    "convert_ezdesignx_network",
    "manage_demand",
    "control_simulation",
    "query_simulation_state",
    "optimize_traffic_signals",
    "run_workflow",
    "manage_rl_task",
    "get_sumo_info",
    "run_simple_simulation",
    "run_analysis",
}


def _rpc(proc: subprocess.Popen, payload: dict) -> None:
    assert proc.stdin is not None
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()


def _read_response(proc: subprocess.Popen) -> dict:
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line, "server closed stdout without responding"
    return json.loads(line)


@pytest.mark.parametrize(
    "launch",
    [
        pytest.param([sys.executable, str(ROOT / "src" / "server.py")], id="shim-script"),
        pytest.param([sys.executable, "-m", "sumo_mcp"], id="python-m"),
    ],
)
def test_stdio_initialize_and_tools_list(launch: list[str]) -> None:
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        launch,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    try:
        _rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        })
        init = _read_response(proc)
        assert init["id"] == 1
        assert init["result"]["serverInfo"]["name"] == "SUMO-MCP-Server"

        _rpc(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})
        _rpc(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools_resp = _read_response(proc)
        names = {t["name"] for t in tools_resp["result"]["tools"]}

        missing = V01_TOOLS - names
        assert not missing, f"v0.1 tools missing from tools/list: {sorted(missing)}"

        # v0.2 envelope over the wire: call a tool with an unknown action
        # (deterministic, requires no SUMO) and verify the structured envelope
        # arrives as parseable JSON.
        _rpc(proc, {
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {
                "name": "manage_network",
                "arguments": {"action": "no_such_action", "output_file": "x"},
            },
        })
        call_resp = _read_response(proc)
        result = call_resp["result"]
        # FastMCP nests dict returns under structuredContent.result; the text
        # block carries the same JSON for clients without structured support.
        structured = result.get("structuredContent") or {}
        envelope = structured.get("result") or json.loads(result["content"][0]["text"])
        assert envelope["ok"] is False
        assert envelope["tool"] == "manage_network"
        assert envelope["summary"] == "Unknown action: no_such_action"
        assert envelope["error"]["code"] == "INVALID_ARGUMENT"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_server_exits_cleanly_on_stdin_eof() -> None:
    """codex-review regression: MCP hosts expect the stdio server to exit on
    client disconnect. Close stdin after the handshake and require a clean,
    unforced process exit (no terminate())."""
    import os

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        [sys.executable, "-m", "sumo_mcp"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    try:
        _rpc(proc, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "0"},
            },
        })
        _read_response(proc)

        assert proc.stdin is not None
        proc.stdin.close()

        returncode = proc.wait(timeout=20)
        assert returncode == 0, f"server exited with {returncode} after stdin EOF"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)
            pytest.fail("server did not exit after stdin EOF (orphan process)")
