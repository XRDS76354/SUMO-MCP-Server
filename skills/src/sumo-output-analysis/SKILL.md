---
name: sumo-output-analysis
description: Analyze SUMO output files with structured v0.2 analysis tools.
---

# SUMO Output Analysis

## Use When
- The user has summary, tripinfo, FCD, queue, emission, or CSV output files.

## Preferred Tools
- `analyze_sumo_output` for streaming XML analysis, including gzip files.
- `run_analysis` for legacy FCD CSV summaries.
- `run_sumo_tool` for SUMO plotting or XML conversion scripts when the user asks for external artifacts.

## Output Expectations
- Report metrics, counts, truncation, and artifact paths.
- For large XML, prefer summaries and sampled metrics over dumping raw rows into chat.
