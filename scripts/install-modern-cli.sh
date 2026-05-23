#!/usr/bin/env bash
# Install recommended modern CLI tools via cargo.
# Idempotent: skips already-installed binaries (by `command -v`).
#
# Usage: bash ~/repos/github.com/elm-inc/agent-rules/scripts/install-modern-cli.sh

set -uo pipefail

if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo not found. Install rustup first: https://rustup.rs/" >&2
  exit 1
fi

# crate:binary  (binary name differs from crate for some)
PKGS=(
  ripgrep:rg
  fd-find:fd
  bat:bat
  eza:eza
  du-dust:dust
  bottom:btm
  procs:procs
  git-delta:delta
  sd:sd
  hyperfine:hyperfine
  tealdeer:tldr
  jless:jless
  tokei:tokei
  zoxide:zoxide
)

installed=()
skipped=()
failed=()

for pair in "${PKGS[@]}"; do
  pkg="${pair%%:*}"
  bin="${pair##*:}"
  if command -v "$bin" >/dev/null 2>&1; then
    skipped+=("$bin")
    printf 'skip:    %-12s (found: %s)\n' "$pkg" "$(command -v "$bin")"
    continue
  fi
  printf 'install: %s ...\n' "$pkg"
  if cargo install --locked "$pkg"; then
    installed+=("$bin")
  else
    failed+=("$pkg")
    printf 'FAILED:  %s\n' "$pkg" >&2
  fi
done

echo ""
echo "== summary =="
printf 'installed (%d): %s\n' "${#installed[@]}" "${installed[*]:-none}"
printf 'skipped   (%d): %s\n' "${#skipped[@]}"   "${skipped[*]:-none}"
printf 'failed    (%d): %s\n' "${#failed[@]}"    "${failed[*]:-none}"

if command -v tldr >/dev/null 2>&1; then
  echo ""
  echo "tip: tldr --update でキャッシュを最新化"
fi

if [ ${#failed[@]} -gt 0 ]; then
  exit 2
fi
