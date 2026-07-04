"""Contract regression tests for the 11 v0.1 tools after the v0.2 envelope upgrade.

Locks down, per tool:
- every documented action/target/method/workflow alias keeps working;
- parameter aliases (end/end_time, scenario/scenario_name, timeout/timeout_s, ...)
  keep resolving to the same underlying call;
- error paths return an `ok=False` envelope with a machine-readable error code
  instead of raising or returning a bare string;
- the envelope shape stays canonical (no unknown keys, required keys present).

Underlying SUMO calls are monkeypatched — no SUMO installation required.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

import sumo_mcp.server as srv
from sumo_mcp.models import ENVELOPE_KEYS, ErrorCode


def check_envelope(env: Dict[str, Any]) -> None:
    assert isinstance(env, dict)
    for key in ("ok", "tool", "summary"):
        assert key in env, f"envelope missing required key {key}: {env}"
    unknown = set(env) - set(ENVELOPE_KEYS)
    assert not unknown, f"envelope has unknown keys {unknown}"
    if not env["ok"]:
        assert "error" in env and env["error"].get("code"), f"failed envelope lacks error.code: {env}"


# --- manage_network -------------------------------------------------------


def test_manage_network_generate_grid(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls = {}

    def fake_netgenerate(output_file, grid, grid_number, options):
        calls.update(output_file=output_file, grid=grid, grid_number=grid_number, options=options)
        return "Netgenerate OK"

    monkeypatch.setattr(srv, "netgenerate", fake_netgenerate)
    out = str(tmp_path / "net.net.xml")
    env = srv.manage_network("generate", out, {"grid": True, "grid_number": 4})

    check_envelope(env)
    assert env["ok"] is True
    assert env["summary"] == "Netgenerate OK"
    assert calls == {"output_file": out, "grid": True, "grid_number": 4, "options": None}
    assert env["artifacts"][0]["role"] == "network"
    assert env["artifacts"][0]["exists"] is False  # fake didn't create it


def test_manage_network_spider_aliases_and_flag_injection(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured = {}

    def fake_netgenerate(output_file, grid, grid_number, options):
        captured["grid"] = grid
        captured["options"] = options
        return "OK"

    monkeypatch.setattr(srv, "netgenerate", fake_netgenerate)
    # v0.1 double aliases: arm_number, circle_number, space_radius, attach_length
    env = srv.manage_network("generate", str(tmp_path / "s.net.xml"), {
        "spider": True, "arm_number": 6, "circle_number": 4,
        "space_radius": 80, "attach_length": 50, "omit_center": True,
        "options": ["--grid", "--grid.number", "5"],  # must be stripped
    })

    check_envelope(env)
    assert env["ok"] is True
    assert captured["grid"] is False
    opts = captured["options"]
    assert "--grid" not in opts and "5" not in opts
    assert opts[0] == "--spider"
    for flag, value in (("--spider.arm-number", "6"), ("--spider.circle-number", "4"),
                        ("--spider.space-radius", "80.0"), ("--spider.attach-length", "50.0")):
        assert value == opts[opts.index(flag) + 1]
    assert "--spider.omit-center" in opts


@pytest.mark.parametrize("bad_params, message_part", [
    ({"spider": True, "arms": "many"}, "arms must be a positive integer"),
    ({"spider": True, "arms": 0}, "arms must be > 0"),
    ({"spider": True, "circles": -1}, "circles must be > 0"),
    ({"spider": True, "ring_radius": "wide"}, "ring_radius must be a number"),
    ({"spider": True, "radial_distance": -2}, "radial_distance must be >= 0"),
])
def test_manage_network_spider_validation_errors(bad_params, message_part, tmp_path) -> None:
    env = srv.manage_network("generate", str(tmp_path / "x.net.xml"), bad_params)
    check_envelope(env)
    assert env["ok"] is False
    assert env["error"]["code"] == ErrorCode.INVALID_ARGUMENT
    assert message_part in env["summary"]


def test_manage_network_convert_osm_alias(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(srv, "netconvert", lambda osm, out, options: "Converted")
    for alias in ("convert", "convert_osm"):
        env = srv.manage_network(alias, str(tmp_path / "n.net.xml"), {"osm_file": "map.osm"})
        check_envelope(env)
        assert env["ok"] is True and env["summary"] == "Converted"

    env = srv.manage_network("convert", str(tmp_path / "n.net.xml"), {})
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.INVALID_ARGUMENT


def test_manage_network_download_osm_requires_bbox(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env = srv.manage_network("download_osm", str(tmp_path), {})
    check_envelope(env)
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.INVALID_ARGUMENT

    monkeypatch.setattr(srv, "osm_get", lambda bbox, out, prefix, options: "Downloaded")
    env = srv.manage_network("download_osm", str(tmp_path), {"bbox": "1,2,3,4"})
    assert env["ok"] is True
    assert env["data"]["bbox"] == "1,2,3,4" and env["data"]["prefix"] == "osm"


def test_manage_network_unknown_action(tmp_path) -> None:
    env = srv.manage_network("teleport", str(tmp_path / "x"), {})
    check_envelope(env)
    assert env["ok"] is False
    assert env["error"]["code"] == ErrorCode.INVALID_ARGUMENT
    assert env["summary"] == "Unknown action: teleport"


# --- convert_ezdesignx_network (dedicated tool + manage_network action) ----


def test_convert_ezdesignx_delegates_and_wraps(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    seen = {}

    def fake_summary(**kwargs):
        seen.update(kwargs)
        return "converted"

    monkeypatch.setattr(srv, "convert_ezdesignx_network_summary", fake_summary)
    env = srv.convert_ezdesignx_network(
        input_json="a.jsonc", output_dir=str(tmp_path), validation="strict",
    )
    check_envelope(env)
    assert env["ok"] is True and env["summary"] == "converted"
    assert seen["input_json"] == "a.jsonc" and seen["validation"] == "strict"

    env = srv.manage_network("convert_ezdesignx", str(tmp_path), {"input_json": "a.jsonc"})
    assert env["ok"] is True and env["summary"] == "converted"
    assert seen["validation"] == "topology"  # default preserved


# --- manage_demand ---------------------------------------------------------


def test_manage_demand_random_trips_aliases(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    captured = {}

    def fake_random_trips(net, out, end_time, period, options):
        captured.update(end_time=end_time, period=period)
        return "Trips OK"

    monkeypatch.setattr(srv, "random_trips", fake_random_trips)
    out = str(tmp_path / "t.trips.xml")

    # action alias + `end` param alias
    env = srv.manage_demand("random_trips", "n.net.xml", out, {"end": 120, "period": 2})
    check_envelope(env)
    assert env["ok"] is True and captured == {"end_time": 120, "period": 2.0}

    env = srv.manage_demand("generate_random", "n.net.xml", out, None)
    assert captured == {"end_time": 3600, "period": 1.0}  # defaults

    env = srv.manage_demand("generate_random", "n.net.xml", out, {"end_time": "soon"})
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.INVALID_ARGUMENT


def test_manage_demand_od_and_routing_aliases(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(srv, "od2trips", lambda od, out, options: "OD OK")
    monkeypatch.setattr(srv, "duarouter", lambda net, trips, out, options: "Routes OK")
    out = str(tmp_path / "o.xml")

    for alias in ("convert_od", "od_matrix"):
        env = srv.manage_demand(alias, "n.net.xml", out, {"od_file": "od.txt"})
        assert env["ok"] is True and env["summary"] == "OD OK"
    env = srv.manage_demand("convert_od", "n.net.xml", out, {})
    assert env["ok"] is False

    for alias in ("compute_routes", "routing"):
        env = srv.manage_demand(alias, "n.net.xml", out, {"route_files": "t.trips.xml"})
        assert env["ok"] is True and env["summary"] == "Routes OK"
    env = srv.manage_demand("routing", "n.net.xml", out, {})
    assert env["ok"] is False


# --- control_simulation ----------------------------------------------------


class _FakeConnection:
    def __init__(self):
        self.calls = []

    def connect(self, config_file, gui, port, host, timeout_s=None):
        self.calls.append(("connect", config_file, gui, port, host, timeout_s))

    def simulation_step(self, step, timeout_s=None):
        self.calls.append(("step", step, timeout_s))

    def disconnect(self, timeout_s=None):
        self.calls.append(("disconnect", timeout_s))


def test_control_simulation_connect_defaults_and_timeout_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeConnection()
    monkeypatch.setattr(srv, "connection_manager", fake)

    env = srv.control_simulation("connect", {"config_file": "sim.sumocfg"})
    check_envelope(env)
    assert env["ok"] is True and env["summary"] == "Successfully connected to SUMO."
    # v0.1 defaults: gui False, port 8813, host localhost, no timeout kwarg
    assert fake.calls[-1] == ("connect", "sim.sumocfg", False, 8813, "localhost", None)
    assert env["data"]["mode"] == "launch"

    # `timeout` alias for timeout_s; attach mode without config_file
    env = srv.control_simulation("connect", {"timeout": 5})
    assert fake.calls[-1] == ("connect", None, False, 8813, "localhost", 5.0)
    assert env["data"]["mode"] == "attach"

    env = srv.control_simulation("step", {"step": 10})
    assert env["ok"] is True and fake.calls[-1] == ("step", 10, None)

    env = srv.control_simulation("disconnect", None)
    assert env["ok"] is True and fake.calls[-1] == ("disconnect", None)


def test_control_simulation_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    env = srv.control_simulation("connect", {"timeout_s": "fast"})
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.INVALID_ARGUMENT

    class Exploding:
        def connect(self, *a, **k):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(srv, "connection_manager", Exploding())
    env = srv.control_simulation("connect", {"config_file": "x.sumocfg"})
    check_envelope(env)
    assert env["ok"] is False
    assert env["error"]["code"] == ErrorCode.CONNECTION_ERROR
    assert "connection refused" in env["summary"]

    env = srv.control_simulation("fly", {})
    assert env["ok"] is False and env["summary"] == "Unknown action: fly"


# --- query_simulation_state --------------------------------------------------


def test_query_state_targets_and_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "get_vehicles", lambda: ["v0", "v1"])
    monkeypatch.setattr(srv, "get_vehicle_speed", lambda vid: 13.9)
    monkeypatch.setattr(srv, "get_vehicle_position", lambda vid: (100.0, 200.0))
    monkeypatch.setattr(srv, "get_simulation_info", lambda: {"time": 42.0})

    for alias in ("vehicle_list", "vehicles"):
        env = srv.query_simulation_state(alias)
        check_envelope(env)
        assert env["ok"] is True
        assert env["summary"] == "Active vehicles: ['v0', 'v1']"
        assert env["data"] == {"vehicles": ["v0", "v1"], "count": 2}

    env = srv.query_simulation_state("vehicle_variable", {"vehicle_id": "v0", "variable": "speed"})
    assert env["ok"] is True and env["summary"] == "Speed: 13.9"
    assert env["data"]["value"] == 13.9

    env = srv.query_simulation_state("vehicle_variable", {"vehicle_id": "v0", "variable": "position"})
    assert env["data"]["value"] == [100.0, 200.0]  # tuple made JSON-safe

    env = srv.query_simulation_state("simulation")
    assert env["ok"] is True and env["data"]["simulation"] == {"time": 42.0}


def test_query_state_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    env = srv.query_simulation_state("vehicle_variable", {"vehicle_id": "v0"})
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.INVALID_ARGUMENT

    monkeypatch.setattr(srv, "get_vehicle_speed", lambda vid: 0)
    env = srv.query_simulation_state("vehicle_variable", {"vehicle_id": "v0", "variable": "warp"})
    assert env["ok"] is False and env["summary"] == "Unknown variable: warp"

    def boom():
        raise ConnectionError("not connected")

    monkeypatch.setattr(srv, "get_vehicles", boom)
    env = srv.query_simulation_state("vehicles")
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.CONNECTION_ERROR

    env = srv.query_simulation_state("galaxy")
    assert env["ok"] is False and env["summary"] == "Unknown target: galaxy"


# --- optimize_traffic_signals ------------------------------------------------


def test_optimize_signals_websters_alias(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(srv, "tls_cycle_adaptation", lambda n, r, o: "Cycle OK")
    monkeypatch.setattr(srv, "tls_coordinator", lambda n, r, o, opts: "Coord OK")
    out = str(tmp_path / "tls.add.xml")

    for alias in ("cycle_adaptation", "Websters"):
        env = srv.optimize_traffic_signals(alias, "n.net.xml", "r.rou.xml", out)
        check_envelope(env)
        assert env["ok"] is True and env["summary"] == "Cycle OK"
        assert env["artifacts"][0]["role"] == "tls_program"

    env = srv.optimize_traffic_signals("coordination", "n.net.xml", "r.rou.xml", out)
    assert env["ok"] is True and env["summary"] == "Coord OK"

    env = srv.optimize_traffic_signals("magic", "n", "r", out)
    assert env["ok"] is False and env["summary"] == "Unknown method: magic"


# --- run_workflow -------------------------------------------------------------


def test_run_workflow_sim_gen_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def fake_sim_gen(output_dir, grid_number, sim_seconds):
        captured.update(output_dir=output_dir, grid_number=grid_number, sim_seconds=sim_seconds)
        return "SimGen OK"

    monkeypatch.setattr(srv, "sim_gen_workflow", fake_sim_gen)

    for name in ("sim_gen_eval", "sim_gen_workflow", "sim_gen"):
        env = srv.run_workflow(name, {"grid_size": 5, "duration": 300})
        check_envelope(env)
        assert env["ok"] is True and env["summary"] == "SimGen OK"
        assert captured == {"output_dir": "output", "grid_number": 5, "sim_seconds": 300}


def test_run_workflow_signal_opt_and_rl_train(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "signal_opt_workflow", lambda n, r, o, s, c: "SignalOpt OK")
    monkeypatch.setattr(srv, "rl_train_workflow", lambda s, o, e, st: f"RL {s} {e}x{st}")

    env = srv.run_workflow("signal_opt", {})
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.INVALID_ARGUMENT

    env = srv.run_workflow("signal_opt", {"net_file": "n.net.xml", "route_file": "r.rou.xml"})
    assert env["ok"] is True and env["summary"] == "SignalOpt OK"

    env = srv.run_workflow("rl_train", {"scenario": "single-intersection", "num_episodes": 2,
                                        "steps_per_episode": 100})
    assert env["ok"] is True and env["summary"] == "RL single-intersection 2x100"

    env = srv.run_workflow("world_peace", {})
    assert env["ok"] is False
    assert "Unknown workflow" in env["summary"] and "sim_gen_eval" in env["summary"]


# --- manage_rl_task -------------------------------------------------------------


def test_manage_rl_task_list_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "list_rl_scenarios", lambda: ["a", "b"])
    env = srv.manage_rl_task("list_scenarios")
    check_envelope(env)
    assert env["ok"] is True
    assert env["summary"] == "['a', 'b']"  # v0.1 str() rendering preserved
    assert env["data"]["scenarios"] == ["a", "b"]


def test_manage_rl_task_train_custom_scenario_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "find_sumo_rl_scenario_files",
                        lambda name: ("net.xml", "rou.xml", None))
    captured = {}

    def fake_train(**kwargs):
        captured.update(kwargs)
        return "Episode 1/1: Total Reward = -5.00"

    monkeypatch.setattr(srv, "run_rl_training", fake_train)

    # `scenario` alias + `num_episodes`/`steps_per_episode` aliases + output_dir alias
    env = srv.manage_rl_task("train_custom", {
        "scenario": "single-intersection", "num_episodes": 3,
        "steps_per_episode": 200, "output_dir": "runs",
    })
    check_envelope(env)
    assert env["ok"] is True
    assert captured["net_file"] == "net.xml" and captured["route_file"] == "rou.xml"
    assert captured["episodes"] == 3 and captured["steps_per_episode"] == 200
    assert captured["out_dir"] == "runs"
    assert captured["algorithm"] == "ql" and captured["reward_type"] == "diff-waiting-time"


@pytest.mark.parametrize("params, code", [
    ({}, ErrorCode.INVALID_ARGUMENT),                                # neither scenario nor files
    ({"net_file": "n", "route_file": "r", "episodes": 0}, ErrorCode.INVALID_ARGUMENT),
    ({"net_file": "n", "route_file": "r", "steps": "-"}, ErrorCode.INVALID_ARGUMENT),
])
def test_manage_rl_task_validation_errors(params, code) -> None:
    env = srv.manage_rl_task("train_custom", params)
    check_envelope(env)
    assert env["ok"] is False and env["error"]["code"] == code


def test_manage_rl_task_scenario_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "find_sumo_rl_scenario_files",
                        lambda name: (None, None, "Error: Scenario 'x' not found. Available: []"))
    env = srv.manage_rl_task("train_custom", {"scenario": "x"})
    assert env["ok"] is False and env["error"]["code"] == ErrorCode.FILE_NOT_FOUND


# --- get_sumo_info / run_simple_simulation / run_analysis ------------------------


def test_get_sumo_info_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "find_sumo_binary", lambda name: None)
    env = srv.get_sumo_info()
    check_envelope(env)
    assert env["ok"] is False
    assert env["error"]["code"] == ErrorCode.SUMO_NOT_FOUND
    assert env["error"].get("remediation")


def test_run_simple_simulation_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "run_simple_simulation", lambda cfg, steps: f"Simulated {cfg} for {steps}")
    env = srv.run_simple_simulation_tool("sim.sumocfg", steps=25)
    check_envelope(env)
    assert env["ok"] is True and env["summary"] == "Simulated sim.sumocfg for 25"
    assert env["data"] == {"config_path": "sim.sumocfg", "steps": 25}

    monkeypatch.setattr(srv, "run_simple_simulation", lambda cfg, steps: "Error: config not found")
    env = srv.run_simple_simulation_tool("missing.sumocfg")
    assert env["ok"] is False


def test_run_analysis_wraps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(srv, "analyze_fcd", lambda f: "Analysis Result:\nTotal Data Points: 10")
    env = srv.run_analysis("fcd.xml")
    check_envelope(env)
    assert env["ok"] is True and env["summary"].startswith("Analysis Result:")
