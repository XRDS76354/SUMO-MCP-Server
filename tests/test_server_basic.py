import subprocess
import json
import os
import sys
import time
import selectors
from typing import Any

def test_mcp_server():
    # Path to server script
    server_path = os.path.join(os.path.dirname(__file__), "..", "src", "server.py")
    
    def _read_json_line(process: subprocess.Popen[str], timeout_s: float = 20.0) -> dict[str, Any]:
        if process.stdout is None:
            raise RuntimeError("process.stdout is None")

        # Windows pipes do not support selectors/select reliably.
        if sys.platform == "win32":
            import queue
            import threading

            deadline = time.time() + timeout_s
            while time.time() < deadline:
                remaining = deadline - time.time()
                line_queue: queue.Queue[str] = queue.Queue(maxsize=1)

                def reader() -> None:
                    line_queue.put(process.stdout.readline())

                thread = threading.Thread(target=reader, daemon=True)
                thread.start()

                try:
                    line = line_queue.get(timeout=remaining)
                except queue.Empty:
                    raise TimeoutError("timed out waiting for server JSON-RPC response") from None

                if not line:
                    raise RuntimeError("server stdout closed unexpectedly")

                line = line.strip()
                if not line:
                    continue

                return json.loads(line)

            raise TimeoutError("timed out waiting for server JSON-RPC response")

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                remaining = deadline - time.time()
                events = selector.select(timeout=remaining)
                if not events:
                    continue

                line = process.stdout.readline()
                if not line:
                    raise RuntimeError("server stdout closed unexpectedly")

                line = line.strip()
                if not line:
                    continue

                return json.loads(line)

            raise TimeoutError("timed out waiting for server JSON-RPC response")
        finally:
            selector.close()

    # Start the server process
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [sys.executable, server_path],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        env=env,
        bufsize=1, # Line-buffered
    )
    
    print("Server started. Sending initialize...")
    
    try:
        assert process.stdin is not None

        # 1. Initialize
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        }
        process.stdin.write(json.dumps(init_req) + "\n")
        process.stdin.flush()

        response = _read_json_line(process)
        print("Initialize response:", response)
        assert response["id"] == 1
        assert "serverInfo" in response["result"]

        # 2. Initialized notification
        notify_req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        process.stdin.write(json.dumps(notify_req) + "\n")
        process.stdin.flush()

        # 3. List Tools
        list_req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
        process.stdin.write(json.dumps(list_req) + "\n")
        process.stdin.flush()

        response = _read_json_line(process)
        print("Tools list response:", response)
        assert response["id"] == 2
        tools = response["result"]["tools"]
        assert any(t["name"] == "get_sumo_info" for t in tools)

        # 4. Call get_sumo_info
        call_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "get_sumo_info", "arguments": {}},
        }
        process.stdin.write(json.dumps(call_req) + "\n")
        process.stdin.flush()

        response = _read_json_line(process)
        print("Call response:", response)
        assert response["id"] == 3
        content = response["result"]["content"][0]["text"]
        print("Tool output:", content)
        assert content
        # 在无 SUMO 环境下，get_sumo_info 也应返回可读错误而不是崩溃。
        assert ("SUMO Version" in content) or ("Error" in content)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()

if __name__ == "__main__":
    test_mcp_server()
