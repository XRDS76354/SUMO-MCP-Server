import logging
import os
import subprocess
import threading
from typing import Callable, Optional, TypeVar

import traci

from sumo_mcp.utils.sumo import find_sumo_binary

logger = logging.getLogger(__name__)

DEFAULT_TRACI_TIMEOUT_S = float(os.environ.get("SUMO_MCP_TRACI_TIMEOUT_S", "10"))

T = TypeVar("T")


def _run_with_timeout(func: Callable[[], T], timeout_s: float, description: str) -> T:
    result: dict[str, T] = {}
    error: dict[str, Exception] = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["value"] = func()
        except Exception as exc:
            error["error"] = exc
        finally:
            done.set()

    thread = threading.Thread(target=_worker, daemon=True, name=f"sumo-mcp:{description}")
    thread.start()

    if not done.wait(timeout_s):
        raise TimeoutError(f"TimeoutError: {description} timed out after {timeout_s:.1f}s")

    if "error" in error:
        raise error["error"]

    return result["value"]


class SUMOConnection:
    """
    Singleton class to manage the connection to the SUMO server via TraCI.
    """
    _instance: Optional['SUMOConnection'] = None
    _connected: bool

    def __new__(cls) -> "SUMOConnection":
        if cls._instance is None:
            cls._instance = super(SUMOConnection, cls).__new__(cls)
            cls._instance._connected = False
        return cls._instance

    def connect(
        self,
        config_file: Optional[str] = None,
        gui: bool = False,
        port: int = 8813,
        host: str = "localhost",
        timeout_s: float = DEFAULT_TRACI_TIMEOUT_S,
    ) -> None:
        """
        Start SUMO and connect, or connect to an existing instance.
        If config_file is provided, starts a new instance.
        If config_file is None, attempts to connect to existing server at host:port.
        """
        if self._connected:
            logger.info("Already connected to SUMO.")
            return

        try:
            if config_file:
                binary_name = "sumo-gui" if gui else "sumo"
                binary = find_sumo_binary(binary_name)
                if not binary:
                    raise RuntimeError(
                        "Could not locate SUMO executable. "
                        "Please ensure SUMO is installed and either the binary is in PATH or SUMO_HOME is set."
                    )
                # Add --no-step-log to prevent stdout pollution which breaks JSON-RPC
                cmd = [binary, "-c", config_file, "--no-step-log", "true"]
                logger.info(f"Starting SUMO with command: {cmd}")
                _run_with_timeout(
                    lambda: traci.start(cmd, port=port, stdout=subprocess.DEVNULL),
                    timeout_s=timeout_s,
                    description="traci.start",
                )
            else:
                logger.info(f"Connecting to existing SUMO at {host}:{port}")
                _run_with_timeout(
                    lambda: traci.init(host=host, port=port),
                    timeout_s=timeout_s,
                    description="traci.init",
                )

            self._connected = True
            logger.info("Successfully connected to SUMO.")
        except Exception as e:
            logger.error(f"Failed to connect to SUMO: {e}")
            self._connected = False
            try:
                _run_with_timeout(traci.close, timeout_s=timeout_s, description="traci.close")
            except Exception:
                pass
            raise

    def disconnect(self, timeout_s: float = DEFAULT_TRACI_TIMEOUT_S) -> None:
        """Disconnect from SUMO server."""
        if not self._connected:
            return

        try:
            _run_with_timeout(traci.close, timeout_s=timeout_s, description="traci.close")
            logger.info("Disconnected from SUMO.")
        except Exception as e:
            logger.error(f"Error during disconnect: {e}")
        finally:
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def traci_call(self, func: Callable[[], T], description: str, timeout_s: float = DEFAULT_TRACI_TIMEOUT_S) -> T:
        """Run a TraCI call with a soft timeout and disconnect on timeout."""
        if not self.is_connected():
            raise RuntimeError("Not connected to SUMO.")

        try:
            return _run_with_timeout(func, timeout_s=timeout_s, description=description)
        except TimeoutError:
            self._connected = False
            try:
                _run_with_timeout(traci.close, timeout_s=timeout_s, description="traci.close")
            except Exception:
                pass
            raise

    def simulation_step(self, step: float = 0, timeout_s: float = DEFAULT_TRACI_TIMEOUT_S) -> None:
        """Advance the simulation."""
        self.traci_call(lambda: traci.simulationStep(step), description="traci.simulationStep", timeout_s=timeout_s)


# Global instance
connection_manager = SUMOConnection()
