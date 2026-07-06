"""Subprocess entry point for RL training jobs."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from sumo_mcp.mcp_tools.rl import run_rl_training
from sumo_mcp.rl.runs import latest_checkpoint, load_config, update_run
from sumo_mcp.utils.sumo import find_sumo_home


def _copy_metrics(run_dir: Path) -> str | None:
    candidates = sorted(run_dir.glob("train_results*.csv"))
    if not candidates:
        return None
    metrics_file = run_dir / "metrics.csv"
    metrics_file.write_text(candidates[0].read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return str(metrics_file)


def _result(ok: bool, summary: str, **extra: Any) -> Dict[str, Any]:
    result: Dict[str, Any] = {"ok": ok, "summary": summary}
    result.update(extra)
    return result


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(json.dumps(_result(False, "Usage: python -m sumo_mcp.rl.train_entry <run_dir>")), flush=True)
        return 2

    run_dir = Path(args[0]).expanduser().resolve()
    try:
        config = load_config(str(run_dir))
        home = os.environ.get("SUMO_HOME") or find_sumo_home()
        if home:
            os.environ.setdefault("SUMO_HOME", home)

        update_run(str(run_dir), {"status": "running"})
        checkpoint_dir = run_dir / "checkpoints"
        resume_checkpoint = config.get("resume_checkpoint")
        text = run_rl_training(
            net_file=str(config["net_file"]),
            route_file=str(config["route_file"]),
            out_dir=str(run_dir),
            episodes=int(config.get("episodes", 1)),
            steps_per_episode=int(config.get("steps_per_episode", 1000)),
            algorithm=str(config.get("algorithm", "ql")),
            reward_type=str(config.get("reward_type", "diff-waiting-time")),
            checkpoint_dir=str(checkpoint_dir),
            resume_checkpoint=str(resume_checkpoint) if resume_checkpoint else None,
        )
        ok = not text.lstrip().lower().startswith(("error", "training failed", "algorithm "))
        metrics_file = _copy_metrics(run_dir)
        checkpoint = latest_checkpoint(str(run_dir))
        update_run(str(run_dir), {
            "status": "succeeded" if ok else "failed",
            "episodes_done": int(config.get("episodes", 1)) if ok else 0,
            "metrics_file": metrics_file or str(run_dir / "metrics.csv"),
            "final_model": checkpoint,
            "latest_checkpoint": checkpoint,
            "training_summary": text,
        })
        payload = _result(ok, text, run_dir=str(run_dir), metrics_file=metrics_file, checkpoint=checkpoint)
        print(json.dumps(payload, ensure_ascii=False), flush=True)
        return 0 if ok else 1
    except Exception as exc:
        try:
            update_run(str(run_dir), {"status": "failed", "training_summary": f"{type(exc).__name__}: {exc}"})
        except Exception:
            pass
        print(json.dumps(_result(False, f"{type(exc).__name__}: {exc}", run_dir=str(run_dir))), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
