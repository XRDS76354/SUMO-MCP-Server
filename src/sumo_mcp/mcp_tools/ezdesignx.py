"""ezdesignX JSON to SUMO conversion utilities for SUMO-MCP.

This module is intentionally self-contained so the MCP server can keep working
without relying on the original development directory under ``test/``.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
# --- begin embedded core.py ---
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from xml.etree.ElementTree import Element, ElementTree, SubElement


Point = Tuple[float, float]

DEFAULT_MOTOR_SPEED = 13.89
DEFAULT_BICYCLE_SPEED = 5.56
DEFAULT_PEDESTRIAN_SPEED = 1.39
DEFAULT_CROSSWALK_WIDTH = 4.0
EMIT_MERGE_WIDTH_THRESHOLD = 0.5
EPSILON = 1e-6


def sanitize_identifier(value: str, fallback: str = "id") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("_")
    return cleaned or fallback


def sanitize_filename(value: str, fallback: str = "ezdesignx") -> str:
    cleaned = re.sub(r"[\\/]+", "_", value or "").strip()
    return cleaned or fallback


def round_float(value: float, digits: int = 3) -> float:
    return round(float(value), digits)


def format_shape(points: Sequence[Point]) -> str:
    return " ".join(f"{round_float(x)},{round_float(y)}" for x, y in points)


def normalize_angle(angle_deg: float) -> float:
    return float(angle_deg) % 360.0


def ezdesignx_angle_to_sumo_angle(angle_deg: float) -> float:
    return normalize_angle(-float(angle_deg))


def angle_to_vector(angle_deg: float) -> Point:
    radians = math.radians(angle_deg)
    return (math.cos(radians), math.sin(radians))


def left_normal(vector: Point) -> Point:
    return (-vector[1], vector[0])


def point_add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1])


def point_sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1])


def point_mul(vector: Point, scalar: float) -> Point:
    return (vector[0] * scalar, vector[1] * scalar)


def point_lerp(a: Point, b: Point, ratio: float) -> Point:
    return (a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio)


def point_length(vector: Point) -> float:
    return math.hypot(vector[0], vector[1])


def normalize_vector(vector: Point) -> Point:
    length = point_length(vector)
    if length <= EPSILON:
        return (0.0, 0.0)
    return (vector[0] / length, vector[1] / length)


def polyline_length(points: Sequence[Point]) -> float:
    total = 0.0
    for start, end in zip(points, points[1:]):
        total += point_length(point_sub(end, start))
    return total


def indent_xml(element: Element, level: int = 0) -> None:
    indent = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = indent + "  "
        for child in element:
            indent_xml(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = indent
    if level and (not element.tail or not element.tail.strip()):
        element.tail = indent


def write_xml(root: Element, path: Path) -> None:
    indent_xml(root)
    tree = ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def run_command(command: Sequence[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=False,
    )


def _strip_jsonc_comments(text: str) -> str:
    text = re.sub(r"^\ufeff", "", text)
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    text = re.sub(r"(^|[^:])//.*$", r"\1", text, flags=re.MULTILINE)
    return text


def load_json_like(path: Path) -> Dict[str, object]:
    raw_text = path.read_text(encoding="utf-8")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return json.loads(_strip_jsonc_comments(raw_text))


@dataclass
class ReportItem:
    path: str
    message: str
    details: Dict[str, object] = field(default_factory=dict)


class ReportCollector:
    def __init__(self) -> None:
        self.mapped: List[ReportItem] = []
        self.approximated: List[ReportItem] = []
        self.filtered: List[ReportItem] = []
        self.consumed_features: Set[str] = set()
        self.approximated_features: Set[str] = set()
        self.unsupported_features: Set[str] = set()

    def add_mapped(self, path: str, message: str, **details: object) -> None:
        self.mapped.append(ReportItem(path=path, message=message, details=details))

    def add_approx(self, path: str, message: str, **details: object) -> None:
        self.approximated.append(ReportItem(path=path, message=message, details=details))

    def add_filtered(self, path: str, message: str, **details: object) -> None:
        self.filtered.append(ReportItem(path=path, message=message, details=details))

    def note_consumed(self, feature: str) -> None:
        self.consumed_features.add(feature)

    def note_approximated(self, feature: str) -> None:
        self.approximated_features.add(feature)

    def note_unsupported(self, feature: str) -> None:
        self.unsupported_features.add(feature)

    def as_dict(self) -> Dict[str, object]:
        return {
            "mapped": [asdict(item) for item in self.mapped],
            "approximated": [asdict(item) for item in self.approximated],
            "filtered": [asdict(item) for item in self.filtered],
            "consumedFeatures": sorted(self.consumed_features),
            "approximatedFeatures": sorted(self.approximated_features),
            "unsupportedButSeenFeatures": sorted(self.unsupported_features),
        }


@dataclass
class LaneSpec:
    raw_index: int
    width: float
    lane_type: str
    arrow_types: Tuple[str, ...]
    allow: Optional[str]
    disallow: Optional[str]
    speed: float
    sumo_index: Optional[int] = None
    collapsed_index: Optional[int] = None


@dataclass
class SegmentSpec:
    id: str
    type: str
    length: float
    alignment: str
    report_path: str
    lane_mapping: Dict[int, int]
    region_types: Dict[int, str]
    all_lanes: List[LaneSpec]
    drivable_lanes: List[LaneSpec]
    has_explicit_lanes: bool = False
    approximated_from: Optional[str] = None


@dataclass
class RoadSpec:
    id: str
    safe_id: str
    index: int
    junctionx_angle_deg: float
    junctionx_incoming_angle_deg: float
    sumo_angle_deg: float
    sumo_incoming_angle_deg: float
    offset: float
    median_width: float
    median_corner_radius: float
    median_extension_distance: float
    incoming_stop_line_distance: Optional[float]
    outgoing_stop_line_distance: Optional[float]
    use_corner_curve: bool
    corner_ratio_a: Optional[float]
    corner_ratio_b: Optional[float]
    corner_angle_a: Optional[float]
    corner_angle_b: Optional[float]
    corner_curvature_a: Optional[float]
    corner_curvature_b: Optional[float]
    incoming_segments: List[SegmentSpec]
    outgoing_segments: List[SegmentSpec]
    street_name: Optional[str]


@dataclass
class NormalizedConfig:
    source_id: str
    name: str
    schema_kind: str
    rotation_deg: float
    scale: float
    driving_side: str
    roads: List[RoadSpec]
    crosswalks: List[Dict[str, object]]
    right_turn_lanes: List[object]


@dataclass
class NodeDef:
    id: str
    x: float
    y: float
    node_type: str = "priority"
    radius: Optional[float] = None


@dataclass
class JoinDef:
    id: str
    node_ids: List[str]
    node_type: str


@dataclass
class EdgeDef:
    id: str
    from_node: str
    to_node: str
    shape: List[Point]
    lanes: List[LaneSpec]
    priority: int = 1
    speed: float = DEFAULT_MOTOR_SPEED
    spread_type: str = "center"
    name: Optional[str] = None
    params: Dict[str, object] = field(default_factory=dict)


@dataclass
class ConnectionDef:
    from_edge: str
    to_edge: str
    from_lane: int
    to_lane: int
    allow: Optional[str] = None
    shape: Optional[List[Point]] = None


@dataclass
class PolyDef:
    id: str
    poly_type: str
    color: str
    layer: int
    fill: bool
    shape: List[Point]


@dataclass
class PoiDef:
    id: str
    poi_type: str
    color: str
    x: float
    y: float
    layer: int
    width: float = 1.0


@dataclass
class EmittedEdgeGroup:
    start_segment_index: int
    end_segment_index: int
    edge: EdgeDef
    source_segment_ids: List[str]


@dataclass
class ChainRuntime:
    road_id: str
    direction: str
    axis_angle_deg: float
    axis_vector: Point
    side_vector: Point
    inner_point: Point
    inner_node_id: str
    boundary_points: List[Point]
    boundary_node_ids: List[str]
    edges: List[EdgeDef]
    emitted_groups: List[EmittedEdgeGroup]
    segments: List[SegmentSpec]
    structured_width: float
    drivable_width: float


@dataclass
class RoadRuntime:
    road: RoadSpec
    incoming: ChainRuntime
    outgoing: ChainRuntime


@dataclass
class NetworkPlan:
    config: NormalizedConfig
    nodes: List[NodeDef]
    joins: List[JoinDef]
    edges: List[EdgeDef]
    connections: List[ConnectionDef]
    polys: List[PolyDef]
    pois: List[PoiDef]
    road_runtimes: Dict[str, RoadRuntime]


@dataclass
class ConversionArtifacts:
    input_json: Path
    output_dir: Path
    stem: str
    nodes_xml: Path
    edges_xml: Path
    connections_xml: Path
    net_xml: Path
    additional_xml: Path
    sumocfg: Path
    report_json: Path


def _lane_speed_and_access(lane_type: str) -> Tuple[float, Optional[str], Optional[str]]:
    if lane_type == "non-motor":
        return (DEFAULT_BICYCLE_SPEED, "bicycle", None)
    if lane_type == "pedestrian":
        return (DEFAULT_PEDESTRIAN_SPEED, "pedestrian", None)
    return (DEFAULT_MOTOR_SPEED, None, None)


def _normalize_lane_type(raw_lane_type: Optional[str]) -> str:
    value = str(raw_lane_type or "motor").strip()
    normalized = value.lower()
    if normalized in {"motor", "vehicle"}:
        return "motor"
    if normalized in {"nonmotor", "non-motor", "bicycle", "bike"}:
        return "non-motor"
    if normalized in {"pedestrian", "sidewalk"}:
        return "pedestrian"
    if normalized in {"greenbelt", "green_belt"}:
        return "greenBelt"
    return value or "motor"


def _classify_marking_turn_type(raw_type: object) -> Optional[str]:
    text = str(raw_type or "")
    if not text:
        return None
    normalized = text.strip().lower().replace("_", "-")
    if normalized in {"left", "right", "straight", "straight-left", "straight-right"}:
        return normalized
    has_left = "左" in text
    has_right = "右" in text
    has_straight = "直" in text
    if has_straight and has_left:
        return "straight-left"
    if has_straight and has_right:
        return "straight-right"
    if has_left:
        return "left"
    if has_right:
        return "right"
    if has_straight:
        return "straight"
    return None


def _legacy_arrows_from_centerline(raw_lane: Dict[str, object], report: ReportCollector, path: str) -> List[Dict[str, str]]:
    centerline = raw_lane.get("centerline") or {}
    if not isinstance(centerline, dict):
        return []
    if centerline.get("startCap"):
        report.add_filtered(f"{path}.centerline.startCap", "基础适配版忽略 lane centerline.startCap")
        report.note_unsupported("lane.centerline.startCap")
    arrows: List[Dict[str, str]] = []
    for region in centerline.get("regions") or []:
        if not isinstance(region, dict):
            continue
        for marking in region.get("markings") or []:
            if not isinstance(marking, dict):
                continue
            turn_type = _classify_marking_turn_type(marking.get("type"))
            if turn_type and {"type": turn_type} not in arrows:
                arrows.append({"type": turn_type})
    if arrows:
        report.add_approx(path, "centerline.markings 已降维为旧 arrows", arrows=[item["type"] for item in arrows])
        report.note_approximated("lane.centerline.markings")
    return arrows


def _normalize_lane(raw_lane: object, lane_index: int, path: str, report: ReportCollector) -> LaneSpec:
    if isinstance(raw_lane, (float, int)):
        report.add_approx(path, "数值车道按机动车车道处理", width=float(raw_lane))
        lane_type = "motor"
        width = float(raw_lane)
        arrows: Tuple[str, ...] = tuple()
    elif isinstance(raw_lane, dict):
        lane_type = _normalize_lane_type(raw_lane.get("laneType"))  # type: ignore[arg-type]
        width = float(raw_lane.get("width") or 3.5)
        raw_arrows = raw_lane.get("arrows") or _legacy_arrows_from_centerline(raw_lane, report, path)
        arrows = tuple(
            str(item.get("type") or "straight")
            for item in raw_arrows
            if isinstance(item, dict)
        )
        if raw_lane.get("waitingArea"):
            report.add_filtered(f"{path}.waitingArea", "waitingArea 暂不进入 SUMO 语义，仅记录在日志中")
        if raw_lane.get("showStopLine") is not None:
            report.add_filtered(f"{path}.showStopLine", "showStopLine 暂不进入 SUMO 语义")
        if raw_lane.get("stopLineAngle") is not None:
            report.add_filtered(f"{path}.stopLineAngle", "lane stopLineAngle 暂按附加标注忽略")
        if raw_lane.get("stopLineOffset") is not None:
            report.add_filtered(f"{path}.stopLineOffset", "lane stopLineOffset 暂按附加标注忽略")
    else:
        report.add_approx(path, "未知车道类型，按默认机动车车道处理")
        lane_type = "motor"
        width = 3.5
        arrows = tuple()

    if lane_type == "non-motor":
        report.add_mapped(
            path,
            "non-motor 车道忽略方向箭头，路口连接将按 bicycle 可达目标生成",
            rawArrows=list(arrows),
        )
        arrows = tuple()

    width = max(width, 0.1)
    speed, allow, disallow = _lane_speed_and_access(lane_type)
    return LaneSpec(
        raw_index=lane_index,
        width=width,
        lane_type=lane_type,
        arrow_types=arrows,
        allow=allow,
        disallow=disallow,
        speed=speed,
    )


def _assign_sumo_lane_indices(lanes: List[LaneSpec], driving_side: str) -> None:
    drivable = [lane for lane in lanes if lane.lane_type != "greenBelt"]
    if driving_side == "left":
        order = list(drivable)
    else:
        order = list(reversed(drivable))
    for sumo_index, lane in enumerate(order):
        lane.sumo_index = sumo_index
    for collapsed_index, lane in enumerate(drivable):
        lane.collapsed_index = collapsed_index


def _segment_lanes_from_path(segment: Dict[str, object], path: str, report: ReportCollector) -> List[LaneSpec]:
    raw_lanes = segment.get("lanes") or []
    lanes = [
        _normalize_lane(raw_lane, lane_index, f"{path}.lanes[{lane_index}]", report)
        for lane_index, raw_lane in enumerate(raw_lanes)
    ]
    if segment.get("markingRules"):
        report.add_filtered(f"{path}.markingRules", "markingRules 暂不映射为 SUMO 车道线语义")
    return lanes


def _clone_lanes(lanes: Sequence[LaneSpec]) -> List[LaneSpec]:
    return [
        LaneSpec(
            raw_index=lane.raw_index,
            width=lane.width,
            lane_type=lane.lane_type,
            arrow_types=lane.arrow_types,
            allow=lane.allow,
            disallow=lane.disallow,
            speed=lane.speed,
        )
        for lane in lanes
    ]


def _normalize_region_types(raw_region_types: object) -> Dict[int, str]:
    if not isinstance(raw_region_types, dict):
        return {}
    region_types: Dict[int, str] = {}
    for key, value in raw_region_types.items():
        if str(key).isdigit() and isinstance(value, str) and value:
            region_types[int(key)] = value
    return region_types


def _lane_by_raw_index(lanes: Sequence[LaneSpec], raw_index: int) -> Optional[LaneSpec]:
    for lane in lanes:
        if lane.raw_index == raw_index:
            return lane
    return None


def _nearest_explicit_lane(
    segments: Sequence[SegmentSpec],
    segment_index: int,
    raw_index: int,
    step: int,
) -> Optional[LaneSpec]:
    index = segment_index + step
    while 0 <= index < len(segments):
        candidate = segments[index]
        if candidate.has_explicit_lanes:
            lane = _lane_by_raw_index(candidate.all_lanes, raw_index)
            if lane is not None:
                return lane
        index += step
    return None


def _infer_transition_lane_type(
    region_type: Optional[str],
    previous_lane: Optional[LaneSpec],
    next_lane: Optional[LaneSpec],
) -> Tuple[str, str]:
    if region_type:
        return region_type, "region_types"
    if previous_lane and previous_lane.lane_type == "non-motor":
        return "non-motor", "neighbor_previous"
    if next_lane and next_lane.lane_type == "non-motor":
        return "non-motor", "neighbor_next"
    if previous_lane and next_lane and previous_lane.lane_type == next_lane.lane_type:
        return previous_lane.lane_type, "neighbor_agreement"
    if previous_lane:
        return previous_lane.lane_type, "neighbor_previous"
    if next_lane:
        return next_lane.lane_type, "neighbor_next"
    return "motor", "default_motor_lane"


def _infer_transition_lane_width(
    lane_type: str,
    previous_lane: Optional[LaneSpec],
    next_lane: Optional[LaneSpec],
) -> float:
    if previous_lane and next_lane and previous_lane.lane_type == lane_type and next_lane.lane_type == lane_type:
        return (previous_lane.width + next_lane.width) / 2.0
    if previous_lane and previous_lane.lane_type == lane_type:
        return previous_lane.width
    if next_lane and next_lane.lane_type == lane_type:
        return next_lane.width
    if previous_lane:
        return previous_lane.width
    if next_lane:
        return next_lane.width
    return 3.5


def _infer_transition_lane_arrows(
    lane_type: str,
    previous_lane: Optional[LaneSpec],
    next_lane: Optional[LaneSpec],
) -> Tuple[str, ...]:
    if lane_type == "non-motor":
        return tuple()
    if previous_lane and previous_lane.arrow_types:
        return previous_lane.arrow_types
    if next_lane and next_lane.arrow_types:
        return next_lane.arrow_types
    return tuple()


def _infer_transition_lanes(
    segments: Sequence[SegmentSpec],
    segment_index: int,
    report: ReportCollector,
) -> List[LaneSpec]:
    segment = segments[segment_index]
    candidate_indices = set(segment.region_types.keys())
    for step in (-1, 1):
        index = segment_index + step
        while 0 <= index < len(segments):
            candidate = segments[index]
            if candidate.has_explicit_lanes:
                candidate_indices.update(lane.raw_index for lane in candidate.all_lanes)
                break
            index += step
    candidate_indices.update(segment.lane_mapping.keys())
    candidate_indices.update(segment.lane_mapping.values())

    if not candidate_indices:
        report.add_approx(
            segment.report_path,
            "transition 缺少 lanes / regionTypes / 邻段语义，按单机动车道保底",
            segmentId=segment.id,
        )
        speed, allow, disallow = _lane_speed_and_access("motor")
        return [LaneSpec(0, 3.5, "motor", tuple(), allow, disallow, speed)]

    inferred_lanes: List[LaneSpec] = []
    for raw_index in sorted(candidate_indices):
        previous_lane = _nearest_explicit_lane(segments, segment_index, raw_index, -1)
        next_lane = _nearest_explicit_lane(segments, segment_index, raw_index, 1)
        region_type = segment.region_types.get(raw_index)
        lane_type, source = _infer_transition_lane_type(region_type, previous_lane, next_lane)
        width = _infer_transition_lane_width(lane_type, previous_lane, next_lane)
        arrows = _infer_transition_lane_arrows(lane_type, previous_lane, next_lane)
        speed, allow, disallow = _lane_speed_and_access(lane_type)
        inferred_lanes.append(
            LaneSpec(
                raw_index=raw_index,
                width=width,
                lane_type=lane_type,
                arrow_types=arrows,
                allow=allow,
                disallow=disallow,
                speed=speed,
            )
        )
        if source == "region_types":
            report.add_mapped(
                f"{segment.report_path}.regionTypes[{raw_index}]",
                "transition regionTypes 用于恢复车道类型",
                laneType=lane_type,
            )
        elif source == "default_motor_lane":
            report.add_approx(
                f"{segment.report_path}.lanes[{raw_index}]",
                "transition 车道缺乏显式语义，按机动车车道保底",
                laneType=lane_type,
            )
        else:
            report.add_approx(
                f"{segment.report_path}.lanes[{raw_index}]",
                "transition 车道类型按相邻显式段同 index 推断",
                laneType=lane_type,
                previousLaneType=previous_lane.lane_type if previous_lane else None,
                nextLaneType=next_lane.lane_type if next_lane else None,
            )
    return inferred_lanes


def _point_from_raw(raw_point: object) -> Optional[Point]:
    if not isinstance(raw_point, dict):
        return None
    try:
        return (float(raw_point.get("x") or 0.0), float(raw_point.get("y") or 0.0))
    except (TypeError, ValueError):
        return None


def _straight_segment_length(raw_segment: Dict[str, object]) -> Optional[float]:
    start = _point_from_raw(raw_segment.get("start"))
    end = _point_from_raw(raw_segment.get("end"))
    if start is None or end is None:
        return None
    return point_length(point_sub(end, start))


def _segment_chord_angle(raw_segment: Dict[str, object]) -> Optional[float]:
    start = _point_from_raw(raw_segment.get("start"))
    end = _point_from_raw(raw_segment.get("end"))
    if start is None or end is None:
        return None
    vector = point_sub(end, start)
    if point_length(vector) <= EPSILON:
        return None
    return normalize_angle(math.degrees(math.atan2(vector[1], vector[0])))


def _signed_angle_delta(target: float, base: float) -> float:
    return ((target - base + 180.0) % 360.0) - 180.0


def _first_segment_with_points(raw_segments: Sequence[Dict[str, object]]) -> Optional[Dict[str, object]]:
    for raw_segment in raw_segments:
        if _point_from_raw(raw_segment.get("start")) is not None and _point_from_raw(raw_segment.get("end")) is not None:
            return raw_segment
    return None


def _infer_median_width(incoming_segments: Sequence[Dict[str, object]], outgoing_segments: Sequence[Dict[str, object]]) -> float:
    incoming = _first_segment_with_points(incoming_segments)
    outgoing = _first_segment_with_points(outgoing_segments)
    if not incoming or not outgoing:
        return 0.0
    incoming_start = _point_from_raw(incoming.get("start"))
    outgoing_start = _point_from_raw(outgoing.get("start"))
    if incoming_start is None or outgoing_start is None:
        return 0.0
    incoming_width = sum(
        float(lane.get("width") or 3.5)
        for lane in incoming.get("lanes") or []
        if isinstance(lane, dict)
    )
    outgoing_width = sum(
        float(lane.get("width") or 3.5)
        for lane in outgoing.get("lanes") or []
        if isinstance(lane, dict)
    )
    center_distance = point_length(point_sub(incoming_start, outgoing_start))
    return max(0.0, center_distance - incoming_width / 2.0 - outgoing_width / 2.0)


def _adapt_v1_segment(
    raw_segment: Dict[str, object],
    path: str,
    report: ReportCollector,
) -> Dict[str, object]:
    adapted = dict(raw_segment)
    if raw_segment.get("length") is None:
        length = _straight_segment_length(raw_segment)
        if length is not None:
            adapted["length"] = length
            shape_kind = str(raw_segment.get("shape") or "line")
            if shape_kind == "cubicBezier":
                report.add_approx(path, "cubicBezier 在基础适配版中按 start/end 弦长降维为直线长度", length=length)
                report.note_approximated("segment.shape.cubicBezier")
            elif shape_kind:
                report.add_approx(path, "segment.start/end 已降维为旧核心 length", shape=shape_kind, length=length)
                report.note_approximated("segment.shape.line")
    if raw_segment.get("centerline"):
        report.add_filtered(f"{path}.centerline", "基础适配版忽略 segment centerline")
        report.note_unsupported("segment.centerline")
    return adapted


def _fill_transition_lengths(
    segments: List[Dict[str, object]],
    path_prefix: str,
    report: ReportCollector,
) -> None:
    for segment_index, segment in enumerate(segments):
        if segment.get("length") is not None:
            continue
        if str(segment.get("type") or "") != "transition":
            continue
        previous_segment = segments[segment_index - 1] if segment_index > 0 else None
        next_segment = segments[segment_index + 1] if segment_index + 1 < len(segments) else None
        previous_end = _point_from_raw(previous_segment.get("end")) if previous_segment else None
        next_start = _point_from_raw(next_segment.get("start")) if next_segment else None
        if previous_end is None or next_start is None:
            continue
        length = point_length(point_sub(next_start, previous_end))
        if length <= EPSILON:
            continue
        segment["length"] = length
        report.add_approx(
            f"{path_prefix}[{segment_index}]",
            "transition 缺少 start/end，按前段 end 到后段 start 的距离降维为旧 length",
            length=length,
        )
        report.note_approximated("transition.length.inferred")


def _apply_v1_geometry_angles(
    road: Dict[str, object],
    raw_road: Dict[str, object],
    incoming_segments: Sequence[Dict[str, object]],
    outgoing_segments: Sequence[Dict[str, object]],
    path: str,
    report: ReportCollector,
) -> None:
    incoming_source = _first_segment_with_points(incoming_segments)
    outgoing_source = _first_segment_with_points(outgoing_segments)
    incoming_angle = _segment_chord_angle(incoming_source) if incoming_source else None
    outgoing_angle = _segment_chord_angle(outgoing_source) if outgoing_source else None
    inferred_angle = outgoing_angle if outgoing_angle is not None else incoming_angle
    if inferred_angle is None:
        return

    raw_angle = float(raw_road.get("angle") or 0.0)
    road["angle"] = inferred_angle
    delta = abs(_signed_angle_delta(inferred_angle, raw_angle))
    if delta > 0.5:
        report.add_approx(
            f"{path}.angle",
            "road.angle 已按首个显式 segment start/end 反推修正",
            rawAngle=raw_angle,
            inferredAngle=inferred_angle,
            delta=delta,
            source="outgoingSegments" if outgoing_angle is not None else "incomingSegments",
        )
        report.note_approximated("road.angle.fromSegmentGeometry")
    else:
        report.add_mapped(
            f"{path}.angle",
            "road.angle 与显式 segment 几何一致",
            angle=inferred_angle,
            source="outgoingSegments" if outgoing_angle is not None else "incomingSegments",
        )

    if incoming_angle is not None and outgoing_angle is not None:
        skew = _signed_angle_delta(incoming_angle, inferred_angle)
        if abs(skew) > 0.5:
            road["incomingSkewAngle"] = skew
            report.add_approx(
                f"{path}.incomingSkewAngle",
                "incoming/outgoing 显式几何角度不同，降维为旧核心 incomingSkewAngle",
                incomingAngle=incoming_angle,
                outgoingAngle=inferred_angle,
                skewAngle=skew,
            )
            report.note_approximated("road.incomingSkewAngle.fromSegmentGeometry")
        elif raw_road.get("incomingSkewAngle") is not None:
            road["incomingSkewAngle"] = raw_road.get("incomingSkewAngle")


def _adapt_v1_config(raw: Dict[str, object], report: ReportCollector) -> Dict[str, object]:
    adapted = dict(raw)
    adapted_roads: List[Dict[str, object]] = []
    report.note_consumed("schema.v1")
    report.note_consumed("road.angle")
    report.note_consumed("segment.startEndChordLength")
    report.note_consumed("lane.width")
    report.note_consumed("lane.laneType")

    for road_index, raw_road_obj in enumerate(raw.get("roads") or []):
        if not isinstance(raw_road_obj, dict):
            continue
        path = f"roads[{road_index}]"
        raw_road = raw_road_obj
        road = dict(raw_road)
        incoming_segments = [
            _adapt_v1_segment(segment, f"{path}.incomingSegments[{segment_index}]", report)
            for segment_index, segment in enumerate(raw_road.get("incomingSegments") or [])
            if isinstance(segment, dict)
        ]
        outgoing_segments = [
            _adapt_v1_segment(segment, f"{path}.outgoingSegments[{segment_index}]", report)
            for segment_index, segment in enumerate(raw_road.get("outgoingSegments") or [])
            if isinstance(segment, dict)
        ]
        _fill_transition_lengths(incoming_segments, f"{path}.incomingSegments", report)
        _fill_transition_lengths(outgoing_segments, f"{path}.outgoingSegments", report)
        road["incomingSegments"] = incoming_segments
        road["outgoingSegments"] = outgoing_segments
        road["offset"] = float(raw_road.get("offset") or 0.0)
        _apply_v1_geometry_angles(road, raw_road, incoming_segments, outgoing_segments, path, report)

        if incoming_segments and raw_road.get("incomingStopLineDistance") is None:
            stop_distance = incoming_segments[0].get("stopLineDistance")
            if stop_distance is not None:
                road["incomingStopLineDistance"] = stop_distance
                report.add_mapped(f"{path}.incomingSegments[0].stopLineDistance", "降维为旧 incomingStopLineDistance", distance=stop_distance)
                report.note_consumed("segment.stopLineDistance")
        if outgoing_segments and raw_road.get("outgoingStopLineDistance") is None:
            stop_distance = outgoing_segments[0].get("stopLineDistance")
            if stop_distance is not None:
                road["outgoingStopLineDistance"] = stop_distance
                report.add_mapped(f"{path}.outgoingSegments[0].stopLineDistance", "降维为旧 outgoingStopLineDistance", distance=stop_distance)
                report.note_consumed("segment.stopLineDistance")

        raw_median = raw_road.get("median") if isinstance(raw_road.get("median"), dict) else {}
        median = dict(raw_median or {})
        centerline = median.get("centerline") if isinstance(median.get("centerline"), dict) else {}
        if centerline:
            if centerline.get("splits") or centerline.get("regions"):
                report.add_filtered(f"{path}.median.centerline", "基础适配版仅保留简单矩形中分带，忽略 splits/regions")
                report.note_unsupported("median.centerline.splits")
            start_cap = centerline.get("startCap") if isinstance(centerline.get("startCap"), dict) else {}
            if median.get("extensionDistance") is None and isinstance(start_cap, dict) and start_cap.get("extensionDistance") is not None:
                median["extensionDistance"] = start_cap.get("extensionDistance")
            if median.get("cornerRadius") is None and isinstance(start_cap, dict) and start_cap.get("cornerRadius") is not None:
                median["cornerRadius"] = start_cap.get("cornerRadius")
            report.note_approximated("median.centerline.simpleRectangle")
        if median.get("width") is None:
            median["width"] = _infer_median_width(incoming_segments, outgoing_segments)
            report.add_approx(f"{path}.median.width", "由 incoming/outgoing 首段 start 点中心距反推简单中分带宽度", width=median["width"])
            report.note_approximated("median.width.inferred")
        road["median"] = median

        if raw_road.get("laneArrows"):
            report.add_filtered(f"{path}.laneArrows", "基础适配版不恢复 road laneArrows")
            report.note_unsupported("road.laneArrows")
        adapted_roads.append(road)

    if raw.get("crosswalks"):
        report.add_filtered("crosswalks", "基础适配版不输出 crosswalk")
        report.note_unsupported("crosswalks")
        if any(isinstance(item, dict) and item.get("widthOffset") is not None for item in raw.get("crosswalks") or []):
            report.note_unsupported("crosswalk.widthOffset")

    adapted["roads"] = adapted_roads
    adapted["crosswalks"] = list(raw.get("crosswalks") or [])
    return adapted


def load_and_normalize(input_path: Path, report: Optional[ReportCollector] = None) -> Tuple[NormalizedConfig, ReportCollector]:
    collector = report or ReportCollector()
    raw = load_json_like(input_path)
    schema_version = raw.get("schemaVersion")
    if schema_version != 1:
        raise ValueError(f"不支持的 schemaVersion={schema_version!r}；基础适配版只支持 ezdesignX v1")
    schema_kind = "ezdesignx.config.v1"
    raw = _adapt_v1_config(raw, collector)

    source_id = str(raw.get("id") or input_path.stem)
    name = str(raw.get("name") or input_path.stem)
    rotation_deg = float(raw.get("rotation") or 0.0)
    scale = float(raw.get("scale") or 1.0)
    driving_side = str(raw.get("drivingSide") or "right").lower()
    if driving_side not in {"right", "left"}:
        collector.add_approx("drivingSide", "未知 drivingSide，按 right 处理", rawValue=driving_side)
        driving_side = "right"

    collector.add_mapped("rotation", "整体旋转角参与几何重建", value=rotation_deg)
    collector.add_mapped("scale", "整体比例参与几何重建", value=scale)
    collector.add_mapped("drivingSide", "按 drivingSide 解释左右转和车道索引", value=driving_side)

    if raw.get("rightTurnLanes"):
        collector.add_filtered("rightTurnLanes", "rightTurnLanes 暂未映射到核心 SUMO 语义")

    roads: List[RoadSpec] = []
    for road_index, raw_road in enumerate(raw.get("roads") or []):
        path = f"roads[{road_index}]"
        road_id = str(raw_road.get("id") or f"road-{road_index}")
        safe_id = sanitize_identifier(road_id, f"road_{road_index}")
        base_angle = float(raw_road.get("angle") or (road_index * 90.0))
        junctionx_angle_deg = normalize_angle(base_angle + rotation_deg)
        junctionx_incoming_angle_deg = normalize_angle(
            junctionx_angle_deg + float(raw_road.get("incomingSkewAngle") or 0.0)
        )
        sumo_angle_deg = ezdesignx_angle_to_sumo_angle(junctionx_angle_deg)
        sumo_incoming_angle_deg = ezdesignx_angle_to_sumo_angle(junctionx_incoming_angle_deg)
        offset = float(raw_road.get("offset") or 0.0) * scale
        median = raw_road.get("median") or {}
        median_width = float(median.get("width", raw_road.get("medianWidth") or 0.0)) * scale
        median_corner_radius = float(median.get("cornerRadius") or 0.0) * scale
        median_extension_distance = float(median.get("extensionDistance") or 0.0) * scale

        collector.add_mapped(
            f"{path}.angle",
            "road angle 以 ezdesignX 屏幕坐标记录，写入 SUMO 几何时会做 y 轴翻转",
            value=junctionx_angle_deg,
            sumoAngle=sumo_angle_deg,
        )
        collector.add_mapped(f"{path}.offset", "road offset 用于平移道路轴线", value=offset)
        collector.add_mapped(f"{path}.median.width", "median 宽度用于附加图层", value=median_width)
        collector.add_mapped(
            f"{path}.median.extensionDistance",
            "median extensionDistance 用于附加图层长度",
            value=median_extension_distance,
        )
        if median.get("gaps"):
            collector.add_filtered(f"{path}.median.gaps", "median.gaps 暂仅记录，不参与核心网络构建")
        if raw_road.get("laneArrows"):
            collector.add_filtered(f"{path}.laneArrows", "laneArrows 暂不单独映射，转向使用 lane.arrows")

        incoming_segments: List[SegmentSpec] = []
        outgoing_segments: List[SegmentSpec] = []
        for direction_key, destination in (
            ("incomingSegments", incoming_segments),
            ("outgoingSegments", outgoing_segments),
        ):
            raw_segments = raw_road.get(direction_key) or []
            for segment_index, raw_segment in enumerate(raw_segments):
                segment_path = f"{path}.{direction_key}[{segment_index}]"
                segment_id = str(raw_segment.get("id") or f"{road_id}-{direction_key}-{segment_index}")
                segment_type = str(raw_segment.get("type") or "uniform")
                length = float(raw_segment.get("length") or 0.0) * scale
                if length <= EPSILON:
                    collector.add_approx(segment_path, "segment.length 缺失或非法，按 1m 保底", rawValue=raw_segment.get("length"))
                    length = 1.0
                alignment = str(raw_segment.get("alignment") or "center")
                raw_mapping = raw_segment.get("laneMapping") or {}
                lane_mapping = {
                    int(key): int(value)
                    for key, value in raw_mapping.items()
                    if str(key).isdigit() and str(value).lstrip("-").isdigit()
                }
                region_types = _normalize_region_types(raw_segment.get("regionTypes"))
                all_lanes = _segment_lanes_from_path(raw_segment, segment_path, collector)
                if segment_type == "transition" and not all_lanes:
                    collector.add_approx(segment_path, "transition 段未显式给出车道，将从邻近 uniform 段推断")
                destination.append(
                    SegmentSpec(
                        id=segment_id,
                        type=segment_type,
                        length=length,
                        alignment=alignment,
                        report_path=segment_path,
                        lane_mapping=lane_mapping,
                        region_types=region_types,
                        all_lanes=all_lanes,
                        drivable_lanes=[],
                        has_explicit_lanes=bool(all_lanes),
                    )
                )

        for segments in (incoming_segments, outgoing_segments):
            for segment_index, segment in enumerate(segments):
                if segment.all_lanes:
                    continue
                segment.all_lanes = _infer_transition_lanes(segments, segment_index, collector)
                segment.approximated_from = "transition_semantic_recovery"

        for segments in (incoming_segments, outgoing_segments):
            for segment in segments:
                _assign_sumo_lane_indices(segment.all_lanes, driving_side)
                for lane in segment.all_lanes:
                    if lane.lane_type == "greenBelt":
                        collector.add_filtered(
                            f"{path}.{segment.id}.lanes[{lane.raw_index}]",
                            "greenBelt 不进入 drivable network，将写入 add.xml polygon",
                            width=lane.width,
                        )
                segment.drivable_lanes = [lane for lane in segment.all_lanes if lane.lane_type != "greenBelt"]

        roads.append(
            RoadSpec(
                id=road_id,
                safe_id=safe_id,
                index=road_index,
                junctionx_angle_deg=junctionx_angle_deg,
                junctionx_incoming_angle_deg=junctionx_incoming_angle_deg,
                sumo_angle_deg=sumo_angle_deg,
                sumo_incoming_angle_deg=sumo_incoming_angle_deg,
                offset=offset,
                median_width=median_width,
                median_corner_radius=median_corner_radius,
                median_extension_distance=median_extension_distance,
                incoming_stop_line_distance=(
                    float(raw_road["incomingStopLineDistance"]) * scale
                    if raw_road.get("incomingStopLineDistance") is not None
                    else None
                ),
                outgoing_stop_line_distance=(
                    float(raw_road["outgoingStopLineDistance"]) * scale
                    if raw_road.get("outgoingStopLineDistance") is not None
                    else None
                ),
                use_corner_curve=bool(raw_road.get("useCornerCurve", True)),
                corner_ratio_a=raw_road.get("cornerRatioA", raw_road.get("cornerRatio")),
                corner_ratio_b=raw_road.get("cornerRatioB", raw_road.get("cornerRatio")),
                corner_angle_a=raw_road.get("cornerAngleA"),
                corner_angle_b=raw_road.get("cornerAngleB"),
                corner_curvature_a=raw_road.get("cornerCurvatureA"),
                corner_curvature_b=raw_road.get("cornerCurvatureB"),
                incoming_segments=incoming_segments,
                outgoing_segments=outgoing_segments,
                street_name=raw_road.get("streetName"),
            )
        )

    normalized = NormalizedConfig(
        source_id=source_id,
        name=name,
        schema_kind=schema_kind,
        rotation_deg=rotation_deg,
        scale=scale,
        driving_side=driving_side,
        roads=roads,
        crosswalks=list(raw.get("crosswalks") or []),
        right_turn_lanes=list(raw.get("rightTurnLanes") or []),
    )
    return normalized, collector


def _structured_width(segment: SegmentSpec) -> float:
    return sum(lane.width for lane in segment.all_lanes)


def _drivable_width(segment: SegmentSpec) -> float:
    return sum(lane.width for lane in segment.drivable_lanes)


def _lane_compat_signature(segment: SegmentSpec) -> List[Tuple[int, str, Optional[str], Optional[str]]]:
    return [
        (lane.raw_index, lane.lane_type, lane.allow, lane.disallow)
        for lane in segment.drivable_lanes
    ]


def _segments_compatible_for_emit(source: SegmentSpec, target: SegmentSpec) -> Tuple[bool, str]:
    if len(source.drivable_lanes) != len(target.drivable_lanes):
        return False, "lane_count_mismatch"
    if _lane_compat_signature(source) != _lane_compat_signature(target):
        return False, "lane_signature_mismatch"
    max_width_diff = max(
        (
            abs(source_lane.width - target_lane.width)
            for source_lane, target_lane in zip(source.drivable_lanes, target.drivable_lanes)
        ),
        default=0.0,
    )
    if max_width_diff > EMIT_MERGE_WIDTH_THRESHOLD:
        return False, "lane_width_mismatch"
    return True, "compatible"


def _merge_group_lanes(segments: Sequence[SegmentSpec], driving_side: str) -> List[LaneSpec]:
    base_lanes = _clone_lanes(segments[0].drivable_lanes)
    total_length = sum(segment.length for segment in segments)
    weights = [segment.length / max(total_length, EPSILON) for segment in segments]
    for lane in base_lanes:
        matching_widths = []
        for segment, weight in zip(segments, weights):
            source_lane = _lane_by_raw_index(segment.drivable_lanes, lane.raw_index)
            if source_lane is None:
                continue
            matching_widths.append((source_lane.width, weight))
        if matching_widths:
            lane.width = sum(width * weight for width, weight in matching_widths)
    _assign_sumo_lane_indices(base_lanes, driving_side)
    return base_lanes


def _build_emission_group_ranges(
    road: RoadSpec,
    direction: str,
    segments: Sequence[SegmentSpec],
    report: ReportCollector,
) -> List[Tuple[int, int]]:
    if not segments:
        return []

    ranges: List[Tuple[int, int]] = []
    index = 0
    while index < len(segments):
        run_end = index
        run_contains_transition = segments[index].type == "transition"
        incompatibility_reason: Optional[str] = None
        while run_end + 1 < len(segments):
            compatible, reason = _segments_compatible_for_emit(segments[run_end], segments[run_end + 1])
            if not compatible:
                incompatibility_reason = reason
                break
            run_end += 1
            run_contains_transition = run_contains_transition or segments[run_end].type == "transition"

        if run_end > index and run_contains_transition:
            report.add_mapped(
                f"roads[{road.index}].{direction}Segments[{index}]",
                "兼容 transition 链按单个 emitted edge 发射，避免边界生成内部 junction",
                sourceSegmentIds=[segment.id for segment in segments[index : run_end + 1]],
                startSegmentIndex=index,
                endSegmentIndex=run_end,
            )
            ranges.append((index, run_end))
        else:
            if (
                incompatibility_reason is not None
                and (segments[run_end].type == "transition" or (run_end + 1 < len(segments) and segments[run_end + 1].type == "transition"))
            ):
                report.add_approx(
                    f"roads[{road.index}].{direction}Segments[{run_end}]",
                    "transition 边界 lane 拓扑不兼容，保留分段发射",
                    sourceSegmentIds=[segments[run_end].id, segments[run_end + 1].id] if run_end + 1 < len(segments) else [segments[run_end].id],
                    reason=incompatibility_reason,
                )
            ranges.append((index, index))
            if run_end > index:
                for single_index in range(index + 1, run_end + 1):
                    ranges.append((single_index, single_index))
        index = run_end + 1

    return ranges


def _lane_band_map(segment: SegmentSpec) -> Dict[int, Tuple[float, float]]:
    total = _structured_width(segment)
    # ezdesignX lane arrays are ordered from the inner side (near median)
    # toward the outer curb, so positive offsets track the inner side.
    cursor = total / 2.0
    bands: Dict[int, Tuple[float, float]] = {}
    for lane in segment.all_lanes:
        next_cursor = cursor - lane.width
        bands[lane.raw_index] = (cursor, next_cursor)
        cursor = next_cursor
    return bands


def _carriageway_center_sign(driving_side: str, direction: str) -> int:
    if driving_side == "left":
        return 1 if direction == "outgoing" else -1
    return -1 if direction == "outgoing" else 1


def _road_left_vector(road: RoadSpec) -> Point:
    return left_normal(normalize_vector(angle_to_vector(road.sumo_angle_deg)))


def _chain_lateral_vectors(road: RoadSpec, axis_vector: Point, direction: str, driving_side: str) -> Tuple[Point, Point]:
    road_left = _road_left_vector(road)
    center_sign = _carriageway_center_sign(driving_side, direction)
    center_vector = point_mul(road_left, center_sign)
    cross_section_vector = left_normal(axis_vector)
    inner_side_vector = point_mul(cross_section_vector, -center_sign)
    return center_vector, inner_side_vector


def _make_node(node_id: str, point: Point, node_type: str = "priority") -> NodeDef:
    return NodeDef(id=node_id, x=round_float(point[0]), y=round_float(point[1]), node_type=node_type)


def _chain_base_point(road: RoadSpec, road_left_vector: Point) -> Point:
    return point_mul(road_left_vector, road.offset)


def _build_chain(
    road: RoadSpec,
    direction: str,
    driving_side: str,
    report: ReportCollector,
) -> Tuple[List[NodeDef], List[EdgeDef], ChainRuntime]:
    segments = road.outgoing_segments if direction == "outgoing" else road.incoming_segments
    axis_angle = road.sumo_angle_deg if direction == "outgoing" else road.sumo_incoming_angle_deg
    axis_vector = angle_to_vector(axis_angle)
    axis_vector = normalize_vector(axis_vector)
    road_left_vector = _road_left_vector(road)
    center_vector, side_vector = _chain_lateral_vectors(road, axis_vector, direction, driving_side)
    structured_width = _structured_width(segments[0]) if segments else 0.0
    drivable_width = _drivable_width(segments[0]) if segments else 0.0
    centerline_shift = road.median_width / 2.0 + structured_width / 2.0
    base_point = _chain_base_point(road, road_left_vector)
    inner_point = point_add(base_point, point_mul(center_vector, centerline_shift))
    inner_node_id = f"node_{road.safe_id}_{direction}_inner"

    nodes: List[NodeDef] = [_make_node(inner_node_id, inner_point)]
    boundary_points = [inner_point]
    boundary_node_ids = [inner_node_id]
    distance = 0.0
    for segment_index, segment in enumerate(segments):
        distance += segment.length
        point_at_boundary = point_add(inner_point, point_mul(axis_vector, distance))
        node_id = f"node_{road.safe_id}_{direction}_{segment_index}"
        boundary_points.append(point_at_boundary)
        boundary_node_ids.append(node_id)

    group_ranges = _build_emission_group_ranges(road, direction, segments, report)
    edges: List[EdgeDef] = []
    emitted_groups: List[EmittedEdgeGroup] = []
    emitted_boundary_indices = {0}
    for start_index, end_index in group_ranges:
        emitted_boundary_indices.add(start_index)
        emitted_boundary_indices.add(end_index + 1)

    for boundary_index in sorted(emitted_boundary_indices):
        if boundary_index == 0:
            continue
        nodes.append(_make_node(boundary_node_ids[boundary_index], boundary_points[boundary_index]))

    for start_index, end_index in group_ranges:
        grouped_segments = list(segments[start_index : end_index + 1])
        lanes = _merge_group_lanes(grouped_segments, driving_side)
        if direction == "outgoing":
            from_boundary = start_index
            to_boundary = end_index + 1
            shape = boundary_points[start_index : end_index + 2]
        else:
            from_boundary = end_index + 1
            to_boundary = start_index
            shape = list(reversed(boundary_points[start_index : end_index + 2]))

        edge = EdgeDef(
            id=f"edge_{road.safe_id}_{direction}_{start_index}",
            from_node=boundary_node_ids[from_boundary],
            to_node=boundary_node_ids[to_boundary],
            shape=shape,
            lanes=lanes,
            speed=max((lane.speed for lane in lanes), default=DEFAULT_MOTOR_SPEED),
            name=road.street_name,
            params={
                "segmentType": grouped_segments[0].type if len(grouped_segments) == 1 else "merged_transition_chain",
                "ezdesignxRoadId": road.id,
                "direction": direction,
                "sourceSegmentIds": ",".join(segment.id for segment in grouped_segments),
            },
        )
        edges.append(edge)
        emitted_groups.append(
            EmittedEdgeGroup(
                start_segment_index=start_index,
                end_segment_index=end_index,
                edge=edge,
                source_segment_ids=[segment.id for segment in grouped_segments],
            )
        )

    runtime = ChainRuntime(
        road_id=road.id,
        direction=direction,
        axis_angle_deg=axis_angle,
        axis_vector=axis_vector,
        side_vector=side_vector,
        inner_point=inner_point,
        inner_node_id=inner_node_id,
        boundary_points=boundary_points,
        boundary_node_ids=boundary_node_ids,
        edges=edges,
        emitted_groups=emitted_groups,
        segments=segments,
        structured_width=structured_width,
        drivable_width=drivable_width,
    )
    return nodes, edges, runtime


def _lane_lookup_by_collapsed_index(lanes: Sequence[LaneSpec]) -> Dict[int, LaneSpec]:
    lookup: Dict[int, LaneSpec] = {}
    for lane in lanes:
        if lane.collapsed_index is not None:
            lookup[lane.collapsed_index] = lane
    return lookup


def _default_target_for_source(source_index: int, source_count: int, target_count: int, alignment: str) -> int:
    if target_count <= 1:
        return 0
    if source_count <= 1:
        return 0 if alignment != "outer" else target_count - 1
    ratio = source_index / max(source_count - 1, 1)
    if alignment == "outer":
        target = round(ratio * (target_count - 1))
    elif alignment == "center":
        target = round(ratio * (target_count - 1))
    else:
        target = round(ratio * (target_count - 1))
    return int(max(0, min(target_count - 1, target)))


def _build_lane_continuity_connections(
    source_edge: EdgeDef,
    source_segment: SegmentSpec,
    target_edge: EdgeDef,
    target_segment: SegmentSpec,
) -> List[ConnectionDef]:
    source_lookup = _lane_lookup_by_collapsed_index(source_edge.lanes)
    target_lookup = _lane_lookup_by_collapsed_index(target_edge.lanes)
    if not source_lookup or not target_lookup:
        return []

    preferred_target_to_source = target_segment.lane_mapping or {}
    inverse_preferred: Dict[int, List[int]] = {}
    for target_index, source_index in preferred_target_to_source.items():
        inverse_preferred.setdefault(source_index, []).append(target_index)

    source_count = len(source_lookup)
    target_count = len(target_lookup)
    connections: List[ConnectionDef] = []
    for source_collapsed, source_lane in source_lookup.items():
        target_candidates = inverse_preferred.get(source_collapsed)
        if not target_candidates:
            guessed_target = _default_target_for_source(
                source_collapsed,
                source_count,
                target_count,
                target_segment.alignment,
            )
            target_candidates = [guessed_target]
        for target_collapsed in target_candidates:
            target_lane = target_lookup.get(target_collapsed)
            if not target_lane or source_lane.sumo_index is None or target_lane.sumo_index is None:
                continue
            connections.append(
                ConnectionDef(
                    from_edge=source_edge.id,
                    to_edge=target_edge.id,
                    from_lane=source_lane.sumo_index,
                    to_lane=target_lane.sumo_index,
                    allow=source_lane.allow or target_lane.allow,
                )
            )
    return connections


def _sort_roads_clockwise(roads: Sequence[RoadSpec]) -> List[RoadSpec]:
    return sorted(roads, key=lambda road: normalize_angle(road.junctionx_angle_deg))


def _turn_target_road(
    ordered_roads: Sequence[RoadSpec],
    current_index: int,
    turn_type: str,
    driving_side: str,
    movement_direction: str = "incoming",
) -> List[RoadSpec]:
    total = len(ordered_roads)
    if total <= 1:
        return []
    right_step = 1 if driving_side == "right" else -1
    if movement_direction == "incoming":
        # ordered_roads are sorted by each leg's outward axis around the center.
        # For an incoming movement the driver is heading toward the center, so
        # left/right are reversed relative to the outward axis ordering.
        right_step *= -1
    left_step = -right_step
    right_index = (current_index + right_step) % total
    left_index = (current_index + left_step) % total
    current_angle = ordered_roads[current_index].junctionx_angle_deg
    straight_target = min(
        (
            (index, abs(((road.junctionx_angle_deg - current_angle + 180.0) % 360.0) - 180.0))
            for index, road in enumerate(ordered_roads)
            if index != current_index
        ),
        key=lambda item: abs(item[1] - 180.0),
    )[0]

    mapping = {
        "left": [ordered_roads[left_index]],
        "straight": [ordered_roads[straight_target]],
        "right": [ordered_roads[right_index]],
        "straight-left": [ordered_roads[straight_target], ordered_roads[left_index]],
        "straight-right": [ordered_roads[straight_target], ordered_roads[right_index]],
    }
    return mapping.get(turn_type, [ordered_roads[straight_target]])


def _compatible_target_lanes(source_lane: LaneSpec, target_edge: EdgeDef) -> List[LaneSpec]:
    if source_lane.lane_type == "non-motor":
        candidates = [lane for lane in target_edge.lanes if lane.lane_type == "non-motor"]
        return candidates
    candidates = [lane for lane in target_edge.lanes if lane.lane_type == "motor"]
    if candidates:
        return candidates
    return list(target_edge.lanes)


def _build_turn_connections(
    plan_roads: Dict[str, RoadRuntime],
    ordered_roads: Sequence[RoadSpec],
    driving_side: str,
    report: Optional[ReportCollector] = None,
) -> List[ConnectionDef]:
    connections: List[ConnectionDef] = []
    per_turn_counters: Dict[Tuple[str, str, str], int] = {}
    logged_non_motor_paths: Set[str] = set()

    ordered_index = {road.id: index for index, road in enumerate(ordered_roads)}
    for road in ordered_roads:
        runtime = plan_roads[road.id]
        source_edge = runtime.incoming.edges[0]
        source_segment = road.incoming_segments[0]
        for source_lane in source_segment.drivable_lanes:
            if source_lane.sumo_index is None:
                continue
            if source_lane.lane_type == "non-motor":
                target_roads = [
                    target_road
                    for target_road in ordered_roads
                    if target_road.id != road.id
                    and _compatible_target_lanes(source_lane, plan_roads[target_road.id].outgoing.edges[0])
                ]
                if report is not None:
                    report_path = f"roads[{road.index}].incomingSegments[0].lanes[{source_lane.raw_index}]"
                    if report_path not in logged_non_motor_paths:
                        report.add_mapped(
                            report_path,
                            "non-motor 车道不读取方向箭头，连接到所有存在 bicycle 目标的方向",
                            targetRoadIds=[target_road.id for target_road in target_roads],
                        )
                        logged_non_motor_paths.add(report_path)
                target_road_groups = [target_roads]
            else:
                arrow_types = source_lane.arrow_types or ("straight",)
                target_road_groups = [
                    _turn_target_road(
                        ordered_roads=ordered_roads,
                        current_index=ordered_index[road.id],
                        turn_type=arrow_type,
                        driving_side=driving_side,
                        movement_direction="incoming",
                    )
                    for arrow_type in arrow_types
                ]
            for target_roads in target_road_groups:
                for target_road in target_roads:
                    target_edge = plan_roads[target_road.id].outgoing.edges[0]
                    target_candidates = _compatible_target_lanes(source_lane, target_edge)
                    if not target_candidates:
                        continue
                    counter_key = (road.id, target_road.id, source_lane.lane_type)
                    counter = per_turn_counters.get(counter_key, 0)
                    target_lane = target_candidates[min(counter, len(target_candidates) - 1)]
                    per_turn_counters[counter_key] = counter + 1
                    if target_lane.sumo_index is None:
                        continue
                    connections.append(
                        ConnectionDef(
                            from_edge=source_edge.id,
                            to_edge=target_edge.id,
                            from_lane=source_lane.sumo_index,
                            to_lane=target_lane.sumo_index,
                            allow=source_lane.allow or target_lane.allow,
                        )
                    )
    return connections


def _rectangle_from_centerline(start: Point, end: Point, side_vector: Point, inner_offset: float, outer_offset: float) -> List[Point]:
    return [
        point_add(start, point_mul(side_vector, inner_offset)),
        point_add(end, point_mul(side_vector, inner_offset)),
        point_add(end, point_mul(side_vector, outer_offset)),
        point_add(start, point_mul(side_vector, outer_offset)),
    ]


def _sample_cubic_bezier(start: Point, control_a: Point, control_b: Point, end: Point, samples: int = 16) -> List[Point]:
    points: List[Point] = []
    for step in range(samples + 1):
        t = step / samples
        omt = 1.0 - t
        x = (
            (omt ** 3) * start[0]
            + 3 * (omt ** 2) * t * control_a[0]
            + 3 * omt * (t ** 2) * control_b[0]
            + (t ** 3) * end[0]
        )
        y = (
            (omt ** 3) * start[1]
            + 3 * (omt ** 2) * t * control_a[1]
            + 3 * omt * (t ** 2) * control_b[1]
            + (t ** 3) * end[1]
        )
        points.append((x, y))
    return points


def _point_at_ratio(points: Sequence[Point], ratio: float) -> Point:
    if not points:
        return (0.0, 0.0)
    if ratio <= 0:
        return points[0]
    if ratio >= 1:
        return points[-1]
    target_length = polyline_length(points) * ratio
    walked = 0.0
    for start, end in zip(points, points[1:]):
        segment_length = point_length(point_sub(end, start))
        if walked + segment_length >= target_length:
            local_ratio = (target_length - walked) / max(segment_length, EPSILON)
            return point_lerp(start, end, local_ratio)
        walked += segment_length
    return points[-1]


def _corner_curve(
    from_runtime: RoadRuntime,
    to_runtime: RoadRuntime,
    from_road: RoadSpec,
    to_road: RoadSpec,
) -> List[Point]:
    start = point_add(
        from_runtime.outgoing.inner_point,
        point_mul(from_runtime.outgoing.side_vector, from_runtime.outgoing.structured_width / 2.0),
    )
    end = point_add(
        to_runtime.incoming.inner_point,
        point_mul(to_runtime.incoming.side_vector, to_runtime.incoming.structured_width / 2.0),
    )
    tangent_start = from_runtime.outgoing.axis_vector
    tangent_end = point_mul(to_runtime.incoming.axis_vector, -1.0)
    chord = point_length(point_sub(end, start))
    ratio_a = float(from_road.corner_ratio_b or from_road.corner_ratio_a or 1.0)
    ratio_b = float(to_road.corner_ratio_a or to_road.corner_ratio_b or 1.0)
    curvature = max(
        0.2,
        min(
            1.8,
            (
                float(from_road.corner_curvature_b or from_road.corner_curvature_a or 0.6)
                + float(to_road.corner_curvature_a or to_road.corner_curvature_b or 0.6)
            )
            / 2.0,
        ),
    )
    control_distance = chord * 0.32 * ((ratio_a + ratio_b) / 2.0) * curvature
    control_a = point_add(start, point_mul(tangent_start, control_distance))
    control_b = point_sub(end, point_mul(tangent_end, control_distance))
    return _sample_cubic_bezier(start, control_a, control_b, end)


def _crosswalk_polygon(start: Point, end: Point, width: float, width_offset: float = 0.0) -> List[Point]:
    chord = point_sub(end, start)
    normal = normalize_vector(left_normal(chord))
    shifted_start = point_add(start, point_mul(normal, width_offset))
    shifted_end = point_add(end, point_mul(normal, width_offset))
    half_width = width / 2.0
    return [
        point_add(shifted_start, point_mul(normal, half_width)),
        point_add(shifted_end, point_mul(normal, half_width)),
        point_sub(shifted_end, point_mul(normal, half_width)),
        point_sub(shifted_start, point_mul(normal, half_width)),
    ]


def _build_additional_shapes(plan: NetworkPlan, report: ReportCollector) -> Tuple[List[PolyDef], List[PoiDef]]:
    polys: List[PolyDef] = []
    pois: List[PoiDef] = []

    for runtime in plan.road_runtimes.values():
        road = runtime.road
        for chain in (runtime.incoming, runtime.outgoing):
            for segment_index, segment in enumerate(chain.segments):
                band_map = _lane_band_map(segment)
                start_point = chain.boundary_points[segment_index]
                end_point = chain.boundary_points[segment_index + 1]
                for lane in segment.all_lanes:
                    if lane.lane_type != "greenBelt":
                        continue
                    inner_band, outer_band = band_map[lane.raw_index]
                    polygon = _rectangle_from_centerline(start_point, end_point, chain.side_vector, inner_band, outer_band)
                    polys.append(
                        PolyDef(
                            id=f"poly_{road.safe_id}_{chain.direction}_{segment_index}_greenbelt_{lane.raw_index}",
                            poly_type="ezdesignx.greenBelt",
                            color="34,139,34",
                            layer=3,
                            fill=True,
                            shape=polygon,
                        )
                    )

            if chain.structured_width > EPSILON:
                stop_distance = (
                    road.incoming_stop_line_distance if chain.direction == "incoming" else road.outgoing_stop_line_distance
                )
                if stop_distance is not None and stop_distance < sum(segment.length for segment in chain.segments) + EPSILON:
                    stop_center = point_add(chain.inner_point, point_mul(chain.axis_vector, stop_distance))
                    stop_polygon = _rectangle_from_centerline(
                        point_add(stop_center, point_mul(chain.axis_vector, -0.15)),
                        point_add(stop_center, point_mul(chain.axis_vector, 0.15)),
                        chain.side_vector,
                        -chain.structured_width / 2.0,
                        chain.structured_width / 2.0,
                    )
                    polys.append(
                        PolyDef(
                            id=f"poly_{road.safe_id}_{chain.direction}_stopline",
                            poly_type="ezdesignx.stopLine",
                            color="255,255,255",
                            layer=4,
                            fill=True,
                            shape=stop_polygon,
                        )
                    )
                    report.add_approx(
                    f"roads[{road.index}].{chain.direction}StopLineDistance",
                        "stopLineDistance 以附加 stop line polygon 近似表达",
                        distance=stop_distance,
                    )

        if road.median_width > EPSILON:
            road_axis = angle_to_vector(road.sumo_angle_deg)
            center = _chain_base_point(road, _road_left_vector(road))
            median_length = max(
                road.median_extension_distance + road.median_corner_radius * 2.0,
                6.0,
            )
            start = center
            end = point_add(center, point_mul(road_axis, median_length))
            polygon = _rectangle_from_centerline(
                start,
                end,
                left_normal(road_axis),
                -road.median_width / 2.0,
                road.median_width / 2.0,
            )
            polys.append(
                PolyDef(
                    id=f"poly_{road.safe_id}_median",
                    poly_type="ezdesignx.median",
                    color="180,180,180",
                    layer=2,
                    fill=True,
                    shape=polygon,
                )
            )

    for crosswalk_index, crosswalk in enumerate(plan.config.crosswalks):
        report.add_filtered(
            f"crosswalks[{crosswalk_index}]",
            "基础适配版不写入 crosswalk；保持旧核心风格，只输出主路网、简单中分带和停止线",
            crosswalkId=str(crosswalk.get("id") or f"crosswalk-{crosswalk_index}"),
            enabled=bool(crosswalk.get("enabled", True)),
        )

    return polys, pois


def build_network_plan(config: NormalizedConfig, report: ReportCollector) -> NetworkPlan:
    nodes_by_id: Dict[str, NodeDef] = {}
    edges: List[EdgeDef] = []
    road_runtimes: Dict[str, RoadRuntime] = {}

    for road in config.roads:
        outgoing_nodes, outgoing_edges, outgoing_runtime = _build_chain(road, "outgoing", config.driving_side, report)
        incoming_nodes, incoming_edges, incoming_runtime = _build_chain(road, "incoming", config.driving_side, report)
        for node in outgoing_nodes + incoming_nodes:
            nodes_by_id[node.id] = node
        edges.extend(outgoing_edges)
        edges.extend(incoming_edges)
        road_runtimes[road.id] = RoadRuntime(road=road, incoming=incoming_runtime, outgoing=outgoing_runtime)

    joins = [
        JoinDef(
            id="ezdesignx_center",
            node_ids=[
                runtime.incoming.inner_node_id
                for runtime in road_runtimes.values()
            ]
            + [
                runtime.outgoing.inner_node_id
                for runtime in road_runtimes.values()
            ],
            node_type="traffic_light" if len(config.roads) >= 3 else "priority",
        )
    ]

    connections: List[ConnectionDef] = []
    for runtime in road_runtimes.values():
        outgoing_groups = runtime.outgoing.emitted_groups
        outgoing_segments = runtime.outgoing.segments
        for group_index in range(len(outgoing_groups) - 1):
            source_group = outgoing_groups[group_index]
            target_group = outgoing_groups[group_index + 1]
            connections.extend(
                _build_lane_continuity_connections(
                    source_edge=source_group.edge,
                    source_segment=outgoing_segments[source_group.end_segment_index],
                    target_edge=target_group.edge,
                    target_segment=outgoing_segments[target_group.start_segment_index],
                )
            )

        incoming_groups = runtime.incoming.emitted_groups
        incoming_segments = runtime.incoming.segments
        for center_index in range(len(incoming_groups) - 1):
            outer_index = center_index + 1
            center_group = incoming_groups[center_index]
            outer_group = incoming_groups[outer_index]
            connections.extend(
                _build_lane_continuity_connections(
                    source_edge=outer_group.edge,
                    source_segment=incoming_segments[outer_group.start_segment_index],
                    target_edge=center_group.edge,
                    target_segment=incoming_segments[center_group.end_segment_index],
                )
            )

    ordered_roads = _sort_roads_clockwise(config.roads)
    connections.extend(_build_turn_connections(road_runtimes, ordered_roads, config.driving_side, report))

    plan = NetworkPlan(
        config=config,
        nodes=list(nodes_by_id.values()),
        joins=joins,
        edges=edges,
        connections=connections,
        polys=[],
        pois=[],
        road_runtimes=road_runtimes,
    )
    plan.polys, plan.pois = _build_additional_shapes(plan, report)
    return plan


def _edge_element(edge: EdgeDef) -> Element:
    attributes = {
        "id": edge.id,
        "from": edge.from_node,
        "to": edge.to_node,
        "numLanes": str(max(len(edge.lanes), 1)),
        "speed": f"{edge.speed:.2f}",
        "priority": str(edge.priority),
        "spreadType": edge.spread_type,
        "shape": format_shape(edge.shape),
    }
    if edge.name:
        attributes["name"] = edge.name
    edge_element = Element("edge", attributes)
    for lane in sorted(edge.lanes, key=lambda item: item.sumo_index or 0):
        lane_attributes = {
            "index": str(lane.sumo_index or 0),
            "width": f"{lane.width:.2f}",
            "speed": f"{lane.speed:.2f}",
        }
        if lane.allow:
            lane_attributes["allow"] = lane.allow
        if lane.disallow:
            lane_attributes["disallow"] = lane.disallow
        SubElement(edge_element, "lane", lane_attributes)
    for key, value in edge.params.items():
        SubElement(edge_element, "param", {"key": str(key), "value": str(value)})
    return edge_element


def _write_nodes_xml(plan: NetworkPlan, path: Path) -> None:
    root = Element("nodes")
    for node in sorted(plan.nodes, key=lambda item: item.id):
        attributes = {
            "id": node.id,
            "x": f"{node.x:.3f}",
            "y": f"{node.y:.3f}",
            "type": node.node_type,
        }
        if node.radius is not None:
            attributes["radius"] = f"{node.radius:.3f}"
        SubElement(root, "node", attributes)
    for join in plan.joins:
        SubElement(
            root,
            "join",
            {
                "id": join.id,
                "nodes": " ".join(join.node_ids),
                "type": join.node_type,
            },
        )
    write_xml(root, path)


def _write_edges_xml(plan: NetworkPlan, path: Path) -> None:
    root = Element("edges")
    for edge in sorted(plan.edges, key=lambda item: item.id):
        root.append(_edge_element(edge))
    write_xml(root, path)


def _write_connections_xml(plan: NetworkPlan, path: Path) -> None:
    root = Element("connections")
    for connection in plan.connections:
        attributes = {
            "from": connection.from_edge,
            "to": connection.to_edge,
            "fromLane": str(connection.from_lane),
            "toLane": str(connection.to_lane),
        }
        if connection.allow:
            attributes["allow"] = connection.allow
        if connection.shape:
            attributes["shape"] = format_shape(connection.shape)
        SubElement(root, "connection", attributes)
    write_xml(root, path)


def _write_additional_xml(plan: NetworkPlan, path: Path) -> None:
    root = Element("additional")
    for poly in plan.polys:
        SubElement(
            root,
            "poly",
            {
                "id": poly.id,
                "type": poly.poly_type,
                "color": poly.color,
                "layer": str(poly.layer),
                "fill": "1" if poly.fill else "0",
                "shape": format_shape(poly.shape),
            },
        )
    for poi in plan.pois:
        SubElement(
            root,
            "poi",
            {
                "id": poi.id,
                "type": poi.poi_type,
                "color": poi.color,
                "layer": str(poi.layer),
                "x": f"{poi.x:.3f}",
                "y": f"{poi.y:.3f}",
                "width": f"{poi.width:.2f}",
            },
        )
    write_xml(root, path)


def _write_sumocfg(artifacts: ConversionArtifacts, path: Path) -> None:
    root = Element("configuration")
    input_element = SubElement(root, "input")
    SubElement(input_element, "net-file", {"value": artifacts.net_xml.name})
    SubElement(input_element, "additional-files", {"value": artifacts.additional_xml.name})
    time_element = SubElement(root, "time")
    SubElement(time_element, "begin", {"value": "0"})
    SubElement(time_element, "end", {"value": "1"})
    report_element = SubElement(root, "report")
    SubElement(report_element, "verbose", {"value": "false"})
    SubElement(report_element, "no-step-log", {"value": "true"})
    write_xml(root, path)


def _base_report_dict(config: NormalizedConfig, plan: NetworkPlan, artifacts: ConversionArtifacts, report: ReportCollector) -> Dict[str, object]:
    return {
        "source": {
            "id": config.source_id,
            "name": config.name,
            "schemaKind": config.schema_kind,
            "adapterMode": "legacy-core-minimal-v1",
            "drivingSide": config.driving_side,
            "rotation": config.rotation_deg,
            "scale": config.scale,
            "roadCount": len(config.roads),
            "crosswalkCount": len(config.crosswalks),
        },
        "artifacts": {
            "nodesXml": str(artifacts.nodes_xml),
            "edgesXml": str(artifacts.edges_xml),
            "connectionsXml": str(artifacts.connections_xml),
            "netXml": str(artifacts.net_xml),
            "sumocfg": str(artifacts.sumocfg),
            "additionalXml": str(artifacts.additional_xml),
        },
        "summary": {
            "edgeCount": len(plan.edges),
            "connectionCount": len(plan.connections),
            "polyCount": len(plan.polys),
            "poiCount": len(plan.pois),
            "roads": [
                {
                    "roadId": road.id,
                    "incomingSegments": len(road.incoming_segments),
                    "outgoingSegments": len(road.outgoing_segments),
                    "incomingMotorLanes": sum(
                        1
                        for lane in road.incoming_segments[0].drivable_lanes
                        if lane.lane_type == "motor"
                    )
                    if road.incoming_segments
                    else 0,
                    "outgoingMotorLanes": sum(
                        1
                        for lane in road.outgoing_segments[0].drivable_lanes
                        if lane.lane_type == "motor"
                    )
                    if road.outgoing_segments
                    else 0,
                }
                for road in config.roads
            ],
        },
        **report.as_dict(),
    }


def _write_report_json(report_dict: Dict[str, object], path: Path) -> None:
    path.write_text(json.dumps(report_dict, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_binary(explicit_path: Optional[str], fallback_name: str) -> str:
    if explicit_path:
        return explicit_path
    discovered = shutil.which(fallback_name)
    if discovered:
        return discovered
    raise FileNotFoundError(f"无法找到 {fallback_name}，请通过命令行参数显式传入")


def prepare_artifacts(input_json: Path, output_dir: Path) -> ConversionArtifacts:
    stem = sanitize_filename(input_json.stem, "ezdesignx")
    output_dir.mkdir(parents=True, exist_ok=True)
    return ConversionArtifacts(
        input_json=input_json,
        output_dir=output_dir,
        stem=stem,
        nodes_xml=output_dir / f"{stem}.nod.xml",
        edges_xml=output_dir / f"{stem}.edg.xml",
        connections_xml=output_dir / f"{stem}.con.xml",
        net_xml=output_dir / f"{stem}.net.xml",
        additional_xml=output_dir / f"{stem}.add.xml",
        sumocfg=output_dir / f"{stem}.sumocfg",
        report_json=output_dir / f"{stem}.conversion-report.json",
    )


def generate_plain_network(
    input_json: Path,
    output_dir: Path,
) -> Tuple[NormalizedConfig, NetworkPlan, ConversionArtifacts, ReportCollector]:
    report = ReportCollector()
    config, report = load_and_normalize(input_json, report)
    plan = build_network_plan(config, report)
    artifacts = prepare_artifacts(input_json, output_dir)
    _write_nodes_xml(plan, artifacts.nodes_xml)
    _write_edges_xml(plan, artifacts.edges_xml)
    _write_connections_xml(plan, artifacts.connections_xml)
    _write_additional_xml(plan, artifacts.additional_xml)
    _write_sumocfg(artifacts, artifacts.sumocfg)
    return config, plan, artifacts, report


def run_netconvert(
    artifacts: ConversionArtifacts,
    netconvert_bin: str,
    driving_side: str,
) -> subprocess.CompletedProcess[str]:
    command = [
        netconvert_bin,
        "--node-files",
        str(artifacts.nodes_xml),
        "--edge-files",
        str(artifacts.edges_xml),
        "--connection-files",
        str(artifacts.connections_xml),
        "--output-file",
        str(artifacts.net_xml),
        "--offset.disable-normalization",
        "--plain.extend-edge-shape",
        "--precision",
        "4",
    ]
    if driving_side == "left":
        command.append("--lefthand")
    return run_command(command, cwd=artifacts.output_dir)


def convert_ezdesignx_json(
    input_json: Path,
    output_dir: Path,
    netconvert_bin: Optional[str] = None,
) -> Tuple[NormalizedConfig, NetworkPlan, ConversionArtifacts, ReportCollector, subprocess.CompletedProcess[str]]:
    resolved_netconvert = _find_binary(netconvert_bin, "netconvert")
    config, plan, artifacts, report = generate_plain_network(input_json, output_dir)
    netconvert_result = run_netconvert(artifacts, resolved_netconvert, config.driving_side)
    return config, plan, artifacts, report, netconvert_result


def finalize_report(
    config: NormalizedConfig,
    plan: NetworkPlan,
    artifacts: ConversionArtifacts,
    report: ReportCollector,
    validation_result: Dict[str, object],
    netconvert_result: subprocess.CompletedProcess[str],
) -> Dict[str, object]:
    report_dict = _base_report_dict(config, plan, artifacts, report)
    report_dict["netconvert"] = {
        "returncode": netconvert_result.returncode,
        "stdout": netconvert_result.stdout,
        "stderr": netconvert_result.stderr,
    }
    report_dict["validation"] = validation_result
    _write_report_json(report_dict, artifacts.report_json)
    return report_dict

# --- begin embedded validator.py ---
import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence



ANGLE_THRESHOLD = 1.0
LENGTH_ABS_THRESHOLD = 0.5
LENGTH_REL_THRESHOLD = 0.02
LANE_WIDTH_THRESHOLD = 0.1


def _find_binary(explicit_path: Optional[str], fallback_name: str) -> str:
    if explicit_path:
        return explicit_path
    discovered = shutil.which(fallback_name)
    if discovered:
        return discovered
    raise FileNotFoundError(f"无法找到 {fallback_name}，请通过命令行参数显式传入")


def _angular_difference(actual: float, expected: float) -> float:
    return abs(((actual - expected + 180.0) % 360.0) - 180.0)


def _parse_net_edges(net_xml: Path) -> Dict[str, Dict[str, object]]:
    tree = ET.parse(net_xml)
    root = tree.getroot()
    edges: Dict[str, Dict[str, object]] = {}
    for edge in root.findall("edge"):
        edge_id = edge.attrib.get("id", "")
        if edge_id.startswith(":"):
            continue
        lanes = edge.findall("lane")
        edges[edge_id] = {
            "laneCount": len(lanes),
            "laneWidths": [float(lane.attrib.get("width", "0") or 0.0) for lane in lanes],
            "laneSpeeds": [float(lane.attrib.get("speed", "0") or 0.0) for lane in lanes],
        }
    return edges


def _check_lengths(expected: float, actual: float) -> Dict[str, float]:
    difference = abs(expected - actual)
    relative = difference / max(expected, EPSILON)
    return {
        "expected": expected,
        "actual": actual,
        "difference": difference,
        "relativeDifference": relative,
    }


def _strict_metrics(config: NormalizedConfig, plan: NetworkPlan) -> Dict[str, object]:
    road_metrics: List[Dict[str, object]] = []
    max_angle_error = 0.0
    max_length_error = 0.0
    max_lane_width_error = 0.0

    for road in config.roads:
        runtime = plan.road_runtimes[road.id]
        incoming_expected = sum(segment.length for segment in road.incoming_segments)
        outgoing_expected = sum(segment.length for segment in road.outgoing_segments)
        incoming_actual = polyline_length(list(reversed(runtime.incoming.boundary_points)))
        outgoing_actual = polyline_length(runtime.outgoing.boundary_points)
        incoming_length_check = _check_lengths(incoming_expected, incoming_actual)
        outgoing_length_check = _check_lengths(outgoing_expected, outgoing_actual)

        incoming_lane_width_errors = [
            abs(source.width - target.width)
            for source, target in zip(road.incoming_segments[0].drivable_lanes, runtime.incoming.edges[0].lanes)
        ] if road.incoming_segments else []
        outgoing_lane_width_errors = [
            abs(source.width - target.width)
            for source, target in zip(road.outgoing_segments[0].drivable_lanes, runtime.outgoing.edges[0].lanes)
        ] if road.outgoing_segments else []

        road_angle_errors = {
            "outgoing": _angular_difference(runtime.outgoing.axis_angle_deg, road.sumo_angle_deg),
            "incoming": _angular_difference(runtime.incoming.axis_angle_deg, road.sumo_incoming_angle_deg),
        }
        max_angle_error = max(max_angle_error, road_angle_errors["outgoing"], road_angle_errors["incoming"])
        max_length_error = max(
            max_length_error,
            incoming_length_check["difference"],
            outgoing_length_check["difference"],
        )
        max_lane_width_error = max(
            max_lane_width_error,
            max(incoming_lane_width_errors or [0.0]),
            max(outgoing_lane_width_errors or [0.0]),
        )

        road_metrics.append(
            {
                "roadId": road.id,
                "angleError": road_angle_errors,
                "incomingLength": incoming_length_check,
                "outgoingLength": outgoing_length_check,
                "incomingLaneWidthErrors": incoming_lane_width_errors,
                "outgoingLaneWidthErrors": outgoing_lane_width_errors,
            }
        )

    return {
        "roadMetrics": road_metrics,
        "thresholds": {
            "angleDeg": ANGLE_THRESHOLD,
            "lengthAbs": LENGTH_ABS_THRESHOLD,
            "lengthRelative": LENGTH_REL_THRESHOLD,
            "laneWidth": LANE_WIDTH_THRESHOLD,
        },
        "maxAngleError": max_angle_error,
        "maxLengthError": max_length_error,
        "maxLaneWidthError": max_lane_width_error,
        "passed": (
            max_angle_error <= ANGLE_THRESHOLD
            and max_length_error <= LENGTH_ABS_THRESHOLD
            and max_lane_width_error <= LANE_WIDTH_THRESHOLD
        ),
    }


def validate_conversion(
    config: NormalizedConfig,
    plan: NetworkPlan,
    artifacts: ConversionArtifacts,
    validation_level: str,
    netconvert_result_returncode: int,
    sumo_bin: Optional[str] = None,
    sumo_gui_bin: Optional[str] = None,
) -> Dict[str, object]:
    result: Dict[str, object] = {
        "level": validation_level,
        "passed": True,
        "checks": [],
        "manualChecks": {
            "sumoGui": f"{sumo_gui_bin or 'sumo-gui'} -c {artifacts.sumocfg}",
            "netedit": f"netedit {artifacts.net_xml}",
        },
    }

    def add_check(name: str, passed: bool, **details: object) -> None:
        result["checks"].append({"name": name, "passed": passed, **details})
        if not passed:
            result["passed"] = False

    add_check("netconvert_returncode", netconvert_result_returncode == 0, returncode=netconvert_result_returncode)

    expected_files: Sequence[Path] = (
        artifacts.nodes_xml,
        artifacts.edges_xml,
        artifacts.connections_xml,
        artifacts.net_xml,
        artifacts.additional_xml,
        artifacts.sumocfg,
    )
    missing_files = [str(path) for path in expected_files if not path.exists()]
    add_check("artifacts_exist", not missing_files, missingFiles=missing_files)

    if validation_level == "basic" or not result["passed"]:
        return result

    net_edges = _parse_net_edges(artifacts.net_xml)
    expected_edge_count = len(plan.edges)
    add_check("edge_count_matches", len(net_edges) == expected_edge_count, expected=expected_edge_count, actual=len(net_edges))

    lane_mismatches: List[Dict[str, object]] = []
    for edge in plan.edges:
        actual = net_edges.get(edge.id)
        expected_lane_count = len(edge.lanes)
        if actual is None:
            lane_mismatches.append({"edgeId": edge.id, "reason": "missing_in_net"})
            continue
        if actual["laneCount"] != expected_lane_count:
            lane_mismatches.append(
                {
                    "edgeId": edge.id,
                    "expectedLaneCount": expected_lane_count,
                    "actualLaneCount": actual["laneCount"],
                }
            )
    add_check("lane_count_matches", not lane_mismatches, mismatches=lane_mismatches)

    road_checks: List[Dict[str, object]] = []
    for road in config.roads:
        runtime = plan.road_runtimes[road.id]
        expected_incoming_motor = sum(1 for lane in road.incoming_segments[0].drivable_lanes if lane.lane_type == "motor") if road.incoming_segments else 0
        expected_outgoing_motor = sum(1 for lane in road.outgoing_segments[0].drivable_lanes if lane.lane_type == "motor") if road.outgoing_segments else 0
        actual_incoming_motor = sum(1 for lane in runtime.incoming.edges[0].lanes if lane.lane_type == "motor") if runtime.incoming.edges else 0
        actual_outgoing_motor = sum(1 for lane in runtime.outgoing.edges[0].lanes if lane.lane_type == "motor") if runtime.outgoing.edges else 0
        road_checks.append(
            {
                "roadId": road.id,
                "expectedIncomingMotorLanes": expected_incoming_motor,
                "actualIncomingMotorLanes": actual_incoming_motor,
                "expectedOutgoingMotorLanes": expected_outgoing_motor,
                "actualOutgoingMotorLanes": actual_outgoing_motor,
            }
        )
    add_check(
        "motor_lane_count_matches",
        all(
            item["expectedIncomingMotorLanes"] == item["actualIncomingMotorLanes"]
            and item["expectedOutgoingMotorLanes"] == item["actualOutgoingMotorLanes"]
            for item in road_checks
        ),
        roads=road_checks,
    )

    add_check("connection_count_nonzero", len(plan.connections) > 0, connectionCount=len(plan.connections))

    resolved_sumo = _find_binary(sumo_bin, "sumo")
    sumo_result = run_command(
        [
            resolved_sumo,
            "-c",
            str(artifacts.sumocfg),
            "--quit-on-end",
            "--duration-log.disable",
            "true",
            "--no-step-log",
            "true",
        ],
        cwd=artifacts.output_dir,
    )
    add_check(
        "sumo_headless_load",
        sumo_result.returncode == 0,
        returncode=sumo_result.returncode,
        stdout=sumo_result.stdout,
        stderr=sumo_result.stderr,
    )

    if validation_level != "strict":
        return result

    strict = _strict_metrics(config, plan)
    result["strictMetrics"] = strict
    add_check("strict_thresholds", bool(strict["passed"]), maxAngleError=strict["maxAngleError"], maxLengthError=strict["maxLengthError"], maxLaneWidthError=strict["maxLaneWidthError"])
    return result


VALIDATION_LEVELS = ("basic", "topology", "strict")


def _stringify_validation_passed(validation_result: Dict[str, object]) -> str:
    return "yes" if bool(validation_result.get("passed")) else "no"


def run_ezdesignx_conversion(
    input_json: str | Path,
    output_dir: str | Path,
    validation: str = "topology",
    netconvert_bin: Optional[str] = None,
    sumo_bin: Optional[str] = None,
    sumo_gui_bin: Optional[str] = None,
) -> Dict[str, Any]:
    """Run an ezdesignX -> SUMO conversion and return a serializable summary."""

    input_path = Path(input_json).expanduser().resolve()
    output_path = Path(output_dir).expanduser().resolve()
    validation_level = str(validation).strip().lower()

    if not input_path.exists():
        raise FileNotFoundError(f"Input file does not exist: {input_path}")
    if validation_level not in VALIDATION_LEVELS:
        raise ValueError(
            f"validation must be one of {', '.join(VALIDATION_LEVELS)}, got {validation!r}"
        )

    config, plan, artifacts, report, netconvert_result = convert_ezdesignx_json(
        input_json=input_path,
        output_dir=output_path,
        netconvert_bin=netconvert_bin,
    )
    validation_result = validate_conversion(
        config=config,
        plan=plan,
        artifacts=artifacts,
        validation_level=validation_level,
        netconvert_result_returncode=netconvert_result.returncode,
        sumo_bin=sumo_bin,
        sumo_gui_bin=sumo_gui_bin,
    )
    report_dict = finalize_report(
        config=config,
        plan=plan,
        artifacts=artifacts,
        report=report,
        validation_result=validation_result,
        netconvert_result=netconvert_result,
    )

    ok = netconvert_result.returncode == 0 and bool(validation_result.get("passed"))
    return {
        "ok": ok,
        "input_json": str(input_path),
        "output_dir": str(output_path),
        "validation": validation_level,
        "validation_passed": bool(validation_result.get("passed")),
        "netconvert_returncode": netconvert_result.returncode,
        "schema_kind": report_dict["source"]["schemaKind"],
        "adapter_mode": report_dict["source"]["adapterMode"],
        "artifacts": {
            "nodes_xml": str(artifacts.nodes_xml),
            "edges_xml": str(artifacts.edges_xml),
            "connections_xml": str(artifacts.connections_xml),
            "net_xml": str(artifacts.net_xml),
            "additional_xml": str(artifacts.additional_xml),
            "sumocfg": str(artifacts.sumocfg),
            "report_json": str(artifacts.report_json),
        },
        "validation_result": validation_result,
        "report": report_dict,
    }


def format_ezdesignx_conversion_summary(result: Dict[str, Any]) -> str:
    """Format a user-facing summary string for MCP responses."""

    artifacts = result["artifacts"]
    headline = (
        "ezdesignX -> SUMO conversion completed."
        if result["ok"]
        else "ezdesignX -> SUMO conversion finished with validation issues."
    )
    return "\n".join(
        [
            headline,
            f"Input file: {result['input_json']}",
            f"Output directory: {result['output_dir']}",
            f"schemaKind: {result['schema_kind']}",
            f"adapterMode: {result['adapter_mode']}",
            f"Validation: {result['validation']}",
            f"Validation passed: {_stringify_validation_passed(result['validation_result'])}",
            f"netconvert return code: {result['netconvert_returncode']}",
            f"net.xml: {artifacts['net_xml']}",
            f"sumocfg: {artifacts['sumocfg']}",
            f"Report: {artifacts['report_json']}",
        ]
    )


def convert_ezdesignx_network(
    input_json: str,
    output_dir: str,
    validation: str = "topology",
    netconvert_bin: Optional[str] = None,
    sumo_bin: Optional[str] = None,
    sumo_gui_bin: Optional[str] = None,
) -> str:
    """High-level wrapper used by MCP tools."""

    try:
        result = run_ezdesignx_conversion(
            input_json=input_json,
            output_dir=output_dir,
            validation=validation,
            netconvert_bin=netconvert_bin,
            sumo_bin=sumo_bin,
            sumo_gui_bin=sumo_gui_bin,
        )
    except Exception as exc:
        return f"Error converting ezdesignX network: {type(exc).__name__}: {exc}"
    return format_ezdesignx_conversion_summary(result)


__all__ = [
    "VALIDATION_LEVELS",
    "build_network_plan",
    "convert_ezdesignx_json",
    "convert_ezdesignx_network",
    "finalize_report",
    "format_ezdesignx_conversion_summary",
    "load_and_normalize",
    "run_ezdesignx_conversion",
    "validate_conversion",
]
