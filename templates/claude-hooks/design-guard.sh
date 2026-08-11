#!/usr/bin/env bash
# design-guard.sh — PreToolUse ガード (Edit/Write/MultiEdit 用)
#
# 目的: @elm/base 由来の「managed(上流・shadcn add で再生成)」ファイルへの直接編集を
#       ask に落とし、カスタムを「owned(保持される)」層へ誘導する:
#         - トークン(色/型/余白の値) → app/theme.overrides.css
#         - primitives の挙動        → ラッパー/案件コンポーネント
#       これにより「一部カスタム指示」で base を書き換える事故を機械的に防ぐ。
#
# 配置: 案件の .claude/hooks/design-guard.sh (/shadcn がコピー)。
#       .claude/settings.json の PreToolUse (matcher: "Edit|Write|MultiEdit") から呼ぶ。
#
# 契約: PreToolUse の JSON を stdin で受け、ask のときのみ hookSpecificOutput を stdout に出す。
# 安全側 (fail-open): jq 不在・parse 失敗・対象外は allow (exit 0)。ブロックはしない (ask 止まり)。
set -u

command -v jq >/dev/null 2>&1 || exit 0
input="$(cat)"
[ -n "$input" ] || exit 0

tool="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null)" || exit 0
case "$tool" in
  Edit | Write | MultiEdit) ;;
  *) exit 0 ;;
esac

fp="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
[ -n "$fp" ] || exit 0
base="${fp##*/}"

ask() {
  jq -cn --arg r "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"ask",permissionDecisionReason:$r}}'
  exit 0
}

# 1) shadcn primitives は managed (add で再生成)。直接編集せずラッパーへ。
case "$fp" in
  */components/ui/*)
    ask "『$base』は shadcn primitive (managed / shadcn add で再生成される)。直接編集せず、ラッパーか案件コンポーネントで対応してください。詳細: .claude/rules/elm-design-overrides.md" ;;
esac

# 2) globals.css の base 管理域 (:root / .dark / --token) を触る編集は owned 層へ誘導。
#    add @elm/base は CLI(Bash)経由なのでこのガードには掛からない = 掛かるのは AI の直接編集だけ。
if [ "$base" = "globals.css" ]; then
  payload="$(printf '%s' "$input" \
    | jq -r '[.tool_input.new_string, .tool_input.old_string, .tool_input.content, (.tool_input.edits // [] | map(.new_string, .old_string))] | flatten | map(select(. != null)) | join("\n")' 2>/dev/null)"
  if printf '%s' "$payload" | grep -qE '(--[a-z][a-z0-9-]*[[:space:]]*:|:root|\.dark)'; then
    ask "globals.css は @elm/base の管理域 (add @elm/base で上書きされる)。トークンの上書きは app/theme.overrides.css に書いてください (base 更新でも維持されます)。詳細: .claude/rules/elm-design-overrides.md"
  fi
fi

exit 0
