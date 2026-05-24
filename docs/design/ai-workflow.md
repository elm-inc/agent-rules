# AI 開発ワークフロー (多層・多モデル) 設計

- Linear Project: [AI 開発ワークフロー多層化](https://linear.app/elm-inc/project/ai-開発ワークフロー多層化-5d5bc734ffcd)
- ADR: [0001-multi-llm-development-workflow](../adr/0001-multi-llm-development-workflow.md)
- 制定日: 2026-05-22
- 状態: **運用開始 (Phase 1-5 完了)、ROI 評価中**

## 1. 背景・目的

AI に開発・レビュー・検証を任せる比率が上がるため、**単一モデル依存をやめて多層化** する。実装は Claude Opus 4.7 のまま、レビュー・テスト生成を複数ベンダーの LLM (Anthropic / OpenAI / Google / DeepSeek / ローカル Qwen) で分担する。

Claude と GPT は学習分布が近く同じ間違い方をしやすいため、Gemini と DeepSeek を混ぜて思考の多様性を確保する。さらに pre-commit hooks 等の **機械検証 (非 AI)** を併用し、**3 層 (機械・LLM・人間)** で品質を担保する。

## 2. 採用したモデル・スキル

| ロール | モデル / ツール | スキル | 採用理由 |
|---|---|---|---|
| 実装 (主) | Claude Opus 4.7 | (Claude Code 本体) | 長文推論・コード横断、現状の最高性能枠 |
| 0 次レビュー | ローカル Qwen2.5-Coder-32B (vLLM/FP8) | `/local-review` | コスト 0、機密データ送信不要、無制限回せる |
| セカンドオピニオン | Codex (GPT-5) | `/codex-review` 他 | Anthropic と別ベンダー、修正提案が具体的 |
| 設計レッドチーム | DeepSeek-R1 (API) | `/deepseek-redteam` | 思考連鎖で深い問題発見、$0.007/回 と激安 |
| リポ横断 | Gemini 2.5 Pro (1M context) | `/gemini-review` | cross-file 視点で唯一無二の指摘 |
| テスト生成 | Qwen (主) + R1 (property) | `/test-generate` | 大量生成にローカル、不変条件発想にクラウド |
| テストデータ | Qwen (バッチ) | `/test-data` | 関係制約推論 + コスト 0 で大量生成 |
| 機械検証 | pre-commit hooks | (各リポで設定) | AI と独立した第 3 層 |

## 3. 運用フロー (実績ベース)

```
[設計]
  Claude が docs/design/foo.md 起草
   ├→ /deepseek-redteam で盲点炙り出し
   └→ (任意) /codex-audit で実装視点ツッコミ

[実装]
  Claude Opus 4.7 で実装

[コミット前]
  /local-review                      ← 0 次 (秒)
  pre-commit hooks (型/lint/semgrep) ← 機械
  (必要時) /test-generate            ← テスト追加
  /codex-review                      ← セカンドオピニオン
  (必要時) /gemini-review            ← リポ横断

[実行検証]
  /verify, E2E テスト
```

軽微な変更では `/local-review` + pre-commit のみで十分。`/gemini-review` は 10+ ファイル変更や ADR drift 疑い時のみ。

## 4. ベンチマーク実績 (Phase 4 試運転)

| スキル | LLM | 入力 tok | 出力 tok | 思考 tok | 応答時間 | 1 回コスト |
|---|---|---|---|---|---|---|
| `/local-review` | Qwen2.5-Coder-32B FP8 | 750 | 374 | — | 64.5s | $0 |
| `/deepseek-redteam` | DeepSeek-R1 | 691 | 2853 | 2621 chars | 42.3s | $0.007 |
| `/gemini-review` | Gemini 2.5 Pro | 1453 | 1196 | 3688 | 43.6s | $0.051 |
| `/test-generate` | Qwen | 425 | 1213 | — | 202s | $0 |
| `/test-data` | Qwen | 464 | 1312 | — | 219s | $0 |

### 検出品質
- `/local-review`: 仕込み 5 バグ全検出 ✅
- `/deepseek-redteam`: 12+ Critical/High 発見、HS256→RS256 等の代替案提案
- `/gemini-review`: **cross-file 固有の指摘** (型不整合・drift・dead code) — 他では検出不能
- `/test-generate`: 14 ケース + 境界値網羅、ただし AI assertion 要 review
- `/test-data`: 関係制約守る、Phase 5 でプロンプト改訂済

## 5. 振り返り (Phase 4-5 時点)

### 何が効いたか
- **DeepSeek-R1 の高 ROI**: 7 円で設計の致命的問題を発見。`/codex-review` と組み合わせると groupthink を効果的に防ぐ
- **Gemini の cross-file 視点**: 単一ファイルでは見えない drift を確実に検出。コストは高いが「使い所」が明確
- **ローカル Qwen の常駐**: 0 次レビューを無限に回せる安心感。機密コードも送信不要
- **トークンファイル方式** (`~/.*_token` perms 600 + `env-snippet.sh`): バックアップ漏洩リスク低減

### 何が効かなかったか・課題
- **Qwen 推論速度 6 tokens/sec が律速** — `/test-generate` `/test-data` で 200 秒超え
  - 原因: CPU offload 6GB の PCIe shuttle
  - Phase 6+ 対策: offload 3-4GB に削減、または 14B モデル切替検討
- **Gemini thinking コスト** — output tokens の 3 倍が thinking で消費
  - Phase 5 で `thinkingConfig.thinkingBudget: 0` オプション追加済
- **Qwen max_model_len 4096 制約** — KV cache 不足で縮小せざるを得なかった
  - Phase 6+ 対策: デスクトップ GPU 解放 + max_model_len 8192 に拡張

### 落とし穴の記録
1. **HuggingFace unauthenticated レート制限** — 17GB で DL ストール。HF_TOKEN 必須
2. **online FP8 量子化で OOM** — 32B モデルは pre-quantized FP8 必須 (RedHatAI 等)
3. **Gemini 2.5 Pro は無料枠なし** — billing 必須 (Prepay or Standard)
4. **DeepSeek は前払い** — $2 入金必要
5. **Gemini thinking デフォルト有効** — maxOutputTokens 不足で出力 0
6. **Qwen context 制約と max_tokens のハードコード** — `VLLMValidationError` 注意

## 6. コスト見通し

### ローカル LLM
- GPU 稼働 24h 想定 (idle 30W、推論時 200W)
- 月電気代: 約 1000-3000 円 (日本平均単価)
- API コスト: 0

### クラウド LLM (1 開発者あたり 1 ヶ月想定)
| API | 月の想定使用 | 月額 |
|---|---|---|
| Claude (Anthropic) | 既存 | (既存) |
| Codex (OpenAI) | 既存 | (既存) |
| Gemini 2.5 Pro | `/gemini-review` × 10-20 回 | $1-2 |
| DeepSeek-R1 | `/deepseek-redteam` × 30-50 回 | $0.5-1 |

**追加コスト**: 月 $2-3 程度の想定 (実測は Phase 6+ で更新)。

## 7. 次の改善案 (Phase 5 引継ぎ + 今後)

### 短期 (Phase 5 で対応済)
- [x] Gemini maxOutputTokens 8192 デフォルト化
- [x] `/test-data` プロンプト改訂 (件数指定、地域多様性、過剰解釈防止)
- [x] `/test-generate` 動的 max_tokens + 実行検証フロー
- [x] `/local-review` 動的 max_tokens + 大差分分割勧告

### 中期 (Phase 6+)
- [ ] Qwen CPU offload 削減 (6GB → 3-4GB)、max_model_len 8192 拡張
- [ ] デスクトップ GPU プロセス停止検討 (Xorg・gnome-shell)
- [ ] `/multi-review` (複数 LLM 並列実行 + マージ)
- [ ] `/local-review` の pre-commit hook 自動化
- [ ] 試運転の CI 自動化 (回帰検出)

### 長期
- [ ] AWQ INT4 量子化モデル評価 (Qwen の速度改善)
- [ ] vLLM bench で 14B vs 32B の品質/速度トレードオフ実測
- [ ] 組織コンプライアンス確認 (DeepSeek 中国経由の許容範囲)

## 8. 実運用データ追記欄

> **このセクションは月次で更新する。** 1-2 ヶ月運用後の実データに基づき、上記の見積を補正・ROI を確定する。

### 月別使用頻度

| 月 | `/local-review` | `/codex-review` | `/deepseek-redteam` | `/gemini-review` | `/test-generate` | `/test-generate --brainstorm` ★ | `/test-data` |
|---|---|---|---|---|---|---|---|
| 2026-05 (本月、暫定) | — | — | — | — | — | 1 (Phase 8 試運転) | — |
| 2026-06 | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

★ ADR-0002 採択 (2026-05-24) で追加された新モード。詳細: [phase8-brainstorm-trial.md](../setup/notes/phase8-brainstorm-trial.md)

### 月別コスト集計

`scripts/track-cost.sh` で集計 (Phase 6 雛形)。

| 月 | Gemini | DeepSeek | 合計 |
|---|---|---|---|
| 2026-05 | TBD | TBD | TBD |
| 2026-06 | TBD | TBD | TBD |

### ROI 判定 (3 ヶ月後)

- 各スキルの「防いだバグ数」を主観評価
- 「やめても困らない」スキルがあれば statement とともに削除候補に
- 新規追加候補があれば追記

## 9. 関連リンク

- ADR: [0001-multi-llm-development-workflow.md](../adr/0001-multi-llm-development-workflow.md)
- Phase 別実行記録:
  - [Phase 2: vLLM セットアップ](../setup/notes/phase2-trial.md)
  - [Phase 3: クラウド API セットアップ](../setup/notes/phase3-trial.md)
  - [Phase 4: 試運転と検証](../setup/notes/phase4-trial.md)
  - [Phase 5: フィードバック反映](../setup/notes/phase5-feedback.md)
- Linear Project: https://linear.app/elm-inc/project/ai-開発ワークフロー多層化-5d5bc734ffcd
- GitHub Branch: `feat/linear-skills`
