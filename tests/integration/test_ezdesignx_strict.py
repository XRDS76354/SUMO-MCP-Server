from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sumo_mcp.mcp_tools.ezdesignx import run_ezdesignx_conversion


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ezdesignx"
MIN_TRANSITION_FIXTURE = FIXTURE_DIR / "min_transition_fixture.json"


@pytest.mark.skipif(
    not (shutil.which("netconvert") and shutil.which("sumo")),
    reason="requires local netconvert and sumo",
)
def test_strict_conversion_reports_metrics(tmp_path: Path) -> None:
    result = run_ezdesignx_conversion(
        input_json=str(MIN_TRANSITION_FIXTURE),
        output_dir=str(tmp_path),
        validation="strict",
    )

    strict_metrics = result["validation_result"]["strictMetrics"]
    assert result["ok"] is True
    assert result["validation_result"]["passed"] is True
    assert strict_metrics["passed"] is True
    assert "maxAngleError" in strict_metrics
    assert "maxLengthError" in strict_metrics
    assert "maxLaneWidthError" in strict_metrics
