import os
from importlib.util import find_spec
from pathlib import Path
from typing import Any, List, Optional, Tuple

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
    try:
        if not os.path.exists(net_file):
            return f"Error: Network file not found at {net_file}"
        if not os.path.exists(route_file):
            return f"Error: Route file not found at {route_file}"

        if not os.path.exists(out_dir):
            os.makedirs(out_dir)
            
        env_class = _get_sumo_environment_class()
        env = None
        try:
            env = env_class(
                net_file=net_file,
                route_file=route_file,
                out_csv_name=os.path.join(out_dir, "train_results"),
                use_gui=False,
                num_seconds=steps_per_episode,
                reward_fn=reward_type,
                single_agent=False,
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
                obs = env.reset()
                if not isinstance(obs, dict):
                    return (
                        "Training failed: Unexpected observation type from sumo-rl reset(). "
                        f"Expected dict, got {type(obs).__name__}."
                    )

                # Align agent state to the new episode start.
                for ts_id, ts_obs in obs.items():
                    state = env.encode(ts_obs, ts_id)
                    if ts_id not in agents:
                        action_space = env.action_spaces(ts_id)
                        agents[ts_id] = QLAgent(
                            starting_state=state,
                            state_space=env.observation_spaces(ts_id),
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

                while not dones.get("__all__", False):
                    # sumo-rl returns observations/rewards only for agents that are ready to act.
                    actions = {ts_id: agents[ts_id].act() for ts_id in obs.keys() if ts_id in agents}

                    step_result = env.step(actions)
                    if not (isinstance(step_result, tuple) and len(step_result) == 4):
                        return (
                            "Training failed: Unexpected return value from sumo-rl step(). "
                            "Expected (obs, rewards, dones, info)."
                        )
                    next_obs, rewards, dones, _info = step_result

                    if not isinstance(next_obs, dict) or not isinstance(rewards, dict) or not isinstance(dones, dict):
                        return "Training failed: Unexpected types returned from sumo-rl step()."

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
            
    except Exception as e:
        return f"Training failed: {str(e)}"
