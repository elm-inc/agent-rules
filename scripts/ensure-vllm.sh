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
# 常駐 (opt-in) との共存: systemd の vllm-qwen-coder が active なら、本スクリプトは
# 起動・停止・watcher に一切干渉せず healthy 確認のみ行う (相互 churn を防ぐ)。
#
# Usage:
#   bash ensure-vllm.sh            # 稼働保証 (未稼働なら起動して healthy まで待機)
#   bash ensure-vllm.sh stop       # 即時停止 (GPU 解放)
#   bash ensure-vllm.sh status     # running / stopped を表示
#
# 終了コード (up): 0=稼働中, 1=起動失敗(GPU競合等), 2 は内部用 (呼び出し側には 1 を返す)
#
# 主な環境変数 (デフォルトは常駐運用と同一設定):
#   VLLM_PORT=8000  VLLM_MODEL=RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic
#   VLLM_SERVED_NAME=qwen-coder  VLLM_MAX_LEN=4096  VLLM_GPU_MEM_UTIL=0.88
#   VLLM_CPU_OFFLOAD_GB=6  VLLM_HF_CACHE=$HOME/.cache/huggingface
#   VLLM_START_TIMEOUT=300 (秒)  VLLM_IDLE_MINUTES=15  VLLM_IDLE_POLL=60 (watcher へ継承)
#   VLLM_IMAGE=vllm/vllm-openai:latest  ← 安定運用では版を pin 推奨 (例 :v0.21.0)。
#     :latest のままでもメトリクス改名で watcher が誤停止しないよう idle-watch 側は fail-safe。
set -uo pipefail

PORT="${VLLM_PORT:-8000}"
BASE_URL="http://localhost:${PORT}/v1"
CONTAINER="vllm-qwen-coder"
IMAGE="${VLLM_IMAGE:-vllm/vllm-openai:latest}"
MODEL="${VLLM_MODEL:-RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic}"
SERVED_NAME="${VLLM_SERVED_NAME:-qwen-coder}"
MAX_LEN="${VLLM_MAX_LEN:-4096}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.88}"
CPU_OFFLOAD_GB="${VLLM_CPU_OFFLOAD_GB:-6}"
HF_CACHE="${VLLM_HF_CACHE:-$HOME/.cache/huggingface}"
START_TIMEOUT="${VLLM_START_TIMEOUT:-300}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCH="${SCRIPT_DIR}/vllm-idle-watch.sh"
WATCH_LOCK="/tmp/vllm-idle-watch.lock"   # /tmp 固定 (TMPDIR 変動で単一化が破れるのを防ぐ)
WATCH_LOG="/tmp/vllm-idle-watch.log"
START_LOCK="/tmp/vllm-ensure-start.lock"
LEASE="/tmp/vllm-last-ensure"            # up 呼び出し=直近の利用意図。watcher が idle タイマーに反映 (TOCTOU 緩和)

log() { echo "[ensure-vllm] $*" >&2; }
healthy() { curl -sf -m 5 "${BASE_URL}/models" >/dev/null 2>&1; }

# systemd 常駐 (opt-in) 管理下か。read-only、sudo 不要。
systemd_managed() {
  command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet vllm-qwen-coder 2>/dev/null
}

# アイドル監視を 1 つだけ常駐させる (flock -n で多重起動防止、setsid で完全デタッチ)。
# 9>&- で親の起動ロック (START_LOCK) を子に継承させない。watcher 不在は警告する。
start_watcher() {
  if [ ! -x "$WATCH" ]; then
    log "WARN: watcher 不在 ($WATCH)。アイドル自動停止が効きません"
    return 0
  fi
  if command -v setsid >/dev/null 2>&1; then
    setsid flock -n "$WATCH_LOCK" bash "$WATCH" </dev/null >>"$WATCH_LOG" 2>&1 9>&- &
  else
    nohup flock -n "$WATCH_LOCK" bash "$WATCH" </dev/null >>"$WATCH_LOG" 2>&1 9>&- &
  fi
  disown 2>/dev/null || true
}

