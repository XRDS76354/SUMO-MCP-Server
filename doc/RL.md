# SUMO-MCP v0.2 RL Guide

[中文文档](RL_CN.md)

This guide documents the v0.2 `manage_rl_task` contract for SUMO-RL training,
evaluation, and iteration. The MCP tool surface stays unchanged; RL capability
is extended through actions on `manage_rl_task`.

## Actions

| Action | Purpose |
|---|---|
| `list_scenarios` | List built-in `sumo-rl` network scenarios. |
| `list_algorithms` | Report algorithm support and optional dependency status. |
| `validate_env` | Preflight SUMO_HOME, binaries, XML, demand, TLS, timing, and algorithm dependencies. |
| `train` | Start a background RL training job with a run directory and manifest. |
| `resume` | Continue a run from the latest checkpoint/model. |
| `status` | Inspect run manifest and/or background job status. |
| `stop` | Cancel a background training job. |
| `evaluate` | Evaluate a saved Q-table or SB3 model. |
| `compare` | Compare trained policy against deterministic fixed-action baseline. |
| `list_runs` | List previous run manifests under an output directory. |
| `train_custom` | v0.1-compatible synchronous Q-learning path. |

## Algorithm Matrix

| Algorithm | Backend | Scope | Extra deps | Train | Resume | Evaluate/Compare |
|---|---|---|---|---|---|---|
| `ql` | sumo-rl `QLAgent` | Single or multi TLS | none beyond runtime | yes | Q-table checkpoint | yes |
| `pettingzoo-independent-ql` | independent per-TLS Q-tables | Single or multi TLS | `pettingzoo` from `sumo-rl` | yes | Q-table checkpoint | yes |
| `dqn` | Stable-Baselines3 DQN | one TLS | `sumo-mcp[rl]` | yes | `.zip` model | yes |
| `ppo` | Stable-Baselines3 PPO | one TLS | `sumo-mcp[rl]` | yes | `.zip` model | yes |
| `a2c` | Stable-Baselines3 A2C | one TLS | `sumo-mcp[rl]` | yes | `.zip` model | yes |

SB3 v0.2 intentionally rejects multi-TLS networks in `validate_env` because the
implemented trainer uses `sumo_rl.SumoEnvironment(single_agent=True)`, which
controls one traffic signal. Use `ql` or `pettingzoo-independent-ql` for
multi-signal independent learners until the SuperSuit/RLlib parameter-sharing
path is implemented.

## Recommended Loop

1. Inspect runtime:

```json
manage_rl_task("list_algorithms", {})
```

2. Validate a scenario or custom files:

```json
manage_rl_task("validate_env", {
  "scenario": "single-intersection",
  "algorithm": "ql",
  "delta_time": 5,
  "yellow_time": 2
})
```

3. Train as a background job:

```json
manage_rl_task("train", {
  "scenario": "single-intersection",
  "algorithm": "ql",
  "episodes": 3,
  "steps_per_episode": 1000,
  "output_dir": "rl_runs"
})
```

4. Poll and evaluate:

```json
manage_rl_task("status", {"job_id": "...", "run_dir": "rl_runs/..."})
manage_rl_task("evaluate", {"run_dir": "rl_runs/...", "episodes": 1})
manage_rl_task("compare", {"run_dir": "rl_runs/...", "episodes": 1})
```

5. Resume from latest checkpoint:

```json
manage_rl_task("resume", {"run_dir": "rl_runs/...", "episodes": 2})
```

## Run Directory Layout

Each `train` action creates:

```text
rl_runs/<run_id>/
  config.json
  manifest.json
  metrics.csv
  checkpoints/
    q_table_ep<N>.pkl        # QL / pettingzoo-independent-ql
    dqn_model.zip            # SB3 algorithms
  tensorboard/
  evaluation_trained.json
  evaluation_fixed.json
  comparison.json
```

Evaluation metrics always include `episode_rewards`, `mean_total_reward`, and
`policy`. When SUMO-RL system info is available, evaluation also aggregates:

- `mean_system_total_waiting_time`
- `mean_system_mean_waiting_time`
- `mean_system_total_stopped`
- `mean_system_mean_speed`
- `mean_agents_total_stopped`
- `mean_agents_total_accumulated_waiting_time`

## Failure Semantics

All public tool failures return a structured envelope with `ok=false`.

- Missing SUMO/SUMO_HOME: `SUMO_NOT_FOUND`
- Missing `sumo-rl`, SB3, or Torch: `DEPENDENCY_MISSING`
- Unknown algorithm or bad parameters: `INVALID_ARGUMENT`
- Invalid XML, empty demand, missing TLS, or unsupported SB3 multi-TLS scope: `VALIDATION_FAILED`

Install advanced RL dependencies with:

```bash
pip install -e ".[rl]"
```

