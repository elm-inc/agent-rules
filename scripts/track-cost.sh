#!/usr/bin/env bash
# クラウド LLM API の月次コスト集計
# Linear: AGENT-6 (Phase 6)
#
# 使い方:
#   ./scripts/track-cost.sh                  # 当月の集計
#   ./scripts/track-cost.sh --month 2026-06  # 特定月
#
# 注意:
#   - 各 API のダッシュボードから手動取得が必要なケースもある
#   - Gemini: https://console.cloud.google.com/billing → 該当プロジェクト
#   - DeepSeek: https://platform.deepseek.com/usage
#   - OpenAI (Codex): https://platform.openai.com/usage
#   - Anthropic (Claude): https://console.anthropic.com/settings/usage
#
# 結果は docs/design/ai-workflow.md の月別コスト表に転記する。

set -euo pipefail

MONTH="${MONTH:-$(date +%Y-%m)}"
[ "${1:-}" = "--month" ] && MONTH="$2"

echo "=== AI ワークフロー月次コスト集計: $MONTH ==="
echo ""

# DeepSeek: 残高ベース推定 (API 経由で取得可能)
echo "--- DeepSeek ---"
if [ -f ~/.deepseek_token ]; then
  DEEPSEEK_API_KEY="$(cat ~/.deepseek_token)"
  BALANCE=$(curl -sf https://api.deepseek.com/user/balance \
    -H "Authorization: Bearer $DEEPSEEK_API_KEY" 2>/dev/null \
    | jq -r '.balance_infos[0].total_balance // "N/A"')
  echo "  現在残高: \$$BALANCE"
  echo "  月次消費は dashboard で確認: https://platform.deepseek.com/usage"
  unset DEEPSEEK_API_KEY
else
  echo "  (~/.deepseek_token なし、SKIP)"
fi
echo ""

# Gemini: 公式 API には集計エンドポイントなし → ダッシュボード参照を案内
echo "--- Gemini ---"
echo "  ダッシュボード: https://aistudio.google.com/ → Billing"
echo "  または: https://console.cloud.google.com/billing"
echo "  Phase 4 実測値: \$0.051 / リクエスト (thinking 込み)"
echo ""

# ローカル LLM: GPU 稼働時間 + 平均電力から電気代を推定
echo "--- ローカル LLM (vLLM + Qwen) ---"
if docker ps --filter name=vllm-qwen-coder --format '{{.Status}}' 2>/dev/null | grep -q Up; then
  UPTIME=$(docker inspect vllm-qwen-coder --format '{{.State.StartedAt}}' 2>/dev/null)
  echo "  稼働中 (開始: $UPTIME)"
  # GPU 平均電力 (estimate): idle 30W, 推論時 200W
  # 24h 稼働で約 100W 平均と仮定: 100W × 720h/月 × 35円/kWh = 約 2500円/月
  echo "  電気代推定: 約 2500 円/月 (24h 稼働、平均 100W、35 円/kWh 仮定)"
else
  echo "  停止中"
fi
echo ""

# Claude (Opus = セッションモデル/実質 1x, Fable 5 = 従量課金)。
# Fable の実費は transcript (~/.claude/projects/**/*.jsonl) から自動集計する (fable-usage.sh)。
echo "--- Claude / Fable 5 (従量課金の実費) ---"
FABLE_SH="$(dirname "$0")/fable-usage.sh"
if [ -x "$FABLE_SH" ]; then
  "$FABLE_SH" --month "$MONTH" | sed 's/^/  /'
else
  echo "  (scripts/fable-usage.sh なし、SKIP)"
fi
echo ""

# シェル履歴からスキル呼び出し回数を集計 (zsh/bash 共通)
# 注: Claude Code TUI から呼んだスキルはここに出ない (シェル経由のみカウント)。
#     Fable の実費は上の fable-usage.sh が transcript から拾うのでこの限界の影響を受けない。
echo "--- スキル使用頻度 (シェル履歴から推定 — TUI 呼び出しは含まれない) ---"
HISTFILE_CANDIDATES=(~/.zsh_history ~/.bash_history)
for f in "${HISTFILE_CANDIDATES[@]}"; do
  [ -f "$f" ] || continue
  echo "  ソース: $f"
  for cmd in "/local-review" "/codex-review" "/deepseek-redteam" "/gemini-review" "/test-generate" "/test-data"; do
    COUNT=$(grep -cF "$cmd" "$f" 2>/dev/null || true)
    COUNT=${COUNT:-0}
    printf "    %-22s: %d 回\n" "$cmd" "$COUNT"
  done
  break
done
echo ""

echo "=== 完了 ==="
echo ""
echo "上記を docs/design/ai-workflow.md の §8 実運用データ追記欄に転記してください。"
