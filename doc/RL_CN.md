# SUMO-MCP v0.2 强化学习指南

[English](RL.md)

本文档说明 v0.2 中 `manage_rl_task` 的强化学习训练、评估与迭代契约。
MCP 工具数量保持不变，RL 能力通过 `manage_rl_task` 的 action 扩展。

## Actions

| Action | 用途 |
|---|---|
| `list_scenarios` | 列出 `sumo-rl` 内置场景。 |
| `list_algorithms` | 查看算法支持状态和可选依赖是否已安装。 |
| `validate_env` | 预检 SUMO_HOME、二进制、XML、需求、信号灯、时序和算法依赖。 |
| `train` | 创建 run 目录并启动后台训练 job。 |
| `resume` | 从最新 checkpoint/model 继续训练。 |
| `status` | 查看 run manifest 和/或后台 job 状态。 |
| `stop` | 取消后台训练 job。 |
| `evaluate` | 评估保存的 Q-table 或 SB3 model。 |
| `compare` | 对比训练策略与固定动作基线。 |
| `list_runs` | 列出输出目录下的历史 run。 |
| `train_custom` | 保留 v0.1 兼容的同步 Q-learning 路径。 |

## 算法矩阵

| Algorithm | Backend | 范围 | 额外依赖 | Train | Resume | Evaluate/Compare |
|---|---|---|---|---|---|---|
| `ql` | sumo-rl `QLAgent` | 单/多信号灯 | 运行时依赖即可 | 支持 | Q-table checkpoint | 支持 |
| `pettingzoo-independent-ql` | 每个信号灯独立 Q-table | 单/多信号灯 | `sumo-rl` 自带 `pettingzoo` | 支持 | Q-table checkpoint | 支持 |
| `dqn` | Stable-Baselines3 DQN | 单信号灯 | `sumo-mcp[rl]` | 支持 | `.zip` model | 支持 |
| `ppo` | Stable-Baselines3 PPO | 单信号灯 | `sumo-mcp[rl]` | 支持 | `.zip` model | 支持 |
| `a2c` | Stable-Baselines3 A2C | 单信号灯 | `sumo-mcp[rl]` | 支持 | `.zip` model | 支持 |

v0.2 的 SB3 训练器使用 `sumo_rl.SumoEnvironment(single_agent=True)`，
因此 `validate_env` 会拒绝多信号灯网络，避免只训练第一个信号灯却被误解为全局优化。
多信号灯独立学习请使用 `ql` 或 `pettingzoo-independent-ql`；SuperSuit/RLlib
参数共享会放在后续增量中实现。

## 推荐闭环

1. 查看运行时能力：

```json
manage_rl_task("list_algorithms", {})
```

2. 预检内置场景或自定义文件：

```json
manage_rl_task("validate_env", {
  "scenario": "single-intersection",
  "algorithm": "ql",
  "delta_time": 5,
  "yellow_time": 2
})
```

3. 后台训练：

```json
manage_rl_task("train", {
  "scenario": "single-intersection",
  "algorithm": "ql",
  "episodes": 3,
  "steps_per_episode": 1000,
  "output_dir": "rl_runs"
})
```

4. 轮询、评估、对比：

```json
manage_rl_task("status", {"job_id": "...", "run_dir": "rl_runs/..."})
manage_rl_task("evaluate", {"run_dir": "rl_runs/...", "episodes": 1})
manage_rl_task("compare", {"run_dir": "rl_runs/...", "episodes": 1})
```

5. 从最新 checkpoint 继续训练：

```json
manage_rl_task("resume", {"run_dir": "rl_runs/...", "episodes": 2})
```

## Run 目录结构

每次 `train` 会创建：

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

评估结果始终包含 `episode_rewards`、`mean_total_reward`、`policy`。
当 SUMO-RL 返回系统信息时，还会聚合：

- `mean_system_total_waiting_time`
- `mean_system_mean_waiting_time`
- `mean_system_total_stopped`
- `mean_system_mean_speed`
- `mean_agents_total_stopped`
- `mean_agents_total_accumulated_waiting_time`

## 失败语义

所有公开工具错误都返回结构化 envelope：`ok=false`。

- SUMO/SUMO_HOME 缺失：`SUMO_NOT_FOUND`
- `sumo-rl`、SB3、Torch 缺失：`DEPENDENCY_MISSING`
- 未知算法或参数错误：`INVALID_ARGUMENT`
- XML 无效、需求为空、缺信号灯、SB3 多信号灯边界不支持：`VALIDATION_FAILED`

安装高级 RL 依赖：

```bash
pip install -e ".[rl]"
```

