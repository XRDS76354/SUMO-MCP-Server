---
name: sumo-network-build
description: Build, convert, and inspect SUMO networks using SUMO-MCP v0.2 tools.
---

# SUMO Network Build

## Use When
- The user needs a grid/spider/random network, OSM import, or ezdesignX conversion.
- The user asks why a network cannot support simulation, routing, signals, or RL.

## Preferred Tools
- `manage_network(action="generate")` for abstract networks.
- `manage_network(action="download_osm")` and `manage_network(action="convert")` for OSM.
- `convert_ezdesignx_network` or `manage_network(action="convert_ezdesignx")` for ezdesignX v1 JSON/JSONC.
- `list_sumo_commands` and `run_sumo_binary(name="netconvert"|"netgenerate")` for advanced native flags.

## Output Expectations
- Return `.net.xml`, optional `.sumocfg`, conversion reports, and any warnings.
- For RL or signal workflows, explicitly confirm traffic lights and green phases when possible.

## Recovery
- If SUMO is missing, use `sumo://diagnostics` and return `SUMO_NOT_FOUND` guidance.
- If OSM conversion needs extra flags, pass them through `params.options` or `args: list[str]`.
