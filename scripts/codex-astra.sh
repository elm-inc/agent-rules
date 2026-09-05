#!/usr/bin/env bash
# Codex CLI を GPT-6 Astra で起動し、呼び出しを【フロンティア枠の台帳】に記録する薄いラッパ。
#
# なぜラッパが要るか:
#   Astra は Fable と同額 ($10/$50 per MTok) の実費だが、Codex CLI は別プロセスで走るため
#   Claude Code の transcript に残らない。OpenAI の usage/costs API は admin scope
#   (api.usage.read) が必要で通常の sk-proj- キーでは 403 (2026-09-06 実測)。
#   → 「呼んだこと」だけでもローカルに残さないと、フロンティア枠の計器に穴が空く。
#      トークン数が出力から拾えればそれも記録し、拾えなければ null にして
#      frontier-usage.sh 側で「未計上」として明示する (0 と偽らない)。
#
# 使い方 (codex にそのまま渡る):
#   ./scripts/codex-astra.sh review --base main
#   ./scripts/codex-astra.sh exec --sandbox read-only "..."
#
# 根拠: docs/adr/0019-frontier-tier-orchestration.md

set -uo pipefail

MODEL="gpt-6-astra"
MIN_VERSION="0.153.0"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/agent-rules"
LEDGER="${ASTRA_LEDGER:-$CACHE_DIR/frontier-astra.jsonl}"

command -v codex >/dev/null 2>&1 || { echo "codex CLI が見つかりません" >&2; exit 127; }

# --- バージョンゲート ------------------------------------------------------
# 0.149.1 は Astra を server-side で拒否する (400 "requires a newer version of Codex")。
# 不親切な 400 で失敗するより先に、原因が分かる形で止める。
raw_ver="$(codex --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)"
# sort -V (GNU 拡張) が無い環境では**ゲートを諦めて先へ進む**。
# ここで fail-closed にすると、Codex が十分新しいのに「バージョン不足」と誤って止まり、
# 利用者がラッパを迂回して素の codex を直接叩く動機を作ってしまう (台帳に載らなくなる)。
# 判定できないときは server 側の 400 に委ねる方が実害が小さい。
sortv_ok=1
printf '1.0.0\n1.0.1\n' | sort -V >/dev/null 2>&1 || sortv_ok=0
if [ -n "$raw_ver" ] && [ "$sortv_ok" = "1" ]; then
  lowest="$(printf '%s\n%s\n' "$raw_ver" "$MIN_VERSION" | sort -V | head -1)"
  if [ "$lowest" != "$MIN_VERSION" ] && [ "$raw_ver" != "$MIN_VERSION" ]; then
    cat >&2 <<MSG
Codex CLI $raw_ver は GPT-6 Astra を使えません ($MIN_VERSION 以上が必要)。
  sudo npm install -g @openai/codex@latest
で更新してください。Sol での通常レビューは /codex-review が使えます。
MSG
    exit 3
  fi
fi

[ "$#" -gt 0 ] || { echo "usage: $0 <codex サブコマンドと引数>" >&2; exit 2; }

mkdir -p "$CACHE_DIR" 2>/dev/null || { echo "台帳ディレクトリを作成できません: $CACHE_DIR" >&2; exit 1; }
out_tmp="$(mktemp "${TMPDIR:-/tmp}/codex-astra.XXXXXX")" || exit 1
trap 'rm -f "$out_tmp"' EXIT

CALL_ID="$(date +%s)-$$"

# --- 起動許可ゲート: 【呼ぶ前に】start 行を書く ----------------------------
# 終了後にしか記録しないと、Ctrl-C・クラッシュ・スリープで中断した呼び出しが
# 「OpenAI には課金されたのに台帳に無い」状態になる (計測を回避する最も簡単な経路にもなる)。
# start を先に書けば、end が付かなかった呼び出しも【中断】として必ず可視化できる。
# 台帳に書けない場合は Codex を起動しない — 計器に載らない実費を作らないため。
if ! printf '{"ts":%s,"month":"%s","model":"%s","id":"%s","phase":"start"}\n' \
      "$(date +%s)" "$(date +%Y-%m)" "$MODEL" "$CALL_ID" >> "$LEDGER" 2>/dev/null; then
  echo "台帳に書き込めないため中止します: $LEDGER" >&2
  echo "(計器に載らない実費を作らないための fail-closed です)" >&2
  exit 4
fi

# --- 実行 (出力はユーザーに見せつつ控えも取る) -----------------------------
set -o pipefail
codex --model "$MODEL" "$@" 2>&1 | tee "$out_tmp"
rc="${PIPESTATUS[0]}"

# --- トークン数の抽出 (権威ある turn.completed の usage のみ) ----------------
# Codex は `--json` を付けたとき、ターン終了時に正確な usage を出す:
#   {"type":"turn.completed","usage":{"input_tokens":N,"cached_input_tokens":N,
#                                     "cache_write_input_tokens":N,"output_tokens":N,...}}
#
# **ヒューリスティックな抽出は行わない。** 以前は出力から "input ... 数字" を正規表現で
# 拾っていたが、初回の実走で **レビュー本文中の散文 (`output=0`) を拾って 0 を記録**した。
# 誤った数字は null より悪い — 未計上として警告されず「計測済み $0」に化けるため。
# よって「turn.completed の usage が取れたか / 取れなかったか」の二値に倒す。
#
# 制約 (ADR-0019 に記録): `codex review` には --json が無いため、
# **レビュー経路は構造的に計測できない**。その場合は null = 未計上として正直に扱う。
extract_usage() {
  local field="$1"
  # 複数ターンあり得るので合算する。jq が無ければ諦める (推測しない)。
  command -v jq >/dev/null 2>&1 || return 1
  local v
  v="$(grep -h '"type":"turn.completed"' "$out_tmp" 2>/dev/null \
       | jq -s --arg f "$field" '[ .[] | .usage[$f] // empty ] | add // empty' 2>/dev/null)"
  [ -n "$v" ] && [ "$v" != "null" ] && { echo "$v"; return 0; }
  return 1
}

in_tok="$(extract_usage 'input_tokens' || true)"
cached_tok="$(extract_usage 'cached_input_tokens' || true)"
out_tok="$(extract_usage 'output_tokens' || true)"

jnum() { if [ -n "${1:-}" ]; then printf '%s' "$1"; else printf 'null'; fi; }

printf '{"ts":%s,"month":"%s","model":"%s","id":"%s","phase":"end","input":%s,"cached":%s,"output":%s,"rc":%s}\n' \
  "$(date +%s)" "$(date +%Y-%m)" "$MODEL" "$CALL_ID" \
  "$(jnum "$in_tok")" "$(jnum "$cached_tok")" "$(jnum "$out_tok")" "$rc" \
  >> "$LEDGER"

if [ -z "$in_tok" ] || [ -z "$out_tok" ]; then
  echo "" >&2
  echo "note: この呼び出しのトークン数は記録できませんでした (台帳では【未計上】扱い)。" >&2
  echo "      Codex は --json を付けたときだけ正確な usage を出します。" >&2
  echo "      \`codex review\` には --json が無いため、レビュー経路は構造的に計測できません。" >&2
  echo "      実費の正は https://platform.openai.com/usage を参照してください。" >&2
fi

exit "$rc"
