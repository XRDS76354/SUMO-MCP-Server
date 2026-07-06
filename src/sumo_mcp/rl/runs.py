"""Run directory and manifest helpers for RL experiments."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_FILE = "config.json"
MANIFEST_FILE = "manifest.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, payload: Dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def create_run(out_dir: str, config: Dict[str, Any], *, run_id: Optional[str] = None) -> Dict[str, Any]:
    """Create a reproducible RL run directory and return its manifest."""
    rid = run_id or new_run_id()
    run_dir = Path(out_dir).expanduser().resolve() / rid
    (run_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
    (run_dir / "tensorboard").mkdir(parents=True, exist_ok=True)

    full_config = dict(config)
    full_config["run_id"] = rid
    full_config["run_dir"] = str(run_dir)
    _atomic_write(run_dir / CONFIG_FILE, full_config)

    manifest: Dict[str, Any] = {
        "run_id": rid,
        "run_dir": str(run_dir),
        "algorithm": str(config.get("algorithm", "ql")),
        "status": "created",
        "episodes_done": 0,
        "created_at": _now(),
        "updated_at": _now(),
        "config_file": str(run_dir / CONFIG_FILE),
        "metrics_file": str(run_dir / "metrics.csv"),
        "checkpoints_dir": str(run_dir / "checkpoints"),
        "tensorboard_dir": str(run_dir / "tensorboard"),
        "final_model": None,
        "job_id": None,
    }
    _atomic_write(run_dir / MANIFEST_FILE, manifest)
    return manifest


def load_run(run_dir: str) -> Dict[str, Any]:
    path = Path(run_dir).expanduser().resolve() / MANIFEST_FILE
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return loaded


def load_config(run_dir: str) -> Dict[str, Any]:
    path = Path(run_dir).expanduser().resolve() / CONFIG_FILE
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return loaded


def update_config(run_dir: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    config = load_config(run_dir)
    config.update(updates)
    _atomic_write(Path(run_dir).expanduser().resolve() / CONFIG_FILE, config)
    return config


def update_run(run_dir: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    manifest = load_run(run_dir)
    manifest.update(updates)
    manifest["updated_at"] = _now()
    _atomic_write(Path(run_dir).expanduser().resolve() / MANIFEST_FILE, manifest)
    return manifest


def list_runs(out_dir: str) -> List[Dict[str, Any]]:
    root = Path(out_dir).expanduser().resolve()
    if not root.is_dir():
        return []
    runs: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        manifest = child / MANIFEST_FILE
        if not manifest.is_file():
            continue
        try:
            runs.append(json.loads(manifest.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(runs, key=lambda r: str(r.get("created_at", "")), reverse=True)


def latest_checkpoint(run_dir: str) -> Optional[str]:
    checkpoints = Path(run_dir).expanduser().resolve() / "checkpoints"
    if not checkpoints.is_dir():
        return None
    candidates = sorted(
        [p for p in checkpoints.iterdir() if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return str(candidates[0]) if candidates else None
