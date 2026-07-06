"""MCP resources and prompt content for SUMO-MCP v0.2."""
from __future__ import annotations

import json
from importlib import resources
from typing import Any, Dict, List

from sumo_mcp.catalog import list_commands
from sumo_mcp.jobs import job_manager
from sumo_mcp.models import ErrorCode
from sumo_mcp.rl.algorithms import list_algorithms
from sumo_mcp.utils.sumo import find_sumo_binary, find_sumo_home, find_sumo_tools_dir

PUBLIC_TOOLS = (
    "manage_network",
    "convert_ezdesignx_network",
    "manage_demand",
    "control_simulation",
    "query_simulation_state",
    "optimize_traffic_signals",
    "run_workflow",
    "manage_rl_task",
    "get_sumo_info",
    "run_simple_simulation",
    "run_analysis",
    "list_sumo_commands",
    "run_sumo_binary",
    "run_sumo_tool",
    "analyze_sumo_output",
    "manage_sumo_jobs",
)


def _json(payload: Dict[str, Any] | List[Dict[str, Any]]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def read_static_resource(name: str) -> str:
    return (
        resources.files("sumo_mcp.resources.content")
        .joinpath(name)
        .read_text(encoding="utf-8")
    )


def diagnostics_resource() -> str:
    commands = list_commands()
    available = [c for c in commands if c.get("available")]
    tier1 = [c for c in commands if c.get("tier") == 1]
    payload = {
        "ok": True,
        "sumo_home": find_sumo_home(),
        "sumo_tools_dir": find_sumo_tools_dir(),
        "binaries": {
            name: find_sumo_binary(name)
            for name in ("sumo", "sumo-gui", "netconvert", "netgenerate", "duarouter", "od2trips")
        },
        "catalog": {
            "total": len(commands),
            "available": len(available),
            "tier1_total": len(tier1),
            "tier1_available": len([c for c in tier1 if c.get("available")]),
        },
        "rl_algorithms": list_algorithms(),
    }
    return _json(payload)


def tool_catalog_resource() -> str:
    rows = [
        ("manage_network", "Generate/convert/download networks; includes ezdesignX conversion action."),
        ("convert_ezdesignx_network", "Dedicated ezdesignX v1 JSON/JSONC to SUMO converter."),
        ("manage_demand", "Generate random demand, convert OD, and compute routes."),
        ("control_simulation", "Connect, step, and disconnect an online TraCI simulation."),
        ("query_simulation_state", "Read vehicles and simulation state from online sessions."),
        ("optimize_traffic_signals", "Run Webster cycle adaptation and green-wave coordination tools."),
        ("run_workflow", "Run compact end-to-end workflows: sim generation, signal optimization, RL train."),
        ("manage_rl_task", "RL preflight, train/resume jobs, status, evaluate, compare, list runs."),
        ("get_sumo_info", "Return installed SUMO diagnostics and path information."),
        ("run_simple_simulation", "Run a simple SUMO simulation from net/route files."),
        ("run_analysis", "Legacy FCD CSV analysis helper."),
        ("list_sumo_commands", "Inspect curated/discovered SUMO binary/tool catalog."),
        ("run_sumo_binary", "Run whitelisted SUMO binaries with argv-list safety."),
        ("run_sumo_tool", "Run whitelisted SUMO tools scripts with argv-list safety."),
        ("analyze_sumo_output", "Stream-parse SUMO outputs: summary, tripinfo, FCD, queue, emission."),
        ("manage_sumo_jobs", "Inspect/cancel/list long-running background jobs."),
    ]
    lines = [
        "# SUMO-MCP Tool Catalog",
        "",
        "Use these 16 tools; add capability through actions/resources, not new tools.",
        "",
    ]
    lines.extend(f"- `{name}`: {desc}" for name, desc in rows)
    return "\n".join(lines) + "\n"


def commands_resource() -> str:
    compact = [
        {
            "name": c["name"],
            "kind": c["kind"],
            "tier": c["tier"],
            "category": c["category"],
            "available": c["available"],
            "description": c["description"],
        }
        for c in list_commands(tier=1)
    ]
    return _json(compact)


def job_resource(job_id: str) -> str:
    status = job_manager.get_status(job_id)
    if status is None:
        return _json({
            "ok": False,
            "error": {"code": ErrorCode.JOB_NOT_FOUND, "message": f"No job with id {job_id!r}"},
        })
    result = job_manager.get_result(job_id)
    logs = job_manager.get_logs(job_id, tail_lines=40)
    return _json({"ok": True, "job_id": job_id, "status": status, "result": result, "logs": logs})
