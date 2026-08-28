# Codex configuration

This directory contains Codex-specific shared configuration managed by this repository.

## Files

- `agent-rules.config.toml`: standard shared Codex `--profile agent-rules` config layer.
- `agent-rules-review.config.toml`: review-oriented layer.
- `agent-rules-local.config.toml`: local-development layer.
- `agent-rules-restricted.config.toml`: conservative read-only layer.
- `mcp/*.toml`: MCP fragments used as shared templates or render inputs.

## Policy

- Keep secrets, auth files, local project trust entries, and personal model defaults in `~/.codex/config.toml`.
- Put shared MCP definitions and shared feature flags in `.config.toml` profile layers or `mcp/*.toml` fragments.
- Run Codex with `--profile agent-rules` when the standard shared layer should be applied.

`install.sh` symlinks every `.codex/*.config.toml` file to `~/.codex/`.
