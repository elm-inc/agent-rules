#!/usr/bin/env bash
# vllm-healthcheck.sh — 常駐 vLLM の死活監視 (cron / systemd timer 用)
#
# 異常検知時の通知経路はユーザー設定次第:
#   - ntfy.sh: NTFY_TOPIC=elmo-claude-XXXXX を環境変数で指定
#   - その他: WEBHOOK_URL を指定 (任意の JSON POST)
#   - いずれも未設定なら stderr に出すのみ (cron がメール送る前提)
#
# Usage:
#   bash vllm-healthcheck.sh                  # 単発チェック
#   */5 * * * * /path/to/vllm-healthcheck.sh  # cron で 5 分おき

set -uo pipefail

URL="${VLLM_HEALTH_URL:-http://localhost:8000/v1/models}"
TIMEOUT="${VLLM_HEALTH_TIMEOUT:-5}"

notify() {
  local msg="$1"
  echo "[$(date '+%F %T')] $msg" >&2

  if [ -n "${NTFY_TOPIC:-}" ]; then
    curl -sf -m 5 -d "$msg" "https://ntfy.sh/$NTFY_TOPIC" > /dev/null || true
  fi

  if [ -n "${WEBHOOK_URL:-}" ]; then
    curl -sf -m 5 -H 'Content-Type: application/json' \
      -d "$(jq -n --arg m "$msg" '{text:$m, source:"vllm-healthcheck"}')" \
      "$WEBHOOK_URL" > /dev/null || true
  fi
}

if curl -sf -m "$TIMEOUT" "$URL" > /dev/null; then
  # healthy — quiet
  exit 0
fi

# unhealthy
HOST=$(hostname)
notify "vLLM unhealthy on $HOST: $URL (timeout ${TIMEOUT}s)"

# GPU 状態も付け加えて通知 (二度押し許容)
if command -v nvidia-smi > /dev/null; then
  GPU=$(nvidia-smi --query-gpu=memory.used,memory.free,utilization.gpu --format=csv,noheader 2>&1 | head -1)
  notify "  GPU: $GPU"
fi

exit 1
