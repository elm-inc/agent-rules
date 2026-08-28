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
codex --profile agent-rules
codex exec --profile agent-rules "依頼内容"
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

The flag is `-p` / `--profile` (codex-cli 0.149.1; the older `--profile-v2` spelling was removed and now fails with `error: unexpected argument`). A profile name that does not exist is **silently ignored** — Codex starts with defaults instead of failing, so verify the run header shows the settings you expect.

`-p` / `--profile` applies to runtime commands such as `codex`, `codex exec`, `codex review`, `codex resume`, `codex fork`, and `codex debug prompt-input`. It does not apply to management commands such as `codex mcp list`.

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

### Linear MCP

Linear is the primary task tracker for this setup. Register the official streamable HTTP MCP server once per machine:

```bash
codex mcp add linear --url https://mcp.linear.app/mcp
codex mcp login linear
```

The login command opens a Linear OAuth URL and stores the local OAuth credentials under `~/.codex/`. Do not commit those credentials.

Verify registration:

```bash
codex mcp list
codex mcp get linear
```

Verify actual tool use with a small read-only request:

```bash
codex --profile agent-rules exec "Linear MCP を使って、自分が参加している Linear team 名を最大3件だけ表示してください。"
```

The expected MCP call is `linear/list_teams`. If OAuth expires, rerun `codex mcp login linear`.

When starting another Codex session, use the same shared profile:

```bash
codex --profile agent-rules
```

If the session says that only a tool such as `multi_agent_v1` is available and Linear tools such as `linear/list_projects`, `linear/get_issue`, or `linear/save_issue` are not visible, first distinguish the two tool layers:

- `codex mcp list` / `codex mcp get linear` checks local Codex CLI MCP registration.
- The tools exposed directly inside a hosted conversation can be a smaller set and may not list MCP tools even when Codex CLI can use them.
- `codex --profile agent-rules exec "Linear MCP ..."` is the reliable end-to-end check for Codex CLI MCP availability.

If `codex exec` can call `linear/list_teams` but an interactive session cannot, restart that session with `codex --profile agent-rules`. If it still cannot use Linear, capture the startup log and `codex mcp get linear` output; the local registration is then present and the issue is in that session's tool exposure or startup path.

### Codex Apps MCP startup timeout

Codex Apps may start an internal MCP server named `codex_apps`. If startup is slow, Codex can show:

```text
MCP client for `codex_apps` timed out after 30 seconds
```

For Codex CLI 0.133.0, adding only this table to `~/.codex/config.toml` is not safe because it can fail config parsing with `invalid transport`:

```toml
[mcp_servers.codex_apps]
startup_timeout_sec = 90
```

If Codex Apps are not needed on the machine, disable the Apps MCP path locally instead:

```toml
[features]
apps = false
enable_mcp_apps = false
```

If Apps are required, prefer upgrading Codex CLI first and then retesting the timeout override. Keep this setting machine-local until the Codex version in use accepts the partial `codex_apps` timeout table under `--strict-config`.

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
codex --profile agent-rules-review review --uncommitted
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
