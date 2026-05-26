#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="${1:-agent-rules}"
PROFILE_FILE="$REPO_DIR/.codex/$PROFILE.config.toml"

if [[ ! -f "$PROFILE_FILE" ]]; then
    echo "ERROR: profile not found: $PROFILE_FILE" >&2
    exit 1
fi

cat "$PROFILE_FILE"

if compgen -G "$REPO_DIR/.codex/mcp/*.toml" >/dev/null; then
    printf '\n# MCP fragments\n'
    for fragment in "$REPO_DIR"/.codex/mcp/*.toml; do
        printf '\n# Source: .codex/mcp/%s\n' "$(basename "$fragment")"
        cat "$fragment"
    done
fi
