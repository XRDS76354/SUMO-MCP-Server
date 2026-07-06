"""Structured, streaming analysis of SUMO output files.

FCD dumps easily reach hundreds of MB, so everything here uses
``xml.etree.ElementTree.iterparse`` with ``elem.clear()`` — memory stays flat
regardless of file size, and ``max_elements`` caps the work (results are then
flagged ``truncated``). Gzipped outputs (``.gz``) are handled transparently.

Standard library only — no pandas — so the base install stays lightweight.
"""
from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import IO, Any, Dict, List, Optional, cast

from sumo_mcp.models import ErrorCode

_KIND_BY_ROOT = {
    "summary": "summary",
    "tripinfos": "tripinfo",
    "fcd-export": "fcd",
    "queue-export": "queue",
    "emission-export": "emission",
    "netstate": "netstate",
}


def _open_maybe_gzip(path: Path) -> IO[bytes]:
    if path.suffix == ".gz":
        return cast(IO[bytes], gzip.open(path, "rb"))
    return open(path, "rb")


def _stats(values: List[float]) -> Dict[str, float]:
    if not values:
        return {}
    ordered = sorted(values)
    n = len(ordered)

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, round(p * (n - 1))))
        return ordered[idx]

    return {
        "count": float(n),
        "mean": round(sum(ordered) / n, 4),
        "min": ordered[0],
        "max": ordered[-1],
        "p50": pct(0.50),
        "p95": pct(0.95),
    }


def _get_float(elem: ET.Element, attr: str) -> Optional[float]:
    raw = elem.get(attr)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def analyze_output(
    file_path: str,
    kind: Optional[str] = None,
    max_elements: int = 500_000,
) -> Dict[str, Any]:
    """Analyze one SUMO output file; returns metrics without loading it whole."""
    path = Path(file_path)
    if not path.is_file():
        return {
            "ok": False, "file": str(path), "kind": kind,
            "error": {"code": ErrorCode.FILE_NOT_FOUND,
                      "message": f"File not found: {path}"},
        }

    try:
        with _open_maybe_gzip(path) as fh:
            context = ET.iterparse(fh, events=("start", "end"))
            _, root = next(context)  # grab root element
            detected = _KIND_BY_ROOT.get(root.tag, "generic")
            effective_kind = kind or detected

            if effective_kind == "summary":
                payload = _analyze_summary(context, root, max_elements)
            elif effective_kind == "tripinfo":
                payload = _analyze_tripinfo(context, root, max_elements)
            elif effective_kind == "fcd":
                payload = _analyze_fcd(context, root, max_elements)
            elif effective_kind == "queue":
                payload = _analyze_queue(context, root, max_elements)
            elif effective_kind == "emission":
                payload = _analyze_emission(context, root, max_elements)
            else:
                payload = _analyze_generic(context, root, max_elements)
    except ET.ParseError as exc:
        return {
            "ok": False, "file": str(path), "kind": kind,
            "error": {"code": ErrorCode.EXECUTION_FAILED,
                      "message": f"XML parse error: {exc}"},
        }
    except OSError as exc:
        return {
            "ok": False, "file": str(path), "kind": kind,
            "error": {"code": ErrorCode.EXECUTION_FAILED,
                      "message": f"Failed to read file: {exc}"},
        }

    payload.update({"ok": True, "file": str(path), "kind": effective_kind})
    return payload


def _analyze_summary(context: Any, root: ET.Element, max_elements: int) -> Dict[str, Any]:
    steps = 0
    last: Dict[str, float] = {}
    waiting_series: List[float] = []
    speed_series: List[float] = []
    truncated = False

    for event, elem in context:
        if event != "end" or elem.tag != "step":
            continue
        steps += 1
        for attr in ("time", "loaded", "inserted", "running", "waiting", "ended",
                     "halting", "meanWaitingTime", "meanSpeed"):
            value = _get_float(elem, attr)
            if value is not None:
                last[attr] = value
        mwt = _get_float(elem, "meanWaitingTime")
        if mwt is not None and mwt >= 0:
            waiting_series.append(mwt)
        ms = _get_float(elem, "meanSpeed")
        if ms is not None and ms >= 0:
            speed_series.append(ms)
        elem.clear()
        root.clear()
        if steps >= max_elements:
            truncated = True
            break

    metrics: Dict[str, Any] = {"last_step": last}
    if waiting_series:
        metrics["mean_waiting_time_avg"] = round(sum(waiting_series) / len(waiting_series), 4)
    if speed_series:
        metrics["mean_speed_avg"] = round(sum(speed_series) / len(speed_series), 4)
    return {"metrics": metrics, "counts": {"steps": steps}, "truncated": truncated}


