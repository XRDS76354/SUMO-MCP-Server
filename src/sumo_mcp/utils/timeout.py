"""
智能超时控制器

提供三层超时策略：
1. 静态超时 - 用于快速、可预测的操作
2. 参数自适应超时 - 根据输入参数估算合理超时
3. 心跳+指数退避 - 用于长时间运行的操作（如 RL 训练）
"""

import os
import logging
import inspect
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class TimeoutConfig:
    """超时配置"""
    base_timeout: float = 60.0          # 基础超时（秒）
    max_timeout: float = 3600.0         # 最大超时（秒）
    backoff_factor: float = 2.0         # 指数退避因子
    heartbeat_interval: float = 10.0    # 心跳检测间隔（秒）


# 预定义的超时配置
TIMEOUT_CONFIGS = {
    # Layer 1: 静态超时
    "netconvert": TimeoutConfig(base_timeout=300, max_timeout=600),
    "netgenerate": TimeoutConfig(base_timeout=120, max_timeout=300),
    "osmGet": TimeoutConfig(base_timeout=120, max_timeout=300),

    # Layer 2: 参数自适应（基础值，实际会根据参数调整）
    "randomTrips": TimeoutConfig(base_timeout=300, max_timeout=900),
    "duarouter": TimeoutConfig(base_timeout=120, max_timeout=1800),
    "simulation": TimeoutConfig(base_timeout=60, max_timeout=1800),
    "tlsCycleAdaptation": TimeoutConfig(base_timeout=300, max_timeout=1800),
    "tlsCoordinator": TimeoutConfig(base_timeout=300, max_timeout=1800),

    # Layer 3: 心跳+指数退避
    "rl_training": TimeoutConfig(
        base_timeout=300,           # 首次尝试 5 分钟
        max_timeout=7200,           # 最大 2 小时
        backoff_factor=1.5,         # 每次失败后扩展 1.5 倍
        heartbeat_interval=30.0     # 每 30 秒检查一次进程存活
    ),
}


def calculate_adaptive_timeout(
    operation: str,
    params: Optional[dict] = None
) -> float:
    """
    根据操作类型和参数计算自适应超时时间。

    Args:
        operation: 操作名称（如 "randomTrips", "simulation", "rl_training"）
        params: 操作参数，用于估算耗时

    Returns:
        估算的超时时间（秒）
    """
    config = TIMEOUT_CONFIGS.get(operation, TimeoutConfig())
    params = params or {}

    timeout = config.base_timeout

    if operation == "randomTrips":
        # 根据 end_time 调整：每 1000 秒仿真时间增加 10 秒超时
        end_time = params.get("end_time", 3600)
        timeout += end_time / 100

    elif operation == "duarouter":
        # 根据预估路径数量调整
        # 如果有 trips 文件大小信息，可以更精确估算
        timeout += params.get("estimated_routes", 1000) * 0.05

    elif operation == "simulation":
        # 根据仿真步数调整
        steps = params.get("steps", 1000)
        timeout += steps * 0.01

    elif operation in {"tlsCycleAdaptation", "tlsCoordinator"}:
        # TLS tools are pure file-processing scripts: the main predictor for runtime
        # is route file size (vehicle count) and, to a lesser extent, net size.
        route_files_bytes = params.get("route_files_bytes", 0) or 0
        net_file_bytes = params.get("net_file_bytes", 0) or 0

        try:
            route_files_bytes = float(route_files_bytes)
        except (TypeError, ValueError):
            route_files_bytes = 0
        try:
            net_file_bytes = float(net_file_bytes)
        except (TypeError, ValueError):
            net_file_bytes = 0

        # Heuristic: each additional 100KB of routes adds ~1s budget.
        timeout += route_files_bytes / 100_000
        # Net XML tends to be smaller; use a gentler slope.
        timeout += net_file_bytes / 500_000

    elif operation == "rl_training":
        # RL 训练：根据 episodes × steps 估算
        episodes = params.get("episodes", 1)
        steps_per_episode = params.get("steps_per_episode", 1000)
        # 估算：每个 episode 大约需要 steps/100 秒（保守估计）
        estimated_time = episodes * (steps_per_episode / 50)
        timeout = max(config.base_timeout, estimated_time * 1.5)  # 1.5x 安全余量

    return min(timeout, config.max_timeout)


class HeartbeatTimeoutExecutor:
    """
    心跳+指数退避超时执行器

    适用于长时间运行的操作，如 RL 训练。
    特点：
    1. 定期检查进程/操作是否存活（心跳）
    2. 首次超时后，使用指数退避扩展超时窗口
    3. 支持进度回调，避免误判"卡住"
    """

    def __init__(self, config: TimeoutConfig):
        self.config = config
        self.current_timeout = config.base_timeout
        self.retry_count = 0
        self._last_heartbeat = time.time()
        self._is_alive = True
        self._lock = threading.Lock()

    def heartbeat(self) -> None:
        """记录心跳，表示操作仍在进行"""
        with self._lock:
            self._last_heartbeat = time.time()

    def check_alive(self) -> bool:
        """检查是否在心跳间隔内有活动"""
        with self._lock:
            elapsed = time.time() - self._last_heartbeat
            return elapsed < self.config.heartbeat_interval * 3  # 3 倍容忍度

    def expand_timeout(self) -> float:
        """扩展超时窗口（指数退避）"""
        self.retry_count += 1
        self.current_timeout = min(
            self.current_timeout * self.config.backoff_factor,
            self.config.max_timeout
        )
        logger.info(
            "Timeout expanded: retry=%d, new_timeout=%.1fs",
            self.retry_count, self.current_timeout
        )
        return self.current_timeout

    def get_current_timeout(self) -> float:
        """获取当前超时时间"""
        return self.current_timeout


