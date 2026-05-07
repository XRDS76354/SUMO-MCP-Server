# SUMO-MCP: MCP Server for SUMO Traffic Simulation (LLM-Oriented)

[中文文档](README_CN.md)

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
    <a href="doc/API.md"><img src="https://img.shields.io/badge/API-Docs-blue" alt="API Docs" /></a>
    <img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey" alt="Platform" />
  </p>
</div>

SUMO-MCP is a middleware layer connecting Large Language Models (LLMs) with [Eclipse SUMO](https://www.eclipse.org/sumo/) traffic simulation. Through [Model Context Protocol (MCP)](https://modelcontextprotocol.io/), AI agents (such as Claude, Cursor, and TRAE) can directly call SUMO capabilities for end-to-end automation across **OpenStreetMap data retrieval**, **network generation**, **demand modeling**, **simulation execution**, and **signal optimization**.

The system supports both **offline workflows** (file-based pipelines) and **online interaction** (real-time TraCI control), covering use cases from macroscopic planning to microscopic control.

API reference: `doc/API.md` (the single source of truth remains tool registration in `src/server.py`).
ezdesignX conversion guide: [doc/EZDESIGNX_TO_SUMO.md](doc/EZDESIGNX_TO_SUMO.md).

## Core Features

### 1. Unified Toolchain
Core MCP interfaces are grouped into intuitive tools to simplify common SUMO operations:

![SUMO-MCP Tool List](doc/sumo-mcp工具列表.png)

- **Network Management (`manage_network`)**: Generate networks (`generate`), download OSM data (`download_osm`), convert formats (`convert`), and convert ezdesignX v1 JSON/JSONC (`convert_ezdesignx`). A dedicated `convert_ezdesignx_network` tool is also available.
- **Demand Management (`manage_demand`)**: Generate random trips (`generate_random`), convert OD matrices (`convert_od`), and compute routes (`compute_routes`).
- **Signal Optimization (`optimize_traffic_signals`)**: Includes cycle adaptation (`cycle_adaptation`) and coordination (`coordination`). `cycle_adaptation` outputs SUMO `<additional>` signal plans (automatically mounted into `<additional-files>` by workflows).
- **Simulation & Analysis**: Run standard config-based simulation (`run_simple_simulation`) and FCD trajectory analysis (`run_analysis`).

Some aggregated tools accept `params.options: list[str]`, which are appended token-by-token to underlying SUMO binaries/scripts (see "General Conventions" in `doc/API.md`).

### 2. Online Interaction
Real-time control via TraCI enables fine-grained closed-loop operations:

- **Simulation Control (`control_simulation`)**: Connect (`connect`), step (`step`), and cleanly disconnect (`disconnect`).
- **State Query (`query_simulation_state`)**: Fetch active vehicle IDs (`vehicle_list`), per-vehicle variables (`vehicle_variable`), and global simulation statistics.

### 3. Automated Workflows
Built-in end-to-end workflows (`run_workflow`) for research and engineering tasks:

- **Sim Gen & Eval (`sim_gen_eval`)**: One-shot pipeline: "generate network -> generate demand -> route computation -> simulation -> analysis".
  - Params: `grid_number` (aliases: `grid_size`, `size`), `sim_seconds` (aliases: `steps`, `duration`, `end_time`), `output_dir`
- **Signal Optimization (`signal_opt`)**: Full pipeline: "baseline simulation -> optimization -> optimized simulation -> comparison" with automatic handling of `<additional>` outputs.
  - Params: `net_file` (required), `route_file` (required), `sim_seconds` (aliases: `steps`, `duration`), `use_coordinator`, `output_dir`
- **RL Training (`rl_train`)**: Reinforcement learning training for built-in scenarios. For custom network training, use `manage_rl_task/train_custom` (based on [sumo-rl](https://github.com/LucasAlegre/sumo-rl); network must contain traffic lights; explicitly setting `SUMO_HOME` is recommended).
  - Params: `scenario_name` (alias: `scenario`), `episodes` (alias: `num_episodes`), `steps` (alias: `steps_per_episode`), `output_dir`

For detailed parameters and examples, see [API documentation](doc/API.md).

---

## Requirements

- **OS**: Windows / Linux / macOS
- **Python**: 3.10+
- **SUMO**: [Eclipse SUMO](https://www.eclipse.org/sumo/) (`SUMO_HOME` recommended; SUMO binaries should be available in `PATH`)

### Python Dependencies

Runtime dependencies (required for all MCP tools):
- `mcp[cli]>=1.0.0`
- `sumolib>=1.20.0`
- `traci>=1.20.0`
- `sumo-rl>=1.4.3`
- `pandas>=2.0.0`
- `requests>=2.31.0`

Development dependencies (optional):
- `mypy>=1.8.0`
- `flake8>=7.0.0`
- `pytest>=8.0.0`
- `psutil>=5.9.0`
- `types-*`

On Windows, `./install_deps.ps1 -NoDev` installs runtime dependencies only.

---

## Installation

### 1. Get the Code

Option A: clone from GitHub (recommended)
```bash
git clone https://github.com/XRDS76354/SUMO-MCP-Server.git
cd sumo-mcp
```

Option B: download ZIP
1. Visit the [GitHub repository](https://github.com/XRDS76354/SUMO-MCP-Server).
2. Click **Code** -> **Download ZIP**.
3. Extract and enter the project folder.

Option C: install as dependency (WIP)
```bash
pip install git+https://github.com/XRDS76354/SUMO-MCP-Server.git
```

### 2. Install and Configure SUMO

This project depends on [Eclipse SUMO](https://www.eclipse.org/sumo/).

Important notes:
- If you only use SUMO binaries (`sumo`, `netconvert`, `netgenerate`, `duarouter`, `od2trips`, ...), make sure they are in `PATH`.
- If you use SUMO tool scripts (`randomTrips.py`, `osmGet.py`, `tls*.py`, ...), ensure `<SUMO_HOME>/tools` is discoverable. Setting `SUMO_HOME` to your SUMO install directory and adding `$SUMO_HOME/bin` to `PATH` is recommended.

Platform-specific setup:
- **Windows**
  1. Install SUMO using the official installer ([docs](https://sumo.dlr.de/)).
  2. Set environment variables (example):
     - CMD: `setx SUMO_HOME "C:\Program Files\Eclipse\sumo"`, `setx PATH "%SUMO_HOME%\bin;%PATH%"`
     - PowerShell: `$env:SUMO_HOME="C:\Program Files\Eclipse\sumo"; $env:PATH="$env:SUMO_HOME\bin;$env:PATH"`
  3. Verify: `sumo --version`
- **Linux (Ubuntu/Debian)**
  1. Install: `sudo apt-get install sumo sumo-tools`
  2. Optional but recommended for tools scripts: `export SUMO_HOME=/usr/share/sumo` and add `$SUMO_HOME/bin` to `PATH`
  3. Verify: `sumo --version`
- **macOS (Homebrew)**
  1. Install: `brew install sumo`
  2. Homebrew usually exposes `sumo` in `PATH`; for tools scripts, set `SUMO_HOME` to `.../share/sumo` (for example `/usr/local/share/sumo` or `/opt/homebrew/share/sumo`)
  3. Verify: `sumo --version`

For more details, see [SUMO official docs](https://sumo.dlr.de/docs/).

### 3. Python Environment

#### Windows one-click installation

Use the built-in scripts to create `.venv` and install dependencies (default includes `.[dev]`).

Option A: PowerShell (recommended)
```powershell
.\install_deps.ps1

# Optional
.\install_deps.ps1 -NoDev
.\install_deps.ps1 -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
```

Option B: CMD
```bat
install_deps.bat

REM Optional
install_deps.bat -NoDev
install_deps.bat -IndexUrl https://pypi.tuna.tsinghua.edu.cn/simple
```

The scripts will:
- Validate Python 3.10+
- Create `.venv` if missing
- Upgrade pip/setuptools/wheel
- Install project dependencies in editable mode

#### Option 1: use uv (recommended)

```bash
# 1. Install uv
pip install uv

# 2. Sync dependencies
uv sync

# 3. Activate environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate
```

#### Option 2: Conda + pip

```bash
# 1. Create and activate conda env
conda create -n sumo-mcp python=3.10 -y
conda activate sumo-mcp

# 2. Install dependencies
pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple

# Runtime-only alternative:
pip install -r requirements.txt
```

---

## Start and Configure

### 1. Run Locally (for testing)

The server is implemented with `mcp.server.fastmcp.FastMCP` and communicates over stdio using JSON-RPC 2.0.

Start directly with Python:

```bash
python src/server.py
```

Or use provided startup scripts:
- Linux/macOS: `./start_server.sh`
- Windows (PowerShell): `.\start_server.ps1`
- Windows (CMD): `start_server.bat`

### 2. MCP Host Configuration (critical)

When configuring in host apps (Claude Desktop, Trae, Cursor), always use absolute paths.

A. Find required paths
- Python executable
  - Windows (PowerShell): `(Get-Command python).Source`
  - Linux/macOS: `which python`
- `SUMO_HOME`
  - Windows: `echo %SUMO_HOME%`
  - Linux/macOS: `echo $SUMO_HOME`

B. Example host config (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "sumo-mcp": {
      "command": "/path/to/your/env/python",
      "args": ["/path/to/sumo-mcp/src/server.py"],
      "env": {
        "SUMO_HOME": "/your/actual/sumo/path",
        "PYTHONPATH": "/path/to/sumo-mcp/src"
      }
    }
  }
}
```

Important:
1. Replace `command` with the absolute path of your Python interpreter.
2. Replace `args` with the absolute path of `src/server.py`.
3. Explicitly setting `SUMO_HOME` and `PYTHONPATH` helps avoid `ModuleNotFoundError` and environment mismatch issues.

More config samples: `mcp_config_examples.json`.

---

## Prompt Examples

In any MCP-enabled AI assistant, try prompts like:

- Workflow task:

  > "Generate a 3x3 grid network, simulate 100 seconds, and report the average speed."
  > *(Likely calls `run_workflow("sim_gen_eval", {"grid_number": 3, "sim_seconds": 100})`)*

- Online interaction task:

  > "Start simulation for this config and report vehicle speed for ID `v_0` each step. Alert me if speed drops below 5 m/s."
  > *(Likely calls `control_simulation` + `query_simulation_state`)*

- RL task:

  > "List built-in RL scenarios and train a simple intersection for 5 episodes."
  > *(Likely calls `manage_rl_task("list_scenarios")` + `run_workflow("rl_train", {"scenario_name": "...", "episodes": 5})`)*

- Complex integrated scenario:

  > "Use sumo-mcp to generate a 4x4 grid network where all nodes are intersections, spacing 100m, with traffic lights at every intersection. Generate 200 vehicles, run a 1000-second simulation with trajectory recording, then compute average speed for all vehicles over the whole simulation and report it with 2 decimal places."

  Typical execution flow:
  1. `manage_network(action="generate", output_file="grid.net.xml", params={"grid": true, "grid_number": 4})`
  2. `manage_demand(action="random_trips", net_file="grid.net.xml", output_file="trips.xml", params={"end_time": 1000, "period": 5.0})`
  3. `run_workflow("sim_gen_eval", {"grid_number": 4, "sim_seconds": 1000, "output_dir": "results"})` (or compose online calls manually)
  4. `run_analysis(fcd_file="results/fcd.xml")`

---

## Troubleshooting

- Cannot find `sumo` (for example: `Error: Could not locate SUMO executable ('sumo').`)
  1. Run `sumo --version` in terminal.
  2. If unavailable, add SUMO `bin/` to `PATH`, or set `SUMO_HOME` and add `$SUMO_HOME/bin` to `PATH`.

- Cannot find SUMO tools scripts (`randomTrips.py`, `osmGet.py`, `tls*.py`)
  1. Ensure `SUMO_HOME` points to the SUMO installation directory.
  2. Ensure `<SUMO_HOME>/tools` exists and includes required scripts.

- MCP call hangs or host shows `undefined`
  1. Communication is JSON-RPC over stdio; non-JSON stdout from child processes can corrupt transport.
  2. Upgrade to latest version (TraCI SUMO stdout isolation is included), or ensure child-process stdout is captured/redirected.

- MCP client does not inherit environment variables
  1. Pass explicit `env` in your MCP host config (`mcp_config_examples.json`).

## Project Structure

```text
sumo-mcp/
├── doc/
│   ├── API.md              # MCP tool API reference (English)
│   ├── API_CN.md           # MCP tool API reference (Chinese)
│   └── sumo-mcp.jpg        # Project image
├── src/
│   ├── server.py           # MCP server entry (FastMCP, aggregated interfaces)
│   ├── utils/              # Common utilities
│   │   ├── connection.py   # TraCI connection manager
│   │   ├── output.py       # Output helpers
│   │   ├── sumo.py         # SUMO config helpers
│   │   ├── timeout.py      # Timeout helpers
│   │   └── traci.py        # TraCI wrappers
│   ├── mcp_tools/          # Core tool modules
│   │   ├── analysis.py     # Analysis tools
│   │   ├── network.py      # Network tools
│   │   ├── route.py        # Routing tools
│   │   ├── signal.py       # Signal tools
│   │   ├── simulation.py   # Simulation control tools
│   │   ├── vehicle.py      # Vehicle tools
│   │   └── rl.py           # Reinforcement learning tools
│   ├── resources/          # Resource files
│   └── workflows/          # Automated workflows
│       ├── sim_gen.py      # Simulation generation workflow
│       ├── signal_opt.py   # Signal optimization workflow
│       └── rl_train.py     # RL training workflow
├── pyproject.toml          # Project config and dependencies
├── requirements.lock       # Locked dependency versions
├── README.md               # Project documentation (English)
└── README_CN.md            # Project documentation (Chinese)
```

## License

MIT License

## Media Support

Thanks to the following media platform for coverage:

- BigTrans WeChat Official Account - [重磅开源！SUMO-MCP让大模型助力交通仿真](https://mp.weixin.qq.com/s/fJ_W0zEQlgA-1bAfmjki-A)

## Contributors

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