def _analyze_tripinfo(context: Any, root: ET.Element, max_elements: int) -> Dict[str, Any]:
    series: Dict[str, List[float]] = {
        "duration": [], "waitingTime": [], "routeLength": [],
        "timeLoss": [], "departDelay": [],
    }
    trips = 0
    truncated = False

    for event, elem in context:
        if event != "end" or elem.tag != "tripinfo":
            continue
        trips += 1
        for attr, bucket in series.items():
            value = _get_float(elem, attr)
            if value is not None:
                bucket.append(value)
        elem.clear()
        root.clear()
        if trips >= max_elements:
            truncated = True
            break

    metrics = {attr: _stats(values) for attr, values in series.items() if values}
    return {"metrics": metrics, "counts": {"trips": trips}, "truncated": truncated}


def _analyze_fcd(context: Any, root: ET.Element, max_elements: int) -> Dict[str, Any]:
    timesteps = 0
    samples = 0
    speed_sum = 0.0
    speed_max = 0.0
    truncated = False

    for event, elem in context:
        if event != "end":
            continue
        if elem.tag == "vehicle":
            samples += 1
            speed = _get_float(elem, "speed")
            if speed is not None:
                speed_sum += speed
                speed_max = max(speed_max, speed)
            elem.clear()
        elif elem.tag == "timestep":
            timesteps += 1
            elem.clear()
            root.clear()
        if samples >= max_elements:
            truncated = True
            break

    metrics: Dict[str, Any] = {}
    if samples:
        metrics["speed_mean"] = round(speed_sum / samples, 4)
        metrics["speed_max"] = speed_max
    if timesteps:
        metrics["vehicles_per_timestep_avg"] = round(samples / timesteps, 2)
    return {
        "metrics": metrics,
        "counts": {"timesteps": timesteps, "vehicle_samples": samples},
        "truncated": truncated,
    }


def _analyze_queue(context: Any, root: ET.Element, max_elements: int) -> Dict[str, Any]:
    lanes = 0
    qtime: List[float] = []
    qlen: List[float] = []
    truncated = False

    for event, elem in context:
        if event != "end":
            continue
        if elem.tag == "lane":
            lanes += 1
            value = _get_float(elem, "queueing_time")
            if value is not None:
                qtime.append(value)
            value = _get_float(elem, "queueing_length")
            if value is not None:
                qlen.append(value)
            elem.clear()
        elif elem.tag == "data":
            elem.clear()
            root.clear()
        if lanes >= max_elements:
            truncated = True
            break

    metrics: Dict[str, Any] = {}
    if qtime:
        metrics["queueing_time"] = {"mean": round(sum(qtime) / len(qtime), 4), "max": max(qtime)}
    if qlen:
        metrics["queueing_length"] = {"mean": round(sum(qlen) / len(qlen), 4), "max": max(qlen)}
    return {"metrics": metrics, "counts": {"lane_records": lanes}, "truncated": truncated}


def _analyze_emission(context: Any, root: ET.Element, max_elements: int) -> Dict[str, Any]:
    pollutants = ("CO2", "CO", "NOx", "PMx", "HC", "fuel")
    totals = {p: 0.0 for p in pollutants}
    samples = 0
    truncated = False

    for event, elem in context:
        if event != "end":
            continue
        if elem.tag == "vehicle":
            samples += 1
            for p in pollutants:
                value = _get_float(elem, p)
                if value is not None:
                    totals[p] += value
            elem.clear()
        elif elem.tag == "timestep":
            elem.clear()
            root.clear()
        if samples >= max_elements:
            truncated = True
            break

    metrics: Dict[str, Any] = {
        f"{p}_total": round(total, 4) for p, total in totals.items() if total > 0
    }
    if samples:
        for p, total in totals.items():
            if total > 0:
                metrics[f"{p}_mean_per_sample"] = round(total / samples, 6)
    return {"metrics": metrics, "counts": {"vehicle_samples": samples}, "truncated": truncated}


def _analyze_generic(context: Any, root: ET.Element, max_elements: int) -> Dict[str, Any]:
    """Unknown output type: count elements per tag so the agent can decide."""
    tag_counts: Dict[str, int] = {}
    total = 0
    truncated = False

    for event, elem in context:
        if event != "end" or elem is root:  # root itself is reported as root_tag
            continue
        tag_counts[elem.tag] = tag_counts.get(elem.tag, 0) + 1
        total += 1
        elem.clear()
        if total % 1000 == 0:
            root.clear()
        if total >= max_elements:
            truncated = True
            break

    top = dict(sorted(tag_counts.items(), key=lambda kv: -kv[1])[:20])
    return {
        "metrics": {"root_tag": root.tag, "element_counts": top},
        "counts": {"total_elements": total},
        "truncated": truncated,
        "notes": "Unknown output type; pass kind= explicitly for typed metrics.",
    }
