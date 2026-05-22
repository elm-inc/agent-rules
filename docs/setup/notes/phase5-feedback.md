# Phase 5: 試運転フィードバック反映

Linear: [AGENT-5](https://linear.app/elm-inc/issue/AGENT-5)
Branch: `worktree/agent-5-phase5-feedback`
Started: 2026-05-22

Phase 4 試運転で見つかった具体的問題に対する **スキル本体の改善** を実施。プロンプト本体・パラメータ調整が中心 (中期最適化は Phase 6 引継ぎ)。

## 変更サマリ

| 対象 | 変更内容 | Phase 4 で観測された問題 |
|---|---|---|
| `skills/gemini-review/SKILL.md` | maxOutputTokens 4096 → **8192**、thinking 仕様明記、`thinkingBudget: 0` の選択肢追加、コスト記述に thinking 込みコスト反映 | thinking で出力枯渇 (4093 思考 → 出力 0)、コスト誤算 |
| `skills/test-data/SKILL.md` | プロンプト全面改訂: **件数指定**で分布精度、過剰解釈禁止を明示、**地域多様性** (日/欧米/その他) 要求、ダミー個人情報の規約 | 70/20/10 指示 → 50/30/20 (乖離)、SUSPENDED に termination_date (過剰解釈)、anglo-saxon 偏重 |
| `skills/test-generate/SKILL.md` | **動的 `max_tokens` 計算** (context - input - 100)、生成テストの **実行検証フロー** を追加 (assertion 誤り判定) | `VLLMValidationError` (4097 > 4096)、AI assertion が実コードと不一致 |
| `skills/local-review/SKILL.md` | 動的 `max_tokens` 計算、大差分検出 + 分割勧告 | (予防策) Phase 2 で context 4096 になり、ハードコード 4096 だと overflow リスク |

## 変更の Why と How

### 1. `/gemini-review` thinking 対応

**Why**: Phase 4 で `maxOutputTokens: 4096` 設定時に、thinking が 4093 token を消費し本来の応答が 0 token になった。SKILL がこの挙動を文書化していなかったため、利用者が同じハマりを繰り返す。

**How**:
- `maxOutputTokens: 8192` を下限に設定 (内訳 thinking ~4000 + output ~4000)
- thinking 消費量・課金単価 (output 料金扱い) を明記
- 簡潔指摘で十分な用途向けに `thinkingConfig.thinkingBudget: 0` の選択肢を追加

### 2. `/test-data` プロンプト改訂

**Why**: Phase 4 で 3 種類の問題:
1. 「70%/20%/10%」と指示しても実際は 50/30/20 になる (LLM は分布指示が苦手)
2. 「status==deleted の場合のみ termination 必須」と書いても、SUSPENDED や ACTIVE にも termination_date を入れる (過剰解釈)
3. 名前が "Alice Johnson" "Bob Smith" など anglo-saxon に偏重

**How**:
- 分布を **件数で指定** (「10 件中 7 件 ACTIVE」)
- 過剰解釈禁止を **明示の禁止条項** として記載 (「それ以外では null にする」)
- 地域多様性を **例示で要求** (日/欧米/その他 3 系統)
- 個人情報の **リザーブドメイン強制** (`*@example.com`, `*@test.invalid`)
- 多様性チェック表に **「想定との乖離」列** を追加

### 3. `/test-generate` 実行検証フロー

**Why**: Phase 4 で AI が「`format_duration(60) → '1分'`」のように期待値を生成したが、実装は `'1分0秒'` を返す可能性が高い。生成テストをそのまま信用するとバグを見逃す。

**How**:
- 生成 → 保存 → **`pytest` 実行 → 赤緑判定** を必須プロセスに
- 赤テストには 3 つの可能性:
  - 実装側のバグ (修正対象)
  - assertion 側の AI 誤り (修正対象)
  - 不明 (ユーザー判断)
- 各場合の判断手順を明記

### 4. 動的 `max_tokens` (両 Qwen スキル)

**Why**: Phase 2 で vLLM の `--max-model-len` を 32768 → 4096 に下げたが、SKILL の `max_tokens: 4096` ハードコードと衝突 (`入力 97 + 4000 > 4096` で overflow)。Phase 5 以降 max_model_len が変動する可能性もある。

**How**:
- `/v1/models` から `max_model_len` を取得
- 入力長を推定 (4 chars/token の近似)
- `max_out = max_model_len - input_tok - 100` (100 はマージン)
- 最低 500 を確保

## 完了条件

- [x] `/gemini-review`: thinking 対応、デフォルト 8192、thinkingBudget 0 選択肢
- [x] `/test-data`: プロンプト改訂 (件数指定、過剰解釈禁止、地域多様性、ダミー強制)
- [x] `/test-generate`: 動的 max_tokens、実行検証フロー
- [x] `/local-review`: 動的 max_tokens、大差分の分割勧告
- [x] 変更サマリ・Why・How を本文書に記録

## 残課題 → Phase 6

### 中期最適化 (Phase 2 関連)
- Qwen CPU offload 6GB → 3-4GB (速度 6 tokens/sec の改善)
- Qwen `--max-model-len` 4096 → 8192 (KV cache 拡張)
- デスクトップ GPU プロセス停止検討

### ROI 評価 (Phase 6 本来の役割)
- 1-2 ヶ月運用後の検出/生成品質の追跡
- スキル別のコスト集計
- 「やめても困らないスキル」の特定

### 追加機能 (任意)
- `/multi-review`: 複数 LLM を並列実行してマージ
- `/local-review` の pre-commit hook 自動化
- 試運転の CI 自動化 (回帰検出)

## 検証推奨

本変更は SKILL の **指示文** だけを更新したため、`/gemini-review` 等を実行した時の **出力品質変化** で評価する必要がある。Phase 6 (ROI 振り返り) で再試験を推奨。

実機での簡易再確認は以下で可能:
```bash
# /test-data 改訂版の動作確認
samples/user_schema.py に対して /test-data を実行し、
- ACTIVE/SUSPENDED/DELETED の件数が指定通り (70/20/10)
- DELETED 以外で termination_date が null
- 名前に日本/欧米/その他が混在
が確認できれば成功。
```
