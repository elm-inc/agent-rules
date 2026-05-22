---
name: test-generate
description: 対象の関数・モジュールに対するテストケース列挙とテスト実装を生成する。ローカル LLM (Qwen2.5-Coder-32B) を主、DeepSeek-R1 を property-based test の不変条件発想に使う。mutation testing の生存変異を殺すテスト追加モードもあり
argument-hint: <対象ファイルまたは関数> [--property] [--mutants <生存変異リスト>]
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(curl *) Bash(jq *) Bash(cat *) Bash(find *) Bash(ls *) Bash(grep *) Read Write Edit
---

# テストケース・実装生成

対象コードに対し、**正常系・境界・異常系を列挙** → **テスト実装を生成** する。プロパティテスト不変条件の発想やミューテーションテスト対策モードも持つ。

## 使い分け

| モード | LLM | 用途 |
|---|---|---|
| 列挙 + 実装 (デフォルト) | Qwen2.5-Coder-32B (ローカル) | 通常のテスト生成 |
| `--property` | DeepSeek-R1 (発想) + Qwen (実装) | プロパティテスト不変条件 |
| `--mutants` | Qwen | 生存ミュータントを殺すテスト追加 |

## 前提

- ローカル: vLLM が稼働 (`$LOCAL_LLM_BASE_URL`)
- `--property` 使用時: `DEEPSEEK_API_KEY` 必須
- セットアップ: [`docs/setup/local-llm.md`](../../docs/setup/local-llm.md)

## 引数の解釈

`$ARGUMENTS` を以下のように解釈する:

1. **最初の引数**: 対象ファイルパス or `path:functionName`
2. **`--property`** → プロパティテスト不変条件モードを有効化
3. **`--mutants <path>`** → 生存ミュータントのリストファイルを読み込み対策

## 実行手順

### 1. テストフレームワーク検出

リポジトリのテストフレームワークを自動検出する (package.json / pyproject.toml / go.mod 等から):

```bash
# Python
if [ -f pyproject.toml ] && grep -q pytest pyproject.toml; then FRAMEWORK="pytest"; fi
# TypeScript/JS
if [ -f package.json ]; then
  grep -q vitest package.json && FRAMEWORK="vitest"
  grep -q jest package.json && FRAMEWORK="jest"
fi
# Go
[ -f go.mod ] && FRAMEWORK="go test"
```

property-based test ライブラリも検出:
- pytest → `hypothesis`
- vitest/jest → `fast-check`
- go → `gopter` or `testing/quick`

### 2. 対象コードの取得 + 既存テストの参照

```bash
# 対象関数のソース取得
cat "$TARGET_FILE"

# 既存の近接テスト (規約理解のため)
TEST_DIR=$(find . -type d \( -name "tests" -o -name "__tests__" -o -name "test" \) ! -path "*/node_modules/*" | head -3)
find "$TEST_DIR" -type f | head -5 | xargs -I {} sh -c 'echo "## {}"; cat "{}"'
```

### 3-A. 通常モード: テストケース列挙

ローカル LLM (Qwen) でケースを列挙:

```
あなたは熟練のテストエンジニアです。以下のコードに対して、テストケースを **網羅的に列挙** してください。

カテゴリごとに表形式で出力してください:
| カテゴリ | 入力 | 期待 | 重要度 |
|---|---|---|---|
| 正常系 (典型) | ... | ... | High |
| 正常系 (空) | ... | ... | High |
| 境界 (最小/最大) | ... | ... | High |
| 異常系 (型) | ... | ... | Medium |
| 異常系 (値域) | ... | ... | Medium |
| 並行 / 副作用 | ... | ... | High |

テストフレームワーク: {FRAMEWORK}
既存テストの規約 (参考): {EXISTING_TESTS_SNIPPET}

---
{TARGET_CODE}
---
```

### 3-B. `--property` モード: 不変条件発想

DeepSeek-R1 でプロパティテストの不変条件を発想:

```
あなたはプロパティベーステストに精通したエンジニアです。
以下のコードの **不変条件 (invariants)** と **メタモルフィック関係 (metamorphic relations)** を列挙してください。

例:
- ソート関数 → 出力は入力の置換 / 出力は単調 / 冪等性
- 逆関数の存在 (encode/decode, parse/format)
- 結合律 / 交換律 / 単位元
- 入力サイズに対する単調性

各不変条件について、{FRAMEWORK} で書く際の生成戦略 (どんな input generator を使うか) も提案してください。

---
{TARGET_CODE}
---
```

