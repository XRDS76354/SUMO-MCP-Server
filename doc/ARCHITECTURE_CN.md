# SUMO-MCP v0.2 架构

v0.2 保持 MCP 工具面紧凑，把复杂度下沉到内部模块。

```text
MCP host
  |
FastMCP server (`sumo_mcp.server`)
  |
  +-- models: 结构化返回信封和错误码
  +-- catalog: curated + runtime SUMO 命令白名单
  +-- execution: stdout-safe 子进程执行器和 artifact 推断
  +-- jobs: 长任务 manifest、状态和进程树取消
  +-- sessions: 命名在线 TraCI session
  +-- mcp_tools: v0.1 兼容 wrapper
  +-- workflows: 仿真/信号/RL 高层工作流
  +-- analysis: SUMO 输出流式解析
  +-- rl: 预检、run manifest、QL/SB3 训练、评估/对比
  +-- resources: MCP resources、guides、prompts、diagnostics
```

## 公共契约

- 注册 16 个 MCP tools。
- 保留 v0.1 工具名。
- 所有工具返回 v0.2 envelope。
- 新能力优先通过 action、resource、prompt 或 catalog entry 扩展，而不是增加工具数。

## 命令安全

`run_sumo_binary` 和 `run_sumo_tool` 只能执行 catalog 白名单中的命令。
参数以 argv list 传入，不走 shell。GUI 工具默认阻断，除非设置
`SUMO_MCP_ALLOW_GUI=1`。

## 长任务

`sumo_mcp.jobs` 把后台 job 持久化到 `SUMO_MCP_JOBS_DIR` 或
`./sumo_mcp_jobs`。manifest 包含 command、pid/pgid、状态、时间戳、请求回显、
结果和日志。取消时会杀进程树。

## 在线 session

在线仿真使用命名 session，避免多个仿真实例互相覆盖；未提供 session 时保留旧全局连接行为。

## RL 层

RL run 会创建 `config.json`、`manifest.json`、`metrics.csv`、`checkpoints/`
和 `tensorboard/`。`ql` 与 `pettingzoo-independent-ql` 使用独立 Q-table；
`dqn`、`ppo`、`a2c` 在安装 `sumo-mcp[rl]` 后使用 SB3 单信号灯训练器。

## 知识层

resources 暴露 diagnostics、工具目录、命令目录、工作流指南、RL 指南、
排障指南和 job 详情。prompts 编码常见 agent 工作流，同时不增加工具数量。

