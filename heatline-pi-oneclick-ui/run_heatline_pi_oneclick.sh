#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
SCRIPT_PATH="$SCRIPT_DIR/heatline_pi_oneclick_gui.py"

if command -v pkexec >/dev/null 2>&1; then
  exec pkexec env DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" "$PYTHON_BIN" "$SCRIPT_PATH"
elif command -v sudo >/dev/null 2>&1; then
  exec sudo -E "$PYTHON_BIN" "$SCRIPT_PATH"
else
  exec "$PYTHON_BIN" "$SCRIPT_PATH"
fi
