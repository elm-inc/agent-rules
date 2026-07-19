#!/usr/bin/env bash
# Fable 5 の当月利用実費を Claude Code の transcript から集計する。
# 従量課金移行 (included 無償枠は 2026-07-19 まで / 実費 credits は 2026-07-20 開始) に伴い
# 「Fable = 実費」を可視化し過剰利用を抑えるための計器。
# 根拠: docs/adr/0010-fable-metered-billing-controls.md
#
# 使い方:
#   ./scripts/fable-usage.sh                 # 当月のレポート (トークン内訳 + $ + 予算ステータス)
#   ./scripts/fable-usage.sh --month 2026-07 # 指定月
#   ./scripts/fable-usage.sh --statusline    # statusline 用: "<cost_int> <budget_int>" をキャッシュから即返す
#   ./scripts/fable-usage.sh --refresh       # キャッシュを再計算 (統計的に重い。通常は statusline が裏で起動)
#
# 予算しきい値: FABLE_BUDGET_USD (既定 100 / 開発者1人あたり月)。ソフトゲート — ブロックはしない。
# transcript 位置: CLAUDE_PROJECTS_DIR (既定 ~/.claude/projects)。サブエージェントログも再帰的に含む。

set -uo pipefail

BUDGET="${FABLE_BUDGET_USD:-100}"
PROJECTS="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/agent-rules"
CACHE="$CACHE_DIR/fable-mtd.json"
LOCK="/tmp/agent-rules-fable-usage.lock"   # /tmp 固定 (TMPDIR 変動で単一化が破れる)
STALE_SEC=600                              # statusline がこの秒数を超えたキャッシュを裏で更新

# Fable 従量課金の単価 (per MTok)。cache は Anthropic 標準の write=1.25x / read=0.1x を input 単価に乗じた推定。
PRICE_INPUT=10 ; PRICE_CACHE_WRITE=12.5 ; PRICE_CACHE_READ=1 ; PRICE_OUTPUT=50

MODE="report"
MONTH="$(date +%Y-%m)"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --statusline) MODE="statusline" ;;
    --refresh)    MODE="refresh" ;;
    --month)      MONTH="${2:-$MONTH}"; shift ;;
    *) ;;
  esac
  shift
done

