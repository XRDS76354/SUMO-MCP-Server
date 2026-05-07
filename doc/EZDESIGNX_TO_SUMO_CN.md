# ezdesignX 转 SUMO

SUMO-MCP 现在内置了一个自包含的 ezdesignX 转换器，可以把 ezdesignX 
`JSON` 或 `JSONC` 路口配置转换成 SUMO 路网。

## 输入与输出

- 输入：一个 ezdesignX `JSON` 或 `JSONC` 文件
- 输出目录中的产物：
  `*.nod.xml`、`*.edg.xml`、`*.con.xml`、`*.net.xml`、`*.add.xml`、
  `*.sumocfg`、`*.conversion-report.json`

## MCP 调用入口

- 专用工具：
  `convert_ezdesignx_network(input_json, output_dir, validation="topology", ...)`
- 路网管理兼容入口：
  `manage_network(action="convert_ezdesignx", output_file=<output_dir>, params={"input_json": ...})`

这两个入口复用同一套底层实现，返回包含输出路径、`schemaKind`、
`adapterMode` 与校验状态的文本摘要。

## 校验级别

- `basic`：检查关键产物是否生成，以及 `netconvert` 是否成功
- `topology`：在 `basic` 基础上增加 edge、lane 和 headless SUMO 加载检查
- `strict`：在 `topology` 基础上增加角度、长度和车道宽度误差指标

## 当前适配行为

- `schemaKind` 固定报告为 `ezdesignx.config.v1`
- `adapterMode` 固定报告为 `legacy-core-minimal-v1`
- `line` 段根据 `start/end` 反推旧式长度
- `cubicBezier` 段当前按弦长降维为直线
- `transition` 段在缺失长度时可按邻近显式几何推断
- lane `centerline.markings` 会降维成旧式转向箭头模型
- `crosswalk` 与 `laneStartCap` 当前不会写入输出附加几何
- `stopLine`、`median`、`greenBelt` 会以 `ezdesignx.*` 类型写入附加图层

## 迁移说明

运行时代码现在位于 `src/mcp_tools/ezdesignx.py`。
