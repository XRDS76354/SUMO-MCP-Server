# SUMO-MCP v0.2 Architecture

SUMO-MCP v0.2 keeps the public MCP tool surface compact and moves complexity
into internal layers.

```text
MCP host
  |
FastMCP server (`sumo_mcp.server`)
  |
  +-- models: structured result envelope and error codes
  +-- catalog: curated + runtime SUMO command whitelist
  +-- execution: stdout-safe subprocess runner and artifact inference
  +-- jobs: persistent long-running job manifests and process-tree cancel
  +-- sessions: label-based online TraCI sessions
  +-- mcp_tools: v0.1-compatible wrappers
  +-- workflows: compact high-level simulation/signal/RL workflows
  +-- analysis: streaming SUMO output parsers
  +-- rl: preflight, run manifests, QL/SB3 training, evaluate/compare
  +-- resources: MCP resources, guides, prompts, and diagnostics
```

## Public Contract

- 16 MCP tools are registered.
- v0.1 names remain available.
- All tools return the v0.2 envelope.
- New capability should normally be added as tool actions, resources, prompts,
  or catalog entries rather than new tools.

## Command Safety

`run_sumo_binary` and `run_sumo_tool` execute only commands resolved from the
catalog whitelist. Arguments are passed as argv lists with no shell. GUI tools
are blocked unless `SUMO_MCP_ALLOW_GUI=1` is set.

## Long Jobs

`sumo_mcp.jobs` persists every background job under `SUMO_MCP_JOBS_DIR` or
`./sumo_mcp_jobs`. Job manifests include command, pid/pgid, status, timestamps,
request echo, and result/log files. Cancellation kills the process tree on
macOS/Linux and Windows.

## Online Sessions

Online simulation uses named sessions so multiple simulations can be controlled
without colliding with the legacy global connection. Tools still preserve old
global behavior when no session is provided.

## RL Layer

RL runs create `config.json`, `manifest.json`, `metrics.csv`, `checkpoints/`,
and `tensorboard/`. `ql` and `pettingzoo-independent-ql` use independent
Q-table learners. `dqn`, `ppo`, and `a2c` use Stable-Baselines3 single-TLS
trainers when `sumo-mcp[rl]` is installed.

## Knowledge Layer

Resources expose diagnostics, the tool catalog, command catalog, workflow
guides, RL guidance, troubleshooting, and job details. Prompts encode common
agent workflows without expanding the tool surface.

