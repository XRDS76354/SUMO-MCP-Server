import subprocess


def test_manage_network_spider_excludes_grid_flags(monkeypatch) -> None:
    import server as server_module
    from mcp_tools import network as network_module
    from utils import timeout as timeout_module

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(timeout_module.subprocess, "run", fake_run)
    monkeypatch.setattr(network_module.sumolib, "checkBinary", lambda _: "/usr/bin/netgenerate")

    server_module.manage_network(
        "generate",
        "out.net.xml",
        {"spider": True, "grid": True, "grid_number": 9},
    )

    assert calls
    cmd = calls[0]
    assert "--spider" in cmd
    assert "--grid" not in cmd
    assert "--grid.number" not in cmd


def test_manage_network_grid_excludes_spider_flags(monkeypatch) -> None:
    import server as server_module
    from mcp_tools import network as network_module
    from utils import timeout as timeout_module

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(timeout_module.subprocess, "run", fake_run)
    monkeypatch.setattr(network_module.sumolib, "checkBinary", lambda _: "/usr/bin/netgenerate")

    server_module.manage_network(
        "generate",
        "out.net.xml",
        {},
    )

    assert calls
    cmd = calls[0]
    assert "--grid" in cmd
    assert "--spider" not in cmd

