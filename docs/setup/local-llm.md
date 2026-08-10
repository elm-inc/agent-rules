# ローカル LLM セットアップ (vLLM + Qwen2.5-Coder)

本ドキュメントは、`/local-review` `/test-generate` `/test-data` 等のローカル LLM 系スキルが前提とする推論サーバの構築手順を示す。

> **運用方式: オンデマンド起動が既定 (ADR-0005, 2026-06-11)**
> vLLM は常駐させず、ローカル LLM スキルが必要時に `scripts/ensure-vllm.sh` で起動し、アイドル後に自動停止して GPU を解放する。詳細は下記「オンデマンド運用」を参照。常駐 (boot 自動起動) は高頻度利用マシン向けの opt-in に変更。

## ハードウェア前提

- **GPU**: RTX PRO 4500 Blackwell (32GB GDDR7, FP4/FP8 ネイティブ)
- 推奨 OS: Ubuntu 24.04 LTS (CUDA 12.6+)
- ディスク: モデル保存に 100GB 以上

他の GPU でも動くが、量子化設定 (FP8 / Q5_K_M) を VRAM に合わせて調整する。

## 採用モデル (ADR-0002 採択後)

| 用途 | モデル | 量子化 | 重量 | **実 VRAM (KV cache + overhead 込み)** |
|---|---|---|---|---|
| **主力 (コードレビュー、実装、テスト) — オンデマンド起動** | `RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic` | FP8 | 18.14 GiB | ~28-30 GiB |
| swap 1 (高速ループ・観点抽出補助) | `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ` | AWQ INT4 | 9.38 GiB | ~17.5 GiB |
| swap 2 (機密案件レッドチーム) | `deepseek-ai/DeepSeek-R1-Distill-Qwen-14B` | online FP8 | 15.5 GiB | ~28.5 GiB |

**重要**: 32GB VRAM では同時ロード不可 (Phase 1 ベンチで確定)。**A 案 (swap 方式) で運用**: 主力をオンデマンド起動 (ADR-0005)、swap 候補は要求時に `scripts/vllm-swap-to.sh` で一時起動 → 終了時に主力復帰。

Phase 1 実測詳細: [docs/setup/notes/phase7-distill-eval.md](notes/phase7-distill-eval.md)

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

### 3. systemd サービス化 (常駐させたい場合のみ、opt-in)

`/etc/systemd/system/vllm-qwen-coder.service` に上記 docker run を wrap した unit を置き、`systemctl enable --now vllm-qwen-coder` で起動時自動起動。**ただし既定はオンデマンド運用** (次セクション)。常駐は GPU を専有して構わない高頻度利用マシンでのみ選ぶ。

## オンデマンド運用 (既定、ADR-0005)

vLLM を常駐させず、ローカル LLM スキルが呼ばれた時だけ起動し、アイドル後に自動停止して GPU を解放する。GPU を他プロジェクトと共有するマシン向け。

### 仕組み

| スクリプト | 役割 |
|---|---|
| `scripts/ensure-vllm.sh` | 冪等な起動保証。稼働中なら即進行、未稼働なら起動して healthy まで待機。各ローカル LLM スキルが推論前に呼ぶ |
| `scripts/vllm-idle-watch.sh` | アイドル監視。`vllm:prompt_tokens_total` を poll し、一定時間変化が無ければ `docker stop` で GPU 解放。`ensure-vllm.sh` が flock で 1 つだけ常駐させる |

docker を直接管理するため **sudo 不要** (elmo が docker グループ所属)。コンテナ設定は常駐時と同一。

### 常駐からの移行 (一度だけ)

```bash
# 現行の常駐 systemd を停止 + boot 自動起動を無効化 (sudo はここだけ)
sudo systemctl disable --now vllm-qwen-coder

# 以降はスキル実行時に自動起動される。手動で叩く場合:
bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh          # 起動保証
bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh status   # running / stopped
bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh stop     # 即停止 (GPU 解放)
```

systemd unit ファイル自体は残すので、常駐に戻したくなったら `sudo systemctl enable --now vllm-qwen-coder` で復帰できる。

### 主な環境変数 (`~/.bashrc`)

```bash
export VLLM_IDLE_MINUTES=15   # この分数アイドルで自動停止 (デフォルト 15)
export VLLM_START_TIMEOUT=300 # 起動待ちタイムアウト秒 (デフォルト 300)
# export VLLM_IMAGE=vllm/vllm-openai:v0.21.0  # 安定運用では版を pin 推奨 (既定は :latest)
# モデル/ポート等を変える場合: VLLM_MODEL / VLLM_SERVED_NAME / VLLM_PORT / VLLM_MAX_LEN / VLLM_GPU_MEM_UTIL / VLLM_CPU_OFFLOAD_GB / VLLM_HF_CACHE / VLLM_IDLE_POLL
```

