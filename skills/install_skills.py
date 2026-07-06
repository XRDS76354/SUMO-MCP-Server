#!/usr/bin/env python3
"""Install SUMO-MCP skills into Codex and/or Claude project skill directories."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"


def _skill_dirs() -> Iterable[Path]:
    return sorted(path for path in SRC.iterdir() if (path / "SKILL.md").is_file())


def _copy_skill(src_dir: Path, target_root: Path) -> Path:
    dest = target_root / src_dir.name
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_dir / "SKILL.md", dest / "SKILL.md")
    return dest


def install(target: str, codex_dir: Path, claude_dir: Path) -> list[Path]:
    if not SRC.is_dir():
        raise FileNotFoundError(f"skills source directory not found: {SRC}")

    roots: list[Path] = []
    if target in ("codex", "both"):
        roots.append(codex_dir)
    if target in ("claude", "both"):
        roots.append(claude_dir)

    installed: list[Path] = []
    for root in roots:
        for skill_dir in _skill_dirs():
            installed.append(_copy_skill(skill_dir, root))
    return installed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("codex", "claude", "both"), default="both")
    parser.add_argument("--codex-dir", type=Path, default=Path(".codex") / "skills")
    parser.add_argument("--claude-dir", type=Path, default=Path(".claude") / "skills")
    args = parser.parse_args()

    installed = install(args.target, args.codex_dir, args.claude_dir)
    for path in installed:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
