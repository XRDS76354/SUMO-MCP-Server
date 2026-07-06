# v0.2 剩余工作规格（阶段⑤⑥⑦）

> 状态：阶段⑤、阶段⑥、阶段⑦已在 `v0.2-dev` 分支完成并提交。本文作为实施与审查追溯清单保留，不再表示当前仍有同名剩余工作。

> 交接文档：由 codex 实施，Claude 审查。基线 = `v0.2-dev` 分支 commit `57efa3c`。
> 全局验收门槛（每阶段必须满足，审查第一时间检查）：
> 1. `pytest tests/` 全绿（当前 163 个，只增不减）；
> 2. `flake8 src tests` 零违规（.flake8 已配置，max-line-length=120）；
> 3. 新增模块过 `mypy --follow-imports=silent <新文件>` strict；
> 4. **16 工具面不得增减**——`tests/protocol/test_stdio_handshake.py` 锁定了工具数，新能力一律并入现有工具的 action；
> 5. v0.1 契约不动：`tests/unit/test_tool_contracts.py` 与 `test_legacy_failure_detection.py` 是红线，改动它们的断言=破坏兼容，审查直接打回；
> 6. 所有子进程不得污染 stdout（MCP stdio 安全）；错误一律返回 `ok=false` 信封（`sumo_mcp/models.py` 的 `make_error`），不得抛异常出工具函数。

---

## 已完成基座（codex 需要了解的现状）

- `sumo_mcp/models.py`：统一信封 `{ok, tool, summary, action?, data?, artifacts?, metrics?, command?, stdout_tail?, stderr_tail?, warnings?, error{code,message,remediation}?, job_id?}` + `ErrorCode` 13 个稳定错误码 + `legacy_result()`（v0.1 字符串按失败串全集自动分类）。
- `sumo_mcp/catalog/`：命令注册表（14 二进制 + ~55 精选脚本 tier1 + 运行时发现 tier3），`resolve_command` 白名单/路径围栏，`describe_command` --help 缓存。
- `sumo_mcp/execution/runner.py`：`run_cli(kind, name, args, *, cwd, timeout_s, expected_outputs)` 安全执行器（argv 不走 shell、flag 黑名单、GUI 守卫 `SUMO_MCP_ALLOW_GUI`、进程树击杀、artifact 推断）。
- `sumo_mcp/jobs/manager.py`：`job_manager` 单例。**`start_callable_job(fn, label, request)` 就是为 RL 训练预留的**——fn 收到 `threading.Event`（cancel 信号），返回 JSON-safe dict；manifest.json 原子落盘；重启后可见。
- `sumo_mcp/sessions/manager.py`：具名多会话 TraCI + `ALLOWED_CALLS` 白名单（8 域 60+ 方法）。
- `sumo_mcp/analysis/output.py`：`analyze_output(file_path, kind, max_elements)` 流式解析 summary/tripinfo/fcd/queue/emission。
- `sumo_mcp/server.py`：16 工具已接线。`manage_rl_task` 目前只有 v0.1 的 `list_scenarios` / `train_custom`（同步 QL 训练）。
- pyproject 已有 `[rl]` extras 骨架：`stable-baselines3>=2.3.0, torch>=2.0.0, tensorboard>=2.15.0, supersuit>=3.9.0, pettingzoo>=1.24.0`；`[rllib]`：`ray[rllib]>=2.9.0`。版本可按实测兼容性调整，但必须在 PR 里说明理由。

---

## 阶段⑤ RL 子系统（工作量最大，优先级最高）

### 目标
manage_rl_task 从"只能同步跑 QL"升级为"可训练、可评估、可迭代"的完整 RL 实验平台。

### 新建模块（建议结构）
```
src/sumo_mcp/rl/
├── __init__.py
├── preflight.py      # 训练前预检
├── runs.py           # 实验目录规范 + RunManifest
├── envs.py           # sumo-rl 环境构建封装（单/多智能体、无头、种子）
├── trainers/
│   ├── __init__.py   # ALGORITHMS 注册表 {"ql": ..., "dqn": ..., "ppo": ..., "a2c": ...}
│   ├── base.py       # Trainer 协议：train(cancel_event) -> result dict / resume / evaluate
│   ├── ql.py         # 迁移现有 mcp_tools/rl.py 的 QLAgent 逻辑 + Q 表 pickle 序列化(续训用)
│   └── sb3.py        # DQN/PPO/A2C（依赖缺失时报 DEPENDENCY_MISSING）
├── multi_agent.py    # PettingZoo parallel_env + 每交叉口独立学习器
└── evaluation.py     # 策略 vs 固定配时基线对比
```

### 关键需求逐条

