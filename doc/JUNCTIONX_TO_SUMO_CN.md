# JunctionX 转 SUMO

SUMO-MCP 现在内置了一个自包含的 JunctionX 转换器，可以把 JunctionX
JSON 路口配置转换成 SUMO 产物。

## 输入与输出

- 输入：一个 JunctionX JSON 文件（从junctionX中编辑好的路网导出配置文件）
- 输出目录中的产物：
  `*.nod.xml`、`*.edg.xml`、`*.con.xml`、`*.net.xml`、`*.add.xml`、
  `*.sumocfg`、`*.conversion-report.json`

## MCP 调用入口

- 专用工具：
  `convert_junctionx_network(input_json, output_dir, validation="topology", ...)`
- 兼容入口：
  `manage_network(action="convert_junctionx", output_file=<output_dir>, params={"input_json": ...})`

这两个入口都复用同一套底层实现，返回包含输出路径与校验状态的文本摘要。

## 校验级别

- `basic`：检查关键产物是否生成，以及 `netconvert` 是否成功
- `topology`：在 `basic` 基础上增加 edge、lane 和 headless SUMO 加载检查
- `strict`：在 `topology` 基础上增加角度、长度和车道宽度误差指标

## 当前映射状态

- `transition` 段优先保留长度，并在缺少显式车道几何时推断车道连续性
- 兼容的 `uniform/transition/uniform` 链可能合并为单个 SUMO edge，减少内部切分痕迹
- `greenBelt` 不进入可通行路网，而是写入附加 polygon
- `crosswalks` 当前只记录到转换报告中，不写入 `add.xml`，避免输出不可靠的几何

