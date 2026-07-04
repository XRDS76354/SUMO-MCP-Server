"""codex-review regression: ezdesignX binary discovery must honor SUMO_HOME.

A supported install may expose SUMO only via SUMO_HOME (macOS framework,
pip eclipse-sumo without PATH wrappers). ``_find_binary`` used to consult
``shutil.which`` only, failing those installs.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from sumo_mcp.mcp_tools.ezdesignx import _find_binary


def _make_fake_binary(bin_dir: Path, name: str) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / (f"{name}.exe" if sys.platform == "win32" else name)
    exe.write_bytes(b"#!/bin/sh\nexit 0\n")
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe


def test_explicit_path_wins(tmp_path: Path) -> None:
    assert _find_binary(str(tmp_path / "custom-netconvert"), "netconvert") == str(tmp_path / "custom-netconvert")


def test_resolves_via_sumo_home_when_path_is_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "sumo-home"
    expected = _make_fake_binary(fake_home / "bin", "netconvert")

    monkeypatch.setenv("SUMO_HOME", str(fake_home))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    # Neutralize sumolib's per-binary env override, if set in the outer env.
    monkeypatch.delenv("NETCONVERT_BINARY", raising=False)

    resolved = Path(_find_binary(None, "netconvert"))
    assert resolved == expected


def test_missing_binary_raises_actionable_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUMO_HOME", str(tmp_path / "nonexistent-home"))
    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    monkeypatch.delenv("NETCONVERT_BINARY", raising=False)

    with pytest.raises(FileNotFoundError):
        _find_binary(None, "netconvert")
