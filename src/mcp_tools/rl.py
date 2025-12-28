import os
import threading
from contextlib import contextmanager
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from utils.traci import ensure_traci_start_stdout_suppressed

# NOTE:
# `sumo_rl` will raise an ImportError at import-time if `SUMO_HOME` is not set.
# To avoid breaking non-RL features (e.g. importing the MCP server), we lazily
# import `SumoEnvironment` only when training is actually invoked.
SumoEnvironment: Any | None = None


def _get_sumo_environment_class() -> Any:
    """Return `sumo_rl.SumoEnvironment`, importing it lazily."""
    global SumoEnvironment
    if SumoEnvironment is None:
        from sumo_rl import SumoEnvironment as imported_sumo_environment

        SumoEnvironment = imported_sumo_environment
    return SumoEnvironment


def _get_sumo_rl_nets_dir() -> Optional[Path]:
    """Return the `sumo_rl/nets` directory without importing sumo-rl."""
    spec = find_spec("sumo_rl")
    if spec is None or spec.origin is None:
        return None

    package_dir = Path(spec.origin).resolve().parent
    nets_dir = package_dir / "nets"
    if nets_dir.is_dir():
        return nets_dir
    return None


def _scenario_candidates(scenario_name: str) -> List[str]:
    """Return scenario directory name candidates in priority order."""
    raw = scenario_name.strip()
    if not raw:
        return []

    candidates = [raw]

    normalized = raw.replace("_", "-")
    if normalized != raw:
        candidates.append(normalized)

    # Backward/variant naming compatibility.
    if raw == "single-intersection":
        candidates.append("2way-single-intersection")

    # De-duplicate while preserving order.
    seen = set()
    uniq: List[str] = []
    for c in candidates:
        if c not in seen:
            uniq.append(c)
            seen.add(c)
    return uniq


def list_rl_scenarios() -> List[str]:
    """
    List available built-in RL scenarios from sumo-rl package.
    These are typically folders in sumo_rl/nets.
    """
    nets_dir = _get_sumo_rl_nets_dir()
    if nets_dir is None:
        return ["Error: sumo-rl is not installed or nets directory not found"]

    try:
        scenarios = [p.name for p in nets_dir.iterdir() if p.is_dir()]
        return sorted(scenarios)
    except Exception as e:
        return [f"Error listing scenarios: {e}"]


