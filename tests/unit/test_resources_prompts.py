"""Tests for MCP resources, prompts, and packaged guide content."""
from __future__ import annotations

import json

import anyio

from sumo_mcp.resources import provider
from sumo_mcp.server import server


def test_static_resource_content_uses_current_tool_names() -> None:
    stale_names = {
        "inspect_sumo_installation",
        "run_sumo_workflow_v2",
        "start_simulation_session",
        "rl_start_training",
    }
    for name in ("tool-selection.md", "workflows.md", "rl-training.md", "troubleshooting.md"):
        text = provider.read_static_resource(name)
        assert len(text.strip()) > 200
        for stale in stale_names:
            assert stale not in text


def test_diagnostics_and_job_resource_shapes() -> None:
    diagnostics = json.loads(provider.diagnostics_resource())
    assert diagnostics["ok"] is True
    assert "catalog" in diagnostics
    assert any(algo["name"] == "ql" for algo in diagnostics["rl_algorithms"])

    missing = json.loads(provider.job_resource("no-such-job"))
    assert missing["ok"] is False
    assert missing["error"]["code"] == "JOB_NOT_FOUND"


def test_tool_catalog_resource_lists_sixteen_tools() -> None:
    text = provider.tool_catalog_resource()
    for tool_name in provider.PUBLIC_TOOLS:
        assert f"`{tool_name}`" in text
    assert text.count("- `") == 16


def test_fastmcp_resources_and_prompts_registered() -> None:
    async def run() -> None:
        resources = await server.list_resources()
        templates = await server.list_resource_templates()
        prompts = await server.list_prompts()

        uris = {str(r.uri) for r in resources}
        assert {
            "sumo://diagnostics",
            "sumo://tool-catalog",
            "sumo://commands",
            "sumo://guide/tool-selection",
            "sumo://guide/workflows",
            "sumo://guide/rl-training",
            "sumo://guide/troubleshooting",
        } <= uris
        assert {str(t.uriTemplate) for t in templates} == {"sumo://jobs/{job_id}"}
        assert {
            "build-simulation-from-scratch",
            "import-osm-area",
            "optimize-signals",
            "rl-train-and-evaluate",
            "analyze-simulation-outputs",
        } <= {p.name for p in prompts}

        tool_catalog = await server.read_resource("sumo://tool-catalog")
        assert "manage_rl_task" in tool_catalog[0].content

        prompt = await server.get_prompt("rl-train-and-evaluate", {"scenario_or_net": "single-intersection"})
        assert "manage_rl_task" in prompt.messages[0].content.text

    anyio.run(run)
