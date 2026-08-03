#!/usr/bin/env bash
# PreToolUse(Bash) guard: 操作時の安全原則を機械 enforcement する (agent-rules)。
# CLAUDE.md 刈り込み (ADR-0013) で散文ルールから落ちる抑止力を permissions/hook 側で補う。
# templates/claude-settings/settings.user.json から ~/.claude/settings.json に配備して使う。
#
# 入力: PreToolUse hook の JSON (stdin)。出力: allow なら無出力で exit 0、
#       deny/ask は hookSpecificOutput JSON を出して exit 0。
# fail-safe: 判定不能 (jq 無し / parse 失敗 / command 空) は allow に倒し、作業を止めない。
set -uo pipefail

emit() { # decision reason
  # permissionDecisionReason は JSON 文字列に載せるため jq で安全にエンコードする
  jq -cn --arg d "$1" --arg r "$2" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:$d,permissionDecisionReason:$r}}'
  exit 0
}

command -v jq >/dev/null 2>&1 || exit 0
input="$(cat)" || exit 0
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)" || exit 0
[ -z "$cmd" ] && exit 0

# --- 生 HTTP クライアントで skill を迂回する呼び出しを止める ---
if printf '%s' "$cmd" | grep -Eiq '(^|[^[:alnum:]_])(curl|wget|xh|http|https|httpie)([^[:alnum:]_]|$)'; then
  if printf '%s' "$cmd" | grep -Eiq 'api\.figma\.com|figma\.com/(v1|api)'; then
    emit deny "Figma API を生 curl で叩かない (安全原則)。レート制御・version 差分キャッシュ・429 バックオフのある /figma 経由で実行してください。"
  fi
  if printf '%s' "$cmd" | grep -Eiq '(^|[^[:alnum:].])([[:alnum:]-]+\.)*newrelic\.com|nerdgraph'; then
    emit deny "New Relic API を生 curl で叩かない (顧客テナント取り違え防止・fail-closed)。/newrelic --profile <名> 経由で実行してください。"
  fi
fi

# --- ~/.claude / ~/CLAUDE.md 等への symlink 再設定 (差し替え面) は確認を挟む ---
if printf '%s' "$cmd" | grep -Eq '(^|[^[:alnum:]_])ln[[:space:]]+-[[:alnum:]]*s'; then
  if printf '%s' "$cmd" | grep -Eq '(\$HOME|~|/home/[^/[:space:]]+)/(\.claude|CLAUDE\.md|RULES\.md|AGENTS\.md)'; then
    emit ask "~/.claude 配下 / ~/CLAUDE.md 等への symlink 再設定です。正規手順は agent-rules の install.sh です。意図した操作か確認してください。"
  fi
fi

exit 0
