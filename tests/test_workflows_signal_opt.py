import os
import re
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


# Add src to path so imports work without installation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from workflows.signal_opt import signal_opt_workflow


def test_cross_drive_paths(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()

    net_file = source_dir / "net.xml"
    route_file = source_dir / "routes.xml"
    net_file.write_text("<net/>", encoding="utf-8")
    route_file.write_text("<routes/>", encoding="utf-8")

    with (
        pytest.warns(RuntimeWarning),
        patch("workflows.signal_opt.os.path.relpath", side_effect=ValueError("cross-drive")),
        patch("workflows.signal_opt.run_simple_simulation", return_value="OK"),
        patch("workflows.signal_opt.analyze_fcd", return_value="analysis"),
        patch("workflows.signal_opt.tls_cycle_adaptation", return_value="OK"),
    ):
        result = signal_opt_workflow(
            net_file=str(net_file),
            route_file=str(route_file),
            output_dir=str(output_dir),
            steps=10,
            use_coordinator=False,
        )

    assert "Signal Optimization Workflow Completed" in result

    assert (output_dir / "net.xml").exists()
    assert (output_dir / "routes.xml").exists()

    baseline_cfg = (output_dir / "baseline.sumocfg").read_text(encoding="utf-8")
    assert 'net-file value="net.xml"' in baseline_cfg
    assert 'route-files value="routes.xml"' in baseline_cfg

    assert re.search(r"[A-Z]:[\\\\/]", baseline_cfg) is None
