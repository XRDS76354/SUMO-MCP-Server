# SUMO-MCP: SUMO 智能交通仿真的 MCP 服务器

[English Documentation](README.md)

<div align="center">
  <img src="doc/sumo-mcp.jpg" alt="SUMO-MCP Logo" width="200" />
  <br />
  <br />
  <p align="center">
    <a href="https://github.com/XRDS76354/SUMO-MCP-Server"><img src="https://img.shields.io/badge/Status-Active-success" alt="Status" /></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10+-blue" alt="Python" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="License" /></a>
    <a href="https://deepwiki.com/XRDS76354/SUMO-MCP-Server"><img src="https://deepwiki.com/badge.svg" alt="DeepWiki" /></a>
    <a href="https://github.com/XRDS76354/SUMO-MCP-Server"><img src="https://img.shields.io/github/last-commit/XRDS76354/SUMO-MCP-Server" alt="Last Commit" /></a>
    <a href="doc/API_CN.md"><img src="https://img.shields.io/badge/API-Docs-blue" alt="API Docs" /></a>
    <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey" alt="Platform" />
  </p>
</div>

SUMO-MCP 是一个连接大语言模型 (LLM) 与 [Eclipse SUMO](https://www.eclipse.org/sumo/) 交通仿真的中间件。通过 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)，它允许 AI 智能体（如 Claude, Cursor, TRAE等）直接调用 SUMO 的核心功能，实现从**OpenStreetMap 数据获取**、**路网生成**、**需求建模**到**仿真运行**与**信号优化**的全流程自动化。

系统支持**离线仿真**（基于文件的工作流）和**在线交互**（实时 TraCI 控制）两种模式，满足从宏观规划到微观控制的多样化需求。

API 参考见 [doc/API_CN.md](doc/API_CN.md)（唯一真相源以 `src/sumo_mcp/server.py` 的工具注册为准）。
ezdesignX 转换说明见 [doc/EZDESIGNX_TO_SUMO_CN.md](doc/EZDESIGNX_TO_SUMO_CN.md)。
架构说明见 [doc/ARCHITECTURE_CN.md](doc/ARCHITECTURE_CN.md)。变更日志见 [CHANGELOG.md](CHANGELOG.md)。

## v0.2 速查

- 固定 16 个 MCP tools，并保留 v0.1 工具名。
- 所有工具返回结构化 envelope；人类可读文本在 `summary`。
- 安全 SUMO binary/tool wrapper：命令目录、后台 job、stdout 隔离。
- MCP resources/prompts 提供 diagnostics、工具选择、RL 训练、工作流和排障指南。
- RL 闭环支持预检、训练/续训、状态、评估、对比和 run manifest。

## 🚀 核心功能特性

### 1. 全面的工具链集成
聚合符合直觉的核心 MCP 接口，简化 SUMO 复杂操作。v0.2 权威工具清单以
[doc/API_CN.md](doc/API_CN.md) 和 MCP resource `sumo://tool-catalog` 为准；
旧截图仅作为历史素材保留。

*   **路网管理 (`manage_network`)**: 支持路网生成 (`generate`)、OSM 地图下载 (`download_osm`)、格式转换 (`convert`) 以及 ezdesignX v1 JSON/JSONC 转换 (`convert_ezdesignx`)；同时提供专用工具 `convert_ezdesignx_network`。
*   **需求管理 (`manage_demand`)**: 提供随机行程生成 (`generate_random`)、OD 矩阵转换 (`convert_od`) 和路径计算 (`compute_routes`)。
*   **信号优化 (`optimize_traffic_signals`)**: 集成周期自适应 (`cycle_adaptation`) 和绿波协调 (`coordination`) 算法；其中 `cycle_adaptation` 输出为 SUMO `<additional>` 信号方案文件（由工作流自动挂载到 `<additional-files>`）。
*   **SUMO CLI 适配**: 使用 `list_sumo_commands`、`run_sumo_binary`、`run_sumo_tool` 查看并运行白名单 SUMO binaries/tools。
*   **仿真与分析**: 支持标准配置文件仿真 (`run_simple_simulation`)、旧版 FCD 分析 (`run_analysis`) 和流式 XML 输出分析 (`analyze_sumo_output`)。

部分聚合工具支持在 `params` 中传入 `options: list[str]`，用于将额外参数按 token 透传到底层 SUMO 二进制/脚本（详见 `doc/API_CN.md` 的“通用约定”）。

### 2. 在线实时交互 (Online Interaction)
支持通过 TraCI 协议与运行中的仿真实例进行实时交互，赋予 LLM 微观控制与感知能力：

*   **仿真控制 (`control_simulation`)**: 提供启动连接 (`connect`)、单步推演 (`step`) 和安全断开 (`disconnect`)。
*   **状态查询 (`query_simulation_state`)**: 实时获取车辆列表 (`vehicle_list`)、车辆细节变量 (`vehicle_variable`) 及全局仿真统计。

### 3. 自动化智能工作流
内置端到端的自动化工作流 (`run_workflow`)，简化复杂科研与工程任务：

*   **Sim Gen & Eval (`sim_gen_eval`)**: 一键执行 "生成路网 -> 生成需求 -> 路径计算 -> 仿真运行 -> 结果分析" 的完整闭环。
    - 参数：`grid_number`(别名:`grid_size`,`size`), `sim_seconds`(别名:`steps`,`duration`,`end_time`), `output_dir`
*   **Signal Optimization (`signal_opt`)**: 自动执行 "基线仿真 -> 信号优化 -> 优化仿真 -> 效果对比" 的全流程，并自动处理优化工具输出的 `<additional>` 文件挂载。
    - 参数：`net_file`(必填), `route_file`(必填), `sim_seconds`(别名:`steps`,`duration`), `use_coordinator`, `output_dir`
*   **RL Training (`rl_train` / `manage_rl_task`)**: 基于 SUMO-RL 的强化学习闭环：预检、后台训练/继续训练、状态查询、评估和对比。v0.2 支持 Q-learning、每信号灯独立 Q-learning，以及可选 SB3 DQN/PPO/A2C 单信号灯训练。见 [RL 指南](doc/RL_CN.md)。
    - 参数：`scenario_name`(别名:`scenario`), `episodes`(别名:`num_episodes`), `steps`(别名:`steps_per_episode`), `output_dir`

> 💡 **提示**: 关于各工具的详细参数说明与调用示例，请参考 [API 详细文档](doc/API_CN.md) 和 [RL 指南](doc/RL_CN.md)。

---

## 🛠️ 环境要求

*   **操作系统**: Windows / Linux / macOS
*   **Python**: 3.10+ (强制要求，以支持最新的类型系统与 MCP SDK)
*   **SUMO**: [Eclipse SUMO](https://www.eclipse.org/sumo/)(需配置 `SUMO_HOME` 环境变量，并确保其二进制目录在 `PATH` 中)

### Python 依赖

**运行时依赖**（安装后即可使用所有 MCP 工具）：
- `mcp[cli]>=1.0.0` - 官方 Model Context Protocol SDK
- `sumolib>=1.20.0` - SUMO Python 库（路网操作、二进制调用）
- `traci>=1.20.0` - Traffic Control Interface（在线实时控制）
- `sumo-rl>=1.4.3` - SUMO 强化学习环境（RL 训练功能）
- `pandas>=2.0.0` - 数据分析（FCD 轨迹处理）
- `requests>=2.31.0` - HTTP 请求（OSM 数据下载）

**开发依赖**（可选，用于测试和代码质量检查）：
- `mypy>=1.8.0` - 静态类型检查
- `flake8>=7.0.0` - 代码风格检查
- `pytest>=8.0.0` - 单元测试框架
- `psutil>=5.9.0` - 系统资源监控（性能测试）
- `types-*` - 类型存根包（mypy 支持）

使用 `.\install_deps.ps1 -NoDev` 可以跳过开发依赖的安装。

---

## 📦 安装指南

### 1. 获取代码

您可以通过以下方式获取项目：

**方式 A：通过 Git 克隆 (推荐)**
```bash
git clone https://github.com/XRDS76354/SUMO-MCP-Server.git
cd SUMO-MCP-Server
```

**方式 B：下载压缩包**
1. 访问 [GitHub 项目主页](https://github.com/XRDS76354/SUMO-MCP-Server)。
2. 点击 **Code** 按钮，选择 **Download ZIP**。
3. 解压并进入项目目录。

**方式 C：从 GitHub 安装**
如果您想在其他项目中使用：
```bash
pip install git+https://github.com/XRDS76354/SUMO-MCP-Server.git

# 或者不做持久安装，直接运行：
uvx --from git+https://github.com/XRDS76354/SUMO-MCP-Server sumo-mcp
```

### 2. 安装与配置 SUMO

本系统依赖于 [Eclipse SUMO](https://www.eclipse.org/sumo/) 仿真引擎。

#### 重要提示 (Important Notes)
*   **仅使用 SUMO 二进制工具**（`sumo` / `netconvert` / `netgenerate` / `duarouter` / `od2trips` 等）：保证命令在 `PATH` 中即可。
*   **使用 SUMO tools 脚本**（`randomTrips.py` / `osmGet.py` / `tls*.py` 等）：需要能定位到 `<SUMO_HOME>/tools`，推荐设置 `SUMO_HOME` 指向 SUMO 安装目录，并把 `$SUMO_HOME/bin` 加入 `PATH`。

#### 各平台安装步骤
*   **Windows**:
    1. 安装 SUMO：使用官方安装包（文档：https://sumo.dlr.de/）。
    2. 设置环境变量（示例）：
       - CMD：`setx SUMO_HOME "C:\Program Files\Eclipse\sumo"`，`setx PATH "%SUMO_HOME%\bin;%PATH%"`
       - PowerShell：`$env:SUMO_HOME="C:\Program Files\Eclipse\sumo"; $env:PATH="$env:SUMO_HOME\bin;$env:PATH"`
    3. 验证：`sumo --version`
*   **Linux (Ubuntu/Debian)**:
    1. 安装：`sudo apt-get install sumo sumo-tools`
    2. 可选（使用 tools 脚本时推荐）：`export SUMO_HOME=/usr/share/sumo` 并把 `$SUMO_HOME/bin` 加入 `PATH`
    3. 验证：`sumo --version`
*   **macOS (Homebrew)**:
    1. 安装：`brew install sumo`
    2. Homebrew 通常会自动把 `sumo` 加到 `PATH`；如需 tools 脚本，可设置 `SUMO_HOME` 指向 `.../share/sumo`（例如 `/usr/local/share/sumo` 或 `/opt/homebrew/share/sumo`）
    3. 验证：`sumo --version`

> � **更多说明**: 更多关于 SUMO 安装与配置的详细信息，请参考 [SUMO 官方文档](https://sumo.dlr.de/docs/)。

### 3. Python 环境配置

#### Windows 一键安装

在 Windows 上可以直接使用仓库自带脚本创建 `.venv` 并安装依赖（默认包含开发依赖 `.[dev]`）。

**方式 A：PowerShell（推荐）**

```powershell
.\install_deps.ps1

# 可选参数：
.\install_deps.ps1 -NoDev                                               # 仅安装运行依赖
.\install_deps.ps1 -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple  # 使用国内镜像
```

**方式 B：CMD（命令提示符）**
```bat
install_deps.bat

REM 可选参数：
install_deps.bat -NoDev
install_deps.bat -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
```

脚本会自动：
- 检测并验证 Python 3.10+ 版本
- 创建虚拟环境 `.venv`（如不存在）
- 升级 pip/setuptools/wheel
- 安装项目依赖（editable mode）

您可以选择以下任一方式手动配置开发环境。

#### 方式1：使用 uv (推荐 - 极速)

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

#### 方式2：使用 Conda + Pip 

如果您习惯使用 Conda 管理环境，可以按照以下步骤操作：

```bash
# 1. 创建并激活 Conda 环境
conda create -n sumo-mcp python=3.10 -y
conda activate sumo-mcp

# 2. 安装项目依赖
# 推荐国内用户使用镜像源加速，一键安装项目及开发工具
pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple

# 可选高级 RL 依赖
pip install -e ".[rl]"

# 或者仅安装基础依赖
pip install -r requirements.txt
```

---

## 🚦 启动与配置

### 1. 本地直接启动 (用于测试)

服务器基于官方 `mcp.server.fastmcp.FastMCP` 实现，通过标准输入输出 (stdio) 传输 JSON-RPC 2.0 消息。

使用 Python 直接启动 MCP 服务器：

```bash
python src/server.py
python -m sumo_mcp
sumo-mcp
```

或者使用仓库自带的启动脚本（会自动处理环境检测与 `PATH` 挂载）：

*   **Linux/macOS**: `./start_server.sh`
*   **Windows (PowerShell)**: `.\start_server.ps1`
*   **Windows (CMD)**: `start_server.bat`

### 2. MCP 服务配置 (关键 - 用于 AI 宿主)

配置 MCP 服务器到宿主应用（如 Claude Desktop, Trae, Cursor）时，**必须使用绝对路径**。

#### A. 查找必要路径
在终端中激活您的环境后，运行以下命令：

*   **Python 绝对路径**:
    - Windows (PS): `(Get-Command python).Source`
    - Linux/macOS: `which python`
*   **SUMO_HOME 路径**:
    - Windows: `echo %SUMO_HOME%`
    - Linux/macOS: `echo $SUMO_HOME`

#### B. 宿主应用配置示例
将以下 JSON 添加到宿主应用的配置文件中（例如 Claude Desktop 的 `claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "sumo-mcp": {
      "command": "/path/to/your/env/python", 
      "args": ["/path/to/SUMO-MCP-Server/src/server.py"],
      "env": {
        "SUMO_HOME": "/your/actual/sumo/path",
        "PYTHONPATH": "/path/to/SUMO-MCP-Server/src"
      }
    }
  }
}
```

> **⚠️ 重要提示**: 
> 1. `command`: 必须替换为您找到的 **Python 解释器绝对路径**。
> 2. `args`: 必须替换为项目 `src/server.py` 的 **绝对路径**。
> 3. `env`: 显式设置 `SUMO_HOME` 和 `PYTHONPATH` 可以有效避免 `ModuleNotFoundError` 或环境识别错误。
> 4. 已安装环境可直接使用 `sumo-mcp` 或 `python -m sumo_mcp`，不必走源码 shim。

工具清单与参数约定请以 `src/sumo_mcp/server.py` 或 `doc/API_CN.md` 为准。

更多配置示例见 `mcp_config_examples.json`。

---

## 💡 使用示例 (Prompt)

在配置了 MCP 的 AI 助手中，您可以尝试以下自然语言指令：

*   **工作流任务**:

    > "生成一个 3x3 的网格路网，模拟 100 秒的交通流，并告诉我平均车速。"
    > *(AI 将调用 `run_workflow("sim_gen_eval", {"grid_number": 3, "sim_seconds": 100})`)*

*   **在线交互任务**:
    > "启动这个配置文件的仿真，每运行一步就告诉我 ID 为 'v_0' 的车辆速度，如果速度低于 5m/s 就提醒我。"
    > *(AI 将调用 `control_simulation` 和 `query_simulation_state`)*
*   **强化学习任务**:

    > "列出所有内置的强化学习场景，然后选择一个简单的路口场景训练 5 个回合。"
    > *(AI 将调用 `manage_rl_task("list_scenarios")`、`manage_rl_task("validate_env")`、`manage_rl_task("train")`，然后执行 `evaluate` 和 `compare`)*
- **复杂综合场景示例 (推荐测试)**:

  > "使用工具中的sumo-mcp完成下面操作：生成一个4x4的网格路网，要求所有节点均为交叉路口，设置网格间距为100米（默认值）确保所有交叉口都配置交通信号灯，设置车辆总数为200辆，运行进行1000秒的交通仿真，启用车辆轨迹记录功能，提取所有车辆的速度数据计算整个仿真期间所有车辆的平均速度，结果精确到小数点后两位。"
  >
  > **AI 内部执行逻辑**:
  >
  > 1. 调用 `manage_network(action="generate", output_file="grid.net.xml", params={"grid": true, "grid_number": 4})`
  > 2. 调用 `manage_demand(action="random_trips", net_file="grid.net.xml", output_file="trips.xml", params={"end_time": 1000, "period": 5.0})` (计算: 1000s / 200辆 = 每5秒一辆)
  > 3. 调用 `run_workflow("sim_gen_eval", {"grid_number": 4, "sim_seconds": 1000, "output_dir": "results"})` 或手动组合 `control_simulation`
  > 4. 调用 `run_analysis(fcd_file="results/fcd.xml")` 获取平均速度统计。

---

## 🧰 Troubleshooting

*   **提示找不到 `sumo`**（例如：`Error: Could not locate SUMO executable (`sumo`).`）：
    1. 先在终端执行 `sumo --version`，确认 SUMO 二进制可用。
    2. 若不可用：把 SUMO 的 `bin/` 加入 `PATH`，或设置 `SUMO_HOME` 并把 `$SUMO_HOME/bin` 加入 `PATH`。
*   **提示找不到 tools 脚本**（例如：`randomTrips.py` / `osmGet.py` / `tls*.py`）：
    1. 确认 `SUMO_HOME` 指向 SUMO 安装目录。
    2. 确认 `<SUMO_HOME>/tools` 目录存在且包含对应脚本。
*   **MCP 调用卡住 / 响应显示 `undefined`**：
    1. 该项目通过 stdio 传输 JSON-RPC，任何子进程（SUMO / tools 脚本）向标准输出打印的非 JSON 文本都可能污染通信，导致宿主无法解析响应。
    2. 升级到最新版本（已将 TraCI 启动的 SUMO stdout 做隔离），或确保相关子进程输出被捕获/重定向。
*   **MCP 客户端无法继承环境变量**：
    1. 在 MCP 客户端配置中显式传入 `env`（参考 `mcp_config_examples.json`）。

## 📂 项目结构

```text
SUMO-MCP-Server/
├── doc/
│   ├── API.md             # MCP 工具 API 参考（英文）
│   ├── API_CN.md          # MCP 工具 API 参考（中文）
│   ├── ARCHITECTURE.md    # 架构说明
│   ├── RL.md              # RL 指南
│   └── sumo-mcp.jpg       # 项目图片
├── src/
│   ├── server.py           # v0.1 兼容入口 shim
│   └── sumo_mcp/           # v0.2 package: server/catalog/jobs/sessions/rl/resources
├── skills/                 # SUMO-MCP skills 源和安装脚本
├── pyproject.toml          # 项目配置与依赖管理
├── requirements.lock       # 锁定依赖版本
├── CHANGELOG.md            # 变更日志
├── README.md               # 项目文档（英文）
└── README_CN.md            # 项目文档（中文）
```

## 📄 许可证

MIT License

## 📣 媒体支持

感谢以下媒体平台对项目的支持：

- BigTrans 公众号 - [重磅开源！SUMO-MCP让大模型助力交通仿真](https://mp.weixin.qq.com/s/fJ_W0zEQlgA-1bAfmjki-A)

## 贡献者 ✨

<table>
  <tr>
    <td align="center">
      <a href="https://github.com/2217173240">
        <img src="https://github.com/2217173240.png?size=100" width="100px;" alt=""/><br />
        <sub><b>2217173240</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/gateblues">
        <img src="https://github.com/gateblues.png?size=100" width="100px;" alt=""/><br />
        <sub><b>gateblues</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/Hiners">
        <img src="https://github.com/Hiners.png?size=100" width="100px;" alt=""/><br />
        <sub><b>Hiners</b></sub>
      </a>
    </td>
    <td align="center">
      <a href="https://github.com/Zpzp1997">
        <img src="https://github.com/Zpzp1997.png?size=100" width="100px;" alt=""/><br />
        <sub><b>Zpzp1997</b></sub>
      </a>
    </td>
  </tr>
</table>
