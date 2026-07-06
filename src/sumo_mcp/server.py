import logging
import subprocess
import sys
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
from sumo_mcp.analysis import analyze_output
from sumo_mcp.catalog import describe_command, list_commands
from sumo_mcp.execution import run_cli
from sumo_mcp.jobs import job_manager
from sumo_mcp.models import ErrorCode, artifact, legacy_result, make_error, make_result
from sumo_mcp.resources.provider import (
    commands_resource,
    diagnostics_resource,
    job_resource,
    read_static_resource,
    tool_catalog_resource,
)
from sumo_mcp.rl import create_run, list_algorithms as list_rl_algorithms_v2, list_runs, load_run
from sumo_mcp.rl.algorithms import training_backend
from sumo_mcp.rl.evaluation import compare_run, evaluate_run
from sumo_mcp.rl.preflight import validate_rl_environment
from sumo_mcp.rl.runs import latest_checkpoint, load_config, update_config, update_run
from sumo_mcp.sessions import ALLOWED_CALLS, session_manager
from sumo_mcp.utils.connection import connection_manager
from sumo_mcp.utils.jsonsafe import to_json_safe
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


@server.resource("sumo://diagnostics", mime_type="application/json")
def sumo_diagnostics_resource() -> str:
    """Dynamic SUMO installation, command catalog, and RL dependency diagnostics."""
    return diagnostics_resource()


@server.resource("sumo://tool-catalog", mime_type="text/markdown")
def sumo_tool_catalog_resource() -> str:
    """Compact guide to the fixed 16-tool SUMO-MCP surface."""
    return tool_catalog_resource()


@server.resource("sumo://commands", mime_type="application/json")
def sumo_commands_resource() -> str:
    """Tier-1 SUMO command catalog entries with availability state."""
    return commands_resource()


@server.resource("sumo://guide/tool-selection", mime_type="text/markdown")
def sumo_tool_selection_guide() -> str:
    """Decision tree for choosing the correct SUMO-MCP tool."""
    return read_static_resource("tool-selection.md")


@server.resource("sumo://guide/workflows", mime_type="text/markdown")
def sumo_workflows_guide() -> str:
    """Common end-to-end SUMO workflow recipes."""
    return read_static_resource("workflows.md")


@server.resource("sumo://guide/rl-training", mime_type="text/markdown")
def sumo_rl_training_guide() -> str:
    """SUMO-RL algorithm selection, training loop, and common failures."""
    return read_static_resource("rl-training.md")


@server.resource("sumo://guide/troubleshooting", mime_type="text/markdown")
def sumo_troubleshooting_guide() -> str:
    """Error-code oriented troubleshooting guide."""
    return read_static_resource("troubleshooting.md")


@server.resource("sumo://jobs/{job_id}", mime_type="application/json")
def sumo_job_resource(job_id: str) -> str:
    """Read a background job manifest/result/log tail by id."""
    return job_resource(job_id)


@server.prompt(
    name="build-simulation-from-scratch",
    description="Guide an agent through abstract network, demand, route, simulation, and analysis.",
)
def prompt_build_simulation_from_scratch(grid_size: int = 3, sim_seconds: int = 1000) -> str:
    return (
        "Build a SUMO simulation from scratch. Use `manage_network(action=\"generate\")` "
        f"with grid_number={grid_size}, then `manage_demand(action=\"generate_random\")`, "
        "`manage_demand(action=\"compute_routes\")`, run the simulation with "
        "`run_simple_simulation` or `run_sumo_binary(name=\"sumo\")`, and analyze outputs "
        f"with `analyze_sumo_output`. Use sim_seconds={sim_seconds}. Return artifacts and metrics."
    )


@server.prompt(name="import-osm-area", description="Guide OSM bbox import into a runnable SUMO scenario.")
def prompt_import_osm_area(bbox: str, sim_seconds: int = 1000) -> str:
    return (
        f"Import OSM bbox `{bbox}`. Use `manage_network(action=\"download_osm\")`, then "
        "`manage_network(action=\"convert\")` or `run_sumo_tool(name=\"osmBuild.py\")`. "
        "Generate demand with `manage_demand`, route with `manage_demand(action=\"compute_routes\")` "
        f"or `run_sumo_binary(name=\"duarouter\")`, simulate for {sim_seconds}s, and analyze outputs."
    )


@server.prompt(name="optimize-signals", description="Guide signal baseline, optimization, and comparison.")
def prompt_optimize_signals(net_file: str, route_file: str, sim_seconds: int = 3600) -> str:
    return (
        f"Optimize signals for net `{net_file}` and route `{route_file}`. Prefer "
        "`run_workflow(workflow_name=\"signal_opt\")` for baseline-vs-optimized comparison. "
        f"Use sim_seconds={sim_seconds}. If raw signal plans are requested, call "
        "`optimize_traffic_signals` and explain that the output is an additional file."
    )


@server.prompt(name="rl-train-and-evaluate", description="Guide RL preflight, training job, evaluation, comparison.")
def prompt_rl_train_and_evaluate(scenario_or_net: str, algorithm: str = "ql", episodes: int = 3) -> str:
    return (
        f"Run an RL training loop for `{scenario_or_net}` using algorithm `{algorithm}`. "
        "First call `manage_rl_task(action=\"list_algorithms\")`, then "
        "`manage_rl_task(action=\"validate_env\")`. Start `manage_rl_task(action=\"train\")`, "
        "poll `manage_rl_task(action=\"status\")`, then call `manage_rl_task(action=\"evaluate\")` "
        f"and `manage_rl_task(action=\"compare\")`. Use episodes={episodes} unless the user overrides it."
    )


