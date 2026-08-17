#!/usr/bin/env bash
# vllm-swap-to.sh — A 案 (swap 方式) の補助スクリプト
#
# ADR-0002 採択 / Phase 1 ベンチで 32GB VRAM では複数モデル同時ロード不可と判明。
# このスクリプトは主力 vllm-qwen-coder (30B-A3B AWQ4bit) の停止/復帰を扱う。
# 復帰はオンデマンド既定 (ADR-0005) に合わせ ensure-vllm.sh 経由 (docker start ではない)。
#
# **swap ターゲットは現在ゼロ** — ADR-0017 で distill / coder-14b を廃止した
# (前者は /test-generate --with-distill の廃止、後者は主力が 16.9 GiB になり
#  VRAM を空ける動機が消えたため)。新設するときは config/models.yml に登録してから。
#
# Usage:
#   bash vllm-swap-to.sh status       # 現状確認
#   bash vllm-swap-to.sh restore      # main vLLM の復帰

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
    echo "ERROR: swap ターゲット '$TARGET' は ADR-0017 で廃止されました。" >&2
    echo "  distill:   /test-generate --with-distill の廃止に伴い不要 (代替: DeepSeek V4-Flash API)" >&2
    echo "  coder-14b: 主力が 16.9 GiB になり VRAM を空ける目的が消滅" >&2
    echo "  新しい swap 先が必要なら config/models.yml に追加してから実装してください。" >&2
    exit 2
    ;;
  *)
    echo "Usage: $0 {distill|coder-14b|status|restore}" >&2
    exit 2
    ;;
esac
