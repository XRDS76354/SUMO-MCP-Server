from __future__ import annotations

import sys
from pathlib import Path


def _prepend_to_syspath(path: Path) -> None:
    resolved = str(path.resolve())
    existing = [p for p in sys.path if Path(p).resolve() != Path(resolved)]
    sys.path[:] = [resolved, *existing]


_prepend_to_syspath(Path(__file__).resolve().parents[1] / "src")

