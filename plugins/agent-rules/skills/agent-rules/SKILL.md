---
name: agent-rules
description: Use the elm-inc agent-rules repository as the shared Codex CLI baseline for rules, skills, MCP profile layers, worktree policy, and review workflow.
---

# Agent Rules

Use this skill when a Codex session needs to understand or apply the shared `agent-rules` baseline.

## Workflow

1. Read `RULES.md` for cross-agent policy.
2. Read `AGENTS.md` for Codex-specific operating rules.
3. Use `docs/setup/codex-cli.md` for setup, MCP, profile, doctor, and validation details.
4. Prefer `scripts/codex-doctor.sh` and `scripts/validate-codex-skills.sh` when checking an installation.

Keep `~/.codex/config.toml` local. Shared Codex settings belong in `.codex/*.config.toml` and secrets must be referenced by environment variable name only.
