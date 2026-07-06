"""Helpers for turning arbitrary TraCI/SUMO objects into JSON-safe values."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, List, Tuple

JsonSafeResult = Tuple[Any, List[str]]

_PRIMITIVE_TYPES = (str, int, float, bool, type(None))


def to_json_safe(value: Any, *, max_depth: int = 6, max_items: int = 100) -> JsonSafeResult:
    """Return ``(json_safe_value, warnings)`` for a possibly complex object.

    TraCI getters can return SUMO-specific objects such as ProgramLogic/Phase.
    FastMCP serializes tool results as JSON, so every direct call result must be
    normalized before it enters the envelope.
    """
    warnings: List[str] = []

    def convert(obj: Any, path: str, depth: int) -> Any:
        if isinstance(obj, _PRIMITIVE_TYPES):
            return obj
        if depth >= max_depth:
            warnings.append(f"{path}: truncated at max_depth={max_depth}")
            return repr(obj)
        if isinstance(obj, bytes):
            warnings.append(f"{path}: bytes decoded with replacement")
            return obj.decode("utf-8", errors="replace")
        if is_dataclass(obj) and not isinstance(obj, type):
            return convert(asdict(obj), path, depth + 1)
        if isinstance(obj, dict):
            items = list(obj.items())
            if len(items) > max_items:
                warnings.append(f"{path}: dict truncated to {max_items} items")
                items = items[:max_items]
            return {str(k): convert(v, f"{path}.{k}", depth + 1) for k, v in items}
        if isinstance(obj, (list, tuple, set, frozenset)):
            items = list(obj)
            if len(items) > max_items:
                warnings.append(f"{path}: sequence truncated to {max_items} items")
                items = items[:max_items]
            return [convert(item, f"{path}[{idx}]", depth + 1) for idx, item in enumerate(items)]

        special = _sumo_object_to_dict(obj)
        if special is not None:
            return convert(special, path, depth + 1)

        attrs = _public_attrs(obj)
        if attrs:
            return convert(attrs, path, depth + 1)

        warnings.append(f"{path}: converted {type(obj).__name__} to repr")
        return repr(obj)

    return convert(value, "$", 0), warnings


def _sumo_object_to_dict(obj: Any) -> Dict[str, Any] | None:
    """Best-effort structured extraction for common TraCI objects."""
    cls_name = type(obj).__name__
    if cls_name == "Logic" or {"programID", "type", "currentPhaseIndex", "phases"} <= set(dir(obj)):
        return {
            "type": cls_name,
            "program_id": getattr(obj, "programID", None),
            "logic_type": getattr(obj, "type", None),
            "current_phase_index": getattr(obj, "currentPhaseIndex", None),
            "sub_parameter": getattr(obj, "subParameter", None),
            "phases": getattr(obj, "phases", None),
        }
    if cls_name == "Phase" or {"duration", "state"} <= set(dir(obj)):
        return {
            "type": cls_name,
            "duration": getattr(obj, "duration", None),
            "state": getattr(obj, "state", None),
            "min_duration": getattr(obj, "minDur", None),
            "max_duration": getattr(obj, "maxDur", None),
            "next": getattr(obj, "next", None),
            "name": getattr(obj, "name", None),
        }
    return None


def _public_attrs(obj: Any) -> Dict[str, Any]:
    attrs: Dict[str, Any] = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        if callable(value):
            continue
        attrs[name] = value
    return attrs
