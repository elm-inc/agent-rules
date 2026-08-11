#!/usr/bin/env bash
# PreToolUse(Bash) guard: 操作時の安全原則を機械 enforcement する (agent-rules)。
# CLAUDE.md 刈り込み (ADR-0013) で散文ルールから落ちる抑止力を permissions/hook 側で補う。
# templates/claude-settings/settings.user.json から ~/.claude/settings.json に配備して使う。
#
# 入力: PreToolUse hook の JSON (stdin)。出力: allow なら無出力で exit 0、
#       deny/ask は hookSpecificOutput JSON を出して exit 0。
# fail-safe: 判定不能 (jq 無し / parse 失敗 / command 空) は allow に倒し、作業を止めない。
#
# 判定方針: コマンドをセグメント (パイプ・列挙・コマンド置換の境界) に分割し、各セグメントの
#           「実際に実行される先頭コマンド語」が curl/wget 等のときだけ判定する。これにより
#           `echo "https://api.figma.com"` や `git commit -m "...figma.com..."` のような
#           URL を文字列として含むだけの無害コマンドを誤検知しない。
set -uo pipefail

emit() { # decision reason
  jq -cn --arg d "$1" --arg r "$2" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:$d,permissionDecisionReason:$r}}'
  exit 0
}

command -v jq >/dev/null 2>&1 || exit 0
input="$(cat)" || exit 0
cmd="$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)" || exit 0
[ -z "$cmd" ] && exit 0

# セグメント境界 (|| && ; & | $( ` ( ) < > { }) を改行に置換して 1 セグメント 1 行にする。
segments="$(printf '%s' "$cmd" | sed -E 's/(\|\||&&|\$\(|[;&|`(){}<>])/\n/g')"

while IFS= read -r seg; do
  [ -z "$seg" ] && continue
  # 先頭の空白・env 代入 (FOO=bar)・ラッパー語 (sudo/command/env/nohup/nice/time/builtin) を剥がして最初の語を得る
  s="$(printf '%s' "$seg" | sed -E 's/^[[:space:]]+//
                                     :a
                                     s/^([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]+|sudo|command|env|nohup|nice|time|builtin)[[:space:]]+//
                                     ta')"
  first="${s%%[[:space:]]*}"
  first="${first##*/}"   # /usr/bin/curl → curl
  case "$first" in
    curl|wget|xh|http|https|httpie)
      if printf '%s' "$seg" | grep -Eiq 'api\.figma\.com|figma\.com/(v1|api)'; then
        emit deny "Figma API を生 curl で叩かない (安全原則)。レート制御・version 差分キャッシュ・429 バックオフのある /figma 経由で実行してください。"
      fi
      if printf '%s' "$seg" | grep -Eiq '(^|[^[:alnum:].])([[:alnum:]-]+\.)*newrelic\.com|nerdgraph'; then
        emit deny "New Relic API を生 curl で叩かない (顧客テナント取り違え防止・fail-closed)。/newrelic --profile <名> 経由で実行してください。"
      fi
      ;;
    ln)
      # symlink 再設定 (-s フラグ) が ~/.claude 配下 / ~/CLAUDE.md 等を対象にするなら確認を挟む
      if printf '%s' "$s" | grep -Eq '(^|[[:space:]])-[[:alnum:]]*s' && \
         printf '%s' "$seg" | grep -Eq '(\$HOME|~|/home/[^/[:space:]]+)/(\.claude|CLAUDE\.md|RULES\.md|AGENTS\.md)'; then
        emit ask "~/.claude 配下 / ~/CLAUDE.md 等への symlink 再設定です。正規手順は agent-rules の install.sh です。意図した操作か確認してください。"
      fi
      ;;
  esac
done <<< "$segments"

exit 0
