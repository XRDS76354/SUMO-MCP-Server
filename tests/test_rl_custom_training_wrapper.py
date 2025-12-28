import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple
from unittest.mock import patch


class _DummyActionSpace:
    n = 2

    def sample(self) -> int:
        return 0


class _DummyQLAgent:
    def __init__(
        self,
        starting_state: object,
        state_space: object,
        action_space: _DummyActionSpace,
        alpha: float,
        gamma: float,
    ) -> None:
        self.state = starting_state
        self.action_space = action_space
        self.q_table: dict[object, list[float]] = {starting_state: [0.0 for _ in range(action_space.n)]}
        self.action = None
        self.acc_reward = 0.0

    def act(self) -> int:
        return 0

    def learn(self, next_state: object, reward: float, done: bool) -> None:
        self.state = next_state
        self.acc_reward += float(reward)


class _DummyEnv:
    last_instance: "_DummyEnv | None" = None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.ts_ids = ["A", "B"]
        self.episode = 0
        self.out_csv_name = kwargs.get("out_csv_name")
        self._step = 0
        self._saved: list[Tuple[str, int]] = []
        self._closed = False
        self._close_threads: list[str] = []
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
        self._close_threads.append(threading.current_thread().name)
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

    with patch.dict(os.environ, {"SUMO_HOME": "/tmp/sumo"}, clear=False):
        with patch("sumo_rl.agents.QLAgent", _DummyQLAgent):
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

    with patch.dict(os.environ, {"SUMO_HOME": "/tmp/sumo"}, clear=False):
        with patch("sumo_rl.agents.QLAgent", _DummyQLAgent):
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


def test_run_rl_training_injects_sumo_log_files(tmp_path: Path) -> None:
    from mcp_tools.rl import run_rl_training

    net_file = tmp_path / "net.net.xml"
    route_file = tmp_path / "routes.rou.xml"
    net_file.write_text("<net></net>", encoding="utf-8")
    route_file.write_text("<routes></routes>", encoding="utf-8")

    out_dir = tmp_path / "out"

    with patch.dict(os.environ, {"SUMO_HOME": "/tmp/sumo"}, clear=False):
        with patch("sumo_rl.agents.QLAgent", _DummyQLAgent):
            with patch("mcp_tools.rl._get_sumo_environment_class", return_value=_DummyEnv):
                result = run_rl_training(
                    net_file=str(net_file),
                    route_file=str(route_file),
                    out_dir=str(out_dir),
                    episodes=1,
                    steps_per_episode=1,
                    algorithm="ql",
                    reward_type="diff-waiting-time",
                )

    assert "Episode 1/1" in result
    env = _DummyEnv.last_instance
    assert env is not None
    additional = env.kwargs.get("additional_sumo_cmd")
    assert isinstance(additional, str)
    assert "--error-log sumo_error.log" in additional
    assert "--log sumo.log" in additional
    assert "--message-log sumo_message.log" in additional


def test_run_rl_training_times_out_when_step_hangs(tmp_path: Path) -> None:
    from mcp_tools.rl import run_rl_training
    from utils.timeout import TIMEOUT_CONFIGS, TimeoutConfig

    class _HangingEnv(_DummyEnv):
        def step(self, actions: Dict[str, int]):  # type: ignore[override]
            time.sleep(0.5)
            return super().step(actions)

    net_file = tmp_path / "net.net.xml"
    route_file = tmp_path / "routes.rou.xml"
    net_file.write_text("<net></net>", encoding="utf-8")
    route_file.write_text("<routes></routes>", encoding="utf-8")

    out_dir = tmp_path / "out"

    with patch.dict(os.environ, {"SUMO_HOME": "/tmp/sumo"}, clear=False):
        with patch("sumo_rl.agents.QLAgent", _DummyQLAgent):
            with patch.dict(
                TIMEOUT_CONFIGS,
                {
                    "rl_training": TimeoutConfig(
                        base_timeout=0.2,
                        max_timeout=0.2,
                        backoff_factor=1.5,
                        heartbeat_interval=0.05,
                    )
                },
                clear=False,
            ):
                with patch("mcp_tools.rl._get_sumo_environment_class", return_value=_HangingEnv):
                    result = run_rl_training(
                        net_file=str(net_file),
                        route_file=str(route_file),
                        out_dir=str(out_dir),
                        episodes=1,
                        steps_per_episode=1,
                        algorithm="ql",
                        reward_type="diff-waiting-time",
                    )

    assert "TimeoutError" in result or "timed out" in result.lower()
    env = _DummyEnv.last_instance
    assert env is not None
    # Cancellation callback should close the environment even if the training thread is stuck.
    assert env._closed is True
    assert "MainThread" in env._close_threads


def test_run_rl_training_redirects_traci_stdout(monkeypatch, tmp_path: Path) -> None:
    from mcp_tools.rl import run_rl_training

    net_file = tmp_path / "net.net.xml"
    route_file = tmp_path / "routes.rou.xml"
    net_file.write_text("<net></net>", encoding="utf-8")
    route_file.write_text("<routes></routes>", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_traci_start(*args, **kwargs):
        captured["stdout"] = kwargs.get("stdout")
        raise RuntimeError("stop")

    monkeypatch.setattr("traci.start", fake_traci_start, raising=False)

    class _EnvCallsTraciStart:
        def __init__(self, **kwargs: Any) -> None:
            import traci

            traci.start(["sumo"])

    with patch("mcp_tools.rl._get_sumo_environment_class", return_value=_EnvCallsTraciStart):
        result = run_rl_training(
            net_file=str(net_file),
            route_file=str(route_file),
            out_dir=str(tmp_path / "out"),
            episodes=1,
            steps_per_episode=1,
        )

    assert captured["stdout"] is subprocess.DEVNULL
    assert "Training failed" in result
