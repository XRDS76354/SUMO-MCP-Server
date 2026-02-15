# SUMO-MCP API 参考 (FastMCP Tools)

[English Documentation](API.md)

本文件是对 `src/server.py` 中 `@server.tool` 注册工具的文档镜像，用于给 MCP 宿主/LLM 提供稳定的调用契约。

**唯一真相源**：`src/server.py`（如本文与实现不一致，以代码为准）。

![SUMO-MCP 工具一览](sumo-mcp工具列表.png)

## 环境要求

- **Python**: 3.10+
- **SUMO**: 1.23+（二进制在 PATH 中；使用 tools 脚本需设置 SUMO_HOME）
- **Python 依赖**:
  - 运行时：`mcp[cli]`, `sumolib`, `traci`, `sumo-rl`, `pandas`, `requests`
  - 开发（可选）：`mypy`, `flake8`, `pytest`, `psutil`, `types-*`

详细安装指南见 [README_CN.md](../README_CN.md)。

## 通用约定

### 返回值
所有工具均返回 `string`（成功信息/结果摘要，或以 `Error:` 开头的错误信息）。

### `params.options`
部分工具支持在 `params` 中传入 `options`（`list[str]`），这些参数会**按 token 原样追加**到底层 SUMO 二进制/脚本命令中。

示例：
```json
{
  "options": ["--tls.guess", "true", "--default.lanenumber", "2"]
}
```

### SUMO 工具脚本依赖
封装 SUMO Python 工具脚本的能力（如 `osmGet.py` / `randomTrips.py` / `tls*.py`）需要能定位到 `<SUMO_HOME>/tools`。
项目会尝试自动推导 `SUMO_HOME`，但为保证确定性，仍推荐显式设置环境变量 `SUMO_HOME`。

为了提供更简洁、符合人类直觉的接口，我们将原有的 20+ 个工具合并为 7 个核心工具。每个工具通过 `action` 或 `method` 参数区分具体操作。

## 1. 路网管理 (manage_network)

管理 SUMO 路网文件的生成、转换和下载。

*   **工具名**: `manage_network`
*   **参数**:
    *   `action` (string): 操作类型，可选值：
        *   `generate`: 生成抽象路网（Grid/Spider）。
        *   `convert` (或 `convert_osm`): 将 OSM 文件转换为 SUMO 路网。
        *   `download_osm`: 从 OpenStreetMap 下载地图数据。
    *   `output_file` (string): 输出文件路径（对于 download_osm 为输出目录）。
    *   `params` (object, optional): 具体操作参数：
        *   `generate`: `{ "grid": bool, "grid_number": int, "spider": bool }`
        *   `convert` / `convert_osm`: `{ "osm_file": string }`
        *   `download_osm`: `{ "bbox": "w,s,e,n", "prefix": string }`
        *   `options`: `list[string]`，追加到底层命令的额外参数（见“通用约定”）

**说明**：
* `generate` 时 `spider=true` 会覆盖 `grid/grid_number`（强制生成 Spider 网络）；如需更多 Spider 参数请通过 `params.options` 透传 `netgenerate` 命令行选项。

## 2. 需求管理 (manage_demand)

管理交通需求生成、OD 矩阵转换和路径计算。

*   **工具名**: `manage_demand`
*   **参数**:
    *   `action` (string): 操作类型，可选值：
        *   `generate_random` (或 `random_trips`): 生成随机行程。
        *   `convert_od` (或 `od_matrix`): 将 OD 矩阵转换为行程。
        *   `compute_routes` (或 `routing`): 使用 duarouter 计算路由。
    *   `net_file` (string): 基础路网文件路径。
    *   `output_file` (string): 输出文件路径。
    *   `params` (object, optional): 具体操作参数：
        *   `generate_random` / `random_trips`: `{ "end_time": int, "end": int, "period": float }`（`end` 为兼容别名）
        *   `convert_od` / `od_matrix`: `{ "od_file": string }`
        *   `compute_routes` / `routing`: `{ "route_files": string }` (输入 trips 文件路径)
        *   `options`: `list[string]`，追加到底层命令的额外参数（见“通用约定”）

## 3. 仿真控制 (control_simulation)

在线控制 SUMO 仿真实例的生命周期。

*   **工具名**: `control_simulation`
*   **参数**:
    *   `action` (string): 操作类型，可选值：
        *   `connect`: 启动新仿真或连接现有实例。
        *   `step`: 向前推演仿真时间。
        *   `disconnect`: 断开连接并停止仿真。
    *   `params` (object, optional): 具体操作参数：
        *   `connect`: `{ "config_file": string, "gui": bool, "port": int, "host": string }`
        *   `step`: `{ "step": float }` (默认为 0，表示一步)

## 4. 状态查询 (query_simulation_state)

在线查询仿真中的实时状态（车辆、路网等）。需在 `control_simulation` 建立连接后使用。

*   **工具名**: `query_simulation_state`
*   **参数**:
    *   `target` (string): 查询目标，可选值：
        *   `vehicle_list` (或 `vehicles`): 获取所有活跃车辆 ID。
        *   `vehicle_variable`: 获取特定车辆的具体变量。
        *   `simulation`: 获取全局仿真状态（时间、车辆数统计）。
    *   `params` (object, optional): 具体操作参数：
        *   `vehicle_variable`: `{ "vehicle_id": string, "variable": string }`
            *   `variable` 支持: `speed`, `position`, `acceleration`, `lane`, `route`

