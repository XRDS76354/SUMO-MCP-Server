"""SUMO command catalog: curated metadata + runtime discovery + whitelisting."""
from sumo_mcp.catalog.registry import (
    CommandSpec,
    describe_command,
    get_catalog,
    list_commands,
    resolve_command,
)

__all__ = [
    "CommandSpec",
    "describe_command",
    "get_catalog",
    "list_commands",
    "resolve_command",
]
