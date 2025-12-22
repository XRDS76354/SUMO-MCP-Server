import glob
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import sumolib

logger = logging.getLogger(__name__)


def find_sumo_binary(name: str) -> str:
    """
    Find a SUMO binary by name.

    Resolution order:
    1) `sumolib.checkBinary()` (respects SUMO_HOME when set)
    2) `shutil.which()` (respects PATH)

    Returns:
        The resolved executable path (preferred) or the original name as a fallback.
    """
    try:
        resolved = sumolib.checkBinary(name)
    except Exception:
        resolved = name

    if resolved == name or not resolved:
        which = shutil.which(name)
        return which or name

    return resolved


def _candidate_sumo_home_from_binary(sumo_binary: str) -> Optional[Path]:
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
            import winreg  # type: ignore[import-not-found]

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
