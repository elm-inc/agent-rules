# MCP fragments

Shared MCP definitions can live here as TOML fragments.

Rules:

- Do not store token values, secrets, private keys, or `.env` contents.
- For stdio servers, use `env_vars = ["TOKEN_ENV_NAME"]` for secrets that Codex should read from the environment.
- For HTTP servers, use `bearer_token_env_var = "TOKEN_ENV_NAME"`.
- Keep machine-specific command paths out of shared fragments unless every target machine has the same path.

`scripts/render-codex-config.sh` can concatenate profile and MCP fragments for inspection or for generating a profile layer.
