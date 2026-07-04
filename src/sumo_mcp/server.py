import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from sumo_mcp.utils.traci import ensure_traci_start_stdout_suppressed
from sumo_mcp.mcp_tools.simulation import run_simple_simulation
from sumo_mcp.mcp_tools.network import netconvert, netgenerate, osm_get
from sumo_mcp.mcp_tools.ezdesignx import convert_ezdesignx_network as convert_ezdesignx_network_summary
from sumo_mcp.mcp_tools.route import random_trips, duarouter, od2trips
from sumo_mcp.mcp_tools.signal import tls_cycle_adaptation, tls_coordinator
from sumo_mcp.mcp_tools.analysis import analyze_fcd
from sumo_mcp.mcp_tools.vehicle import (
    get_vehicles, get_vehicle_speed, get_vehicle_position,
    get_vehicle_acceleration, get_vehicle_lane, get_vehicle_route,
    get_simulation_info
)
from sumo_mcp.mcp_tools.rl import find_sumo_rl_scenario_files, list_rl_scenarios, run_rl_training
from sumo_mcp.models import ErrorCode, artifact, legacy_result, make_error, make_result
from sumo_mcp.utils.connection import connection_manager
from sumo_mcp.utils.sumo import find_sumo_binary, find_sumo_home, find_sumo_tools_dir
from sumo_mcp.workflows.sim_gen import sim_gen_workflow
from sumo_mcp.workflows.signal_opt import signal_opt_workflow
from sumo_mcp.workflows.rl_train import rl_train_workflow

# Configure logging to stderr to not interfere with MCP stdio transport
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ensure TraCI never writes to stdout by default (MCP stdio safety).
ensure_traci_start_stdout_suppressed()

# Initialize MCP Server (official SDK)
server = FastMCP("SUMO-MCP-Server")

# All tools return the v0.2 structured envelope (see sumo_mcp.models):
# {ok, tool, summary, action?, data?, artifacts?, metrics?, command?,
#  stdout_tail?, stderr_tail?, warnings?, error?, job_id?}.
# The v0.1 human-readable string return is preserved verbatim in `summary`.
Envelope = Dict[str, Any]

_ENVELOPE_NOTE = (
    " Returns a structured JSON envelope: {ok, tool, summary, action?, data?, "
    "artifacts?, error{code,message,remediation}?}; `summary` is human-readable."
)


def _ezdesignx_artifacts(output_dir: str) -> List[Dict[str, Any]]:
    """Collect the well-known ezdesignX conversion outputs from output_dir."""
    artifacts: List[Dict[str, Any]] = []
    out = Path(output_dir)
    if not out.is_dir():
        return artifacts
    for pattern, role in (
        ("*.net.xml", "network"),
        ("*.sumocfg", "sumo_config"),
        ("*report*.json", "conversion_report"),
    ):
        for path in sorted(out.glob(pattern)):
            artifacts.append(artifact(str(path), role))
    return artifacts


# --- 1. Network Management ---


@server.tool(description="Manage SUMO network (generate, convert, download OSM, or convert ezdesignX)."
             + _ENVELOPE_NOTE)
