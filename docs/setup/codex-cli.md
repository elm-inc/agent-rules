# Codex CLI shared setup

This document defines the shared Codex CLI baseline for this repository.

## Source of truth

- Common rules: `RULES.md`
- Codex entrypoint rules: `AGENTS.md`
- Shared Codex profile layers: `.codex/*.config.toml`
- Shared skills: `skills/*/SKILL.md`
- Bootstrap: `install.sh`

Machine-local files are not managed by Git:

- `~/.codex/config.toml`
- `~/.codex/auth.json`
- project trust entries
- model defaults and personal UI settings

## Setup

```bash
~/repos/github.com/elm-inc/agent-rules/install.sh
scripts/codex-doctor.sh
```

Use the standard profile when running Codex:

```bash
codex --profile-v2 agent-rules
codex exec --profile-v2 agent-rules "依頼内容"
```

The wrapper keeps this shorter:

```bash
scripts/codex-agent-rules
scripts/codex-agent-rules exec "依頼内容"
```

## Profiles

| Profile | File | Use |
|---|---|---|
| `agent-rules` | `.codex/agent-rules.config.toml` | Standard shared layer |
| `agent-rules-review` | `.codex/agent-rules-review.config.toml` | Review-oriented runs |
| `agent-rules-local` | `.codex/agent-rules-local.config.toml` | Local development conventions |
| `agent-rules-restricted` | `.codex/agent-rules-restricted.config.toml` | Read-only inspection |

`--profile-v2` applies to runtime commands such as `codex`, `codex exec`, `codex review`, `codex resume`, `codex fork`, and `codex debug prompt-input`. It does not apply to management commands such as `codex mcp list`.

## MCP

Shared MCP definitions belong in `.codex/*.config.toml` or `.codex/mcp/*.toml`.

Do not commit token values. Use environment variable names:

```toml
[mcp_servers.example]
command = "example-mcp-server"
args = ["--stdio"]
env_vars = ["EXAMPLE_TOKEN"]

[mcp_servers.example_http]
url = "https://mcp.example.com/mcp"
bearer_token_env_var = "EXAMPLE_MCP_TOKEN"
```

Use `scripts/render-codex-config.sh agent-rules` to inspect the combined standard profile and MCP fragments.

## Validation

```bash
bash -n install.sh scripts/*.sh
python3 -c 'import tomllib; import pathlib; [tomllib.load(open(p, "rb")) for p in pathlib.Path(".codex").glob("*.config.toml")]'
scripts/validate-codex-skills.sh
scripts/codex-doctor.sh
```

## Review checklist

Before commit:

```bash
codex review --uncommitted
codex --profile-v2 agent-rules-review review --uncommitted
```

Review focus:

- behavior regressions and missing tests
- secret leakage
- destructive commands or excessive permissions
- worktree policy violations
- accidental edits to `~/.codex/config.toml` semantics
- MCP token values committed instead of env var names

## Plugin scaffold

The repository also includes a minimal local Codex plugin scaffold:

- `plugins/agent-rules/.codex-plugin/plugin.json`
- `.agents/plugins/marketplace.json`

This is for future marketplace-based distribution. The primary installation path remains `install.sh` and symlinks.

For a non-default marketplace, install the marketplace root explicitly:

```bash
codex plugin marketplace add .
codex plugin list
```