**R1 预检 `preflight.py`（必须先做，所有训练入口调用）**
`validate_rl_environment(net_file, route_file, params) -> dict`，检查项（每项返回 `{check, passed, detail}`）：
1. SUMO_HOME 已设或可推导（`find_sumo_home`）；
2. `sumo` 二进制可用；
3. `sumo_rl` 可 import（注意它 import 时就要求 SUMO_HOME——需先设好再 import，参考现有 `mcp_tools/rl.py` 的懒加载模式）；
4. net_file/route_file 存在且 XML 可解析；
5. **net 里存在 trafficlight 节点**（解析 `.net.xml` 的 `<tlLogic>`）——无 TLS 训练必失败，v0.1 只能在跑挂后才知道；
6. route 文件有车（`<vehicle>`/`<flow>`/`<trip>` 至少一个）；
7. `delta_time > yellow_time`（sumo-rl 的硬约束，默认 delta_time=5, yellow_time=2；用户传参时校验）；
8. 若 algorithm 属于 SB3 系，检查 `stable_baselines3`/`torch` 可 import，缺失返回 `DEPENDENCY_MISSING` + remediation "pip install sumo-mcp[rl]"。
返回 `{ok: 全过, checks: [...], summary}`。

**R2 实验目录规范 `runs.py`**
每次训练一个 run 目录：`<out_dir>/<run_id>/`（run_id = 时间戳+短uuid）：
```
config.json        # 全部超参+文件路径+种子+算法+sumo版本 —— 可复现的完整记录
checkpoints/       # QL: q_table_ep{N}.pkl；SB3: model_ep{N}.zip
metrics.csv        # sumo-rl 自带的 out_csv 或自行聚合（episode, total_reward, mean_waiting_time, ...）
tensorboard/       # 仅 SB3（tensorboard_log 参数）
final_model.(pkl|zip)
manifest.json      # RunManifest: run_id/algorithm/status/episodes_done/created_at/...
```
提供 `list_runs(out_dir)` / `load_run(run_dir)`。

**R3 训练器**
- `ql.py`：把 `mcp_tools/rl.py` 里 `run_rl_training` 的 QL 循环迁移过来（**原函数保留不删**，`train_custom` 旧路径继续用它保证兼容），新增：每 N episode 保存 Q 表 pickle；`resume` 从 checkpoint 加载 Q 表接着训。
- `sb3.py`：单智能体（网络只有 1 个 TLS 或用户指定 single-agent 模式）。`SumoEnvironment(single_agent=True)` 是标准 gymnasium env，直接喂 SB3 的 DQN/PPO/A2C。**不做 SAC**（动作空间离散，SAC 不适用——文档里说明）。`model.save/load` 支持 resume。`tensorboard_log` 指向 run 目录。
- `multi_agent.py`：sumo-rl 的 `parallel_env`（PettingZoo API），务实方案 = 每个 TLS 一个独立 QL/DQN 学习器（independent learners），不做集中式训练。SB3 多智能体可用 supersuit 的 `pettingzoo_env_to_vec_env_v1 + concat_vec_envs_v1` 包装成参数共享单模型（二选一实现，PR 里说明选择）。
- 所有训练循环必须：响应 `cancel_event`（每 episode 边界检查）、强制无头（不传 gui）、`seed` 参数贯穿（env reset + 算法 seed）、TraCI stdout 抑制（复用 `ensure_traci_start_stdout_suppressed`）。

**R4 训练必须走异步 job**
同步训练几小时会卡死 MCP 调用。`manage_rl_task(action="train")` 内部：
```python
info = job_manager.start_callable_job(
    lambda cancel: trainer.train(cancel), label=f"rl-train-{algorithm}", request={...})
```
立即返回 `{job_id, run_dir}` 信封。**建议训练在子进程而非线程里跑**（SB3/torch 与线程 + TraCI 全局态会互相干扰；且 cancel 需要能真正杀掉 SUMO 子进程）——可以用 `start_callable_job` 包一层 `subprocess.run([sys.executable, "-m", "sumo_mcp.rl.train_entry", config_json_path])` 的模式：写一个 `train_entry.py` CLI 入口读 config.json 跑训练。这同时天然解决 stdout 隔离。实现方式留给 codex 决定，但 PR 必须说明并发模型和取消语义。

**R5 评估 `evaluation.py`**
`evaluate(run_dir 或 model+env 参数, episodes=N)` 与 `compare(run_dir, episodes=N)`：
- 加载训好的策略跑 N episodes（确定性动作），聚合 mean_waiting_time / mean_queue / mean_speed / total_reward；
- 基线 = 同一网络的固定配时（不加载 RL 控制，直接 sumo 跑同样时长，用 `analyze_output` 解析 summary/tripinfo）；
- 输出对比 JSON（`comparison.json` 落 run 目录）+ metrics 进信封（`waiting_time_improvement_pct` 等）。

