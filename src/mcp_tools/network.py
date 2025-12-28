import subprocess
import sumolib
import os
import sys
from typing import Optional, List

from utils.sumo import build_sumo_diagnostics, find_sumo_tool_script
from utils.output import truncate_text
from utils.timeout import subprocess_run_with_timeout

def netconvert(osm_file: str, output_file: str, options: Optional[List[str]] = None) -> str:
    """
    Wrapper for SUMO netconvert. Converts OSM files to SUMO network files.
    """
    try:
        binary = sumolib.checkBinary('netconvert')
    except (SystemExit, Exception) as e:
        return f"Error finding netconvert: {e}"

    cmd = [binary, "--osm-files", osm_file, "-o", output_file]
    if options:
        cmd.extend(options)
    
    try:
        result = subprocess_run_with_timeout(cmd, operation="netconvert", check=True)
        return f"Netconvert successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"Netconvert failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"Netconvert execution error: {str(e)}"

def netgenerate(output_file: str, grid: bool = True, grid_number: int = 3, options: Optional[List[str]] = None) -> str:
    """
    Wrapper for SUMO netgenerate. Generates abstract networks.
    """
    try:
        binary = sumolib.checkBinary('netgenerate')
    except (SystemExit, Exception) as e:
        return f"Error finding netgenerate: {e}"

    cmd = [binary, "-o", output_file]
    if grid:
        cmd.extend(["--grid", "--grid.number", str(grid_number)])
    
    if options:
        cmd.extend(options)
    
    try:
        result = subprocess_run_with_timeout(cmd, operation="netgenerate", check=True)
        return f"Netgenerate successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"Netgenerate failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"Netgenerate execution error: {str(e)}"

def osm_get(bbox: str, output_dir: str, prefix: str = "osm", options: Optional[List[str]] = None) -> str:
    """
    Wrapper for osmGet.py. Downloads OSM data.
    
    Args:
        bbox: Bounding box "west,south,east,north".
        output_dir: Directory to save the data.
        prefix: Prefix for output files.
    """
    script = find_sumo_tool_script("osmGet.py")
    if not script:
        return "\n".join(
            [
                "Error: Could not locate SUMO tool script `osmGet.py`.",
                build_sumo_diagnostics("sumo"),
                "Please set `SUMO_HOME` to your SUMO installation directory "
                "(so that `$SUMO_HOME/tools/osmGet.py` exists).",
            ]
        )
        
    os.makedirs(output_dir, exist_ok=True)
        
    # osmGet.py writes to current dir or specified prefix. 
    # We should run it in the output_dir or handle paths carefully.
    # It seems osmGet.py uses --prefix to specify output filename prefix.
    
    cmd = [sys.executable, script, "--bbox", bbox, "--prefix", prefix]
    
    if options:
        cmd.extend(options)
        
    try:
        # Run in output_dir so files are saved there
        result = subprocess_run_with_timeout(cmd, operation="osmGet", check=True, cwd=output_dir)
        return f"osmGet successful.\nStdout: {truncate_text(result.stdout)}"
    except subprocess.CalledProcessError as e:
        return f"osmGet failed.\nStderr: {truncate_text(e.stderr)}\nStdout: {truncate_text(e.stdout)}"
    except Exception as e:
        return f"osmGet execution error: {str(e)}"
