@echo off
REM SUMO-MCP Server Startup Script for Windows
REM 说明：
REM - SUMO 需已安装
REM - 推荐：在系统环境变量中设置 SUMO_HOME，并确保 %SUMO_HOME%\\bin 在 PATH 中
REM - 若未设置 SUMO_HOME，本脚本将仅依赖 PATH 中的 sumo/netgenerate 等二进制

REM IMPORTANT:
REM MCP stdio transport requires server stdout to contain ONLY JSON-RPC messages.
REM This script prints diagnostics to stderr only.

if defined SUMO_HOME (
  set "PATH=%SUMO_HOME%\bin;%PATH%"
) else (
  >&2 echo WARN: SUMO_HOME not set, relying on PATH.
)

where sumo >nul 2>nul
if errorlevel 1 (
  if defined SUMO_HOME (
    >&2 echo WARN: sumo not found in PATH after applying SUMO_HOME=%SUMO_HOME% ^(expected %SUMO_HOME%\bin^).
    >&2 echo WARN: Some tools will fail until SUMO is available in PATH.
  ) else (
    >&2 echo WARN: SUMO not found. Some tools will fail until SUMO is installed or SUMO_HOME is set.
  )
)

set "PYTHONUNBUFFERED=1"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
  set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" "%~dp0src\server.py"
