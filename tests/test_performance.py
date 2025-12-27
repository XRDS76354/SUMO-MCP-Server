import os
import shutil
import time

import pytest

psutil = pytest.importorskip("psutil")

# This module measures real workflow performance and requires SUMO.
HAS_SUMO = bool(os.environ.get("SUMO_HOME")) or shutil.which("sumo") is not None
pytestmark = pytest.mark.skipif(
    not HAS_SUMO,
    reason="Requires SUMO installed (set SUMO_HOME or add `sumo` to PATH).",
)

from workflows.sim_gen import sim_gen_workflow

@pytest.fixture
def output_dir():
    path = os.path.join(os.path.dirname(__file__), "output_perf")
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    yield path

def measure_workflow(output_dir, grid_n, steps):
    process = psutil.Process(os.getpid())
    start_mem = process.memory_info().rss / 1024 / 1024
    start_time = time.time()
    
    res = sim_gen_workflow(output_dir, grid_number=grid_n, steps=steps)
    
    end_time = time.time()
    end_mem = process.memory_info().rss / 1024 / 1024
    
    duration = end_time - start_time
    mem_diff = end_mem - start_mem
    
    print(f"\nPerformance [Grid {grid_n}x{grid_n}, Steps {steps}]:")
    print(f"  Duration: {duration:.2f}s")
    print(f"  Memory Change: {mem_diff:.2f}MB")
    
    return duration, res

def test_perf_small(output_dir):
    duration, res = measure_workflow(os.path.join(output_dir, "small"), 3, 100)
    assert "Workflow Completed Successfully" in res
    assert duration < 10.0 # Expect fast execution

def test_perf_medium(output_dir):
    duration, res = measure_workflow(os.path.join(output_dir, "medium"), 5, 200)
    assert "Workflow Completed Successfully" in res
    assert duration < 30.0

def test_perf_large(output_dir):
    # Reduced steps to keep test fast enough for interaction
    duration, res = measure_workflow(os.path.join(output_dir, "large"), 10, 200)
    assert "Workflow Completed Successfully" in res
