---
name: sumo-rl-experiments
description: Run and summarize SUMO RL workflows using SUMO-MCP v0.2 tools.
---

# SUMO RL Experiments

## Use When
- The task involves SUMO-RL scenarios, traffic-signal RL, training, evaluation, or iterative experiments.

## Required Resources
- Read `sumo://guide/rl-training` for algorithm boundaries.
- Use `sumo://diagnostics` if SUMO or optional RL dependency state is uncertain.

## Tool Order
1. `manage_rl_task(action="list_algorithms")`
2. `manage_rl_task(action="validate_env")`
3. `manage_rl_task(action="train")`
4. `manage_rl_task(action="status")` until the job is terminal
5. `manage_rl_task(action="evaluate")`
6. `manage_rl_task(action="compare")`
7. `manage_rl_task(action="resume")` when more training is needed

## Algorithm Boundaries
- `ql` works without advanced extras and supports independent single/multi-signal learners.
- `pettingzoo-independent-ql` uses the independent multi-agent Q-table path.
- `dqn`, `ppo`, and `a2c` require `sumo-mcp[rl]` and are single-traffic-signal SB3 trainers in v0.2.

## Failure Recovery
- `SUMO_NOT_FOUND`: fix SUMO_HOME and binary PATH.
- `DEPENDENCY_MISSING`: install `sumo-mcp[rl]` for SB3/Torch.
- `VALIDATION_FAILED`: check TLS, green phases, demand, and timing.
