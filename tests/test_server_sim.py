import subprocess
import json
import os
import sys
import shutil

import pytest


# This test runs a real SUMO simulation via the MCP server. Skip if SUMO is unavailable.
HAS_SUMO = bool(os.environ.get("SUMO_HOME")) or shutil.which("sumo") is not None
pytestmark = pytest.mark.skipif(
    not HAS_SUMO,
    reason="Requires SUMO installed (set SUMO_HOME or add `sumo` to PATH).",
)

def test_sim_tool():
    server_path = os.path.join(os.path.dirname(__file__), "..", "src", "server.py")
    config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", "simple_sim", "hello.sumocfg"))
    
    process = subprocess.Popen(
        [sys.executable, server_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=0
    )
    
    # Initialize
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}) + "\n")
    process.stdin.flush()
    process.stdout.readline() # Read response
    
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    process.stdin.flush()
    
    # Call simulation
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "run_simple_simulation",
            "arguments": {
                "config_path": config_path,
                "steps": 50
            }
        }
    }
    process.stdin.write(json.dumps(req) + "\n")
    process.stdin.flush()
    
    line = process.stdout.readline()
    if not line:
        print("No output from server")
        return

    response = json.loads(line)
    print("Sim response:", response)
    
    if "error" in response:
        print("Error:", response["error"])
        assert False, f"Server returned error: {response['error']}"

    content = response["result"]["content"][0]["text"]
    print("Output:", content)
    
    assert "Simulation finished successfully" in content
    assert "Steps run: 50" in content
    
    process.terminate()

if __name__ == "__main__":
    test_sim_tool()
