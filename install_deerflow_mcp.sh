#!/usr/bin/env bash
set -euo pipefail

TARGET_HERMES_HOME="${1:-$HOME/.hermes}"
TARGET_SCRIPT_DIR="$TARGET_HERMES_HOME/scripts"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SOURCE_DIR="$SCRIPT_DIR/deerflow-mcp"

mkdir -p "$TARGET_SCRIPT_DIR"
cp "$SOURCE_DIR/deerflow_mcp.py" "$TARGET_SCRIPT_DIR/deerflow_mcp.py"
cp "$SOURCE_DIR/run_deerflow_mcp.sh" "$TARGET_SCRIPT_DIR/run_deerflow_mcp.sh"
chmod +x "$TARGET_SCRIPT_DIR/run_deerflow_mcp.sh"

echo "Installed DeerFlow MCP wrapper files into: $TARGET_SCRIPT_DIR"
echo "Next steps:"
echo "  1. Add the deerflow mcp_servers block to your active Hermes config.yaml"
echo "  2. Set DEERFLOW_BACKEND_DIR / DEER_FLOW_CONFIG_PATH / DEER_FLOW_EXTENSIONS_CONFIG_PATH under that config if needed"
echo "  3. Run: hermes mcp test deerflow"
