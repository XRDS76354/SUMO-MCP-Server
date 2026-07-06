#!/bin/bash
# SUMO-MCP Server Startup Script for Linux/macOS/MSYS
# 说明：
# - SUMO 需已安装
# - 推荐：在系统环境变量中设置 SUMO_HOME，并确保 $SUMO_HOME/bin 在 PATH 中
# - 若未设置 SUMO_HOME，本脚本将仅依赖 PATH 中的 `sumo`/`netgenerate` 等二进制

# IMPORTANT:
# MCP stdio transport requires server stdout to contain ONLY JSON-RPC messages.
# This script prints diagnostics to stderr only.

if [ -n "${SUMO_HOME:-}" ]; then
  export PATH="$SUMO_HOME/bin:$PATH"
fi

if ! command -v sumo &> /dev/null; then
  if [ -z "${SUMO_HOME:-}" ]; then
    echo "WARN: SUMO not found. Some tools will fail until SUMO is installed or SUMO_HOME is set." >&2
  else
    echo "WARN: \`sumo\` not found in PATH after applying SUMO_HOME=$SUMO_HOME (expected $SUMO_HOME/bin)." >&2
    echo "WARN: Some tools will fail until SUMO is available in PATH." >&2
  fi
fi

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer the repo-local virtualenv if it exists.
PYTHON_EXE="python"
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PYTHON_EXE="$SCRIPT_DIR/.venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/Scripts/python.exe" ]; then
  PYTHON_EXE="$SCRIPT_DIR/.venv/Scripts/python.exe"
elif [ -x "$SCRIPT_DIR/.venv/Scripts/python" ]; then
  PYTHON_EXE="$SCRIPT_DIR/.venv/Scripts/python"
fi

export PYTHONUNBUFFERED=1

# 启动 MCP 服务器
exec "$PYTHON_EXE" "$SCRIPT_DIR/src/server.py"