> vLLM image を `:latest` のまま使う場合でも、アイドル監視は対象メトリクス行が取得できないとき停止判断をスキップする (fail-safe) ので、メトリクス改名で使用中に誤停止することはない。安定性を最優先するなら `VLLM_IMAGE` で版を固定する。

**環境変数の注意**:
- `VLLM_PORT` を既定 (8000) から変える場合、スキル側が参照する `LOCAL_LLM_BASE_URL` (既定 `http://localhost:8000/v1`) も合わせて変える。両者は別系統なので片方だけ変えると食い違う。
- `VLLM_IDLE_MINUTES` / `VLLM_IDLE_POLL` の変更は**次に起動する watcher から**有効。既に稼働中の watcher には反映されない (一度 `ensure-vllm.sh stop` するか、現 watcher が自然終了してから再起動)。

**前提 (canonical path)**: スキルは `~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh` を絶対パスで呼ぶ。CLAUDE.md (`agent-rules` の運用) が clone 先をこのパスに規定しているため。別の場所に clone した場合はスキルの起動保証ステップが動かないので、canonical path に置く (または symlink する)。

### トレードオフ

- アイドル後の**初回スキル実行はモデルロード待ち (1-2 分)**。連続実行・15 分以内の再実行はキャッシュ済みで即時
- すぐ GPU を空けたい時は `ensure-vllm.sh stop`
- 高頻度利用が常態化したら常駐 (systemd) に戻す選択も可

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

## モデル swap (ADR-0002 採択フロー)

ADR-0002 採択により、主力 (Qwen-Coder-32B FP8、オンデマンド起動) はそのまま、swap 用に Distill / 14B INT4 を必要時に起動するヘルパースクリプトを使う。

### 自動 swap (推奨)

```bash
# Distill-Qwen-14B FP8 を :8001 で起動 (機密案件レッドチーム)
bash scripts/vllm-swap-to.sh distill

# Qwen-Coder-14B AWQ INT4 を :8001 で起動 (高速ループ)
bash scripts/vllm-swap-to.sh coder-14b

# 状態確認
bash scripts/vllm-swap-to.sh status

# swap 終了 → 主力復帰
bash scripts/vllm-swap-to.sh restore
```

`scripts/vllm-swap-to.sh` は内部で:
1. 主力 `vllm-qwen-coder` を docker stop
2. 引数モデルを :8001 で docker run (`--name vllm-swap`)
3. /v1/models で healthcheck (最大 6 分待機)
4. ユーザーに利用例を表示

`restore` で逆順 (swap 停止 → 主力を `ensure-vllm.sh` 経由で復帰。オンデマンド既定では `--rm` 撤去後も停止中=コンテナ不在のことがあるため docker start は使わない)。swap 時間: 30-60 秒 / モデル。

### 健全性監視

```bash
# 単発チェック
bash scripts/vllm-healthcheck.sh

# cron で 5 分おき (異常時 NTFY_TOPIC に通知)
*/5 * * * * NTFY_TOPIC=elmo-claude-XXXX /path/to/scripts/vllm-healthcheck.sh
```

### サプライチェーン対策 (モデル改ざん検証)

ADR-0002 採択時の発見 (DeepSeek-R1 redteam High 指摘) への対応:

```bash
bash scripts/vllm-verify-model.sh Qwen/Qwen2.5-Coder-14B-Instruct-AWQ
bash scripts/vllm-verify-model.sh deepseek-ai/DeepSeek-R1-Distill-Qwen-14B
```

HF Hub の API から取得した safetensors SHA256 をローカルファイルと照合する。
publisher allowlist: `Qwen / deepseek-ai / RedHatAI / mistralai / google / meta-llama`。それ以外は明示的に拒否。

### systemd unit 化 (AGENT-14, 手動 install 推奨)

**既定はオンデマンド運用 (ADR-0005)** であり、systemd 常駐は高頻度利用マシン向けの opt-in。常駐を選ぶ場合のみ、ブート時の起動順序制御 / journalctl ログ統一のため systemd unit 化する。テンプレ: [`templates/systemd/vllm-qwen-coder.service`](../../templates/systemd/vllm-qwen-coder.service)。

セットアップ手順:

