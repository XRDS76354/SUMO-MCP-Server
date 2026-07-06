"""Evaluation helpers for saved Q-learning RL runs."""
from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Any, Dict, Optional

from sumo_mcp.rl.runs import load_config, load_run, update_run
from sumo_mcp.utils.sumo import find_sumo_home
from sumo_mcp.utils.traci import ensure_traci_start_stdout_suppressed


def _load_q_tables(checkpoint: str) -> Dict[str, Any]:
    with open(checkpoint, "rb") as f:
        payload = pickle.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint {checkpoint} did not contain a dict")
    q_tables = payload.get("q_tables", payload)
    if not isinstance(q_tables, dict):
        raise ValueError(f"checkpoint {checkpoint} did not contain q_tables")
    return q_tables


def _greedy_action(q_tables: Dict[str, Any], ts_id: str, state: Any) -> int:
    table = q_tables.get(ts_id, {})
    values = table.get(state) if hasattr(table, "get") else None
    if not values:
        return 0
    return int(max(range(len(values)), key=lambda idx: values[idx]))


def _make_env(config: Dict[str, Any], run_dir: str) -> Any:
    ensure_traci_start_stdout_suppressed()
    home = os.environ.get("SUMO_HOME") or find_sumo_home()
    if home:
        os.environ.setdefault("SUMO_HOME", home)
    from sumo_rl import SumoEnvironment

    return SumoEnvironment(
        net_file=str(config["net_file"]),
        route_file=str(config["route_file"]),
        out_csv_name=str(Path(run_dir) / "evaluation"),
        use_gui=False,
        num_seconds=int(config.get("steps_per_episode", 1000)),
        reward_fn=str(config.get("reward_type", "diff-waiting-time")),
        single_agent=False,
        sumo_warnings=False,
    )


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
    manifest = load_run(run_dir)
    config = load_config(run_dir)
    ckpt = checkpoint or manifest.get("latest_checkpoint") or manifest.get("final_model")
    if policy == "trained" and not ckpt:
        return {"ok": False, "error": {"code": "FILE_NOT_FOUND", "message": "No checkpoint found for evaluation."}}
    q_tables = _load_q_tables(str(ckpt)) if policy == "trained" else {}

    env = None
    episode_rewards = []
    try:
        env = _make_env(config, run_dir)
        ts_ids = getattr(env, "ts_ids", None) or ["ts_0"]
        for _episode in range(episodes):
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
                if policy == "fixed":
                    actions: Any = 0 if single_agent_mode else {ts_id: 0 for ts_id in obs}
                elif single_agent_mode:
                    ts_id = next(iter(obs.keys()))
                    actions = _greedy_action(q_tables, ts_id, env.encode(obs[ts_id], ts_id))
                else:
                    actions = {
                        ts_id: _greedy_action(q_tables, ts_id, env.encode(ts_obs, ts_id))
                        for ts_id, ts_obs in obs.items()
                    }
                step_result = env.step(actions)
                if len(step_result) == 4:
                    next_obs, rewards, dones, _info = step_result
                    done_all = bool(dones.get("__all__", False)) if isinstance(dones, dict) else bool(dones)
                    reward_values = rewards.values() if isinstance(rewards, dict) else [rewards]
                elif len(step_result) == 5:
                    next_obs, reward, terminated, truncated, _info = step_result
                    done_all = bool(terminated) or bool(truncated)
                    reward_values = [reward]
                    next_obs = {ts_ids[0]: next_obs}
                else:
                    raise RuntimeError(f"Unexpected env.step return length {len(step_result)}")
                total_reward += sum(float(r) for r in reward_values)
                obs = next_obs if isinstance(next_obs, dict) else {ts_ids[0]: next_obs}
                decision_steps += 1
            episode_rewards.append(total_reward)
        mean_reward = sum(episode_rewards) / max(1, len(episode_rewards))
        metrics = {
            "episodes": episodes,
            "episode_rewards": episode_rewards,
            "mean_total_reward": mean_reward,
            "policy": policy,
        }
        out = Path(run_dir) / f"evaluation_{policy}.json"
        out.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        update_run(run_dir, {f"evaluation_{policy}": str(out)})
        return {"ok": True, "summary": f"{policy} evaluation mean reward {mean_reward:.3f}", "metrics": metrics,
                "artifact": str(out)}
    except Exception as exc:
        return {"ok": False, "error": {"code": "EXECUTION_FAILED", "message": f"{type(exc).__name__}: {exc}"}}
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass


def compare_run(run_dir: str, *, episodes: int = 1) -> Dict[str, Any]:
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
