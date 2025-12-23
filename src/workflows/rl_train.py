from mcp_tools.rl import find_sumo_rl_scenario_files, list_rl_scenarios, run_rl_training

def rl_train_workflow(
    scenario_name: str,
    output_dir: str,
    episodes: int = 5,
    steps: int = 1000
) -> str:
    """
    Workflow to train an RL agent on a built-in sumo-rl scenario.
    1. Locate scenario files
    2. Run training
    3. Return summary
    """
    if not scenario_name:
        return (
            "Error: rl_train workflow requires scenario_name.\n"
            "Hint: Use manage_rl_task(list_scenarios) to list built-in scenarios, "
            "or use manage_rl_task(train_custom) for custom net/route files."
        )

    net_file, route_file, err = find_sumo_rl_scenario_files(scenario_name)
    if err:
        available = list_rl_scenarios()
        return f"{err}\nAvailable: {available}"
        
    return run_rl_training(
        net_file=net_file,
        route_file=route_file,
        out_dir=output_dir,
        episodes=episodes,
        steps_per_episode=steps,
        algorithm="ql"
    )
