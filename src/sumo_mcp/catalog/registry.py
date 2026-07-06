"""Runtime SUMO command registry.

Merges three layers into one whitelist:

1. curated binaries (tier 1)   - the 14 core SUMO executables;
2. curated tool scripts (tier 1) - ~50 industry-relevant scripts with metadata;
3. discovered tool scripts (tier 3) - every other ``*.py`` under
   ``$SUMO_HOME/tools`` found at runtime.

The registry is the single source of truth for what ``run_sumo_binary`` /
``run_sumo_tool`` may execute: anything not resolvable here is rejected.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from sumo_mcp.catalog.curated import CURATED_BINARIES, CURATED_TOOLS
from sumo_mcp.utils.sumo import find_sumo_binary, find_sumo_tools_dir


@dataclass
class CommandSpec:
    """One executable SUMO command (native binary or Python tool script)."""

    name: str            # "netconvert" or "randomTrips.py" or "visualization/plot_net_dump.py"
    kind: str            # "binary" | "tool"
    tier: int            # 1 = curated, 3 = runtime-discovered
    category: str
    description: str
    available: bool
    path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Directories under tools/ that contain libraries, tests or interactive junk —
# not standalone CLI commands. Their scripts are excluded from tier-3 discovery.
_EXCLUDED_DIRS = frozenset({
    "__pycache__", "tests", "test", "purgatory", "devel", "game",
    "build_config", "neteditTestFunctions", "lib", "sumolib", "traci",
    "libsumo", "libtraci", "data", "webWizard",
})

_HELP_TIMEOUT_S = 20
_HELP_MAX_CHARS = 8000

_lock = threading.Lock()
_catalog_cache: Optional[Dict[str, CommandSpec]] = None
_help_cache: Dict[str, str] = {}


def _resolve_tools_dir() -> Optional[Path]:
    tools_dir = find_sumo_tools_dir()
    if not tools_dir:
        return None
    try:
        return Path(tools_dir).resolve()
    except OSError:
        return None


def _fenced_script_path(tools_dir: Path, name: str) -> Optional[Path]:
    """Resolve a tools-relative script name, refusing anything that escapes
    the tools directory (``../``, absolute paths, symlink tricks)."""
    if Path(name).is_absolute():
        return None
    try:
        candidate = (tools_dir / name).resolve()
        candidate.relative_to(tools_dir)
    except (OSError, ValueError):
        return None
    return candidate


def _build_catalog() -> Dict[str, CommandSpec]:
    catalog: Dict[str, CommandSpec] = {}

    for name, (category, description) in CURATED_BINARIES.items():
        path = find_sumo_binary(name)
        catalog[name] = CommandSpec(
            name=name, kind="binary", tier=1, category=category,
            description=description, available=path is not None, path=path,
        )

    tools_dir = _resolve_tools_dir()

    for name, (category, description) in CURATED_TOOLS.items():
        script_path: Optional[Path] = None
        if tools_dir is not None:
            resolved = _fenced_script_path(tools_dir, name)
            if resolved is not None and resolved.is_file():
                script_path = resolved
        catalog[name] = CommandSpec(
            name=name, kind="tool", tier=1, category=category,
            description=description, available=script_path is not None,
            path=str(script_path) if script_path else None,
        )

    if tools_dir is not None:
        for script in sorted(tools_dir.rglob("*.py")):
            rel_parts = script.relative_to(tools_dir).parts
            if any(part in _EXCLUDED_DIRS for part in rel_parts[:-1]):
                continue
            if script.name.startswith("_"):
                continue
            rel_name = "/".join(rel_parts)
            if rel_name in catalog:
                continue
            catalog[rel_name] = CommandSpec(
                name=rel_name, kind="tool", tier=3, category="uncategorized",
                description="", available=True, path=str(script),
            )

    return catalog


def get_catalog(refresh: bool = False) -> Dict[str, CommandSpec]:
    """Return the (cached) command catalog, rebuilding it when asked."""
    global _catalog_cache
    with _lock:
        if _catalog_cache is None or refresh:
            _catalog_cache = _build_catalog()
        return _catalog_cache


def list_commands(
    kind: Optional[str] = None,
    tier: Optional[int] = None,
    search: Optional[str] = None,
    include_unavailable: bool = True,
) -> List[Dict[str, Any]]:
    """Filterable view over the catalog, envelope-ready dicts."""
    needle = search.lower() if search else None
    results: List[Dict[str, Any]] = []
    for spec in get_catalog().values():
        if kind is not None and spec.kind != kind:
            continue
        if tier is not None and spec.tier != tier:
            continue
        if not include_unavailable and not spec.available:
            continue
        if needle is not None:
            haystack = f"{spec.name} {spec.description} {spec.category}".lower()
            if needle not in haystack:
                continue
        results.append(spec.to_dict())
    return results


def resolve_command(name: str, kind: Optional[str] = None) -> Optional[CommandSpec]:
    """Whitelist lookup. Returns None for unknown names, kind mismatches and
    anything that would escape the SUMO installation (never constructs paths
    from unvetted input)."""
    spec = get_catalog().get(name)
    if spec is None:
        return None
    if kind is not None and spec.kind != kind:
        return None
    return spec


def describe_command(name: str, refresh: bool = False) -> Dict[str, Any]:
    """Catalog entry plus (cached) ``--help`` output for the command."""
    spec = resolve_command(name)
    if spec is None:
        return {
            "name": name,
            "error": f"Unknown command: {name!r}. Use list_sumo_commands to see the whitelist.",
        }

    result = spec.to_dict()
    if not spec.available or spec.path is None:
        result["error"] = (
            f"Command {name!r} is not available in this SUMO installation "
            "(binary not found or script missing)."
        )
        return result

    with _lock:
        cached = None if refresh else _help_cache.get(name)
    if cached is None:
        if spec.kind == "binary":
            argv = [spec.path, "--help"]
        else:
            argv = [sys.executable, spec.path, "--help"]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=_HELP_TIMEOUT_S,
            )
            # Some tools print help to stderr and/or exit non-zero; take
            # whatever output exists rather than failing on the return code.
            cached = (proc.stdout or proc.stderr or "").strip()
            if not cached:
                cached = f"<no --help output; exit code {proc.returncode}>"
        except subprocess.TimeoutExpired:
            cached = "<--help timed out>"
        except OSError as exc:
            cached = f"<failed to execute --help: {exc}>"
        with _lock:
            _help_cache[name] = cached

    if len(cached) > _HELP_MAX_CHARS:
        cached = cached[:_HELP_MAX_CHARS] + "\n... [truncated]"
    result["help_text"] = cached
    return result
