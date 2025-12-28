import subprocess


def test_manage_network_spider_maps_params_into_netgenerate_cmd(monkeypatch) -> None:
    import server as server_module
    from mcp_tools import network as network_module
    from utils import timeout as timeout_module

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(timeout_module.subprocess, "run", fake_run)
    monkeypatch.setattr(network_module.sumolib, "checkBinary", lambda _: "/usr/bin/netgenerate")

    result = server_module.manage_network(
        "generate",
        "out.net.xml",
        {"spider": True, "arms": 5},
    )

    assert isinstance(result, str)
    assert calls, "Expected a netgenerate subprocess call"
    cmd = calls[0]
    assert "--spider" in cmd
    assert "--spider.arm-number" in cmd
    idx = cmd.index("--spider.arm-number")
    assert cmd[idx + 1] == "5"


def test_manage_network_spider_rejects_invalid_arms(monkeypatch) -> None:
    import server as server_module
    from utils import timeout as timeout_module

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(timeout_module.subprocess, "run", fake_run)

    result = server_module.manage_network(
        "generate",
        "out.net.xml",
        {"spider": True, "arms": 0},
    )

    assert "Error" in result
    assert not calls

