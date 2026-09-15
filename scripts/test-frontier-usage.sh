#!/usr/bin/env bash
# frontier-usage.sh の Fable 集計の回帰テスト
#
# 守るもの: cat で連結した transcript に不正な JSON 行が 1 行でも混じると、
#           jq がストリーム全体を abort し、それ以降のファイルが丸ごと
#           集計から落ちる (2>/dev/null で無音)。実測で月次コストが
#           $28.38 と表示され、実際は $272.25 だった (約 10 倍の過少報告)。
# Linear: AGENT-22 / GitHub: #56
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="$SCRIPT_DIR/frontier-usage.sh"
MONTH="$(date +%Y-%m)"
TS="${MONTH}-01T00:00:00.000Z"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PROJ="$TMP/projects/dummy-repo"
mkdir -p "$PROJ/session/subagents"

# usage 付きの assistant 行を作る
row() {  # $1=input $2=cache_w $3=cache_read $4=output
  printf '{"type":"assistant","timestamp":"%s","message":{"model":"claude-fable-5-1","usage":{"input_tokens":%s,"cache_creation_input_tokens":%s,"cache_read_input_tokens":%s,"output_tokens":%s}}}\n' \
    "$TS" "$1" "$2" "$3" "$4"
}

# a.jsonl: 正常 2 行 + 【不正な JSON 行】。以前はここでストリームが死んだ。
{ row 100 200 300 400
  printf '{"parentUuid":"x","attachment":{"type":"hook_success","hookName":\n'   # 壊れた行
  row 100 200 300 400
} > "$PROJ/session/a.jsonl"

# b.jsonl: abort 位置より後ろ。修正前は丸ごと落ちていた。
row 1000 2000 3000 4000 > "$PROJ/session/subagents/agent-b.jsonl"

# Astra 側は空台帳 (NA にせず 0 件として扱わせる)
: > "$TMP/astra.jsonl"

OUT="$(CLAUDE_PROJECTS_DIR="$TMP/projects" \
       ASTRA_LEDGER="$TMP/astra.jsonl" \
       XDG_CACHE_HOME="$TMP/cache" \
       bash "$TARGET" 2>&1)"

fail=0
check() {  # $1=説明 $2=期待する正規表現
  if grep -qE "$2" <<<"$OUT"; then
    echo "  ok   : $1"
  else
    echo "  FAIL : $1"
    echo "         期待: $2"
    fail=1
  fi
}

echo "=== frontier-usage.sh: Fable 集計の回帰テスト ($MONTH) ==="

# 期待値: input 100+100+1000 = 1,200 / output 400+400+4000 = 4,800
# 不正行より後ろの b.jsonl が集計されることが本テストの主眼。
check "不正行の前後と別ファイルの input が全て集計される (1,200)" 'input +: +1,?200 tok'
check "不正行の前後と別ファイルの output が全て集計される (4,800)" 'output +: +4,?800 tok'
check "cache read が集計される (3,600)"                             'cache read +: +3,?600 tok'
check "parse できない行が 1 件として報告される"                      'parse できない行を 1 件'

# 過少報告の回帰そのもの: 不正行で打ち切られると input は 100 で止まる
if grep -qE 'input +: +100 tok' <<<"$OUT"; then
  echo "  FAIL : 不正行でストリームが abort している (回帰)"
  fail=1
fi

echo ""
if [ "$fail" -eq 0 ]; then
  echo "全て pass"
else
  echo "失敗あり。実際の出力:"; echo "$OUT" | sed 's/^/    /'
fi
exit "$fail"
