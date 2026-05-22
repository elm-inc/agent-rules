#!/usr/bin/env bash
# vLLM サーバの動作確認 + 推論速度計測
# Linear: AGENT-2
set -euo pipefail

BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:8000/v1}"
MODEL="${LOCAL_LLM_MODEL:-qwen-coder}"

echo "=== 1. /v1/models 応答確認 ==="
if ! curl -sf "$BASE_URL/models" | jq .; then
  echo "FAIL: $BASE_URL/models が応答しません"
  exit 1
fi

echo ""
echo "=== 2. シンプルな chat completion (動作確認) ==="
curl -sf "$BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg model "$MODEL" '{
    model: $model,
    messages: [{role: "user", content: "Pythonでフィボナッチ数列の最初の10項を出力してください。コードのみ短く。"}],
    max_tokens: 200,
    temperature: 0.2
  }')" | jq -r '.choices[0].message.content'

echo ""
echo "=== 3. 推論速度計測 (256 token 生成) ==="
START=$(date +%s.%N)
RESPONSE=$(curl -sf "$BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg model "$MODEL" '{
    model: $model,
    messages: [{role: "user", content: "RESTful API 設計のベストプラクティスを 5 つ、それぞれ 2 文で説明してください。"}],
    max_tokens: 256,
    temperature: 0.2
  }')")
END=$(date +%s.%N)

TOKENS=$(echo "$RESPONSE" | jq -r '.usage.completion_tokens // 0')
ELAPSED=$(echo "$END - $START" | bc)
TPS=$(echo "scale=1; $TOKENS / $ELAPSED" | bc)

echo "  生成 token: $TOKENS"
echo "  所要時間:   ${ELAPSED}s"
echo "  速度:       ${TPS} tokens/sec"

echo ""
echo "=== 4. VRAM 使用状況 ==="
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