### 3-C. `--mutants` モード: ミュータント対策

生存ミュータントのリストを Qwen に渡してテスト追加:

```
以下は mutation testing で **生き残った変異 (テストで検出できなかったもの)** のリストです。
各変異を **殺す (テストで失敗させる)** ためのテストケースを生成してください。

---
変異リスト:
{MUTANTS}
---
対象コード:
{TARGET_CODE}
---
```

### 4. テスト実装の生成

列挙結果を Qwen に渡して **実装** させる:

```
以下のテストケース列挙に基づき、{FRAMEWORK} 形式でテスト実装を書いてください。
既存テストの規約 (import, setup, naming) に従ってください。

ケース列挙:
{ENUMERATION}

既存テスト規約:
{EXISTING_TESTS_SNIPPET}

対象コード:
{TARGET_CODE}
```

### 5. 出力とユーザー確認

- 列挙結果と実装を表示
- ユーザーに **保存先パス** を確認 (既存テスト隣 or 新規)
- 承認後、Write/Edit で保存

### 6. 生成テストの実行検証 (Phase 5 追加)

> **重要 (Phase 4 で判明)**: AI 生成 assertion は実コードと **一致しないことがある** (例: 期待 `"1分"` だが実装は `"1分0秒"`)。必ず実行して赤緑確認する。

```bash
# 1. テストをまず実行
pytest "$NEW_TEST_PATH" -v 2>&1 | tee /tmp/test-result.txt

# 2. 全部緑なら完了
if [ $? -eq 0 ]; then
  echo "✓ 全テスト pass"
  exit 0
fi

# 3. 赤テストがある場合、Claude に判断を仰ぐ:
#    - 実装側のバグ → 実装を直す
#    - assertion 側の誤り (AI の期待値間違い) → assertion を直す
#    - どちらか不明 → ユーザーに確認
echo "✗ 失敗テスト発見。実装 vs assertion のどちらが正しいか判断する:"
grep -E "FAILED|AssertionError" /tmp/test-result.txt
```

## Qwen context 制約への対処 (Phase 5 追加)

> **Phase 4 で判明**: vLLM の `--max-model-len 4096` 制約下で、入力 + 出力 > 4096 だと `VLLMValidationError`。

`max_tokens` を **動的に決定** する:

```bash
# vLLM の context 上限を取得
MAX_LEN=$(curl -s "${LOCAL_LLM_BASE_URL}/models" | jq -r '.data[0].max_model_len // 4096')

# 入力 token を推定 (粗く 4 chars/token)
INPUT_TOK=$(( ${#PROMPT} / 4 ))

# 安全マージン 100 を引いて出力 token 上限を決定
MAX_OUT=$(( MAX_LEN - INPUT_TOK - 100 ))
[ "$MAX_OUT" -lt 500 ] && MAX_OUT=500  # 最低 500 は確保
```

## API 呼び出し詳細

### Qwen (vLLM)

```bash
PAYLOAD=$(jq -n --arg model "${LOCAL_LLM_MODEL:-qwen-coder}" --arg content "$PROMPT" \
  '{model:$model, messages:[{role:"user", content:$content}], temperature:0.3, max_tokens:8192}')

curl -sf "${LOCAL_LLM_BASE_URL:-http://localhost:8000/v1}/chat/completions" \
  -H "Content-Type: application/json" -d "$PAYLOAD" \
  | jq -r '.choices[0].message.content'
```

### DeepSeek-R1

```bash
PAYLOAD=$(jq -n --arg content "$PROMPT" \
  '{model:"deepseek-reasoner", messages:[{role:"user", content:$content}], max_tokens:8192}')

curl -sf https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" -d "$PAYLOAD" \
  | jq -r '.choices[0].message.content'
```

## コマンド例

```bash
# 関数指定で通常テスト生成
/test-generate src/utils/date.ts:formatDuration

# ファイル全体
/test-generate src/payment/processor.py

# プロパティテスト
/test-generate src/algo/sort.ts --property

# ミュータント対策
/test-generate src/auth/token.py --mutants reports/mutants-survived.txt
```

## 注意事項

- 生成テストは **必ず人間 (or Claude) がレビュー** すること。AI 生成テストは表面的になりがち
- mutation test 連携は `mutmut` (Python) / `Stryker` (JS/TS) を別途セットアップ前提
- プロパティテストは初回学習コストが高い。導入は段階的に
- 生成された assertion がコードと同じ誤解をしていないか注意 (tautology 回避)
