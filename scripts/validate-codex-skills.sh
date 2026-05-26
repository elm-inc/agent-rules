#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATUS=0

for skill_dir in "$REPO_DIR"/skills/*; do
    [[ -d "$skill_dir" ]] || continue
    skill_name="$(basename "$skill_dir")"
    skill_file="$skill_dir/SKILL.md"

    if [[ ! -f "$skill_file" ]]; then
        echo "ERROR: $skill_name: missing SKILL.md"
        STATUS=1
        continue
    fi

    if [[ "$(sed -n '1p' "$skill_file")" != "---" ]]; then
        echo "ERROR: $skill_name: missing YAML frontmatter"
        STATUS=1
        continue
    fi

    declared_name="$(sed -n '/^---$/,/^---$/p' "$skill_file" | sed -n 's/^name:[[:space:]]*//p' | head -1)"
    description="$(sed -n '/^---$/,/^---$/p' "$skill_file" | sed -n 's/^description:[[:space:]]*//p' | head -1)"

    if [[ -z "$declared_name" ]]; then
        echo "ERROR: $skill_name: missing frontmatter name"
        STATUS=1
    elif [[ "$declared_name" != "$skill_name" ]]; then
        echo "WARN:  $skill_name: frontmatter name is '$declared_name'"
    fi

    if [[ -z "$description" ]]; then
        echo "ERROR: $skill_name: missing frontmatter description"
        STATUS=1
    fi

    if grep -qE '^(allowed-tools|argument-hint|disable-model-invocation):' "$skill_file"; then
        echo "INFO:  $skill_name: contains Claude-style metadata; Codex should ignore unknown frontmatter"
    fi
done

exit "$STATUS"