# transcript を走査し当月 Fable のトークンを合算 → "input cache_write cache_read output" を返す。
# fail-safe: 依存欠如・データ無しは "0 0 0 0" (安全側 = 0 実費)。
aggregate_tokens() {
  local month="$1" first
  first="${month}-01"
  command -v jq >/dev/null 2>&1 || { echo "0 0 0 0"; return 0; }
  [ -d "$PROJECTS" ] || { echo "0 0 0 0"; return 0; }

  # (1) 当月に追記のあった jsonl だけに絞る (性能。当月 Fable 利用があるセッションは当月 mtime を持つ)
  local -a files ffiles
  mapfile -t files < <(find "$PROJECTS" -type f -name '*.jsonl' -newermt "$first 00:00:00" 2>/dev/null)
  [ "${#files[@]}" -eq 0 ] && { echo "0 0 0 0"; return 0; }
  # (2) fable モデル ID を含むファイルだけ残す (Opus 専用の巨大ログを jq に流さない)
  mapfile -t ffiles < <(grep -lF "claude-fable" "${files[@]}" 2>/dev/null)
  [ "${#ffiles[@]}" -eq 0 ] && { echo "0 0 0 0"; return 0; }

  # (3) assistant かつ model=fable かつ timestamp が当月のメッセージの usage を合算
  cat "${ffiles[@]}" 2>/dev/null \
    | jq -rc --arg m "$month" '
        select(.type == "assistant")
        | select((.message.model // "") | test("fable"))
        | select((.timestamp // "")[0:7] == $m)
        | [ (.message.usage.input_tokens // 0),
            (.message.usage.cache_creation_input_tokens // 0),
            (.message.usage.cache_read_input_tokens // 0),
            (.message.usage.output_tokens // 0) ] | @tsv' 2>/dev/null \
    | awk 'BEGIN{i=cw=cr=o=0}
           {i+=$1; cw+=$2; cr+=$3; o+=$4}
           END{ printf "%d %d %d %d\n", i, cw, cr, o }'
}

# トークン4値 → $ (小数2桁)。awk 比較は使わないので括弧不要だが float 演算のみ。
cost_of() {
  awk -v i="$1" -v cw="$2" -v cr="$3" -v o="$4" \
      -v pi="$PRICE_INPUT" -v pcw="$PRICE_CACHE_WRITE" -v pcr="$PRICE_CACHE_READ" -v po="$PRICE_OUTPUT" \
      'BEGIN{ printf "%.2f", (i*pi + cw*pcw + cr*pcr + o*po)/1000000 }'
}

write_cache() {
  local month="$1" cost="$2" now tmp
  now="$(date +%s)"
  mkdir -p "$CACHE_DIR" 2>/dev/null || return 0
  tmp="$(mktemp "$CACHE_DIR/.fable-mtd.XXXXXX" 2>/dev/null)" || return 0
  printf '{"month":"%s","cost":%s,"budget":%s,"ts":%s}\n' "$month" "$cost" "$BUDGET" "$now" > "$tmp" \
    && mv -f "$tmp" "$CACHE" 2>/dev/null || rm -f "$tmp" 2>/dev/null
}

do_refresh() {
  local toks cost
  toks="$(aggregate_tokens "$MONTH")"
  # shellcheck disable=SC2086
  cost="$(cost_of $toks)"
  write_cache "$MONTH" "$cost"
  echo "$cost"
}

case "$MODE" in
  refresh)
    do_refresh >/dev/null
    ;;

  statusline)
    # キャッシュを即読み (走査しない)。古ければ裏で単一起動リフレッシュ (レンダーを遅延させない)。
    cost="" cmonth="" cts=0
    if [ -f "$CACHE" ]; then
      cost="$(jq -r '.cost // empty' "$CACHE" 2>/dev/null)"
      cmonth="$(jq -r '.month // empty' "$CACHE" 2>/dev/null)"
      cts="$(jq -r '.ts // 0' "$CACHE" 2>/dev/null)"
    fi
    now="$(date +%s)"
    # キャッシュが無い/別月/古い → デタッチしたリフレッシュを 1 本だけ起動 (flock で単一化、親ロックを子に継がせない)
    if [ -z "$cost" ] || [ "$cmonth" != "$MONTH" ] || [ "$(( now - cts ))" -ge "$STALE_SEC" ]; then
      setsid flock -n "$LOCK" bash "$0" --refresh </dev/null >/dev/null 2>&1 9>&- &
    fi
    # 別月のキャッシュは表示に使わない (次のリフレッシュで正される)
    [ "$cmonth" != "$MONTH" ] && cost=""
    if [ -n "$cost" ]; then
      printf '%.0f %.0f\n' "$cost" "$BUDGET"
    else
      echo "NA $BUDGET"
    fi
    ;;

  report|*)
    toks="$(aggregate_tokens "$MONTH")"
    read -r i cw cr o <<<"$toks"
    # shellcheck disable=SC2086
    cost="$(cost_of $toks)"
    # statusline 用キャッシュは当月のみ更新 (過去月レポートで当月キャッシュを汚さない)
    [ "$MONTH" = "$(date +%Y-%m)" ] && write_cache "$MONTH" "$cost"
    pct="$(awk -v c="$cost" -v b="$BUDGET" 'BEGIN{ if ((b+0)>0) printf "%.0f", c/b*100; else printf "0" }')"
    over="$(awk -v c="$cost" -v b="$BUDGET" 'BEGIN{ print ((c+0)>(b+0) ? 1 : 0) }')"

    echo "=== Fable 5 当月利用実費: $MONTH (開発者1人・このマシン) ==="
    echo ""
    printf "  input        : %'d tok\n" "$i" 2>/dev/null || printf "  input        : %d tok\n" "$i"
    printf "  cache write  : %'d tok\n" "$cw" 2>/dev/null || printf "  cache write  : %d tok\n" "$cw"
    printf "  cache read   : %'d tok\n" "$cr" 2>/dev/null || printf "  cache read   : %d tok\n" "$cr"
    printf "  output       : %'d tok\n" "$o" 2>/dev/null || printf "  output       : %d tok\n" "$o"
    echo "  --------------------------------"
    echo "  推定実費     : \$$cost  (予算 \$$BUDGET の ${pct}%)"
    if [ "$over" = "1" ]; then
      echo "  ⚠️  予算超過。以降の Fable 委譲は本当に必要か都度確認する (人手ゲート。ブロックはしない)。"
    fi
    echo ""
    echo "  ※ ローカル transcript ベースの推定。正確な請求は Console: https://console.anthropic.com/settings/usage"
    echo "  ※ included 無償枠は 2026-07-19 まで。7/20 より前の利用は credit 課金外なので、当月推定は上限見積り (実費はこれ以下)。"
    echo "  ※ 結果は docs/design/ai-workflow.md §8 の Fable 行に転記する。"
    ;;
esac
