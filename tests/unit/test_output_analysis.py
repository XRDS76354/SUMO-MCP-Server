"""Unit tests for streaming SUMO output analysis (no SUMO required)."""
from __future__ import annotations

import gzip
from pathlib import Path

from sumo_mcp.analysis import analyze_output

SUMMARY_XML = """<?xml version="1.0"?>
<summary>
  <step time="0.00" loaded="2" inserted="2" running="2" waiting="0" ended="0" halting="0"
        meanWaitingTime="0.00" meanSpeed="10.00"/>
  <step time="1.00" loaded="4" inserted="3" running="3" waiting="1" ended="0" halting="1"
        meanWaitingTime="2.00" meanSpeed="8.00"/>
  <step time="2.00" loaded="4" inserted="4" running="2" waiting="0" ended="2" halting="0"
        meanWaitingTime="4.00" meanSpeed="6.00"/>
</summary>
"""

TRIPINFO_XML = """<?xml version="1.0"?>
<tripinfos>
  <tripinfo id="v0" duration="10" waitingTime="2" routeLength="100" timeLoss="3" departDelay="0"/>
  <tripinfo id="v1" duration="20" waitingTime="4" routeLength="200" timeLoss="6" departDelay="1"/>
  <tripinfo id="v2" duration="30" waitingTime="6" routeLength="300" timeLoss="9" departDelay="2"/>
</tripinfos>
"""

FCD_XML = """<?xml version="1.0"?>
<fcd-export>
  <timestep time="0.00">
    <vehicle id="v0" speed="5.0" x="1" y="1"/>
    <vehicle id="v1" speed="15.0" x="2" y="2"/>
  </timestep>
  <timestep time="1.00">
    <vehicle id="v0" speed="10.0" x="3" y="3"/>
  </timestep>
</fcd-export>
"""

QUEUE_XML = """<?xml version="1.0"?>
<queue-export>
  <data timestep="0.00">
    <lanes>
      <lane id="a_0" queueing_time="0.0" queueing_length="0.0"/>
      <lane id="b_0" queueing_time="10.0" queueing_length="50.0"/>
    </lanes>
  </data>
</queue-export>
"""

EMISSION_XML = """<?xml version="1.0"?>
<emission-export>
  <timestep time="0.00">
    <vehicle id="v0" CO2="100.5" NOx="0.5" PMx="0.02" fuel="43.1" CO="2.0" HC="0.1"/>
    <vehicle id="v1" CO2="200.5" NOx="1.5" PMx="0.04" fuel="86.2" CO="4.0" HC="0.2"/>
  </timestep>
</emission-export>
"""


def _write(tmp_path: Path, name: str, content: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_summary_metrics(tmp_path: Path) -> None:
    result = analyze_output(_write(tmp_path, "summary.xml", SUMMARY_XML))
    assert result["ok"] is True
    assert result["kind"] == "summary"  # auto-detected
    assert result["counts"]["steps"] == 3
    last = result["metrics"]["last_step"]
    assert last["time"] == 2.0 and last["ended"] == 2.0
    assert result["metrics"]["mean_waiting_time_avg"] == 2.0   # (0+2+4)/3
    assert result["metrics"]["mean_speed_avg"] == 8.0          # (10+8+6)/3
    assert result["truncated"] is False


def test_tripinfo_metrics(tmp_path: Path) -> None:
    result = analyze_output(_write(tmp_path, "tripinfo.xml", TRIPINFO_XML))
    assert result["kind"] == "tripinfo"
    assert result["counts"]["trips"] == 3
    duration = result["metrics"]["duration"]
    assert duration["mean"] == 20.0 and duration["min"] == 10.0 and duration["max"] == 30.0
    assert duration["p50"] == 20.0
    assert result["metrics"]["waitingTime"]["mean"] == 4.0


def test_fcd_metrics(tmp_path: Path) -> None:
    result = analyze_output(_write(tmp_path, "fcd.xml", FCD_XML))
    assert result["kind"] == "fcd"
    assert result["counts"] == {"timesteps": 2, "vehicle_samples": 3}
    assert result["metrics"]["speed_mean"] == 10.0  # (5+15+10)/3
    assert result["metrics"]["speed_max"] == 15.0
    assert result["metrics"]["vehicles_per_timestep_avg"] == 1.5


def test_queue_metrics(tmp_path: Path) -> None:
    result = analyze_output(_write(tmp_path, "queue.xml", QUEUE_XML))
    assert result["kind"] == "queue"
    assert result["counts"]["lane_records"] == 2
    assert result["metrics"]["queueing_time"] == {"mean": 5.0, "max": 10.0}
    assert result["metrics"]["queueing_length"] == {"mean": 25.0, "max": 50.0}


def test_emission_metrics(tmp_path: Path) -> None:
    result = analyze_output(_write(tmp_path, "emission.xml", EMISSION_XML))
    assert result["kind"] == "emission"
    assert result["counts"]["vehicle_samples"] == 2
    assert result["metrics"]["CO2_total"] == 301.0
    assert result["metrics"]["NOx_total"] == 2.0
    assert result["metrics"]["CO2_mean_per_sample"] == 150.5


def test_gzip_transparency(tmp_path: Path) -> None:
    gz_path = tmp_path / "summary.xml.gz"
    with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
        fh.write(SUMMARY_XML)
    result = analyze_output(str(gz_path))
    assert result["ok"] is True and result["counts"]["steps"] == 3


def test_kind_override_and_generic_fallback(tmp_path: Path) -> None:
    # unknown root tag -> generic with tag census
    generic = _write(tmp_path, "custom.xml", "<mystery><a/><a/><b/></mystery>")
    result = analyze_output(generic)
    assert result["kind"] == "generic"
    assert result["metrics"]["element_counts"] == {"a": 2, "b": 1}
    assert "notes" in result

    # explicit kind wins over detection
    result = analyze_output(_write(tmp_path, "s.xml", SUMMARY_XML), kind="generic")
    assert result["kind"] == "generic"


def test_max_elements_truncation(tmp_path: Path) -> None:
    result = analyze_output(_write(tmp_path, "t.xml", TRIPINFO_XML), max_elements=2)
    assert result["ok"] is True
    assert result["truncated"] is True
    assert result["counts"]["trips"] == 2


def test_missing_file_and_broken_xml(tmp_path: Path) -> None:
    result = analyze_output(str(tmp_path / "nope.xml"))
    assert result["ok"] is False and result["error"]["code"] == "FILE_NOT_FOUND"

    broken = _write(tmp_path, "broken.xml", "<summary><step time='0'")
    result = analyze_output(broken)
    assert result["ok"] is False and result["error"]["code"] == "EXECUTION_FAILED"
    assert "parse error" in result["error"]["message"].lower()
