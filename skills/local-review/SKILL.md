---
name: local-review
description: ローカル LLM (Qwen3-Coder-30B-A3B / vLLM) で差分の0次レビューを行う。コミット直前の雑なミス検出に使う。/codex-review より前段で安価・高速。秒オーダーで終わる。vLLM は普段停止しておりスキルが自動起動するため「停止中」でも実行可 (停止=利用不可ではない)
argument-hint: "[対象指定（例: --base main, --uncommitted, --commit <sha>） + 追加観点]"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(curl *) Bash(jq *) Bash(cat *) Bash(bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh*)
---

# ローカル LLM による 0 次コードレビュー

Qwen3-Coder-30B-A3B (MoE / AWQ 4bit, vLLM) で差分を高速レビューする。`/codex-review` の前段に挟み、明らかなバグ・型違反・未処理エラーを早期に検出する。

## 前提

- vLLM は**オンデマンド起動**。常駐させず、本スキルが `ensure-vllm.sh` で必要時のみ起動する (アイドル後は自動停止し GPU を解放)
- セットアップ・運用方式: [`docs/setup/local-llm.md`](../../docs/setup/local-llm.md)、設計判断: [`docs/adr/0005`](../../docs/adr/0005-on-demand-local-llm.md)
- 起動に失敗した場合 (GPU が他プロセスで使用中など) はユーザーに知らせて中止し、`/codex-review` を代替案として案内する

## 引数の解釈

`$ARGUMENTS` を以下のルールで解釈する:

1. **引数なし** → uncommitted な変更 (staged + unstaged) をレビュー
2. **`--base <branch>`** → 指定ブランチとの差分
3. **`--commit <sha>`** → 指定コミットの変更
4. **`--uncommitted`** → 明示的に未コミットを対象
5. **上記以外のテキスト** → 追加レビュー観点として併用

## 実行手順

### 1. vLLM の起動保証 (オンデマンド)

`ensure-vllm.sh` を呼ぶ。稼働中なら即進行、未稼働なら起動して healthy まで待機する (初回ロードは 1-2 分)。起動後はアイドル監視が常駐し、一定時間 (デフォルト 15 分) 使われなければ自動停止して GPU を解放する。

```bash
MODEL_NAME="${LOCAL_LLM_MODEL:-qwen-coder}"
BASE_URL="${LOCAL_LLM_BASE_URL:-http://localhost:8000/v1}"

if ! bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh; then
  echo "ERROR: vLLM を起動できませんでした (GPU が他プロセスで使用中の可能性)"
  echo "  → nvidia-smi で GPU を確認するか、/codex-review を代わりに使ってください"
  exit 1
fi
```

> 初回起動の待機が長い場合や、すぐ GPU を空けたい場合は `bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh stop` で即停止できる。

### 2. 差分の取得

引数に応じて以下のいずれかで取得:

```bash
# uncommitted (staged + unstaged + untracked)
{
  git diff HEAD
  # untracked ファイルは git diff に出ないので明示的に追加
  git ls-files --others --exclude-standard | while read -r f; do
    [ -f "$f" ] || continue
    echo ""
    echo "diff --git a/$f b/$f"
    echo "new file (untracked)"
    echo "--- /dev/null"
    echo "+++ b/$f"
    sed 's/^/+/' "$f"
  done
}

# base 指定
git diff "$BASE"...HEAD

# commit 指定
git show "$SHA"
```

差分が空の場合はその旨を伝えて終了する。

### 3. プロンプト組み立て

```
あなたは熟練のコードレビュアーです。以下の差分を **0 次レビュー** してください。
目的は明らかなバグ・型違反・未処理エラー・セキュリティリスクの早期検出です。

以下の観点で **重大度順** に箇条書きで報告してください:
1. バグ・ロジックエラー (条件式の反転、off-by-one、null 参照、競合状態)
2. 型・契約違反 (引数の型・値域、戻り値の扱い、None/null チェック漏れ)
3. 未処理エラー (例外吸い込み、リソースリーク、トランザクション漏れ)
4. セキュリティ (入力検証、SQL/コマンドインジェクション、シークレット露出)
5. 明白なパフォーマンス問題 (N+1、同期 I/O のループ、不要な再計算)

**重要**: 指摘がない場合は素直に「指摘なし」と答えてください。
スタイル指摘・命名の好み・refactor 提案は **含めない** でください (別レビュー層の担当)。

追加観点: {ARGUMENTS_OR_NONE}

---
{DIFF}
---
```

### 4. vLLM 呼び出し

> vLLM の `max_model_len` から動的に `max_tokens` を計算する (モデル載せ替えで context 上限は変わるため、ハードコードしない)。ADR-0017 で 4096 → 32768 に拡大済み。

```bash
# context 上限を取得 (現行 Qwen3-Coder-30B-A3B AWQ4bit は 32768)
MAX_LEN=$(curl -s "$BASE_URL/models" | jq -r '.data[0].max_model_len // 32768')
INPUT_TOK=$(( ${#PROMPT} / 4 ))
MAX_OUT=$(( MAX_LEN - INPUT_TOK - 100 ))
[ "$MAX_OUT" -lt 500 ] && MAX_OUT=500

# 差分が context を超えそうなら ファイル単位に分割を勧告
EST_TOTAL_TOK=$(( ${#PROMPT} / 4 ))
if [ "$EST_TOTAL_TOK" -gt "$MAX_LEN" ]; then
  echo "WARNING: 推定 ${EST_TOTAL_TOK} tok > context ${MAX_LEN} tok"
  echo "  → ファイル単位での分割実行を推奨。git diff --name-only で対象抽出して順次実行。"
fi

PAYLOAD=$(jq -n \
  --arg model "$MODEL_NAME" \
  --arg content "$PROMPT" \
  --argjson max_out "$MAX_OUT" \
  '{
    model: $model,
    messages: [{role: "user", content: $content}],
    temperature: 0.2,
    max_tokens: $max_out
  }')

curl -sf "$BASE_URL/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" | jq -r '.choices[0].message.content'
```

### 5. 結果表示

レビュー結果をそのままユーザーに表示する。Claude 側で **要約や追加コメントは付けない** (0 次レビューの目的は素早い検出であり、二重解釈を避ける)。

## コマンド例

```bash
# 未コミット変更を高速レビュー
/local-review

# main との差分
/local-review --base main

# セキュリティ観点を追加
/local-review --uncommitted セキュリティ重点

# 特定コミット
/local-review --commit abc1234
```

## 注意事項

- 大差分 (>20K token) はモデルのコンテキストを超えうる。その場合はファイル単位に分割して順次レビューする
- 推論時間は通常 5-30 秒。1 分以上かかる場合は vLLM の負荷を `nvidia-smi` で確認
- このスキルはあくまで **0 次**。重要 commit 前は `/codex-review` を続けて実行する
- スタイルや命名は対象外。それらは `ruff` `prettier` 等の linter で対応
