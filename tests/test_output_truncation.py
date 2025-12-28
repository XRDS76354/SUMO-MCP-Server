import subprocess


def test_truncate_text_keeps_tail_and_marks_truncation() -> None:
    from utils.output import truncate_text

    text = "0123456789"
    truncated = truncate_text(text, max_chars=4)
    assert "truncated" in truncated.lower()
    assert truncated.endswith("6789")


def test_subprocess_tool_output_is_truncated(monkeypatch) -> None:
    from mcp_tools import network as network_module
    from utils.output import DEFAULT_MAX_OUTPUT_CHARS

    long_stdout = "x" * (DEFAULT_MAX_OUTPUT_CHARS + 10)

    monkeypatch.setattr(network_module.sumolib, "checkBinary", lambda _: "/usr/bin/netconvert")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout=long_stdout, stderr="")

    monkeypatch.setattr(network_module, "subprocess_run_with_timeout", fake_run)

    result = network_module.netconvert("in.osm.xml", "out.net.xml")
    assert isinstance(result, str)
    assert "<truncated" in result
    assert long_stdout[-10:] in result

