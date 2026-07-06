"""Algorithm metadata and dependency checks for RL tasks."""
from __future__ import annotations

from importlib.util import find_spec
from typing import Any, Dict, List

SB3_ALGORITHMS = frozenset({"dqn", "ppo", "a2c"})
INDEPENDENT_QL_ALGORITHMS = frozenset({"ql", "pettingzoo-independent-ql"})


def _available(module_name: str) -> bool:
    return find_spec(module_name) is not None


def list_algorithms() -> List[Dict[str, Any]]:
    """Return supported algorithms and their dependency state."""
    sb3_available = _available("stable_baselines3")
    torch_available = _available("torch")
    pettingzoo_available = _available("pettingzoo")
    return [
        {
            "name": "ql",
            "family": "tabular",
            "available": True,
            "multi_agent": True,
            "dependency": None,
            "description": "sumo-rl built-in QLAgent; fast smoke tests and small networks.",
        },
        {
            "name": "dqn",
            "family": "stable-baselines3",
            "available": sb3_available and torch_available,
            "multi_agent": False,
            "dependency": "sumo-mcp[rl]",
            "description": "SB3 DQN for single-intersection discrete signal control.",
        },
        {
            "name": "ppo",
            "family": "stable-baselines3",
            "available": sb3_available and torch_available,
            "multi_agent": False,
            "dependency": "sumo-mcp[rl]",
            "description": "SB3 PPO single-agent baseline for one controlled traffic signal.",
        },
        {
            "name": "a2c",
            "family": "stable-baselines3",
            "available": sb3_available and torch_available,
            "multi_agent": False,
            "dependency": "sumo-mcp[rl]",
            "description": "SB3 A2C single-agent baseline for one controlled traffic signal.",
        },
        {
            "name": "pettingzoo-independent-ql",
            "family": "pettingzoo",
            "available": pettingzoo_available,
            "multi_agent": True,
            "dependency": "sumo-mcp[rl]",
            "description": "Independent per-signal Q-learning for multi-agent SUMO-RL scenarios.",
        },
    ]


def algorithm_status(name: str) -> Dict[str, Any] | None:
    normalized = name.lower()
    for spec in list_algorithms():
        if spec["name"] == normalized:
            return spec
    return None


def training_backend(name: str) -> str | None:
    """Return the internal training backend for an algorithm."""
    normalized = name.lower()
    if normalized in INDEPENDENT_QL_ALGORITHMS:
        return "ql"
    if normalized in SB3_ALGORITHMS:
        return "sb3"
    return None
