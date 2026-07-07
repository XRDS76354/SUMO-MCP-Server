"""Helpers for SUMO-RL generated CSV metrics."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_EPISODE_RE = re.compile(r"_ep(\d+)\.csv$")


def _episode_number(path: Path) -> int:
    match = _EPISODE_RE.search(path.name)
    return int(match.group(1)) if match else -1


def latest_train_results(run_dir: Path) -> Optional[Path]:
    candidates = list(run_dir.glob("train_results*.csv"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: (_episode_number(path), path.stat().st_mtime))


def copy_latest_metrics(run_dir: Path) -> Optional[str]:
    source = latest_train_results(run_dir)
    if source is None:
        return None
    metrics_file = run_dir / "metrics.csv"
    metrics_file.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    return str(metrics_file)
