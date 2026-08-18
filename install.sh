#!/usr/bin/env bash
# Install / refresh symlinks for agent-rules:
# - top-level rules: CLAUDE.md, RULES.md, AGENTS.md
# - Claude skills: ~/.claude/skills/*
# - Claude subagents: ~/.claude/agents/*
# - Codex skills: ~/.codex/skills/*
# - Codex profile-v2 config layers: ~/.codex/*.config.toml
#
# 使い方:
#   ./install.sh            symlink を作成/更新 (既存 symlink はスキップ)。従来どおり
#   ./install.sh --check    doctor: symlink 完全性 + settings drift を検査 (無変更)。問題があれば exit 1
#   ./install.sh --fix      作成/更新 + ユーザーレベル settings を add-only マージ (新規キーのみ)
#
# Idempotent — re-running on an already-installed machine is safe.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

MODE=install
case "${1:-}" in
    --check) MODE=check ;;
    --fix)   MODE=fix ;;
    ""|--install) MODE=install ;;
    -h|--help)
        sed -n '11,14p' "$0" | sed 's/^#\s\?//'
        exit 0 ;;
    *) echo "unknown arg: $1 (--check / --fix / なし)"; exit 2 ;;
esac

PROBLEMS=0

ln_if_not() {
    local src="$1"
    local dst="$2"

    if [[ -L "$dst" ]]; then
        local current="$(readlink "$dst")"
        if [[ "$current" == "$src" ]]; then
            echo "ok:   $dst"
            return
        fi
        echo "WARN: $dst is a symlink to $current (expected $src), skipping"
        return
    fi

    if [[ -e "$dst" ]]; then
        echo "WARN: $dst exists and is not a symlink, skipping"
        return
    fi

    if ! mkdir -p "$(dirname "$dst")"; then
        echo "WARN: could not create parent directory for $dst, skipping"
        return
    fi

    if ln -s "$src" "$dst" 2>/dev/null; then
        echo "link: $dst -> $src"
    else
        echo "WARN: could not link $dst -> $src, skipping"
    fi
}

# 読み取り専用の完全性チェック。問題は PROBLEMS に加算する (無変更)。
check_link() {
    local src="$1" dst="$2"
    if [[ -L "$dst" ]]; then
        if [[ "$(readlink "$dst")" == "$src" ]]; then
            echo "ok:   $dst"
        else
            echo "WRONG: $dst -> $(readlink "$dst") (expected $src)"
            PROBLEMS=$((PROBLEMS + 1))
        fi
    elif [[ -e "$dst" ]]; then
        echo "WARN: $dst exists and is not a symlink"
        PROBLEMS=$((PROBLEMS + 1))
    else
        echo "MISSING: $dst (expected -> $src)"
        PROBLEMS=$((PROBLEMS + 1))
    fi
}

# MODE に応じて 1 リンクを作成 (install/fix) or 検査 (check)
handle_link() {
    if [[ "$MODE" == check ]]; then
        check_link "$1" "$2"
    else
        ln_if_not "$1" "$2"
    fi
}

# check 以外でのみディレクトリ作成 (check は無変更)
ensure_dir() {
    [[ "$MODE" == check ]] || mkdir -p "$1"
}

echo "== Top-level rules =="
handle_link "$REPO_DIR/CLAUDE.md" "$HOME/CLAUDE.md"
handle_link "$REPO_DIR/RULES.md"  "$HOME/RULES.md"
handle_link "$REPO_DIR/AGENTS.md" "$HOME/AGENTS.md"

echo ""
echo "== Claude skills =="
ensure_dir "$HOME/.claude/skills"
for skill_dir in "$REPO_DIR"/skills/*/; do
    skill_name="$(basename "$skill_dir")"
    handle_link "$REPO_DIR/skills/$skill_name" "$HOME/.claude/skills/$skill_name"
done

echo ""
echo "== Claude subagents =="
ensure_dir "$HOME/.claude/agents"
for agent_file in "$REPO_DIR"/agents/*.md; do
    [ -e "$agent_file" ] || continue
    agent_name="$(basename "$agent_file")"
    handle_link "$REPO_DIR/agents/$agent_name" "$HOME/.claude/agents/$agent_name"
done

echo ""
echo "== Codex skills =="
ensure_dir "$HOME/.codex/skills"
for skill_dir in "$REPO_DIR"/skills/*/; do
    skill_name="$(basename "$skill_dir")"
    handle_link "$REPO_DIR/skills/$skill_name" "$HOME/.codex/skills/$skill_name"
done

