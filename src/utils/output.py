from __future__ import annotations

import os

DEFAULT_MAX_OUTPUT_CHARS = int(os.environ.get("SUMO_MCP_MAX_OUTPUT_CHARS", "8000"))


def truncate_text(text: str | None, max_chars: int = DEFAULT_MAX_OUTPUT_CHARS) -> str:
    """Truncate large stdout/stderr strings to keep MCP responses bounded."""
    if not text:
        return ""

    if max_chars <= 0:
        return ""

    if len(text) <= max_chars:
        return text

    original_len = len(text)
    tail = text[-max_chars:]
    truncated = original_len - max_chars
    return (
        f"... <truncated {truncated} chars; showing last {max_chars} of {original_len}> ...\n"
        f"{tail}"
    )

