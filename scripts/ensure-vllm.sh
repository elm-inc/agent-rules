#!/usr/bin/env bash
# ensure-vllm.sh — vLLM をオンデマンド起動する (常駐をやめ、ローカル LLM スキル呼び出し時だけ立ち上げる)
#
# 目的: GPU を普段は解放しておき、/local-review /test-generate /test-data などが
#       必要とした時だけ vLLM を起動する。起動後はアイドル監視 (vllm-idle-watch.sh) を
#       1 つ常駐させ、一定時間使われなければ自動停止して GPU を解放する。
#
# sudo 不要 (elmo は docker グループ所属)。常駐 systemd 方式からの移行は
# `sudo systemctl disable --now vllm-qwen-coder` を一度だけ実行する。
#
# Usage:
#   bash ensure-vllm.sh            # 稼働保証 (未稼働なら起動して healthy まで待機)
#   bash ensure-vllm.sh stop       # 即時停止 (GPU 解放)
#   bash ensure-vllm.sh status     # running / stopped を表示
#
# 主な環境変数 (デフォルトは常駐運用と同一設定):
#   VLLM_PORT=8000  VLLM_MODEL=RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic
#   VLLM_MAX_LEN=4096  VLLM_GPU_MEM_UTIL=0.88  VLLM_CPU_OFFLOAD_GB=6
#   VLLM_HF_CACHE=$HOME/.cache/huggingface  VLLM_START_TIMEOUT=300 (秒)
#   VLLM_IDLE_MINUTES=15 (アイドル監視へ引き継ぐ)
set -uo pipefail

PORT="${VLLM_PORT:-8000}"
BASE_URL="http://localhost:${PORT}/v1"
CONTAINER="vllm-qwen-coder"
MODEL="${VLLM_MODEL:-RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic}"
SERVED_NAME="${VLLM_SERVED_NAME:-qwen-coder}"
MAX_LEN="${VLLM_MAX_LEN:-4096}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.88}"
CPU_OFFLOAD_GB="${VLLM_CPU_OFFLOAD_GB:-6}"
HF_CACHE="${VLLM_HF_CACHE:-$HOME/.cache/huggingface}"
START_TIMEOUT="${VLLM_START_TIMEOUT:-300}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCH="${SCRIPT_DIR}/vllm-idle-watch.sh"
WATCH_LOCK="${TMPDIR:-/tmp}/vllm-idle-watch.lock"
WATCH_LOG="${TMPDIR:-/tmp}/vllm-idle-watch.log"

log() { echo "[ensure-vllm] $*" >&2; }
healthy() { curl -sf -m 5 "${BASE_URL}/models" >/dev/null 2>&1; }

# アイドル監視を 1 つだけ常駐させる (flock -n で多重起動防止、setsid で完全デタッチ)。
# 既存の watcher が生きていれば flock が即失敗して何も起動しない (self-healing: 死んでいれば再起動)。
start_watcher() {
  [ -x "$WATCH" ] || return 0
  local launcher="exec flock -n '$WATCH_LOCK' bash '$WATCH'"
  if command -v setsid >/dev/null 2>&1; then
    setsid bash -c "$launcher" </dev/null >>"$WATCH_LOG" 2>&1 &
  else
    nohup bash -c "$launcher" </dev/null >>"$WATCH_LOG" 2>&1 &
  fi
  disown 2>/dev/null || true
}

case "${1:-up}" in
  stop)
    log "vLLM を停止します..."
    if docker stop "$CONTAINER" >/dev/null 2>&1; then log "停止しました (GPU 解放)"; else log "稼働していません"; fi
    exit 0
    ;;
  status)
    if healthy; then echo "running (${BASE_URL})"; else echo "stopped"; fi
    exit 0
    ;;
esac

# --- up (デフォルト): 稼働保証 ---
if healthy; then
  start_watcher
  exit 0
fi

log "vLLM 未稼働 → 起動します (初回モデルロードに 1-2 分)"

# 異常終了で残ったコンテナを掃除 (--rm でも残ることがある)
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

if ! docker run -d --rm \
    --name "$CONTAINER" \
    --gpus all --ipc=host \
    -p "${PORT}:8000" \
    -v "${HF_CACHE}:/root/.cache/huggingface" \
    ${HUGGING_FACE_HUB_TOKEN:+-e HUGGING_FACE_HUB_TOKEN="$HUGGING_FACE_HUB_TOKEN"} \
    -e HF_HUB_ENABLE_HF_TRANSFER=1 \
    -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    vllm/vllm-openai:latest \
    --model "$MODEL" \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    ${CPU_OFFLOAD_GB:+--cpu-offload-gb "$CPU_OFFLOAD_GB"} \
    --enforce-eager \
    --served-model-name "$SERVED_NAME" >/dev/null; then
  log "ERROR: docker run に失敗しました (GPU が他プロセスで使用中の可能性)。nvidia-smi で確認してください"
  exit 1
fi

deadline=$(( $(date +%s) + START_TIMEOUT ))
while ! healthy; do
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    log "ERROR: コンテナが異常終了しました。直近ログ:"
    docker logs --tail 30 "$CONTAINER" >&2 2>/dev/null || true
    exit 1
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    log "ERROR: ${START_TIMEOUT}s 以内に起動完了しませんでした。直近ログ:"
    docker logs --tail 30 "$CONTAINER" >&2 2>/dev/null || true
    exit 1
  fi
  sleep 5
done

log "起動完了 (${BASE_URL})。アイドル時は自動停止します (VLLM_IDLE_MINUTES=${VLLM_IDLE_MINUTES:-15})"
start_watcher
exit 0
