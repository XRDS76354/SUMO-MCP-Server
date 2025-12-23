import os
import sys
from unittest.mock import patch

import pytest


# Add src to path so imports work without installation
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from utils.sumo import find_sumo_binary


def test_find_sumo_binary_checkbinary_systemexit_fallback() -> None:
    with (
        patch("utils.sumo.sumolib.checkBinary", side_effect=SystemExit(1)),
        patch("utils.sumo.shutil.which", return_value="/usr/bin/sumo"),
    ):
        assert find_sumo_binary("sumo") == "/usr/bin/sumo"


def test_find_sumo_binary_checkbinary_oserror_fallback() -> None:
    with (
        patch("utils.sumo.sumolib.checkBinary", side_effect=OSError("no sumo")),
        patch("utils.sumo.shutil.which", return_value="/usr/bin/sumo"),
    ):
        assert find_sumo_binary("sumo") == "/usr/bin/sumo"


def test_find_sumo_binary_found_absolute() -> None:
    with (
        patch("utils.sumo.sumolib.checkBinary", return_value="/usr/bin/sumo"),
        patch("utils.sumo.shutil.which", return_value=None),
    ):
        assert find_sumo_binary("sumo") == "/usr/bin/sumo"


def test_find_sumo_binary_checkbinary_returns_name() -> None:
    with (
        patch("utils.sumo.sumolib.checkBinary", return_value="sumo"),
        patch("utils.sumo.shutil.which", return_value=None),
    ):
        assert find_sumo_binary("sumo") is None


def test_find_sumo_binary_checkbinary_attributeerror_not_caught() -> None:
    with patch("utils.sumo.sumolib.checkBinary", side_effect=AttributeError("bug")):
        with pytest.raises(AttributeError):
            find_sumo_binary("sumo")
