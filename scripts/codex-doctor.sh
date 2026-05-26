#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
STATUS=0

ok() { echo "ok:   $*"; }
warn() { echo "WARN: $*"; }
fail() { echo "FAIL: $*"; STATUS=1; }

check_link() {
    local src="$1"
    local dst="$2"
    if [[ ! -L "$dst" ]]; then
        fail "$dst is not a symlink"
        return
    fi
    local current
    current="$(readlink "$dst")"
    if [[ "$current" == "$src" ]]; then
        ok "$dst -> $src"
    else
        fail "$dst points to $current (expected $src)"
    fi
}

echo "== Codex CLI =="
if command -v codex >/dev/null 2>&1; then
    ok "codex: $(codex --version 2>/dev/null | head -1)"
else
    fail "codex command not found"
fi

echo ""
echo "== Rule links =="
check_link "$REPO_DIR/AGENTS.md" "$HOME/AGENTS.md"
check_link "$REPO_DIR/RULES.md" "$HOME/RULES.md"

echo ""
echo "== Codex profiles =="
for profile in "$REPO_DIR"/.codex/*.config.toml; do
    name="$(basename "$profile")"
    check_link "$profile" "$HOME/.codex/$name"
done

echo ""
echo "== Codex skills =="
for skill_dir in "$REPO_DIR"/skills/*; do
    [[ -d "$skill_dir" ]] || continue
    skill_name="$(basename "$skill_dir")"
    check_link "$skill_dir" "$HOME/.codex/skills/$skill_name"
done

echo ""
echo "== Dangling skill links =="
if find "$HOME/.codex/skills" -maxdepth 1 -type l ! -exec test -e {} \; -print 2>/dev/null | grep -q .; then
    find "$HOME/.codex/skills" -maxdepth 1 -type l ! -exec test -e {} \; -print
    STATUS=1
else
    ok "no dangling Codex skill symlinks"
fi

echo ""
echo "== TOML =="
if ! python3 - "$REPO_DIR" <<'PY'
import pathlib
import sys
import tomllib

repo = pathlib.Path(sys.argv[1])
status = 0
for path in sorted((repo / ".codex").glob("*.config.toml")) + sorted((repo / ".codex" / "mcp").glob("*.toml")):
    try:
        tomllib.load(path.open("rb"))
    except Exception as exc:
        print(f"FAIL: {path}: {exc}")
        status = 1
    else:
        print(f"ok:   {path}")
sys.exit(status)
PY
then
    STATUS=1
fi

echo ""
echo "== MCP environment names =="
missing_envs="$(
    python3 - "$REPO_DIR" <<'PY'
import os
import pathlib
import sys
import tomllib

repo = pathlib.Path(sys.argv[1])
env_names = set()
for path in sorted((repo / ".codex").glob("*.config.toml")) + sorted((repo / ".codex" / "mcp").glob("*.toml")):
    data = tomllib.load(path.open("rb"))
    for server in data.get("mcp_servers", {}).values():
        if isinstance(server, dict):
            env_names.update(server.get("env_vars", []))
            token_env = server.get("bearer_token_env_var")
            if token_env:
                env_names.add(token_env)
for name in sorted(env_names):
    if not os.environ.get(name):
        print(name)
PY
)"
if [[ -n "$missing_envs" ]]; then
    warn "environment variables referenced but unset:"
    echo "$missing_envs" | sed 's/^/  - /'
else
    ok "all referenced MCP environment variables are set, or none are referenced"
fi

exit "$STATUS"
