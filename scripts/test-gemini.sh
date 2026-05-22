#!/usr/bin/env bash
# Gemini 2.5 Pro API 動作確認
# Linear: AGENT-3
set -euo pipefail

if [ -z "${GEMINI_API_KEY:-}" ]; then
  # ~/.gemini_token をフォールバックで読む
  if [ -f ~/.gemini_token ]; then
    GEMINI_API_KEY="$(cat ~/.gemini_token)"
  else
    echo "ERROR: GEMINI_API_KEY が未設定で ~/.gemini_token もありません"
    echo "https://aistudio.google.com/apikey で取得して以下のいずれかを実行:"
    echo "  - export GEMINI_API_KEY=\"...\""
    echo "  - umask 077 && read -s -p 'key: ' k && echo \"\$k\" > ~/.gemini_token && unset k"
    exit 1
  fi
fi

MODEL="${GEMINI_MODEL:-gemini-2.5-pro}"
PROMPT="${1:-1から10までの素数を列挙し、なぜそれが素数なのか1行で説明してください。}"

echo "=== Gemini API 動作確認 ($MODEL) ==="

PAYLOAD=$(jq -n --arg p "$PROMPT" '{
  contents: [{parts: [{text: $p}]}],
  generationConfig: {temperature: 0.2, maxOutputTokens: 2048}
}')

START=$(date +%s.%N)
RESPONSE=$(curl -sf "https://generativelanguage.googleapis.com/v1beta/models/${MODEL}:generateContent?key=${GEMINI_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")
END=$(date +%s.%N)
ELAPSED=$(echo "$END - $START" | bc)

# 応答テキスト
echo ""
echo "=== 応答 ==="
echo "$RESPONSE" | jq -r '.candidates[0].content.parts[0].text'

# 使用量 (thinking tokens は別カウント)
echo ""
echo "=== 使用量 ==="
echo "$RESPONSE" | jq -r '.usageMetadata | "  入力: \(.promptTokenCount) tok, 出力: \(.candidatesTokenCount // 0) tok, 思考: \(.thoughtsTokenCount // 0) tok, 計: \(.totalTokenCount) tok"'
echo "  応答時間: ${ELAPSED}s"
FINISH=$(echo "$RESPONSE" | jq -r '.candidates[0].finishReason // "?"')
echo "  終了理由: $FINISH"

# モデル
echo ""
echo "=== モデル ==="
echo "$RESPONSE" | jq -r '.modelVersion'
