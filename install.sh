#!/usr/bin/env bash
# Install / refresh symlinks for agent-rules: CLAUDE.md, RULES.md, AGENTS.md, skills/*
#
# Idempotent — re-running on an already-installed machine is safe.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

ln_if_not() {
    local src="$1"
    local dst="$2"

    if [[ -L "$dst" ]]; then
        local current="$(readlink "$dst")"
        if [[ "$current" == "$src" ]]; then
            echo "ok:   $dst"
            return
        fi
        echo "WARN: $dst is a symlink to $current (expected $src), skipping"
        return
    fi

    if [[ -e "$dst" ]]; then
        echo "WARN: $dst exists and is not a symlink, skipping"
        return
    fi

    mkdir -p "$(dirname "$dst")"
    ln -s "$src" "$dst"
    echo "link: $dst -> $src"
}

echo "== Top-level rules =="
ln_if_not "$REPO_DIR/CLAUDE.md" "$HOME/CLAUDE.md"
ln_if_not "$REPO_DIR/RULES.md"  "$HOME/RULES.md"
ln_if_not "$REPO_DIR/AGENTS.md" "$HOME/AGENTS.md"

echo ""
echo "== Skills =="
mkdir -p "$HOME/.claude/skills"
for skill_dir in "$REPO_DIR"/skills/*/; do
    skill_name="$(basename "$skill_dir")"
    ln_if_not "$REPO_DIR/skills/$skill_name" "$HOME/.claude/skills/$skill_name"
done

echo ""
echo "Install complete."
