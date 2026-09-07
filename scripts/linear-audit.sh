#!/usr/bin/env bash
# linear-audit.sh — Linear と worktree レジストリの乖離を検出する (ADR-0021)
#
# なぜ要るか (2026-09-07 実測・15 リポジトリ):
#   worktree タスク 145 件中 Linear 連携は 39 件 (27%)、commit への (ELM-xxx) 参照は 0 件。
#   原因は「メンテを忘れる」ではなく **Linear が作業経路の外にある**こと。
#   出口 (/worktree-finish が自動で Done にする) は既に自動なので、
#   穴は (a) 入口をすり抜ける と (b) 出口を通らずに消える の 2 つだけ。
#
#   さらに (c) 滞留 (active だが長期間コミットが無い) を検出する。
#   これは移行作業で判明した — 未連携 active 8 件のうち **6 件が 85-129 日停止**していた。
#   **滞留タスクに Issue を作ると、避けたい滞留を自分で作ることになる。**
#   「Issue を作る」前に「まだやるのか」を問える形にする。
#
# 検出するのはこの 3 つに限る。**平時に出力しない**ことを最優先にする
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
STALE_DAYS="${LINEAR_AUDIT_STALE_DAYS:-60}"   # これ以上コミットが無い active を滞留とみなす
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

  # active な各タスクについて「事実」を集め、**1 タスク 1 行**にまとめて出す。
  # 同じタスクが複数行に散ると読む負荷が上がり、計器として使われなくなる。
  while IFS='|' read -r tname tpath tid; do
    [ -n "$tname" ] || continue
    facts=""

    # (a) 入口すり抜け: Linear 未連携
    [ "$tid" = "null" ] || [ -z "$tid" ] && facts="Linear 未連携"

    if [ ! -d "$tpath" ]; then
      # (b) 出口を通らず消えた: worktree が無いのに active
      if [ "$tid" != "null" ] && [ -n "$tid" ]; then
        facts="${facts:+$facts / }worktree 消滅 — **${tid} が In Progress のまま**の可能性"
      else
        facts="${facts:+$facts / }worktree 消滅 (レジストリの掃除漏れ)"
      fi
    else
      # (c) 滞留: worktree はあるが長期間コミットが無い
      last="$(git -C "$tpath" log -1 --format=%ct 2>/dev/null)"
      if [ -n "$last" ]; then
        days=$(( ( $(date +%s) - last ) / 86400 ))
        if [ "$days" -ge "$STALE_DAYS" ]; then
          base="$(jq -r --arg n "$tname" '.tasks[] | select(.name==$n) | .base_branch // "main"' "$reg" 2>/dev/null | head -1)"
          ahead="$(git -C "$tpath" rev-list --count "${base}..HEAD" 2>/dev/null || echo "?")"
          if [ "$ahead" = "0" ]; then
            facts="${facts:+$facts / }${days}日停止・未マージ 0 commit (実質空)"
          else
            facts="${facts:+$facts / }${days}日停止 (未マージ ${ahead} commit)"
          fi
        fi
      fi
    fi

    [ -n "$facts" ] && emit "  [$name] $tname — $facts"
  done < <(jq -r '.tasks[] | select(.status=="active") | "\(.name)|\(.worktree_path)|\(.linear_issue_id)"' "$reg" 2>/dev/null)
done

exit $found
