import os
import logging
import subprocess
import traci

from sumo_mcp.utils.sumo import build_sumo_diagnostics, find_sumo_binary
from sumo_mcp.utils.timeout import run_with_adaptive_timeout
from sumo_mcp.utils.traci import traci_close_best_effort

logger = logging.getLogger(__name__)


def run_simple_simulation(config_path: str, steps: int = 100) -> str:
    """
    Run a SUMO simulation using the given configuration file.

    Args:
        config_path: Path to the .sumocfg file.
        steps: Number of simulation steps to run.

    Returns:
        A summary string of the simulation execution.
    """
    if not os.path.exists(config_path):
        return f"Error: Config file not found at {config_path}"

    sumo_binary = find_sumo_binary("sumo")
    if not sumo_binary:
        return "\n".join(
            [
                "Error: Could not locate SUMO executable (`sumo`).",
                build_sumo_diagnostics("sumo"),
                "Please ensure SUMO is installed and either `sumo` is available in PATH or `SUMO_HOME` is set.",
            ]
        )

    # Start simulation
    # We use a random label to allow parallel runs if needed (though traci global lock is an issue)
    # Ideally use libsumo if available for speed, but traci is safer for now.
    cmd = [sumo_binary, "-c", config_path, "--no-step-log", "true", "--random"]

    try:
        def _run() -> str:
            # IMPORTANT: MCP uses stdout for JSON-RPC over stdio.
            # SUMO can write progress/log output to stdout which would corrupt the protocol stream,
            # causing clients to hang or show "undefined" responses.
            traci.start(cmd, stdout=subprocess.DEVNULL)

            vehicle_counts = []
            for _ in range(steps):
                traci.simulationStep()
                vehicle_counts.append(traci.vehicle.getIDCount())

            traci.close()

            avg_vehicles = sum(vehicle_counts) / len(vehicle_counts) if vehicle_counts else 0
            max_vehicles = max(vehicle_counts) if vehicle_counts else 0

            return (
                "Simulation finished successfully.\n"
                f"Steps run: {steps}\n"
                f"Average vehicles: {avg_vehicles:.2f}\n"
                f"Max vehicles: {max_vehicles}"
            )

        return run_with_adaptive_timeout(_run, operation="simulation", params={"steps": steps})

    except Exception as e:
        closed = traci_close_best_effort()
        if not closed:
            logger.debug("traci.close timed out during cleanup for %s", config_path)
        return "\n".join(
            [
                f"Simulation error: {type(e).__name__}: {e}",
                f"- config_path: {config_path}",
                f"- steps: {steps}",
                f"- sumo_binary: {sumo_binary}",
                f"- SUMO_HOME: {os.environ.get('SUMO_HOME', 'Not Set')}",
            ]
        )