def manage_network(action: str, output_file: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    """
    actions:
    - generate: params={'grid': bool, 'grid_number': int} or spider params
      ({'spider': True, 'arms'|'arm_number', 'circles'|'circle_number',
        'ring_radius'|'space_radius', 'radial_distance'|'attach_length', 'omit_center'})
    - convert | convert_osm: params={'osm_file': str}
    - download_osm: output_file is treated as output_dir. params={'bbox': str, 'prefix': str}
    - convert_ezdesignx: output_file is treated as output_dir. params={'input_json': str,
      'validation': 'basic'|'topology'|'strict', 'netconvert_bin'?, 'sumo_bin'?, 'sumo_gui_bin'?}
    """
    tool = "manage_network"
    params = params or {}
    options = params.get("options")

    def _invalid(message: str) -> Envelope:
        return make_error(tool, message, code=ErrorCode.INVALID_ARGUMENT, action=action)

    if action == "generate":
        spider = bool(params.get("spider", False))
        grid = bool(params.get("grid", True))
        grid_number = params.get("grid_number", 3)

        if spider:
            # Spider network takes precedence over grid settings.
            grid = False
            options_list = list(options or [])

            def _strip_flag(flag: str, has_value: bool = False) -> None:
                while flag in options_list:
                    idx = options_list.index(flag)
                    options_list.pop(idx)
                    if has_value and idx < len(options_list):
                        options_list.pop(idx)

            def _set_option(flag: str, value: str) -> None:
                if flag in options_list:
                    idx = options_list.index(flag)
                    if idx + 1 < len(options_list):
                        options_list[idx + 1] = value
                    else:
                        options_list.append(value)
                else:
                    options_list.extend([flag, value])

            # Enforce Spider/Grid mutual exclusion even when the user provided `options`.
            _strip_flag("--grid")
            _strip_flag("--grid.number", has_value=True)

            if "--spider" not in options_list:
                options_list.insert(0, "--spider")

            arms_raw = params.get("arms", params.get("arm_number"))
            if arms_raw is not None:
                try:
                    arms = int(arms_raw)
                except (TypeError, ValueError):
                    return _invalid(f"Error: arms must be a positive integer, got {arms_raw!r}")
                if arms <= 0:
                    return _invalid("Error: arms must be > 0")
                _set_option("--spider.arm-number", str(arms))

            circles_raw = params.get("circles", params.get("circle_number"))
            if circles_raw is not None:
                try:
                    circles = int(circles_raw)
                except (TypeError, ValueError):
                    return _invalid(f"Error: circles must be a positive integer, got {circles_raw!r}")
                if circles <= 0:
                    return _invalid("Error: circles must be > 0")
                _set_option("--spider.circle-number", str(circles))

            space_radius_raw = params.get("ring_radius", params.get("space_radius"))
            if space_radius_raw is not None:
                try:
                    space_radius = float(space_radius_raw)
                except (TypeError, ValueError):
                    return _invalid(f"Error: ring_radius must be a number, got {space_radius_raw!r}")
                if space_radius <= 0:
                    return _invalid("Error: ring_radius must be > 0")
                _set_option("--spider.space-radius", str(space_radius))

            attach_length_raw = params.get("radial_distance", params.get("attach_length"))
            if attach_length_raw is not None:
                try:
                    attach_length = float(attach_length_raw)
                except (TypeError, ValueError):
                    return _invalid(f"Error: radial_distance must be a number, got {attach_length_raw!r}")
                if attach_length < 0:
                    return _invalid("Error: radial_distance must be >= 0")
                _set_option("--spider.attach-length", str(attach_length))

            omit_center_raw = params.get("omit_center")
            if omit_center_raw:
                if "--spider.omit-center" not in options_list:
                    options_list.append("--spider.omit-center")

            options = options_list

        text = netgenerate(output_file, grid, grid_number, options)
        return legacy_result(tool, text, action=action, artifacts=[artifact(output_file, "network")])

    elif action == "convert" or action == "convert_osm":
        osm_file = params.get("osm_file")
        if not osm_file:
            return _invalid("Error: osm_file required for convert action")
        text = netconvert(osm_file, output_file, options)
        return legacy_result(tool, text, action=action, artifacts=[artifact(output_file, "network")])

    elif action == "download_osm":
        # output_file here acts as output_dir
        bbox = params.get("bbox")
        prefix = params.get("prefix", "osm")
        if not bbox:
            return _invalid("Error: bbox required for download_osm action")
        text = osm_get(bbox, output_file, prefix, options)
        return legacy_result(
            tool, text, action=action,
            data={"output_dir": output_file, "bbox": bbox, "prefix": prefix},
        )

    elif action == "convert_ezdesignx":
        input_json = params.get("input_json")
        if not input_json:
            return _invalid("Error: input_json required for convert_ezdesignx action")
        validation = str(params.get("validation", "topology"))
        netconvert_bin = params.get("netconvert_bin")
        sumo_bin = params.get("sumo_bin")
        sumo_gui_bin = params.get("sumo_gui_bin")
        text = convert_ezdesignx_network_summary(
            input_json=str(input_json),
            output_dir=output_file,
            validation=validation,
            netconvert_bin=str(netconvert_bin) if netconvert_bin is not None else None,
            sumo_bin=str(sumo_bin) if sumo_bin is not None else None,
            sumo_gui_bin=str(sumo_gui_bin) if sumo_gui_bin is not None else None,
        )
        return legacy_result(tool, text, action=action, artifacts=_ezdesignx_artifacts(output_file))

    return _invalid(f"Unknown action: {action}")


@server.tool(description="Convert an ezdesignX v1 JSON or JSONC intersection file into SUMO network artifacts."
             + _ENVELOPE_NOTE)
def convert_ezdesignx_network(
    input_json: str,
    output_dir: str,
    validation: str = "topology",
    netconvert_bin: Optional[str] = None,
    sumo_bin: Optional[str] = None,
    sumo_gui_bin: Optional[str] = None,
) -> Envelope:
    text = convert_ezdesignx_network_summary(
        input_json=input_json,
        output_dir=output_dir,
        validation=validation,
        netconvert_bin=netconvert_bin,
        sumo_bin=sumo_bin,
        sumo_gui_bin=sumo_gui_bin,
    )
    return legacy_result(
        "convert_ezdesignx_network", text,
        artifacts=_ezdesignx_artifacts(output_dir),
        data={"input_json": input_json, "output_dir": output_dir, "validation": validation},
    )

# --- 2. Demand Management ---


@server.tool(description="Manage traffic demand (random trips, OD matrix, routing)." + _ENVELOPE_NOTE)
def manage_demand(action: str, net_file: str, output_file: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    """
    actions:
    - generate_random | random_trips: params={'end_time'|'end': int, 'period': float}
    - convert_od | od_matrix: params={'od_file': str} (net_file unused but kept for consistency)
    - compute_routes | routing: params={'route_files': str} (input trips)
    """
    tool = "manage_demand"
    params = params or {}
    options = params.get("options")

    def _invalid(message: str) -> Envelope:
        return make_error(tool, message, code=ErrorCode.INVALID_ARGUMENT, action=action)

    if action == "generate_random" or action == "random_trips":
        # Backward/compat aliases: some clients use `end` instead of `end_time`.
        end_time_raw = params.get("end_time", params.get("end", 3600))
        period_raw = params.get("period", 1.0)
        try:
            end_time = int(end_time_raw)
        except (TypeError, ValueError):
            return _invalid(f"Error: end_time must be an integer, got {end_time_raw!r}")
        try:
            period = float(period_raw)
        except (TypeError, ValueError):
            return _invalid(f"Error: period must be a number, got {period_raw!r}")
        text = random_trips(net_file, output_file, end_time, period, options)
        return legacy_result(tool, text, action=action, artifacts=[artifact(output_file, "trips")])

    elif action == "convert_od" or action == "od_matrix":
        od_file = params.get("od_file")
        if not od_file:
            return _invalid("Error: od_file required for convert_od")
        text = od2trips(od_file, output_file, options)
        return legacy_result(tool, text, action=action, artifacts=[artifact(output_file, "trips")])

    elif action == "compute_routes" or action == "routing":
        route_files = params.get("route_files")  # Input trips file
        if not route_files:
            return _invalid("Error: route_files required for compute_routes")
        text = duarouter(net_file, route_files, output_file, options)
        return legacy_result(tool, text, action=action, artifacts=[artifact(output_file, "routes")])

    return _invalid(f"Unknown action: {action}")

# --- 3. Simulation Control ---


@server.tool(description="Control SUMO simulation via TraCI (connect, step, disconnect)." + _ENVELOPE_NOTE)
def control_simulation(action: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    """
    actions:
    - connect: params={'config_file': str, 'gui': bool, 'port': int (default 8813),
      'host': str (default 'localhost'), 'timeout_s'|'timeout': float}
      (omit config_file to attach to an already-running SUMO instance)
    - step: params={'step': float, 'timeout_s'?: float}
    - disconnect: params={'timeout_s'?: float}
    """
    tool = "control_simulation"
    params = params or {}

    try:
        timeout_s_raw = params.get("timeout_s", params.get("timeout"))
        timeout_s: Optional[float] = None
        if timeout_s_raw is not None:
            try:
                timeout_s = float(timeout_s_raw)
            except (TypeError, ValueError):
                return make_error(
                    tool, f"Error: timeout_s must be a number, got {timeout_s_raw!r}",
                    code=ErrorCode.INVALID_ARGUMENT, action=action,
                )

        if action == "connect":
            config_file = params.get("config_file")
            gui = params.get("gui", False)
            port = params.get("port", 8813)
            host = params.get("host", "localhost")
            if timeout_s is None:
                connection_manager.connect(config_file, gui, port, host)
            else:
                connection_manager.connect(config_file, gui, port, host, timeout_s=timeout_s)
            return make_result(
                tool, "Successfully connected to SUMO.", action=action,
                data={"config_file": config_file, "gui": bool(gui), "port": port, "host": host,
                      "mode": "launch" if config_file else "attach"},
            )

        elif action == "step":
            step = params.get("step", 0)
            if timeout_s is None:
                connection_manager.simulation_step(step)
            else:
                connection_manager.simulation_step(step, timeout_s=timeout_s)
            return make_result(tool, "Simulation advanced.", action=action, data={"step": step})

        elif action == "disconnect":
            if timeout_s is None:
                connection_manager.disconnect()
            else:
                connection_manager.disconnect(timeout_s=timeout_s)
            return make_result(tool, "Successfully disconnected from SUMO.", action=action)

    except Exception as e:
        return make_error(
            tool, f"Error in control_simulation ({action}): {type(e).__name__}: {e}",
            code=ErrorCode.CONNECTION_ERROR, action=action,
        )

    return make_error(tool, f"Unknown action: {action}", code=ErrorCode.INVALID_ARGUMENT, action=action)

# --- 4. Query State ---


@server.tool(description="Query simulation state (vehicles, speed, position). Requires active TraCI connection."
             + _ENVELOPE_NOTE)
def query_simulation_state(target: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    """
    targets:
    - vehicle_list | vehicles: no params
    - vehicle_variable: params={'vehicle_id': str,
      'variable': 'speed'|'position'|'lane'|'acceleration'|'route'}
    - simulation: no params
    """
    tool = "query_simulation_state"
    params = params or {}

    try:
        if target == "vehicle_list" or target == "vehicles":
            vehs = get_vehicles()
            return make_result(
                tool, f"Active vehicles: {vehs}", action=target,
                data={"vehicles": list(vehs), "count": len(vehs)},
            )

        elif target == "vehicle_variable":
            v_id = params.get("vehicle_id")
            var = params.get("variable")
            if not v_id or not var:
                return make_error(
                    tool, "Error: vehicle_id and variable required",
                    code=ErrorCode.INVALID_ARGUMENT, action=target,
                )

            getters = {
                "speed": get_vehicle_speed,
                "position": get_vehicle_position,
                "acceleration": get_vehicle_acceleration,
                "lane": get_vehicle_lane,
                "route": get_vehicle_route,
            }
            if var not in getters:
                return make_error(
                    tool, f"Unknown variable: {var}", code=ErrorCode.INVALID_ARGUMENT, action=target,
                )
            value = getters[var](v_id)
            json_value: Any = list(value) if isinstance(value, tuple) else value
            return make_result(
                tool, f"{var.capitalize()}: {value}", action=target,
                data={"vehicle_id": v_id, "variable": var, "value": json_value},
            )

        elif target == "simulation":
            info = get_simulation_info()
            return make_result(
                tool, f"Simulation Info: {info}", action=target,
                data={"simulation": info if isinstance(info, dict) else str(info)},
            )

    except Exception as e:
        return make_error(
            tool, f"Error querying state: {type(e).__name__}: {e}",
            code=ErrorCode.CONNECTION_ERROR, action=target,
        )

    return make_error(tool, f"Unknown target: {target}", code=ErrorCode.INVALID_ARGUMENT, action=target)

# --- 5. Optimize Signals ---


@server.tool(description="Optimize traffic signals (cycle adaptation or coordination)." + _ENVELOPE_NOTE)
def optimize_traffic_signals(
    method: str, net_file: str, route_file: str, output_file: str, params: Optional[Dict[str, Any]] = None
) -> Envelope:
    """
    methods:
    - cycle_adaptation | Websters: adapt TLS cycles (tlsCycleAdaptation.py)
    - coordination: TLS green-wave coordination (tlsCoordinator.py)
    """
    tool = "optimize_traffic_signals"
    params = params or {}
    options = params.get("options")

    if method == "cycle_adaptation" or method == "Websters":
        text = tls_cycle_adaptation(net_file, route_file, output_file)
        return legacy_result(tool, text, action=method, artifacts=[artifact(output_file, "tls_program")])
    elif method == "coordination":
        text = tls_coordinator(net_file, route_file, output_file, options)
        return legacy_result(tool, text, action=method, artifacts=[artifact(output_file, "tls_program")])

    return make_error(tool, f"Unknown method: {method}", code=ErrorCode.INVALID_ARGUMENT, action=method)

# --- 6. Workflows ---


@server.tool(
    description="""Run high-level SUMO workflows. Available workflows:

**sim_gen_eval** - Generate grid network, simulate traffic, analyze results.
  params:
  - grid_number (int): Grid size NxN. Default=3. Aliases: grid_size, size
  - sim_seconds (int): Simulation duration in seconds. Default=100. Aliases: steps, duration, end_time
  - output_dir (str): Output directory. Default="output"
  Example: run_workflow("sim_gen_eval", {"grid_number": 3, "sim_seconds": 1000})

**signal_opt** - Optimize traffic signals for existing network.
  params:
  - net_file (str): Path to .net.xml file. REQUIRED
  - route_file (str): Path to .rou.xml file. REQUIRED
  - sim_seconds (int): Simulation duration. Default=3600. Aliases: steps, duration
  - use_coordinator (bool): Use tlsCoordinator instead of tlsCycleAdaptation. Default=false
  - output_dir (str): Output directory. Default="output"

**rl_train** - Train RL agent for traffic signal control.
  params:
  - scenario_name (str): Built-in scenario name (use manage_rl_task("list_scenarios") to see options). Aliases: scenario
  - episodes (int): Number of training episodes. Default=5. Aliases: num_episodes
  - steps (int): Steps per episode. Default=1000. Aliases: steps_per_episode
  - output_dir (str): Output directory. Default="output"
""" + _ENVELOPE_NOTE
)
def run_workflow(workflow_name: str, params: Dict[str, Any]) -> Envelope:
    """Execute a high-level workflow."""
    tool = "run_workflow"

    # Helper to get param with aliases
    def get_param(keys: List[str], default: Any = None) -> Any:
        for k in keys:
            if k in params:
                return params[k]
        return default

    if workflow_name in ("sim_gen_eval", "sim_gen_workflow", "sim_gen"):
        grid_number = get_param(["grid_number", "grid_size", "size"], 3)
        sim_seconds = get_param(["sim_seconds", "steps", "duration", "end_time"], 100)
        output_dir = get_param(["output_dir"], "output")

        text = sim_gen_workflow(output_dir, int(grid_number), int(sim_seconds))
        return legacy_result(
            tool, text, action=workflow_name,
            data={"workflow": "sim_gen_eval", "output_dir": output_dir,
                  "grid_number": int(grid_number), "sim_seconds": int(sim_seconds)},
        )

    elif workflow_name in ("signal_opt", "signal_opt_workflow"):
        net_file = get_param(["net_file"], "")
        route_file = get_param(["route_file"], "")

        if not net_file or not route_file:
            return make_error(
                tool, "Error: signal_opt requires net_file and route_file parameters.",
                code=ErrorCode.INVALID_ARGUMENT, action=workflow_name,
            )

        sim_seconds = get_param(["sim_seconds", "steps", "duration"], 3600)
        use_coordinator = get_param(["use_coordinator"], False)
        output_dir = get_param(["output_dir"], "output")

        text = signal_opt_workflow(net_file, route_file, output_dir, int(sim_seconds), bool(use_coordinator))
        return legacy_result(
            tool, text, action=workflow_name,
            data={"workflow": "signal_opt", "output_dir": output_dir,
                  "net_file": net_file, "route_file": route_file,
                  "sim_seconds": int(sim_seconds), "use_coordinator": bool(use_coordinator)},
        )

    elif workflow_name == "rl_train":
        scenario_name = get_param(["scenario_name", "scenario"], "")
        episodes = get_param(["episodes", "num_episodes"], 5)
        steps = get_param(["steps", "steps_per_episode"], 1000)
        output_dir = get_param(["output_dir"], "output")

        text = rl_train_workflow(scenario_name, output_dir, int(episodes), int(steps))
        return legacy_result(
            tool, text, action=workflow_name,
            data={"workflow": "rl_train", "scenario_name": scenario_name,
                  "episodes": int(episodes), "steps": int(steps), "output_dir": output_dir},
        )

    return make_error(
        tool, f"Unknown workflow: {workflow_name}. Available: sim_gen_eval, signal_opt, rl_train",
        code=ErrorCode.INVALID_ARGUMENT, action=workflow_name,
    )

# --- 7. RL Task Management ---


@server.tool(description="Manage RL tasks (list scenarios, custom training)." + _ENVELOPE_NOTE)
def manage_rl_task(action: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    """
    actions:
    - list_scenarios: no params
    - train_custom: params={'scenario'|'scenario_name' OR 'net_file'+'route_file',
      'out_dir'|'output_dir', 'episodes'|'num_episodes', 'steps'|'steps_per_episode',
      'algorithm', 'reward_type'}
    """
    tool = "manage_rl_task"
    params = params or {}

    def _invalid(message: str) -> Envelope:
        return make_error(tool, message, code=ErrorCode.INVALID_ARGUMENT, action=action)

    if action == "list_scenarios":
        scenarios = list_rl_scenarios()
        return legacy_result(
            tool, str(scenarios), action=action,
            data={"scenarios": scenarios},
        )

    elif action == "train_custom":
        scenario_name = params.get("scenario") or params.get("scenario_name")
        net_file = params.get("net_file")
        route_file = params.get("route_file")

        if scenario_name:
            net_file, route_file, err = find_sumo_rl_scenario_files(str(scenario_name))
            if err:
                return make_error(tool, err, code=ErrorCode.FILE_NOT_FOUND, action=action)

        if not net_file or not route_file:
            return _invalid(
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
            return _invalid(f"Error: episodes must be an integer, got {episodes_raw!r}")
        try:
            steps_per_episode = int(steps_raw)
        except (TypeError, ValueError):
            return _invalid(f"Error: steps must be an integer, got {steps_raw!r}")

        if episodes <= 0:
            return _invalid("Error: episodes must be > 0")
        if steps_per_episode <= 0:
            return _invalid("Error: steps must be > 0")

        algorithm = str(params.get("algorithm", "ql"))
        reward_type = str(params.get("reward_type", "diff-waiting-time"))

        text = run_rl_training(
            net_file=str(net_file),
            route_file=str(route_file),
            out_dir=str(out_dir),
            episodes=episodes,
            steps_per_episode=steps_per_episode,
            algorithm=algorithm,
            reward_type=reward_type,
        )
        return legacy_result(
            tool, text, action=action,
            data={"net_file": str(net_file), "route_file": str(route_file),
                  "out_dir": str(out_dir), "episodes": episodes,
                  "steps_per_episode": steps_per_episode,
                  "algorithm": algorithm, "reward_type": reward_type},
        )

    return _invalid(f"Unknown action: {action}")

# --- Legacy/Misc ---


@server.tool(name="get_sumo_info", description="Get the version, paths and diagnostics of the installed SUMO."
             + _ENVELOPE_NOTE)
def get_sumo_info() -> Envelope:
    tool = "get_sumo_info"
    try:
        sumo_binary = find_sumo_binary("sumo")
        if not sumo_binary:
            return make_error(
                tool,
                "Error: Could not locate SUMO executable. "
                "Please ensure SUMO is installed and either `sumo` is available in PATH or `SUMO_HOME` is set.",
                code=ErrorCode.SUMO_NOT_FOUND,
                remediation="Install SUMO (https://eclipse.dev/sumo) or `pip install eclipse-sumo`, "
                            "then set SUMO_HOME or add its bin/ directory to PATH.",
            )

        result = subprocess.run(
            [sumo_binary, "--version"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        version_output = (result.stdout.splitlines() or ["Unknown"])[0]

        sumo_home = find_sumo_home()
        tools_dir = find_sumo_tools_dir()
        summary = "\n".join(
            [
                f"SUMO Binary: {sumo_binary}",
                f"SUMO Version: {version_output}",
                f"SUMO_HOME: {sumo_home or 'Not Set'}",
                f"SUMO Tools Dir: {tools_dir or 'Not Found'}",
            ]
        )
        return make_result(
            tool, summary,
            data={
                "sumo_binary": sumo_binary,
                "sumo_version": version_output,
                "sumo_home": sumo_home,
                "tools_dir": tools_dir,
            },
        )
    except Exception as e:
        return make_error(tool, f"Error checking SUMO: {str(e)}", code=ErrorCode.EXECUTION_FAILED)


@server.tool(name="run_simple_simulation", description="Run a SUMO simulation using a config file." + _ENVELOPE_NOTE)
def run_simple_simulation_tool(config_path: str, steps: int = 100) -> Envelope:
    text = run_simple_simulation(config_path, steps)
    return legacy_result(
        "run_simple_simulation", text,
        data={"config_path": config_path, "steps": steps},
    )


@server.tool(description="Analyze FCD (floating car data) output." + _ENVELOPE_NOTE)
def run_analysis(fcd_file: str) -> Envelope:
    text = analyze_fcd(fcd_file)
    return legacy_result("run_analysis", text, data={"fcd_file": fcd_file})


def main() -> None:
    """Run the SUMO MCP server on stdio (console-script / ``python -m`` entry point)."""
    # NOTE:
    # MCP stdio transport relies on AnyIO/asyncio to process thread callbacks.
    # In some environments, a lack of scheduled timers can cause the event loop to
    # block indefinitely while waiting for stdio worker-thread results. A small
    # periodic sleep keeps the loop responsive without emitting any stdout output.
    import anyio

    async def _wakeup_task() -> None:
        while True:
            await anyio.sleep(0.1)

    async def _run_stdio_with_wakeup() -> None:
        async with anyio.create_task_group() as tg:
            tg.start_soon(_wakeup_task)
            await server.run_stdio_async()
            # run_stdio_async() returns on client disconnect (stdin EOF); the
            # wakeup task loops forever, so cancel it or the process never exits.
            tg.cancel_scope.cancel()

    anyio.run(_run_stdio_with_wakeup)


if __name__ == "__main__":
    main()
