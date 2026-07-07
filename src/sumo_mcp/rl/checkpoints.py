"""Safe checkpoint helpers for SUMO-RL Q-learning runs."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from sumo_mcp.models import ErrorCode

CHECKPOINT_FORMAT = "sumo-mcp-q-table-v1"
STATE_KEY_FORMAT = "sumo-mcp-q-state-v1"


class CheckpointError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_scalar(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return value


def _normalize_state(value: Any) -> Any:
    value = _normalize_scalar(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist) and not isinstance(value, (str, bytes, bytearray)):
        try:
            value = tolist()
        except Exception:
            pass
    if isinstance(value, tuple):
        return {"type": "tuple", "items": [_normalize_state(v) for v in value]}
    if isinstance(value, list):
        return {"type": "list", "items": [_normalize_state(v) for v in value]}
    if isinstance(value, dict):
        return {
            "type": "dict",
            "items": [[str(k), _normalize_state(v)] for k, v in sorted(value.items(), key=lambda item: str(item[0]))],
        }
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return {"type": "float", "value": str(value)}
        return {"type": "float", "value": format(value, ".17g")}
    return {"type": "repr", "value": repr(value)}


def _denormalize_state(value: Any) -> Any:
    if isinstance(value, dict):
        marker = value.get("type")
        if marker == "tuple":
            return tuple(_denormalize_state(v) for v in value.get("items", []))
        if marker == "list":
            return tuple(_denormalize_state(v) for v in value.get("items", []))
        if marker == "dict":
            return tuple((k, _denormalize_state(v)) for k, v in value.get("items", []))
        if marker == "float":
            raw = str(value.get("value", "0"))
            return float(raw)
        if marker == "repr":
            return str(value.get("value", ""))
    return value


def state_to_key(state: Any) -> str:
    payload = {"format": STATE_KEY_FORMAT, "state": _normalize_state(state)}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def key_to_state(key: str) -> Any:
    payload = json.loads(key)
    if not isinstance(payload, dict) or payload.get("format") != STATE_KEY_FORMAT:
        raise ValueError("invalid Q-state key format")
    return _denormalize_state(payload.get("state"))


def _encode_q_value(value: Any) -> Any:
    """Return a strictly-JSON-safe representation of a Q-value.

    Non-finite floats (a diverged Q-table produces inf/nan) have no valid JSON
    literal; the default ``json.dumps`` would emit bare ``Infinity``/``NaN`` tokens
    that no strict/external parser can read. Encode them as strings that ``float()``
    parses back losslessly so the checkpoint stays valid JSON and round-trips.
    """
    value = _normalize_scalar(value)
    number = float(value)
    if math.isfinite(number):
        return number
    if math.isnan(number):
        return "NaN"
    return "Infinity" if number > 0 else "-Infinity"


def _decode_q_value(value: Any) -> float:
    # float() accepts "Infinity"/"-Infinity"/"NaN" as well as numeric inputs.
    return float(value)


def _serialize_q_tables(q_tables: Mapping[str, Any]) -> Dict[str, Dict[str, List[Any]]]:
    payload: Dict[str, Dict[str, List[Any]]] = {}
    for ts_id, table in q_tables.items():
        if not isinstance(table, Mapping):
            continue
        payload[str(ts_id)] = {
            state_to_key(state): [_encode_q_value(v) for v in values]
            for state, values in table.items()
        }
    return payload


def save_q_checkpoint(
    path: str,
    *,
    algorithm: str,
    requested_algorithm: str,
    episode: int,
    q_tables: Mapping[str, Any],
    config: Optional[Mapping[str, Any]] = None,
) -> str:
    checkpoint = Path(path)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "format": CHECKPOINT_FORMAT,
        "algorithm": algorithm,
        "requested_algorithm": requested_algorithm,
        "episode": episode,
        "created_at": _now(),
        "config": dict(config or {}),
        "q_tables": _serialize_q_tables(q_tables),
    }
    tmp = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
    # allow_nan=False is a hard backstop: _encode_q_value already stringifies non-finite
    # values, so any bare inf/nan reaching here is a bug we want to surface, not silently
    # write invalid JSON.
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    os.replace(tmp, checkpoint)
    return str(checkpoint)


def _load_payload(path: str) -> Dict[str, Any]:
    checkpoint = Path(path)
    if checkpoint.suffix.lower() == ".pkl":
        raise CheckpointError(
            ErrorCode.INVALID_ARGUMENT,
            "Legacy pickle Q-learning checkpoints are not accepted by public MCP tools; retrain to JSON.",
        )
    try:
        loaded = json.loads(checkpoint.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CheckpointError(ErrorCode.FILE_NOT_FOUND, f"checkpoint not found: {checkpoint}") from exc
    except json.JSONDecodeError as exc:
        raise CheckpointError(ErrorCode.INVALID_ARGUMENT, f"invalid checkpoint JSON: {exc}") from exc
    if not isinstance(loaded, dict) or loaded.get("format") != CHECKPOINT_FORMAT:
        raise CheckpointError(ErrorCode.INVALID_ARGUMENT, f"unsupported Q-learning checkpoint format: {checkpoint}")
    return loaded


def load_q_tables(path: str, *, decode_keys: bool = False) -> Dict[str, Any]:
    payload = _load_payload(path)
    q_tables = payload.get("q_tables")
    if not isinstance(q_tables, dict):
        raise CheckpointError(ErrorCode.INVALID_ARGUMENT, f"checkpoint {path} did not contain q_tables")
    if not decode_keys:
        return q_tables
    decoded: Dict[str, Dict[Any, list[float]]] = {}
    for ts_id, table in q_tables.items():
        if not isinstance(table, dict):
            continue
        decoded[str(ts_id)] = {
            key_to_state(key): [_decode_q_value(v) for v in values] for key, values in table.items()
        }
    return decoded


def validate_checkpoint_path(run_dir: str, checkpoint: str, *, suffix: str) -> str:
    run_path = Path(run_dir).expanduser().resolve()
    checkpoints_dir = run_path / "checkpoints"
    path = Path(checkpoint).expanduser().resolve()
    try:
        path.relative_to(checkpoints_dir)
    except ValueError as exc:
        raise CheckpointError(
            ErrorCode.INVALID_ARGUMENT,
            f"checkpoint must be under the run checkpoints directory: {checkpoints_dir}",
        ) from exc
    if path.suffix.lower() != suffix:
        raise CheckpointError(
            ErrorCode.INVALID_ARGUMENT,
            f"checkpoint must use {suffix} format for this algorithm: {path}",
        )
    if not path.is_file():
        raise CheckpointError(ErrorCode.FILE_NOT_FOUND, f"checkpoint not found: {path}")
    return str(path)
