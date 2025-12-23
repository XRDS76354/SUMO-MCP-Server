import json
import os
import shutil
import subprocess
import sys
import time
import selectors
from pathlib import Path
from typing import Any

import pytest

# This is an integration test that exercises real SUMO binaries/tools via the MCP server.
HAS_SUMO = bool(os.environ.get("SUMO_HOME")) or shutil.which("sumo") is not None
pytestmark = pytest.mark.skipif(
    not HAS_SUMO,
    reason="Requires SUMO installed (set SUMO_HOME or add `sumo` to PATH).",
)


def _read_json_line(process: subprocess.Popen[str], timeout_s: float = 120.0) -> dict[str, Any]:
    if process.stdout is None:
        raise RuntimeError("process.stdout is None")

    # Windows 上 `select()`/`selectors` 不能用于管道 FD（仅支持 socket），因此使用线程读取避免 WinError 10038。
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

            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"Expected JSON-RPC line, got: {line}") from exc

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

            try:
                return json.loads(line)
            except json.JSONDecodeError as exc:
                raise AssertionError(f"Expected JSON-RPC line, got: {line}") from exc

        raise TimeoutError("timed out waiting for server JSON-RPC response")
    finally:
        selector.close()


def test_workflow(tmp_path: Path) -> None:
    output_dir = tmp_path / "output_workflow"
    server_path = Path(__file__).resolve().parents[1] / "src" / "server.py"

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    process = subprocess.Popen(
        [sys.executable, str(server_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        env=env,
        bufsize=1,
    )

    try:
        assert process.stdin is not None

        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "pytest", "version": "0"},
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        init_resp = _read_json_line(process, timeout_s=20.0)
        assert init_resp["id"] == 1
        assert init_resp["jsonrpc"] == "2.0"

        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()

        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "run_workflow",
                        "arguments": {
                            "workflow_name": "sim_gen_eval",
                            "params": {"output_dir": str(output_dir), "grid_number": 3, "steps": 50},
                        },
                    },
                }
            )
            + "\n"
        )
        process.stdin.flush()
        call_resp = _read_json_line(process, timeout_s=120.0)
        assert call_resp["id"] == 2
        assert "error" not in call_resp

        content = call_resp["result"]["content"][0]["text"]
        assert "Workflow Completed Successfully" in content
        assert "Average Speed" in content
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
