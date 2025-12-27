import os
import shutil
import warnings
import logging
from filecmp import cmp
from typing import List, Optional

from mcp_tools.simulation import run_simple_simulation
from mcp_tools.signal import tls_cycle_adaptation, tls_coordinator
from mcp_tools.analysis import analyze_fcd

logger = logging.getLogger(__name__)


def _copy_to_dir(src_file: str, dst_dir: str) -> str:
    """
    Copy src_file into dst_dir (if needed) and return the local path.

    This is used to ensure generated SUMO config files can reference inputs via
    relative paths, even on Windows when source and destination are on different drives.
    """
    dst_file = os.path.join(dst_dir, os.path.basename(src_file))
    if os.path.abspath(src_file) == os.path.abspath(dst_file):
        return dst_file

    if os.path.exists(dst_file):
        try:
            if cmp(src_file, dst_file, shallow=False):
                return dst_file
        except OSError:
            pass

    shutil.copy2(src_file, dst_file)
    return dst_file


def signal_opt_workflow(
    net_file: str, 
    route_file: str, 
    output_dir: str, 
    steps: int = 3600,
    use_coordinator: bool = False
) -> str:
    """
    Signal Optimization Workflow.
    1. Run Baseline Simulation
    2. Optimize Signals (Cycle Adaptation or Coordinator)
    3. Run Optimized Simulation
    4. Compare Results

    Note:
        To keep generated `.sumocfg` files portable (especially on Windows across drives),
        `net_file` and `route_file` will be copied into `output_dir` when needed.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    local_net_file = _copy_to_dir(net_file, output_dir)
    local_route_file = _copy_to_dir(route_file, output_dir)
        
    # Baseline paths
    baseline_cfg = os.path.join(output_dir, "baseline.sumocfg")
    baseline_fcd = os.path.join(output_dir, "baseline_fcd.xml")
    
    # Optimized paths
    opt_net_file = os.path.join(output_dir, "optimized.net.xml")
    opt_cfg = os.path.join(output_dir, "optimized.sumocfg")
    opt_fcd = os.path.join(output_dir, "optimized_fcd.xml")
    
    # 1. Run Baseline
    _create_config(baseline_cfg, local_net_file, local_route_file, baseline_fcd, steps)
    res_baseline = run_simple_simulation(baseline_cfg, steps)
    if "error" in res_baseline.lower():
        return f"Baseline Simulation Failed: {res_baseline}"
        
    analysis_baseline = analyze_fcd(baseline_fcd)
    
    # 2. Optimize
    if use_coordinator:
        res_opt = tls_coordinator(local_net_file, local_route_file, opt_net_file)
    else:
        res_opt = tls_cycle_adaptation(local_net_file, local_route_file, opt_net_file)
        
    if "failed" in res_opt.lower() or "error" in res_opt.lower():
        return f"Optimization Failed: {res_opt}"
    
    # Check if optimized file is valid and determines if it is a net or additional
    is_additional = _is_additional_file(opt_net_file)
    
    # 3. Run Optimized
    if is_additional:
        # Use original net + additional file
        _create_config(
            opt_cfg,
            local_net_file,
            local_route_file,
            opt_fcd,
            steps,
            additional_files=[opt_net_file],
        )
    else:
        # Use new net file
        _create_config(opt_cfg, opt_net_file, local_route_file, opt_fcd, steps)
        
    res_optimized = run_simple_simulation(opt_cfg, steps)
    if "error" in res_optimized.lower():
        return f"Optimized Simulation Failed: {res_optimized}"
        
    analysis_optimized = analyze_fcd(opt_fcd)
    
    return (f"Signal Optimization Workflow Completed.\n\n"
            f"--- Baseline Results ---\n{res_baseline}\n{analysis_baseline}\n\n"
            f"--- Optimization Step ---\n{res_opt}\n\n"
            f"--- Optimized Results ---\n{res_optimized}\n{analysis_optimized}")


def _is_additional_file(file_path: str) -> bool:
    if not os.path.exists(file_path): return False
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            head = f.read(1000)
        return '<additional' in head
    except Exception as e:
        logger.debug("Failed to inspect additional file %s: %s", file_path, e)
        return False


def _create_config(cfg_path: str, net_file: str, route_file: str, fcd_file: str, steps: int, additional_files: Optional[List[str]] = None) -> None:
    cfg_dir = os.path.dirname(os.path.abspath(cfg_path))

    def _as_cfg_path(file_path: str) -> str:
        abs_path = os.path.abspath(file_path)
        try:
            rel_path = os.path.relpath(abs_path, cfg_dir)
        except ValueError:
            basename = os.path.basename(abs_path)
            warnings.warn(
                f"Cannot compute relative path from config dir '{cfg_dir}' to '{abs_path}'. "
                f"Using basename '{basename}' for portability; ensure the file exists in '{cfg_dir}'.",
                RuntimeWarning,
                stacklevel=2,
            )
            return basename

        if rel_path.startswith(".."):
            basename = os.path.basename(abs_path)
            warnings.warn(
                f"Path '{abs_path}' is outside config dir '{cfg_dir}'. "
                f"Using basename '{basename}' for portability; ensure the file exists in '{cfg_dir}'.",
                RuntimeWarning,
                stacklevel=2,
            )
            return basename

        return rel_path

    additional_str = ""
    if additional_files:
        val = ",".join([_as_cfg_path(f) for f in additional_files])
        additional_str = f'<additional-files value="{val}"/>'

    net_value = _as_cfg_path(net_file)
    route_value = _as_cfg_path(route_file)
    fcd_value = _as_cfg_path(fcd_file)

    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(f"""<configuration>
    <input>
        <net-file value="{net_value}"/>
        <route-files value="{route_value}"/>
        {additional_str}
    </input>
    <time>
        <begin value="0"/>
        <end value="{steps}"/>
    </time>
    <output>
        <fcd-output value="{fcd_value}"/>
    </output>
</configuration>""")
