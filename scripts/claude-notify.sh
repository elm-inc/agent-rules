#!/usr/bin/env bash
# Claude Code Notification フック — セッションが注意を要する時 (入力待ち / 許可確認) に
# デスクトップ通知 (Linux/libnotify) + ターミナル通知 + ベルを出す。
# 多数セッションを並行する時、どのプロジェクトのセッションが自分を待っているかを手元で知るため。
#
# 登録 (ローカル ~/.claude/settings.json、既存にマージ):
#   { "hooks": { "Notification": [ {
#       "matcher": "permission_prompt|idle_prompt",
#       "hooks": [ { "type": "command",
#                    "command": "~/repos/github.com/elm-inc/agent-rules/scripts/claude-notify.sh" } ] } ] } }
#
# stdin に JSON (.message / .cwd / .session_id …)。デスクトップ通知は副作用で発火し、
# ターミナル通知は terminalSequence 出力で Claude Code 経由に発火 (v2.1.141+)。Notification は exit 0。

input=$(cat)
msg=$(printf '%s' "$input" | jq -r '.message // "入力待ち / 確認が必要です"' 2>/dev/null)
[ -z "$msg" ] && msg="入力待ち / 確認が必要です"
dir=$(printf '%s' "$input" | jq -r '.cwd // ""' 2>/dev/null)
proj=$(basename "${dir:-.}")
title="Claude Code — ${proj}"

# デスクトップ通知 (Linux/libnotify)。無ければスキップ。
if command -v notify-send >/dev/null 2>&1; then
  notify-send -a "Claude Code" "$title" "$msg" 2>/dev/null || true
fi

# ターミナル通知 (OSC 777) + ベルを Claude Code 経由で発火。jq があれば JSON 出力。
if command -v jq >/dev/null 2>&1; then
  seq=$(printf '\033]777;notify;%s;%s\007\a' "$title" "$msg")
  jq -nc --arg seq "$seq" '{terminalSequence: $seq}' 2>/dev/null || true
fi

exit 0
