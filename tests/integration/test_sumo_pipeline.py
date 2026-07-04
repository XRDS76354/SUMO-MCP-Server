"""End-to-end pipeline against a real SUMO installation.

Covers the classic netgenerate -> randomTrips -> duarouter -> sumo chain that
the manage_network / manage_demand / run_simple_simulation tools wrap, plus the
sim_gen_eval workflow. Marked ``requires_sumo``; auto-skipped when SUMO is absent.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from sumo_mcp.server import (
    get_sumo_info,
    manage_demand,
    manage_network,
    run_simple_simulation_tool,
)

pytestmark = pytest.mark.requires_sumo


@pytest.fixture(autouse=True)
def _ensure_sumo_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """sumolib tools (randomTrips) need SUMO_HOME; derive it when unset."""
    if os.environ.get("SUMO_HOME"):
        return
    from sumo_mcp.utils.sumo import find_sumo_home

    home = find_sumo_home()
    if home:
        monkeypatch.setenv("SUMO_HOME", home)


def test_get_sumo_info_reports_binary_and_version() -> None:
    result = get_sumo_info()
    assert "SUMO Binary:" in result
    assert "SUMO Version:" in result
    assert "Error" not in result


def test_full_pipeline_generate_demand_simulate(tmp_path: Path) -> None:
    net_file = str(tmp_path / "grid.net.xml")
    trips_file = str(tmp_path / "grid.trips.xml")
    routes_file = str(tmp_path / "grid.rou.xml")

    # 1. netgenerate (grid 3x3)
    result = manage_network("generate", net_file, {"grid": True, "grid_number": 3})
    assert Path(net_file).is_file(), f"netgenerate failed: {result}"

    # 2. randomTrips
    result = manage_demand("generate_random", net_file, trips_file, {"end_time": 60, "period": 2.0})
    assert Path(trips_file).is_file(), f"randomTrips failed: {result}"

    # 3. duarouter
    result = manage_demand("compute_routes", net_file, routes_file, {"route_files": trips_file})
    assert Path(routes_file).is_file(), f"duarouter failed: {result}"

    # 4. write a minimal sumocfg and run headless
    cfg = tmp_path / "sim.sumocfg"
    cfg.write_text(
        f"""<configuration>
    <input>
        <net-file value="{net_file}"/>
        <route-files value="{routes_file}"/>
    </input>
</configuration>
""",
        encoding="utf-8",
    )
    result = run_simple_simulation_tool(str(cfg), steps=50)
    assert "Error" not in result, f"simulation failed: {result}"


def test_spider_network_generation(tmp_path: Path) -> None:
    net_file = str(tmp_path / "spider.net.xml")
    result = manage_network("generate", net_file, {"spider": True, "arms": 5, "circles": 3})
    assert Path(net_file).is_file(), f"spider netgenerate failed: {result}"
