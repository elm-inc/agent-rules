---
name: gemini-review
description: Gemini 2.5 Pro の長文コンテキスト (1M+ token) でリポジトリ横断レビューを行う。大規模リファクタ・複数ファイルの整合性・ADR とコードの drift・全体アーキテクチャ検証など、Claude/Codex の通常コンテキストに収まらない範囲で使う
argument-hint: [--scope <path or glob> | --diff [--base <branch>] | --adr <path>] [+ 観点]
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(curl *) Bash(jq *) Bash(cat *) Bash(find *) Bash(ls *) Read
---

# Gemini 2.5 Pro による長文コンテキスト・リポジトリ横断レビュー

Gemini 2.5 Pro (1M+ token コンテキスト) を使い、Claude/Codex の通常コンテキストでは収まらない範囲のレビューを行う。**多数ファイル横断 / ADR とコードの drift / 大規模設計変更** が主用途。

## 使用判断

通常のレビューは `/local-review` → `/codex-review` で十分。以下に該当する時のみこのスキルを使う:

- 変更が **10 ファイル以上** または **1000 行以上**
- 複数のサブシステムにまたがる
- `docs/adr/` や `docs/architecture/` との整合性を確認したい
- リポジトリ全体の **規約 / 命名 / 構造の一貫性** を見たい

該当しない場合は Claude が「`/local-review` または `/codex-review` で十分です」と案内する。

## 前提

- 環境変数 `GEMINI_API_KEY` が設定されていること
- 未設定なら https://aistudio.google.com/apikey で取得
- エンドポイント: `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent`

## 引数の解釈

`$ARGUMENTS` を以下のルールで解釈する:

1. **`--scope <path | glob>`** → 指定パス配下のファイルをすべて文脈に含めてレビュー
2. **`--diff`** (+ 任意で `--base <branch>`) → 差分 + 関連ファイル全文を文脈に含める
3. **`--adr <path>`** → 指定 ADR の決定事項と現コードの整合性をレビュー
4. **その他のテキスト** → 追加観点

## 実行手順

### 1. API キー確認

```bash
if [ -z "${GEMINI_API_KEY:-}" ]; then
  echo "ERROR: GEMINI_API_KEY が未設定です"
  echo "https://aistudio.google.com/apikey で取得し ~/.bashrc に追加してください"
  exit 1
fi
```

### 2. 文脈の収集

引数に応じて以下を `$CONTEXT` に組み立てる (ファイルごとに `## path/to/file.ts` ヘッダ + 全文を連結):

```bash
# --scope <path|glob>
find $SCOPE -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" \
  -o -name "*.go" -o -name "*.rs" -o -name "*.md" \) \
  ! -path "*/node_modules/*" ! -path "*/.git/*" ! -path "*/dist/*" \
  | while read f; do
      echo "## $f"
      cat "$f"
      echo ""
    done

# --diff [--base main]
echo "## 差分"
git diff "${BASE:-HEAD}"
echo ""
echo "## 変更ファイルの全文"
git diff --name-only "${BASE:-HEAD}" | while read f; do
  [ -f "$f" ] || continue
  echo "## $f"
  cat "$f"
  echo ""
done
# --base 省略時 (uncommitted) は untracked ファイルも収集
if [ -z "$BASE" ] || [ "$BASE" = "HEAD" ]; then
  git ls-files --others --exclude-standard | while read f; do
    [ -f "$f" ] || continue
    echo "## (untracked) $f"
    cat "$f"
    echo ""
  done
fi

# --adr <path>
echo "## ADR"
cat "$ADR_PATH"
echo ""
echo "## 関連コード (ADR で言及されているパス配下)"
# ADR から言及パスを推測して cat (手動で絞ってもよい)
```

トークン量の目安: 1 ファイル平均 500 行 = 約 5K token。**500 ファイルでも 2.5M token** で 1M 内に収まらない場合は --scope を絞る。

### 3. プロンプト組み立て

```
あなたはリポジトリ全体を把握したシニアレビュアーです。
以下のコンテキストには {対象種別: 指定ディレクトリ全体 | 差分+関連ファイル | ADR+関連コード} が含まれます。

通常のレビューでは見つけにくい以下の観点を **重点的に** 確認してください:

1. **横断的な不整合**: 同じ概念に複数の表現・命名・型がないか
2. **規約からの逸脱**: 既存パターン (エラー処理、ログ、テスト構造) からの逸脱はないか
3. **設計ドキュメントとの drift**: docs/adr や docs/architecture と実装が食い違っていないか
4. **依存関係の歪み**: レイヤー違反、循環依存、責務の漏れ込み
5. **重複と類似**: 既存ロジックの再実装、似て非なる関数の併存
6. **デッドコード / 未参照**: 不要になったコード・型・設定

各指摘について {ファイルパス:行番号} を必ず記載してください。
重大度 (High / Medium / Low) を付けてください。

追加観点: {ARGUMENTS_OR_NONE}

---
{CONTEXT}
---
```

### 4. Gemini API 呼び出し

```bash
PAYLOAD=$(jq -n \
  --arg content "$PROMPT" \
  '{
    contents: [{parts: [{text: $content}]}],
    generationConfig: {
      temperature: 0.2,
      maxOutputTokens: 8192
    }
  }')

curl -sf "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=$GEMINI_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" | jq -r '.candidates[0].content.parts[0].text'
```

### 5. 結果表示

レビュー結果をそのまま表示する。指摘ごとにファイルパスと行番号があるので、Claude 側で各指摘について簡潔に対処方針 (修正案 / 議論 / 却下) を 1 行付けてもよい。

## コマンド例

```bash
# apps/web 配下の全体レビュー
/gemini-review --scope apps/web

# 大規模 PR (10+ ファイル) のレビュー
/gemini-review --diff --base main

# ADR とコードの整合性確認
/gemini-review --adr docs/adr/0007-auth-rewrite.md

# 特定観点を強調
/gemini-review --scope packages/payment 決済の冪等性とリトライ戦略
```

## コスト

Gemini 2.5 Pro:
- Input: $1.25 / 1M token (200K まで) / $2.50 / 1M (超過分)
- Output: $10 / 1M token

500 ファイル (2.5M token) を 1 回投げると input $5 程度。**頻発させない用途**として設計済み。

## 注意事項

- 1M token 超のリポは `--scope` でサブツリーに絞る
- バイナリ・画像・大きな snapshot ファイルは除外する (`! -name "*.snap"` 等)
- 機密性が高い場合は Google AI Studio のデータ利用ポリシーを確認。`gemini-2.5-pro` の paid tier では学習に使われない
- 出力の指摘は対象が広い分、Claude/ユーザー側で優先度判断が必須
