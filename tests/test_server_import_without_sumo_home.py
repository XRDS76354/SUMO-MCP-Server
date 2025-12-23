"""回归测试：未设置`SUMO_HOME`时仍可导入MCP服务端模块。

背景：`sumo_rl`在导入时会强制检查`SUMO_HOME`环境变量并抛出`ImportError`。
服务端模块应避免在导入阶段就硬依赖该检查，以便非RL功能（如工具列表、参数解析等）
在缺少SUMO运行环境时仍能启动并给出清晰的运行期错误。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def test_import_server_without_sumo_home(monkeypatch: pytest.MonkeyPatch) -> None:
    """确保`SUMO_HOME`缺失时导入`src/server.py`不会直接失败。"""
    monkeypatch.delenv("SUMO_HOME", raising=False)

    src_dir = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(src_dir))
    try:
        sys.modules.pop("sumo_rl", None)
        sys.modules.pop("server", None)
        server = importlib.import_module("server")

        # 确保服务端导入阶段不会触发 sumo-rl 的导入副作用。
        assert "sumo_rl" not in sys.modules

        # RL 相关功能在缺少 SUMO 环境时应返回可读错误，而不是抛异常。
        res = server.manage_rl_task("list_scenarios")
        assert isinstance(res, str)
        assert res
    finally:
        sys.modules.pop("server", None)
        sys.path.remove(str(src_dir))
