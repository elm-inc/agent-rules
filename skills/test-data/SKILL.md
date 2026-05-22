---
name: test-data
description: スキーマ・型定義 (Pydantic / TypeScript / DB schema) から、業務的に妥当なテストデータ・factory・fixture を生成する。faker と違い「入社日 < 退職日」のような関係制約も LLM が補完する。大量生成はローカル LLM のバッチ推論で行う
argument-hint: <スキーマファイル or 型名> [--count <N>] [--format factory|fixture|json]
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(curl *) Bash(jq *) Bash(cat *) Bash(find *) Bash(ls *) Bash(grep *) Read Write
---

# 業務的に妥当なテストデータ生成

スキーマや型定義からテストデータ・factory・fixture を生成する。**型レベルの validity だけでなく、関係制約 (入社日 < 退職日, 注文金額 > 0, 顧客 ID の参照整合) を LLM が補完**する点が faker と異なる。

## 前提

- ローカル: vLLM が稼働 (`$LOCAL_LLM_BASE_URL`)
- 大量生成 (>100) はローカルのバッチ推論で行う (クラウドだとコスト・速度が劣る)
- セットアップ: [`docs/setup/local-llm.md`](../../docs/setup/local-llm.md)

## 引数の解釈

`$ARGUMENTS` を以下のように解釈する:

1. **最初の引数**: 対象スキーマファイル or 型名 (`path:TypeName`)
2. **`--count <N>`** → 生成件数 (デフォルト 10)
3. **`--format <factory|fixture|json>`** → 出力形式
   - `factory`: factory-boy / fishery などのファクトリ関数
   - `fixture`: pytest fixture / vitest test fixture
   - `json`: 生 JSON 配列

## サポートする入力スキーマ

| 種別 | 検出 |
|---|---|
| Pydantic | `class X(BaseModel)` |
| dataclass | `@dataclass` |
| TypeScript interface/type | `interface X {}` / `type X = {}` |
| Zod schema | `z.object({...})` |
| Prisma / Drizzle schema | `model X {}` |
| SQL DDL | `CREATE TABLE` |
| JSON Schema | `.json` with `$schema` |

## 実行手順

### 1. スキーマ取得 + 関連スキーマも収集

```bash
# 対象スキーマファイル
cat "$SCHEMA_FILE"

# 関連参照型 (外部キー、ネスト型) を grep で抽出
grep -E "ForeignKey|references|Relation" "$SCHEMA_FILE" \
  | while read line; do
      # 参照先の型名を抽出して該当ファイルを cat
      ...
    done
```

### 2. 出力形式の規約検出

既存の test/factories ディレクトリから命名・パターンを参考にする:

```bash
find . -type d \( -name "factories" -o -name "fixtures" -o -name "__fixtures__" \) \
  ! -path "*/node_modules/*" | head -3 | xargs -I {} ls {} | head -10
```

### 3. プロンプト組み立て

```
あなたはテストデータ設計に長けたエンジニアです。
以下のスキーマに対して、テストデータを {COUNT} 件生成してください。

## 制約条件

- 型レベルの妥当性 (型・必須・enum) は完全に守る
- **業務的に妥当な関係制約** を考慮:
  - 日付の前後関係 (作成日 < 更新日 < 削除日, 開始日 < 終了日)
  - 金額の符号と単位 (注文金額 > 0, 返金は元注文以下)
  - 参照整合性 (FK の値は存在する親レコードを指す)
  - enum の現実的分布 (status の 90% は "active" など)
- **多様性**: 似たデータの羅列を避け、エッジに近い値 (空文字、最小/最大、Unicode 含む文字列) も混ぜる
- 個人情報は **完全なダミー** (実在する名前・メール・電話を絶対に使わない)

## 出力形式

形式: {FORMAT}
- factory: {ファクトリライブラリ検出結果} のスタイルで関数として
- fixture: {テストフレームワーク} の fixture 形式
- json: JSON 配列

既存規約:
{EXISTING_PATTERN_SNIPPET}

---
スキーマ:
{SCHEMA_CONTENT}

関連スキーマ:
{RELATED_SCHEMAS}
---

最後に、生成データの **多様性チェック表** (各フィールドの値分布) も出力してください。
```

### 4. Qwen (vLLM) 呼び出し

```bash
PAYLOAD=$(jq -n --arg model "${LOCAL_LLM_MODEL:-qwen-coder}" --arg content "$PROMPT" \
  '{model:$model, messages:[{role:"user", content:$content}], temperature:0.6, max_tokens:16384}')

curl -sf "${LOCAL_LLM_BASE_URL:-http://localhost:8000/v1}/chat/completions" \
  -H "Content-Type: application/json" -d "$PAYLOAD" \
  | jq -r '.choices[0].message.content'
```

**`temperature: 0.6`** にしているのは、多様性確保のため (レビュー系の 0.2 より高め)。

### 5. 大量生成 (N > 100) の最適化

100 件超の場合はバッチに分けて並列リクエスト:

```bash
BATCH=20
ROUNDS=$(( ($COUNT + $BATCH - 1) / $BATCH ))

for i in $(seq 1 $ROUNDS); do
  # seed を変えて呼び出し
  curl ... &
done
wait

# 結果をマージ・重複排除
```

vLLM は並列リクエストを効率的に処理できるため、ローカルなら 1000 件でも数分。

### 6. 出力とユーザー確認

- 生成データと多様性チェックを表示
- 保存先パスを確認 (既存 factories ディレクトリ隣)
- 承認後 Write で保存
- 可能なら 1 件だけバリデーション通過確認:

```bash
# 例: Pydantic
python -c "from schema import User; import json; [User(**d) for d in json.load(open('$OUT'))]"
```

## コマンド例

```bash
# Pydantic 型から 50 件 factory 生成
/test-data app/models/user.py:User --count 50 --format factory

# Prisma schema からテスト用 JSON
/test-data prisma/schema.prisma --count 20 --format json

# TypeScript interface から vitest fixture
/test-data src/types/order.ts:Order --format fixture

# SQL DDL から大量データ
/test-data db/migrations/001_init.sql --count 1000 --format json
```

## 注意事項

- 個人情報の取り扱い: 生成データは **必ず完全ダミー**。実データの匿名化代替ではない
- 関係制約の網羅は LLM の判断に依存。**重要なテストでは生成後に制約検証 script を通す**
- 大量生成は GPU 使用率が上がる。他のスキル (`/local-review` 等) と並行実行に注意
- 生成データに偏りが残る場合は seed や temperature を調整して再生成
