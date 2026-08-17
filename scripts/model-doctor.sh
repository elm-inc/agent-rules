#!/usr/bin/env bash
# model-doctor.sh — モデル ID の健全性を機械検証する (根拠: ADR-0017)
#
# 背景: deepseek-reasoner (R1) が 2026-07-24 に退役したのに、ID が
#       skills/deepseek-redteam/SKILL.md へ直接埋まっていたため 3 週間検知できなかった。
#       「ベンダーは黙ってモデルを消す」を前提に、2 種類の検査を機械化する。
#
#   --drift  (API キー不要 / CI 向け)
#       operational surface (CLAUDE.md skills/ scripts/ agents/) に現れるモデル ID が
#       すべて config/models.yml の active に登録されているか。退役 ID が残っていないか。
#
#   --probe  (API キー必要 / ローカル向け)
#       active の各 ID がベンダー API に実在するか。退役予定日が近いものを警告する。
#
# Usage:
#   bash scripts/model-doctor.sh            # --drift + --probe (キーがある分だけ)
#   bash scripts/model-doctor.sh --drift    # 静的検査のみ (CI)
#   bash scripts/model-doctor.sh --probe    # 疎通確認のみ
#
# 終了コード: 0=健全, 1=要対応 (drift or 実在しない ID)

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEDGER="${REPO_ROOT}/config/models.yml"

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; DIM=$'\033[2m'; RST=$'\033[0m'
ok()   { echo "  ${GRN}✓${RST} $*"; PROBED=$(( ${PROBED:-0} + 1 )); }
warn() { echo "  ${YEL}!${RST} $*"; }
fail() { echo "  ${RED}✗${RST} $*"; RC=1; }
RC=0

[ -f "$LEDGER" ] || { echo "${RED}ERROR${RST}: 台帳が見つかりません: $LEDGER"; exit 1; }

MODE="${1:-all}"

# --- 台帳の読み出し (PyYAML) ---------------------------------------------
ledger() { python3 -c "
import sys, yaml
d = yaml.safe_load(open('$LEDGER'))
$1
"; }

# --- 1. drift 検査 (静的・キー不要) --------------------------------------
run_drift() {
  echo "== drift 検査 (operational surface vs 台帳) =="

  # 台帳の active / retired ID
  local active retired
  active="$(ledger "print('\n'.join(m['id'] for m in d['active'] if m.get('id')))")"
  retired="$(ledger "print('\n'.join(m['id'] for m in d['retired']))")"

  # 走査対象: 実際に実行されるもの。docs/ は履歴として旧 ID を書いてよいので除外。
  local targets=(CLAUDE.md RULES.md AGENTS.md skills scripts agents templates plugins prompts .github)
  local scan=()
  for t in "${targets[@]}"; do [ -e "${REPO_ROOT}/$t" ] && scan+=("${REPO_ROOT}/$t"); done

  # モデル ID らしき文字列だけを狙い撃つ (skill 名 "deepseek-redteam" 等を拾わない)
  # HF org は vllm-verify-model.sh の許可 org を必ず包含すること
  # (許可したのにパターンに無い = 検査されない、という穴を作らない)
  local hf_orgs='RedHatAI|Qwen|nvidia|mistralai|google|meta-llama|deepseek-ai|cyankiwi|unsloth|lmstudio-community|mlx-community|zai-org'
  local pattern="claude-(opus|sonnet|haiku|fable|mythos)-[0-9][a-zA-Z0-9.-]*|deepseek-(reasoner|chat|v[0-9][a-zA-Z0-9.-]*)|gemini-[0-9][a-zA-Z0-9.-]*|gpt-[0-9][a-zA-Z0-9.-]*|(${hf_orgs})/[A-Za-z0-9._-]+"


  # 除外: 台帳そのものと、パターン定義を持つ本スクリプト (自己言及で誤検知するため)
  local excludes=(--exclude-dir=.git --exclude=models.yml --exclude=model-doctor.sh)

  # 「退役したので使うな」と散文で書いている行まで落とさないための逃がし弁。
  # 行内に model-doctor:allow があればその行は検査対象外にする。
  # 暗黙に許す仕組みにはせず、書いた人が意識してマークすることを要求する。
  local found
  found="$(grep -rhE "$pattern" "${scan[@]}" 2>/dev/null "${excludes[@]}" \
          | grep -v 'model-doctor:allow' \
          | grep -oE "$pattern" \
          | sed 's/[.,)"'"'"'`]*$//' | sort -u)"

  # fail-close: 0 件は「健全」ではなく「検査が壊れた」と解釈する。
  # パターン陳腐化・走査対象ミスを green にしてしまうと検知機構の意味が無い。
  if [ -z "$found" ]; then
    fail "モデル ID が 1 つも検出できませんでした。パターンか走査対象が壊れている可能性があります"
    return
  fi

  local unknown=0
  while IFS= read -r id; do
    [ -n "$id" ] || continue
    if grep -qxF "$id" <<<"$retired"; then
      fail "退役/移行済みの ID が残っています: ${id}"
      grep -rnE "(^|[^a-zA-Z0-9.-])${id//./\\.}([^a-zA-Z0-9.-]|$)" "${scan[@]}" 2>/dev/null \
        "${excludes[@]}" | grep -v 'model-doctor:allow' \
        | cut -d: -f1-2 | sort -u | sed "s|${REPO_ROOT}/|      → |"
      unknown=1
    elif ! grep -qxF "$id" <<<"$active"; then
      fail "台帳に未登録の ID: ${id} (config/models.yml の active に足すか、使用をやめてください)"
      unknown=1
    fi
  done <<<"$found"

  [ "$unknown" -eq 0 ] && ok "検出した ID はすべて台帳の active に登録済み ($(wc -l <<<"$found") 件)"
}

# --- 2. 疎通確認 (ベンダー API に実在するか) ------------------------------
read_token() {  # $1=token_file
  local f="${1/#\~/$HOME}"
  [ -f "$f" ] && cat "$f" || echo ""
}

probe_vendor() {  # $1=vendor  $2..=期待する ID 群
  local vendor="$1"; shift
  local ids=("$@")
  local url token auth extra jqids
  url="$(ledger "print(d['probes']['$vendor']['url'])")"
  token="$(read_token "$(ledger "print(d['probes']['$vendor']['token_file'])")")"
  auth="$(ledger "print(d['probes']['$vendor']['auth'])")"
  extra="$(ledger "print(d['probes']['$vendor'].get('extra_header',''))")"
  jqids="$(ledger "print(d['probes']['$vendor']['jq_ids'])")"

  if [ -z "$token" ] && [ "$auth" != "bearer_optional" ]; then
    warn "${vendor}: トークン未設定 → skip"
    return
  fi

  # HuggingFace はモデル単位でしか引けないので個別に叩く
  if [ "$vendor" = "huggingface" ]; then
    for id in "${ids[@]}"; do
      if curl -sf -m 20 "${url}${id}" ${token:+-H "Authorization: Bearer $token"} >/dev/null 2>&1; then
        ok "huggingface: ${id}"
      else
        fail "huggingface: ${id} が取得できません (リポジトリ名の誤り or 非公開)"
      fi
    done
    return
  fi

  local resp
  case "$auth" in
    bearer)    resp="$(curl -sf -m 25 "$url" -H "Authorization: Bearer $token" 2>/dev/null)" ;;
    x-api-key) resp="$(curl -sf -m 25 "$url" -H "x-api-key: $token" ${extra:+-H "$extra"} 2>/dev/null)" ;;
    query_key) resp="$(curl -sf -m 25 "${url}?key=${token}" 2>/dev/null)" ;;
    *)         warn "${vendor}: 未知の auth 方式 '${auth}' → skip"; return ;;
  esac

  if [ -z "$resp" ]; then
    warn "${vendor}: モデル一覧を取得できません (キー無効 or ネットワーク) → skip"
    return
  fi

  local upstream
  upstream="$(jq -r "$jqids" <<<"$resp" 2>/dev/null | sort -u)"
  for id in "${ids[@]}"; do
    if grep -qxF "$id" <<<"$upstream"; then
      ok "${vendor}: ${id}"
    else
      fail "${vendor}: ${id} は上流に存在しません → 退役の可能性。config/models.yml を更新してください"
      echo "${DIM}      上流の候補: $(grep -iE "$(cut -d- -f1-2 <<<"$id")" <<<"$upstream" | head -4 | tr '\n' ' ')${RST}"
    fi
  done
}

