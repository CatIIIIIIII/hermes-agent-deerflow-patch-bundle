#!/usr/bin/env bash
set -euo pipefail

TARGET="${1:-$HOME/.hermes/hermes-agent}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PATCH_FILE="$SCRIPT_DIR/patches/hermes-v0.8.0-custom-ua.patch"

if [[ ! -f "$PATCH_FILE" ]]; then
  echo "Patch file not found: $PATCH_FILE" >&2
  exit 1
fi

if [[ ! -d "$TARGET" ]]; then
  echo "Target directory not found: $TARGET" >&2
  exit 1
fi

if [[ ! -d "$TARGET/.git" ]]; then
  echo "Target does not look like a git checkout: $TARGET" >&2
  exit 1
fi

git -C "$TARGET" apply --check "$PATCH_FILE"
git -C "$TARGET" apply "$PATCH_FILE"

echo "Applied patch to $TARGET"
