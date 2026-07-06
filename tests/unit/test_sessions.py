"""Unit tests for the multi-session TraCI manager (fake traci, no SUMO)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

import sumo_mcp.sessions.manager as sm
from sumo_mcp.sessions.manager import ALLOWED_CALLS, SessionManager


class _FakeDomain:
    def __init__(self, calls: List[Any]) -> None:
        self._calls = calls

    def __getattr__(self, method: str) -> Any:
        def record(*args: Any) -> Any:
            self._calls.append((method, args))
            if method == "getTime":
                return 7.0
            if method == "getIDList":
                return ("v0", "v1")
            return None
        return record


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: List[Any] = []
        self.closed = False
        self.simulation = _FakeDomain(self.calls)
        self.vehicle = _FakeDomain(self.calls)
        self.trafficlight = _FakeDomain(self.calls)
        self.inductionloop = _FakeDomain(self.calls)

    def simulationStep(self) -> None:
        self.calls.append(("simulationStep", ()))

    def close(self) -> None:
        self.closed = True


class _FakeTraci:
    def __init__(self) -> None:
        self.connections: Dict[str, _FakeConnection] = {}
        self.started: List[Dict[str, Any]] = []
        self.hang = False

    def start(self, cmd: List[str], label: str = "default", stdout: Any = None) -> None:
        if self.hang:
            import time
            time.sleep(30)
        self.started.append({"cmd": cmd, "label": label})
        self.connections[label] = _FakeConnection()

    def getConnection(self, label: str) -> _FakeConnection:
        return self.connections[label]


@pytest.fixture()
def fake_traci(monkeypatch: pytest.MonkeyPatch) -> _FakeTraci:
    fake = _FakeTraci()
    monkeypatch.setattr(SessionManager, "_traci", lambda self: fake)
    monkeypatch.setattr(sm, "find_sumo_binary", lambda name: f"/fake/bin/{name}")
    monkeypatch.delenv("SUMO_MCP_ALLOW_GUI", raising=False)
    return fake


def _mgr() -> SessionManager:
    return SessionManager()


def test_open_auto_labels_and_command(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    info1 = manager.open("a.sumocfg")
    info2 = manager.open("b.sumocfg", extra_args=["--seed", "42"])
    assert info1.label == "s1" and info2.label == "s2"
    assert info1.status == "active"
    assert fake_traci.started[0]["cmd"][:3] == ["/fake/bin/sumo", "-c", "a.sumocfg"]
    assert "--start" in fake_traci.started[0]["cmd"]
    assert fake_traci.started[1]["cmd"][-2:] == ["--seed", "42"]


def test_open_duplicate_label_rejected(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    manager.open("a.sumocfg", label="base")
    with pytest.raises(ValueError, match="already in use"):
        manager.open("b.sumocfg", label="base")


def test_session_cap_enforced(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    for i in range(SessionManager.MAX_SESSIONS):
        manager.open(f"{i}.sumocfg")
    with pytest.raises(RuntimeError, match="Session limit"):
        manager.open("overflow.sumocfg")


def test_gui_guard_blocks_without_env(fake_traci: _FakeTraci, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _mgr()
    with pytest.raises(PermissionError, match="SUMO_MCP_ALLOW_GUI"):
        manager.open("a.sumocfg", gui=True)
    monkeypatch.setenv("SUMO_MCP_ALLOW_GUI", "1")
    info = manager.open("a.sumocfg", gui=True)
    assert fake_traci.started[0]["cmd"][0].endswith("sumo-gui")
    assert info.gui is True


def test_open_timeout_when_traci_hangs(fake_traci: _FakeTraci) -> None:
    fake_traci.hang = True
    manager = _mgr()
    with pytest.raises(TimeoutError, match="did not complete"):
        manager.open("a.sumocfg", timeout_s=0.5)


def test_missing_sumo_binary(fake_traci: _FakeTraci, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sm, "find_sumo_binary", lambda name: None)
    with pytest.raises(FileNotFoundError, match="SUMO_HOME"):
        _mgr().open("a.sumocfg")


def test_step_semantics(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    manager.open("a.sumocfg")

    result = manager.step(steps=3)  # single session: label optional
    assert result == {"label": "s1", "sim_time": 7.0, "active_vehicles": 2}
    conn = fake_traci.connections["s1"]
    assert sum(1 for c in conn.calls if c[0] == "simulationStep") == 3

    manager.open("b.sumocfg")
    with pytest.raises(KeyError, match="Multiple sessions"):
        manager.step()  # ambiguous now
    assert manager.step(label="s2")["label"] == "s2"

    with pytest.raises(ValueError):
        manager.step(label="s1", steps=0)


def test_step_without_sessions(fake_traci: _FakeTraci) -> None:
    with pytest.raises(KeyError, match="No active sessions"):
        _mgr().step()


def test_call_whitelist(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    manager.open("a.sumocfg")

    assert manager.call(None, "vehicle", "getIDList") == ("v0", "v1")
    manager.call(None, "trafficlight", "setPhase", ["tls0", 2])
    conn = fake_traci.connections["s1"]
    assert ("setPhase", ("tls0", 2)) in conn.calls

    with pytest.raises(PermissionError, match="domain 'gui' is not exposed"):
        manager.call(None, "gui", "screenshot")
    with pytest.raises(PermissionError, match="not whitelisted"):
        manager.call(None, "vehicle", "setLegalSpeedFactor")
    # error message must guide the agent to what IS allowed
    with pytest.raises(PermissionError, match="setPhase"):
        manager.call(None, "trafficlight", "unknownMethod")


def test_whitelist_covers_industry_surface() -> None:
    assert "setPhase" in ALLOWED_CALLS["trafficlight"]
    assert "setRedYellowGreenState" in ALLOWED_CALLS["trafficlight"]
    assert {
        "getAcceleration", "setSpeed", "rerouteTraveltime", "add", "remove", "changeLane",
    } <= ALLOWED_CALLS["vehicle"]
    assert "getLastStepVehicleNumber" in ALLOWED_CALLS["inductionloop"]
    assert "getJamLengthMeters" in ALLOWED_CALLS["lanearea"]


def test_close_and_list(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    manager.open("a.sumocfg", label="one")
    manager.open("b.sumocfg", label="two")

    assert {s["label"] for s in manager.list_sessions()} == {"one", "two"}
    result = manager.close("one")
    assert result == {"label": "one", "status": "closed"}
    assert fake_traci.connections["one"].closed is True
    assert {s["label"] for s in manager.list_sessions()} == {"two"}
    assert manager.get("one") is None
    assert manager.close_all() == 1
    assert manager.list_sessions() == []


def test_idle_sessions_reaped(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    manager.open("a.sumocfg", label="stale")
    # backdate last_used_at beyond the TTL
    old = datetime.now(timezone.utc) - timedelta(seconds=SessionManager.DEFAULT_IDLE_TTL_S + 60)
    manager._sessions["stale"].info.last_used_at = old.isoformat()

    assert manager.list_sessions() == []  # reaped lazily
    assert fake_traci.connections["stale"].closed is True


def test_close_dead_connection_tolerated(fake_traci: _FakeTraci) -> None:
    manager = _mgr()
    manager.open("a.sumocfg", label="dying")

    def explode() -> None:
        raise ConnectionError("already gone")

    fake_traci.connections["dying"].close = explode  # type: ignore[method-assign]
    assert manager.close("dying")["status"] == "closed"
    assert manager.list_sessions() == []
