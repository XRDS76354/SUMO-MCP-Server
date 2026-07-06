"""Algorithm metadata and dependency checks for RL tasks."""
from __future__ import annotations

from importlib.util import find_spec
from typing import Any, Dict, List


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
            "multi_agent": True,
            "dependency": "sumo-mcp[rl]",
            "description": "SB3 PPO; can be adapted to vectorized PettingZoo wrappers.",
        },
        {
            "name": "a2c",
            "family": "stable-baselines3",
            "available": sb3_available and torch_available,
            "multi_agent": True,
            "dependency": "sumo-mcp[rl]",
            "description": "SB3 A2C; lighter policy-gradient baseline.",
        },
        {
            "name": "pettingzoo-independent-ql",
            "family": "pettingzoo",
            "available": pettingzoo_available,
            "multi_agent": True,
            "dependency": "sumo-mcp[rl]",
            "description": "Independent learners over sumo-rl parallel_env.",
        },
    ]


def algorithm_status(name: str) -> Dict[str, Any] | None:
    normalized = name.lower()
    for spec in list_algorithms():
        if spec["name"] == normalized:
            return spec
    return None
