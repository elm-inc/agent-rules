#!/usr/bin/env bash
# Claude Code ステータスライン
# 表示: モデル · effort · context% · Max 使用率 (5h / 7d, 閾値で色変え) · vLLM 稼働 · git ブランチ
#
# Claude Code が stdin に JSON (model / effort / context_window / rate_limits / workspace …) を流す。
# jq で抽出し、1 行に整形して stdout へ。色付けは ANSI。閾値: <50 緑 / 50-79 黄 / >=80 赤。
#
# 登録 (ローカルの ~/.claude/settings.json、既存設定にマージ):
#   { "statusLine": { "type": "command",
#       "command": "~/repos/github.com/elm-inc/agent-rules/scripts/statusline.sh" } }
#
# 注: rate_limits は Claude.ai サブスク (Pro/Max) で最初の API 応答後に入る。未取得時は "--"。

input=$(cat)
j() { jq -r "$1 // empty" <<<"$input" 2>/dev/null; }

model=$(j '.model.display_name'); [ -z "$model" ] && model=$(j '.model.id'); [ -z "$model" ] && model='?'
effort=$(j '.effort.level')
ctx=$(j '.context_window.used_percentage')
five=$(j '.rate_limits.five_hour.used_percentage')
seven=$(j '.rate_limits.seven_day.used_percentage')
cwd=$(j '.workspace.current_dir'); [ -z "$cwd" ] && cwd=$(j '.cwd')
branch=$(git -C "${cwd:-.}" rev-parse --abbrev-ref HEAD 2>/dev/null)

RST=$'\e[0m'; DIM=$'\e[2m'; CY=$'\e[36m'
GRN=$'\e[32m'; YEL=$'\e[33m'; RED=$'\e[31m'

# パーセント (小数可) を閾値で色付け。空なら淡色の "--"。
colpct() {
  local v="$1" n c
  [ -z "$v" ] && { printf '%s--%s' "$DIM" "$RST"; return; }
  n=${v%.*}; [ -z "$n" ] && n=0
  if   [ "$n" -ge 80 ]; then c="$RED"
  elif [ "$n" -ge 50 ]; then c="$YEL"
  else                        c="$GRN"; fi
  printf '%s%s%%%s' "$c" "$n" "$RST"
}

# vLLM 稼働状態 (localhost:VLLM_PORT/v1/models へ軽量チェック。短タイムアウトでステータスラインを遅延させない。
# 停止時は接続拒否で即返る)。稼働=緑●, 停止=淡色○。
vport="${VLLM_PORT:-8000}"
if curl -sf -m 1 "http://localhost:${vport}/v1/models" >/dev/null 2>&1; then
  vllm="${GRN}vLLM●${RST}"
else
  vllm="${DIM}vLLM○${RST}"
fi

S="${DIM} · ${RST}"
out="${CY}${model}${RST}"
[ -n "$effort" ] && out="${out}${S}effort:${effort}"
if [ -n "$ctx" ]; then out="${out}${S}ctx ${ctx%.*}%"; else out="${out}${S}ctx ${DIM}--%${RST}"; fi
out="${out}${S}5h $(colpct "$five")${DIM} / ${RST}7d $(colpct "$seven")"
out="${out}${S}${vllm}"

# フロンティア層 (Fable 5.1 + GPT-6 Astra) の当月実費。frontier-usage.sh がキャッシュから
# 即返す (重い走査は裏で throttle)。当月使っていなければ (実費 0) 表示しない — 平時は汚さない。
# 第3フィールド: "+" = 未計上の呼び出しがあり表示値は【下限】 / "?" = そもそも計測不能。
fu="$(dirname "${BASH_SOURCE[0]}")/frontier-usage.sh"
[ -x "$fu" ] || fu="$HOME/repos/github.com/elm-inc/agent-rules/scripts/frontier-usage.sh"
if [ -x "$fu" ]; then
  read -r fcost fbudget fflag < <("$fu" --statusline 2>/dev/null)
  # "?" = 計測不能。**黙って隠すと「今月は使っていない」と区別が付かない**ので明示する
  # (計器が壊れていることを 0 と誤読させない — ADR-0019 のレッドチーム指摘)
  if [ "${fflag:--}" = "?" ]; then
    out="${out}${S}🧠FR ${YEL}?${RST}"
  elif [ -n "${fcost:-}" ] && [ "$fcost" != "NA" ] \
       && { [ "${fcost:-0}" -gt 0 ] 2>/dev/null || [ "${fflag:--}" = "+" ]; }; then
    fpct=0; [ "${fbudget:-0}" -gt 0 ] 2>/dev/null && fpct=$(( fcost * 100 / fbudget ))
    if   [ "$fpct" -ge 100 ]; then fc="$RED"
    elif [ "$fpct" -ge 70 ];  then fc="$YEL"
    else                           fc="$GRN"; fi
    fmark=""; [ "${fflag:--}" = "+" ] && fmark="+"
    out="${out}${S}🧠FR ${fc}\$${fcost}${fmark}${RST}${DIM}/${fbudget}${RST}"
  fi
fi

[ -n "$branch" ] && out="${out}${S}⎇ ${branch}"

printf '%s\n' "$out"
