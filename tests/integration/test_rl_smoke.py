"""Minimal RL training smoke test (Q-Learning via sumo-rl).

Trains 1 episode x tiny step budget on the built-in single-intersection
scenario. Goal is not learning quality — only that the train path executes
end-to-end on this platform. Marked ``requires_rl``.
"""
from __future__ import annotations

import os
import time
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


def test_ql_training_job_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sumo_mcp.server as srv

    monkeypatch.setenv("SUMO_MCP_JOBS_DIR", str(tmp_path / "jobs"))
    env = srv.manage_rl_task("train", {
        "scenario": "single-intersection",
        "episodes": 1,
        "steps_per_episode": 50,
        "output_dir": str(tmp_path / "runs"),
        "algorithm": "ql",
        "timeout_s": 120,
    })
    assert env["ok"] is True, env
    job_id = env["job_id"]
    run_dir = Path(env["data"]["run"]["run_dir"])

    deadline = time.monotonic() + 120
    status = {}
    while time.monotonic() < deadline:
        status_env = srv.manage_rl_task("status", {"job_id": job_id, "run_dir": str(run_dir)})
        assert status_env["ok"] is True, status_env
        status = status_env["data"]["job"]
        if status["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.5)

    assert status.get("status") == "succeeded", status
    manifest = srv.manage_rl_task("status", {"run_dir": str(run_dir)})["data"]["run"]
    assert manifest["status"] == "succeeded"
    assert Path(manifest["config_file"]).is_file()
    assert Path(manifest["metrics_file"]).is_file()
    assert Path(manifest["latest_checkpoint"]).is_file()

    eval_env = srv.manage_rl_task("evaluate", {"run_dir": str(run_dir), "episodes": 1})
    assert eval_env["ok"] is True, eval_env
    assert "mean_total_reward" in eval_env["metrics"]

    compare_env = srv.manage_rl_task("compare", {"run_dir": str(run_dir), "episodes": 1})
    assert compare_env["ok"] is True, compare_env
    assert "mean_reward_delta" in compare_env["metrics"]
