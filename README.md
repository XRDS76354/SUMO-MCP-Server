# SUMO-MCP: 智能交通仿真与控制的 MCP 平台

<div align="center">
  <img src="doc/sumo-mcp.jpg" alt="SUMO-MCP Logo" width="200" />
  <br />
  <br />
  <p align="center">
    <img src="https://img.shields.io/badge/Status-Active-success" alt="Status" />
    <img src="https://img.shields.io/badge/Python-3.10+-blue" alt="Python" />
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License" />
  </p>
</div>

SUMO-MCP 是一个连接大语言模型 (LLM) 与 [Eclipse SUMO](https://www.eclipse.org/sumo/) 交通仿真的中间件。通过 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)，它允许 AI 智能体（如 Claude, Cursor, TRAE等）直接调用 SUMO 的核心功能，实现从**OpenStreetMap 数据获取**、**路网生成**、**需求建模**到**仿真运行**与**信号优化**的全流程自动化。

系统支持**离线仿真**（基于文件的工作流）和**在线交互**（实时 TraCI 控制）两种模式，满足从宏观规划到微观控制的多样化需求。

API 参考见 `doc/API.md`（唯一真相源以 `src/server.py` 的工具注册为准）。

## 🚀 核心功能特性

### 1. 全面的工具链集成
聚合符合直觉的核心 MCP 接口，简化 SUMO 复杂操作：

*   **路网管理 (`manage_network`)**: 支持路网生成 (`generate`)、OSM 地图下载 (`download_osm`) 与格式转换 (`convert`)。
*   **需求管理 (`manage_demand`)**: 提供随机行程生成 (`generate_random`)、OD 矩阵转换 (`convert_od`) 和路径计算 (`compute_routes`)。
*   **信号优化 (`optimize_traffic_signals`)**: 集成周期自适应 (`cycle_adaptation`) 和绿波协调 (`coordination`) 算法；其中 `cycle_adaptation` 输出为 SUMO `<additional>` 信号方案文件（由工作流自动挂载到 `<additional-files>`）。
*   **仿真与分析**: 支持标准配置文件仿真 (`run_simple_simulation`) 与 FCD 轨迹数据分析 (`run_analysis`)。

部分聚合工具支持在 `params` 中传入 `options: list[str]`，用于将额外参数按 token 透传到底层 SUMO 二进制/脚本（详见 `doc/API.md` 的“通用约定”）。

### 2. 在线实时交互 (Online Interaction)
支持通过 TraCI 协议与运行中的仿真实例进行实时交互，赋予 LLM 微观控制与感知能力：

*   **仿真控制 (`control_simulation`)**: 提供启动连接 (`connect`)、单步推演 (`step`) 和安全断开 (`disconnect`)。
*   **状态查询 (`query_simulation_state`)**: 实时获取车辆列表 (`vehicle_list`)、车辆细节变量 (`vehicle_variable`) 及全局仿真统计。

### 3. 自动化智能工作流
内置端到端的自动化工作流 (`run_workflow`)，简化复杂科研与工程任务：

*   **Sim Gen & Eval (`sim_gen_eval`)**: 一键执行 "生成路网 -> 生成需求 -> 路径计算 -> 仿真运行 -> 结果分析" 的完整闭环。
*   **Signal Optimization (`signal_opt`)**: 自动执行 "基线仿真 -> 信号优化 -> 优化仿真 -> 效果对比" 的全流程，并自动处理优化工具输出的 `<additional>` 文件挂载。
*   **RL Training (`rl_train`)**: 针对内置场景的强化学习训练；自定义路网训练使用 `manage_rl_task/train_custom`（要求路网包含信号灯，且 `sumo-rl` 运行建议显式设置 `SUMO_HOME`）。

---

## 🛠️ 环境要求

*   **操作系统**: Windows / Linux / macOS
*   **Python**: 3.10+ (强制要求，以支持最新的类型系统与 MCP SDK)
*   **SUMO**: Eclipse SUMO 1.23+（需保证 SUMO 二进制在 `PATH` 中；如需使用 SUMO 自带 tools 脚本，建议配置 `SUMO_HOME`）

---

## 📦 安装指南

### 1. 获取代码

您可以通过以下方式获取项目：

**方式 A：通过 Git 克隆 (推荐)**
```bash
git clone https://github.com/2217173240/sumo-mcp.git
cd sumo-mcp
```

**方式 B：下载压缩包**
1. 访问 [GitHub 项目主页](https://github.com/2217173240/sumo-mcp)。
2. 点击 **Code** 按钮，选择 **Download ZIP**。
3. 解压并进入项目目录。

**方式 C：作为依赖安装 (WIP)**
如果您想在其他项目中使用，可以尝试：
```bash
pip install git+https://github.com/2217173240/sumo-mcp.git
```

## 🛠️ 环境配置 (二选一)

您可以选择以下任一方式配置开发环境。

### 选项 A：使用 uv (推荐 - 极速)

[uv](https://github.com/astral-sh/uv) 是目前最快的 Python 包管理工具，支持一键同步依赖。

```bash
# 1. 安装 uv (如果尚未安装)
pip install uv

# 2. 同步项目环境 (自动创建虚拟环境并安装依赖)
uv sync

# 3. 激活环境
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

### 选项 B：使用 Conda + Pip (传统)

如果您习惯使用 Conda 管理环境，可以按照以下步骤操作：

```bash
# 1. 创建并激活 Conda 环境
conda create -n sumo-mcp python=3.10 -y
conda activate sumo-mcp

# 2. 安装项目依赖 (包含开发工具)
pip install -e ".[dev]"
```

### 4. 配置 SUMO (Installation & Setup)

#### Important Notes
*   **仅使用 SUMO 二进制工具**（`sumo` / `netconvert` / `netgenerate` / `duarouter` / `od2trips` 等）：保证命令在 `PATH` 中即可。
*   **使用 SUMO tools 脚本**（`randomTrips.py` / `osmGet.py` / `tls*.py` 等）：需要能定位到 `<SUMO_HOME>/tools`，推荐设置 `SUMO_HOME` 指向 SUMO 安装目录，并把 `$SUMO_HOME/bin` 加入 `PATH`。

#### Windows Setup
1. 安装 SUMO：使用官方安装包（文档：https://sumo.dlr.de/）。
2. 设置环境变量（示例）：
   - CMD（持久化）：`setx SUMO_HOME "C:\Program Files\Eclipse\sumo"`，`setx PATH "%SUMO_HOME%\bin;%PATH%"`
   - PowerShell（当前会话）：`$env:SUMO_HOME="C:\Program Files\Eclipse\sumo"; $env:PATH="$env:SUMO_HOME\bin;$env:PATH"`
3. 验证：`sumo --version`

#### Linux Setup (Ubuntu/Debian)
1. 安装：`sudo apt-get install sumo sumo-tools`
2. 可选（使用 tools 脚本时推荐）：`export SUMO_HOME=/usr/share/sumo` 并把 `$SUMO_HOME/bin` 加入 `PATH`
3. 验证：`sumo --version`

#### macOS Setup (Homebrew)
1. 安装：`brew install sumo`
2. Homebrew 通常会自动把 `sumo` 加到 `PATH`；如需 tools 脚本，可设置 `SUMO_HOME` 指向 `.../share/sumo`（例如 `/usr/local/share/sumo` 或 `/opt/homebrew/share/sumo`）
3. 验证：`sumo --version`

---

## 🚦 启动服务

使用 Python 启动 MCP 服务器：

```bash
python src/server.py
```

也可以使用启动脚本（会自动把 `$SUMO_HOME/bin` 加入 `PATH`，并在找不到 `sumo` 时给出提示）：

```bash
# Linux/macOS
./start_server.sh
```

```powershell
# Windows PowerShell
.\start_server.ps1
```

```bat
REM Windows CMD
start_server.bat
```

服务器基于官方 `mcp.server.fastmcp.FastMCP`，通过标准输入输出 (stdio) 传输 JSON-RPC 2.0 消息，您可以将其配置到任何支持 MCP 的宿主应用中。

工具清单与参数约定请以 `src/server.py` / `doc/API.md` 为准。

**Claude Desktop 配置示例**:

```json
{
  "mcpServers": {
    "sumo-mcp": {
      "command": "path/to/your/venv/python",
      "args": ["path/to/sumo-mcp/src/server.py"]
    }
  }
}
```

更多配置示例见 `mcp_config_examples.json`。

---

## 💡 使用示例 (Prompt)

在配置了 MCP 的 AI 助手中，您可以尝试以下自然语言指令：

*   **工作流任务**:
    > "生成一个 3x3 的网格路网，模拟 1000 秒的交通流，并告诉我平均车速。"
    > *(AI 将调用 `manage_network` 和 `run_workflow`)*
*   **在线交互任务**:
    > "启动这个配置文件的仿真，每运行一步就告诉我 ID 为 'v_0' 的车辆速度，如果速度低于 5m/s 就提醒我。"
    > *(AI 将调用 `control_simulation` 和 `query_simulation_state`)*
*   **强化学习任务**:
    > "列出所有内置的强化学习场景，然后选择一个简单的路口场景训练 5 个回合。"
    > *(AI 将调用 `manage_rl_task` 和 `run_workflow`)*

---

## 🧰 Troubleshooting

*   **提示找不到 `sumo`**（例如：`Error: Could not locate SUMO executable (`sumo`).`）：
    1. 先在终端执行 `sumo --version`，确认 SUMO 二进制可用。
    2. 若不可用：把 SUMO 的 `bin/` 加入 `PATH`，或设置 `SUMO_HOME` 并把 `$SUMO_HOME/bin` 加入 `PATH`。
*   **提示找不到 tools 脚本**（例如：`randomTrips.py` / `osmGet.py` / `tls*.py`）：
    1. 确认 `SUMO_HOME` 指向 SUMO 安装目录。
    2. 确认 `<SUMO_HOME>/tools` 目录存在且包含对应脚本。
*   **MCP 客户端无法继承环境变量**：
    1. 在 MCP 客户端配置中显式传入 `env`（参考 `mcp_config_examples.json`）。

## 📂 项目结构

```text
sumo-mcp/
├── doc/
│   ├── API.md             # MCP 工具 API 参考（与 src/server.py 对齐）
│   └── sumo-mcp.jpg       # 项目图片
├── docs/                  # 开发/审查过程文档（可选阅读）
├── examples/              # 示例脚本（会忽略生成的输出文件）
├── src/
│   ├── server.py           # MCP 服务器入口 (FastMCP 实现，聚合接口)
│   ├── utils/              # 通用工具
│   │   ├── connection.py   # TraCI 连接管理器
│   │   └── ...
│   ├── mcp_tools/          # 核心工具模块
│   │   ├── network.py      # 网络工具
│   │   ├── route.py        # 路径工具
│   │   ├── signal.py       # 信号工具
│   │   ├── vehicle.py      # 车辆工具
│   │   ├── rl.py           # 强化学习工具
│   │   └── analysis.py     # 分析工具
│   └── workflows/          # 自动化工作流
│       ├── sim_gen.py      # 仿真生成工作流
│       ├── signal_opt.py   # 信号优化工作流
│       └── rl_train.py     # RL 训练工作流
├── pyproject.toml          # 项目配置与依赖管理
├── requirements.lock       # 锁定依赖版本
└── README.md               # 项目文档
```

## 📄 许可证

MIT License