run_probe() {
  echo
  echo "== 疎通確認 (台帳の active が上流に実在するか) =="
  PROBED=0
  local vendors
  vendors="$(ledger "print('\n'.join(sorted({m['vendor'] for m in d['active'] if m.get('id')})))")"
  while IFS= read -r v; do
    [ -n "$v" ] || continue
    # alias を持つものは upstream_id (dated ID 等) で実在確認する
    mapfile -t ids < <(ledger "print('\n'.join(m.get('upstream_id') or m['id'] for m in d['active'] if m.get('id') and m['vendor']=='$v'))")
    probe_vendor "$v" "${ids[@]}"
  done <<<"$vendors"

  # 1 つも実際に確認できていないなら「健全」と言ってはいけない
  if [ "${PROBED:-0}" -eq 0 ]; then
    fail "どのベンダーにも到達できませんでした (キー未設定 or ネットワーク)。疎通確認は成立していません"
  fi

  # 退役予定日が 90 日以内のものを警告
  echo
  echo "== 退役予定 =="
  ledger "
import datetime
today = datetime.date.today()
hit = False
for m in d['retired']:
    when = m.get('retires_on')
    if not when: continue
    left = (when - today).days
    hit = True
    mark = '!' if left <= 90 else ' '
    print(f'  {mark} {m[\"id\"]}: {when} 退役予定 (残り {left} 日) → {m[\"successor\"]}')
if not hit: print('  (期限付きの退役予定なし)')
"
}

echo "model-doctor — 台帳: ${DIM}${LEDGER#$REPO_ROOT/}${RST} (updated: $(ledger "print(d['updated'])"))"
echo
case "$MODE" in
  --drift) run_drift ;;
  --probe) run_probe ;;
  all|--all) run_drift; run_probe ;;
  *) echo "usage: $0 [--drift|--probe|--all]"; exit 2 ;;
esac

echo
if [ "$RC" -eq 0 ]; then echo "${GRN}健全です${RST}"; else echo "${RED}要対応の項目があります${RST}"; fi
exit "$RC"
