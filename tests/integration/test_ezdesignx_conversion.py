from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sumo_mcp.mcp_tools.ezdesignx import convert_ezdesignx_json, run_ezdesignx_conversion


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ezdesignx"
FOUR_WAY_SAMPLE = FIXTURE_DIR / "four_way_v1.json"
SIX_WAY_SAMPLE = FIXTURE_DIR / "six_way_v1.json"
SUMO_AVAILABLE = bool(shutil.which("netconvert") and shutil.which("sumo"))

pytestmark = [
    pytest.mark.requires_sumo,
    pytest.mark.skipif(not SUMO_AVAILABLE, reason="requires local netconvert and sumo"),
]


@pytest.mark.parametrize(
    "sample_path",
    [FOUR_WAY_SAMPLE, SIX_WAY_SAMPLE],
    ids=["four_way_v1", "six_way_v1"],
)
def test_topology_conversion_produces_expected_artifacts(tmp_path: Path, sample_path: Path) -> None:
    result = run_ezdesignx_conversion(
        input_json=str(sample_path),
        output_dir=str(tmp_path),
        validation="topology",
    )

    artifacts = result["artifacts"]
    report = result["report"]
    assert result["ok"] is True
    assert result["schema_kind"] == "ezdesignx.config.v1"
    assert result["adapter_mode"] == "legacy-core-minimal-v1"
    assert result["validation_result"]["passed"] is True
    assert Path(artifacts["net_xml"]).exists()
    assert Path(artifacts["sumocfg"]).exists()
    assert Path(artifacts["additional_xml"]).exists()
    assert Path(artifacts["report_json"]).exists()
    additional_text = Path(artifacts["additional_xml"]).read_text(encoding="utf-8")
    assert "ezdesignx.crosswalk" not in additional_text
    assert "ezdesignx.laneStartCap" not in additional_text
    assert "ezdesignx.stopLine" in additional_text
    assert "consumedFeatures" in report
    assert "approximatedFeatures" in report
    assert "unsupportedButSeenFeatures" in report


def test_direct_conversion_returns_plan_and_artifacts(tmp_path: Path) -> None:
    config, plan, artifacts, report, netconvert_result = convert_ezdesignx_json(
        input_json=FOUR_WAY_SAMPLE,
        output_dir=tmp_path,
    )
    assert config.schema_kind == "ezdesignx.config.v1"
    assert len(plan.connections) > 0
    assert artifacts.net_xml.exists()
    assert artifacts.sumocfg.exists()
    assert netconvert_result.returncode == 0, netconvert_result.stderr
    assert report.approximated_features or report.consumed_features
