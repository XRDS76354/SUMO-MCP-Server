from __future__ import annotations

from pathlib import Path

from sumo_mcp.mcp_tools import ezdesignx as ezdesignx_module
from sumo_mcp.mcp_tools.ezdesignx import build_network_plan, convert_ezdesignx_json, load_and_normalize


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "ezdesignx"
FOUR_WAY_SAMPLE = FIXTURE_DIR / "four_way_v1.json"
SIX_WAY_SAMPLE = FIXTURE_DIR / "six_way_v1.json"
MIN_TRANSITION_FIXTURE = FIXTURE_DIR / "min_transition_fixture.json"


def test_ezdesignx_module_is_self_contained() -> None:
    module_text = Path(ezdesignx_module.__file__).read_text(encoding="utf-8")
    assert "test/ezdesignx_to_sumo" not in module_text
    assert "junctionx_to_sumo" not in module_text
    assert "convert_junctionx_" not in module_text


def test_load_four_way_v1_config_as_legacy_core_input() -> None:
    config, report = load_and_normalize(FOUR_WAY_SAMPLE)
    assert config.schema_kind == "ezdesignx.config.v1"
    assert len(config.roads) == 4
    assert config.driving_side == "right"
    east = next(road for road in config.roads if road.id == "roadEast")
    assert [segment.type for segment in east.incoming_segments] == ["uniform", "transition", "uniform"]
    assert east.incoming_segments[1].length > 1.0
    assert east.outgoing_segments[1].lane_mapping == {0: 1, 1: 2}
    assert (east.incoming_stop_line_distance or 0.0) == 25.0
    assert "transition.length.inferred" in report.approximated_features


def test_load_six_way_jsonc_config_as_legacy_core_input() -> None:
    config, report = load_and_normalize(SIX_WAY_SAMPLE)
    assert config.schema_kind == "ezdesignx.config.v1"
    assert len(config.roads) == 6
    ramp = next(road for road in config.roads if road.id == "road-1778049163847")
    assert ramp.junctionx_angle_deg == 172.99873244250466
    assert "segment.shape.cubicBezier" in report.approximated_features
    assert "road.angle.fromSegmentGeometry" in report.approximated_features
    assert "crosswalks" in report.unsupported_features
    assert "median.centerline.splits" in report.unsupported_features


def test_build_network_plan_uses_old_core_style() -> None:
    config, report = load_and_normalize(FOUR_WAY_SAMPLE)
    plan = build_network_plan(config, report)
    assert len(plan.road_runtimes) == 4
    assert len(plan.edges) > 0
    assert len(plan.connections) > 0
    assert not any(poly.poly_type == "ezdesignx.crosswalk" for poly in plan.polys)
    assert not any(poi.poi_type == "ezdesignx.laneStartCap" for poi in plan.pois)
    assert any(poly.poly_type == "ezdesignx.stopLine" for poly in plan.polys)
    assert any(poly.poly_type == "ezdesignx.median" for poly in plan.polys)


def test_min_transition_fixture_can_be_loaded() -> None:
    config, report = load_and_normalize(MIN_TRANSITION_FIXTURE)
    east = next(road for road in config.roads if road.id == "roadEast")
    assert east.incoming_segments[1].type == "transition"
    assert east.incoming_segments[1].all_lanes
    assert report.approximated


def test_report_includes_feature_sets(tmp_path: Path) -> None:
    config, plan, artifacts, report, netconvert_result = convert_ezdesignx_json(
        input_json=FOUR_WAY_SAMPLE,
        output_dir=tmp_path,
    )
    validation = {
        "level": "basic",
        "passed": netconvert_result.returncode == 0,
        "checks": [],
        "manualChecks": {},
    }
    report_dict = ezdesignx_module.finalize_report(
        config=config,
        plan=plan,
        artifacts=artifacts,
        report=report,
        validation_result=validation,
        netconvert_result=netconvert_result,
    )
    assert report_dict["source"]["schemaKind"] == "ezdesignx.config.v1"
    assert report_dict["source"]["adapterMode"] == "legacy-core-minimal-v1"
    assert "consumedFeatures" in report_dict
    assert "approximatedFeatures" in report_dict
    assert "unsupportedButSeenFeatures" in report_dict
