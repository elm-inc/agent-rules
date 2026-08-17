#!/usr/bin/env bash
# DeepSeek V4-Pro API 動作確認 (思考モード)
# モデル ID の単一ソースは config/models.yml (ADR-0017)
# Linear: AGENT-3
set -euo pipefail

if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  if [ -f ~/.deepseek_token ]; then
    DEEPSEEK_API_KEY="$(cat ~/.deepseek_token)"
  else
    echo "ERROR: DEEPSEEK_API_KEY が未設定で ~/.deepseek_token もありません"
    echo "https://platform.deepseek.com/api_keys で取得して以下のいずれかを実行:"
    echo "  - export DEEPSEEK_API_KEY=\"...\""
    echo "  - umask 077 && read -s -p 'key: ' k && echo \"\$k\" > ~/.deepseek_token && unset k"
    exit 1
  fi
fi

MODEL="${DEEPSEEK_MODEL:-deepseek-v4-pro}"
PROMPT="${1:-1から10までの素数を列挙し、なぜそれが素数なのか1行で説明してください。}"

echo "=== DeepSeek API 動作確認 ($MODEL) ==="

PAYLOAD=$(jq -n --arg p "$PROMPT" --arg m "$MODEL" '{
  model: $m,
  thinking: {type: "enabled"},
  reasoning_effort: "high",
  messages: [{role: "user", content: $p}],
  max_tokens: 1024
}')

START=$(date +%s.%N)
RESPONSE=$(curl -sf https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
END=$(date +%s.%N)
ELAPSED=$(echo "$END - $START" | bc)

# 思考過程 (思考モード有効時に reasoning_content へ入る)
REASONING=$(echo "$RESPONSE" | jq -r '.choices[0].message.reasoning_content // empty')
if [ -n "$REASONING" ]; then
  echo ""
  echo "=== 思考過程 (reasoning_content) ==="
  echo "$REASONING" | head -30
  [ "$(echo "$REASONING" | wc -l)" -gt 30 ] && echo "  ... (省略 $(echo "$REASONING" | wc -l) 行中)"
fi

echo ""
echo "=== 最終回答 ==="
echo "$RESPONSE" | jq -r '.choices[0].message.content'

echo ""
echo "=== 使用量 ==="
echo "$RESPONSE" | jq -r '.usage | "  入力: \(.prompt_tokens) tok, 出力: \(.completion_tokens) tok, 計: \(.total_tokens) tok"'
echo "  応答時間: ${ELAPSED}s"