case "${1:-up}" in
  stop)
    if systemd_managed; then
      log "systemd 常駐管理下です。停止は: sudo systemctl stop vllm-qwen-coder"
      exit 0
    fi
    log "vLLM を停止します..."
    if docker stop "$CONTAINER" >/dev/null 2>&1; then log "停止しました (GPU 解放)"; else log "稼働していません"; fi
    exit 0
    ;;
  status)
    if systemd_managed; then echo "running (systemd 常駐, ${BASE_URL})"
    elif healthy; then echo "running (${BASE_URL})"
    else echo "stopped"; fi
    exit 0
    ;;
esac

# --- up (デフォルト): 稼働保証 ---

# up が呼ばれた = スキルが直後に推論する意図。watcher の idle 停止判定に効かせ、
# healthy→exit 直後に watcher が docker stop する TOCTOU 窓を塞ぐ (M-3)。
touch "$LEASE" 2>/dev/null || true

# systemd 常駐管理下: 起動・停止・watcher に干渉せず healthy 確認のみ
if systemd_managed; then
  healthy && exit 0
  log "systemd 常駐がロード中… healthy を待機 (最大 ${START_TIMEOUT}s)"
  sd_deadline=$(( $(date +%s) + START_TIMEOUT ))
  while ! healthy; do
    if [ "$(date +%s)" -ge "$sd_deadline" ]; then
      log "ERROR: systemd 常駐 vLLM が healthy になりません。'systemctl status vllm-qwen-coder' を確認"
      exit 1
    fi
    sleep 5
  done
  exit 0
fi

# 既に稼働中なら watcher の生存だけ保証して終了
if healthy; then
  start_watcher
  exit 0
fi

# cold-start を flock で直列化 (worktree 並列で同時起動しても殺し合わない)。
# ロック取得後に再 healthy チェックし、待機中に別プロセスが起動済みなら相乗りする。
(
  if ! flock -w "$START_TIMEOUT" 9; then
    log "ERROR: 起動ロックを ${START_TIMEOUT}s 以内に取得できませんでした"
    exit 1
  fi
  healthy && exit 0

  log "vLLM 未稼働 → 起動します (初回モデルロードに 1-2 分)"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true   # 異常終了で残ったコンテナを掃除

  if ! docker run -d \
      --name "$CONTAINER" \
      --gpus all --ipc=host \
      -p "${PORT}:8000" \
      -v "${HF_CACHE}:/root/.cache/huggingface" \
      ${HUGGING_FACE_HUB_TOKEN:+-e HUGGING_FACE_HUB_TOKEN="$HUGGING_FACE_HUB_TOKEN"} \
      -e HF_HUB_ENABLE_HF_TRANSFER=1 \
      -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
      "$IMAGE" \
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
      docker logs --tail 30 "$CONTAINER" >&2 2>/dev/null || true   # --rm を外したのでログが残る
      exit 1
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
      log "${START_TIMEOUT}s 以内に healthy になりませんでした (初回 18GB DL や低速ロードの可能性)"
      exit 2   # まだロード中かもしれない → 呼び出し側で watcher を立てる
    fi
    sleep 5
  done
  exit 0
) 9>"$START_LOCK"
rc=$?

case "$rc" in
  0)
    log "起動完了 (${BASE_URL})。アイドル時は自動停止します (VLLM_IDLE_MINUTES=${VLLM_IDLE_MINUTES:-15})"
    start_watcher
    exit 0
    ;;
  2)
    # まだロード中: watcher を立てて GPU を放置しない (未使用ならアイドル後に自動停止)
    start_watcher
    log "バックグラウンドでロード継続中。'ensure-vllm.sh status' で確認 / 'stop' で中止できます。初回 DL は docs/setup/local-llm.md の手動起動推奨"
    exit 1
    ;;
  *)
    exit 1
    ;;
esac