```bash
# 1) ユニットファイル配置
sudo cp ~/repos/github.com/elm-inc/agent-rules/templates/systemd/vllm-qwen-coder.service /etc/systemd/system/
sudo systemctl daemon-reload

# 2) HF token を 600 権限ファイルに分離 (inline 漏洩防止)
sudo install -m 600 /dev/null /etc/vllm-qwen-coder.env
echo "HUGGING_FACE_HUB_TOKEN=$(cat ~/.hf_token)" | sudo tee -a /etc/vllm-qwen-coder.env > /dev/null
sudo chmod 600 /etc/vllm-qwen-coder.env  # 念のため再確認

# 3) 既存 docker --restart コンテナを停止 (移行のためダウンタイム ~2 分)
docker stop vllm-qwen-coder && docker rm vllm-qwen-coder

# 4) systemd 経由で起動 + boot 自動起動有効化
sudo systemctl enable --now vllm-qwen-coder
sudo systemctl status vllm-qwen-coder

# 5) 初回起動を 1-2 分待ってヘルスチェック
sleep 90 && curl -sf http://localhost:8000/v1/models | jq -r '.data[].id'

# 6) journalctl でログ確認
journalctl -u vllm-qwen-coder -f
```

確認ポイント:
- `systemctl status` で `Active: active (running)` であること
- `/etc/vllm-qwen-coder.env` が `-rw-------` であること (`ls -la /etc/vllm-qwen-coder.env`)
- ブート再起動後も自動で立ち上がること (`sudo reboot` で確認、ただし計画停止時のみ)

### HF cache の場所 (Phase 7 で判明 → AGENT-16 で移行)

- 既存 (現状): `~/models/hub/` (docker volume 経由で root 所有、elmo から書けない)
- **新規 DL 推奨先**: `~/.cache/huggingface/hub/` (elmo 所有、`hf download` で直接使える)
- env-snippet.sh では `HF_HUB_CACHE` を後者に向けている

#### AGENT-16 移行手順 (手動実行)

```bash
# 約 30-60 分のダウンタイム。sudo パスワードが 2 回必要 (chown と mv)。
bash ~/repos/github.com/elm-inc/agent-rules/scripts/migrate-hf-cache.sh
```

スクリプトの動作:
1. 確認プロンプトを表示 (`yes` で続行)
2. `vllm-qwen-coder` 停止 → 削除
3. `rsync -a --ignore-existing` で旧 → 新 cache へコピー (既存 elmo 所有領域は保護)
4. `sudo chown -R elmo:elmo ~/.cache/huggingface/hub` で root 所有を解消
5. `sudo mv ~/models ~/models.legacy.YYYYMMDD-HHMMSS` で旧 cache を保全 (削除しない)
6. 新 volume mount で `vllm-qwen-coder` を再作成
7. `/v1/models` を polling、最大 5 分で healthy 確認

移行後の確認:
- `hf download <model>` で `~/.cache/huggingface/hub/` 配下に直接 DL できること
- `/local-review` を 1 回実行して vLLM 動作確認
- `~/models.legacy.*` を 1 ヶ月程度保持して問題なければ `sudo rm -rf` で削除

AGENT-14 (systemd unit) を **install 済みで未移行パスのまま**なら、unit ファイル
(`/etc/systemd/system/vllm-qwen-coder.service`) の `ExecStart` 行の
`-v ~/models` を `-v ~/.cache/huggingface` に書き換えてから
`sudo systemctl daemon-reload && sudo systemctl restart vllm-qwen-coder` を実行。

(`templates/systemd/vllm-qwen-coder.service` の `-v` 行は AGENT-16 移行**後**の
統一パス `~/.cache/huggingface` を既定とする。オンデマンド (ensure-vllm.sh) と
同一 cache を見るため、常駐 opt-in でも二重 DL は起きない。AGENT-16 **未移行**マシンで
systemd unit を入れる場合のみ、テンプレを sed で
`s|~/.cache/huggingface|~/models|` して旧パスに戻す。)

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
| Anthropic | Claude Opus 4.8 (Fable 5 は要所) | (実装本体) | 実装・推論主力 |
| OpenAI | GPT-5 (Codex CLI) | `/codex-review` 他 | セカンドオピニオン |
| Google | Gemini 2.5 Pro | `/gemini-review` | リポ横断・長文ドキュメント |
| DeepSeek | DeepSeek-R1 | `/deepseek-redteam` | 設計レッドチーム (思考連鎖) |

API キーの取得先は前述の環境変数セクション参照。
