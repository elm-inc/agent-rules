#!/usr/bin/env bash
# vllm-swap-to.sh — A 案 (swap 方式) の補助スクリプト
#
# ADR-0002 採択 / Phase 1 ベンチで 32GB VRAM では複数モデル同時ロード不可と判明。
# このスクリプトは主力 vllm-qwen-coder (32B FP8) を一時停止し、指定モデルを :8001
# で起動、終了後に主力を復帰させる。`/test-generate --brainstorm --with-distill`
# や手動レッドチームから呼び出す想定。
# 復帰はオンデマンド既定 (ADR-0005) に合わせ ensure-vllm.sh 経由 (docker start ではない)。
#
# Usage:
#   bash vllm-swap-to.sh distill      # DeepSeek-R1-Distill-Qwen-14B (online FP8)
#   bash vllm-swap-to.sh coder-14b    # Qwen-Coder-14B AWQ INT4
#   bash vllm-swap-to.sh status       # 現状確認のみ (swap せず)
#   bash vllm-swap-to.sh restore      # main vLLM の復帰のみ

set -uo pipefail

TARGET="${1:-status}"
PORT="${VLLM_SWAP_PORT:-8001}"
MAIN_CONTAINER="${VLLM_MAIN_CONTAINER:-vllm-qwen-coder}"
SWAP_CONTAINER="vllm-swap"
HF_TOKEN="$(cat ~/.hf_token 2>/dev/null || true)"
HF_CACHE="${HF_CACHE_DIR:-$HOME/.cache/huggingface}"

is_main_running() {
  docker ps --format '{{.Names}}' | grep -qx "$MAIN_CONTAINER"
}

is_swap_running() {
  docker ps --format '{{.Names}}' | grep -qx "$SWAP_CONTAINER"
}

wait_healthy() {
  local url="$1"
  local max_tries="${2:-72}"  # 60s * 5 = 5min default
  for _ in $(seq 1 "$max_tries"); do
    curl -sf -m 3 "$url/models" > /dev/null 2>&1 && return 0
    sleep 5
  done
  return 1
}

show_status() {
  echo "=== vLLM status ==="
  echo "main ($MAIN_CONTAINER on :8000): $(is_main_running && echo "running" || echo "stopped")"
  echo "swap ($SWAP_CONTAINER on :$PORT): $(is_swap_running && echo "running" || echo "stopped")"
  echo ""
  echo "=== GPU ==="
  nvidia-smi --query-gpu=memory.used,memory.free,memory.total --format=csv,noheader
}

stop_main() {
  if is_main_running; then
    echo "Stopping $MAIN_CONTAINER..."
    docker stop "$MAIN_CONTAINER" > /dev/null
    sleep 3
  fi
}

restore_main() {
  if is_main_running; then
    echo "$MAIN_CONTAINER already running."
    return 0
  fi
  # オンデマンド既定 (ADR-0005) では主力は --rm なしでも停止中=コンテナ不在のことがあるため、
  # docker start ではなく ensure-vllm.sh で復帰させる (未起動/停止中/systemd 常駐すべてに対応)。
  echo "Restoring $MAIN_CONTAINER via ensure-vllm.sh..."
  if bash "$(dirname "$0")/ensure-vllm.sh"; then
    echo "  -> main healthy"
  else
    echo "  !! main の復帰に失敗 — bash $(dirname "$0")/ensure-vllm.sh status / docker logs $MAIN_CONTAINER を確認"
    return 1
  fi
}

stop_swap() {
  if is_swap_running; then
    echo "Stopping $SWAP_CONTAINER..."
    docker rm -f "$SWAP_CONTAINER" > /dev/null
  fi
}

launch_distill() {
  echo "Launching Distill-Qwen-14B online FP8 on :$PORT..."
  docker run -d --name "$SWAP_CONTAINER" \
    --gpus all --ipc=host -p "$PORT:8000" \
    -v "$HF_CACHE":/root/.cache/huggingface \
    -e HUGGING_FACE_HUB_TOKEN="$HF_TOKEN" \
    vllm/vllm-openai:latest \
    --model deepseek-ai/DeepSeek-R1-Distill-Qwen-14B \
    --quantization fp8 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.90 \
    --served-model-name distill \
    --enforce-eager > /dev/null
}

launch_coder_14b() {
  echo "Launching Qwen-Coder-14B AWQ INT4 on :$PORT..."
  docker run -d --name "$SWAP_CONTAINER" \
    --gpus all --ipc=host -p "$PORT:8000" \
    -v "$HF_CACHE":/root/.cache/huggingface \
    -e HUGGING_FACE_HUB_TOKEN="$HF_TOKEN" \
    vllm/vllm-openai:latest \
    --model Qwen/Qwen2.5-Coder-14B-Instruct-AWQ \
    --max-model-len 4096 \
    --gpu-memory-utilization 0.50 \
    --served-model-name coder-14b \
    --enforce-eager > /dev/null
}

case "$TARGET" in
  status)
    show_status
    ;;
  restore)
    stop_swap
    restore_main
    show_status
    ;;
  distill|coder-14b)
    stop_main
    stop_swap
    if [ "$TARGET" = "distill" ]; then
      launch_distill
    else
      launch_coder_14b
    fi
    if wait_healthy "http://localhost:$PORT/v1"; then
      echo "  -> $TARGET ready on http://localhost:$PORT/v1 (served-model-name: $TARGET)"
      echo ""
      echo "Use it with:"
      echo "  curl http://localhost:$PORT/v1/chat/completions \\"
      echo "    -H 'Content-Type: application/json' \\"
      echo "    -d '{\"model\":\"$TARGET\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}'"
      echo ""
      echo "When done, restore main with: bash $(basename "$0") restore"
    else
      echo "  !! $TARGET failed to start in 6 min. Logs:"
      docker logs "$SWAP_CONTAINER" 2>&1 | tail -30
      stop_swap
      restore_main
      exit 1
    fi
    ;;
  *)
    echo "Usage: $0 {distill|coder-14b|status|restore}" >&2
    exit 2
    ;;
esac
