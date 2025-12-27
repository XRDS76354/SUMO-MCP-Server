import pytest
import os

from mcp_tools.network import netconvert
from mcp_tools.simulation import run_simple_simulation

def test_cmd_injection_netconvert():
    # Attempt to inject a command via filename
    # Note: subprocess.run with list args usually handles this safely.
    # We expect the command to fail gracefully (file not found) rather than executing 'echo hacked'
    
    malicious_file = "test.osm; echo hacked > hacked.txt"
    output_file = "out.net.xml"
    
    res = netconvert(malicious_file, output_file)
    
    # Check that hacked.txt was NOT created
    assert not os.path.exists("hacked.txt")
    assert ("error" in res.lower()) or ("failed" in res.lower())
    
def test_path_traversal_config():
    # Attempt to read a file outside directory (though this tool just runs sumo)
    # The risk is low for run_simple_simulation as it just passes path to sumo
    # But let's see if it crashes or handles it
    
    res = run_simple_simulation("../../../windows/system32/calc.exe", steps=10)
    assert "Error" in res

def test_invalid_inputs():
    res = run_simple_simulation("non_existent.sumocfg", steps=-10)
    assert "Error" in res
