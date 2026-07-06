"""Tests for SUMO-MCP skill source and installer layout."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sumo_mcp.resources.provider import PUBLIC_TOOLS


ROOT = Path(__file__).resolve().parents[2]


def test_skill_sources_reference_current_tool_surface() -> None:
    src = ROOT / "skills" / "src"
    skills = sorted(src.glob("*/SKILL.md"))
    assert len(skills) == 7
    stale_names = {"inspect_sumo_installation", "run_sumo_workflow_v2", "rl_start_training"}
    known_tools = set(PUBLIC_TOOLS)
    text = "\n".join(path.read_text(encoding="utf-8") for path in skills)
    for stale in stale_names:
        assert stale not in text
    assert "`manage_rl_task`" in text
    assert "`manage_network`" in text
    for tool in ("manage_rl_task", "manage_network", "run_sumo_binary", "analyze_sumo_output"):
        assert tool in known_tools


def test_install_skills_generates_codex_and_claude_layouts(tmp_path: Path) -> None:
    codex_dir = tmp_path / "codex"
    claude_dir = tmp_path / "claude"
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "skills" / "install_skills.py"),
            "--target",
            "both",
            "--codex-dir",
            str(codex_dir),
            "--claude-dir",
            str(claude_dir),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "sumo-rl-experiments" in proc.stdout
    for root in (codex_dir, claude_dir):
        installed = sorted(path.parent.name for path in root.glob("*/SKILL.md"))
        assert installed == [
            "sumo-demand-routing",
            "sumo-network-build",
            "sumo-online-simulation",
            "sumo-orchestrator",
            "sumo-output-analysis",
            "sumo-rl-experiments",
            "sumo-signal-optimization",
        ]
