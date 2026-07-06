# Changelog

## v0.2.0

### Changed

- Upgraded public tool returns from v0.1 strings to structured envelopes.
  Human-readable text remains in `summary`.
- Kept all v0.1 tool names and ezdesignX conversion capability.
- Locked the public MCP tool surface to 16 tools.

### Added

- SUMO command catalog with curated tier-1 binaries/tools and runtime tier-3
  discovery under `$SUMO_HOME/tools`.
- Safe `run_sumo_binary` and `run_sumo_tool` wrappers with argv-list execution,
  GUI blocking, output artifact inference, and background mode.
- Persistent job manager with status/result/logs/cancel/list actions.
- Label-based online simulation sessions and session-aware state queries.
- Streaming `analyze_sumo_output` for large SUMO XML outputs.
- RL preflight, run manifests, background training jobs, checkpoints, resume,
  evaluation, and trained-vs-fixed comparison.
- Q-learning, PettingZoo-named independent Q-learning, and optional
  Stable-Baselines3 DQN/PPO/A2C single-TLS trainers.
- MCP resources, prompts, and SUMO-MCP skills source/install script.
- Three-platform CI for no-SUMO tests and real-SUMO integration tiers.

### Migration Notes

- Existing clients that treated a tool response as plain text should read
  `summary` from the returned object.
- Failures should be detected with `ok=false` and `error.code` rather than by
  parsing string prefixes.
- Long-running operations may return `job_id`; poll `manage_sumo_jobs` or
  `manage_rl_task(action="status")`.

