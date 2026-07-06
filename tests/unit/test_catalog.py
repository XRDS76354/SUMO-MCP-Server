"""Unit tests for the SUMO command catalog (no SUMO installation required)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import sumo_mcp.catalog.registry as reg
from sumo_mcp.catalog.curated import CURATED_BINARIES, CURATED_TOOLS, GUI_COMMANDS


@pytest.fixture(autouse=True)
def _fresh_catalog(monkeypatch: pytest.MonkeyPatch):
    """Isolate the module-level caches for every test."""
    monkeypatch.setattr(reg, "_catalog_cache", None)
    monkeypatch.setattr(reg, "_help_cache", {})
    yield


def _fake_tools_tree(root: Path) -> Path:
    tools = root / "tools"
    (tools / "route").mkdir(parents=True)
    (tools / "__pycache__").mkdir()
    (tools / "purgatory").mkdir()
    (tools / "randomTrips.py").write_text("# fake\n")
    (tools / "route" / "cutRoutes.py").write_text("# fake\n")
    (tools / "route" / "newTool.py").write_text("# fake tier-3\n")
    (tools / "route" / "_helper.py").write_text("# private, excluded\n")
    (tools / "__pycache__" / "junk.py").write_text("")
    (tools / "purgatory" / "old.py").write_text("")
    return tools


# --- curated table integrity -------------------------------------------------


def test_curated_binaries_cover_all_fourteen() -> None:
    expected = {
        "sumo", "sumo-gui", "netedit", "netconvert", "netgenerate", "polyconvert",
        "duarouter", "jtrrouter", "marouter", "od2trips", "dfrouter",
        "activitygen", "emissionsMap", "emissionsDrivingCycle",
    }
    assert set(CURATED_BINARIES) == expected


def test_curated_tools_selection_quality() -> None:
    assert len(CURATED_TOOLS) >= 40, "curated tier-1 script set shrank below spec"
    for must_have in ("randomTrips.py", "routeSampler.py", "osmGet.py", "osmBuild.py",
                      "tlsCycleAdaptation.py", "tlsCoordinator.py", "assign/duaIterate.py",
                      "xml/xml2csv.py", "traceExporter.py"):
        assert must_have in CURATED_TOOLS
    for name, (category, description) in CURATED_TOOLS.items():
        assert category and description, f"curated entry {name} missing metadata"
    assert not set(CURATED_BINARIES) & set(CURATED_TOOLS)
    assert GUI_COMMANDS <= (set(CURATED_BINARIES) | set(CURATED_TOOLS))


# --- catalog building --------------------------------------------------------


def test_catalog_survives_missing_sumo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: None)

    catalog = reg.get_catalog(refresh=True)
    assert set(CURATED_BINARIES) <= set(catalog)
    assert set(CURATED_TOOLS) <= set(catalog)
    assert all(not spec.available for spec in catalog.values())
    assert all(spec.tier == 1 for spec in catalog.values())  # no tier-3 without tools dir


def test_catalog_discovers_tier3_and_excludes_junk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _fake_tools_tree(tmp_path)
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: str(tools))

    catalog = reg.get_catalog(refresh=True)

    # curated names that exist on disk resolve with a path
    assert catalog["randomTrips.py"].available is True
    assert catalog["randomTrips.py"].tier == 1
    assert catalog["route/cutRoutes.py"].available is True
    # curated names missing from this (fake) install remain listed, unavailable
    assert catalog["osmGet.py"].available is False and catalog["osmGet.py"].path is None
    # new script discovered as tier 3
    assert catalog["route/newTool.py"].tier == 3
    assert catalog["route/newTool.py"].description == ""
    # exclusions: private files, __pycache__, purgatory
    assert "route/_helper.py" not in catalog
    assert not any("__pycache__" in name or "purgatory" in name for name in catalog)


def test_catalog_is_cached_until_refresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _fake_tools_tree(tmp_path)
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: str(tools))

    first = reg.get_catalog(refresh=True)
    (tools / "route" / "later.py").write_text("# added after build\n")
    assert "route/later.py" not in reg.get_catalog()
    assert reg.get_catalog() is first
    assert "route/later.py" in reg.get_catalog(refresh=True)


# --- whitelist resolution / path fencing --------------------------------------


def test_resolve_command_rejects_unknown_and_kind_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _fake_tools_tree(tmp_path)
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: f"/fake/bin/{name}")
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: str(tools))
    reg.get_catalog(refresh=True)

    assert reg.resolve_command("netconvert") is not None
    assert reg.resolve_command("randomTrips.py", kind="tool") is not None
    assert reg.resolve_command("netconvert", kind="tool") is None
    assert reg.resolve_command("randomTrips.py", kind="binary") is None
    assert reg.resolve_command("rm") is None
    assert reg.resolve_command("../../etc/passwd") is None
    assert reg.resolve_command("/etc/passwd") is None


def test_fenced_script_path_blocks_traversal(tmp_path: Path) -> None:
    tools = _fake_tools_tree(tmp_path)
    (tmp_path / "evil.py").write_text("# outside tools\n")

    resolved = tools.resolve()
    assert reg._fenced_script_path(resolved, "randomTrips.py") is not None
    assert reg._fenced_script_path(resolved, "../evil.py") is None
    assert reg._fenced_script_path(resolved, str(tmp_path / "evil.py")) is None
    assert reg._fenced_script_path(resolved, "route/../../evil.py") is None


# --- list_commands filters ----------------------------------------------------


def test_list_commands_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _fake_tools_tree(tmp_path)
    monkeypatch.setattr(reg, "find_sumo_binary",
                        lambda name: f"/fake/bin/{name}" if name == "sumo" else None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: str(tools))
    reg.get_catalog(refresh=True)

    assert all(c["kind"] == "binary" for c in reg.list_commands(kind="binary"))
    assert all(c["tier"] == 3 for c in reg.list_commands(tier=3))
    hits = reg.list_commands(search="random")
    assert any(c["name"] == "randomTrips.py" for c in hits)
    assert not reg.list_commands(search="zzz-no-such-thing")
    available_only = reg.list_commands(include_unavailable=False)
    assert {c["name"] for c in available_only if c["kind"] == "binary"} == {"sumo"}


# --- describe_command ----------------------------------------------------------


def test_describe_unknown_and_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: None)
    reg.get_catalog(refresh=True)

    assert "error" in reg.describe_command("no_such_thing")
    described = reg.describe_command("netconvert")
    assert described["available"] is False and "error" in described


def test_describe_tolerates_nonzero_help_and_caches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _fake_tools_tree(tmp_path)
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: str(tools))
    reg.get_catalog(refresh=True)

    calls = {"n": 0}

    def fake_run(argv, **kwargs):
        calls["n"] += 1

        class P:
            returncode = 1
            stdout = ""
            stderr = "usage: randomTrips.py [options]"
        return P()

    monkeypatch.setattr(reg.subprocess, "run", fake_run)

    described = reg.describe_command("randomTrips.py")
    assert described["help_text"] == "usage: randomTrips.py [options]"
    reg.describe_command("randomTrips.py")
    assert calls["n"] == 1  # cached
    reg.describe_command("randomTrips.py", refresh=True)
    assert calls["n"] == 2


def test_describe_handles_help_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _fake_tools_tree(tmp_path)
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: str(tools))
    reg.get_catalog(refresh=True)

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1)

    monkeypatch.setattr(reg.subprocess, "run", fake_run)
    described = reg.describe_command("randomTrips.py")
    assert described["help_text"] == "<--help timed out>"


def test_describe_truncates_long_help(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = _fake_tools_tree(tmp_path)
    monkeypatch.setattr(reg, "find_sumo_binary", lambda name: None)
    monkeypatch.setattr(reg, "find_sumo_tools_dir", lambda: str(tools))
    reg.get_catalog(refresh=True)

    def fake_run(argv, **kwargs):
        class P:
            returncode = 0
            stdout = "x" * 20000
            stderr = ""
        return P()

    monkeypatch.setattr(reg.subprocess, "run", fake_run)
    described = reg.describe_command("randomTrips.py")
    assert described["help_text"].endswith("... [truncated]")
    assert len(described["help_text"]) < 9000