echo ""
echo "== Codex config profile =="
for config_file in "$REPO_DIR"/.codex/*.config.toml; do
    config_name="$(basename "$config_file")"
    handle_link "$config_file" "$HOME/.codex/$config_name"
done

echo ""
echo "== Shell integration =="
ensure_dir "$HOME/.claude/shell"
handle_link "$REPO_DIR/scripts/zellij-hygiene.sh" "$HOME/.claude/shell/zellij-hygiene.sh"
handle_link "$REPO_DIR/scripts/env-snippet.sh"    "$HOME/.claude/shell/env-snippet.sh"

# ユーザーレベル settings の add-only 適用 / drift 検査。
# add-only: template のトップレベルキーのうち user に無いものだけ追加。既存キーは決して上書きしない。
handle_user_settings() {
    local tmpl="$REPO_DIR/templates/claude-settings/settings.user.json"
    local user="$HOME/.claude/settings.json"
    echo ""
    echo "== User settings (add-only) =="
    if [[ ! -f "$tmpl" ]]; then
        echo "skip: template なし ($tmpl)"
        return
    fi
    if ! command -v jq >/dev/null 2>&1; then
        echo "WARN: jq 無しのため settings チェックを skip"
        return
    fi
    if [[ ! -f "$user" ]]; then
        if [[ "$MODE" == fix ]]; then
            mkdir -p "$(dirname "$user")"
            cp "$tmpl" "$user"
            echo "add:  $user を新規作成 (template から)"
        else
            echo "MISSING: $user (template あり。--fix で作成 or 手動配置)"
            # `[[ ]] && ...` を最終文にしない: 偽のとき戻り値 1 で set -e が発火し、
            # 以降の Bash integration が丸ごと skip される (実際に踏んだ)
            if [[ "$MODE" == check ]]; then PROBLEMS=$((PROBLEMS + 1)); fi
        fi
        return
    fi
    # template のトップレベルキーで user に無いもの (= drift)
    local missing=()
    local k
    while IFS= read -r k; do
        if jq -e --arg k "$k" 'has($k)' "$user" >/dev/null 2>&1; then
            echo "skip: settings.$k は既存 (add-only では上書きしない。差分は手動マージ)"
        else
            missing+=("$k")
        fi
    done < <(jq -r 'keys[]' "$tmpl")

    if [[ "${#missing[@]}" -eq 0 ]]; then
        echo "ok:   settings に未適用の template キーなし"
        return
    fi
    if [[ "$MODE" == fix ]]; then
        local tmp
        tmp="$(mktemp)" && jq -s '.[0] + .[1]' "$tmpl" "$user" > "$tmp" && mv "$tmp" "$user"
        echo "add:  settings に追加: ${missing[*]}"
    else
        echo "DRIFT: settings 未適用キー: ${missing[*]} (--fix で add-only 追加)"
        if [[ "$MODE" == check ]]; then PROBLEMS=$((PROBLEMS + 1)); fi
    fi
}
handle_user_settings

# bashrc 連携は install/fix のみ (check は無変更)
if [[ "$MODE" != check ]]; then
    echo ""
    echo "== Bash integration =="
    SNIPPET='source $HOME/.claude/skills/cli-help/bash.sh'
    if grep -qxF "$SNIPPET" "$HOME/.bashrc" 2>/dev/null; then
        echo "ok:   .bashrc already sources cli-help/bash.sh"
    else
        printf '\n# modern CLI cheatsheet & soft reminder (agent-rules)\n%s\n' "$SNIPPET" >> "$HOME/.bashrc"
        echo "add:  .bashrc <- source cli-help/bash.sh"
    fi

    ZJ_SNIPPET='source $HOME/.claude/shell/zellij-hygiene.sh'
    if grep -qxF "$ZJ_SNIPPET" "$HOME/.bashrc" 2>/dev/null; then
        echo "ok:   .bashrc already sources zellij-hygiene.sh"
    else
        printf '\n# zellij session hygiene (agent-rules)\n%s\n' "$ZJ_SNIPPET" >> "$HOME/.bashrc"
        echo "add:  .bashrc <- source zellij-hygiene.sh"
    fi

    # API キー・ローカル LLM の環境変数。キー本体は ~/.*_token (600) に置き、ここでは読むだけ。
    # 注意: .bashrc は非対話シェルで早期 return するため、これが効くのは対話シェルと
    # そこから継承する子プロセス (claude 等) のみ。CI や非対話実行では skill 側の
    # ~/.*_token fallback が受け持つ。
    ENV_SNIPPET='source $HOME/.claude/shell/env-snippet.sh'
    if grep -qxF "$ENV_SNIPPET" "$HOME/.bashrc" 2>/dev/null; then
        echo "ok:   .bashrc already sources env-snippet.sh"
    else
        printf '\n# AI workflow env (API keys / local LLM) (agent-rules)\n%s\n' "$ENV_SNIPPET" >> "$HOME/.bashrc"
        echo "add:  .bashrc <- source env-snippet.sh  (要 source ~/.bashrc or 新しいシェル)"
    fi
fi

echo ""
if [[ "$MODE" == check ]]; then
    if [[ "$PROBLEMS" -eq 0 ]]; then
        echo "doctor: 問題なし (symlink 完全・settings drift なし)"
        exit 0
    fi
    echo "doctor: $PROBLEMS 件の問題を検出 (--fix で解消できるものは解消)"
    exit 1
fi
echo "Install complete."
