"""Subprocess entry point for Stable-Baselines3 RL training jobs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Type

from sumo_mcp.models import ErrorCode
from sumo_mcp.rl.algorithms import SB3_ALGORITHMS
from sumo_mcp.rl.metrics import copy_latest_metrics
from sumo_mcp.rl.runs import latest_checkpoint, load_config, update_run
from sumo_mcp.utils.sumo import find_sumo_home
from sumo_mcp.utils.traci import ensure_traci_start_stdout_suppressed


def _result(ok: bool, summary: str, **extra: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": ok, "summary": summary}
    result.update(extra)
    return result


def _model_class(algorithm: str) -> Type[Any]:
    try:
        from stable_baselines3 import A2C, DQN, PPO
    except ImportError as exc:
        raise RuntimeError("stable-baselines3 and torch are required; install sumo-mcp[rl]") from exc

    mapping: Dict[str, Type[Any]] = {"dqn": DQN, "ppo": PPO, "a2c": A2C}
    return mapping[algorithm]


def _make_env(config: Dict[str, Any], run_dir: Path) -> Any:
    ensure_traci_start_stdout_suppressed()
    from sumo_rl import SumoEnvironment

    kwargs: Dict[str, Any] = {
        "net_file": str(config["net_file"]),
        "route_file": str(config["route_file"]),
        "out_csv_name": str(run_dir / "train_results"),
        "use_gui": False,
        "num_seconds": int(config.get("steps_per_episode", 1000)),
        "reward_fn": str(config.get("reward_type", "diff-waiting-time")),
        "delta_time": int(config.get("delta_time", 5)),
        "yellow_time": int(config.get("yellow_time", 2)),
        "single_agent": True,
        "sumo_warnings": False,
    }
    seed = _seed(config)
    if seed is not None:
        kwargs["sumo_seed"] = seed
    return SumoEnvironment(**kwargs)


def _total_timesteps(config: Dict[str, Any]) -> int:
    explicit = config.get("total_timesteps")
    if explicit is not None:
        return int(explicit)
    return int(config.get("episodes", 1)) * int(config.get("steps_per_episode", 1000))


def _seed(config: Dict[str, Any]) -> Optional[int]:
    raw = config.get("seed")
    if raw is None or raw == "":
        return None
    return int(raw)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(json.dumps(_result(False, "Usage: python -m sumo_mcp.rl.sb3_entry <run_dir>")), flush=True)
        return 2

    run_dir = Path(args[0]).expanduser().resolve()
    env = None
    try:
        config = load_config(str(run_dir))
        algorithm = str(config.get("algorithm", "")).lower()
        if algorithm not in SB3_ALGORITHMS:
            raise ValueError(f"SB3 entry cannot train algorithm {algorithm!r}")

        home = os.environ.get("SUMO_HOME") or find_sumo_home()
        if home:
            os.environ.setdefault("SUMO_HOME", home)

        update_run(str(run_dir), {"status": "running"})
        model_cls = _model_class(algorithm)
        env = _make_env(config, run_dir)
        timesteps = _total_timesteps(config)
        tensorboard_dir = run_dir / "tensorboard"
        checkpoint_dir = run_dir / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        resume_checkpoint = config.get("resume_checkpoint")

        if resume_checkpoint:
            model = model_cls.load(str(resume_checkpoint), env=env)
        else:
            model = model_cls(
                str(config.get("policy", "MlpPolicy")),
                env,
                verbose=0,
                tensorboard_log=str(tensorboard_dir),
                seed=_seed(config),
            )
        model.learn(total_timesteps=timesteps)
        model_file = checkpoint_dir / f"{algorithm}_model.zip"
        model.save(str(model_file))

        try:
            env.save_csv(env.out_csv_name, env.episode)
        except Exception:
            pass
        metrics_file = copy_latest_metrics(run_dir)
        checkpoint = latest_checkpoint(str(run_dir), suffixes={".zip"}) or str(model_file)
        summary = f"{algorithm.upper()} SB3 training finished: {timesteps} timesteps."
        update_run(str(run_dir), {
            "status": "succeeded",
            "episodes_done": int(config.get("episodes", 1)),
            "total_timesteps": timesteps,
            "metrics_file": metrics_file or str(run_dir / "metrics.csv"),
            "final_model": checkpoint,
            "latest_checkpoint": checkpoint,
            "training_summary": summary,
        })
        payload = _result(True, summary, run_dir=str(run_dir), metrics_file=metrics_file, checkpoint=checkpoint)
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0
    except RuntimeError as exc:
        summary = f"Dependency missing: {exc}"
        try:
            update_run(str(run_dir), {
                "status": "failed",
                "training_summary": summary,
                "error": {"code": ErrorCode.DEPENDENCY_MISSING, "message": summary},
            })
        except Exception:
            pass
        print(json.dumps(_result(False, summary, error={"code": ErrorCode.DEPENDENCY_MISSING,
                                                        "message": summary})), flush=True)
        return 1
    except Exception as exc:
        summary = f"{type(exc).__name__}: {exc}"
        try:
            update_run(str(run_dir), {"status": "failed", "training_summary": summary})
        except Exception:
            pass
        print(json.dumps(_result(False, summary, run_dir=str(run_dir))), flush=True)
        return 1
    finally:
        if env is not None:
            try:
                env.close()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