**R6 manage_rl_task 新 action（并入现有工具，签名 `(action, params)` 不变）**
| action | params | 行为 |
|---|---|---|
| `list_scenarios` | — | 不变（v0.1） |
| `train_custom` | 不变 | 不变（v0.1 同步 QL，向后兼容） |
| `list_algorithms` | — | 返回可用算法及依赖状态（ql 恒可用；dqn/ppo/a2c 标注 [rl] extras 是否装了） |
| `validate_env` | net_file/route_file 或 scenario, 训练参数 | R1 预检报告 |
| `train` | scenario 或 net+route, algorithm, episodes, steps, seed?, reward_type?, delta_time?, yellow_time?, out_dir?, hyperparams?{} | 预检→异步 job→返回 job_id+run_dir |
| `resume` | run_dir, episodes | 从最新 checkpoint 续训（异步 job） |
| `status` | job_id 或 run_dir | 训练进度（manifest + metrics.csv 尾部） |
| `stop` | job_id | 取消训练 job |
| `evaluate` | run_dir, episodes? | R5 评估（可同步，几分钟内） |
| `compare` | run_dir, episodes? | R5 基线对比 |
| `list_runs` | out_dir? | 实验列表 |
docstring 全部更新；错误路径全走 `make_error`。

**R7 测试**
- unit（无 SUMO/torch，mock）：preflight 每个检查项的真/假分支；runs 目录规范/manifest 读写；ALGORITHMS 注册表；依赖缺失时 sb3 trainer 返回 DEPENDENCY_MISSING；manage_rl_task 新 action 的参数校验与信封形状。
- integration（`requires_sumo`）：validate_env 对真实 grid 网络（有/无 TLS 两种，netgenerate `--default-junction-type traffic_light` 造有 TLS 的）。
- rl-smoke（`requires_rl`）：QL train 2 episodes × 50 steps 走 job 化路径（起 job→轮询 status→succeeded→run 目录有 config.json/metrics.csv/checkpoint）；evaluate 1 episode 出对比数字。**CI 的 rl-smoke job 已存在（仅 ubuntu），确保这些测试在它里面能跑完 <10 分钟**。
- SB3 冒烟标 `requires_rl` + 检测 `stable_baselines3` 可 import 才跑（conftest 的 `_rl_available` 可扩展）；CI 不装 torch 就跳过，本地可验。

### 审查重点（我会查）
- 训练 job 的取消是否真能杀掉 SUMO 进程（不留孤儿）；
- config.json 是否记录全部可复现信息（含 sumo 版本、sumo-rl 版本、种子）；
- `train_custom` 旧路径行为是否与 v0.1 逐位一致；
- reward_type 透传是否正确（sumo-rl 的 reward_fn 参数）；
- Windows 上 torch/multiprocessing 的坑是否有规避说明。

---

## 阶段⑥ MCP 知识层（resources + prompts + skills）

### R8 MCP resources（FastMCP `@server.resource(uri)` 装饰器）
| URI | 内容 | 来源 |
|---|---|---|
| `sumo://diagnostics` | get_sumo_info 的 data + catalog 可用性统计 + [rl] extras 状态 | 动态生成 |
| `sumo://tool-catalog` | 16 工具一览（名称/职责/何时用哪个），紧凑 markdown | 静态字符串或从 docstring 生成 |
| `sumo://commands` | catalog tier1 命令表（name/category/description） | `list_commands(tier=1)` 动态 |
| `sumo://guide/tool-selection` | 决策树：建网→manage_network 或 run_sumo_binary(netgenerate)；需求→manage_demand；在线控制→control_simulation；长任务→background+jobs；RL→manage_rl_task | 静态 markdown |
| `sumo://guide/workflows` | 典型工作流菜谱：从零建仿真/OSM导入/信号优化/RL训练评估迭代，每步给出具体工具调用示例（JSON 参数） | 静态 markdown |
| `sumo://guide/rl-training` | 算法选择（QL 快速验证/DQN 单交叉口/PPO 多智能体）、超参建议、reward 类型说明、常见失败（无TLS/需求太稀/delta_time）与排查 | 静态 markdown |
| `sumo://guide/troubleshooting` | SUMO_NOT_FOUND/GUI_BLOCKED/TIMEOUT/DEPENDENCY_MISSING 等每个错误码的处置手册 | 静态 markdown |
| `sumo://jobs/{job_id}` | job manifest+result（resource template） | `job_manager` 动态 |
静态 markdown 放 `src/sumo_mcp/resources/content/*.md`（包数据，hatch 打包要包含），加载用 `importlib.resources`。

