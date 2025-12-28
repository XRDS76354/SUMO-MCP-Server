import subprocess
import sumolib
import os
import sys
from typing import Optional, List

from utils.sumo import build_sumo_diagnostics, find_sumo_tool_script
from utils.output import truncate_text
from utils.timeout import subprocess_run_with_timeout

def random_trips(net_file: str, output_file: str, end_time: int = 3600, period: float = 1.0, options: Optional[List[str]] = None) -> str:
    """
    Wrapper for randomTrips.py. Generates random trips for a given network.
    """
    script = find_sumo_tool_script("randomTrips.py")
    if not script:
        return "\n".join(
            [
                "Error: Could not locate SUMO tool script `randomTrips.py`.",
                build_sumo_diagnostics("sumo"),
                "Please set `SUMO_HOME` to your SUMO installation directory "
                "(so that `$SUMO_HOME/tools/randomTrips.py` exists).",
            ]
        )
        
    # Using sys.executable ensures we use the same python environment
    cmd = [sys.executable, script, "-n", net_file, "-o", output_file, "-e", str(end_time), "-p", str(period)]
    
    if options:
        cmd.extend(options)
        
    try:
        result = subprocess_run_with_timeout(
            cmd,
            operation="randomTrips",
            params={"end_time": end_time},
            check=True,
        )
        return f"randomTrips successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"randomTrips failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"randomTrips execution error: {str(e)}"

def duarouter(net_file: str, route_files: str, output_file: str, options: Optional[List[str]] = None) -> str:
    """
    Wrapper for duarouter. Computes routes from trips.
    """
    try:
        binary = sumolib.checkBinary('duarouter')
    except (SystemExit, Exception) as e:
        return f"Error finding duarouter: {e}"
        
    cmd = [binary, "-n", net_file, "--route-files", route_files, "-o", output_file, "--ignore-errors"]
    
    if options:
        cmd.extend(options)
        
    try:
        result = subprocess_run_with_timeout(cmd, operation="duarouter", check=True)
        return f"duarouter successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"duarouter failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"duarouter execution error: {str(e)}"

def od2trips(od_file: str, output_file: str, options: Optional[List[str]] = None) -> str:
    """
    Wrapper for od2trips. Converts OD matrices to trips.
    
    Args:
        od_file: Path to OD matrix file.
        output_file: Path to output trips file.
    """
    try:
        binary = sumolib.checkBinary('od2trips')
    except (SystemExit, Exception) as e:
        return f"Error finding od2trips: {e}"
        
    cmd = [binary, "--od-matrix-files", od_file, "-o", output_file]
    
    if options:
        cmd.extend(options)
        
    try:
        result = subprocess_run_with_timeout(cmd, operation="od2trips", check=True)
        return f"od2trips successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"od2trips failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"od2trips execution error: {str(e)}"
