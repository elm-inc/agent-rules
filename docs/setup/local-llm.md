# ローカル LLM セットアップ (vLLM + Qwen2.5-Coder)

本ドキュメントは、`/local-review` `/test-generate` `/test-data` 等のローカル LLM 系スキルが前提とする推論サーバの構築手順を示す。

## ハードウェア前提

- **GPU**: RTX PRO 4500 Blackwell (32GB GDDR7, FP4/FP8 ネイティブ)
- 推奨 OS: Ubuntu 24.04 LTS (CUDA 12.6+)
- ディスク: モデル保存に 100GB 以上

他の GPU でも動くが、量子化設定 (FP8 / Q5_K_M) を VRAM に合わせて調整する。

## 採用モデル

| 用途 | モデル | 量子化 | VRAM 使用量 |
|---|---|---|---|
| 主力 (レビュー、テスト生成) | `Qwen/Qwen2.5-Coder-32B-Instruct` | FP8 | 〜23GB |
| 高速ループ (commit msg, format hint) | `Qwen/Qwen2.5-Coder-7B-Instruct` | FP8 | 〜8GB |
| 任意 (Mistral 系比較) | `mistralai/Codestral-22B-v0.1` | Q5_K_M (GGUF) | 〜16GB |

**主力モデルだけ常駐**させ、7B は必要時に swap する運用を想定。

## ランタイム: vLLM (FP8)

vLLM は OpenAI 互換 API を提供し、Blackwell の FP8 テンソルコアを最大限活用できる。

### 1. Docker で vLLM サーバ起動

```bash
mkdir -p ~/models

docker run -d --restart unless-stopped \
  --name vllm-qwen-coder \
  --gpus all \
  --ipc=host \
  -p 8000:8000 \
  -v ~/models:/root/.cache/huggingface \
  -e HUGGING_FACE_HUB_TOKEN=$HUGGING_FACE_HUB_TOKEN \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-Coder-32B-Instruct \
  --quantization fp8 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --served-model-name qwen-coder
```

初回は HuggingFace から weights を pull するため 10-20 分かかる。

### 2. 動作確認

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen-coder",
    "messages": [{"role": "user", "content": "Pythonでfizzbuzzを書いてください"}],
    "max_tokens": 200
  }'
```

### 3. systemd サービス化 (任意)

`/etc/systemd/system/vllm-qwen.service` に上記 docker run を wrap した unit を置き、`systemctl enable --now vllm-qwen` で起動時自動起動。

## 環境変数

`~/.bashrc` または `~/.zshrc` に追記:

```bash
# ローカル LLM (vLLM)
export LOCAL_LLM_BASE_URL="http://localhost:8000/v1"
export LOCAL_LLM_MODEL="qwen-coder"

# クラウド LLM
export GEMINI_API_KEY="..."     # https://aistudio.google.com/apikey
export DEEPSEEK_API_KEY="..."   # https://platform.deepseek.com/api_keys
# OPENAI_API_KEY / ANTHROPIC_API_KEY は既存
```

スキルから OpenAI 互換クライアントで呼び出す:

```bash
# 例: cli ツール llm + openai-compatible エンドポイント
llm -m openai/qwen-coder \
    -o base_url "$LOCAL_LLM_BASE_URL" \
    "プロンプト内容"
```

または curl で直接 `$LOCAL_LLM_BASE_URL/chat/completions` を叩く。

## モデル swap (7B ↔ 32B)

VRAM が足りなくなった場合、7B に切り替える:

```bash
docker stop vllm-qwen-coder && docker rm vllm-qwen-coder

docker run -d --restart unless-stopped \
  --name vllm-qwen-coder \
  --gpus all --ipc=host -p 8000:8000 \
  -v ~/models:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-Coder-7B-Instruct \
  --quantization fp8 \
  --max-model-len 32768 \
  --served-model-name qwen-coder
```

スキル側はモデル名 `qwen-coder` で抽象化されているため変更不要。

## トラブルシューティング

| 症状 | 原因と対処 |
|---|---|
| `CUDA out of memory` 起動時 | `--gpu-memory-utilization 0.80` に下げる、または 7B に切替 |
| `unknown quantization fp8` | vLLM が古い。`docker pull vllm/vllm-openai:latest` |
| 推論が極端に遅い | 他プロセスが GPU を使用していないか `nvidia-smi` で確認 |
| 32K コンテキストで OOM | `--max-model-len 16384` に縮める |

## クラウド LLM (補完)

ローカルでカバーしきれない用途はクラウドを使う:

| プロバイダ | モデル | スキル | 用途 |
|---|---|---|---|
| Anthropic | Claude Opus 4.7 | (実装本体) | 実装・推論主力 |
| OpenAI | GPT-5 (Codex CLI) | `/codex-review` 他 | セカンドオピニオン |
| Google | Gemini 2.5 Pro | `/gemini-review` | リポ横断・長文ドキュメント |
| DeepSeek | DeepSeek-R1 | `/deepseek-redteam` | 設計レッドチーム (思考連鎖) |

API キーの取得先は前述の環境変数セクション参照。
