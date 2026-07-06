# SUMO-MCP v0.2 API 参考

[English](API.md)

本文档描述 `src/sumo_mcp/server.py` 暴露的 FastMCP 公共契约。v0.2
工具面固定为 16 个工具：v0.1 工具名保留，新增能力通过 action、resource、
prompt 和结构化返回扩展。

## 返回信封

所有工具返回 JSON 兼容 envelope：

```json
{
  "ok": true,
  "tool": "manage_network",
  "action": "generate",
  "summary": "人类可读摘要",
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

只有 `ok`、`tool`、`summary` 始终存在。v0.1 的字符串结果保存在 `summary`。

稳定错误码包括：`SUMO_NOT_FOUND`、`DEPENDENCY_MISSING`、
`INVALID_ARGUMENT`、`FILE_NOT_FOUND`、`EXECUTION_FAILED`、`TIMEOUT`、
`CONNECTION_ERROR`、`SESSION_NOT_FOUND`、`JOB_NOT_FOUND`、`GUI_BLOCKED`、
`VALIDATION_FAILED`、`NETWORK_ERROR`。

## 通用约定

- 路径可用相对路径，但 agent 串联工作流时建议用绝对路径。
- `params.options` 和 CLI `args` 必须是 `list[str]` argv token，不是 shell 字符串。
- 长任务尽量后台化，并用 `manage_sumo_jobs` 轮询。
- SUMO tools 脚本依赖 `<SUMO_HOME>/tools`；建议显式设置 `SUMO_HOME`。

## 工具

### `manage_network(action, output_file, params?)`

路网生成、OSM 下载/转换、ezdesignX 转换。

Actions：

- `generate`：`params.grid`、`params.grid_number`、`params.spider`，以及 `params.options` 原生参数。
- `download_osm`：`output_file` 是输出目录；`params.bbox`、`params.prefix`。
- `convert` / `convert_osm`：`params.osm_file`。
- `convert_ezdesignx`：`output_file` 是输出目录；`params.input_json`、`params.validation`。

### `convert_ezdesignx_network(input_json, output_dir, validation?, netconvert_bin?, sumo_bin?, sumo_gui_bin?)`

专用 ezdesignX v1 JSON/JSONC 转 SUMO 工具，保留 v0.1 独立工具名。

### `manage_demand(action, net_file, output_file, params?)`

需求和路径准备。

Actions：

- `generate_random` / `random_trips`：调用 `randomTrips.py`，支持 `end_time`、`period`、`options`。
- `convert_od` / `od_matrix`：调用 `od2trips`，需要 `params.od_file`。
- `compute_routes` / `routing`：调用 `duarouter`，需要 `params.route_files`。

### `control_simulation(action, params?)`

在线 TraCI 生命周期。

Actions：

- `connect`：`params.config_file`、`params.gui`、`params.port`、`params.host`，可选 `params.session`。
- `step`：`params.step`，可选 `params.session`。
- `disconnect`：可选 `params.session`。

### `query_simulation_state(target, params?)`

在线状态查询。

Targets：

- `vehicle_list` / `vehicles`
- `vehicle_variable`：`params.vehicle_id`、`params.variable`（`speed`、`position`、`acceleration`、`lane`、`route`）
- `simulation`：全局时间和车辆数

提供 `params.session` 时走命名 session；否则保留旧全局连接行为。

### `optimize_traffic_signals(method, net_file, route_file, output_file, params?)`

信号优化。

Methods：

- `cycle_adaptation` / `Websters`：基于 `tlsCycleAdaptation.py` 的 Webster 配时。
- `coordination`：基于 `tlsCoordinator.py` 的绿波协调。

输出是 SUMO additional 文件，需要挂载到 `<additional-files>`。

### `run_workflow(workflow_name, params)`

端到端工作流。

- `sim_gen_eval`：生成路网、需求、路径、仿真和分析。
- `signal_opt`：基线仿真、信号优化、优化仿真、对比。
- `rl_train`：旧版内置 SUMO-RL 工作流。

### `manage_rl_task(action, params?)`

RL 实验生命周期。详见 [RL 指南](RL_CN.md)。

Actions：

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
- `train_custom`（v0.1 兼容同步 Q-learning）

支持算法：`ql`、`pettingzoo-independent-ql`、`dqn`、`ppo`、`a2c`。
SB3 算法需要 `sumo-mcp[rl]`，v0.2 仅支持单信号灯。

### `get_sumo_info()`

SUMO 诊断：版本、二进制、tools 目录、环境状态。

### `run_simple_simulation(config_file, output_dir?)`

使用旧版简单 wrapper 运行 `.sumocfg` 仿真。

### `run_analysis(fcd_file)`

旧版 FCD CSV 分析工具。

### `list_sumo_commands(kind?, tier?, search?, include_unavailable?)`

查看 curated/runtime SUMO 命令目录。`kind` 是 `binary` 或 `tool`。
Tier 1 是精选命令；tier 3 是 `$SUMO_HOME/tools` 动态发现脚本。

### `run_sumo_binary(name, args?, cwd?, timeout_s?, expected_outputs?, background?)`

运行白名单 SUMO 二进制，例如 `sumo`、`netconvert`、`netgenerate`、
`duarouter`、`od2trips`。参数是 argv token。

### `run_sumo_tool(name, args?, cwd?, timeout_s?, expected_outputs?, background?)`

运行白名单 SUMO Python tools 脚本，例如 `randomTrips.py`、`osmBuild.py`、
`tlsCycleAdaptation.py`、`xml/xml2csv.py`。

### `analyze_sumo_output(file_path, kind?, max_elements?)`

流式分析 summary、tripinfo、FCD、queue、emission 等 SUMO XML 输出。
支持 gzip，通过 `max_elements` 控制截断。

### `manage_sumo_jobs(action, params?)`

持久化后台 job 管理。

Actions：

- `list`
- `status`：需要 `params.job_id`
- `result`：需要 `params.job_id`
- `logs`：需要 `params.job_id`，可选 `tail_lines`
- `cancel`：需要 `params.job_id`

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
