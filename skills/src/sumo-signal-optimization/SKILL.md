---
name: sumo-signal-optimization
description: Optimize and compare traffic signal plans with SUMO-MCP v0.2 workflows and tools.
---

# SUMO Signal Optimization

## Use When
- The user wants Webster cycle adaptation, green-wave coordination, or baseline-vs-optimized comparison.

## Preferred Tools
- `run_workflow(workflow_name="signal_opt")` for full comparison.
- `optimize_traffic_signals(method="cycle_adaptation")` for Webster-style additional files.
- `optimize_traffic_signals(method="coordination")` for offsets/green-wave coordination.
- `analyze_sumo_output` for summary/tripinfo/queue metrics after simulation.

## Guardrails
- Signal optimization outputs are SUMO additional files; they are not replacement network files.
- Compare against a baseline before claiming improvement.
- Report waiting time, stopped vehicles, delay, throughput, and artifact paths when available.
