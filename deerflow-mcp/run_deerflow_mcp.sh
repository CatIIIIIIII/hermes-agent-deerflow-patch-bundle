#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER_PATH="${DEERFLOW_MCP_WRAPPER:-$SCRIPT_DIR/deerflow_mcp.py}"

if [[ -n "${DEERFLOW_BACKEND_DIR:-}" ]]; then
  BACKEND_DIR="$DEERFLOW_BACKEND_DIR"
else
  for candidate in "$HOME/Documents/deer-flow/backend" "$HOME/deer-flow/backend"; do
    if [[ -d "$candidate" ]]; then
      BACKEND_DIR="$candidate"
      break
    fi
  done
fi

if [[ -z "${BACKEND_DIR:-}" ]]; then
  echo "Could not find DeerFlow backend directory." >&2
  echo "Set DEERFLOW_BACKEND_DIR to your deer-flow/backend path." >&2
  exit 1
fi

if [[ ! -f "$WRAPPER_PATH" ]]; then
  echo "Wrapper script not found: $WRAPPER_PATH" >&2
  exit 1
fi

cd "$BACKEND_DIR"
exec uv run --with mcp python "$WRAPPER_PATH" "$@"
