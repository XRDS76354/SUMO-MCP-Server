# SUMO-MCP Tool Selection

Use `manage_network` for common network generation, OSM conversion, and
ezdesignX conversion. Use `run_sumo_binary` only when the agent needs a native
SUMO binary option not exposed by the high-level action.

Use `manage_demand` for random trips, OD conversion, and route computation.
Use `run_sumo_tool` for advanced SUMO tools scripts such as calibration,
detector processing, route slicing, GTFS import, and plotting.

Use `control_simulation` plus `query_simulation_state` when an agent needs
online closed-loop TraCI interaction. Use `run_simple_simulation` or
`run_sumo_binary` with `sumo` for offline batch simulation.

Use `optimize_traffic_signals` for Webster cycle adaptation and green-wave
coordination. Use `run_workflow` with `signal_opt` when the user asks for a
baseline-vs-optimized comparison.

Use `analyze_sumo_output` for large SUMO XML outputs. Keep `run_analysis` for
legacy FCD CSV summaries.

Use `manage_rl_task` for RL preflight, train/resume, status, evaluate, compare,
and listing runs. Always call `validate_env` before training custom files.

Use `manage_sumo_jobs` whenever a previous tool call returned `job_id`.
