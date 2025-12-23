# SUMO-MCP Server Startup Script for PowerShell
# 说明：
# - SUMO 需已安装
# - 推荐：在系统环境变量中设置 SUMO_HOME，并确保 $env:SUMO_HOME\bin 在 PATH 中
# - 若未设置 SUMO_HOME，本脚本将仅依赖 PATH 中的 sumo/netgenerate 等二进制

# IMPORTANT:
# MCP stdio transport requires server stdout to contain ONLY JSON-RPC messages.
# This script prints diagnostics to stderr only.

if ($env:SUMO_HOME) {
    $env:PATH = "$env:SUMO_HOME\bin;$env:PATH"
} else {
    [Console]::Error.WriteLine("WARN: SUMO_HOME not set, relying on PATH.")
}

$sumoCmd = Get-Command sumo -ErrorAction SilentlyContinue
if (-not $sumoCmd) {
    if (-not $env:SUMO_HOME) {
        [Console]::Error.WriteLine("WARN: SUMO not found. Some tools will fail until SUMO is installed or SUMO_HOME is set.")
    } else {
        [Console]::Error.WriteLine("WARN: sumo not found in PATH after applying SUMO_HOME=$env:SUMO_HOME (expected $env:SUMO_HOME\\bin).")
        [Console]::Error.WriteLine("WARN: Some tools will fail until SUMO is available in PATH.")
    }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Prefer the repo-local virtualenv if it exists.
$PythonExe = Join-Path $ScriptDir ".venv\\Scripts\\python.exe"
if (-not (Test-Path $PythonExe)) {
    $PythonExe = "python"
}

$env:PYTHONUNBUFFERED = "1"

& $PythonExe (Join-Path $ScriptDir "src\\server.py")
