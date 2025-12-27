import os
import shutil
import pytest

from mcp_tools.network import netgenerate
from mcp_tools.route import random_trips, duarouter
from mcp_tools.simulation import run_simple_simulation
from mcp_tools.analysis import analyze_fcd

# This module exercises real SUMO binaries/tools. Skip in environments without SUMO.
HAS_SUMO = bool(os.environ.get("SUMO_HOME")) or shutil.which("sumo") is not None
pytestmark = pytest.mark.skipif(
    not HAS_SUMO,
    reason="Requires SUMO installed (set SUMO_HOME or add `sumo` to PATH).",
)

# Setup fixtures
@pytest.fixture
def output_dir():
    path = os.path.join(os.path.dirname(__file__), "output_functional")
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    yield path
    # Cleanup after test if needed, but keeping for debug is better
    # shutil.rmtree(path)

def test_netgenerate(output_dir):
    net_file = os.path.join(output_dir, "grid.net.xml")
    result = netgenerate(net_file, grid=True, grid_number=3)
    assert "Netgenerate successful" in result
    assert os.path.exists(net_file)
    assert os.path.getsize(net_file) > 0

def test_random_trips(output_dir):
    net_file = os.path.join(output_dir, "grid.net.xml")
    # Prerequisite
    netgenerate(net_file, grid=True, grid_number=3)
    
    trips_file = os.path.join(output_dir, "trips.xml")
    result = random_trips(net_file, trips_file, end_time=50)
    assert "randomTrips successful" in result
    assert os.path.exists(trips_file)

def test_duarouter(output_dir):
    net_file = os.path.join(output_dir, "grid.net.xml")
    trips_file = os.path.join(output_dir, "trips.xml")
    rou_file = os.path.join(output_dir, "routes.xml")
    
    # Prerequisites
    netgenerate(net_file, grid=True, grid_number=3)
    random_trips(net_file, trips_file, end_time=50)
    
    result = duarouter(net_file, trips_file, rou_file)
    assert "duarouter successful" in result
    assert os.path.exists(rou_file)

def test_simulation_and_analysis(output_dir):
    # Setup full env
    net_file = os.path.join(output_dir, "grid.net.xml")
    trips_file = os.path.join(output_dir, "trips.xml")
    rou_file = os.path.join(output_dir, "routes.xml")
    cfg_file = os.path.join(output_dir, "sim.sumocfg")
    fcd_file = os.path.join(output_dir, "fcd.xml")
    
    netgenerate(net_file, grid=True, grid_number=3)
    random_trips(net_file, trips_file, end_time=50)
    duarouter(net_file, trips_file, rou_file)
    
    with open(cfg_file, "w") as f:
        f.write(f"""<configuration>
            <input>
                <net-file value="{os.path.basename(net_file)}"/>
                <route-files value="{os.path.basename(rou_file)}"/>
            </input>
            <time>
                <begin value="0"/>
                <end value="50"/>
            </time>
            <output>
                <fcd-output value="{os.path.basename(fcd_file)}"/>
            </output>
        </configuration>""")
        
    # Test Sim
    res_sim = run_simple_simulation(cfg_file, steps=50)
    assert "Simulation finished successfully" in res_sim
    assert os.path.exists(fcd_file)
    
    # Test Analysis
    res_analysis = analyze_fcd(fcd_file)
    assert "Analysis Result" in res_analysis
    assert "Average Speed" in res_analysis
