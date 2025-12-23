import os
from typing import Any, List, Optional

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


def list_rl_scenarios() -> List[str]:
    """
    List available built-in RL scenarios from sumo-rl package.
    These are typically folders in sumo_rl/nets.
    """
    try:
        import sumo_rl
        base_path = os.path.dirname(sumo_rl.__file__)
        nets_path = os.path.join(base_path, 'nets')
        if not os.path.exists(nets_path):
            return ["Error: sumo-rl nets directory not found"]
        
        scenarios = [d for d in os.listdir(nets_path) if os.path.isdir(os.path.join(nets_path, d))]
        return sorted(scenarios)
    except Exception as e:
        return [f"Error listing scenarios: {str(e)}"]


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
