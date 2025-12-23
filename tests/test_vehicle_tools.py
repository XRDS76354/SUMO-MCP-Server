import os
import sys
import pytest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from utils.connection import SUMOConnection
from mcp_tools.vehicle import get_vehicles, get_vehicle_speed

class TestSUMOConnection:
    @pytest.fixture
    def conn_manager(self):
        # Reset singleton
        SUMOConnection._instance = None
        return SUMOConnection()

    @patch("utils.connection.find_sumo_binary", return_value="/usr/bin/sumo")
    @patch("traci.start")
    def test_connect_new(self, mock_start, _mock_find_binary, conn_manager):
        conn_manager.connect(config_file="test.sumocfg")
        mock_start.assert_called_once()
        assert conn_manager.is_connected()

    @patch("traci.init")
    def test_connect_existing(self, mock_init, conn_manager):
        conn_manager.connect()
        mock_init.assert_called_once()
        assert conn_manager.is_connected()

    @patch("traci.close")
    def test_disconnect(self, mock_close, conn_manager):
        conn_manager._connected = True
        conn_manager.disconnect()
        mock_close.assert_called_once()
        assert not conn_manager.is_connected()

class TestVehicleTools:
    @patch("utils.connection.connection_manager.is_connected", return_value=True)
    @patch("traci.vehicle.getIDList")
    def test_get_vehicles(self, mock_get_ids, mock_is_connected):
        mock_get_ids.return_value = ("v1", "v2")
        vehs = get_vehicles()
        assert vehs == ["v1", "v2"]

    @patch("utils.connection.connection_manager.is_connected", return_value=True)
    @patch("traci.vehicle.getSpeed")
    def test_get_vehicle_speed(self, mock_get_speed, mock_is_connected):
        mock_get_speed.return_value = 10.5
        speed = get_vehicle_speed("v1")
        assert speed == 10.5

    @patch("utils.connection.connection_manager.is_connected", return_value=False)
    def test_get_vehicles_disconnected(self, mock_is_connected):
        vehs = get_vehicles()
        assert vehs == []
