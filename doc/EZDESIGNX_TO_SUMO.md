# ezdesignX to SUMO

SUMO-MCP includes a self-contained ezdesignX converter that turns ezdesignX 
JSON or JSONC intersection descriptions into SUMO networks.

## Inputs and outputs

- Input: one ezdesignX `JSON` or `JSONC` file
- Output directory artifacts:
  `*.nod.xml`, `*.edg.xml`, `*.con.xml`, `*.net.xml`, `*.add.xml`,
  `*.sumocfg`, `*.conversion-report.json`

## MCP entry points

- Dedicated tool:
  `convert_ezdesignx_network(input_json, output_dir, validation="topology", ...)`
- Compatibility path inside network management:
  `manage_network(action="convert_ezdesignx", output_file=<output_dir>, params={"input_json": ...})`

Both entry points share the same backend and return a text summary with output
paths, `schemaKind`, `adapterMode`, and validation status.

## Validation levels

- `basic`: verify expected files exist and `netconvert` returns success
- `topology`: add edge, lane, and headless SUMO load checks
- `strict`: add angle, length, and lane-width error metrics

## Current adapter behavior

- `schemaKind` is reported as `ezdesignx.config.v1`
- `adapterMode` is reported as `legacy-core-minimal-v1`
- `line` segments infer legacy lengths from `start/end`
- `cubicBezier` segments are reduced to straight-line chord lengths
- `transition` lengths may be inferred from neighboring explicit geometry
- lane `centerline.markings` are reduced to legacy turn-arrow semantics
- `crosswalk` and `laneStartCap` are currently filtered out of the generated
  SUMO add-on geometry
- `stopLine`, `median`, and `greenBelt` outputs are emitted as `ezdesignx.*`
  add-on shapes

## Migration note

The runtime implementation now lives in `src/mcp_tools/ezdesignx.py`. 
