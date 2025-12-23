import os
import sys
from pathlib import Path
from unittest.mock import patch


# Add src to path so imports work without installation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from mcp_tools.network import osm_get
from mcp_tools.route import random_trips
from mcp_tools.signal import tls_cycle_adaptation
from mcp_tools.simulation import run_simple_simulation


def test_run_simple_simulation_missing_sumo_includes_diagnostics(tmp_path: Path) -> None:
    cfg = tmp_path / "test.sumocfg"
    cfg.write_text("<configuration/>", encoding="utf-8")

    with (
        patch("mcp_tools.simulation.find_sumo_binary", return_value=None),
        patch("mcp_tools.simulation.build_sumo_diagnostics", return_value="Diagnostics:\n  - SUMO_HOME env: X"),
    ):
        msg = run_simple_simulation(str(cfg), steps=1)

    assert "Could not locate SUMO executable" in msg
    assert "Diagnostics:" in msg
    assert "SUMO_HOME env" in msg


def test_random_trips_missing_script_includes_diagnostics() -> None:
    with (
        patch("mcp_tools.route.find_sumo_tool_script", return_value=None),
        patch("mcp_tools.route.build_sumo_diagnostics", return_value="Diagnostics:\n  - SUMO_HOME env: X"),
    ):
        msg = random_trips("net.net.xml", "out.trips.xml")

    assert "randomTrips.py" in msg
    assert "Diagnostics:" in msg


def test_osm_get_missing_script_includes_diagnostics(tmp_path: Path) -> None:
    with (
        patch("mcp_tools.network.find_sumo_tool_script", return_value=None),
        patch("mcp_tools.network.build_sumo_diagnostics", return_value="Diagnostics:\n  - SUMO_HOME env: X"),
    ):
        msg = osm_get("0,0,1,1", str(tmp_path))

    assert "osmGet.py" in msg
    assert "Diagnostics:" in msg


def test_tls_cycle_adaptation_missing_script_includes_diagnostics() -> None:
    with (
        patch("mcp_tools.signal.find_sumo_tool_script", return_value=None),
        patch("mcp_tools.signal.build_sumo_diagnostics", return_value="Diagnostics:\n  - SUMO_HOME env: X"),
    ):
        msg = tls_cycle_adaptation("net.net.xml", "routes.rou.xml", "out.xml")

    assert "tlsCycleAdaptation.py" in msg
    assert "Diagnostics:" in msg

