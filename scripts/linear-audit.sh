#!/usr/bin/env bash
# linear-audit.sh — Linear と worktree レジストリの乖離を検出する (ADR-0021)
#
# なぜ要るか (2026-09-07 実測・15 リポジトリ):
#   worktree タスク 145 件中 Linear 連携は 39 件 (27%)、commit への (ELM-xxx) 参照は 0 件。
#   原因は「メンテを忘れる」ではなく **Linear が作業経路の外にある**こと。
#   出口 (/worktree-finish が自動で Done にする) は既に自動なので、
#   穴は (a) 入口をすり抜ける と (b) 出口を通らずに消える の 2 つだけ。
#
# 検出するのはこの 2 つに限る。**平時に出力しない**ことを最優先にする
#   (毎回 20 件出るような一覧は読まれなくなり、計器としての価値を失う)。
#
# 除外の考え方:
#   Linear は**既定で必須**。除外したいリポは自身のルートに .no-linear を置き理由を書く。
#   **中央集権の除外リストは作らない** — agent-rules は public で顧客案件名が混入するため。
#
# 出力: 乖離があるときだけ。無ければ無音。
# 終了コード: 0=乖離なし / 1=乖離あり

set -uo pipefail
SCOPE_ROOT="${LINEAR_AUDIT_ROOT:-$HOME/repos/github.com/elm-inc}"
found=0
emit() { echo "$1"; found=1; }

command -v jq >/dev/null 2>&1 || { echo "linear-audit: jq が無いため検査できません (0 件と誤認しないこと)" >&2; exit 2; }

for repo in "$SCOPE_ROOT"/*/; do
  name="$(basename "$repo")"
  case "$name" in *-worktrees) continue ;; esac
  [ -d "$repo/.git" ] || continue
  [ -f "$repo/.no-linear" ] && continue     # リポ単位の明示的除外

  reg="$repo/.git/parallel-tasks.json"
  [ -f "$reg" ] || continue

  # (a) 入口すり抜け: active なのに Linear 未連携
  while IFS= read -r t; do
    [ -n "$t" ] && emit "  [$name] worktree '$t' に Linear Issue が無い (既定必須)"
  done < <(jq -r '.tasks[] | select(.status=="active") | select(.linear_issue_id==null) | .name' "$reg" 2>/dev/null)

  # (b) 出口を通らず消えた: active のまま worktree ディレクトリが存在しない
  #     → /worktree-finish を通っていないので Linear は In Progress のまま取り残される
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    tname="${line%%|*}"; tpath="${line#*|}"; tid="${tpath##*|}"; tpath="${tpath%%|*}"
    [ -d "$tpath" ] && continue
    if [ "$tid" != "null" ] && [ -n "$tid" ]; then
      emit "  [$name] '$tname' は worktree が消えているのに active。**${tid} が In Progress のまま**の可能性"
    else
      emit "  [$name] '$tname' は worktree が消えているのに active (レジストリの掃除漏れ)"
    fi
  done < <(jq -r '.tasks[] | select(.status=="active") | "\(.name)|\(.worktree_path)|\(.linear_issue_id)"' "$reg" 2>/dev/null)
done

exit $found
