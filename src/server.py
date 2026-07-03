"""Backward-compatible launcher shim (v0.1 entry point).

v0.1 clients start the server with ``python src/server.py`` (see start_server.*).
The implementation moved to the ``sumo_mcp`` package in v0.2; this shim keeps the
old invocation working. Prefer ``sumo-mcp`` (console script) or ``python -m sumo_mcp``.
"""

import sys
from pathlib import Path

# Make ``sumo_mcp`` importable when running from a source checkout without install.
_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sumo_mcp.server import main, server  # noqa: E402,F401  (server re-exported for compat)

if __name__ == "__main__":
    main()
