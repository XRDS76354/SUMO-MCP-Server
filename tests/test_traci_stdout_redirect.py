import subprocess


def test_run_simple_simulation_redirects_sumo_stdout(monkeypatch, tmp_path) -> None:
    from mcp_tools import simulation as simulation_module

    config_path = tmp_path / "dummy.sumocfg"
    config_path.write_text("<configuration/>", encoding="utf-8")

    monkeypatch.setattr(simulation_module, "find_sumo_binary", lambda _: "/usr/bin/sumo")

    captured: dict[str, object] = {}

    def fake_start(*args, **kwargs):
        captured["stdout"] = kwargs.get("stdout")
        raise RuntimeError("stop-after-start")

    monkeypatch.setattr(simulation_module.traci, "start", fake_start)
    monkeypatch.setattr(simulation_module.traci, "close", lambda *a, **k: None)

    result = simulation_module.run_simple_simulation(str(config_path), steps=1)
    assert captured["stdout"] is subprocess.DEVNULL
    assert "Simulation error" in result
    assert "RuntimeError" in result


def test_connection_manager_redirects_sumo_stdout(monkeypatch) -> None:
    from utils.connection import connection_manager
    import utils.connection as connection_module

    # Avoid leaking state across tests (singleton).
    connection_manager._connected = False

    monkeypatch.setattr(connection_module, "find_sumo_binary", lambda _: "/usr/bin/sumo")

    captured: dict[str, object] = {}

    def fake_start(*args, **kwargs):
        captured["stdout"] = kwargs.get("stdout")
        return None

    monkeypatch.setattr(connection_module.traci, "start", fake_start)
    monkeypatch.setattr(connection_module.traci, "close", lambda *a, **k: None)

    connection_manager.connect(config_file="dummy.sumocfg", port=12345)
    assert captured["stdout"] is subprocess.DEVNULL

    # Reset singleton state for other tests.
    connection_manager._connected = False
