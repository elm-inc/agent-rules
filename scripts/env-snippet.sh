# === AI 開発ワークフロー: 環境変数 ===
# このスニペットを ~/.bashrc または ~/.zshrc の末尾に追加してください。
# 適用: source ~/.bashrc
#
# 設計方針: API キーは ~/.bashrc に直接書かず、~/.*_token ファイル (perms 600) に
# 保存し、起動時に読み込む。バックアップ漏洩・他プロセスからの読取りを最小化。
# Phase 2-3 のトークン取得手順は docs/setup/notes/phase{2,3}-*.md 参照。

# --- ローカル LLM (vLLM + Qwen2.5-Coder-32B) ---
export LOCAL_LLM_BASE_URL="http://localhost:8000/v1"
export LOCAL_LLM_MODEL="qwen-coder"

# --- HuggingFace (vLLM の weight DL に必要) ---
[ -f ~/.hf_token ] && export HUGGING_FACE_HUB_TOKEN="$(cat ~/.hf_token)"

# --- クラウド LLM API (Phase 3) ---
[ -f ~/.gemini_token ]   && export GEMINI_API_KEY="$(cat ~/.gemini_token)"
[ -f ~/.deepseek_token ] && export DEEPSEEK_API_KEY="$(cat ~/.deepseek_token)"
