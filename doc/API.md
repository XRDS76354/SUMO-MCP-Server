# SUMO-MCP v0.2 API Reference

[中文文档](API_CN.md)

This document describes the public FastMCP contract exposed by
`src/sumo_mcp/server.py`. The v0.2 tool surface is intentionally fixed at 16
tools: v0.1 tool names remain available, and v0.2 capabilities are added through
actions, resources, prompts, and structured return data.

## Return Envelope

All tools return a JSON-compatible envelope:

```json
{
  "ok": true,
  "tool": "manage_network",
  "action": "generate",
  "summary": "Human readable result",
  "data": {},
  "artifacts": [{"path": "/abs/file", "role": "network", "exists": true, "size_bytes": 123}],
  "metrics": {},
  "command": ["sumo", "-c", "scenario.sumocfg"],
  "stdout_tail": "",
  "stderr_tail": "",
  "warnings": [],
  "error": {"code": "INVALID_ARGUMENT", "message": "details", "remediation": "fix"},
  "job_id": "abc123"
}
```

Only `ok`, `tool`, and `summary` are always present. v0.1 string summaries are
preserved in `summary`.

Stable error codes include `SUMO_NOT_FOUND`, `DEPENDENCY_MISSING`,
`INVALID_ARGUMENT`, `FILE_NOT_FOUND`, `EXECUTION_FAILED`, `TIMEOUT`,
`CONNECTION_ERROR`, `SESSION_NOT_FOUND`, `JOB_NOT_FOUND`, `GUI_BLOCKED`,
`VALIDATION_FAILED`, and `NETWORK_ERROR`.

## General Conventions

- Paths may be relative, but absolute paths are recommended for chained agent workflows.
- `params.options` and CLI `args` are `list[str]` argv tokens, never shell strings.
- Long operations should use background jobs when available and then poll `manage_sumo_jobs`.
- SUMO tools scripts require `<SUMO_HOME>/tools`; set `SUMO_HOME` for deterministic behavior.

## Tools

### `manage_network(action, output_file, params?)`

Network generation, OSM download/conversion, and ezdesignX conversion.

Actions:

- `generate`: `params.grid`, `params.grid_number`, `params.spider`, plus native flags in `params.options`.
- `download_osm`: `output_file` is output directory; `params.bbox`, `params.prefix`.
- `convert` / `convert_osm`: `params.osm_file`.
- `convert_ezdesignx`: `output_file` is output directory; `params.input_json`, `params.validation`.

### `convert_ezdesignx_network(input_json, output_dir, validation?, netconvert_bin?, sumo_bin?, sumo_gui_bin?)`

Dedicated ezdesignX v1 JSON/JSONC to SUMO artifacts converter. Preserves the
v0.1 dedicated tool while sharing the same converter as `manage_network`.

### `manage_demand(action, net_file, output_file, params?)`

Demand and route preparation.

Actions:

- `generate_random` / `random_trips`: calls `randomTrips.py`; supports `end_time`, `period`, and `options`.
- `convert_od` / `od_matrix`: calls `od2trips`; requires `params.od_file`.
- `compute_routes` / `routing`: calls `duarouter`; requires `params.route_files`.

### `control_simulation(action, params?)`

Online TraCI lifecycle.

Actions:

- `connect`: `params.config_file`, `params.gui`, `params.port`, `params.host`, optional `params.session`.
- `step`: `params.step`, optional `params.session`.
- `disconnect`: optional `params.session`.

### `query_simulation_state(target, params?)`

Online state queries.

Targets:

- `vehicle_list` / `vehicles`.
- `vehicle_variable`: `params.vehicle_id`, `params.variable` (`speed`, `position`, `acceleration`, `lane`, `route`).
- `simulation`: global time and vehicle counts.

When `params.session` is provided, the named online session is used; otherwise
the legacy global connection is used.

### `optimize_traffic_signals(method, net_file, route_file, output_file, params?)`

Traffic signal optimization.

Methods:

- `cycle_adaptation` / `Websters`: Webster-style green splits via `tlsCycleAdaptation.py`.
- `coordination`: green-wave offsets via `tlsCoordinator.py`.

Outputs are SUMO additional files and must be mounted as `<additional-files>`.

### `run_workflow(workflow_name, params)`

Compact end-to-end workflows.

Workflows:

- `sim_gen_eval`: generate network, demand, routes, simulation, and analysis.
- `signal_opt`: baseline run, signal optimization, optimized run, comparison.
- `rl_train`: legacy built-in SUMO-RL workflow.

### `manage_rl_task(action, params?)`

RL experiment lifecycle. See [RL guide](RL.md).

Actions:

- `list_scenarios`
- `list_algorithms`
- `validate_env`
- `train`
- `resume`
- `status`
- `stop`
- `evaluate`
- `compare`
- `list_runs`
- `train_custom` (v0.1-compatible synchronous Q-learning)

Supported algorithms: `ql`, `pettingzoo-independent-ql`, `dqn`, `ppo`, `a2c`.
SB3 algorithms require `sumo-mcp[rl]` and are single-TLS in v0.2.

### `get_sumo_info()`

SUMO diagnostics: versions, binaries, tools directory, and environment state.

### `run_simple_simulation(config_file, output_dir?)`

Run a config-based SUMO simulation with the legacy simple wrapper.

### `run_analysis(fcd_file)`

Legacy FCD CSV analysis helper.

### `list_sumo_commands(kind?, tier?, search?, include_unavailable?)`

Inspect the curated/runtime SUMO command catalog. `kind` is `binary` or `tool`.
Tier 1 is curated; tier 3 is dynamically discovered under `$SUMO_HOME/tools`.

### `run_sumo_binary(name, args?, cwd?, timeout_s?, expected_outputs?, background?)`

Run a whitelisted SUMO binary such as `sumo`, `netconvert`, `netgenerate`,
`duarouter`, or `od2trips`. Arguments are argv tokens.

### `run_sumo_tool(name, args?, cwd?, timeout_s?, expected_outputs?, background?)`

Run a whitelisted SUMO Python tool script such as `randomTrips.py`,
`osmBuild.py`, `tlsCycleAdaptation.py`, or `xml/xml2csv.py`.

### `analyze_sumo_output(file_path, kind?, max_elements?)`

Streaming XML analysis for summary, tripinfo, FCD, queue, emission, and related
SUMO outputs. Supports gzip and truncation via `max_elements`.

### `manage_sumo_jobs(action, params?)`

Persistent background job management.

Actions:

- `list`
- `status`: requires `params.job_id`
- `result`: requires `params.job_id`
- `logs`: requires `params.job_id`, optional `tail_lines`
- `cancel`: requires `params.job_id`

## MCP Resources

- `sumo://diagnostics`
- `sumo://tool-catalog`
- `sumo://commands`
- `sumo://guide/tool-selection`
- `sumo://guide/workflows`
- `sumo://guide/rl-training`
- `sumo://guide/troubleshooting`
- `sumo://jobs/{job_id}`

## MCP Prompts

- `build-simulation-from-scratch`
- `import-osm-area`
- `optimize-signals`
- `rl-train-and-evaluate`
- `analyze-simulation-outputs`
