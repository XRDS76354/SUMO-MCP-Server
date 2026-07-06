# SUMO-MCP Workflow Recipes

## From Scratch

1. `manage_network(action="generate")` to create a grid/spider network.
2. `manage_demand(action="generate_random")` to create trips.
3. `manage_demand(action="compute_routes")` to create routes.
4. `run_simple_simulation` or `run_sumo_binary(name="sumo")` to simulate.
5. `analyze_sumo_output` on summary/tripinfo/FCD outputs.

## OSM Area Import

1. `manage_network(action="download_osm")` for a bbox.
2. `manage_network(action="convert")` or `run_sumo_tool(name="osmBuild.py")`.
3. `manage_demand` or `run_sumo_tool(name="randomTrips.py")`.
4. `run_sumo_binary(name="duarouter")` and `run_sumo_binary(name="sumo")`.

## Signal Optimization

1. Prepare net and routes.
2. Run `run_workflow(workflow_name="signal_opt")` for baseline, optimized run,
   and comparison.
3. Use `optimize_traffic_signals` directly only when the user wants the raw TLS
   additional file.

## RL Train Evaluate Iterate

1. `manage_rl_task(action="list_algorithms")`.
2. `manage_rl_task(action="validate_env")`.
3. `manage_rl_task(action="train")`, then poll `manage_rl_task(action="status")`.
4. `manage_rl_task(action="evaluate")`.
5. `manage_rl_task(action="compare")`.
6. `manage_rl_task(action="resume")` if more training is needed.