### R9 MCP prompts（FastMCP `@server.prompt()`）
4-6 个：`build-simulation-from-scratch(区域大小, 时长)`、`import-osm-area(bbox)`、`optimize-signals(net, route)`、`rl-train-and-evaluate(scenario/net, algorithm)`、`analyze-simulation-outputs(output_dir)`。每个 prompt 返回引导 agent 按正确工具序列执行的用户消息模板。

### R10 skills 双适配
- 源：`skills/src/<skill-name>/SKILL.md`（唯一事实源，7 个技能：orchestrator/network-build/demand-routing/online-simulation/signal-optimization/output-analysis/rl-experiments——参考 `git show beta0.2:skills/codex/...` 的旧版改写，工具名对齐 v0.2 的 16 工具）;
- 生成脚本 `skills/install_skills.py --target claude|codex|both`：Claude Code → `.claude/skills/<name>/SKILL.md`（项目级）或 `~/.claude/skills/`；Codex → `~/.codex/skills/`。frontmatter 两边格式略有差异，脚本负责转换；
- manifest.json 更新。

### R11 测试
- resources：注册数量与 URI 清单断言；每个静态 guide 非空且引用的工具名都真实存在（防文档烂链——用 16 工具名单校验文中反引号内的工具名）；`sumo://jobs/{id}` 对不存在 id 的行为。
- prompts：注册清单 + 参数渲染冒烟。
- protocol：stdio `resources/list`、`prompts/list` 握手断言（扩展现有 test_stdio_handshake.py 模式，但**别动 16 工具数断言**）。
- skills：install_skills.py --target both 到 tmp 目录，验证两种布局生成。

---

## 阶段⑦ 文档与仓库卫生（收尾）

### R12 文档
- `doc/API.md` + `doc/API_CN.md` 重写：16 工具逐个——签名/参数表/action 枚举/返回信封示例/典型调用 JSON。**中英内容必须逐节对应**（审查会抽查 diff 结构）。可写 `scripts/generate_api_docs.py` 从 docstring 生成骨架（beta0.2 有类似脚本可参考 `git show beta0.2:scripts/generate_api_docs.py`），但人工润色后的成品入库即可，不强制全自动。
- `README.md`/`README_CN.md`：v0.2 特性总览、安装（pip install -e . / [rl] extras / uvx）、三种启动方式、快速上手（一个从零到仿真的完整对话示例）、16 工具速查表。
- 新增 `doc/RL_TRAINING.md` + `_CN.md`：算法矩阵、run 目录规范、训练→评估→续训迭代闭环教程、超参说明。
- 新增 `doc/ARCHITECTURE.md`：分层图（models/catalog/execution/jobs/sessions/analysis/rl）+ 各层职责。
- 新增 `CHANGELOG.md`：v0.2.0 完整条目（含"返回格式从字符串升级为结构化信封"的迁移说明——v0.1 客户端读返回文本的要改读 `summary` 字段）。
- `mcp_config_examples.json`：补 claude desktop / claude code / codex / cursor 四客户端配置，含 `uvx --from git+https://github.com/XRDS76354/SUMO-MCP-Server sumo-mcp` 方式与 `sumo-mcp` console script 方式。

### R13 仓库卫生
- 删根目录 `routes.rou.xml`（git rm）；
- `.gitignore` 补 `sumo_mcp_jobs/`（阶段④ job 目录）；
- `doc/` 里两张 PNG 若过期（工具列表变了）标注或移除引用；
- `install_deps.{ps1,bat}` 与 `start_server.*` 核对 v0.2 仍然工作（路径没变，应该不用改，验证即可）；
- `requirements.lock` 用 `uv pip compile pyproject.toml -o requirements.lock` 重新生成。

### R14 最终全量验证（提交前必跑，结果写进 PR 描述）
```
pytest tests/                          # 全绿
flake8 src tests                       # 零违规
mypy src/sumo_mcp --follow-imports=silent  # 新模块 strict（存量 utils/ezdesignx 的历史债不要求清）
python src/server.py       ← stdio initialize 握手
python -m sumo_mcp         ← 同上
pip install -e . && sumo-mcp  ← 同上
```

---

## 实施顺序建议
⑤ → ⑥ → ⑦ 串行，每阶段一个 commit（格式参考 git log 现有中文 commit 风格），阶段⑤ 可拆 2-3 个 commit（rl 模块 / job 化接线 / 测试）。**每阶段完成后停下来等审查**，不要一口气做完。
