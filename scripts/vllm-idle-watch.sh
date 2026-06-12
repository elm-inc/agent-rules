#!/usr/bin/env bash
# vllm-idle-watch.sh — vLLM が一定時間アイドルなら自動停止し GPU を解放する
#
# ensure-vllm.sh が flock 経由で単一インスタンスとして起動する。手動実行も可。
# 活動量は vLLM の Prometheus メトリクス `vllm:prompt_tokens_total` (単調増加カウンタ) で判定し、
# N 分間変化が無く実行中リクエストも 0 なら `docker stop` する。
# スキル経由でも直接 API でも、全リクエストを取りこぼさず検知できる。
#
# 環境変数:
#   VLLM_PORT=8000  VLLM_IDLE_MINUTES=15 (この分数アイドルで停止)  VLLM_IDLE_POLL=60 (秒)
set -uo pipefail
cd / 2>/dev/null || true   # cwd 由来の事故 (awk リダイレクト等でのゴミファイル生成) を防ぐ

PORT="${VLLM_PORT:-8000}"
METRICS="http://localhost:${PORT}/metrics"
CONTAINER="vllm-qwen-coder"
IDLE_MINUTES="${VLLM_IDLE_MINUTES:-15}"
POLL="${VLLM_IDLE_POLL:-60}"

log() { echo "[$(date '+%F %T')] vllm-idle-watch: $*"; }

# systemd 常駐 (opt-in) 管理下なら停止しない (systemd が再起動して churn するため)
systemd_managed() {
  command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet vllm-qwen-coder 2>/dev/null
}

# prompt_tokens_total の合計 (engine ラベルが複数でも合算)。取得失敗時は前回値維持のため空を返す。
# 該当行を 1 本も拾えなければ空を返す (メトリクス改名・取得失敗時に "0" と誤判定して停止しない fail-safe)。
# m は一致行数。NR (全行数) だと改名時に s=0 のまま "0" を返して使用中でも停止してしまう。
activity() { curl -s -m 5 "$METRICS" 2>/dev/null | awk '/^vllm:prompt_tokens_total/{s+=$2; m++} END{if(m>0)print s+0}'; }
# 実行中リクエストが 1 件でもあれば 1 (括弧で囲まないと awk が `>` を出力リダイレクトと誤解釈する)
running() { curl -s -m 5 "$METRICS" 2>/dev/null | awk '/^vllm:num_requests_running/{s+=$2} END{print ((s+0)>0?1:0)}'; }

prev="$(activity)"
last_active=$(date +%s)
log "監視開始 (idle ${IDLE_MINUTES} 分で停止, poll ${POLL}s)"

while true; do
  sleep "$POLL"

  # コンテナが既に無ければ役目終了
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    log "コンテナ無し → 監視終了"
    exit 0
  fi

  cur="$(activity)"
  # メトリクス取得失敗 (空) は判定をスキップ (誤停止防止)
  if [ -z "$cur" ]; then
    continue
  fi

  if [ "$cur" != "$prev" ] || [ "$(running)" = "1" ]; then
    prev="$cur"
    last_active=$(date +%s)
    continue
  fi

  idle_min=$(( ($(date +%s) - last_active) / 60 ))
  if [ "$idle_min" -ge "$IDLE_MINUTES" ]; then
    # 万一 systemd 常駐に切り替わっていたら停止しない (churn 防止の保険)
    if systemd_managed; then
      log "idle ${idle_min} 分だが systemd 常駐管理下のため停止せず監視終了"
      exit 0
    fi
    log "idle ${idle_min} 分 → vLLM を停止し GPU を解放します"
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    exit 0
  fi
done
