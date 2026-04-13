#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-$HOME/.hermes/hermes-agent}"
PATCH_NAME="${2:-ua}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./apply.sh [HERMES_REPO] [PATCH]

Examples:
  ./apply.sh
  ./apply.sh ~/.hermes/hermes-agent ua
  ./apply.sh ~/.hermes/hermes-agent deerflow-profile
  ./apply.sh ~/.hermes/hermes-agent all

Available patches:
  ua                Hermes custom endpoint User-Agent fix
  deerflow-profile  Merge default-profile mcp_servers into new Hermes profiles
  all               Apply both patches in order
EOF
}

patch_path_for() {
  case "$1" in
    ua)
      printf '%s\n' "$SCRIPT_DIR/patches/hermes-v0.8.0-custom-ua.patch"
      ;;
    deerflow-profile)
      printf '%s\n' "$SCRIPT_DIR/patches/hermes-v0.8.0-deerflow-profile-mcp.patch"
      ;;
    *)
      return 1
      ;;
  esac
}

apply_one() {
  local patch_name="$1"
  local patch_file
  patch_file="$(patch_path_for "$patch_name")"

  if [[ ! -f "$patch_file" ]]; then
    echo "Patch file not found: $patch_file" >&2
    exit 1
  fi

  git -C "$TARGET" apply --check "$patch_file"
  git -C "$TARGET" apply "$patch_file"
  echo "Applied $patch_name patch to $TARGET"
}

if [[ "$PATCH_NAME" == "-h" || "$PATCH_NAME" == "--help" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -d "$TARGET" ]]; then
  echo "Target directory not found: $TARGET" >&2
  exit 1
fi

if [[ ! -d "$TARGET/.git" ]]; then
  echo "Target does not look like a git checkout: $TARGET" >&2
  exit 1
fi

case "$PATCH_NAME" in
  ua|deerflow-profile)
    apply_one "$PATCH_NAME"
    ;;
  all)
    apply_one ua
    apply_one deerflow-profile
    ;;
  list)
    printf '%s\n' 'ua' 'deerflow-profile' 'all'
    ;;
  *)
    echo "Unknown patch: $PATCH_NAME" >&2
    usage >&2
    exit 1
    ;;
esac
