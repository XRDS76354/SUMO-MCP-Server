import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from server import manage_network, manage_demand, optimize_traffic_signals, run_workflow, query_simulation_state

class TestAPIAliases(unittest.TestCase):
    
    @patch('server.netconvert')
    def test_manage_network_alias(self, mock_netconvert):
        # Test 'convert_osm' alias
        result = manage_network("convert_osm", "out.net.xml", {"osm_file": "map.osm"})
        mock_netconvert.assert_called_with("map.osm", "out.net.xml", None)
        
    @patch('server.random_trips')
    def test_manage_demand_alias(self, mock_random_trips):
        # Test 'random_trips' alias
        result = manage_demand("random_trips", "net.net.xml", "trips.trips.xml", {"end_time": 100})
        mock_random_trips.assert_called_with("net.net.xml", "trips.trips.xml", 100, 1.0, None)
        
    @patch('server.tls_cycle_adaptation')
    def test_optimize_signals_alias(self, mock_cycle):
        # Test 'Websters' alias
        result = optimize_traffic_signals("Websters", "net.net.xml", "route.rou.xml", "out.xml")
        mock_cycle.assert_called_with("net.net.xml", "route.rou.xml", "out.xml")

    @patch('server.sim_gen_workflow')
    def test_workflow_alias(self, mock_sim_gen):
        # Test 'sim_gen_workflow' alias
        result = run_workflow("sim_gen_workflow", {"output_dir": "test"})
        mock_sim_gen.assert_called()

    @patch('server.get_vehicles')
    def test_query_state_alias(self, mock_get_vehicles):
        # Test 'vehicles' alias
        result = query_simulation_state("vehicles")
        mock_get_vehicles.assert_called()
        self.assertIn("Active vehicles", result)

if __name__ == '__main__':
    unittest.main()
