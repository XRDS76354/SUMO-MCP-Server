import os
import shutil
import pytest
from unittest.mock import MagicMock, patch

from mcp_tools.rl import list_rl_scenarios, run_rl_training
from workflows.rl_train import rl_train_workflow

class TestRLTools:
    def test_list_scenarios(self):
        scenarios = list_rl_scenarios()
        assert isinstance(scenarios, list)
        # Assuming sumo-rl is installed and has nets, we should see at least one
        # But in test environment it might be mocked or empty if not fully installed
        # So we just check type
        
    @patch("mcp_tools.rl.SumoEnvironment")
    def test_run_training(self, mock_env, tmp_path):
        # Mock environment
        env_instance = MagicMock()
        mock_env.return_value = env_instance
        env_instance.ts_ids = ["t1"]
        # Gym reset returns (obs, info)
        # obs is a dict {ts_id: state}
        env_instance.reset.return_value = ({"t1": [0,0]}, {})
        # Gym step returns (obs, rewards, term, trunc, info)
        # rewards is a dict {ts_id: reward}
        # In multi-agent env, step returns dicts for all agents
        # done/term/trunc are dicts {agent_id: bool} or a global bool depending on env
        # sumo-rl (single_agent=False) returns a 4-tuple: (obs_dict, rewards_dict, dones_dict, info)
        env_instance.step.return_value = ({"t1": [0,0]}, {"t1": 1}, {"t1": True, "__all__": True}, {})
        env_instance.encode.return_value = "state"
        
        # Mock QLAgent
        # sumo-rl 在未设置 SUMO_HOME 时会在导入期抛 ImportError；这里仅为测试打桩，给一个假值即可。
        with patch.dict(os.environ, {"SUMO_HOME": "/tmp/sumo"}, clear=False):
            with patch("sumo_rl.agents.QLAgent") as mock_agent:
                agent_instance = MagicMock()
                mock_agent.return_value = agent_instance

                net_file = tmp_path / "dummy.net.xml"
                route_file = tmp_path / "dummy.rou.xml"
                net_file.write_text("<net/>", encoding="utf-8")
                route_file.write_text("<routes/>", encoding="utf-8")
                
                res = run_rl_training(
                    net_file=str(net_file),
                    route_file=str(route_file),
                    out_dir=str(tmp_path / "test_out"),
                    episodes=1,
                    steps_per_episode=10
                )
                
                assert "Episode 1/1" in res
                assert "Total Reward" in res

class TestRLWorkflow:
    @patch.dict(os.environ, {"SUMO_HOME": "/tmp/sumo"}, clear=False)
    @patch("workflows.rl_train.run_rl_training") # Patch where it is imported!
    @patch("mcp_tools.rl.list_rl_scenarios")
    @patch("os.path.exists")
    @patch("os.listdir")
    @patch("sumo_rl.__file__", new="/mock/path/sumo_rl/__init__.py")
    def test_workflow(self, mock_listdir, mock_exists, mock_list_scenarios, mock_run_train):
        # Mock file system
        # os.path.exists is called for scenario_path, net_file, route_file
        # We need to be careful with return values if multiple calls
        mock_exists.return_value = True
        mock_listdir.return_value = ["map.net.xml", "map.rou.xml"]
        
        mock_run_train.return_value = "Training Complete"
        
        res = rl_train_workflow("2way-single-intersection", "out_dir")
        
        # In the failure case, it seemed it tried to actually run because mock wasn't effective?
        # Or maybe import side effects.
        # The previous failure "Training failed: Connection closed by SUMO" suggests run_rl_training WAS called 
        # but NOT mocked properly or the workflow implementation didn't use the mock.
        # rl_train_workflow imports run_rl_training from mcp_tools.rl
        # We patched "mcp_tools.rl.run_rl_training" which should work if imported as "from mcp_tools.rl import run_rl_training"
        
        assert res == "Training Complete"
        mock_run_train.assert_called_once()