@server.prompt(name="analyze-simulation-outputs", description="Guide structured analysis of SUMO output files.")
def prompt_analyze_simulation_outputs(output_dir: str) -> str:
    return (
        f"Analyze SUMO outputs under `{output_dir}`. Prefer `analyze_sumo_output` for XML outputs "
        "such as summary, tripinfo, fcd, queue, and emission files. Use `run_analysis` only for "
        "legacy FCD CSV summaries. Report metrics, truncation, and artifact paths."
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


def _legacy_whitelisted_call(domain: str, method: str, args: List[Any]) -> Any:
    """Run one whitelisted TraCI call on the v0.1 global connection."""
    allowed = ALLOWED_CALLS.get(domain)
    if allowed is None:
        raise PermissionError(
            f"TraCI domain {domain!r} is not exposed. Available: {sorted(ALLOWED_CALLS)}"
        )
    if method not in allowed:
        raise PermissionError(
            f"Method {domain}.{method} is not whitelisted. Allowed for {domain}: {sorted(allowed)}"
        )
    import traci
    return getattr(getattr(traci, domain), method)(*args)


def _traci_invoke(session: Optional[str], domain: str, method: str, args: List[Any]) -> Any:
    """Dispatch a whitelisted TraCI call to a named session or the legacy connection."""
    if session is not None:
        return session_manager.call(session, domain, method, args)
    return _legacy_whitelisted_call(domain, method, args)


def _json_safe(value: Any) -> tuple[Any, List[str]]:
    """Normalize TraCI return values before placing them in MCP envelopes."""
    return to_json_safe(value)


# action -> (domain, method, required param names in call order)
_SETTER_ACTIONS: Dict[str, Any] = {
    "set_tls_phase": ("trafficlight", "setPhase", ["tls_id", "phase"]),
    "set_tls_program": ("trafficlight", "setProgram", ["tls_id", "program_id"]),
    "set_tls_state": ("trafficlight", "setRedYellowGreenState", ["tls_id", "state"]),
    "set_tls_phase_duration": ("trafficlight", "setPhaseDuration", ["tls_id", "duration"]),
    "set_vehicle_speed": ("vehicle", "setSpeed", ["vehicle_id", "speed"]),
    "slow_down_vehicle": ("vehicle", "slowDown", ["vehicle_id", "speed", "duration"]),
    "reroute_vehicle": ("vehicle", "rerouteTraveltime", ["vehicle_id"]),
    "change_vehicle_target": ("vehicle", "changeTarget", ["vehicle_id", "edge_id"]),
    "resume_vehicle": ("vehicle", "resume", ["vehicle_id"]),
    "remove_vehicle": ("vehicle", "remove", ["vehicle_id"]),
    "change_lane": ("vehicle", "changeLane", ["vehicle_id", "lane_index", "duration"]),
}


@server.tool(description=(
    "Control SUMO simulation via TraCI: connect/step/disconnect, named multi-session "
    "management, online traffic-signal and vehicle intervention (setters). Without the "
    "`session` param the v0.1 single global connection is used; pass session=<label> "
    "to target a named session (open one via action='connect' with session=<label>)."
    + _ENVELOPE_NOTE))
def control_simulation(action: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    """
    Connection actions:
    - connect: params={'config_file': str, 'gui': bool, 'port': int (default 8813),
      'host': str, 'timeout_s'|'timeout': float, 'session'?: str, 'options'?: [str]}
      Without 'session': v0.1 global connection (omit config_file to attach to a
      running SUMO). With 'session': opens a named parallel session (config_file required).
    - step: params={'step': float (legacy: target time), 'steps': int (session: step count),
      'timeout_s'?: float, 'session'?: str}
    - disconnect: params={'timeout_s'?: float, 'session'?: str}
    - list_sessions / close_all_sessions: no params

    Online intervention actions (all accept 'session'; without it the global connection):
    - set_tls_phase {tls_id, phase} / set_tls_program {tls_id, program_id}
    - set_tls_state {tls_id, state} (e.g. "GrGr") / set_tls_phase_duration {tls_id, duration}
    - set_vehicle_speed {vehicle_id, speed} (-1 returns control to the car-following model)
    - slow_down_vehicle {vehicle_id, speed, duration}
    - stop_vehicle {vehicle_id, edge_id, pos?, lane_index?, duration?} / resume_vehicle {vehicle_id}
    - reroute_vehicle {vehicle_id} / change_vehicle_target {vehicle_id, edge_id}
    - add_vehicle {vehicle_id, route_id, type_id?, depart?} / remove_vehicle {vehicle_id}
    - change_lane {vehicle_id, lane_index, duration}
    - call {domain, method, args?}: any whitelisted TraCI method (see error hints for the whitelist)
    """
    tool = "control_simulation"
    params = params or {}
    session = params.get("session")

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
            if session is not None:
                if not config_file:
                    return make_error(
                        tool, "Error: config_file required when opening a named session",
                        code=ErrorCode.INVALID_ARGUMENT, action=action,
                    )
                info = session_manager.open(
                    str(config_file), label=str(session), gui=bool(gui),
                    extra_args=params.get("options"),
                    timeout_s=timeout_s if timeout_s is not None else 60.0,
                )
                return make_result(
                    tool, f"Session '{info.label}' connected to SUMO.", action=action,
                    data=info.to_dict(),
                )
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
            if session is not None:
                steps = int(params.get("steps", params.get("step", 1)) or 1)
                result = session_manager.step(str(session), steps=steps)
                return make_result(
                    tool, f"Session '{result['label']}' advanced to t={result['sim_time']}.",
                    action=action, data=result,
                )
            step = params.get("step", 0)
            if timeout_s is None:
                connection_manager.simulation_step(step)
            else:
                connection_manager.simulation_step(step, timeout_s=timeout_s)
            return make_result(tool, "Simulation advanced.", action=action, data={"step": step})

        elif action == "disconnect":
            if session is not None:
                closed = session_manager.close(str(session))
                return make_result(
                    tool, f"Session '{closed['label']}' closed.", action=action, data=closed,
                )
            if timeout_s is None:
                connection_manager.disconnect()
            else:
                connection_manager.disconnect(timeout_s=timeout_s)
            return make_result(tool, "Successfully disconnected from SUMO.", action=action)

        elif action == "list_sessions":
            sessions = session_manager.list_sessions()
            return make_result(
                tool, f"{len(sessions)} active session(s).", action=action,
                data={"sessions": sessions},
            )

        elif action == "close_all_sessions":
            count = session_manager.close_all()
            return make_result(tool, f"Closed {count} session(s).", action=action,
                               data={"closed": count})

        elif action in _SETTER_ACTIONS:
            domain, method, required = _SETTER_ACTIONS[action]
            args = []
            for key in required:
                if key not in params:
                    return make_error(
                        tool, f"Error: {key} required for {action}",
                        code=ErrorCode.INVALID_ARGUMENT, action=action,
                    )
                args.append(params[key])
            _traci_invoke(session, domain, method, args)
            return make_result(
                tool, f"{action} applied.", action=action,
                data={"domain": domain, "method": method, "args": args, "session": session},
            )

        elif action == "stop_vehicle":
            for key in ("vehicle_id", "edge_id"):
                if key not in params:
                    return make_error(tool, f"Error: {key} required for stop_vehicle",
                                      code=ErrorCode.INVALID_ARGUMENT, action=action)
            args = [params["vehicle_id"], params["edge_id"],
                    float(params.get("pos", 1.0)), int(params.get("lane_index", 0)),
                    float(params.get("duration", 2 ** 30))]
            _traci_invoke(session, "vehicle", "setStop", args)
            return make_result(tool, "stop_vehicle applied.", action=action,
                               data={"args": args, "session": session})

        elif action == "add_vehicle":
            for key in ("vehicle_id", "route_id"):
                if key not in params:
                    return make_error(tool, f"Error: {key} required for add_vehicle",
                                      code=ErrorCode.INVALID_ARGUMENT, action=action)
            args = [params["vehicle_id"], params["route_id"]]
            kwargs_pos = {"typeID": params.get("type_id", "DEFAULT_VEHTYPE"),
                          "depart": str(params.get("depart", "now"))}
            # vehicle.add(vehID, routeID, typeID=..., depart=...) — positional call keeps
            # the whitelist executor simple.
            _traci_invoke(session, "vehicle", "add",
                          args + [kwargs_pos["typeID"], kwargs_pos["depart"]])
            return make_result(tool, "add_vehicle applied.", action=action,
                               data={"args": args, **kwargs_pos, "session": session})

        elif action == "call":
            domain = params.get("domain")
            method = params.get("method")
            if not domain or not method:
                return make_error(tool, "Error: domain and method required for call",
                                  code=ErrorCode.INVALID_ARGUMENT, action=action)
            value = _traci_invoke(session, str(domain), str(method),
                                  list(params.get("args") or []))
            json_value, warnings = _json_safe(value)
            return make_result(
                tool, f"{domain}.{method} -> {value!r}", action=action,
                data={"domain": domain, "method": method, "value": json_value,
                      "session": session},
                warnings=warnings,
            )

    except (PermissionError, ValueError) as e:
        return make_error(tool, f"Error: {e}", code=ErrorCode.INVALID_ARGUMENT, action=action)
    except KeyError as e:
        return make_error(tool, f"Error: {e.args[0] if e.args else e}",
                          code=ErrorCode.SESSION_NOT_FOUND, action=action)
    except TimeoutError as e:
        return make_error(tool, f"Error: {e}", code=ErrorCode.TIMEOUT, action=action)
    except Exception as e:
        return make_error(
            tool, f"Error in control_simulation ({action}): {type(e).__name__}: {e}",
            code=ErrorCode.CONNECTION_ERROR, action=action,
        )

    return make_error(tool, f"Unknown action: {action}", code=ErrorCode.INVALID_ARGUMENT, action=action)

# --- 4. Query State ---


@server.tool(description=(
    "Query simulation state: vehicles, traffic lights, detectors, simulation counters. "
    "Requires an active TraCI connection. Without the `session` param the v0.1 global "
    "connection is queried; pass session=<label> for a named session." + _ENVELOPE_NOTE))
def query_simulation_state(target: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    """
    targets (all accept optional 'session'):
    - vehicle_list | vehicles: no params
    - vehicle_variable: params={'vehicle_id': str,
      'variable': 'speed'|'position'|'lane'|'acceleration'|'route'}
    - simulation: no params
    - traffic_lights: params={'tls_id'?: str} — all TLS ids, or one TLS's
      phase/program/state/next switch
    - detectors: params={'kind': 'induction'|'lanearea' (default induction),
      'detector_id'?: str} — detector ids or one detector's readings
    - call: params={'domain', 'method' (getter only), 'args'?} — any whitelisted
      TraCI getter
    """
    tool = "query_simulation_state"
    params = params or {}
    session = params.get("session")

    try:
        if target == "vehicle_list" or target == "vehicles":
            if session is not None:
                vehs = list(_traci_invoke(session, "vehicle", "getIDList", []))
            else:
                vehs = get_vehicles()
            return make_result(
                tool, f"Active vehicles: {vehs}", action=target,
                data={"vehicles": list(vehs), "count": len(vehs)},
            )

        elif target == "traffic_lights":
            tls_id = params.get("tls_id")
            if tls_id is None:
                ids = list(_traci_invoke(session, "trafficlight", "getIDList", []))
                return make_result(tool, f"Traffic lights: {ids}", action=target,
                                   data={"traffic_lights": ids, "count": len(ids)})
            detail = {
                "tls_id": tls_id,
                "phase": _traci_invoke(session, "trafficlight", "getPhase", [tls_id]),
                "program": _traci_invoke(session, "trafficlight", "getProgram", [tls_id]),
                "state": _traci_invoke(session, "trafficlight", "getRedYellowGreenState", [tls_id]),
                "phase_duration": _traci_invoke(session, "trafficlight", "getPhaseDuration", [tls_id]),
            }
            return make_result(tool, f"TLS {tls_id}: phase={detail['phase']} state={detail['state']}",
                               action=target, data=detail)

        elif target == "detectors":
            kind = str(params.get("kind", "induction"))
            domain = {"induction": "inductionloop", "lanearea": "lanearea"}.get(kind)
            if domain is None:
                return make_error(tool, f"Unknown detector kind: {kind} (use induction|lanearea)",
                                  code=ErrorCode.INVALID_ARGUMENT, action=target)
            det_id = params.get("detector_id")
            if det_id is None:
                ids = list(_traci_invoke(session, domain, "getIDList", []))
                return make_result(tool, f"{kind} detectors: {ids}", action=target,
                                   data={"detectors": ids, "count": len(ids), "kind": kind})
            readings: Dict[str, Any] = {
                "detector_id": det_id, "kind": kind,
                "vehicle_count": _traci_invoke(session, domain, "getLastStepVehicleNumber", [det_id]),
                "mean_speed": _traci_invoke(session, domain, "getLastStepMeanSpeed", [det_id]),
                "occupancy": _traci_invoke(session, domain, "getLastStepOccupancy", [det_id]),
            }
            if domain == "lanearea":
                readings["jam_length_m"] = _traci_invoke(session, domain, "getJamLengthMeters", [det_id])
            return make_result(tool, f"Detector {det_id}: {readings['vehicle_count']} veh",
                               action=target, data=readings)

        elif target == "call":
            domain = params.get("domain")
            method = params.get("method")
            if not domain or not method:
                return make_error(tool, "Error: domain and method required for call",
                                  code=ErrorCode.INVALID_ARGUMENT, action=target)
            if not str(method).startswith("get"):
                return make_error(
                    tool, f"Error: query target 'call' only allows getters, got {method!r} "
                          "(use control_simulation action='call' for setters)",
                    code=ErrorCode.INVALID_ARGUMENT, action=target)
            value = _traci_invoke(session, str(domain), str(method),
                                  list(params.get("args") or []))
            json_value, warnings = _json_safe(value)
            return make_result(tool, f"{domain}.{method} -> {value!r}", action=target,
                               data={"domain": domain, "method": method, "value": json_value},
                               warnings=warnings)

        elif target == "vehicle_variable":
            v_id = params.get("vehicle_id")
            var = params.get("variable")
            if not v_id or not var:
                return make_error(
                    tool, "Error: vehicle_id and variable required",
                    code=ErrorCode.INVALID_ARGUMENT, action=target,
                )

            session_getters = {
                "speed": ("getSpeed", [v_id]),
                "position": ("getPosition", [v_id]),
                "acceleration": ("getAcceleration", [v_id]),
                "lane": ("getLaneID", [v_id]),
                "route": ("getRoute", [v_id]),
            }
            legacy_getters = {
                "speed": get_vehicle_speed,
                "position": get_vehicle_position,
                "acceleration": get_vehicle_acceleration,
                "lane": get_vehicle_lane,
                "route": get_vehicle_route,
            }
            if var not in session_getters:
                return make_error(
                    tool, f"Unknown variable: {var}", code=ErrorCode.INVALID_ARGUMENT, action=target,
                )
            if session is not None:
                method, args = session_getters[var]
                value = _traci_invoke(session, "vehicle", method, args)
            else:
                value = legacy_getters[var](v_id)
            json_value, warnings = _json_safe(value)
            return make_result(
                tool, f"{var.capitalize()}: {value}", action=target,
                data={"vehicle_id": v_id, "variable": var, "value": json_value},
                warnings=warnings,
            )

        elif target == "simulation":
            if session is not None:
                info = {
                    "time": _traci_invoke(session, "simulation", "getTime", []),
                    "min_expected_number": _traci_invoke(session, "simulation", "getMinExpectedNumber", []),
                    "departed_number": _traci_invoke(session, "simulation", "getDepartedNumber", []),
                    "arrived_number": _traci_invoke(session, "simulation", "getArrivedNumber", []),
                    "colliding_vehicles_number": _traci_invoke(
                        session, "simulation", "getCollidingVehiclesNumber", []),
                    "loaded_number": _traci_invoke(session, "simulation", "getLoadedNumber", []),
                }
            else:
                info = get_simulation_info()
            return make_result(
                tool, f"Simulation Info: {info}", action=target,
                data={"simulation": info if isinstance(info, dict) else str(info)},
            )

    except PermissionError as e:
        return make_error(tool, f"Error: {e}", code=ErrorCode.INVALID_ARGUMENT, action=target)
    except KeyError as e:
        return make_error(tool, f"Error: {e.args[0] if e.args else e}",
                          code=ErrorCode.SESSION_NOT_FOUND, action=target)
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

    class _BadParam(Exception):
        pass

    def get_int_param(keys: List[str], default: int) -> int:
        raw = get_param(keys, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise _BadParam(f"Error: {keys[0]} must be an integer, got {raw!r}") from None

    try:
        if workflow_name in ("sim_gen_eval", "sim_gen_workflow", "sim_gen"):
            grid_number = get_int_param(["grid_number", "grid_size", "size"], 3)
            sim_seconds = get_int_param(["sim_seconds", "steps", "duration", "end_time"], 100)
            output_dir = get_param(["output_dir"], "output")

            text = sim_gen_workflow(output_dir, grid_number, sim_seconds)
            return legacy_result(
                tool, text, action=workflow_name,
                data={"workflow": "sim_gen_eval", "output_dir": output_dir,
                      "grid_number": grid_number, "sim_seconds": sim_seconds},
            )

        elif workflow_name in ("signal_opt", "signal_opt_workflow"):
            net_file = get_param(["net_file"], "")
            route_file = get_param(["route_file"], "")

            if not net_file or not route_file:
                return make_error(
                    tool, "Error: signal_opt requires net_file and route_file parameters.",
                    code=ErrorCode.INVALID_ARGUMENT, action=workflow_name,
                )

            sim_seconds = get_int_param(["sim_seconds", "steps", "duration"], 3600)
            use_coordinator = get_param(["use_coordinator"], False)
            output_dir = get_param(["output_dir"], "output")

            text = signal_opt_workflow(net_file, route_file, output_dir, sim_seconds, bool(use_coordinator))
            return legacy_result(
                tool, text, action=workflow_name,
                data={"workflow": "signal_opt", "output_dir": output_dir,
                      "net_file": net_file, "route_file": route_file,
                      "sim_seconds": sim_seconds, "use_coordinator": bool(use_coordinator)},
            )

        elif workflow_name == "rl_train":
            scenario_name = get_param(["scenario_name", "scenario"], "")
            episodes = get_int_param(["episodes", "num_episodes"], 5)
            steps = get_int_param(["steps", "steps_per_episode"], 1000)
            output_dir = get_param(["output_dir"], "output")

            text = rl_train_workflow(scenario_name, output_dir, episodes, steps)
            return legacy_result(
                tool, text, action=workflow_name,
                data={"workflow": "rl_train", "scenario_name": scenario_name,
                      "episodes": episodes, "steps": steps, "output_dir": output_dir},
            )

    except _BadParam as bad:
        return make_error(tool, str(bad), code=ErrorCode.INVALID_ARGUMENT, action=workflow_name)
    except TimeoutError as exc:
        return make_error(tool, f"Error: workflow timed out: {exc}", code=ErrorCode.TIMEOUT, action=workflow_name)
    except Exception as exc:
        # Workflow internals mostly return error strings, but filesystem and
        # subprocess surprises can still raise — keep the envelope promise.
        return make_error(
            tool, f"Error: workflow {workflow_name} raised {type(exc).__name__}: {exc}",
            code=ErrorCode.EXECUTION_FAILED, action=workflow_name,
        )

    return make_error(
        tool, f"Unknown workflow: {workflow_name}. Available: sim_gen_eval, signal_opt, rl_train",
        code=ErrorCode.INVALID_ARGUMENT, action=workflow_name,
    )

# --- 7. RL Task Management ---


@server.tool(description=(
    "Manage RL tasks: v0.1 scenario listing/custom QL training plus v0.2 preflight, "
    "job-based training, run listing and status/stop actions." + _ENVELOPE_NOTE))
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

    def _int_param(name: str, default: int) -> int:
        raw = params.get(name, default)
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer, got {raw!r}") from exc

    def _resolve_files() -> tuple[Optional[str], Optional[str], Optional[Envelope]]:
        scenario_name = params.get("scenario") or params.get("scenario_name")
        net_file = params.get("net_file")
        route_file = params.get("route_file")
        if scenario_name:
            net_file, route_file, err = find_sumo_rl_scenario_files(str(scenario_name))
            if err:
                return None, None, make_error(tool, err, code=ErrorCode.FILE_NOT_FOUND, action=action)
        if not net_file or not route_file:
            return None, None, _invalid(
                "Error: RL task requires either scenario/scenario_name or net_file + route_file"
            )
        return str(net_file), str(route_file), None

    def _training_module(algorithm: str) -> Optional[str]:
        backend = training_backend(algorithm)
        if backend == "ql":
            return "sumo_mcp.rl.train_entry"
        if backend == "sb3":
            return "sumo_mcp.rl.sb3_entry"
        return None

    if action == "list_scenarios":
        scenarios = list_rl_scenarios()
        return legacy_result(
            tool, str(scenarios), action=action,
            data={"scenarios": scenarios},
        )

    elif action == "list_algorithms":
        algorithms = list_rl_algorithms_v2()
        available = [a["name"] for a in algorithms if a["available"]]
        return make_result(
            tool, f"{len(algorithms)} algorithm(s), available: {available}",
            action=action, data={"algorithms": algorithms, "available": available},
        )

    elif action == "validate_env":
        try:
            net_file, route_file, error = _resolve_files()
            if error:
                return error
            delta_time = _int_param("delta_time", 5)
            yellow_time = _int_param("yellow_time", 2)
        except ValueError as exc:
            return _invalid(f"Error: {exc}")
        algorithm = str(params.get("algorithm", "ql")).lower()
        report = validate_rl_environment(
            net_file=str(net_file),
            route_file=str(route_file),
            algorithm=algorithm,
            delta_time=delta_time,
            yellow_time=yellow_time,
        )
        if not report["ok"]:
            failed = report["failed_checks"]
            code = failed[0].get("code", ErrorCode.VALIDATION_FAILED) if failed else ErrorCode.VALIDATION_FAILED
            return make_error(tool, report["summary"], code=code, action=action, data=report)
        return make_result(tool, report["summary"], action=action, data=report)

    elif action == "train":
        try:
            net_file, route_file, error = _resolve_files()
            if error:
                return error
            algorithm = str(params.get("algorithm", "ql")).lower()
            episodes = _int_param("episodes", 1)
            steps_key = "steps_per_episode" if "steps_per_episode" in params else "steps"
            steps_per_episode = _int_param(steps_key, 1000)
            delta_time = _int_param("delta_time", 5)
            yellow_time = _int_param("yellow_time", 2)
        except ValueError as exc:
            return _invalid(f"Error: {exc}")
        if episodes <= 0 or steps_per_episode <= 0:
            return _invalid("Error: episodes and steps_per_episode must be > 0")

        preflight = validate_rl_environment(
            net_file=str(net_file), route_file=str(route_file), algorithm=algorithm,
            delta_time=delta_time, yellow_time=yellow_time,
        )
        if not preflight["ok"]:
            failed = preflight["failed_checks"]
            code = failed[0].get("code", ErrorCode.VALIDATION_FAILED) if failed else ErrorCode.VALIDATION_FAILED
            return make_error(tool, preflight["summary"], code=code, action=action, data=preflight)
        module = _training_module(algorithm)
        if module is None:
            return make_error(tool, f"Error: unsupported RL algorithm {algorithm!r}",
                              code=ErrorCode.INVALID_ARGUMENT, action=action)

        out_dir = str(params.get("out_dir") or params.get("output_dir") or "rl_runs")
        config = {
            "net_file": str(net_file),
            "route_file": str(route_file),
            "algorithm": algorithm,
            "episodes": episodes,
            "steps_per_episode": steps_per_episode,
            "reward_type": str(params.get("reward_type", "diff-waiting-time")),
            "delta_time": delta_time,
            "yellow_time": yellow_time,
            "seed": params.get("seed"),
            "scenario": params.get("scenario") or params.get("scenario_name"),
            "total_timesteps": params.get("total_timesteps"),
            "policy": str(params.get("policy", "MlpPolicy")),
        }
        manifest = create_run(out_dir, config)
        run_dir = str(manifest["run_dir"])
        command = [sys.executable, "-m", module, run_dir]
        expected_outputs = [
            {"path": str(Path(run_dir) / "metrics.csv"), "role": "rl_metrics"},
            {"path": str(Path(run_dir) / "manifest.json"), "role": "rl_run_manifest"},
            {"path": str(Path(run_dir) / "config.json"), "role": "rl_run_config"},
        ]
        if training_backend(algorithm) == "sb3":
            expected_outputs.append({"path": str(Path(run_dir) / "checkpoints" / f"{algorithm}_model.zip"),
                                     "role": "rl_model"})
        info = job_manager.start_process_job(
            command,
            label=f"rl-train-{algorithm}",
            request={"kind": "rl_train", "run_dir": run_dir, **config},
            timeout_s=float(params.get("timeout_s", params.get("timeout", 3600))),
            expected_outputs=expected_outputs,
        )
        update_run(run_dir, {"status": "queued", "job_id": info["job_id"]})
        return make_result(
            tool, f"Started RL training job {info['job_id']} ({algorithm}).",
            action=action, data={"run": load_run(run_dir), "job": info, "preflight": preflight},
            artifacts=[
                artifact(str(Path(run_dir) / "config.json"), "rl_run_config"),
                artifact(str(Path(run_dir) / "manifest.json"), "rl_run_manifest"),
            ],
            job_id=info["job_id"],
        )

    elif action == "resume":
        run_dir_raw = params.get("run_dir")
        if not run_dir_raw:
            return _invalid("Error: run_dir required for resume")
        run_dir = str(run_dir_raw)
        try:
            config = load_config(run_dir)
            extra_episodes = _int_param("episodes", int(config.get("episodes", 1)))
        except (OSError, ValueError, KeyError) as exc:
            return make_error(tool, f"Error: cannot resume run: {exc}",
                              code=ErrorCode.INVALID_ARGUMENT, action=action)
        config["episodes"] = extra_episodes
        config["resume_checkpoint"] = latest_checkpoint(run_dir)
        update_config(run_dir, config)
        update_run(run_dir, {"status": "queued"})
        algorithm = str(config.get("algorithm", "ql")).lower()
        module = _training_module(algorithm)
        if module is None:
            return make_error(tool, f"Error: unsupported RL algorithm {algorithm!r}",
                              code=ErrorCode.INVALID_ARGUMENT, action=action)
        command = [sys.executable, "-m", module, str(Path(run_dir).resolve())]
        info = job_manager.start_process_job(
            command, label=f"rl-resume-{config.get('algorithm', 'ql')}",
            request={"kind": "rl_resume", "run_dir": run_dir, **config},
            timeout_s=float(params.get("timeout_s", params.get("timeout", 3600))),
        )
        update_run(run_dir, {"job_id": info["job_id"]})
        return make_result(tool, f"Started RL resume job {info['job_id']}.", action=action,
                           data={"run": load_run(run_dir), "job": info}, job_id=info["job_id"])

    elif action == "evaluate":
        run_dir_raw = params.get("run_dir")
        if not run_dir_raw:
            return _invalid("Error: run_dir required for evaluate")
        run_dir_eval = str(run_dir_raw)
        try:
            episodes = _int_param("episodes", 1)
        except ValueError as exc:
            return _invalid(f"Error: {exc}")
        checkpoint_raw = params.get("checkpoint")
        result = evaluate_run(
            run_dir_eval,
            episodes=episodes,
            checkpoint=str(checkpoint_raw) if checkpoint_raw else None,
        )
        if not result["ok"]:
            raw_error_eval = result.get("error")
            if isinstance(raw_error_eval, dict):
                error_message_eval = str(raw_error_eval.get("message", "Evaluation failed."))
                error_code_eval = raw_error_eval.get("code", ErrorCode.EXECUTION_FAILED)
            else:
                error_message_eval = "Evaluation failed."
                error_code_eval = ErrorCode.EXECUTION_FAILED
            return make_error(
                tool,
                error_message_eval,
                code=error_code_eval,
                action=action,
            )
        return make_result(
            tool, result["summary"], action=action, metrics=result["metrics"],
            artifacts=[artifact(result["artifact"], "rl_evaluation")],
            data={"run_dir": run_dir_eval, "evaluation_file": result["artifact"]},
        )

    elif action == "compare":
        run_dir_raw = params.get("run_dir")
        if not run_dir_raw:
            return _invalid("Error: run_dir required for compare")
        run_dir_compare = str(run_dir_raw)
        try:
            episodes = _int_param("episodes", 1)
        except ValueError as exc:
            return _invalid(f"Error: {exc}")
        result = compare_run(run_dir_compare, episodes=episodes)
        if not result["ok"]:
            raw_error_compare = result.get("error")
            if isinstance(raw_error_compare, dict):
                error_message_compare = str(raw_error_compare.get("message", "Comparison failed."))
                error_code_compare = raw_error_compare.get("code", ErrorCode.EXECUTION_FAILED)
            else:
                error_message_compare = "Comparison failed."
                error_code_compare = ErrorCode.EXECUTION_FAILED
            return make_error(
                tool,
                error_message_compare,
                code=error_code_compare,
                action=action,
            )
        return make_result(
            tool, result["summary"], action=action, metrics=result["metrics"],
            artifacts=[artifact(result["artifact"], "rl_comparison")],
            data={"run_dir": run_dir_compare, "comparison_file": result["artifact"]},
        )

    elif action == "status":
        run_dir_raw = params.get("run_dir")
        job_id = params.get("job_id")
        data: Dict[str, Any] = {}
        if run_dir_raw:
            run_dir = str(run_dir_raw)
            try:
                data["run"] = load_run(run_dir)
            except OSError as exc:
                return make_error(tool, f"Error: run_dir not readable: {exc}",
                                  code=ErrorCode.FILE_NOT_FOUND, action=action)
        if job_id:
            status = job_manager.get_status(str(job_id))
            if status is None:
                return make_error(tool, f"Error: no job with id {job_id!r}",
                                  code=ErrorCode.JOB_NOT_FOUND, action=action)
            data["job"] = status
        if not data:
            return _invalid("Error: status requires run_dir or job_id")
        summary = "RL status: " + ", ".join(f"{k}={v.get('status')}" for k, v in data.items())
        return make_result(tool, summary, action=action, data=data, job_id=str(job_id) if job_id else None)

    elif action == "stop":
        job_id = params.get("job_id")
        if not job_id:
            return _invalid("Error: job_id required for stop")
        cancelled = job_manager.cancel(str(job_id))
        if cancelled is None:
            return make_error(tool, f"Error: no job with id {job_id!r}",
                              code=ErrorCode.JOB_NOT_FOUND, action=action)
        return make_result(tool, f"RL job {job_id}: {cancelled['status']}", action=action,
                           data={"job": cancelled}, job_id=str(job_id))

    elif action == "list_runs":
        out_dir = str(params.get("out_dir") or params.get("output_dir") or "rl_runs")
        runs = list_runs(out_dir)
        return make_result(tool, f"{len(runs)} RL run(s) under {out_dir}.", action=action,
                           data={"out_dir": out_dir, "runs": runs})

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
        if algorithm != "ql":
            return make_error(
                tool,
                f"Error: train_custom only supports algorithm='ql' for v0.1 compatibility, got {algorithm!r}. "
                "Use action='train' after installing the stage-5 RL subsystem for SB3/PettingZoo algorithms.",
                code=ErrorCode.INVALID_ARGUMENT,
                action=action,
            )

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


# --- v0.2: SUMO CLI catalog & pass-through ---


@server.tool(description=(
    "Browse the whitelist of runnable SUMO commands: 14 core binaries plus ~600 tool "
    "scripts (tier 1 = curated with descriptions, tier 3 = auto-discovered). Pass "
    "name=<command> to get its --help text. Filter with kind ('binary'|'tool'), tier, "
    "or a search string. Use this before run_sumo_binary / run_sumo_tool."
    + _ENVELOPE_NOTE))
def list_sumo_commands(
    name: Optional[str] = None,
    kind: Optional[str] = None,
    tier: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 100,
) -> Envelope:
    tool = "list_sumo_commands"
    try:
        if name is not None:
            described = describe_command(name)
            if "error" in described and "help_text" not in described:
                return make_error(tool, described["error"],
                                  code=ErrorCode.INVALID_ARGUMENT, action="describe")
            return make_result(tool, f"Description of {name}", action="describe", data=described)

        commands = list_commands(kind=kind, tier=tier, search=search)
        total = len(commands)
        shown = commands[: max(1, limit)]
        summary = f"{total} command(s) matched" + (f", showing first {len(shown)}" if total > len(shown) else "")
        return make_result(
            tool, summary, action="list",
            data={"total": total, "shown": len(shown), "commands": shown},
        )
    except Exception as e:
        return make_error(tool, f"Error listing commands: {type(e).__name__}: {e}",
                          code=ErrorCode.EXECUTION_FAILED)


def _run_cli_tool(tool: str, kind: str, name: str, args: Optional[List[str]],
                  cwd: Optional[str], timeout_s: Optional[float],
                  expected_outputs: Optional[List[Dict[str, str]]],
                  background: bool) -> Envelope:
    safe_args = [str(a) for a in (args or [])]
    if background:
        info = job_manager.start_cli_job(kind, name, safe_args, cwd=cwd, timeout_s=timeout_s,
                                         expected_outputs=expected_outputs, label=name)
        return make_result(
            tool, f"Started background job {info['job_id']} for {name}. "
                  "Poll it with manage_sumo_jobs(action='status').",
            action=name, data=info, job_id=info["job_id"],
        )

    result = run_cli(kind, name, safe_args, cwd=cwd, timeout_s=timeout_s,
                     expected_outputs=expected_outputs)
    if result["ok"]:
        summary = f"{name} completed in {result['duration_s']}s."
    else:
        summary = result["error"]["message"]
    return make_result(
        tool, summary, ok=result["ok"], action=name,
        data={"returncode": result["returncode"], "duration_s": result["duration_s"]},
        artifacts=result["artifacts"], command=result["command"],
        stdout_tail=result["stdout_tail"], stderr_tail=result["stderr_tail"],
        error=result["error"],
    )


@server.tool(description=(
    "Run one of the 14 core SUMO binaries (sumo, netconvert, netgenerate, duarouter, "
    "od2trips, ...) with raw CLI arguments (argv list, no shell). Whitelisted names only "
    "— browse them with list_sumo_commands. Set background=true for long runs and poll "
    "manage_sumo_jobs. Declare expected_outputs=[{path,role}] for precise artifact "
    "tracking." + _ENVELOPE_NOTE))
def run_sumo_binary(
    name: str,
    args: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    timeout_s: Optional[float] = None,
    expected_outputs: Optional[List[Dict[str, str]]] = None,
    background: bool = False,
) -> Envelope:
    return _run_cli_tool("run_sumo_binary", "binary", name, args, cwd, timeout_s,
                         expected_outputs, background)


@server.tool(description=(
    "Run any whitelisted SUMO tool script from $SUMO_HOME/tools (randomTrips.py, "
    "routeSampler.py, assign/duaIterate.py, xml/xml2csv.py, ...) with raw CLI arguments "
    "(argv list, no shell). Browse available scripts with list_sumo_commands; get their "
    "options with list_sumo_commands(name=...). Set background=true for long runs."
    + _ENVELOPE_NOTE))
def run_sumo_tool(
    name: str,
    args: Optional[List[str]] = None,
    cwd: Optional[str] = None,
    timeout_s: Optional[float] = None,
    expected_outputs: Optional[List[Dict[str, str]]] = None,
    background: bool = False,
) -> Envelope:
    return _run_cli_tool("run_sumo_tool", "tool", name, args, cwd, timeout_s,
                         expected_outputs, background)


@server.tool(description=(
    "Analyze a SUMO output file (summary, tripinfo, fcd, queue, emission — auto-detected, "
    "gzip supported) with streaming XML parsing; returns structured metrics without "
    "loading huge files into context. For quick pandas stats on FCD, run_analysis also "
    "still works." + _ENVELOPE_NOTE))
def analyze_sumo_output(
    file_path: str,
    kind: Optional[str] = None,
    max_elements: int = 500_000,
) -> Envelope:
    tool = "analyze_sumo_output"
    result = analyze_output(file_path, kind=kind, max_elements=max_elements)
    if not result["ok"]:
        return make_error(tool, result["error"]["message"],
                          code=result["error"]["code"], action=result.get("kind") or "auto")
    counts = ", ".join(f"{k}={v}" for k, v in result.get("counts", {}).items())
    summary = f"Analyzed {result['kind']} output ({counts})."
    if result.get("truncated"):
        summary += " [truncated at max_elements]"
    return make_result(
        tool, summary, action=result["kind"],
        data={k: v for k, v in result.items() if k not in ("ok",)},
        metrics=result.get("metrics"),
    )


@server.tool(description=(
    "Manage background jobs started by run_sumo_binary / run_sumo_tool / RL training. "
    "actions: status {job_id} | result {job_id} | logs {job_id, tail_lines?} | "
    "cancel {job_id} | list. Job manifests persist on disk, so jobs from previous "
    "server runs remain visible." + _ENVELOPE_NOTE))
def manage_sumo_jobs(action: str, params: Optional[Dict[str, Any]] = None) -> Envelope:
    tool = "manage_sumo_jobs"
    params = params or {}
    job_id = params.get("job_id")

    def _need_job_id() -> Optional[Envelope]:
        if not job_id:
            return make_error(tool, f"Error: job_id required for {action}",
                              code=ErrorCode.INVALID_ARGUMENT, action=action)
        return None

    def _not_found() -> Envelope:
        return make_error(tool, f"Error: no job with id {job_id!r}",
                          code=ErrorCode.JOB_NOT_FOUND, action=action,
                          remediation="Use manage_sumo_jobs(action='list') to see known jobs.")

    try:
        if action == "list":
            jobs = job_manager.list_jobs()
            return make_result(tool, f"{len(jobs)} job(s) known.", action=action,
                               data={"jobs": jobs})

        elif action == "status":
            missing = _need_job_id()
            if missing:
                return missing
            status = job_manager.get_status(str(job_id))
            if status is None:
                return _not_found()
            return make_result(tool, f"Job {job_id}: {status['status']}", action=action,
                               data=status, job_id=str(job_id))

        elif action == "result":
            missing = _need_job_id()
            if missing:
                return missing
            result = job_manager.get_result(str(job_id))
            if result is None:
                return _not_found()
            still_running = result.get("status") in ("pending", "running")
            summary = (f"Job {job_id} still {result.get('status')}." if still_running
                       else f"Job {job_id} finished.")
            return make_result(tool, summary, action=action, data=result, job_id=str(job_id))

        elif action == "logs":
            missing = _need_job_id()
            if missing:
                return missing
            logs = job_manager.get_logs(str(job_id), tail_lines=int(params.get("tail_lines", 100)))
            if logs is None:
                return _not_found()
            return make_result(tool, f"Logs for job {job_id}.", action=action, data=logs,
                               job_id=str(job_id))

        elif action == "cancel":
            missing = _need_job_id()
            if missing:
                return missing
            cancelled = job_manager.cancel(str(job_id))
            if cancelled is None:
                return _not_found()
            return make_result(tool, f"Job {job_id}: {cancelled['status']}", action=action,
                               data=cancelled, job_id=str(job_id))

    except Exception as e:
        return make_error(tool, f"Error in manage_sumo_jobs ({action}): {type(e).__name__}: {e}",
                          code=ErrorCode.EXECUTION_FAILED, action=action)

    return make_error(tool, f"Unknown action: {action}. Available: status, result, logs, cancel, list",
                      code=ErrorCode.INVALID_ARGUMENT, action=action)


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
