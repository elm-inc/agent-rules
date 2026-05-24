# テスト工程の多モデル化 + ローカル量子化モデル併用 設計

- ADR: [0002-multi-model-test-generation](../adr/0002-multi-model-test-generation.md)
- Linear Project: [テスト工程の多モデル化 + ローカル量子化モデル併用](https://linear.app/elm-inc/project/テスト工程の多モデル化-ローカル量子化モデル併用-e3e9282c4778)
- Phases: [AGENT-10](https://linear.app/elm-inc/issue/AGENT-10) / [AGENT-11](https://linear.app/elm-inc/issue/AGENT-11) / [AGENT-12](https://linear.app/elm-inc/issue/AGENT-12) / [AGENT-13](https://linear.app/elm-inc/issue/AGENT-13)
- 制定日: 2026-05-24
- 状態: **設計フェーズ (実装未着手)**

## 1. 背景・目的

ADR-0001 で **レビュー** の多モデル化が完了 (Phase 1-5)。次のフェーズとして **テスト工程** を多モデル化し、合わせて **ローカル量子化モデル併用基盤** を整える。詳細な動機・代替案は ADR-0002 参照。

本ドキュメントは ADR-0002 で承認された方針の **実装計画** を示す。

## 2. スコープ

| 含む | 含まない |
|---|---|
| `/test-generate` の 2 モード化 (`--brainstorm` / `--implement`) | `/test-data` の多モデル化 (限定的補助のみ) |
| ローカル distill モデル評価 (DeepSeek-R1-Distill-Qwen-14B) | API DeepSeek-R1 の置換 (併用継続) |
| AWQ INT4 量子化モデル評価 (Qwen-Coder-14B) | 全 GPU 製品最適化 (RTX PRO 4500 前提) |
| vLLM 複数モデル同時ロード or swap 方式の確立 | 推論サーバの全体再設計 |

## 3. 役割分担 (テスト工程)

```
[① 観点・境界条件の抽出]            ← 多モデル並列 (新)
  /test-generate <target> --brainstorm
   ├→ DeepSeek-R1 (API or distill ローカル) で思考連鎖発想
   ├→ Gemini 2.5 Pro (1M context) で repo 横断 invariant 抽出
   └→ Qwen-Coder-32B (ローカル) で実装視点の網羅

  → 観点リスト (.md ファイル) として出力、重複マージ + 優先度付け

[② テストケース列挙]                ← 単一モデル
  Qwen-Coder-32B で観点リスト → 個別ケース化

[③ テスト実装 (コード生成)]          ← 単一モデル
  /test-generate <target> --implement <観点ファイル>
   → Qwen-Coder-32B (主) または Claude Opus 4.7 (本体)

[④ テストデータ生成]                ← 限定的補助
  /test-data <target>
   → Qwen-Coder-32B (主、現状維持)
   → schema が複数ファイル横断する場合のみ Gemini 補助
```

## 4. スキル仕様変更

### 4.1 `/test-generate` の引数体系

| 起動形 | 動作 | 互換性 |
|---|---|---|
| `/test-generate <target>` | 現状互換 (Qwen 単一で観点抽出 → ケース → 実装) | 既存ユーザー影響なし |
| `/test-generate <target> --brainstorm` | 観点抽出のみ、3 モデル並列、`.md` で出力 | 新規 |
| `/test-generate <target> --implement <観点ファイル>` | 観点ファイルを入力にコード生成 (Qwen 単一) | 新規 |
| `/test-generate <target> --brainstorm --models qwen,r1` | モデル指定 (絞り込み) | 新規 (任意) |

**観点ファイルフォーマット** (`.test-brainstorm.md`):

```markdown
# テスト観点: <target>

## 由来モデル別の生発想
### DeepSeek-R1 が挙げた観点
- ...
### Gemini が挙げた観点
- ...
### Qwen が挙げた観点
- ...

## マージ済み観点リスト (重複除去 + 優先度付け)
- [P0] ...
- [P1] ...
- [P2] ...

## カバレッジ評価
- 全モデル共通: N 件 (高信頼)
- 単一モデルのみ: N 件 (要レビュー)
```

### 4.2 `/test-data` は現状維持 + Gemini オプション

`--schema-wide` フラグ追加時のみ Gemini 補助。デフォルトは Qwen 単独 (現状互換)。

## 5. ローカル LLM 構成変更

### 5.1 採用モデル候補と実 VRAM

VRAM は**モデル重量だけでなく、KV cache (コンテキスト長次第で 2-8GB) + vLLM overhead (各 0.5-1GB) + CUDA scheduler (0.3-0.5GB) を含む実 VRAM** を Phase 1 で実測する。下表のレンジは公開情報・HuggingFace 実測値ベース:

| 用途 | モデル | 量子化 | 重量のみ | **実 VRAM (KV cache + overhead 込み)** | 採用根拠 |
|---|---|---|---|---|---|
| 実装・コード生成 (主) | Qwen2.5-Coder-32B | FP8 | ~23GB | **~26-30GB** | 現状維持、コード品質が最高 |
| 高速ループ・補助 | Qwen2.5-Coder-14B | AWQ INT4 | 6.2-7.5GB | **~9-12GB** | 単独運用または swap 用 |
| レッドチーム (新規) | DeepSeek-R1-Distill-Qwen-14B | AWQ INT4 | 6.2-7.5GB | **~9-12GB** | API R1 のローカル代替候補 |
| (代替案 E 採用時) 実装・コード生成 | Qwen2.5-Coder-32B | AWQ INT4 | ~16GB | **~19-22GB** | INT4 化で 3 モデル同時ロード可能化 |

### 5.2 ロード戦略 (3 案、Phase 1 ベンチマークで選定)

当初想定した「32B FP8 + 14B INT4 × 2 同時ロード = 33GB」は KV cache と overhead を含めると **実 36-42GB 必要で 32GB に絶対収まらない** (DeepSeek-R1 redteam 指摘)。以下 3 案を Phase 1 で実測比較する:

| 案 | 構成 | 実 VRAM | 長所 | 短所 |
|---|---|---|---|---|
| **A. swap 方式 (最も保守的)** | 32B FP8 常駐、14B 系は要求時 swap | ~26-30GB | 既存運用に追加少、品質維持 | 14B ロードに 10-15秒、`--brainstorm` レイテンシ増 |
| **B. 32B INT4 + 14B × 2 同時 (代替案 E)** | 全モデル INT4 化 + 同時ロード | ~27-34GB | 同時ロード成立、`--brainstorm` 高速 | 32B コード生成品質劣化リスク (要計測) |
| **C. 14B 1 種のみ追加** | 32B FP8 常駐 + 14B INT4 × 1 (distill or coder) | ~33-38GB ★ | 部分的多モデル化、設定簡単 | ★ KV cache 次第で OOM 余地、要 max-model-len 削減 |

**選定基準** (Phase 1 終了時):
- **品質第一**: A 案 (swap, FP8 維持)
- **品質許容範囲なら速度優先**: B 案 (代替案 E, 全 INT4 化)
- 「Qwen-Coder-32B INT4 のバグ検出率が FP8 比 -5% 以内」を満たせば B 案採用

### 5.3 並列実行の排他制御 (必須)

`/test-generate --brainstorm` は 1 リクエストで全モデルの VRAM を専有する。複数 worktree セッションから同時呼び出されると **即 OOM** (DeepSeek-R1 redteam Critical 指摘) のため、wrapper レイヤで排他必須:

```bash
# 例: flock を使った semaphore (concurrency = 1)
flock -w 600 /tmp/test-generate-brainstorm.lock \
  bash -c "python brainstorm.py $TARGET"
```

`--max-concurrency 2` を将来オプション化する余地はあるが、Phase 2 初期は **1 に固定**。

### 5.4 観測性 (healthcheck + ログ)

- 各 vLLM インスタンス (`:8000` `:8001` `:8002` 等) に対し `/health` エンドポイント polling する軽量 cron / systemd timer を追加
- 異常時は ntfy.sh などで notification (前掲の iPhone 通知基盤と同じ経路を再利用可)
- `nvidia-smi --query-gpu=memory.used --format=csv` を定期ログ化、VRAM 逼迫を事前検知

### 5.5 セキュリティ (モデル改ざん対策)

- HuggingFace からの DL 時、**公式組織アカウント** (Qwen, RedHatAI, deepseek-ai, deepseek-r1-distill-qwen-14b) のみ許可
- `safetensors` ファイルの SHA256 を HF Hub の API で取得・照合 (vLLM 起動前)
- 改ざん検知時は systemd unit を fail させ、人手介入を要求

## 6. 実装計画 (Phase 別)

### Phase 1: ベンチマーク (2-3 週間 ★ DeepSeek-R1 redteam で工数増)

- [ ] **VRAM 実測** (ロード戦略 A/B/C すべて測定):
  - 各モデル単独ロード時の実 VRAM (`nvidia-smi`)
  - 同時ロード時の実 VRAM (overhead + KV cache 込み)
  - `max-model-len` を 4096/8192/16384 で振って実測
- [ ] **Qwen-Coder-32B INT4 化の品質計測** (代替案 E 採否判断):
  - 対象: `/local-review` Phase 4 試運転バグ検出 (5 件仕込み)
  - 比較: 32B FP8 (現状) vs 32B AWQ INT4
  - 基準: バグ検出率 -5% 以内なら代替案 E 採用候補
- [ ] DeepSeek-R1-Distill-Qwen-14B 品質評価:
  - 対象: ADR-0001 Phase 4 設計レッドチーム問題
  - 比較: オリジナル DeepSeek-R1 (API)
  - 評価軸: Critical/High 検出数、応答時間、出力品質 (主観)
- [ ] Qwen-Coder-14B AWQ INT4 品質評価:
  - 対象: `/local-review` Phase 4 試運転バグ検出
  - 比較: 現行 32B FP8
  - 評価軸: バグ検出率、応答時間
- [ ] **ロード戦略選定** (A/B/C のいずれか):
  - 品質第一なら A (swap)、品質許容なら B (全 INT4)、中間なら C
- [ ] 結果を `docs/setup/notes/phase7-distill-eval.md` にレポート

### Phase 2: `/test-generate` 2 モード化 (1 週間)

- [ ] `--brainstorm` モード実装
  - 3 モデル並列実行 (asyncio または subprocess parallel)
  - 観点ファイル `.test-brainstorm.md` 生成
  - 重複マージ (LLM 1 回 or 単純 set 演算で実験)
- [ ] `--implement` モード実装
  - 観点ファイル読み込み → ケース列挙 → コード生成
  - 既存単一フローのリファクタリング
- [ ] 旧 (引数なし) 動作の後方互換維持
- [ ] `skills/test-generate/SKILL.md` 更新

### Phase 3: vLLM 構成更新 + ドキュメント (3-5 日)

- [ ] `docs/setup/local-llm.md` を複数モデル前提に書き換え
- [ ] systemd or docker compose で複数 vLLM サーバ起動
- [ ] 環境変数追加: `LOCAL_LLM_R1_BASE_URL` `LOCAL_LLM_CODER_14B_BASE_URL`
- [ ] `agent-rules/CLAUDE.md` の役割分担表を更新

### Phase 4: A/B 評価と ADR 採択判定 (2-3 週間)

- [ ] 既存 ai-workflow.md Phase 4 と同様の試運転実施
- [ ] `/test-generate --brainstorm` での観点カバレッジ計測
- [ ] API DeepSeek-R1 と distill ローカル版の同一タスク比較
- [ ] 月次 ROI 表に新スキル列追加 (`/test-generate --brainstorm`)
- [ ] ADR-0002 を **採択** ステータスに更新 (品質 OK なら)、または見直し

## 7. 想定コスト

### 追加クラウド API コスト

| 項目 | 試算 (上方修正) | 備考 |
|---|---|---|
| Gemini `/test-generate --brainstorm` × 月 10-20 回 | $5-20 | 1M context フル使用時 1 リクエスト $0.5-1 (DeepSeek-R1 redteam 指摘で上方修正) |
| (現状の他 API) | 変更なし | — |

**追加月額**: $5-20 程度 (ADR-0001 + $5-20 = 合計 $7-25/月)。ユーザー方針 (能力的に効果的なら拡張可) の範囲内だが、**Gemini 使用は opt-in に格下げ**:
- `/test-generate --brainstorm` のデフォルト並列モデルは DeepSeek-R1 + Qwen の 2 つ
- Gemini は `--brainstorm --with-gemini` 明示時のみ追加 (repo 横断 invariant が必要なケース)

### ローカル GPU 稼働

| 項目 | 試算 |
|---|---|
| 14B INT4 追加常駐 | アイドル時 +20-30W、推論時 +50-100W |
| 月電気代追加 | 500-1500 円 |

### セットアップ工数

| Phase | 想定工数 |
|---|---|
| Phase 1 ベンチマーク | 16-24 時間 |
| Phase 2 スキル実装 | 8-12 時間 |
| Phase 3 構成更新 | 4-8 時間 |
| Phase 4 評価 | 4-8 時間 (月次評価に組み込み) |

## 8. 成功指標 (KPI)

- `/test-generate --brainstorm` で「**単一モデルでは発見できなかった観点**」が 3 ヶ月で 5 件以上見つかる
- distill ローカル版 R1 が API R1 の **80% 以上の Critical 検出率** を維持
- 14B INT4 が 32B FP8 比 **品質 -5% 以内、速度 3 倍以上**
- 全体運用コスト追加が月 $5 + 電気代 1500 円以下に収まる
- 既存 `/test-generate <target>` の挙動が後方互換 (regression なし)

達成できなかった項目は ADR-0002 の見直しトリガー。

## 9. 落とし穴の予防 (ADR-0001 知見 + DeepSeek-R1 redteam 指摘)

| 落とし穴 | 予防策 |
|---|---|
| HuggingFace レート制限で DL ストール | `HF_TOKEN` 必須、`HF_HUB_ENABLE_HF_TRANSFER=1` (phase2-trial.md 参照) |
| online 量子化で OOM | pre-quantized (AWQ INT4) モデルを採用、online 量子化はしない |
| vLLM 複数インスタンスの port 競合 | 環境変数で明示分離 (8000/8001/8002) |
| 並列実行のタイムアウト連鎖 | 各モデルに個別タイムアウト (30s / 60s / 120s) + リトライ **最大 2 回** + 部分結果許容 |
| 観点ファイルの肥大化 | 重複マージ後 200 件超なら警告 + 優先度トップ N に絞る案内 |
| **同時アクセス OOM** (worktree 並列セッション) | `flock` セマフォで `/test-generate --brainstorm` の同時実行を **1 に制限** (§5.3) |
| **観点ファイルの Git 漏洩** | `.test-brainstorm.md` を**デフォルトで `.gitignore` 対象**、共有時のみ明示コミット |
| **HF モデル改ざん (サプライチェーン)** | 公式組織のみ許可 + `safetensors` SHA256 検証 (§5.5) |
| **vLLM サイレント障害** | `/health` エンドポイント polling + 異常時 push 通知 (§5.4) |
| **ロールバック手順未定義** | Phase 2 で `/test-generate` 旧版を `worktree/test-generate-legacy` ブランチに保全、不具合時は revert + force install |

## 10. オープン論点 (Phase 1 ベンチマーク結果次第)

- 14B INT4 が品質不足だった場合の代替: Qwen3-Coder 系 / DeepSeek-Coder-V2-Lite-Instruct
- distill R1 が品質不足だった場合: API R1 を主軸維持、ローカルは廃案
- 32B INT4 化 (代替案 E) でコード生成品質が落ちる場合: A 案 (swap) に決定
- `/test-generate --brainstorm` の出力フォーマットを Linear Issue 自動起票につなげるか
- 排他制御を flock から vLLM 側 `--max-num-seqs` に寄せるかの判断 (将来の `--max-concurrency` 拡張時)

## 11. 関連リンク

- [ADR-0001](../adr/0001-multi-llm-development-workflow.md)
- [ADR-0002](../adr/0002-multi-model-test-generation.md)
- [ai-workflow.md](ai-workflow.md): Phase 1-5 実績
- [docs/setup/local-llm.md](../setup/local-llm.md): vLLM 現行構成
- 関連スキル: `/test-generate` `/test-data` `/local-review` `/deepseek-redteam`
