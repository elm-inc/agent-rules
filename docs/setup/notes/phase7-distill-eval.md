# Phase 7: Distill ローカル化と量子化評価 (進行中)

- Linear: [AGENT-10](https://linear.app/elm-inc/issue/AGENT-10)
- ADR: [0002-multi-model-test-generation](../../adr/0002-multi-model-test-generation.md)
- 設計: [multi-model-test-pipeline](../../design/multi-model-test-pipeline.md)
- ハードウェア: RTX PRO 4500 Blackwell (32GB GDDR7)、ベースライン GPU 占有 ~1.5 GB (Xorg 等)

## 実施日

- 2026-05-24: Phase 1a (モデル DL + VRAM 実測) 完了

## Phase 1a: モデル DL + VRAM 実測

### DL 結果

| モデル | 用途 | サイズ |
|---|---|---|
| `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` | 代替案 E の品質計測用 | 19 GB |
| `Qwen/Qwen2.5-Coder-14B-Instruct-AWQ` | 高速ループ・観点抽出補助 | 9.4 GB |
| `deepseek-ai/DeepSeek-R1-Distill-Qwen-14B` | API R1 のローカル代替候補 | 28 GB (bf16) |

DL 所要: 約 4.5 分 (合計 56 GB、回線速度 ~200 MB/s)。HF cache を `~/.cache/huggingface/hub` (ユーザー所有) に統一。`~/models/hub` (root 所有、既存 vLLM の volume mount) との分離は Phase 3 で揃える。

### VRAM 実測結果

`vllm/vllm-openai:latest` を `--enforce-eager` 付きで起動、`nvidia-smi --query-gpu=memory.used` と vLLM 起動ログから KV cache 情報を取得。

| 構成 | モデル重量 | KV cache 確保 | nvidia-smi 実 VRAM | mml | max-concurrency |
|---|---|---|---|---|---|
| 32B AWQ INT4 | 18.14 GiB | 7.81 GiB | **29178 MiB (~28.5 GiB)** | 4096 | 7.81x |
| 32B AWQ INT4 | 18.14 GiB | 7.81 GiB | **29178 MiB** | 8192 | 3.90x |
| 14B AWQ INT4 (gpu-util 0.50) | 9.38 GiB | 5.59 GiB | **17908 MiB (~17.5 GiB)** | 4096 | 7.46x |
| 14B AWQ INT4 (gpu-util 0.50) | 9.38 GiB | 5.59 GiB | **17910 MiB** | 16384 | 1.86x |
| DeepSeek-R1-Distill-Qwen-14B bf16 | — | — | **FAILED (OOM)** | 4096 | — |
| DeepSeek-R1-Distill-Qwen-14B online FP8 | 15.5 GiB | 10.45 GiB | **29156 MiB (~28.5 GiB)** | 4096 | 13.93x |
| (参考) Qwen-Coder-32B FP8 (現状常駐) | ~23 GiB | — | ~30 GB (測定済み実績) | 4096 | — |

### 重要発見

#### 1. 全同時ロードは物理的に不可能 (DeepSeek-R1 redteam Critical 指摘を裏付け)

設計で想定した 3 戦略 A/B/C のうち、**B 案 (32B INT4 + 14B INT4 × 2 同時) と C 案 (32B FP8 + 14B INT4 同時) は不成立**:

- 32B AWQ INT4 単独で実 28.5 GiB → 残り 4 GiB 弱、14B INT4 (17.5 GiB) は乗らない
- 32B FP8 単独で実 30 GiB → 残り 2 GiB、何も乗らない
- 32B + 14B の同時ロードは VRAM 上**任意の組み合わせで成立しない**

→ **A 案 (swap 方式) で確定**。Phase 2 の `/test-generate --brainstorm` は順次 swap で実装する。

#### 2. 32B AWQ INT4 化のメリットが薄い

- 32B FP8 (~30 GiB) と 32B AWQ INT4 (28.5 GiB) で **VRAM 差はわずか 1.5 GiB**
- 一方、INT4 化で品質劣化リスクを抱える
- → **代替案 E は採用見送り推奨** (Phase 1b の品質ベンチで最終判定するが、VRAM 節約量から見て invest 価値が低い)

#### 3. DeepSeek-R1-Distill-Qwen-14B は bf16 不可、online FP8 で OK

- bf16 (28 GiB) のままだと OOM で起動失敗
- vLLM の `--quantization fp8` (online 量子化) は **成功**、しかも model loading が 15.5 GiB に圧縮されて KV cache 10.45 GiB を確保できる優秀な構成
- ADR-0001 で「online 量子化は OOM する」と書いたが、それは Qwen-Coder-32B の話。**14B クラスでは online FP8 が実用的**

#### 4. 推奨ロード戦略 (Phase 1c 採択候補)

| シナリオ | 推奨構成 |
|---|---|
| 通常時 (現状) | Qwen-Coder-32B FP8 常駐 |
| `--brainstorm` 観点抽出時 | swap で順次: 32B FP8 → 14B AWQ INT4 → Distill-14B online FP8 → 32B FP8 復帰 |
| 高速ループ (将来) | Qwen-Coder-14B AWQ INT4 常駐 + (任意で online FP8 Distill を swap) |

swap 時間: モデル DL は cache 済みなので、`docker stop + start` で **30-60 秒/swap** 程度。`/test-generate --brainstorm` で 3 モデル順次なら合計 1.5-3 分のレイテンシ追加。

## Phase 1b: 品質ベンチマーク (完了 2026-05-24)

### 検証セット

- **コードレビュー**: `samples/buggy_payment.py` (Phase 4 仕込み 5 バグ: 型違反、None チェック漏れ、例外吸い込み、競合状態、SQLi)
- **設計レッドチーム**: `docs/design/multi-model-test-pipeline.md` (本 ADR-0002 の設計)、API DeepSeek-R1 結果と比較

### 結果

| 構成 | コードレビュー検出 | 所要 | 出力 tok | 備考 |
|---|---|---|---|---|
| 32B FP8 (baseline) | **5/5** + balance None ボーナス | 63s | 363 | 現状の `/local-review` 性能を再現 |
| 32B AWQ INT4 | **4/5** (バグ 4 競合状態を見落とし) | 66s | 369 | 競合の指摘なし、トランザクション漏れには触れる |
| 14B AWQ INT4 | **5/5** (競合を "パフォーマンス" 欄で指摘) | 63s | 342 | 位置は変だが内容は正しい |
| Distill FP8 (code-review 参考) | **5/5** + 改善案コード生成 | 92s | 1713 | 思考連鎖モデル特有の冗長性、出力 5x |
| Distill FP8 (design-redteam 本命) | Critical 1 + High 1 (API R1 と一致)、論点数は API R1 の 4/6 ≈ 60-80% | 92s | 1592 | "1 点だけ直すなら" の結論は API R1 と同じ趣旨 |

### 重要発見 (続)

#### 5. **代替案 E (32B AWQ INT4 化) は不採用確定**

- 32B INT4 のバグ検出率 4/5 = **-20% 劣化** (基準 -5% 不達)
- VRAM 節約も 1.5 GiB のみ (発見 #2)
- → A 案 (swap 方式) で 32B FP8 維持が結論

#### 6. **14B INT4 が 32B INT4 を上回る (意外)**

- 14B AWQ INT4 が 5/5 検出 (32B INT4 の 4/5 より高い)
- 原因仮説: 温度 0.2 のばらつき / モデル系列差 / 量子化キャリブレーション差
- 結論: **14B AWQ INT4 は高速ループ + 観点抽出補助として実用** (Phase 2 で `--brainstorm` モードに採用)

#### 7. **Distill FP8 は API R1 の 60-80% 品質、機密案件用に採用候補**

- 設計レッドチームで Critical 1 件 (VRAM 逼迫) を API R1 と同じく抽出、同時アクセス OOM は致命度 High に格下げだが内容は捉えた
- 出力深度は API R1 比劣るが、機密案件 (ローカル必須) では十分実用
- 月 50 回想定での API DeepSeek-R1 コスト $0.5 を 0 に置き換えられる
- → **public コードは API R1 継続、機密コードは Distill FP8** の使い分け

## Phase 1c: ロード戦略採択 (2026-05-24)

### 採択

**A 案 (swap 方式) を採択**:

- **常駐**: Qwen-Coder-32B FP8 (現状の `vllm-qwen-coder`)
- **swap 候補** (`/test-generate --brainstorm` などで必要時):
  - Qwen-Coder-14B AWQ INT4 (高速ループ・観点抽出補助、5/5 検出)
  - DeepSeek-R1-Distill-Qwen-14B (online FP8 で起動、機密案件のレッドチーム)
- **swap 時間**: 30-60 秒 / モデル
- **代替案 E (32B INT4 化)**: **不採用** (品質劣化 20%、VRAM 節約 1.5 GiB のみで割に合わない)

### Phase 2 への引継ぎ事項

- `/test-generate --brainstorm` のモデル並列実行は **swap 順次** (同時ロード不可)
- 観点抽出デフォルト: API DeepSeek-R1 + Qwen-Coder-32B (現状) の 2 系
- `--with-distill` フラグで Distill FP8 をローカル併用 (機密案件用)
- `--with-gemini` opt-in 維持

### Phase 3 への引継ぎ事項

- 既存 vLLM (`vllm-qwen-coder`) の volume mount を `~/models/hub` から `~/.cache/huggingface` に移行 (HF cache 統一)
- DeepSeek-R1-Distill-Qwen-14B 用の vLLM unit を追加 (8001 ポート、online FP8 量子化、mml=16384)
- 14B AWQ INT4 用も同様に追加 (gpu-memory-utilization 0.50, mml=4096)
- swap 自動化スクリプト (現状の `/tmp/phase1a-vram-bench.sh` を参考に)

## 実行ログ

- VRAM 実測 raw: `/tmp/phase1a-vram-results.txt`
- 品質ベンチ raw: `/tmp/phase1b-quality-results.txt`
- DL ログ: `/tmp/phase1-model-dl.log`
- スクリプト: `/tmp/phase1a-vram-bench.sh`, `/tmp/phase1b-quality-bench.sh`

## 実行ログ

- VRAM 実測 raw: `/tmp/phase1a-vram-results.txt`
- DL ログ: `/tmp/phase1-model-dl.log`
- ベンチスクリプト: `/tmp/phase1a-vram-bench.sh`

## 落とし穴の記録 (新規)

1. **`~/models/hub` (vLLM docker volume) は root 所有**で elmo から書けない。HF download は `~/.cache/huggingface/hub` に。Phase 3 で vLLM の volume mount を後者に統一する。
2. **DeepSeek-R1-Distill-Qwen-14B は bf16 単独で 32GB VRAM に乗らない**。online FP8 が必須。AWQ INT4 版を見つけて切り替えるとさらに余裕が出る (community 版あり)。
3. **`--gpu-memory-utilization` のデフォルト 0.90 では並列ロード時に競合**。14B 単独測定では 0.50 まで下げて mml=16384 でも収まることを確認した。
