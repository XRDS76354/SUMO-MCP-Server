import os
from sumo_mcp.mcp_tools.network import netgenerate
from sumo_mcp.mcp_tools.route import random_trips, duarouter
from sumo_mcp.mcp_tools.simulation import run_simple_simulation
from sumo_mcp.mcp_tools.analysis import analyze_fcd


def sim_gen_workflow(output_dir: str, grid_number: int = 3, steps: int = 100) -> str:
    """
    Executes the Simulation Generation & Evaluation workflow:
    1. Generate Grid Network
    2. Generate Random Trips
    3. Compute Routes
    4. Create Config
    5. Run Simulation
    6. Analyze Results
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    net_file = os.path.join(output_dir, "grid.net.xml")
    trips_file = os.path.join(output_dir, "trips.xml")
    route_file = os.path.join(output_dir, "routes.xml")
    sumocfg_file = os.path.join(output_dir, "sim.sumocfg")
    fcd_file = os.path.join(output_dir, "fcd.xml")

    # 1. Generate Net
    res = netgenerate(net_file, grid=True, grid_number=grid_number)
    if "failed" in res.lower():
        return f"Step 1 Failed: {res}"

    # 2. Generate Trips
    res = random_trips(net_file, trips_file, end_time=steps)
    if "failed" in res.lower():
        return f"Step 2 Failed: {res}"

    # 3. Generate Routes
    res = duarouter(net_file, trips_file, route_file)
    if "failed" in res.lower():
        return f"Step 3 Failed: {res}"

    # 4. Create Config
    # We use absolute paths for safety or relative if SUMO expects it.
    # Usually relative to config file is best.
    try:
        with open(sumocfg_file, "w") as f:
            f.write(f"""<configuration>
    <input>
        <net-file value="{os.path.basename(net_file)}"/>
        <route-files value="{os.path.basename(route_file)}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="{steps}"/>
    </time>
    <output>
        <fcd-output value="{os.path.basename(fcd_file)}"/>
    </output>
</configuration>""")
    except Exception as e:
        return f"Step 4 Failed: Could not write config file. {e}"

    # 5. Run Sim
    res = run_simple_simulation(sumocfg_file, steps)
    if "error" in res.lower():
        return f"Step 5 Failed: {res}"

    # 6. Analyze
    # FCD file should exist after sim
    if not os.path.exists(fcd_file):
        return "Step 6 Failed: FCD file not generated."

    res_analysis = analyze_fcd(fcd_file)

    return f"Workflow Completed Successfully.\n\nSimulation Output:\n{res}\n\nAnalysis Result:\n{res_analysis}"
