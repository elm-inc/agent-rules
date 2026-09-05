#!/usr/bin/env bash
# フロンティア層 (Claude Fable 5.1 + GPT-6 Astra) の当月コストを集計する。
#
# 「フロンティア層」= $10/$50 per MTok クラス = セッションモデル (Opus 5) の 2 倍単価。
# 現在の構成員は 2 つで、**計測経路が違う**ことがこのスクリプトの本質的な難所:
#
#   Fable 5.1 : Claude Code の transcript (~/.claude/projects/**/*.jsonl) に
#               model と usage が残るのでトークン単位で拾える。
#               Max は週次上限の 50% まで included (恒久)、超過分のみ実費。
#               included 消費はローカルから観測できないため【上限見積り】(実費 ≤ 表示値)。
#
#   GPT-6 Astra: Codex CLI が別プロセスで走るため transcript に残らない。
#               OpenAI の usage/costs API は admin scope (api.usage.read) が要り、
#               通常の sk-proj- キーでは 403 になる (2026-09-06 実測)。
#               → scripts/codex-astra.sh が呼び出しごとに残す【呼び出し台帳】を読む。
#                 台帳にトークン数があれば $ 換算し、無ければ「回数だけ既知」として
#                 未計上であることを明示する (0 と偽らない)。
#
# 根拠: docs/adr/0019-frontier-tier-orchestration.md (ADR-0010 のフロンティア一般化)
#
# 使い方:
#   ./scripts/frontier-usage.sh                 # 当月レポート (内訳 + $ + 予算ステータス)
#   ./scripts/frontier-usage.sh --month 2026-08 # 指定月
#   ./scripts/frontier-usage.sh --statusline    # statusline 用: "<cost_int> <budget_int> <flag>"
#   ./scripts/frontier-usage.sh --refresh       # キャッシュ再計算 (重い。通常は statusline が裏で起動)
#
# 予算しきい値: FRONTIER_BUDGET_USD (既定 100 / 開発者1人あたり月。旧 FABLE_BUDGET_USD も読む)。
# ソフトゲート — ブロックはしない (ADR-0010 の決定を踏襲)。

set -uo pipefail

BUDGET="${FRONTIER_BUDGET_USD:-${FABLE_BUDGET_USD:-100}}"
PROJECTS="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/agent-rules"
CACHE="$CACHE_DIR/frontier-mtd.json"
ASTRA_LEDGER="${ASTRA_LEDGER:-$CACHE_DIR/frontier-astra.jsonl}"
LOCK="/tmp/agent-rules-frontier-usage.lock"   # /tmp 固定 (TMPDIR 変動で単一化が破れる)
STALE_SEC=600                                 # statusline がこの秒数を超えたキャッシュを裏で更新

# --- 単価 (per MTok) -------------------------------------------------------
# Fable: $10/$50 は 5 → 5.1 で据え置き。**cache read だけ世代で違う** (5 = $1 / 5.1 = $0.25)。
# 過去月レポートや移行月の混在データを過少計上しないため、cache read は世代別に集計する。
PRICE_INPUT=10 ; PRICE_CACHE_WRITE_5M=12.5 ; PRICE_CACHE_WRITE_1H=20 ; PRICE_OUTPUT=50
PRICE_CACHE_READ_51=0.25   # claude-fable-5-1
PRICE_CACHE_READ_5=1       # 旧世代 claude-fable-5 の単価 (過去月の集計用)  # model-doctor:allow

# GPT-6 Astra (2026-09-06 時点)。272K 超の入力は input 2x / output 1.5x。
ASTRA_PRICE_INPUT=10 ; ASTRA_PRICE_CACHED=1 ; ASTRA_PRICE_OUTPUT=50
ASTRA_LONG_CTX_THRESHOLD=272000

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

