"""Unit tests for v0.2 RL preflight, run manifests, and job wiring."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

import sumo_mcp.rl.preflight as preflight
import sumo_mcp.rl.evaluation as evaluation
import sumo_mcp.rl.train_entry as train_entry
import sumo_mcp.server as srv
from sumo_mcp.models import ErrorCode
from sumo_mcp.rl.runs import create_run, latest_checkpoint, list_runs, load_config, load_run, update_run


def _write_pair(tmp_path: Path, *, tls: bool = True, demand: bool = True) -> tuple[str, str]:
    net = tmp_path / "net.net.xml"
    route = tmp_path / "routes.rou.xml"
    net.write_text(
        "<net>"
        + ("<tlLogic id='J0' type='static' programID='0' offset='0'>"
           "<phase duration='31' state='Gr'/></tlLogic>" if tls else "")
        + "</net>",
        encoding="utf-8",
    )
    route.write_text(
        "<routes>" + ("<vehicle id='v0' depart='0'><route edges='e0'/></vehicle>" if demand else "") + "</routes>",
        encoding="utf-8",
    )
    return str(net), str(route)


@pytest.fixture()
def _preflight_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight, "find_sumo_home", lambda: "/sumo")
    monkeypatch.setattr(preflight, "find_sumo_binary", lambda name: f"/sumo/bin/{name}")
    monkeypatch.setattr(preflight, "find_spec", lambda name: object())


def test_preflight_passes_valid_tls_network(tmp_path: Path, _preflight_env: None) -> None:
    net, route = _write_pair(tmp_path)
    report = preflight.validate_rl_environment(net, route, algorithm="ql", delta_time=5, yellow_time=2)
    assert report["ok"] is True
    assert {c["check"] for c in report["checks"]} >= {"traffic_lights", "green_phases", "demand"}


def test_preflight_reports_missing_tls_and_bad_timing(tmp_path: Path, _preflight_env: None) -> None:
    net, route = _write_pair(tmp_path, tls=False)
    report = preflight.validate_rl_environment(net, route, delta_time=2, yellow_time=2)
    assert report["ok"] is False
    failed = {c["check"]: c for c in report["failed_checks"]}
    assert failed["traffic_lights"]["code"] == ErrorCode.VALIDATION_FAILED
    assert failed["timing"]["code"] == ErrorCode.INVALID_ARGUMENT


def test_preflight_reports_empty_demand(tmp_path: Path, _preflight_env: None) -> None:
    net, route = _write_pair(tmp_path, demand=False)
    report = preflight.validate_rl_environment(net, route)
    assert report["ok"] is False
    assert any(c["check"] == "demand" for c in report["failed_checks"])


def test_run_manifest_lifecycle(tmp_path: Path) -> None:
    manifest = create_run(str(tmp_path), {"algorithm": "ql", "episodes": 2}, run_id="run-a")
    run_dir = Path(manifest["run_dir"])
    assert load_config(str(run_dir))["episodes"] == 2
    assert load_run(str(run_dir))["status"] == "created"

    updated = update_run(str(run_dir), {"status": "running", "episodes_done": 1})
    assert updated["episodes_done"] == 1
    assert list_runs(str(tmp_path))[0]["run_id"] == "run-a"
    assert latest_checkpoint(str(run_dir)) is None
    ckpt = run_dir / "checkpoints" / "q.pkl"
    ckpt.write_text("x")
    assert latest_checkpoint(str(run_dir)) == str(ckpt)


def test_manage_rl_task_list_algorithms() -> None:
    env = srv.manage_rl_task("list_algorithms")
    assert env["ok"] is True
    assert any(a["name"] == "ql" and a["available"] for a in env["data"]["algorithms"])


def test_manage_rl_task_validate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    net, route = _write_pair(tmp_path)
    monkeypatch.setattr(srv, "validate_rl_environment", lambda **kwargs: {
        "ok": True, "summary": "passed", "checks": [], "failed_checks": [], "kwargs": kwargs,
    })
    env = srv.manage_rl_task("validate_env", {"net_file": net, "route_file": route, "delta_time": 7})
    assert env["ok"] is True
    assert env["data"]["kwargs"]["delta_time"] == 7


def test_manage_rl_task_train_starts_process_job(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    net, route = _write_pair(tmp_path)
    captured: Dict[str, Any] = {}
    monkeypatch.setattr(srv, "validate_rl_environment", lambda **kwargs: {
        "ok": True, "summary": "passed", "checks": [], "failed_checks": [],
    })

    def fake_start_process_job(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return {"job_id": "job123", "job_dir": str(tmp_path / "jobs" / "job123"), "label": kwargs["label"],
                "status": "pending"}

    monkeypatch.setattr(srv.job_manager, "start_process_job", fake_start_process_job)
    env = srv.manage_rl_task("train", {
        "net_file": net, "route_file": route, "episodes": 2,
        "steps_per_episode": 50, "output_dir": str(tmp_path / "runs"),
    })
    assert env["ok"] is True
    assert env["job_id"] == "job123"
    assert captured["command"][1:4] == ["-m", "sumo_mcp.rl.train_entry", env["data"]["run"]["run_dir"]]
    assert env["data"]["run"]["job_id"] == "job123"


def test_manage_rl_task_train_rejects_failed_preflight(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    net, route = _write_pair(tmp_path)
    monkeypatch.setattr(srv, "validate_rl_environment", lambda **kwargs: {
        "ok": False,
        "summary": "bad",
        "checks": [],
        "failed_checks": [{"check": "traffic_lights", "passed": False, "code": ErrorCode.VALIDATION_FAILED}],
    })
    env = srv.manage_rl_task("train", {"net_file": net, "route_file": route})
    assert env["ok"] is False
    assert env["error"]["code"] == ErrorCode.VALIDATION_FAILED


def test_manage_rl_task_status_stop_and_list_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = create_run(str(tmp_path / "runs"), {"algorithm": "ql"}, run_id="r1")
    monkeypatch.setattr(srv.job_manager, "get_status", lambda job_id: {"job_id": job_id, "status": "running"})
    monkeypatch.setattr(srv.job_manager, "cancel", lambda job_id: {"job_id": job_id, "status": "cancelled"})

    env = srv.manage_rl_task("status", {"run_dir": run["run_dir"], "job_id": "j1"})
    assert env["ok"] is True and env["data"]["job"]["status"] == "running"
    env = srv.manage_rl_task("stop", {"job_id": "j1"})
    assert env["ok"] is True and env["data"]["job"]["status"] == "cancelled"
    env = srv.manage_rl_task("list_runs", {"out_dir": str(tmp_path / "runs")})
    assert env["ok"] is True and env["data"]["runs"][0]["run_id"] == "r1"


def test_train_entry_updates_run_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    run = create_run(str(tmp_path), {
        "net_file": "n.net.xml", "route_file": "r.rou.xml", "algorithm": "ql",
        "episodes": 1, "steps_per_episode": 10, "reward_type": "diff-waiting-time",
    }, run_id="entry")
    run_dir = Path(run["run_dir"])
    (run_dir / "train_results_conn0_ep1.csv").write_text("episode,reward\n1,-1\n", encoding="utf-8")

    def fake_train(**kwargs):
        assert kwargs["checkpoint_dir"] == str(run_dir / "checkpoints")
        (run_dir / "checkpoints" / "q_table_ep1.pkl").write_bytes(b"pickle-ish")
        return "Episode 1/1: Total Reward = -1.00"

    monkeypatch.setattr(train_entry, "run_rl_training", fake_train)
    rc = train_entry.main([str(run_dir)])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    manifest = load_run(str(run_dir))
    assert manifest["status"] == "succeeded"
    assert Path(manifest["metrics_file"]).is_file()
    assert Path(manifest["latest_checkpoint"]).name == "q_table_ep1.pkl"


def test_resume_sets_latest_checkpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = create_run(str(tmp_path / "runs"), {
        "net_file": "n", "route_file": "r", "algorithm": "ql", "episodes": 1,
    }, run_id="resume")
    ckpt = Path(run["run_dir"]) / "checkpoints" / "q_table_ep1.pkl"
    ckpt.write_text("x")
    captured: Dict[str, Any] = {}
    monkeypatch.setattr(srv.job_manager, "start_process_job", lambda command, **kwargs: captured.setdefault(
        "job", {"job_id": "resume-job", "job_dir": "j", "label": kwargs["label"], "status": "pending"}
    ))

    env = srv.manage_rl_task("resume", {"run_dir": run["run_dir"], "episodes": 3})
    assert env["ok"] is True
    assert load_config(run["run_dir"])["resume_checkpoint"] == str(ckpt)


class _FakeEvalEnv:
    delta_time = 1
    ts_ids = ["tls0"]

    def __init__(self) -> None:
        self.steps = 0

    def reset(self):
        self.steps = 0
        return {"tls0": "s0"}

    def encode(self, obs, ts_id):
        return obs

    def step(self, actions):
        self.steps += 1
        reward = 10.0 if actions == {"tls0": 1} else 1.0
        done = self.steps >= 1
        return {"tls0": "s1"}, {"tls0": reward}, {"__all__": done, "tls0": done}, {}

    def close(self) -> None:
        pass


def test_evaluate_and_compare_with_fake_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pickle

    run = create_run(str(tmp_path / "runs"), {
        "net_file": "n", "route_file": "r", "algorithm": "ql", "steps_per_episode": 5,
    }, run_id="eval")
    ckpt = Path(run["run_dir"]) / "checkpoints" / "q_table_ep1.pkl"
    with ckpt.open("wb") as f:
        pickle.dump({"q_tables": {"tls0": {"s0": [0.0, 5.0]}}}, f)
    update_run(run["run_dir"], {"latest_checkpoint": str(ckpt), "final_model": str(ckpt)})
    monkeypatch.setattr(evaluation, "_make_env", lambda config, run_dir: _FakeEvalEnv())

    result = evaluation.evaluate_run(run["run_dir"], episodes=1)
    assert result["ok"] is True
    assert result["metrics"]["mean_total_reward"] == 10.0
    result = evaluation.compare_run(run["run_dir"], episodes=1)
    assert result["ok"] is True
    assert result["metrics"]["mean_reward_delta"] == 9.0


def test_manage_rl_task_evaluate_and_compare(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    run = create_run(str(tmp_path / "runs"), {"algorithm": "ql"}, run_id="eval-action")
    eval_file = Path(run["run_dir"]) / "evaluation.json"
    eval_file.write_text("{}")
    monkeypatch.setattr(srv, "evaluate_run", lambda *a, **k: {
        "ok": True, "summary": "evaluated", "metrics": {"mean_total_reward": 1.0}, "artifact": str(eval_file),
    })
    monkeypatch.setattr(srv, "compare_run", lambda *a, **k: {
        "ok": True, "summary": "compared", "metrics": {"mean_reward_delta": 1.0}, "artifact": str(eval_file),
    })
    env = srv.manage_rl_task("evaluate", {"run_dir": run["run_dir"]})
    assert env["ok"] is True and env["metrics"]["mean_total_reward"] == 1.0
    env = srv.manage_rl_task("compare", {"run_dir": run["run_dir"]})
    assert env["ok"] is True and env["metrics"]["mean_reward_delta"] == 1.0
