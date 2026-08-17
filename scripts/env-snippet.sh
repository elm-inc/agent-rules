# === AI 開発ワークフロー: 環境変数 ===
# このスニペットを ~/.bashrc または ~/.zshrc の末尾に追加してください。
# 適用: source ~/.bashrc
#
# 設計方針: API キーは ~/.bashrc に直接書かず、~/.*_token ファイル (perms 600) に
# 保存し、起動時に読み込む。バックアップ漏洩・他プロセスからの読取りを最小化。
# Phase 2-3 のトークン取得手順は docs/setup/notes/phase{2,3}-*.md 参照。

# --- ローカル LLM (vLLM) ---
# 主力: Qwen3-Coder-30B-A3B AWQ4bit (ADR-0017)。既定はオンデマンド起動 (ADR-0005)
export LOCAL_LLM_BASE_URL="http://localhost:8000/v1"
export LOCAL_LLM_MODEL="qwen-coder"

# swap 用ポート (Distill-Qwen-14B / Qwen-Coder-14B INT4 が必要時に起動)
# scripts/vllm-swap-to.sh で起動・restore する
export LOCAL_LLM_SWAP_BASE_URL="http://localhost:8001/v1"
# モデル名 (served-model-name) は swap-to で起動した値:
#   (swap 候補は用途が無くなったため ADR-0017 で整理。必要になったら台帳に追加する)

# HF cache の統一先 (Phase 7 で elmo 所有領域に移行予定)
export HF_HUB_CACHE="$HOME/.cache/huggingface/hub"

# --- HuggingFace (vLLM の weight DL に必要) ---
[ -f ~/.hf_token ] && export HUGGING_FACE_HUB_TOKEN="$(cat ~/.hf_token)"

# --- クラウド LLM API (Phase 3) ---
[ -f ~/.gemini_token ]   && export GEMINI_API_KEY="$(cat ~/.gemini_token)"
[ -f ~/.deepseek_token ] && export DEEPSEEK_API_KEY="$(cat ~/.deepseek_token)"

# --- 通知経路 (AGENT-15 / docs/setup/notifications.md) ---
# vLLM healthcheck の push 先 ntfy.sh トピック。
# `echo "elmo-vllm-XXXXXX" > ~/.ntfy_topic && chmod 600 ~/.ntfy_topic` で設定。
[ -f ~/.ntfy_topic ] && export NTFY_TOPIC="$(cat ~/.ntfy_topic)"
