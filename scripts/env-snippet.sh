# === ローカル LLM (vLLM + Qwen2.5-Coder-32B) ===
# このスニペットを ~/.bashrc または ~/.zshrc の末尾に追加してください。
# 適用: source ~/.bashrc

export LOCAL_LLM_BASE_URL="http://localhost:8000/v1"
export LOCAL_LLM_MODEL="qwen-coder"

# (任意) HuggingFace 認証トークン — レート制限緩和・ゲート付きモデル用
# https://huggingface.co/settings/tokens で取得
# export HUGGING_FACE_HUB_TOKEN="hf_..."

# (Phase 3 で追加) クラウド LLM API
# export GEMINI_API_KEY="..."     # https://aistudio.google.com/apikey
# export DEEPSEEK_API_KEY="..."   # https://platform.deepseek.com/api_keys
