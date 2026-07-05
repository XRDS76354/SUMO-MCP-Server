"""codex-review regression: legacy_result must classify every real v0.1 failure string.

The failure strings below are the exhaustive inventory of what
mcp_tools/{network,route,signal,simulation,analysis,rl}.py and
workflows/{sim_gen,signal_opt}.py actually return on failure. If a wrapper
gains a new failure convention, add it here AND to models._ERROR_PREFIX.
"""
from __future__ import annotations

import pytest

from sumo_mcp.models import ErrorCode, legacy_result

REAL_FAILURE_STRINGS = [
    # subprocess CalledProcessError conventions ("<tool> failed.")
    "Netconvert failed.\nStderr: x\nStdout: y",
    "Netgenerate failed.\nStderr: x",
    "osmGet failed.\nStderr: x",
    "randomTrips failed.\nStderr: x",
    "duarouter failed.\nStderr: x",
    "od2trips failed.\nStderr: x",
    "tlsCycleAdaptation failed.\nStderr: x",
    "tlsCoordinator failed.\nStderr: x",
    # generic exception conventions ("<tool> execution error:")
    "Netconvert execution error: boom",
    "duarouter execution error: boom",
    "tlsCoordinator execution error: boom",
    # runtime error conventions
    "Simulation error: TraCIException: connection closed",
    "Analysis error: parse failed",
    # "Error..." conventions
    "Error: File fcd.xml not found.",
    "Error finding netconvert: nope",
    "Error: Config file not found at x.sumocfg",
    "Error: Network file not found at n.net.xml",
    "Error: Could not locate SUMO executable (`sumo`).",
    # RL
    "Training failed: ModuleNotFoundError: No module named 'sumo_rl'",
    # workflow step conventions
    "Step 1 Failed: Netgenerate failed.",
    "Step 4 Failed: Could not write config file. boom",
    "Step 6 Failed: FCD file not generated.",
    "Baseline Simulation Failed: Simulation error: x",
    "Optimized Simulation Failed: Simulation error: x",
    # adaptive timeout framework
    "Operation 'simulation' timed out after 60s",
    "Fatal: something",
]

REAL_SUCCESS_STRINGS = [
    "Netconvert successful.\nStdout: ok",
    "Netgenerate successful.\nStdout: ok",
    "osmGet successful.\nStdout: ok",
    "randomTrips successful.\nStdout: ok",
    "duarouter successful.\nStdout: ok",
    "od2trips successful.\nStdout: ok",
    "tlsCycleAdaptation successful.\nStdout: ok",
    "tlsCoordinator successful.\nStdout: ok",
    "Workflow Completed Successfully.\n\nSimulation Output:\nx",
    "Simulation completed: 100 steps",
    "Analysis Result:\nTotal Data Points: 10\nAverage Speed: 5.00 m/s",
    "No vehicle data found in FCD output.",
    "Episode 1/1: Total Reward = -5.00",
    "Successfully connected to SUMO.",
    "Active vehicles: ['v0']",
    "['scenario-a', 'scenario-b']",
    "converted",
]


@pytest.mark.parametrize("text", REAL_FAILURE_STRINGS, ids=lambda t: t.splitlines()[0][:48])
def test_real_failure_strings_are_flagged(text: str) -> None:
    env = legacy_result("some_tool", text)
    assert env["ok"] is False, f"failure string wrapped as success: {text.splitlines()[0]}"
    assert env["error"]["code"], "failed envelope must carry an error code"
    assert env["summary"] == text, "original text must be preserved verbatim"


@pytest.mark.parametrize("text", REAL_SUCCESS_STRINGS, ids=lambda t: t.splitlines()[0][:48])
def test_real_success_strings_stay_ok(text: str) -> None:
    env = legacy_result("some_tool", text)
    assert env["ok"] is True, f"success string misflagged as failure: {text.splitlines()[0]}"
    assert env["summary"] == text


def test_timeout_failure_maps_to_timeout_code() -> None:
    env = legacy_result("t", "Operation 'simulation' timed out after 60s")
    assert env["error"]["code"] == ErrorCode.TIMEOUT


def test_missing_file_failure_maps_to_file_not_found() -> None:
    env = legacy_result("t", "Error: Network file not found at n.net.xml")
    assert env["error"]["code"] == ErrorCode.FILE_NOT_FOUND
