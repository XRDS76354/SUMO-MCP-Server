import os
from unittest.mock import patch

from utils.sumo import find_sumo_home


def test_find_sumo_home_windows_common_paths() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with patch("sys.platform", "win32"):
            with patch("utils.sumo.find_sumo_binary", return_value="sumo"):
                with patch("pathlib.Path.exists", return_value=True):
                    assert find_sumo_home() == "C:/Program Files/Eclipse/sumo"


def test_find_sumo_home_macos_homebrew_cellar() -> None:
    homebrew_sumo_home = "/usr/local/Cellar/sumo/1.2.3/share/sumo"
    with patch.dict(os.environ, {}, clear=True):
        with patch("sys.platform", "darwin"):
            with patch("utils.sumo.find_sumo_binary", return_value="sumo"):
                with patch("utils.sumo.glob.glob", return_value=[homebrew_sumo_home]):
                    with patch("pathlib.Path.exists", return_value=True):
                        assert find_sumo_home() == homebrew_sumo_home

