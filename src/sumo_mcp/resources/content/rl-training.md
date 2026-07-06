# SUMO-RL Training Guide

Use `manage_rl_task(action="list_algorithms")` to inspect runtime support.

Algorithm boundaries:

- `ql`: default independent Q-learning, supports single and multiple traffic
  lights, saves Q-table checkpoints.
- `pettingzoo-independent-ql`: same independent learner contract under the
  PettingZoo-oriented algorithm name, useful for multi-agent wording.
- `dqn`, `ppo`, `a2c`: Stable-Baselines3 algorithms. They require
  `sumo-mcp[rl]` and are intentionally limited to one traffic signal in v0.2.

Always run `manage_rl_task(action="validate_env")` before `train`. Important
checks include SUMO_HOME, `sumo`, `sumo-rl`, net/route XML parse, non-empty
demand, TLS existence, green phases, `delta_time > yellow_time`, and optional
algorithm dependencies.

Evaluation:

- `manage_rl_task(action="evaluate")` runs the trained policy.
- `manage_rl_task(action="compare")` compares against action 0 as a deterministic
  baseline.
- Metrics include reward, waiting time, queue/stopped counts, and mean speed
  when SUMO-RL exposes those fields.

Common fixes:

- No TLS: rebuild network with TLS guessing or add `tlLogic`.
- Empty demand: regenerate trips/routes and ensure route XML is not just types.
- SB3 dependency missing: install `pip install -e ".[rl]"`.
- Multi-TLS SB3 rejected: switch to `ql` / `pettingzoo-independent-ql`.
