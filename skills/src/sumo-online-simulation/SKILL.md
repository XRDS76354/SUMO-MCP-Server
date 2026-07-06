---
name: sumo-online-simulation
description: Run and query label-based online SUMO sessions through TraCI using SUMO-MCP v0.2.
---

# SUMO Online Simulation

## Use When
- The user needs step-by-step simulation, online state queries, or closed-loop control.

## Preferred Tools
- `control_simulation(action="connect")` to start or attach.
- `control_simulation(action="step")` for time advancement.
- `query_simulation_state` for vehicle lists, per-vehicle variables, and simulation stats.
- `control_simulation(action="disconnect")` to close cleanly.

## Guardrails
- Do not use raw `--remote-port` through CLI wrappers; session tools own TraCI ports.
- Use `session`/label parameters when provided so multiple simulations do not collide.
- Disconnect sessions when the workflow is complete.
