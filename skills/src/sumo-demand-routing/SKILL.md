---
name: sumo-demand-routing
description: Generate trips, convert OD matrices, and compute routes with SUMO-MCP v0.2.
---

# SUMO Demand Routing

## Use When
- The user needs trips, flows, OD conversion, route computation, or route validation.

## Preferred Tools
- `manage_demand(action="generate_random")` for quick trips.
- `manage_demand(action="convert_od")` for OD matrices.
- `manage_demand(action="compute_routes")` for `duarouter`.
- `run_sumo_tool` for advanced scripts such as `routeSampler.py`, `route/cutRoutes.py`, or `route/routecheck.py`.
- `run_sumo_binary(name="duarouter")`, `run_sumo_binary(name="jtrrouter")`, or `run_sumo_binary(name="marouter")` for native routing.

## Guardrails
- Keep route files sorted by departure time.
- Validate that route files match the network before simulation.
- Preserve trip and route artifacts with roles.
