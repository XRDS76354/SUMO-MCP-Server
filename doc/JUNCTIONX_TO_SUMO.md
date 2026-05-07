# JunctionX to SUMO

SUMO-MCP includes a self-contained JunctionX converter that turns a JunctionX
JSON intersection description into SUMO.

## Inputs and outputs

- Input: one JunctionX JSON file
- Output directory artifacts:
  `*.nod.xml`, `*.edg.xml`, `*.con.xml`, `*.net.xml`, `*.add.xml`,
  `*.sumocfg`, `*.conversion-report.json`

## MCP entry points

- Dedicated tool:
  `convert_junctionx_network(input_json, output_dir, validation="topology", ...)`
- Compatibility path:
  `manage_network(action="convert_junctionx", output_file=<output_dir>, params={"input_json": ...})`

Both entry points share the same conversion backend and return a text summary
with the output paths and validation status.

## Validation levels

- `basic`: verify expected files exist and `netconvert` returns success
- `topology`: add edge, lane, and headless SUMO load checks
- `strict`: add angle, length, and lane-width error metrics

## Current mapping status

- `transition` segments keep their length and infer lane continuity when
  JunctionX omits explicit lane geometry
- compatible `uniform/transition/uniform` chains can be emitted as one SUMO
  edge to avoid internal split artifacts
- `greenBelt` stays out of the drivable network and is emitted as additional
  polygons
- `crosswalks` are currently recorded in the conversion report and filtered out
  of `add.xml` to avoid placing unreliable geometry

