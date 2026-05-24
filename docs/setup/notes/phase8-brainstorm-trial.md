# Phase 8: `/test-generate --brainstorm` 試運転と評価

- Linear: [AGENT-13](https://linear.app/elm-inc/issue/AGENT-13)
- ADR: [0002-multi-model-test-generation](../../adr/0002-multi-model-test-generation.md) (採択 2026-05-24)
- 設計: [multi-model-test-pipeline](../../design/multi-model-test-pipeline.md)
- Phase 1 結果: [phase7-distill-eval.md](phase7-distill-eval.md)
- 実施日: 2026-05-24

## 目的

ADR-0002 採択後の `/test-generate --brainstorm` (Phase 2 で実装) を試運転し、KPI 達成度を評価する。設計の §8 で定めた KPI:

- 3 ヶ月で「単一モデルでは発見できなかった観点」が 5 件以上発見できる
- distill ローカル版が API R1 の 80% 以上の Critical 検出率
- 14B INT4 が 32B FP8 比で品質 -5% 以内、速度 3 倍以上
- 全体運用コスト追加が月 $5 + 電気代 1500 円以下
- 既存 `/test-generate <target>` 後方互換 (regression なし)

## 試運転 1: `format_duration` 関数の観点抽出

### 対象

```python
# samples/date_utils.py
def format_duration(seconds: int) -> str:
    """秒数を人間可読な形式に変換する。"""
    ...
```

### モード

`/test-generate samples/date_utils.py:format_duration --brainstorm` (デフォルト並列 2 モデル)

### 結果

| モデル | 観点数 | 所要 | 入力 tok | 出力 tok | 思考 tok | コスト |
|---|---|---|---|---|---|---|
| DeepSeek-R1 (API) | **50 観点** (詳細・深掘り) | 52s | 531 | 4999 | 2275 | $0.007 |
| Qwen-Coder-32B FP8 (local) | **25 観点** (簡潔・一部 irrelevant) | 122s | 577 | 715 | — | $0 |

### カバレッジ分析

- **全モデル共通の観点**: 約 15 件 (0秒/1秒/60秒/3600秒/86400秒/3661秒/90061秒、負の整数、None、型違反、idempotency など基本)
- **DeepSeek-R1 のみ発見した観点**: 約 35 件
- **Qwen のみ発見した観点**: 約 5 件 (うち 5 件中 5 件が文脈不適切 - SQL injection / auth bypass / 空コレクション / 循環参照)

### 重要発見: 実装バグの発見

DeepSeek-R1 が**観点 49** で format_duration の **docstring と実装の不一致** を指摘:

```
seconds=86400 (ちょうど 1 日) の場合:
  - docstring 期待: "1日0時間"
  - 実装結果:      "1日0時間0分"  ← `if minutes or (days or hours) and secs == 0` が真になる
```

Qwen-Coder-32B はこのバグを発見できなかった。**多モデル化の典型的な ROI 事例**。

### KPI 達成度

| KPI | 状況 |
|---|---|
| 単一モデルで発見できない観点 5 件以上 (3 ヶ月で) | ✅ 既に 1 サンプルで **観点 41, 43-45, 49 の 5 件発見** |
| distill R1 が API R1 比 80% Critical 検出率 | △ Phase 1b で 60-80% (機密案件用ローカル代替として実用) |
| 14B INT4 が 32B FP8 比 品質 -5%、速度 3 倍 | ⚠ 品質 -0% (5/5 検出) 達成、ただし速度は (Qwen-Coder-14B INT4 を /local-review で計測しないと未確認) |
| 追加コスト 月 $5 + 電気代 1500 円以下 | ⚠ Gemini 使用未確認、現状 R1 のみ使用で月 $0.5-1 想定 |
| 後方互換 (regression なし) | ✅ 引数なし呼び出しは旧挙動を維持、SKILL.legacy.md として旧版保全 |

総合: **2 個 ✅ / 3 個 △⚠** → ADR-0002 採択は妥当、月次評価で △ を追跡。

### Qwen の観点品質に関する注意事項

Qwen-Coder-32B は**文脈に対して不適切な観点を提示しがち**:
- format_duration (int → str の純粋関数) に「SQL injection」「auth bypass」「空コレクション」「循環参照」を挙げた
- 観点ファイルマージ時に Claude が irrelevant なものを除外する必要がある
- プロンプト改善余地: 「対象がドメインモデルか純粋関数かを判断して観点カテゴリを取捨選択する」追加指示

## 試運転 2: A/B 比較 — API R1 vs Distill ローカル

Phase 1b で実施済み:
- 同じ design redteam タスク (本 design ドキュメント) で比較
- API R1: 6 観点 (Critical 2 件)
- Distill FP8 local: 4 観点 (Critical 1 件、High 1 件で Critical に格下げ)
- → Distill は API の 60-80% 相当、機密案件で使える品質

詳細: [phase7-distill-eval.md](phase7-distill-eval.md#7-distill-fp8-は-api-r1-の-60-80-品質機密案件用に採用候補)

## 月次 ROI 表への追加列

`docs/design/ai-workflow.md` §8 に以下の列を追加:

| スキル | 想定使用頻度 | 月額コスト |
|---|---|---|
| `/test-generate --brainstorm` (R1 + Qwen) | 月 10-20 回 | $0.5-1 |
| `/test-generate --brainstorm --with-distill` | 月 5-10 回 (機密のみ) | $0 (ローカル) |
| `/test-generate --brainstorm --with-gemini` | 月 5-10 回 (repo 横断のみ) | $5-20 ★ |
| `/test-generate --implement` | 月 20-30 回 | $0 (ローカル) |

★ Gemini 使用は opt-in。デフォルト 2 モデル並列で十分なケースが多い。

## ADR-0002 採択判定

- ロード戦略 A 案 (swap): ✅ Phase 1 で確定済
- 多モデル化の効果: ✅ 試運転 1 で実証 (実装バグ発見)
- 残課題: 14B INT4 速度実測、Gemini 統合の運用判断
- **結論: ADR-0002 採択は妥当**。月次評価 (Phase 5 と同様の試運転を再実施) で継続検証

## 実行ログ

- 試運転スクリプト: `/tmp/phase4-brainstorm-trial.sh`
- 試運転結果: `/tmp/phase4-test-brainstorm.md`
- 個別出力: `/tmp/phase4-r1.md`, `/tmp/phase4-qwen.md`

## 次のアクション (運用引継ぎ)

- [ ] AGENT-14 (systemd unit 化) — 運用安定化
- [ ] AGENT-15 (healthcheck cron インストール + iPhone push) — 観測性確立
- [ ] AGENT-16 (HF cache volume 統一) — Phase 7 で判明した発散を解消
- [ ] 月次 ROI 評価 (Phase 9, 10...) で `/test-generate --brainstorm` の発見件数と Gemini 使用頻度を継続計測
