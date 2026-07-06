"""Preflight validation for SUMO-RL experiments."""
from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Dict, List, Optional

from sumo_mcp.models import ErrorCode
from sumo_mcp.rl.algorithms import algorithm_status
from sumo_mcp.utils.sumo import find_sumo_binary, find_sumo_home


def _check(name: str, passed: bool, detail: str, *, code: Optional[str] = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {"check": name, "passed": passed, "detail": detail}
    if code:
        item["code"] = code
    return item


def _parse_xml(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _count_demands(root: ET.Element) -> int:
    return sum(1 for tag in ("vehicle", "flow", "trip") for _ in root.iter(tag))


def _traffic_light_summary(root: ET.Element) -> Dict[str, Any]:
    tls = list(root.iter("tlLogic"))
    green_phases = 0
    for logic in tls:
        for phase in logic.iter("phase"):
            state = phase.attrib.get("state", "")
            if "G" in state or "g" in state:
                green_phases += 1
    return {"tl_logic_count": len(tls), "green_phase_count": green_phases}


def validate_rl_environment(
    net_file: str,
    route_file: str,
    *,
    algorithm: str = "ql",
    delta_time: int = 5,
    yellow_time: int = 2,
) -> Dict[str, Any]:
    """Validate whether a SUMO network/route pair is suitable for RL training."""
    checks: List[Dict[str, Any]] = []

    sumo_home = find_sumo_home()
    checks.append(_check(
        "sumo_home",
        bool(sumo_home),
        f"SUMO_HOME={os.environ.get('SUMO_HOME') or sumo_home or 'not found'}",
        code=None if sumo_home else ErrorCode.SUMO_NOT_FOUND,
    ))

    sumo_binary = find_sumo_binary("sumo")
    checks.append(_check(
        "sumo_binary",
        bool(sumo_binary),
        sumo_binary or "sumo binary not found",
        code=None if sumo_binary else ErrorCode.SUMO_NOT_FOUND,
    ))

    sumo_rl_available = find_spec("sumo_rl") is not None
    checks.append(_check(
        "sumo_rl_import",
        sumo_rl_available,
        "sumo_rl importable" if sumo_rl_available else "sumo_rl is not installed",
        code=None if sumo_rl_available else ErrorCode.DEPENDENCY_MISSING,
    ))

    algo = algorithm_status(algorithm)
    checks.append(_check(
        "algorithm",
        algo is not None,
        f"algorithm={algorithm}" if algo is not None else f"unknown algorithm {algorithm!r}",
        code=None if algo is not None else ErrorCode.INVALID_ARGUMENT,
    ))
    if algo is not None and not algo["available"]:
        checks.append(_check(
            "algorithm_dependencies",
            False,
            f"{algorithm} requires {algo.get('dependency') or 'optional dependencies'}",
            code=ErrorCode.DEPENDENCY_MISSING,
        ))

    if delta_time <= yellow_time:
        checks.append(_check(
            "timing",
            False,
            f"delta_time ({delta_time}) must be > yellow_time ({yellow_time})",
            code=ErrorCode.INVALID_ARGUMENT,
        ))
    else:
        checks.append(_check("timing", True, f"delta_time={delta_time}, yellow_time={yellow_time}"))

    net_path = Path(net_file)
    route_path = Path(route_file)
    net_root: Optional[ET.Element] = None
    route_root: Optional[ET.Element] = None

    if not net_path.is_file():
        checks.append(_check("net_file", False, f"network file not found: {net_file}", code=ErrorCode.FILE_NOT_FOUND))
    else:
        try:
            net_root = _parse_xml(net_path)
            checks.append(_check("net_xml", True, f"parsed {net_file}"))
        except ET.ParseError as exc:
            checks.append(_check("net_xml", False, f"invalid network XML: {exc}", code=ErrorCode.VALIDATION_FAILED))

    if not route_path.is_file():
        checks.append(_check("route_file", False, f"route file not found: {route_file}", code=ErrorCode.FILE_NOT_FOUND))
    else:
        try:
            route_root = _parse_xml(route_path)
            checks.append(_check("route_xml", True, f"parsed {route_file}"))
        except ET.ParseError as exc:
            checks.append(_check("route_xml", False, f"invalid route XML: {exc}", code=ErrorCode.VALIDATION_FAILED))

    if net_root is not None:
        tls_summary = _traffic_light_summary(net_root)
        checks.append(_check(
            "traffic_lights",
            tls_summary["tl_logic_count"] > 0,
            f"{tls_summary['tl_logic_count']} tlLogic element(s)",
            code=None if tls_summary["tl_logic_count"] > 0 else ErrorCode.VALIDATION_FAILED,
        ))
        checks.append(_check(
            "green_phases",
            tls_summary["green_phase_count"] > 0,
            f"{tls_summary['green_phase_count']} phase(s) include green states",
            code=None if tls_summary["green_phase_count"] > 0 else ErrorCode.VALIDATION_FAILED,
        ))

    if route_root is not None:
        demand_count = _count_demands(route_root)
        checks.append(_check(
            "demand",
            demand_count > 0,
            f"{demand_count} vehicle/flow/trip demand element(s)",
            code=None if demand_count > 0 else ErrorCode.VALIDATION_FAILED,
        ))

    ok = all(c["passed"] for c in checks)
    failed = [c for c in checks if not c["passed"]]
    return {
        "ok": ok,
        "summary": "RL environment preflight passed." if ok else f"RL preflight failed: {len(failed)} issue(s).",
        "checks": checks,
        "failed_checks": failed,
    }
