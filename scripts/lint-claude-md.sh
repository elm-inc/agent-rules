#!/usr/bin/env bash
# CLAUDE.md の健全性 lint (agent-rules)。CI と手元で使う。
# 検査:
#   1. CLAUDE.md が MAX_LINES 行以下 (ADR-0013: 索引を肥大化させない)
#   2. 幽霊参照ゼロ: CLAUDE.md が `/foo` として参照する skill が実在する (or builtin)
#   3. 未掲載 WARN: user-invokable な skill (disable-model-invocation!=true) が CLAUDE.md 索引に無い
# 1・2 が FAIL なら exit 1。3 は WARN (exit には影響しない)。
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_MD="$REPO_DIR/CLAUDE.md"
MAX_LINES="${CLAUDE_MD_MAX_LINES:-200}"

# skill でない組み込みスラッシュコマンド (幽霊参照から除外)
# code-review / security-review / init は Claude Code 同梱の builtin skill (本リポには置かない)
BUILTINS=" model verify run config rename resume plugin mcp clear help compact memory login logout code-review security-review init "

fail=0

# --- 1. 行数 ---
if [[ ! -f "$CLAUDE_MD" ]]; then
    echo "FAIL: $CLAUDE_MD が無い"
    exit 1
fi
n="$(wc -l < "$CLAUDE_MD")"
if [[ "$n" -gt "$MAX_LINES" ]]; then
    echo "FAIL: CLAUDE.md $n 行 > 上限 $MAX_LINES 行"
    fail=1
else
    echo "ok:   CLAUDE.md $n 行 (<= $MAX_LINES)"
fi

# --- 2. 幽霊参照 (backtick で囲まれた /command を対象。URL/パス誤検出を避ける) ---
ghost=0
while IFS= read -r r; do
    [[ -z "$r" ]] && continue
    [[ -d "$REPO_DIR/skills/$r" ]] && continue
    case "$BUILTINS" in *" $r "*) continue ;; esac
    echo "FAIL: CLAUDE.md の参照 /$r に対応する skill も builtin も無い (幽霊参照)"
    ghost=$((ghost + 1))
    fail=1
done < <(grep -oE '`/[a-z][a-z0-9-]+' "$CLAUDE_MD" | tr -d '`/' | sort -u)
[[ "$ghost" -eq 0 ]] && echo "ok:   幽霊参照なし"

# --- 3. 未掲載スキル (WARN のみ) ---
warn=0
for d in "$REPO_DIR"/skills/*/; do
    name="$(basename "$d")"
    # 明示的に自動起動を切ったスキルは索引不要 (opt-out)
    grep -q '^disable-model-invocation:[[:space:]]*true' "$d/SKILL.md" 2>/dev/null && continue
    # CLAUDE.md に `/name` 参照があれば OK
    grep -qE "\`/$name([\` ]|$)" "$CLAUDE_MD" && continue
    echo "WARN: skill /$name が CLAUDE.md 索引に無く disable-model-invocation:true でもない"
    warn=$((warn + 1))
done
[[ "$warn" -eq 0 ]] && echo "ok:   未掲載の user-invokable skill なし"

echo ""
if [[ "$fail" -ne 0 ]]; then
    echo "lint: FAIL"
    exit 1
fi
echo "lint: OK${warn:+ (WARN $warn 件)}"
exit 0
