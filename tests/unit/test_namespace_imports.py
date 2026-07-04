"""Regression tests for the v0.2 ``sumo_mcp`` namespace migration.

Guards against stale top-level imports (``utils``, ``mcp_tools``, ``workflows``)
surviving anywhere in the package — including lazy imports buried inside
function bodies, which a plain module-import test would not execute.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC_PKG = Path(__file__).resolve().parents[2] / "src" / "sumo_mcp"
LEGACY_TOP_LEVEL = {"utils", "mcp_tools", "workflows", "resources", "server"}


def _iter_import_roots(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            # ``from . import x`` has module=None / level>0 -> relative, fine.
            if node.level == 0 and node.module:
                yield node.lineno, node.module.split(".")[0]


def test_no_stale_legacy_imports_anywhere() -> None:
    offenders: list[str] = []
    for py_file in sorted(SRC_PKG.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for lineno, root in _iter_import_roots(tree):
            if root in LEGACY_TOP_LEVEL:
                offenders.append(f"{py_file.relative_to(SRC_PKG.parent)}:{lineno}: imports '{root}'")
    assert not offenders, (
        "Stale pre-v0.2 top-level imports found (must use 'sumo_mcp.*'):\n" + "\n".join(offenders)
    )


def test_rl_training_entry_does_not_hit_module_not_found(tmp_path: Path) -> None:
    """codex-review regression: run_rl_training() must fail on missing inputs,
    never on the package's own module layout."""
    from sumo_mcp.mcp_tools.rl import run_rl_training

    result = run_rl_training(
        net_file=str(tmp_path / "missing.net.xml"),
        route_file=str(tmp_path / "missing.rou.xml"),
        out_dir=str(tmp_path / "out"),
        episodes=1,
        steps_per_episode=1,
        algorithm="ql",
        reward_type="diff-waiting-time",
    )

    assert "No module named 'utils'" not in result
    assert "No module named 'mcp_tools'" not in result
    assert "No module named 'sumo_mcp" not in result
