import subprocess
import sys
from typing import Optional, List

from utils.sumo import build_sumo_diagnostics, find_sumo_tool_script
from utils.output import truncate_text
from utils.timeout import subprocess_run_with_timeout

def tls_cycle_adaptation(net_file: str, route_files: str, output_file: str) -> str:
    """
    Wrapper for tlsCycleAdaptation.py. Adapts traffic light cycles based on traffic demand.
    """
    script = find_sumo_tool_script("tlsCycleAdaptation.py")
    if not script:
        return "\n".join(
            [
                "Error: Could not locate SUMO tool script `tlsCycleAdaptation.py`.",
                build_sumo_diagnostics("sumo"),
                "Please set `SUMO_HOME` to your SUMO installation directory "
                "(so that `$SUMO_HOME/tools/tlsCycleAdaptation.py` exists).",
            ]
        )
        
    cmd = [sys.executable, script, "-n", net_file, "-r", route_files, "-o", output_file]
    
    try:
        result = subprocess_run_with_timeout(cmd, operation="tlsCycleAdaptation", check=True)
        return f"tlsCycleAdaptation successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"tlsCycleAdaptation failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"Error: {str(e)}"

def tls_coordinator(net_file: str, route_files: str, output_file: str, options: Optional[List[str]] = None) -> str:
    """
    Wrapper for tlsCoordinator.py. Optimizes traffic light coordination.
    
    Args:
        net_file: Path to network file.
        route_files: Path to route file(s).
        output_file: Path to output network file with coordinated signals.
    """
    script = find_sumo_tool_script("tlsCoordinator.py")
    if not script:
        return "\n".join(
            [
                "Error: Could not locate SUMO tool script `tlsCoordinator.py`.",
                build_sumo_diagnostics("sumo"),
                "Please set `SUMO_HOME` to your SUMO installation directory "
                "(so that `$SUMO_HOME/tools/tlsCoordinator.py` exists).",
            ]
        )
        
    cmd = [sys.executable, script, "-n", net_file, "-r", route_files, "-o", output_file]
    
    if options:
        cmd.extend(options)
        
    try:
        result = subprocess_run_with_timeout(cmd, operation="tlsCoordinator", check=True)
        return f"tlsCoordinator successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"tlsCoordinator failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"tlsCoordinator execution error: {str(e)}"
