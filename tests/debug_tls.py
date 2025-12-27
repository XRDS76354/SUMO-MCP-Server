import os
import subprocess

from mcp_tools.signal import tls_cycle_adaptation

def debug_tls():
    base_dir = os.path.dirname(__file__)
    fixtures_dir = os.path.join(base_dir, "fixtures", "simple_sim")
    output_dir = os.path.join(base_dir, "output_debug_tls")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    net_file = os.path.join(fixtures_dir, "hello.net.xml")
    route_file = os.path.join(fixtures_dir, "hello.rou.xml")
    output_net = os.path.join(output_dir, "optimized.net.xml")
    
    print(f"Running tlsCycleAdaptation on {net_file}...")
    res = tls_cycle_adaptation(net_file, route_file, output_net)
    print("Result:", res)
    
    if os.path.exists(output_net):
        print(f"Output file size: {os.path.getsize(output_net)} bytes")
        # Try to run sumo on it
        sumo_cmd = ["sumo", "-n", output_net, "-r", route_file, "--no-step-log", "true", "-e", "50"]
        print("Running verification SUMO...")
        try:
            subprocess.run(sumo_cmd, check=True)
            print("Verification successful")
        except subprocess.CalledProcessError as e:
            print("Verification failed:", e)
    else:
        print("Output file not created!")

if __name__ == "__main__":
    debug_tls()
