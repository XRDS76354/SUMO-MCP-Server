import sys
from pathlib import Path
from typing import Any, Dict, Tuple
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


class _DummyActionSpace:
    n = 2

    def sample(self) -> int:
        return 0


class _DummyEnv:
    last_instance: "_DummyEnv | None" = None

    def __init__(self, **kwargs: Any) -> None:
        self.ts_ids = ["A", "B"]
        self.episode = 0
        self.out_csv_name = kwargs.get("out_csv_name")
        self._step = 0
        self._saved: list[Tuple[str, int]] = []
        self._closed = False
        _DummyEnv.last_instance = self

    def reset(self) -> Dict[str, list[int]]:
        self.episode += 1
        self._step = 0
        return {"A": [0], "B": [0]}

    def step(self, actions: Dict[str, int]) -> Tuple[Dict[str, list[int]], Dict[str, float], Dict[str, bool], dict]:
        self._step += 1
        # Simulate SUMO-RL behavior: only a subset of agents may be ready to act.
        active_ts = "A" if self._step == 1 else "B"
        next_obs = {active_ts: [self._step]}
        rewards = {active_ts: 1.0}
        dones = {"A": False, "B": False, "__all__": self._step >= 2}
        info: dict = {}
        return next_obs, rewards, dones, info

    def action_spaces(self, ts_id: str) -> _DummyActionSpace:
        return _DummyActionSpace()

    def observation_spaces(self, ts_id: str) -> object:
        return object()

    def encode(self, obs: list[int], ts_id: str) -> tuple[str, int]:
        return (ts_id, obs[0])

    def save_csv(self, out_csv_name: str, episode: int) -> None:
        self._saved.append((out_csv_name, episode))

    def close(self) -> None:
        self._closed = True


class _DummyEnvNoTLS(_DummyEnv):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ts_ids = []


def test_run_rl_training_handles_multiagent_api(tmp_path: Path) -> None:
    from mcp_tools.rl import run_rl_training

    net_file = tmp_path / "net.net.xml"
    route_file = tmp_path / "routes.rou.xml"
    net_file.write_text("<net></net>", encoding="utf-8")
    route_file.write_text("<routes></routes>", encoding="utf-8")

    out_dir = tmp_path / "out"

    with patch("mcp_tools.rl._get_sumo_environment_class", return_value=_DummyEnv):
        result = run_rl_training(
            net_file=str(net_file),
            route_file=str(route_file),
            out_dir=str(out_dir),
            episodes=2,
            steps_per_episode=10,
            algorithm="ql",
            reward_type="diff-waiting-time",
        )

    assert "Episode 1/2" in result
    assert "Episode 2/2" in result

    env = _DummyEnv.last_instance
    assert env is not None
    assert env._closed is True
    # The wrapper saves the last episode explicitly.
    assert env._saved == [(str(out_dir / "train_results"), 2)]


def test_run_rl_training_requires_tls(tmp_path: Path) -> None:
    from mcp_tools.rl import run_rl_training

    net_file = tmp_path / "net.net.xml"
    route_file = tmp_path / "routes.rou.xml"
    net_file.write_text("<net></net>", encoding="utf-8")
    route_file.write_text("<routes></routes>", encoding="utf-8")

    with patch("mcp_tools.rl._get_sumo_environment_class", return_value=_DummyEnvNoTLS):
        result = run_rl_training(
            net_file=str(net_file),
            route_file=str(route_file),
            out_dir=str(tmp_path / "out"),
            episodes=1,
            steps_per_episode=10,
            algorithm="ql",
            reward_type="diff-waiting-time",
        )

    assert "No traffic lights found" in result
