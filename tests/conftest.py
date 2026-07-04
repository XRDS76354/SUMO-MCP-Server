from __future__ import annotations

import shutil
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _sumo_available() -> bool:
    if shutil.which("sumo"):
        return True
    try:
        from sumo_mcp.utils.sumo import find_sumo_binary

        return bool(find_sumo_binary("sumo"))
    except Exception:
        return False


def _rl_available() -> bool:
    # sumo-rl imports require SUMO_HOME; presence of the module spec is enough
    # to attempt the smoke test (the test itself sets SUMO_HOME if needed).
    return find_spec("sumo_rl") is not None and _sumo_available()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    sumo_ok = _sumo_available()
    rl_ok = _rl_available()
    skip_sumo = pytest.mark.skip(reason="SUMO installation not found (binaries/SUMO_HOME)")
    skip_rl = pytest.mark.skip(reason="RL runtime unavailable (sumo-rl and/or SUMO missing)")
    skip_net = pytest.mark.skip(reason="network-dependent test (enable with -m network)")

    run_network = "network" in config.getoption("-m", default="")

    for item in items:
        if "requires_sumo" in item.keywords and not sumo_ok:
            item.add_marker(skip_sumo)
        if "requires_rl" in item.keywords and not rl_ok:
            item.add_marker(skip_rl)
        if "network" in item.keywords and not run_network:
            item.add_marker(skip_net)
