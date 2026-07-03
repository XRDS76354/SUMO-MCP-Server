from __future__ import annotations

import inspect
import subprocess
import threading
from typing import Any, Callable, Optional


def ensure_traci_start_stdout_suppressed() -> None:
    """
    Ensure `traci.start()` defaults to `stdout=subprocess.DEVNULL`.

    Why:
      MCP uses JSON-RPC over stdio; any SUMO/TraCI stdout output can corrupt the
      protocol stream and cause clients to hang or show `undefined`.

    This wrapper is:
      - idempotent (won't double-wrap)
      - non-invasive (doesn't override an explicit `stdout=...`)
      - best-effort (no-op if `traci` isn't available or doesn't support `stdout`)
    """
    try:
        import traci  # type: ignore
    except Exception:
        return

    start: Optional[Callable[..., Any]] = getattr(traci, "start", None)
    if start is None:
        return

    if getattr(start, "_mcp_stdout_suppressed", False):
        return

    try:
        sig = inspect.signature(start)
    except (TypeError, ValueError):
        # Can't introspect; be conservative.
        return

    supports_stdout = "stdout" in sig.parameters or any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )
    if not supports_stdout:
        return

    original_start = start

    def _start(cmd, *args: Any, **kwargs: Any):
        kwargs.setdefault("stdout", subprocess.DEVNULL)
        return original_start(cmd, *args, **kwargs)

    setattr(_start, "_mcp_stdout_suppressed", True)
    setattr(_start, "_mcp_original_start", original_start)

    traci.start = _start  # type: ignore[attr-defined]


def traci_close_best_effort(timeout_s: float = 5.0) -> bool:
    """
    Best-effort close TraCI without risking an indefinite hang.

    Returns:
        True if `traci.close()` finished within timeout_s, else False.
    """
    try:
        import traci  # type: ignore
    except Exception:
        return True

    done = threading.Event()

    def _close() -> None:
        try:
            traci.close()
        except Exception:
            pass
        finally:
            done.set()

    thread = threading.Thread(target=_close, daemon=True, name="sumo-mcp:traci.close")
    thread.start()
    return done.wait(timeout_s)