## 5. 信号优化 (optimize_traffic_signals)

执行交通信号灯优化算法。

*   **工具名**: `optimize_traffic_signals`
*   **参数**:
    *   `method` (string): 优化方法，可选值：
        *   `cycle_adaptation` (或 `Websters`): 周期自适应优化（基于 Webster 公式）。
        *   `coordination`: 绿波协调控制。
    *   `net_file` (string): 路网文件。
    *   `route_file` (string): 路由文件。
    *   `output_file` (string): 输出文件路径。
    *   `params` (object, optional):
        *   `options`: `list[string]`，追加到底层命令的额外参数（主要用于 `coordination`；见“通用约定”）

**输出文件类型说明**：
* `cycle_adaptation`：SUMO `<additional>` 文件（包含 `<tlLogic>` 信号方案），应在 `.sumocfg` 中以 `<additional-files>` 引用，而不是作为 `<net-file>`。
* `coordination`：默认同样输出 `<additional>` 文件（TLS offsets），也应通过 `<additional-files>` 引用。
如需端到端“基线 vs 优化”对比，推荐直接使用 `run_workflow` 的 `signal_opt`，会自动处理输出文件类型并生成可运行配置。

## 6. 自动化工作流 (run_workflow)

执行预定义的长流程任务。

*   **工具名**: `run_workflow`
*   **参数**:
    *   `workflow_name` (string): 工作流名称，可选值：
        *   `sim_gen_eval` (或 `sim_gen_workflow` / `sim_gen`): 自动生成路网并评估。
        *   `signal_opt` (或 `signal_opt_workflow`): 信号灯优化全流程对比。
        *   `rl_train`: 强化学习训练流程。
    *   `params` (object): 工作流参数字典（支持别名，优先级按列出顺序）。

### sim_gen_eval 参数

| 参数 | 类型 | 默认值 | 别名 | 说明 |
|------|------|--------|------|------|
| `grid_number` | int | 3 | `grid_size`, `size` | 网格大小 NxN |
| `sim_seconds` | int | 100 | `steps`, `duration`, `end_time` | 仿真时长（秒） |
| `output_dir` | string | "output" | - | 输出目录 |

**调用示例**:
```json
run_workflow("sim_gen_eval", {"grid_number": 3, "sim_seconds": 1000})
// 等价于：
run_workflow("sim_gen_eval", {"size": 3, "steps": 1000})
```

### signal_opt 参数

| 参数 | 类型 | 默认值 | 别名 | 说明 |
|------|------|--------|------|------|
| `net_file` | string | **必填** | - | .net.xml 路网文件路径 |
| `route_file` | string | **必填** | - | .rou.xml 路由文件路径 |
| `sim_seconds` | int | 3600 | `steps`, `duration` | 仿真时长（秒） |
| `use_coordinator` | bool | false | - | 使用 tlsCoordinator 替代 tlsCycleAdaptation |
| `output_dir` | string | "output" | - | 输出目录 |

### rl_train 参数

| 参数 | 类型 | 默认值 | 别名 | 说明 |
|------|------|--------|------|------|
| `scenario_name` | string | - | `scenario` | 内置场景名（用 `manage_rl_task("list_scenarios")` 查看） |
| `episodes` | int | 5 | `num_episodes` | 训练回合数 |
| `steps` | int | 1000 | `steps_per_episode` | 每回合步数 |
| `output_dir` | string | "output" | - | 输出目录 |

## 7. 强化学习任务 (manage_rl_task)

管理基于开源项目 [sumo-rl](https://github.com/LucasAlegre/sumo-rl) 的强化学习任务。

*   **工具名**: `manage_rl_task`
*   **参数**:
    *   `action` (string): 操作类型，可选值：
        *   `list_scenarios`: 列出内置场景。
        *   `train_custom`: 运行自定义训练。
    *   `params` (object, optional):
        *   `train_custom`: 支持两种入口（二选一）：
            1) **内置场景**：`{ "scenario" 或 "scenario_name", "out_dir"/"output_dir", "episodes"/"num_episodes", "steps"/"steps_per_episode", "algorithm", "reward_type" }`
            2) **自定义文件**：`{ "net_file", "route_file", "out_dir"/"output_dir", "episodes"/"num_episodes", "steps"/"steps_per_episode", "algorithm", "reward_type" }`

**约束**：
* `list_scenarios` 仅依赖 `sumo-rl` 包本身；**训练**在 import `sumo-rl` 时强依赖 `SUMO_HOME`，因此运行训练前需显式设置 `SUMO_HOME`（并确保 `sumo` 可执行文件可用）。
* 自定义训练要求路网中存在信号灯（`tlLogic`），否则会返回 `No traffic lights found` 错误提示。
* `algorithm` 当前仅实现 `ql`（Q-Learning）。

---

## 遗留工具 (Legacy)

为了兼容性保留的独立工具：
*   `get_sumo_info`: 获取 SUMO 版本信息。
*   `run_simple_simulation`: 运行简单的配置文件仿真（离线）。参数：`config_path`，`steps`（默认 100）。
*   `run_analysis`: 解析 FCD 输出文件。参数：`fcd_file`。
