def test_manage_rl_task_train_custom_parses_aliases(monkeypatch, tmp_path) -> None:
    import server as server_module

    captured: dict[str, object] = {}

    def fake_run_rl_training(**kwargs):
        captured.update(kwargs)
        return "OK"

    monkeypatch.setattr(server_module, "run_rl_training", fake_run_rl_training)

    out_dir = tmp_path / "out"

    result = server_module.manage_rl_task(
        "train_custom",
        {
            "net_file": "net.net.xml",
            "route_file": "routes.rou.xml",
            "output_dir": str(out_dir),
            "num_episodes": 7,
            "steps_per_episode": 123,
        },
    )

    assert result == "OK"
    assert captured["net_file"] == "net.net.xml"
    assert captured["route_file"] == "routes.rou.xml"
    assert captured["out_dir"] == str(out_dir)
    assert captured["episodes"] == 7
    assert captured["steps_per_episode"] == 123
    assert captured["algorithm"] == "ql"
    assert captured["reward_type"] == "diff-waiting-time"


def test_manage_rl_task_train_custom_resolves_scenario(monkeypatch, tmp_path) -> None:
    import server as server_module

    def fake_find_scenario_files(name: str):
        assert name == "dummy-scenario"
        return ("scenario.net.xml", "scenario.rou.xml", None)

    monkeypatch.setattr(server_module, "find_sumo_rl_scenario_files", fake_find_scenario_files)

    captured: dict[str, object] = {}

    def fake_run_rl_training(**kwargs):
        captured.update(kwargs)
        return "OK"

    monkeypatch.setattr(server_module, "run_rl_training", fake_run_rl_training)

    result = server_module.manage_rl_task(
        "train_custom",
        {
            "scenario": "dummy-scenario",
            "out_dir": str(tmp_path / "out"),
            "episodes": 2,
            "steps": 50,
        },
    )

    assert result == "OK"
    assert captured["net_file"] == "scenario.net.xml"
    assert captured["route_file"] == "scenario.rou.xml"
    assert captured["episodes"] == 2
    assert captured["steps_per_episode"] == 50

