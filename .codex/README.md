# Codex configuration

This directory contains Codex-specific shared configuration managed by this repository.

## Files

- `agent-rules.config.toml`: shared Codex `--profile-v2 agent-rules` config layer.

## Policy

- Keep secrets, auth files, local project trust entries, and personal model defaults in `~/.codex/config.toml`.
- Put shared MCP definitions and shared feature flags in `agent-rules.config.toml`.
- Run Codex with `--profile-v2 agent-rules` when this shared layer should be applied.

`install.sh` symlinks this file to `~/.codex/agent-rules.config.toml`.
