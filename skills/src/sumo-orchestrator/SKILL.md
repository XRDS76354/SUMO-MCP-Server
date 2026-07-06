---
name: sumo-orchestrator
description: Decide which SUMO-MCP v0.2 tools, resources, and specialized skills to use for a SUMO task.
---

# SUMO Orchestrator

## Use When
- A user asks for a traffic simulation workflow and the right tool sequence is unclear.
- A task spans network, demand, routing, simulation, analysis, signal control, or RL.

## First Checks
- Read `sumo://tool-catalog` for the fixed tool surface.
- Read `sumo://guide/tool-selection` for routing decisions.
- Use `sumo://diagnostics` when installation or dependency state matters.

## Tool Routing
- Network build/import: `manage_network`, then `run_sumo_binary` only for native options not covered by actions.
- Demand and routing: `manage_demand`; use `run_sumo_tool` or `run_sumo_binary` for advanced SUMO CLI paths.
- Online control: `control_simulation` and `query_simulation_state`.
- Signal optimization: `run_workflow` with `signal_opt`, or `optimize_traffic_signals` for raw additional files.
- RL: `manage_rl_task` with `validate_env` before `train`.
- Long-running background work: poll or cancel with `manage_sumo_jobs`.

## Guardrails
- Do not invent tool names beyond the 16-tool v0.2 surface.
- Use argv lists for CLI wrappers; never shell strings.
- Preserve generated artifacts and report paths.
