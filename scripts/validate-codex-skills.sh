#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

python3 - "$REPO_DIR" <<'PY'
import re
import sys
from pathlib import Path

repo_dir = Path(sys.argv[1])
allowed_keys = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "argument-hint",
    "disable-model-invocation",
}
status = 0


def unquote_scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value

for skill_dir in sorted((repo_dir / "skills").iterdir()):
    if not skill_dir.is_dir():
        continue

    skill_name = skill_dir.name
    skill_file = skill_dir / "SKILL.md"

    if not skill_file.exists():
        print(f"ERROR: {skill_name}: missing SKILL.md")
        status = 1
        continue

    content = skill_file.read_text()
    match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
    if not match:
        print(f"ERROR: {skill_name}: missing or invalid YAML frontmatter")
        status = 1
        continue

    frontmatter = {}
    raw_values = {}
    for line_no, line in enumerate(match.group(1).splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0].isspace():
            continue

        key, sep, value = line.partition(":")
        if not sep or not re.match(r"^[A-Za-z0-9_-]+$", key):
            print(f"ERROR: {skill_name}: invalid top-level frontmatter line {line_no}: {line}")
            status = 1
            continue
        raw_values[key] = value.strip()
        frontmatter[key] = unquote_scalar(value)

    unexpected = sorted(set(frontmatter) - allowed_keys)
    if unexpected:
        keys = ", ".join(unexpected)
        allowed = ", ".join(sorted(allowed_keys))
        print(f"ERROR: {skill_name}: unexpected frontmatter key(s): {keys}; allowed: {allowed}")
        status = 1

    declared_name = frontmatter.get("name")
    if not declared_name:
        print(f"ERROR: {skill_name}: missing frontmatter name")
        status = 1
    elif declared_name != skill_name:
        print(f"WARN:  {skill_name}: frontmatter name is '{declared_name}'")

    description = frontmatter.get("description")
    if not isinstance(description, str) or not description.strip():
        print(f"ERROR: {skill_name}: missing or invalid frontmatter description")
        status = 1
    elif "<" in description or ">" in description:
        print(f"ERROR: {skill_name}: description must not contain angle brackets")
        status = 1
    elif len(description.strip()) > 1024:
        print(f"ERROR: {skill_name}: description is too long ({len(description.strip())} characters)")
        status = 1

    argument_hint = raw_values.get("argument-hint")
    if argument_hint and argument_hint[0] not in {"'", '"'}:
        print(f"ERROR: {skill_name}: argument-hint must be quoted for YAML compatibility")
        status = 1

    if "argument-hint" in frontmatter or "disable-model-invocation" in frontmatter:
        print(f"INFO:  {skill_name}: contains Claude metadata tolerated by Codex")

sys.exit(status)
PY
