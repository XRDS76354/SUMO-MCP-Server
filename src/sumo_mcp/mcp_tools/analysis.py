import sumolib
import pandas as pd
import os

def analyze_fcd(fcd_file: str) -> str:
    """
    Analyze FCD (Floating Car Data) output XML to compute basic statistics.
    """
    if not os.path.exists(fcd_file):
        return f"Error: File {fcd_file} not found."

    try:
        speeds = []
        vehicle_counts = 0
        
        # sumolib.output.parse returns a generator
        for timestep in sumolib.output.parse(fcd_file, 'timestep'):
            if timestep.vehicle:
                for vehicle in timestep.vehicle:
                    speeds.append(float(vehicle.speed))
                    vehicle_counts += 1
        
        if not speeds:
            return "No vehicle data found in FCD output."
            
        avg_speed = sum(speeds) / len(speeds)
        
        df = pd.DataFrame({'speed': speeds})
        desc = df.describe().to_string()
        
        return f"Analysis Result:\nTotal Data Points: {vehicle_counts}\nAverage Speed: {avg_speed:.2f} m/s\n\nStatistics:\n{desc}"
    except Exception as e:
        return f"Analysis error: {str(e)}"
