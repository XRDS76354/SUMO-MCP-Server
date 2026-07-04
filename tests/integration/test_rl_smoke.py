"""Minimal RL training smoke test (Q-Learning via sumo-rl).

Trains 1 episode x tiny step budget on the built-in single-intersection
scenario. Goal is not learning quality — only that the train path executes
end-to-end on this platform. Marked ``requires_rl``.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.requires_rl


@pytest.fixture(autouse=True)
def _ensure_sumo_home(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("SUMO_HOME"):
        return
    from sumo_mcp.utils.sumo import find_sumo_home

    home = find_sumo_home()
    if home:
        monkeypatch.setenv("SUMO_HOME", home)


def test_list_scenarios_returns_builtin_networks() -> None:
    from sumo_mcp.mcp_tools.rl import list_rl_scenarios

    scenarios = list_rl_scenarios()
    text = str(scenarios)
    assert "single-intersection" in text, f"unexpected scenario list: {text[:400]}"


def test_ql_training_smoke(tmp_path: Path) -> None:
    from sumo_mcp.mcp_tools.rl import find_sumo_rl_scenario_files, run_rl_training

    net_file, route_file, err = find_sumo_rl_scenario_files("single-intersection")
    assert err is None, err
    assert net_file and route_file

    result = run_rl_training(
        net_file=net_file,
        route_file=route_file,
        out_dir=str(tmp_path / "rl_out"),
        episodes=1,
        steps_per_episode=50,
        algorithm="ql",
        reward_type="diff-waiting-time",
    )

    assert "Training failed" not in result, result
    assert "Episode 1/1" in result, result
