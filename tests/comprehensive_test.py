import subprocess
import json
import time
import threading
import traceback
import os
import sys
import shutil
import concurrent.futures
from datetime import datetime

class MCPTestRunner:
    def __init__(self, python_path, server_path):
        self.python_path = python_path
        self.server_path = server_path
        self.process = None
        self.lock = threading.Lock()
        self.request_id = 0
        self.results = {
            "functional": [],
            "performance": [],
            "integration": [],
            "exception": []
        }
        self.output_dir = os.path.join(os.path.dirname(__file__), "test_outputs")
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)
        os.makedirs(self.output_dir)

    def start_server(self):
        print(f"[{datetime.now()}] Starting server...")
        env = os.environ.copy()
        # Ensure PYTHONPATH includes src
        src_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
        env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
        
        self.process = subprocess.Popen(
            [self.python_path, self.server_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=0,
            env=env
        )
        
        # Initial handshake
        self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test-runner", "version": "1.0"}
        })
        resp = self.read_response()
        if "result" not in resp:
            raise Exception("Server initialization failed")
            
        self.send_notification("notifications/initialized")
        print(f"[{datetime.now()}] Server initialized.")

    def stop_server(self):
        if self.process:
            print(f"[{datetime.now()}] Stopping server...")
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
            print(f"[{datetime.now()}] Server stopped.")

    def send_request(self, method, params=None):
        with self.lock:
            self.request_id += 1
            req_id = self.request_id
            
        req = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method
        }
        if params is not None:
            req["params"] = params
            
        json_req = json.dumps(req)
        # print(f"Sending: {json_req}")
        self.process.stdin.write(json_req + "\n")
        self.process.stdin.flush()
        return req_id

    def send_notification(self, method, params=None):
        req = {
            "jsonrpc": "2.0",
            "method": method
        }
        if params is not None:
            req["params"] = params
        self.process.stdin.write(json.dumps(req) + "\n")
        self.process.stdin.flush()

    def read_response(self):
        line = self.process.stdout.readline()
        if not line:
            return None
        return json.loads(line)

    def run_tool(self, tool_name, args):
        start_time = time.time()
        req_id = self.send_request("tools/call", {
            "name": tool_name,
            "arguments": args
        })
        resp = self.read_response()
        duration = time.time() - start_time
        
        success = False
        error_msg = None
        result_content = None
        
        if resp and resp.get("id") == req_id:
            if "error" in resp:
                error_msg = resp["error"]["message"]
            elif "result" in resp:
                success = True
                result_content = resp["result"]["content"][0]["text"]
        else:
            error_msg = "Response ID mismatch or no response"
            
        return {
            "success": success,
            "duration": duration,
            "error": error_msg,
            "content": result_content
        }

    def record_result(self, category, name, passed, details, metrics=None):
        self.results[category].append({
            "name": name,
            "passed": passed,
            "details": details,
            "metrics": metrics or {},
            "timestamp": str(datetime.now())
        })
        status = "PASS" if passed else "FAIL"
        print(f"[{category.upper()}] {name}: {status} ({details})")

    # --- Test Cases ---

    def test_functional(self):
        print("\n--- Starting Functional Tests ---")
        
        # 1. List Tools
        req_id = self.send_request("tools/list")
        resp = self.read_response()
        if resp and "result" in resp and "tools" in resp["result"]:
            tool_names = [t["name"] for t in resp["result"]["tools"]]
            passed = "run_workflow" in tool_names
            self.record_result("functional", "List Tools", passed, f"Found {len(tool_names)} tools")
        else:
            self.record_result("functional", "List Tools", False, "Failed to list tools")

        # 2. Get SUMO Info
        res = self.run_tool("get_sumo_info", {})
        self.record_result("functional", "Get SUMO Info", res["success"], 
                           f"Duration: {res['duration']:.2f}s", {"duration": res["duration"]})

        # 3. Sim Gen Workflow (E2E)
        workflow_out = os.path.join(self.output_dir, "sim_gen_test")
        res = self.run_tool("run_workflow", {
            "workflow_name": "sim_gen_eval",
            "params": {
                "output_dir": workflow_out,
                "grid_number": 3,
                "steps": 50
            }
        })
        passed = res["success"] and "Workflow Completed Successfully" in (res["content"] or "")
        self.record_result("functional", "Sim Gen Workflow", passed, 
                           f"Duration: {res['duration']:.2f}s", {"duration": res["duration"]})

    def test_performance(self):
        print("\n--- Starting Performance Tests ---")
        
        # 1. Concurrency / Response Time Check
        # Since server is synchronous, this tests queueing and stability, not true parallelism
        count = 10
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = []
            for i in range(count):
                futures.append(executor.submit(self.run_tool, "get_sumo_info", {}))
            
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
        total_time = time.time() - start_time
        success_count = sum(1 for r in results if r["success"])
        avg_duration = sum(r["duration"] for r in results) / count
        
        self.record_result("performance", "Concurrent Requests", success_count == count,
                           f"Processed {count} requests in {total_time:.2f}s (Avg: {avg_duration:.2f}s/req)",
                           {"total_time": total_time, "avg_duration": avg_duration})

        # 2. Stress Test (Medium Simulation)
        stress_out = os.path.join(self.output_dir, "stress_test")
        res = self.run_tool("run_workflow", {
            "workflow_name": "sim_gen_eval",
            "params": {
                "output_dir": stress_out,
                "grid_number": 5, # Larger grid
                "steps": 200      # More steps
            }
        })
        self.record_result("performance", "Stress Test (5x5 Grid)", res["success"],
                           f"Duration: {res['duration']:.2f}s", {"duration": res["duration"]})

    def test_integration(self):
        print("\n--- Starting Integration Tests ---")
        
        # Verify file artifacts from previous functional test
        workflow_out = os.path.join(self.output_dir, "sim_gen_test")
        expected_files = ["grid.net.xml", "trips.xml", "routes.xml", "sim.sumocfg", "fcd.xml"]
        missing = [f for f in expected_files if not os.path.exists(os.path.join(workflow_out, f))]
        
        self.record_result("integration", "Artifact Verification", len(missing) == 0,
                           f"Missing files: {missing}" if missing else "All artifacts created")

    def test_exception(self):
        print("\n--- Starting Exception Tests ---")
        
        # 1. Unknown Tool
        res = self.run_tool("non_existent_tool", {})
        passed = not res["success"] and "not found" in (res["error"] or "")
        self.record_result("exception", "Unknown Tool", passed, f"Error: {res['error']}")
        
        # 2. Invalid Arguments (Negative steps)
        # Note: Depending on implementation, SUMO might handle this or python script might fail.
        # Our tools typically pass args to command line.
        invalid_out = os.path.join(self.output_dir, "invalid_test")
        res = self.run_tool("run_workflow", {
            "workflow_name": "sim_gen_eval",
            "params": {
                "output_dir": invalid_out,
                "grid_number": -1, 
                "steps": 10
            }
        })
        # netgenerate might fail with negative grid number
        passed = "Failed" in (res["content"] or "") or (res["error"] is not None)
        self.record_result("exception", "Invalid Arguments", passed, 
                           f"Handled gracefully. Result: {res['content'] or res['error']}")

    def generate_report(self):
        report_path = os.path.join(os.path.dirname(__file__), "..", "TEST_REPORT_V2.md")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# SUMO-MCP Comprehensive Test Report\n\n")
            f.write(f"**Date**: {datetime.now()}\n\n")
            
            f.write("## Summary\n")
            total = sum(len(v) for v in self.results.values())
            passed = sum(sum(1 for r in v if r["passed"]) for v in self.results.values())
            f.write(f"- **Total Tests**: {total}\n")
            f.write(f"- **Passed**: {passed}\n")
            f.write(f"- **Failed**: {total - passed}\n\n")
            
            for category, tests in self.results.items():
                f.write(f"## {category.capitalize()} Tests\n")
                f.write("| Test Name | Status | Details | Metrics |\n")
                f.write("|-----------|--------|---------|---------|\n")
                for t in tests:
                    status_icon = "✅" if t["passed"] else "❌"
                    metrics_str = ", ".join(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k,v in t["metrics"].items())
                    f.write(f"| {t['name']} | {status_icon} | {t['details']} | {metrics_str} |\n")
                f.write("\n")
        
        print(f"\nReport generated at: {report_path}")

if __name__ == "__main__":
    # Path configuration
    base_dir = os.path.dirname(__file__)
    server_script = os.path.join(base_dir, "..", "src", "server.py")
    
    # Use current python executable (assuming it is the conda one)
    python_exe = sys.executable
    
    runner = MCPTestRunner(python_exe, server_script)
    try:
        runner.start_server()
        runner.test_functional()
        runner.test_performance()
        runner.test_integration()
        runner.test_exception()
    except Exception as e:
        print(f"Test Execution Failed: {e}")
        traceback.print_exc()
    finally:
        runner.stop_server()
        runner.generate_report()
