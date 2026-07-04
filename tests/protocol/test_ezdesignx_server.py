from __future__ import annotations

from importlib import import_module
from pathlib import Path


def test_dedicated_ezdesignx_tool_delegates_to_summary_wrapper(tmp_path: Path, monkeypatch) -> None:
    server_module = import_module("sumo_mcp.server")
    calls: list[dict[str, object]] = []

    def fake_summary_wrapper(**kwargs: object) -> str:
        calls.append(kwargs)
        return "converted"

    monkeypatch.setattr(server_module, "convert_ezdesignx_network_summary", fake_summary_wrapper)

    result = server_module.convert_ezdesignx_network(
        input_json="fixture.jsonc",
        output_dir=str(tmp_path),
        validation="strict",
        netconvert_bin="netconvert-custom",
        sumo_bin="sumo-custom",
        sumo_gui_bin="sumo-gui-custom",
    )

    # v0.2: structured envelope; the v0.1 string lives in `summary`.
    assert result["ok"] is True
    assert result["summary"] == "converted"
    assert calls == [
        {
            "input_json": "fixture.jsonc",
            "output_dir": str(tmp_path),
            "validation": "strict",
            "netconvert_bin": "netconvert-custom",
            "sumo_bin": "sumo-custom",
            "sumo_gui_bin": "sumo-gui-custom",
        }
    ]


def test_manage_network_convert_ezdesignx_delegates_to_summary_wrapper(tmp_path: Path, monkeypatch) -> None:
    server_module = import_module("sumo_mcp.server")
    calls: list[dict[str, object]] = []

    def fake_summary_wrapper(**kwargs: object) -> str:
        calls.append(kwargs)
        return "converted"

    monkeypatch.setattr(server_module, "convert_ezdesignx_network_summary", fake_summary_wrapper)

    result = server_module.manage_network(
        action="convert_ezdesignx",
        output_file=str(tmp_path),
        params={
            "input_json": "fixture.jsonc",
            "validation": "basic",
            "netconvert_bin": "netconvert-custom",
            "sumo_bin": "sumo-custom",
            "sumo_gui_bin": "sumo-gui-custom",
        },
    )

    # v0.2: structured envelope; the v0.1 string lives in `summary`.
    assert result["ok"] is True
    assert result["summary"] == "converted"
    assert calls == [
        {
            "input_json": "fixture.jsonc",
            "output_dir": str(tmp_path),
            "validation": "basic",
            "netconvert_bin": "netconvert-custom",
            "sumo_bin": "sumo-custom",
            "sumo_gui_bin": "sumo-gui-custom",
        }
    ]


def test_manage_network_convert_ezdesignx_requires_input_json(tmp_path: Path) -> None:
    server_module = import_module("sumo_mcp.server")

    result = server_module.manage_network(
        action="convert_ezdesignx",
        output_file=str(tmp_path),
        params={},
    )

    # v0.2: structured error envelope; the v0.1 error string lives in `summary`.
    assert result["ok"] is False
    assert result["summary"] == "Error: input_json required for convert_ezdesignx action"
    assert result["error"]["code"] == "INVALID_ARGUMENT"