def find_sumo_rl_scenario_files(scenario_name: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Resolve a sumo-rl built-in scenario directory to its `.net.xml` and `.rou.xml` files.

    Returns:
        (net_file, route_file, error) where error is None on success.
    """
    nets_dir = _get_sumo_rl_nets_dir()
    if nets_dir is None:
        return None, None, "Error: sumo-rl is not installed or nets directory not found"

    candidates = _scenario_candidates(scenario_name)
    if not candidates:
        return None, None, "Error: scenario_name is required"

    for candidate in candidates:
        scenario_dir = nets_dir / candidate
        if not scenario_dir.is_dir():
            continue

        net_files = sorted(scenario_dir.glob("*.net.xml"))
        route_files = sorted(scenario_dir.glob("*.rou.xml"))

        if not net_files or not route_files:
            return None, None, f"Error: Could not find .net.xml or .rou.xml in {scenario_dir}"

        return str(net_files[0]), str(route_files[0]), None

    available = [p.name for p in nets_dir.iterdir() if p.is_dir()]
    return (
        None,
        None,
        f"Error: Scenario '{scenario_name}' not found. Available: {sorted(available)}",
    )


def create_rl_environment(
    net_file: str,
    route_file: str,
    out_csv_name: Optional[str] = None,
    use_gui: bool = False,
    num_seconds: int = 100000,
    reward_fn: str = 'diff-waiting-time'
) -> str:
    """
    Validate and prepare an RL environment configuration.
    Actual environment creation happens in the training process due to Gym's nature.
    This tool validates inputs and returns a configuration summary.
    """
    if not os.path.exists(net_file):
        return f"Error: Network file not found at {net_file}"
    if not os.path.exists(route_file):
        return f"Error: Route file not found at {route_file}"
        
    return (f"RL Environment Configuration Valid:\n"
            f"- Net: {net_file}\n"
            f"- Route: {route_file}\n"
            f"- Reward Function: {reward_fn}\n"
            f"- GUI: {use_gui}\n"
            f"- Horizon: {num_seconds} steps")

def run_rl_training(
    net_file: str,
    route_file: str,
    out_dir: str,
    episodes: int = 1,
    steps_per_episode: int = 1000,
    algorithm: str = "ql",
    reward_type: str = "diff-waiting-time"
) -> str:
    """
    Run a basic RL training session using Q-Learning (default) or other algorithms.
    This runs synchronously and returns the result.
    """
    from collections import deque

    def _tail_file(path: str, max_lines: int = 80) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return "".join(deque(f, maxlen=max_lines)).strip()
        except FileNotFoundError:
            return None
        except Exception as e:
            return f"<Failed to read {path}: {type(e).__name__}: {e}>"

    def _append_log_tail(
        diagnostics: list[str],
        label: str,
        path: str,
        max_lines: int = 80,
    ) -> None:
        diagnostics.append(f"- {label}: {path}")
        tail = _tail_file(path, max_lines=max_lines)
        if tail:
            diagnostics.append(f"---- {os.path.basename(path)} (tail) ----")
            diagnostics.append(tail)

    try:
        if not os.path.exists(net_file):
            return f"Error: Network file not found at {net_file}"
        if not os.path.exists(route_file):
            return f"Error: Route file not found at {route_file}"

        # Ensure any TraCI-launched SUMO process can't leak stdout into MCP stdio.
        ensure_traci_start_stdout_suppressed()

        out_dir_abs = os.path.abspath(out_dir)
        os.makedirs(out_dir_abs, exist_ok=True)

        # Capture SUMO diagnostics into deterministic local files (avoid paths with spaces
        # since sumo-rl splits additional_sumo_cmd by whitespace).
        sumo_error_log_name = "sumo_error.log"
        sumo_error_log_path = os.path.join(out_dir_abs, sumo_error_log_name)
        sumo_log_name = "sumo.log"
        sumo_log_path = os.path.join(out_dir_abs, sumo_log_name)
        sumo_message_log_name = "sumo_message.log"
        sumo_message_log_path = os.path.join(out_dir_abs, sumo_message_log_name)

        additional_sumo_cmd = (
            f"--error-log {sumo_error_log_name} "
            f"--log {sumo_log_name} "
            f"--message-log {sumo_message_log_name}"
        )

        @contextmanager
        def _pushd(path: str):
            orig_cwd = os.getcwd()
            os.chdir(path)
            try:
                yield
            finally:
                try:
                    os.chdir(orig_cwd)
                except Exception:
                    pass

        def _train(
            heartbeat: Callable[[], None],
            cancel_event: threading.Event,
            register_cancel_callback: Callable[[Callable[[], None]], None],
        ) -> str:
            env_class = _get_sumo_environment_class()
            env = None
            cancel_message = "Training cancelled: timeout reached, cancellation requested."

            def _cancel() -> None:
                cancel_event.set()
                if env is None:
                    return
                try:
                    env.close()
                except Exception:
                    pass

            register_cancel_callback(_cancel)

            try:
                with _pushd(out_dir_abs):
                    env = env_class(
                        net_file=net_file,
                        route_file=route_file,
                        out_csv_name=os.path.join(out_dir_abs, "train_results"),
                        use_gui=False,
                        num_seconds=steps_per_episode,
                        reward_fn=reward_type,
                        single_agent=False,
                        sumo_warnings=False,
                        additional_sumo_cmd=additional_sumo_cmd,
                    )

                if not getattr(env, "ts_ids", None):
                    return (
                        "Training failed: No traffic lights found in the provided network.\n"
                        "Hint: RL training requires a network with traffic lights (tlLogic).\n"
                        "If you generated/converted the network yourself, try enabling TLS guessing "
                        "(e.g. netgenerate/netconvert with `--tls.guess true`)."
                    )

                if algorithm != "ql":
                    return f"Algorithm {algorithm} not yet implemented in this tool wrapper."

                # Simple Q-Learning implementation for demonstration.
                # In a real scenario, this would be more complex or use Stable Baselines3.
                from sumo_rl.agents import QLAgent

                agents: dict[str, QLAgent] = {}
                info_log: list[str] = []

                for ep in range(1, episodes + 1):
                    if cancel_event.is_set():
                        return cancel_message
                    heartbeat()
                    with _pushd(out_dir_abs):
                        reset_result = env.reset()

                    if isinstance(reset_result, tuple) and len(reset_result) == 2:
                        obs = reset_result[0]
                    else:
                        obs = reset_result

                    single_agent_mode = False
                    if not isinstance(obs, dict):
                        single_agent_mode = True
                        ts_ids = getattr(env, "ts_ids", None) or ["ts_0"]
                        obs = {ts_ids[0]: obs}

                    # Align agent state to the new episode start.
                    for ts_id, ts_obs in obs.items():
                        state = env.encode(ts_obs, ts_id)
                        if ts_id not in agents:
                            if single_agent_mode:
                                action_space = env.action_space
                                state_space = env.observation_space
                            else:
                                action_space = env.action_spaces(ts_id)
                                state_space = env.observation_spaces(ts_id)
                            agents[ts_id] = QLAgent(
                                starting_state=state,
                                state_space=state_space,
                                action_space=action_space,
                                alpha=0.1,
                                gamma=0.99,
                            )
                        else:
                            agent = agents[ts_id]
                            if state not in agent.q_table:
                                agent.q_table[state] = [0 for _ in range(agent.action_space.n)]
                            agent.state = state
                            agent.action = None
                            agent.acc_reward = 0

                    ep_total_reward = 0.0
                    dones: dict[str, bool] = {"__all__": False}
                    decision_steps = 0
                    delta_time = getattr(env, "delta_time", 1)
                    try:
                        delta_time_int = int(delta_time)
                    except (TypeError, ValueError):
                        delta_time_int = 1
                    max_decisions = max(1, int(steps_per_episode / max(1, delta_time_int))) + 10

                    done_all = False
                    while not done_all and decision_steps < max_decisions:
                        if cancel_event.is_set():
                            return cancel_message
                        heartbeat()
                        # sumo-rl returns observations/rewards only for agents that are ready to act.
                        if single_agent_mode:
                            ts_id = next(iter(obs.keys()), None)
                            action = agents[ts_id].act() if ts_id in agents else None
                            step_result = env.step(action)
                        else:
                            actions = {ts_id: agents[ts_id].act() for ts_id in obs.keys() if ts_id in agents}
                            step_result = env.step(actions)
                        heartbeat()
                        if cancel_event.is_set():
                            return cancel_message

                        if not isinstance(step_result, tuple):
                            return "Training failed: Unexpected return value from sumo-rl step()."

                        if len(step_result) == 4:
                            next_obs, rewards, dones, _info = step_result
                            if not isinstance(next_obs, dict) or not isinstance(rewards, dict) or not isinstance(dones, dict):
                                return "Training failed: Unexpected types returned from sumo-rl step()."
                            done_all = bool(dones.get("__all__", False))
                            if "__all__" not in dones:
                                done_all = all(bool(v) for v in dones.values()) if dones else False
                        elif len(step_result) == 5:
                            obs_val, reward_val, terminated, truncated, _info = step_result
                            ts_ids = getattr(env, "ts_ids", None) or ["ts_0"]
                            next_obs = {ts_ids[0]: obs_val}
                            rewards = {ts_ids[0]: reward_val}
                            done_all = bool(terminated) or bool(truncated)
                            dones = {"__all__": done_all, ts_ids[0]: done_all}
                        else:
                            return (
                                "Training failed: Unexpected return value from sumo-rl step(). "
                                f"Expected 4-tuple or 5-tuple, got {len(step_result)}."
                            )

                        for ts_id, reward in rewards.items():
                            if ts_id not in agents:
                                continue
                            if ts_id not in next_obs:
                                continue
                            agents[ts_id].learn(
                                next_state=env.encode(next_obs[ts_id], ts_id),
                                reward=reward,
                                done=dones.get(ts_id, False),
                            )
                            ep_total_reward += float(reward)

                        obs = next_obs
                        decision_steps += 1

                    info_log.append(f"Episode {ep}/{episodes}: Total Reward = {ep_total_reward:.2f}")

                # sumo-rl only auto-saves metrics for the previous episode on reset().
                # Save the last episode explicitly.
                env.save_csv(env.out_csv_name, env.episode)

                return "\n".join(info_log)
            finally:
                if env is not None:
                    try:
                        env.close()
                    except Exception:
                        pass

        from utils.timeout import run_with_adaptive_timeout

        return run_with_adaptive_timeout(
            _train,
            operation="rl_training",
            params={"episodes": episodes, "steps_per_episode": steps_per_episode},
        )
            
    except Exception as e:
        diagnostics: list[str] = [
            f"Training failed: {type(e).__name__}: {e}",
            f"- SUMO_HOME: {os.environ.get('SUMO_HOME', 'Not Set')}",
            f"- sumo_binary: {None}",
            f"- net_file: {net_file}",
            f"- route_file: {route_file}",
            f"- out_dir: {out_dir}",
            f"- additional_sumo_cmd: {additional_sumo_cmd if 'additional_sumo_cmd' in locals() else None}",
        ]

        try:
            from utils.sumo import find_sumo_binary

            diagnostics[2] = f"- sumo_binary: {find_sumo_binary('sumo') or 'Not Found'}"
        except Exception:
            diagnostics.pop(2)

        if "sumo_error_log_path" in locals():
            _append_log_tail(diagnostics, "sumo_error_log", sumo_error_log_path)
        if "sumo_log_path" in locals():
            _append_log_tail(diagnostics, "sumo_log", sumo_log_path)
        if "sumo_message_log_path" in locals():
            _append_log_tail(diagnostics, "sumo_message_log", sumo_message_log_path)

        return "\n".join(diagnostics)
