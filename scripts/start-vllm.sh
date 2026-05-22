#!/usr/bin/env bash
# vLLM + Qwen2.5-Coder-32B (FP8) コンテナ起動スクリプト
# Linear: AGENT-2
set -euo pipefail

MODEL="${VLLM_MODEL:-RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic}"
SERVED_NAME="${VLLM_SERVED_NAME:-qwen-coder}"
PORT="${VLLM_PORT:-8000}"
CONTAINER_NAME="vllm-qwen-coder"
MAX_LEN="${VLLM_MAX_LEN:-4096}"
GPU_MEM_UTIL="${VLLM_GPU_MEM_UTIL:-0.88}"
ENFORCE_EAGER="${VLLM_ENFORCE_EAGER:-1}"  # 1=disable cudagraph (-2GB), 0=enable (高速だが OOM 余地)
CPU_OFFLOAD_GB="${VLLM_CPU_OFFLOAD_GB:-6}"  # CPU に逃がす重み (32GB VRAM では 4-6 推奨)
MODELS_DIR="${HOME}/models"

mkdir -p "$MODELS_DIR"

# 既存コンテナがあれば停止・削除
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "既存の ${CONTAINER_NAME} を停止・削除します..."
  docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
  docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

EAGER_FLAG=""
[ "$ENFORCE_EAGER" = "1" ] && EAGER_FLAG="--enforce-eager"

OFFLOAD_FLAG=""
[ "$CPU_OFFLOAD_GB" != "0" ] && OFFLOAD_FLAG="--cpu-offload-gb $CPU_OFFLOAD_GB"

echo "vLLM コンテナを起動します:"
echo "  Model:        $MODEL"
echo "  Quant:        pre-quantized FP8 (RedHatAI)"
echo "  Port:         $PORT"
echo "  Max len:      $MAX_LEN"
echo "  GPU util:     $GPU_MEM_UTIL"
echo "  Eager:        $ENFORCE_EAGER (1=cudagraph 無効化、約 2GB 節約)"
echo "  CPU offload:  ${CPU_OFFLOAD_GB} GB (大きいほど GPU 負荷減るが推論遅くなる)"
echo ""

docker run -d --restart no \
  --name "$CONTAINER_NAME" \
  --gpus all \
  --ipc=host \
  -p "${PORT}:8000" \
  -v "${MODELS_DIR}:/root/.cache/huggingface" \
  ${HUGGING_FACE_HUB_TOKEN:+-e HUGGING_FACE_HUB_TOKEN="$HUGGING_FACE_HUB_TOKEN"} \
  -e HF_HUB_ENABLE_HF_TRANSFER=1 \
  -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
  vllm/vllm-openai:latest \
  --model "$MODEL" \
  --max-model-len "$MAX_LEN" \
  --gpu-memory-utilization "$GPU_MEM_UTIL" \
  $EAGER_FLAG \
  $OFFLOAD_FLAG \
  --served-model-name "$SERVED_NAME"

echo ""
echo "コンテナ ID: $(docker ps -q --filter name=$CONTAINER_NAME)"
echo ""
echo "ログ監視:    docker logs -f $CONTAINER_NAME"
echo "起動完了確認: until curl -sf http://localhost:${PORT}/v1/models > /dev/null; do sleep 5; done && echo READY"
