"""Unit tests for the safe CLI runner (no SUMO required).

Real subprocesses are exercised with tiny ``python -c`` stand-ins so that
timeout/kill, exit-code and output-capture behavior is genuinely tested.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import pytest

import sumo_mcp.execution.runner as runner_mod
from sumo_mcp.catalog.registry import CommandSpec
from sumo_mcp.execution.runner import run_cli
from sumo_mcp.models import ErrorCode


def _spec(name: str, kind: str, path: Optional[str], available: bool = True) -> CommandSpec:
    return CommandSpec(name=name, kind=kind, tier=1, category="test",
                       description="", available=available, path=path)


@pytest.fixture()
def fake_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Register a fake whitelisted 'tool' backed by a real tiny python script."""
    script = tmp_path / "fake_tool.py"
    script.write_text(
        "import sys, time\n"
        "if '--sleep' in sys.argv: time.sleep(30)\n"
        "if '--fail' in sys.argv: print('boom', file=sys.stderr); sys.exit(3)\n"
        "print('tool ran ok')\n"
    )

    def fake_resolve(name: str, kind: Optional[str] = None) -> Optional[CommandSpec]:
        if name == "fake_tool.py":
            return _spec(name, "tool", str(script))
        if name == "missing_tool.py":
            return _spec(name, "tool", None, available=False)
        return None

    monkeypatch.setattr(runner_mod, "resolve_command", fake_resolve)
    return script


# --- security boundaries -------------------------------------------------------


def test_rejects_non_list_and_non_str_args(fake_tool: Path) -> None:
    result = run_cli("tool", "fake_tool.py", "not-a-list")  # type: ignore[arg-type]
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_ARGUMENT

    result = run_cli("tool", "fake_tool.py", ["fine", 42])  # type: ignore[list-item]
    assert result["ok"] is False and result["error"]["code"] == ErrorCode.INVALID_ARGUMENT


@pytest.mark.parametrize("bad_arg", [
    "--remote-port", "--remote-port=9999", "--REMOTE-PORT", "--python-script",
    "--python-script=/tmp/evil.py",
])
def test_forbidden_flags_blocked(fake_tool: Path, bad_arg: str) -> None:
    result = run_cli("tool", "fake_tool.py", [bad_arg])
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_ARGUMENT
    assert "not allowed" in result["error"]["message"]


def test_unknown_command_rejected(fake_tool: Path) -> None:
    result = run_cli("tool", "rm", ["-rf", "/"])
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INVALID_ARGUMENT
    assert "whitelist" in result["error"]["message"]


def test_unavailable_command_reports_sumo_not_found(fake_tool: Path) -> None:
    result = run_cli("tool", "missing_tool.py", [])
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.SUMO_NOT_FOUND


def test_bad_kind_rejected(fake_tool: Path) -> None:
    result = run_cli("shell", "fake_tool.py", [])
    assert result["ok"] is False and result["error"]["code"] == ErrorCode.INVALID_ARGUMENT


def test_gui_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    gui_bin = tmp_path / "sumo-gui"
    gui_bin.write_text("")

    monkeypatch.setattr(
        runner_mod, "resolve_command",
        lambda name, kind=None: _spec("sumo-gui", "binary", str(gui_bin)),
    )
    monkeypatch.delenv("SUMO_MCP_ALLOW_GUI", raising=False)

    result = run_cli("binary", "sumo-gui", [])
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.GUI_BLOCKED
    assert "SUMO_MCP_ALLOW_GUI" in result["error"]["remediation"]


# --- real subprocess behavior ----------------------------------------------------


def test_successful_run_captures_output(fake_tool: Path) -> None:
    result = run_cli("tool", "fake_tool.py", [])
    assert result["ok"] is True
    assert result["returncode"] == 0
    assert "tool ran ok" in result["stdout_tail"]
    assert result["command"][0] == sys.executable
    assert result["duration_s"] >= 0
    assert result["error"] is None


def test_nonzero_exit_reports_execution_failed(fake_tool: Path) -> None:
    result = run_cli("tool", "fake_tool.py", ["--fail"])
    assert result["ok"] is False
    assert result["returncode"] == 3
    assert result["error"]["code"] == ErrorCode.EXECUTION_FAILED
    assert "boom" in result["error"]["message"]
    assert "boom" in result["stderr_tail"]


def test_timeout_kills_process(fake_tool: Path) -> None:
    result = run_cli("tool", "fake_tool.py", ["--sleep"], timeout_s=1.5)
    assert result["ok"] is False
    assert result["returncode"] is None
    assert result["error"]["code"] == ErrorCode.TIMEOUT
    assert "background" in result["error"]["remediation"]
    assert result["duration_s"] < 15  # killed, not waited out


# --- artifact inference -----------------------------------------------------------


def test_artifact_inference_from_flags(fake_tool: Path, tmp_path: Path) -> None:
    out_a = tmp_path / "net.net.xml"
    result = run_cli("tool", "fake_tool.py",
                     ["-o", str(out_a), "--fcd-output=" + str(tmp_path / "fcd.xml")])
    roles = {a["role"]: a for a in result["artifacts"]}
    assert set(roles) == {"output", "fcd"}
    assert roles["output"]["path"] == str(out_a)
    assert roles["output"]["exists"] is False


def test_artifact_flag_without_value_ignored(fake_tool: Path) -> None:
    result = run_cli("tool", "fake_tool.py", ["-o", "--fail"])
    # "-o" followed by another flag must not swallow it as a filename
    assert result["artifacts"] == []


def test_relative_artifact_resolved_against_cwd(fake_tool: Path, tmp_path: Path) -> None:
    result = run_cli("tool", "fake_tool.py", ["-o", "rel.xml"], cwd=str(tmp_path))
    assert result["artifacts"][0]["path"] == str(tmp_path / "rel.xml")


def test_expected_outputs_take_precedence(fake_tool: Path, tmp_path: Path) -> None:
    declared = tmp_path / "declared.xml"
    declared.write_text("<x/>")
    result = run_cli(
        "tool", "fake_tool.py", ["-o", str(tmp_path / "ignored.xml")],
        expected_outputs=[{"path": str(declared), "role": "network"}],
    )
    assert len(result["artifacts"]) == 1
    art = result["artifacts"][0]
    assert art["role"] == "network" and art["exists"] is True and art["size_bytes"] > 0
