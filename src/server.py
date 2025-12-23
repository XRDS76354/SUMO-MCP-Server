import logging
import subprocess
from typing import Any, Dict, Optional

from mcp.server.fastmcp import FastMCP

from mcp_tools.simulation import run_simple_simulation
from mcp_tools.network import netconvert, netgenerate, osm_get
from mcp_tools.route import random_trips, duarouter, od2trips
from mcp_tools.signal import tls_cycle_adaptation, tls_coordinator
from mcp_tools.analysis import analyze_fcd
from mcp_tools.vehicle import (
    get_vehicles, get_vehicle_speed, get_vehicle_position, 
    get_vehicle_acceleration, get_vehicle_lane, get_vehicle_route,
    get_simulation_info
)
from mcp_tools.rl import find_sumo_rl_scenario_files, list_rl_scenarios, run_rl_training
from utils.connection import connection_manager
from utils.sumo import find_sumo_binary, find_sumo_home, find_sumo_tools_dir
from workflows.sim_gen import sim_gen_workflow
from workflows.signal_opt import signal_opt_workflow
from workflows.rl_train import rl_train_workflow

# Configure logging to stderr to not interfere with MCP stdio transport
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize MCP Server (official SDK)
server = FastMCP("SUMO-MCP-Server")

# --- 1. Network Management ---
@server.tool(description="Manage SUMO network (generate, convert, or download OSM).")
def manage_network(action: str, output_file: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    actions:
    - generate: params={'grid': bool, 'grid_number': int}
    - convert: params={'osm_file': str}
    - download_osm: output_file is treated as output_dir. params={'bbox': str, 'prefix': str}
    """
    params = params or {}
    options = params.get("options")
    
    if action == "generate":
        spider = bool(params.get("spider", False))
        grid = bool(params.get("grid", True))
        grid_number = params.get("grid_number", 3)

        if spider:
            # Spider network takes precedence over grid settings.
            grid = False
            options_list = list(options or [])
            if "--spider" not in options_list:
                options_list.insert(0, "--spider")
            options = options_list

        return netgenerate(output_file, grid, grid_number, options)
        
    elif action == "convert" or action == "convert_osm":
        osm_file = params.get("osm_file")
        if not osm_file: return "Error: osm_file required for convert action"
        return netconvert(osm_file, output_file, options)
        
    elif action == "download_osm":
        # output_file here acts as output_dir
        bbox = params.get("bbox")
        prefix = params.get("prefix", "osm")
        if not bbox: return "Error: bbox required for download_osm action"
        return osm_get(bbox, output_file, prefix, options)
        
    return f"Unknown action: {action}"

# --- 2. Demand Management ---
@server.tool(description="Manage traffic demand (random trips, OD matrix, routing).")
def manage_demand(action: str, net_file: str, output_file: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    actions:
    - generate_random: params={'end_time': int, 'period': float}
    - convert_od: params={'od_file': str} (net_file unused but kept for consistency)
    - compute_routes: params={'route_files': str} (input trips)
    """
    params = params or {}
    options = params.get("options")
    
    if action == "generate_random" or action == "random_trips":
        end_time = params.get("end_time", 3600)
        period = params.get("period", 1.0)
        return random_trips(net_file, output_file, end_time, period, options)
        
    elif action == "convert_od" or action == "od_matrix":
        od_file = params.get("od_file")
        if not od_file: return "Error: od_file required for convert_od"
        return od2trips(od_file, output_file, options)
        
    elif action == "compute_routes" or action == "routing":
        route_files = params.get("route_files") # Input trips file
        if not route_files: return "Error: route_files required for compute_routes"
        return duarouter(net_file, route_files, output_file, options)
        
    return f"Unknown action: {action}"

# --- 3. Simulation Control ---
@server.tool(description="Control SUMO simulation (connect, step, disconnect).")
def control_simulation(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    actions:
    - connect: params={'config_file': str, 'gui': bool}
    - step: params={'step': float}
    - disconnect: no params
    """
    params = params or {}
    
    try:
        if action == "connect":
            config_file = params.get("config_file")
            gui = params.get("gui", False)
            port = params.get("port", 8813)
            host = params.get("host", "localhost")
            connection_manager.connect(config_file, gui, port, host)
            return "Successfully connected to SUMO."
            
        elif action == "step":
            step = params.get("step", 0)
            connection_manager.simulation_step(step)
            return "Simulation advanced."
            
        elif action == "disconnect":
            connection_manager.disconnect()
            return "Successfully disconnected from SUMO."
            
    except Exception as e:
        return f"Error in control_simulation ({action}): {e}"
        
    return f"Unknown action: {action}"

# --- 4. Query State ---
@server.tool(description="Query simulation state (vehicles, speed, position). Requires active connection.")
def query_simulation_state(target: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    targets:
    - vehicle_list: no params
    - vehicle_variable: params={'vehicle_id': str, 'variable': 'speed'|'position'|'lane'|'acceleration'|'route'}
    """
    params = params or {}
    
    try:
        if target == "vehicle_list" or target == "vehicles":
            vehs = get_vehicles()
            return f"Active vehicles: {vehs}"
            
        elif target == "vehicle_variable":
            v_id = params.get("vehicle_id")
            var = params.get("variable")
            if not v_id or not var: return "Error: vehicle_id and variable required"
            
            if var == "speed": return f"Speed: {get_vehicle_speed(v_id)}"
            if var == "position": return f"Position: {get_vehicle_position(v_id)}"
            if var == "acceleration": return f"Acceleration: {get_vehicle_acceleration(v_id)}"
            if var == "lane": return f"Lane: {get_vehicle_lane(v_id)}"
            if var == "route": return f"Route: {get_vehicle_route(v_id)}"
            
            return f"Unknown variable: {var}"
        
        elif target == "simulation":
            info = get_simulation_info()
            return f"Simulation Info: {info}"
            
    except Exception as e:
        return f"Error querying state: {e}"
        
    return f"Unknown target: {target}"

# --- 5. Optimize Signals ---
@server.tool(description="Optimize traffic signals.")
def optimize_traffic_signals(method: str, net_file: str, route_file: str, output_file: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    methods:
    - cycle_adaptation: adapt TLS cycles
    - coordination: TLS coordination
    """
    params = params or {}
    options = params.get("options")
    
    if method == "cycle_adaptation" or method == "Websters":
        return tls_cycle_adaptation(net_file, route_file, output_file)
    elif method == "coordination":
        return tls_coordinator(net_file, route_file, output_file, options)
        
    return f"Unknown method: {method}"

# --- 6. Workflows ---
@server.tool(description="Run high-level workflows.")
def run_workflow(workflow_name: str, params: Dict[str, Any]) -> str:
    """
    workflows:
    - sim_gen_eval: params={'output_dir', 'grid_number', 'steps'}
    - signal_opt: params={'net_file', 'route_file', 'output_dir', 'steps', 'use_coordinator'}
    - rl_train: params={'scenario_name', 'output_dir', 'episodes', 'steps'}
    """
    if workflow_name == "sim_gen_eval" or workflow_name == "sim_gen_workflow" or workflow_name == "sim_gen":
        return sim_gen_workflow(
            params.get("output_dir", "output"), 
            params.get("grid_number", 3), 
            params.get("steps", 100)
        )
    elif workflow_name == "signal_opt" or workflow_name == "signal_opt_workflow":
        return signal_opt_workflow(
            params.get("net_file", ""),
            params.get("route_file", ""),
            params.get("output_dir", "output"),
            params.get("steps", 3600),
            params.get("use_coordinator", False)
        )
    elif workflow_name == "rl_train":
        return rl_train_workflow(
            params.get("scenario_name", ""),
            params.get("output_dir", "output"),
            params.get("episodes", 5),
            params.get("steps", 1000)
        )
        
    return f"Unknown workflow: {workflow_name}"

# --- 7. RL Task Management ---
@server.tool(description="Manage RL tasks (list scenarios, custom training).")
def manage_rl_task(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    actions:
    - list_scenarios: no params
    - train_custom: params={'net_file', 'route_file', 'out_dir', 'episodes', 'steps', 'algorithm', 'reward_type'}
    """
    params = params or {}
    
    if action == "list_scenarios":
        return str(list_rl_scenarios())
        
    elif action == "train_custom":
        scenario_name = params.get("scenario") or params.get("scenario_name")
        net_file = params.get("net_file")
        route_file = params.get("route_file")

        if scenario_name:
            net_file, route_file, err = find_sumo_rl_scenario_files(str(scenario_name))
            if err:
                return err

        if not net_file or not route_file:
            return (
                "Error: train_custom requires either:\n"
                "  - scenario/scenario_name (built-in sumo-rl scenario), OR\n"
                "  - net_file + route_file (custom files)\n"
                "Hint: Use manage_rl_task(list_scenarios) to see available built-in scenarios."
            )

        out_dir = params.get("out_dir") or params.get("output_dir") or "output"

        episodes_raw = params.get("episodes", params.get("num_episodes", 1))
        steps_raw = params.get("steps", params.get("steps_per_episode", 1000))
        try:
            episodes = int(episodes_raw)
        except (TypeError, ValueError):
            return f"Error: episodes must be an integer, got {episodes_raw!r}"
        try:
            steps_per_episode = int(steps_raw)
        except (TypeError, ValueError):
            return f"Error: steps must be an integer, got {steps_raw!r}"

        if episodes <= 0:
            return "Error: episodes must be > 0"
        if steps_per_episode <= 0:
            return "Error: steps must be > 0"

        algorithm = str(params.get("algorithm", "ql"))
        reward_type = str(params.get("reward_type", "diff-waiting-time"))

        return run_rl_training(
            net_file=str(net_file),
            route_file=str(route_file),
            out_dir=str(out_dir),
            episodes=episodes,
            steps_per_episode=steps_per_episode,
            algorithm=algorithm,
            reward_type=reward_type,
        )
        
    return f"Unknown action: {action}"

# --- Legacy/Misc ---
@server.tool(name="get_sumo_info", description="Get the version and path of the installed SUMO.")
def get_sumo_info() -> str:
    try:
        sumo_binary = find_sumo_binary("sumo")
        if not sumo_binary:
            return (
                "Error: Could not locate SUMO executable. "
                "Please ensure SUMO is installed and either `sumo` is available in PATH or `SUMO_HOME` is set."
            )

        result = subprocess.run([sumo_binary, "--version"], capture_output=True, text=True, check=True)
        version_output = (result.stdout.splitlines() or ["Unknown"])[0]

        sumo_home = find_sumo_home()
        tools_dir = find_sumo_tools_dir()
        return "\n".join(
            [
                f"SUMO Binary: {sumo_binary}",
                f"SUMO Version: {version_output}",
                f"SUMO_HOME: {sumo_home or 'Not Set'}",
                f"SUMO Tools Dir: {tools_dir or 'Not Found'}",
            ]
        )
    except Exception as e:
        return f"Error checking SUMO: {str(e)}"

@server.tool(name="run_simple_simulation", description="Run a SUMO simulation using a config file.")
def run_simple_simulation_tool(config_path: str, steps: int = 100) -> str:
    return run_simple_simulation(config_path, steps)

@server.tool(description="Analyze FCD output.")
def run_analysis(fcd_file: str) -> str:
    return analyze_fcd(fcd_file)

if __name__ == "__main__":
    server.run(transport="stdio")
