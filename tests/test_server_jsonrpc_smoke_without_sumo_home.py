"""集成冒烟测试：不依赖SUMO安装也能完成MCP基础握手与工具枚举。

该用例用于覆盖一个关键风险：
1) 未设置`SUMO_HOME`或未安装`sumo`二进制时，服务端仍应能启动并完成`initialize`/`tools/list`；
2) 仅在真正调用需要SUMO的工具时，再返回明确错误。
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest


def _read_json_line(process: subprocess.Popen[str], timeout_s: float = 20.0) -> dict[str, Any]:
    """从子进程stdout读取一行JSON（带超时），避免测试挂死。"""
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


def test_server_initialize_and_list_tools_without_sumo_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """不设置`SUMO_HOME`也能完成`initialize`与`tools/list`。"""
    monkeypatch.delenv("SUMO_HOME", raising=False)

    server_path = Path(__file__).resolve().parents[1] / "src" / "server.py"
    env = os.environ.copy()
    env.pop("SUMO_HOME", None)
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
        assert "serverInfo" in init_resp["result"]

        process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        process.stdin.flush()

        process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
        process.stdin.flush()
        list_resp = _read_json_line(process, timeout_s=20.0)
        assert list_resp["id"] == 2
        tools = list_resp["result"]["tools"]
        tool_names = {t["name"] for t in tools}

        # 只验证与SUMO无关的基础能力：服务端启动 + 工具枚举。
        assert {"manage_network", "manage_demand", "run_workflow"}.issubset(tool_names)
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