# --- Fable: transcript を走査 ---------------------------------------------
# "input cache_write_5m cache_write_1h cache_read output" を返す。
# fail-safe: 依存欠如・データ無しは "0 0 0 0 0" (安全側 = 0 実費)。
# 注: model 一致は test("fable") と広く取る。過去月レポートで旧世代の Fable も
#     正しく集計するためで、退役 ID を意図的に含む。  # model-doctor:allow
aggregate_fable() {
  local month="$1" first
  first="${month}-01"
  command -v jq >/dev/null 2>&1 || { echo "0 0 0 0 0 0"; return 0; }
  [ -d "$PROJECTS" ] || { echo "0 0 0 0 0 0"; return 0; }

  local -a files ffiles
  mapfile -t files < <(find "$PROJECTS" -type f -name '*.jsonl' -newermt "$first 00:00:00" 2>/dev/null)
  [ "${#files[@]}" -eq 0 ] && { echo "0 0 0 0 0 0"; return 0; }
  mapfile -t ffiles < <(grep -lF "claude-fable" "${files[@]}" 2>/dev/null)
  [ "${#ffiles[@]}" -eq 0 ] && { echo "0 0 0 0 0 0"; return 0; }

  # cache read は世代別に分ける (第6列にモデル世代フラグを出す)
  cat "${ffiles[@]}" 2>/dev/null \
    | jq -rc --arg m "$month" '
        select(.type == "assistant")
        | select((.message.model // "") | test("fable"))
        | select((.timestamp // "")[0:7] == $m)
        | [ (.message.usage.input_tokens // 0),
            (.message.usage.cache_creation_input_tokens // 0),
            ((.message.usage.cache_creation // {}) | .ephemeral_1h_input_tokens // 0),
            (.message.usage.cache_read_input_tokens // 0),
            (.message.usage.output_tokens // 0),
            (if (.message.model // "") | test("fable-5-1") then "new" else "old" end)
          ] | @tsv' 2>/dev/null \
    | awk -F'\t' 'BEGIN{i=c5=c1=crn=cro=o=0}
           { i+=$1; o+=$5
             if ($6 == "new") { crn+=$4 } else { cro+=$4 }
             if ($3 > $2) { c5+=$2 }            # 内訳異常時は全量 5m (下限) 扱い
             else         { c5+=$2-$3; c1+=$3 } }
           END{ printf "%d %d %d %d %d %d\n", i, c5, c1, crn, cro, o }'
}

# 引数: i c5 c1 cache_read_5.1 cache_read_5 o
# 注: Anthropic の input_tokens は cache トークンを【含まない】(disjoint。2026-09-06 実測で確認)。
#     OpenAI (Astra) は逆に部分集合なので、あちらの式をここに流用してはいけない。
fable_cost_of() {
  awk -v i="$1" -v c5="$2" -v c1="$3" -v crn="$4" -v cro="$5" -v o="$6" \
      -v pi="$PRICE_INPUT" -v p5="$PRICE_CACHE_WRITE_5M" -v p1="$PRICE_CACHE_WRITE_1H" \
      -v pcn="$PRICE_CACHE_READ_51" -v pco="$PRICE_CACHE_READ_5" -v po="$PRICE_OUTPUT" \
      'BEGIN{ printf "%.2f", (i*pi + c5*p5 + c1*p1 + crn*pcn + cro*pco + o*po)/1000000 }'
}

# --- Astra: 呼び出し台帳を走査 --------------------------------------------
# 返り値: "cost calls_total calls_unmetered"
#   calls_unmetered = $ に計上できていない呼び出し数。次の 2 種を含む:
#     (a) 完了したがトークン数を出力から拾えなかった (end 行の input/output が null)
#     (b) start 行はあるが end 行が無い = 中断・クラッシュ (実費は発生している可能性が高い)
#   jq 欠如は「計測不能」として cost に "NA" を返す — 0 と偽ると監査不能な $0 になる。
#
# 台帳 1 行 (2 phase):
#   {"ts":N,"month":"YYYY-MM","model":...,"id":"<call>","phase":"start"}
#   {"ts":N,...,"id":"<call>","phase":"end","input":N|null,"cached":N|null,"output":N|null,"rc":N}
aggregate_astra() {
  local month="$1"
  command -v jq >/dev/null 2>&1 || { echo "NA 0 0"; return 0; }
  [ -f "$ASTRA_LEDGER" ] || { echo "0.00 0 0"; return 0; }

  # id ごとに start/end を突き合わせる。旧形式 (phase 無しの 1 行完結) も受け付ける。
  jq -rc --arg m "$month" '
        select((.month // "") == $m)
        | [ (.id // "legacy-\(.ts)"), (.phase // "end"),
            (.input // -1), (.cached // -1), (.output // -1) ] | @tsv' \
      "$ASTRA_LEDGER" 2>/dev/null \
    | awk -F'\t' -v pi="$ASTRA_PRICE_INPUT" -v pc="$ASTRA_PRICE_CACHED" -v po="$ASTRA_PRICE_OUTPUT" \
          -v thr="$ASTRA_LONG_CTX_THRESHOLD" '
        { seen[$1]=1
          if ($2 == "end") { ended[$1]=1; inp[$1]=$3; cch[$1]=$4; out[$1]=$5 } }
        END{
          cost=0; n=0; unmetered=0
          for (id in seen) {
            n++
            if (!(id in ended))            { unmetered++; continue }  # (b) 中断
            if (inp[id] < 0 || out[id] < 0) { unmetered++; continue }  # (a) トークン不明
            i=inp[id]; c=(cch[id]<0?0:cch[id]); o=out[id]
            if (c > i) c = i                            # 異常値の保険
            mi = (i > thr) ? 2   : 1                    # 272K 超は input 2x (判定は総入力)
            mo = (i > thr) ? 1.5 : 1                    #            output 1.5x
            # OpenAI では cached_tokens は input_tokens の【部分集合】(2026-09-06 実測:
            # input=3912 / cached=3909)。素の input 単価は非キャッシュ分にだけ課す。
            # Anthropic は逆に disjoint なので、同じ式を Fable 側に使ってはいけない。
            cost += ((i - c)*pi*mi + c*pc*mi + o*po*mo)/1000000
          }
          printf "%.2f %d %d\n", cost, n, unmetered
        }'
}

write_cache() {
  local month="$1" cost="$2" unmetered="$3" now tmp
  now="$(date +%s)"
  mkdir -p "$CACHE_DIR" 2>/dev/null || return 0
  tmp="$(mktemp "$CACHE_DIR/.frontier-mtd.XXXXXX" 2>/dev/null)" || return 0
  # NA は裸で書くと不正な JSON になりキャッシュ読み出しが壊れる → 文字列にする
  local cost_json="$cost"
  [ "$cost" = "NA" ] && cost_json='"NA"'
  printf '{"month":"%s","cost":%s,"budget":%s,"unmetered":%s,"ts":%s}\n' \
    "$month" "$cost_json" "$BUDGET" "$unmetered" "$now" > "$tmp" \
    && mv -f "$tmp" "$CACHE" 2>/dev/null || rm -f "$tmp" 2>/dev/null
}

compute_total() {
  local ftoks fcost acost acalls aunmet total
  ftoks="$(aggregate_fable "$MONTH")"
  # shellcheck disable=SC2086
  fcost="$(fable_cost_of $ftoks)"
  read -r acost acalls aunmet <<<"$(aggregate_astra "$MONTH")"
  if [ "$acost" = "NA" ]; then
    # Astra 側が測れない = 合計も信用できない。0 と偽らず NA を伝播する。
    total="NA"
  else
    total="$(awk -v a="$fcost" -v b="$acost" 'BEGIN{ printf "%.2f", a+b }')"
  fi
  echo "$ftoks|$fcost|$acost|$acalls|$aunmet|$total"
}

do_refresh() {
  local r total aunmet
  r="$(compute_total)"
  total="$(echo "$r" | cut -d'|' -f6)"
  aunmet="$(echo "$r" | cut -d'|' -f5)"
  write_cache "$MONTH" "$total" "$aunmet"
  echo "$total"
}

case "$MODE" in
  refresh)
    do_refresh >/dev/null
    ;;

  statusline)
    cost="" cmonth="" cts=0 unmet=0
    if [ -f "$CACHE" ]; then
      cost="$(jq -r '.cost // empty' "$CACHE" 2>/dev/null)"
      cmonth="$(jq -r '.month // empty' "$CACHE" 2>/dev/null)"
      cts="$(jq -r '.ts // 0' "$CACHE" 2>/dev/null)"
      unmet="$(jq -r '.unmetered // 0' "$CACHE" 2>/dev/null)"
    fi
    now="$(date +%s)"
    if [ -z "$cost" ] || [ "$cmonth" != "$MONTH" ] || [ "$(( now - cts ))" -ge "$STALE_SEC" ]; then
      setsid flock -n "$LOCK" bash "$0" --refresh </dev/null >/dev/null 2>&1 9>&- &
    fi
    [ "$cmonth" != "$MONTH" ] && cost=""
    # 第3フィールド: "+" = 未計上の呼び出しあり (表示値は下限) / "?" = そもそも測れていない
    flag="-"; [ "${unmet:-0}" -gt 0 ] 2>/dev/null && flag="+"
    # jq が無ければキャッシュも読めないので、その場で計測不能と分かる
    if ! command -v jq >/dev/null 2>&1 || [ "$cost" = "NA" ]; then
      echo "NA $BUDGET ?"; exit 0
    fi
    if [ -n "$cost" ]; then
      printf '%.0f %.0f %s\n' "$cost" "$BUDGET" "$flag"
    else
      echo "NA $BUDGET -"
    fi
    ;;

  report|*)
    r="$(compute_total)"
    ftoks="$(echo "$r" | cut -d'|' -f1)"
    fcost="$(echo "$r" | cut -d'|' -f2)"
    acost="$(echo "$r" | cut -d'|' -f3)"
    acalls="$(echo "$r" | cut -d'|' -f4)"
    aunmet="$(echo "$r" | cut -d'|' -f5)"
    total="$(echo "$r" | cut -d'|' -f6)"
    read -r i c5 c1 crn cro o <<<"$ftoks"
    cr=$(( crn + cro ))

    [ "$MONTH" = "$(date +%Y-%m)" ] && write_cache "$MONTH" "$total" "$aunmet"
    if [ "$total" = "NA" ]; then
      pct="?"; over=0
    else
      pct="$(awk -v c="$total" -v b="$BUDGET" 'BEGIN{ if ((b+0)>0) printf "%.0f", c/b*100; else printf "0" }')"
      over="$(awk -v c="$total" -v b="$BUDGET" 'BEGIN{ print ((c+0)>(b+0) ? 1 : 0) }')"
    fi

    echo "=== フロンティア層 当月コスト: $MONTH (開発者1人・このマシン) ==="
    echo ""
    echo "  [Claude Fable 5.1]  transcript 実測"
    printf "    input        : %'d tok\n" "$i" 2>/dev/null || printf "    input        : %d tok\n" "$i"
    printf "    cache w (5m) : %'d tok\n" "$c5" 2>/dev/null || printf "    cache w (5m) : %d tok\n" "$c5"
    printf "    cache w (1h) : %'d tok\n" "$c1" 2>/dev/null || printf "    cache w (1h) : %d tok\n" "$c1"
    printf "    cache read   : %'d tok" "$cr" 2>/dev/null || printf "    cache read   : %d tok" "$cr"
    [ "$cro" -gt 0 ] 2>/dev/null && printf "  (うち旧 Fable 5 = %s tok @ \$%s)" "$cro" "$PRICE_CACHE_READ_5"
    echo
    printf "    output       : %'d tok\n" "$o" 2>/dev/null || printf "    output       : %d tok\n" "$o"
    echo "    小計         : \$$fcost"
    echo ""
    echo "  [GPT-6 Astra]  呼び出し台帳 ($ASTRA_LEDGER)"
    echo "    呼び出し     : ${acalls} 回 (うち \$ 未計上 ${aunmet} 回 = トークン不明 or 中断)"
    if [ "$acost" = "NA" ]; then
      echo "    小計         : NA (jq が無く台帳を読めない = 計測不能)"
    else
      echo "    小計         : \$$acost"
    fi
    if [ "${aunmet:-0}" -gt 0 ]; then
      echo "    ⚠️  ${aunmet} 回は \$ に計上されていない (トークン不明、または start だけで end が無い中断)。"
      echo "        実費は表示値より大きい。"
    fi
    echo "  --------------------------------"
    if [ "$total" = "NA" ]; then
      echo "  合計         : NA — 計測不能。0 ではなく「測れていない」という意味。"
    else
      echo "  合計         : \$$total  (予算 \$$BUDGET の ${pct}%)"
    fi
    if [ "$over" = "1" ]; then
      echo "  ⚠️  予算超過。以降のフロンティア委譲は本当に必要か都度確認する (人手ゲート。ブロックはしない)。"
    fi
    echo ""
    echo "  ※ Fable: Max は週次上限の 50% まで included (恒久)。included 消費はローカルから観測できないため"
    echo "     全量課金換算の【上限見積り】(実費 ≤ 表示値)。正は Console: https://console.anthropic.com/settings/usage"
    echo "  ※ Astra: included 枠は無く全量実費。正は https://platform.openai.com/usage"
    echo "  ※ 結果は docs/design/ai-workflow.md §8 に転記する。"
    ;;
esac
