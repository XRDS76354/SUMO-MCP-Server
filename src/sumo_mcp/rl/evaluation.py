"""Evaluation helpers for saved Q-learning RL runs."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from sumo_mcp.models import ErrorCode
from sumo_mcp.rl.algorithms import INDEPENDENT_QL_ALGORITHMS, SB3_ALGORITHMS
from sumo_mcp.rl.checkpoints import CheckpointError, load_q_tables, state_to_key, validate_checkpoint_path
from sumo_mcp.rl.runs import load_config, load_run, update_run
from sumo_mcp.utils.sumo import find_sumo_home
from sumo_mcp.utils.traci import ensure_traci_start_stdout_suppressed


def _greedy_action(q_tables: Dict[str, Any], ts_id: str, state: Any) -> int:
    table = q_tables.get(ts_id, {})
    values = table.get(state_to_key(state)) if hasattr(table, "get") else None
    if not values:
        return 0

    def _score(idx: int) -> float:
        # Values loaded with decode_keys=False are raw JSON: numbers, or the
        # "Infinity"/"-Infinity"/"NaN" string tokens written for non-finite Q-values.
        # Coerce to float so argmax never mixes str and float (which raises TypeError).
        try:
            score = float(values[idx])
        except (TypeError, ValueError):
            return float("-inf")
        # Treat NaN as the worst option so it is never greedily selected.
        return float("-inf") if score != score else score

    return int(max(range(len(values)), key=_score))


def _make_env(config: Dict[str, Any], run_dir: str, *, single_agent: bool = False) -> Any:
    ensure_traci_start_stdout_suppressed()
    home = os.environ.get("SUMO_HOME") or find_sumo_home()
    if home:
        os.environ.setdefault("SUMO_HOME", home)
    from sumo_rl import SumoEnvironment

    kwargs: Dict[str, Any] = {
        "net_file": str(config["net_file"]),
        "route_file": str(config["route_file"]),
        "out_csv_name": str(Path(run_dir) / "evaluation"),
        "use_gui": False,
        "num_seconds": int(config.get("steps_per_episode", 1000)),
        "delta_time": int(config.get("delta_time", 5)),
        "yellow_time": int(config.get("yellow_time", 2)),
        "reward_fn": str(config.get("reward_type", "diff-waiting-time")),
        "single_agent": single_agent,
        "sumo_warnings": False,
    }
    seed = config.get("seed")
    if seed is not None and seed != "":
        kwargs["sumo_seed"] = int(seed)
    return SumoEnvironment(**kwargs)


_INFO_METRICS = (
    "system_total_waiting_time",
    "system_mean_waiting_time",
    "system_total_stopped",
    "system_mean_speed",
    "agents_total_stopped",
    "agents_total_accumulated_waiting_time",
)


def _record_info(samples: Dict[str, List[float]], info: Any) -> None:
    if not isinstance(info, dict):
        return
    for key in _INFO_METRICS:
        value = info.get(key)
        if isinstance(value, (int, float)):
            samples.setdefault(key, []).append(float(value))


def _mean(values: List[float]) -> float:
    return sum(values) / max(1, len(values))


def _add_info_metrics(metrics: Dict[str, Any], samples: Dict[str, List[float]]) -> None:
    for key, values in samples.items():
        if values:
            metrics[f"mean_{key}"] = _mean(values)


def _load_sb3_model_class(algorithm: str) -> Type[Any]:
    try:
        from stable_baselines3 import A2C, DQN, PPO
    except ImportError as exc:
        raise RuntimeError("stable-baselines3 and torch are required; install sumo-mcp[rl]") from exc

    mapping: Dict[str, Type[Any]] = {"dqn": DQN, "ppo": PPO, "a2c": A2C}
    return mapping[algorithm]


def _manifest_checkpoint_set(manifest: Dict[str, Any]) -> set[str]:
    paths: set[str] = set()
    for key in ("latest_checkpoint", "final_model"):
        value = manifest.get(key)
        if isinstance(value, str) and value:
            paths.add(str(Path(value).expanduser().resolve()))
    return paths


def _validate_manifest_checkpoint(
    run_dir: str,
    checkpoint: str,
    manifest: Dict[str, Any],
    *,
    algorithm: str,
    suffix: str,
) -> str:
    path = validate_checkpoint_path(run_dir, checkpoint, suffix=suffix)
    resolved = str(Path(path).expanduser().resolve())
    if resolved not in _manifest_checkpoint_set(manifest):
        raise CheckpointError(
            ErrorCode.INVALID_ARGUMENT,
            "SB3 checkpoints must match the server-recorded run manifest checkpoint.",
        )
    expected_name = f"{algorithm}_model{suffix}"
    if Path(path).name != expected_name:
        raise CheckpointError(
            ErrorCode.INVALID_ARGUMENT,
            f"SB3 checkpoint filename must be {expected_name!r} for algorithm {algorithm!r}.",
        )
    return path


def _error(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def _run_policy(
    env: Any,
    config: Dict[str, Any],
    episodes: int,
    policy: str,
    action_fn: Callable[[Any, bool, Dict[str, Any]], Any],
) -> Dict[str, Any]:
    ts_ids = getattr(env, "ts_ids", None) or ["ts_0"]
    episode_rewards: List[float] = []
    info_samples: Dict[str, List[float]] = {}
    seed_raw = config.get("seed")
    seed = int(seed_raw) if seed_raw is not None and seed_raw != "" else None
    for episode_idx in range(episodes):
        try:
            reset_result = env.reset(seed=seed + episode_idx) if seed is not None else env.reset()
        except TypeError:
            reset_result = env.reset()
        obs = reset_result[0] if isinstance(reset_result, tuple) and len(reset_result) == 2 else reset_result
        single_agent_mode = not isinstance(obs, dict)
        if single_agent_mode:
            obs = {ts_ids[0]: obs}

        total_reward = 0.0
        done_all = False
        decision_steps = 0
        delta_time = max(1, int(getattr(env, "delta_time", 1)))
        max_decisions = max(1, int(config.get("steps_per_episode", 1000)) // delta_time) + 10
        while not done_all and decision_steps < max_decisions:
            action_input: Any = obs[ts_ids[0]] if single_agent_mode else obs
            actions = action_fn(action_input, single_agent_mode, obs)
            step_result = env.step(actions)
            if len(step_result) == 4:
                next_obs, rewards, dones, info = step_result
                done_all = bool(dones.get("__all__", False)) if isinstance(dones, dict) else bool(dones)
                reward_values = rewards.values() if isinstance(rewards, dict) else [rewards]
            elif len(step_result) == 5:
                next_obs, reward, terminated, truncated, info = step_result
                done_all = bool(terminated) or bool(truncated)
                reward_values = [reward]
                next_obs = {ts_ids[0]: next_obs}
            else:
                raise RuntimeError(f"Unexpected env.step return length {len(step_result)}")
            total_reward += sum(float(r) for r in reward_values)
            _record_info(info_samples, info)
            obs = next_obs if isinstance(next_obs, dict) else {ts_ids[0]: next_obs}
            decision_steps += 1
        episode_rewards.append(total_reward)
    mean_reward = _mean(episode_rewards)
    metrics: Dict[str, Any] = {
        "episodes": episodes,
        "episode_rewards": episode_rewards,
        "mean_total_reward": mean_reward,
        "policy": policy,
    }
    _add_info_metrics(metrics, info_samples)
    return metrics


def evaluate_run(
    run_dir: str,
    *,
    episodes: int = 1,
    checkpoint: Optional[str] = None,
    policy: str = "trained",
) -> Dict[str, Any]:
    """Evaluate a saved QL run.

    ``policy='trained'`` uses the saved Q-table greedily. ``policy='fixed'``
    always chooses action 0, a deterministic fixed-action baseline that is
    lightweight enough for CI smoke tests.
    """
    env = None
    try:
        manifest = load_run(run_dir)
        config = load_config(run_dir)
        algorithm = str(config.get("algorithm") or manifest.get("algorithm") or "ql").lower()
        ckpt = checkpoint or manifest.get("latest_checkpoint") or manifest.get("final_model")
        if policy == "trained" and not ckpt:
            return _error(ErrorCode.FILE_NOT_FOUND, "No checkpoint found for evaluation.")
        if policy not in ("trained", "fixed"):
            return _error(ErrorCode.INVALID_ARGUMENT, f"Unsupported evaluation policy {policy!r}.")
        if algorithm not in INDEPENDENT_QL_ALGORITHMS and algorithm not in SB3_ALGORITHMS:
            return _error(ErrorCode.INVALID_ARGUMENT, f"Unsupported RL evaluation algorithm {algorithm!r}.")

        if algorithm in SB3_ALGORITHMS:
            if policy == "trained" and checkpoint is not None:
                return _error(
                    ErrorCode.INVALID_ARGUMENT,
                    "SB3 evaluation does not accept caller-supplied checkpoint overrides; "
                    "use the server-recorded run manifest checkpoint.",
                )
            ckpt_path = (
                _validate_manifest_checkpoint(run_dir, str(ckpt), manifest, algorithm=algorithm, suffix=".zip")
                if policy == "trained" else None
            )
            env = _make_env(config, run_dir, single_agent=True)
            model: Any = None
            if policy == "trained":
                model_cls = _load_sb3_model_class(algorithm)
                model = model_cls.load(str(ckpt_path))

            def sb3_action(obs_value: Any, single_agent: bool, all_obs: Dict[str, Any]) -> Any:
                if policy == "fixed":
                    return 0
                action, _state = model.predict(obs_value, deterministic=True)
                return action

            metrics = _run_policy(env, config, episodes, policy, sb3_action)
        else:
            ckpt_path = validate_checkpoint_path(run_dir, str(ckpt), suffix=".json") if policy == "trained" else None
            q_tables = load_q_tables(str(ckpt_path), decode_keys=False) if policy == "trained" else {}
            env = _make_env(config, run_dir, single_agent=False)

            def q_action(obs_value: Any, single_agent: bool, all_obs: Dict[str, Any]) -> Any:
                if policy == "fixed":
                    return 0 if single_agent else {ts_id: 0 for ts_id in all_obs}
                if single_agent:
                    ts_id = next(iter(all_obs.keys()))
                    return _greedy_action(q_tables, ts_id, env.encode(all_obs[ts_id], ts_id))
                return {
                    ts_id: _greedy_action(q_tables, ts_id, env.encode(ts_obs, ts_id))
                    for ts_id, ts_obs in all_obs.items()
                }

            metrics = _run_policy(env, config, episodes, policy, q_action)
        mean_reward = float(metrics["mean_total_reward"])
        out = Path(run_dir) / f"evaluation_{policy}.json"
        out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        update_run(run_dir, {f"evaluation_{policy}": str(out)})
        return {"ok": True, "summary": f"{policy} evaluation mean reward {mean_reward:.3f}", "metrics": metrics,
                "artifact": str(out)}
    except CheckpointError as exc:
        return _error(exc.code, exc.message)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return _error(ErrorCode.INVALID_ARGUMENT, f"{type(exc).__name__}: {exc}")
    except RuntimeError as exc:
        return _error(ErrorCode.DEPENDENCY_MISSING if "stable-baselines3" in str(exc) else ErrorCode.EXECUTION_FAILED,
                      f"{type(exc).__name__}: {exc}")
    except Exception as exc:
        return _error(ErrorCode.EXECUTION_FAILED, f"{type(exc).__name__}: {exc}")
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass


def compare_run(run_dir: str, *, episodes: int = 1) -> Dict[str, Any]:
    try:
        trained = evaluate_run(run_dir, episodes=episodes, policy="trained")
        if not trained.get("ok"):
            return trained
        fixed = evaluate_run(run_dir, episodes=episodes, policy="fixed")
        if not fixed.get("ok"):
            return fixed
        trained_reward = float(trained["metrics"]["mean_total_reward"])
        fixed_reward = float(fixed["metrics"]["mean_total_reward"])
        improvement = trained_reward - fixed_reward
        payload = {
            "trained": trained["metrics"],
            "fixed_action_baseline": fixed["metrics"],
            "mean_reward_delta": improvement,
        }
        out = Path(run_dir) / "comparison.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        update_run(run_dir, {"comparison_file": str(out)})
        return {"ok": True, "summary": f"Mean reward delta vs fixed-action baseline: {improvement:.3f}",
                "metrics": payload, "artifact": str(out)}
    except Exception as exc:
        return _error(ErrorCode.EXECUTION_FAILED, f"{type(exc).__name__}: {exc}")