def run_with_adaptive_timeout(
    func: Callable[..., T],
    operation: str,
    params: Optional[dict] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> T:
    """
    使用自适应超时执行函数。

    对于 RL 训练等长时间操作，使用心跳机制而非简单超时。

    Args:
        func: 要执行的函数
        operation: 操作名称
        params: 操作参数（用于估算超时）
        on_progress: 进度回调函数

    Returns:
        函数执行结果

    Raises:
        TimeoutError: 如果操作超时且无法恢复
    """
    timeout = calculate_adaptive_timeout(operation, params)

    if operation == "rl_training":
        # 使用心跳机制
        config = TIMEOUT_CONFIGS[operation]
        executor = HeartbeatTimeoutExecutor(config)
        executor.current_timeout = timeout

        cancel_event = threading.Event()
        cancel_lock = threading.Lock()
        cancel_callback: dict[str, Optional[Callable[[], None]]] = {"cb": None}

        def register_cancel_callback(cb: Callable[[], None]) -> None:
            with cancel_lock:
                cancel_callback["cb"] = cb

        def request_cancel() -> None:
            cancel_event.set()
            with cancel_lock:
                cb = cancel_callback["cb"]
            if cb is not None:
                try:
                    cb()
                except Exception:
                    logger.debug("Cancel callback failed", exc_info=True)

        # 在后台线程中运行，主线程监控心跳
        result_container: dict = {"result": None, "error": None, "done": False}

        heartbeat = executor.heartbeat

        def _call_func() -> T:
            try:
                sig = inspect.signature(func)
            except (TypeError, ValueError):
                return func()

            kwargs: dict[str, Any] = {}
            if "cancel_event" in sig.parameters:
                kwargs["cancel_event"] = cancel_event
            if "register_cancel_callback" in sig.parameters:
                kwargs["register_cancel_callback"] = register_cancel_callback

            params = list(sig.parameters.values())
            if not params:
                return func(**kwargs) if kwargs else func()

            first = params[0]
            if first.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.VAR_POSITIONAL,
            ):
                return func(heartbeat, **kwargs)

            return func(**kwargs) if kwargs else func()

        def worker():
            try:
                result_container["result"] = _call_func()
            except Exception as e:
                result_container["error"] = e
            finally:
                result_container["done"] = True

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

        start_time = time.time()
        poll_interval = min(1.0, max(0.1, config.heartbeat_interval / 10))
        while not result_container["done"]:
            elapsed = time.time() - start_time

            if elapsed > executor.get_current_timeout():
                if executor.check_alive():
                    # 有心跳活动，扩展超时
                    new_timeout = executor.expand_timeout()
                    if on_progress:
                        on_progress(f"Operation still running, extended timeout to {new_timeout:.0f}s")
                else:
                    # 无心跳，认为卡死
                    request_cancel()
                    raise TimeoutError(
                        f"Operation '{operation}' timed out after {elapsed:.0f}s with no activity"
                    )

            time.sleep(poll_interval)

        if result_container["error"]:
            raise result_container["error"]
        return result_container["result"]

    else:
        # 简单超时
        result_container: dict = {"result": None, "error": None, "done": False}

        def worker():
            try:
                result_container["result"] = func()
            except Exception as e:
                result_container["error"] = e
            finally:
                result_container["done"] = True

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if not result_container["done"]:
            raise TimeoutError(f"Operation '{operation}' timed out after {timeout:.0f}s")

        if result_container["error"]:
            raise result_container["error"]
        return result_container["result"]


def subprocess_run_with_timeout(
    cmd: list,
    operation: str,
    params: Optional[dict] = None,
    **kwargs
) -> subprocess.CompletedProcess:
    """
    使用自适应超时执行 subprocess.run。

    Args:
        cmd: 命令列表
        operation: 操作名称
        params: 操作参数
        **kwargs: 传递给 subprocess.run 的其他参数

    Returns:
        subprocess.CompletedProcess
    """
    timeout = calculate_adaptive_timeout(operation, params)

    # 确保 capture_output 以避免 stdout 污染
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    # Avoid child processes accidentally reading MCP JSON-RPC from stdin.
    kwargs.setdefault("stdin", subprocess.DEVNULL)

    # Ensure tool subprocesses don't inherit "server stdio" behaviors that are only
    # needed for the MCP transport (e.g., PYTHONUNBUFFERED for JSON-RPC flushing).
    env = kwargs.get("env")
    if env is None:
        env = os.environ.copy()
    else:
        env = dict(env)
    env.pop("PYTHONUNBUFFERED", None)
    kwargs["env"] = env

    # Windows: prevent leaking inheritable handles into nested subprocesses and
    # avoid spawning a console window (can be surprisingly slow under piped stdio).
    if sys.platform == "win32":
        kwargs.setdefault("close_fds", True)
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)

    try:
        return subprocess.run(cmd, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as e:
        logger.warning(
            "Command timed out after %.1fs: %s",
            timeout, " ".join(cmd[:3]) + "..."
        )
        raise TimeoutError(
            f"Operation '{operation}' timed out after {timeout:.0f}s. "
            f"This may indicate a very large input or a hanging process. "
            f"Consider breaking down the operation or increasing timeout limits."
        ) from e
