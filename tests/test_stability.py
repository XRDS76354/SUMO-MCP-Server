import pytest
import os
import shutil

from mcp_tools.simulation import run_simple_simulation

# This module runs real SUMO simulations. Skip in environments without SUMO.
HAS_SUMO = bool(os.environ.get("SUMO_HOME")) or shutil.which("sumo") is not None
pytestmark = pytest.mark.skipif(
    not HAS_SUMO,
    reason="Requires SUMO installed (set SUMO_HOME or add `sumo` to PATH).",
)

# This is a shortened stability test for demonstration
# Real stability test would run for hours
def test_stability_loop(tmp_path):
    # Use existing fixture files if possible, or generate small one
    from mcp_tools.network import netgenerate
    from mcp_tools.route import random_trips, duarouter
    
    work_dir = str(tmp_path)
    net_file = os.path.join(work_dir, "grid.net.xml")
    trips_file = os.path.join(work_dir, "trips.xml")
    rou_file = os.path.join(work_dir, "routes.xml")
    cfg_file = os.path.join(work_dir, "sim.sumocfg")
    
    netgenerate(net_file, grid=True, grid_number=3)
    random_trips(net_file, trips_file, end_time=10)
    duarouter(net_file, trips_file, rou_file)
    
    with open(cfg_file, "w") as f:
        f.write(f"""<configuration>
            <input>
                <net-file value="{os.path.basename(net_file)}"/>
                <route-files value="{os.path.basename(rou_file)}"/>
            </input>
            <time>
                <begin value="0"/>
                <end value="10"/>
            </time>
        </configuration>""")
        
    # Run loop
    iterations = 20
    success_count = 0
    for i in range(iterations):
        res = run_simple_simulation(cfg_file, steps=10)
        if "Simulation finished successfully" in res:
            success_count += 1
            
    assert success_count == iterations
