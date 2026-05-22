# Phase 2: vLLM セットアップ実行記録

Linear: [AGENT-2](https://linear.app/elm-inc/issue/AGENT-2)
Branch: `worktree/agent-2-phase2-vllm-setup`
Started: 2026-05-22

## 環境確認結果 (2026-05-22 17:01)

| 項目 | 結果 |
|---|---|
| GPU | NVIDIA RTX PRO 4500 Blackwell, 32623MiB VRAM |
| NVIDIA Driver | 580.142 (CUDA 13.0) |
| Docker | 29.5.0 |
| nvidia-container-toolkit | 1.19.0-1 |
| GPU passthrough (CDI) | OK (`docker run --gpus all nvidia/cuda nvidia-smi` 成功) |
| docker group | user 所属済 |
| 空き容量 (/home) | 3.1TB |
| 現在の VRAM 使用 (デスクトップ) | 1502MiB → vLLM に約 31GB 利用可能 |

> CDI (Container Device Interface) で GPU が見えるため、`/etc/docker/daemon.json` での runtime 登録は不要。`--gpus all` でそのまま動作。

## 採用構成

- vLLM image: `vllm/vllm-openai:latest`
- モデル: `Qwen/Qwen2.5-Coder-32B-Instruct`
- 量子化: FP8 (vLLM 起動時の online quantization)
- max-model-len: 32768
- GPU memory utilization: 0.85

## モデルダウンロード方針の検討

`--quantization fp8` は **BF16 オリジナル重みを download → 起動時に FP8 に on-the-fly 変換** する仕組み。

| 方式 | DL サイズ | DL 時間 | 利点 | 欠点 |
|---|---|---|---|---|
| **オリジナル + online FP8** (採用) | ~65GB | 20-40 min | docs 通り、後で他量子化に切替容易 | DL 大、起動時 RAM 一時消費 |
| pre-quantized FP8 (e.g. `RedHatAI/...-FP8-Dynamic`) | ~32GB | 10-20 min | 起動高速、DL 半分 | docs 改訂必要、別配布元の品質確認要 |

Phase 5 で `RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-Dynamic` 等への切替を検討する (要 ROI 評価)。

## 実行ログ

### 17:01 — 環境確認
- 上記表参照。問題なし。

### 17:02 — vLLM image pull
- `docker pull vllm/vllm-openai:latest` 完了
- イメージサイズ: 32.9 GB (digest: `a230095847e93b...`)
- vLLM image としては大きめだが正常範囲

### 17:04 — vLLM コンテナ起動
- `scripts/start-vllm.sh` で起動。コンテナ ID: `ff001034c172`
- 初期ログ確認:
  - Model: `Qwen/Qwen2.5-Coder-32B-Instruct` 解決済 (Qwen2ForCausalLM)
  - Quantization: FP8 (`CutlassFP8ScaledMMLinearKernel for Fp8OnlineLinearMethod`)
  - Attention: FlashAttention 2
  - vLLM バージョン: v0.21.0
  - dtype: torch.bfloat16 (DL は BF16、メモリは FP8)
- モデル DL & ロード待機中 (`until curl ... /v1/models` を background 監視)

### 17:04-17:30 — 試行錯誤 (記録)

**問題 1: HF レート制限で DL ストール**
- unauthenticated で 9 分後に 17GB で停止 → HF token 取得して解決
- `HUGGING_FACE_HUB_TOKEN` + `HF_HUB_ENABLE_HF_TRANSFER=1` で 238 MB/s 達成

**問題 2: BF16 オリジナル + online FP8 量子化で OOM**
- `Qwen/Qwen2.5-Coder-32B-Instruct` (BF16 → online FP8) は ロード時 peak 29.85GB で 32GB に収まらず
- → pre-quantized FP8 (`RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic`) に切替

**問題 3: 切替後も OOM (270 MiB 不足)**
- デスクトップが 1.5GB 占有 + vLLM が 29.6GB で計算上 32.1GB > 31.4GB
- `--gpu-memory-utilization`、`--enforce-eager`、`PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` 全部試したが不十分
- → `--cpu-offload-gb 6` で 6GB を CPU RAM (125GB 余裕) に逃がし解決

**問題 4: ロード成功後、KV cache 不足で起動失敗**
- 16K context には 4 GiB KV cache 必要、利用可能 1.11 GiB のみ
- → `--max-model-len 4096` に縮小 (差分レビュー用途には十分)

## 最終構成 (動作確認済)

| パラメータ | 値 | 備考 |
|---|---|---|
| Model | `RedHatAI/Qwen2.5-Coder-32B-Instruct-FP8-dynamic` | pre-quantized FP8 |
| `--gpu-memory-utilization` | 0.88 | KV cache 確保のため高め |
| `--cpu-offload-gb` | 6 | 6GB を CPU RAM に逃がす |
| `--max-model-len` | 4096 | KV cache 制約 |
| `--enforce-eager` | (有効) | cudagraph 無効化で 〜2GB 節約 |
| `HF_HUB_ENABLE_HF_TRANSFER` | 1 | 高速 DL |
| `PYTORCH_CUDA_ALLOC_CONF` | `expandable_segments:True` | 断片化対策 |

## ベンチマーク結果 (2026-05-22 18:36)

| 計測 | 値 |
|---|---|
| 起動完了時刻 | 18:36:52 (cache 済なら ~2 分) |
| 動作確認 | ✅ Fibonacci 10 項を Python で正しく生成 |
| 推論速度 | **6.0 tokens/sec** (256 token を 42.5 秒) |
| VRAM 使用 | 30068 MiB / 32623 MiB (92%) |
| max context | 4096 tokens |

**速度評価**: 6 tokens/sec は予想 (30-50 tokens/sec) より大幅遅。CPU offload による PCIe shuttle が律速。
- 200 token のレビュー = 33 秒
- 機能確認には十分、本格運用には Phase 5 で最適化必要

## 完了条件チェック

- [x] `curl http://localhost:8000/v1/models` が 200 を返す
- [x] サンプルプロンプトに対する応答が妥当
- [ ] 再起動後も自動復帰する → systemd 化は任意のため未実施 (script で再現可能)

## ユーザー残作業

1. `scripts/env-snippet.sh` の内容を `~/.bashrc` 末尾に追加 + `source ~/.bashrc`
2. (任意) systemd 化: `sudo cp scripts/vllm-qwen.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now vllm-qwen.service`

## Phase 5 (フィードバック) に持ち越す課題

1. **推論速度 6 tokens/sec → 30+ tokens/sec への改善**
   - デスクトップ GPU プロセス停止 (Xorg, gnome-shell) で 1.5GB 解放 → cpu-offload 2GB に減らせる
   - 14B モデルへのダウングレード検討 (品質と速度のトレードオフ)
   - AWQ INT4 量子化版モデル探索
2. **max_model_len 4096 → 8192+ への拡張**
   - 上記 1 と連動して KV cache 余地確保
3. **不要キャッシュ削除**
   - 前モデル (`Qwen/Qwen2.5-Coder-32B-Instruct` BF16, 17GB) は使わないので削除候補

## 生成済みアーティファクト

- `scripts/start-vllm.sh` — vLLM コンテナ起動 (試行錯誤の結果を反映)
- `scripts/health-check.sh` — 動作確認 + 推論速度計測
- `scripts/env-snippet.sh` — `~/.bashrc` に追加すべき環境変数
- `scripts/vllm-qwen.service` — systemd unit (任意、要 sudo)
