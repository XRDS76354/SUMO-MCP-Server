import subprocess
import json
import os
import sys

def test_mcp_server():
    # Path to server script
    server_path = os.path.join(os.path.dirname(__file__), "..", "src", "server.py")
    
    # Start the server process
    process = subprocess.Popen(
        [sys.executable, server_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=0 # Unbuffered
    )
    
    print("Server started. Sending initialize...")
    
    # 1. Initialize
    init_req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"}
        }
    }
    process.stdin.write(json.dumps(init_req) + "\n")
    process.stdin.flush()
    
    response = json.loads(process.stdout.readline())
    print("Initialize response:", response)
    assert response["id"] == 1
    assert "serverInfo" in response["result"]
    
    # 2. Initialized notification
    notify_req = {
        "jsonrpc": "2.0",
        "method": "notifications/initialized"
    }
    process.stdin.write(json.dumps(notify_req) + "\n")
    process.stdin.flush()
    
    # 3. List Tools
    list_req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list"
    }
    process.stdin.write(json.dumps(list_req) + "\n")
    process.stdin.flush()
    
    response = json.loads(process.stdout.readline())
    print("Tools list response:", response)
    assert response["id"] == 2
    tools = response["result"]["tools"]
    assert any(t["name"] == "get_sumo_info" for t in tools)
    
    # 4. Call get_sumo_info
    call_req = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "get_sumo_info",
            "arguments": {}
        }
    }
    process.stdin.write(json.dumps(call_req) + "\n")
    process.stdin.flush()
    
    response = json.loads(process.stdout.readline())
    print("Call response:", response)
    assert response["id"] == 3
    content = response["result"]["content"][0]["text"]
    print("Tool output:", content)
    assert content
    # 在无 SUMO 环境下，get_sumo_info 也应返回可读错误而不是崩溃。
    assert ("SUMO Version" in content) or ("Error" in content)
    
    # Terminate
    process.terminate()
    print("Test Passed!")

if __name__ == "__main__":
    test_mcp_server()
