# SUMO-MCP Troubleshooting

- `SUMO_NOT_FOUND`: install Eclipse SUMO, set `SUMO_HOME`, and ensure binaries
  such as `sumo`, `netconvert`, and `duarouter` are on PATH.
- `DEPENDENCY_MISSING`: install Python extras. For advanced RL, use
  `pip install -e ".[rl]"`.
- `INVALID_ARGUMENT`: check action names, required params, integer fields, and
  argv lists. `run_sumo_binary` and `run_sumo_tool` require `args: list[str]`.
- `FILE_NOT_FOUND`: pass absolute paths when possible and verify generated
  artifacts exist before chaining tools.
- `VALIDATION_FAILED`: inspect preflight checks. RL commonly fails because of
  missing TLS, no green phases, empty demand, or unsupported SB3 multi-TLS scope.
- `GUI_BLOCKED`: prefer `sumo`, `netconvert`, and headless tools. Set
  `SUMO_MCP_ALLOW_GUI=1` only when a display is intentionally available.
- `TIMEOUT`: start the operation as a background job or raise `timeout_s`.
- `JOB_NOT_FOUND`: use `manage_sumo_jobs(action="list")` or
  `manage_rl_task(action="status")` with the correct `job_id`.
- `SESSION_NOT_FOUND`: reconnect with `control_simulation(action="connect")`.
