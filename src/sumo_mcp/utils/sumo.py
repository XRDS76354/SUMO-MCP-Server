import glob
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import sumolib

logger = logging.getLogger(__name__)


def find_sumo_binary(name: str) -> Optional[str]:
    """
    Find a SUMO binary by name.

    Resolution order:
    1) `sumolib.checkBinary()` (respects SUMO_HOME when set)
    2) `shutil.which()` (respects PATH)

    Returns:
        The resolved absolute executable path, or None if it cannot be located.
    """
    resolved: Optional[str] = None
    try:
        candidate = sumolib.checkBinary(name)
    except (SystemExit, OSError, FileNotFoundError, ImportError) as exc:
        logger.debug("sumolib.checkBinary failed for %s: %s", name, exc)
        candidate = None

    if candidate and candidate != name:
        resolved = candidate

    if resolved:
        # Trust sumolib's result if it looks like an absolute path
        # Use os.path.isabs for cross-platform compatibility (handles /usr/bin on Windows)
        if os.path.isabs(resolved):
            return resolved
        return shutil.which(resolved)

    return shutil.which(name)


def _candidate_sumo_home_from_binary(sumo_binary: Optional[str]) -> Optional[Path]:
    if not sumo_binary:
        return None

    path = Path(sumo_binary)
    if not path.is_absolute():
        return None

    # Typical layout: <SUMO_HOME>/bin/sumo(.exe)
    if path.parent.name.lower() == "bin":
        return path.parent.parent
    return None


def find_sumo_home() -> Optional[str]:
    """
    Resolve SUMO_HOME.

    Priority:
    1) SUMO_HOME environment variable
    2) Derive from `sumo` executable location when it matches <SUMO_HOME>/bin/sumo
    3) Platform-specific common locations
    """
    env_home = os.environ.get("SUMO_HOME")
    if env_home:
        home = Path(env_home).expanduser()
        if home.exists():
            logger.debug("Resolved SUMO_HOME from env: %s", home)
            return str(home)
        logger.debug("SUMO_HOME env set but path does not exist: %s", home)

    sumo_binary = find_sumo_binary("sumo")
    candidate = _candidate_sumo_home_from_binary(sumo_binary)
    if candidate and candidate.exists():
        logger.debug("Resolved SUMO_HOME from sumo binary: %s", candidate)
        return str(candidate)

    if sys.platform == "win32":
        win_paths = [
            Path("C:/Program Files/Eclipse/sumo"),
            Path("C:/Program Files (x86)/Eclipse/sumo"),
            Path("D:/sumo"),
            Path("C:/sumo"),
        ]
        for path in win_paths:
            if path.exists() and (path / "tools").exists():
                logger.debug("Resolved SUMO_HOME from Windows common paths: %s", path)
                return str(path)

        # Windows Registry (optional)
        try:
            import winreg

            key_path = r"SOFTWARE\Eclipse\SUMO"
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    key = winreg.OpenKey(hive, key_path)
                    install_path, _ = winreg.QueryValueEx(key, "InstallPath")
                    winreg.CloseKey(key)
                    if not install_path:
                        continue
                    reg_home = Path(install_path)
                    if reg_home.exists() and (reg_home / "tools").exists():
                        logger.debug("Resolved SUMO_HOME from Windows Registry: %s", reg_home)
                        return str(reg_home)
                except FileNotFoundError:
                    continue
                except OSError:
                    continue
        except ImportError:
            pass

    if sys.platform == "darwin":
        patterns = [
            "/usr/local/Cellar/sumo/*/share/sumo",
            "/opt/homebrew/Cellar/sumo/*/share/sumo",
        ]
        matches: list[str] = []
        for pattern in patterns:
            matches.extend(glob.glob(pattern))

        for raw in sorted(matches, reverse=True):
            home = Path(raw)
            if home.exists() and (home / "tools").exists():
                logger.debug("Resolved SUMO_HOME from Homebrew cellar: %s", home)
                return str(home)

    linux_home = Path("/usr/share/sumo")
    if linux_home.exists() and (linux_home / "tools").exists():
        logger.debug("Resolved SUMO_HOME from Linux common path: %s", linux_home)
        return str(linux_home)

    return None


def find_sumo_tools_dir() -> Optional[str]:
    """Return the SUMO tools directory if it can be located."""
    sumo_home = find_sumo_home()
    if not sumo_home:
        return None

    tools_dir = Path(sumo_home) / "tools"
    if tools_dir.exists():
        return str(tools_dir)

    return None


def find_sumo_tool_script(script_name: str) -> Optional[str]:
    """Find a SUMO python tool script (e.g. randomTrips.py) under SUMO tools dir."""
    tools_dir = find_sumo_tools_dir()
    if not tools_dir:
        return None

    script = Path(tools_dir) / script_name
    if script.exists():
        return str(script)

    return None


def build_sumo_diagnostics(binary_name: str = "sumo") -> str:
    """
    Build a short, multi-line diagnostic string about SUMO discovery.

    This is intended for inclusion in user-facing error messages.
    """
    env_home = os.environ.get("SUMO_HOME") or "Not Set"
    which_bin = shutil.which(binary_name) or "Not Found"
    detected_home = find_sumo_home() or "Not Found"
    tools_dir = find_sumo_tools_dir() or "Not Found"

    return "\n".join(
        [
            "Diagnostics:",
            f"  - SUMO_HOME env: {env_home}",
            f"  - which({binary_name}): {which_bin}",
            f"  - find_sumo_home(): {detected_home}",
            f"  - find_sumo_tools_dir(): {tools_dir}",
        ]
    )
