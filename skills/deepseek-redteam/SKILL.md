---
name: deepseek-redteam
description: DeepSeek V4-Pro (思考モード) で設計やコード変更の盲点・代替案・破綻ケースを炙り出すレッドチーム。docs/design/*.md や差分に対して「致命的な見落としは?」を問う。Anthropic/OpenAI 系と異なる学習分布なので groupthink 対策に有効
argument-hint: "<対象ファイル | --diff [--base <branch>] | --design <path>> [+ 観点]"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(curl *) Bash(jq *) Bash(cat *) Bash(ls *) Read
---

# DeepSeek V4-Pro によるレッドチーム

DeepSeek V4-Pro の思考モードを使い、設計や実装の **致命的な盲点・代替案・破綻ケース** を洗い出す。Claude / GPT と学習系統が異なるため、同じ間違い方をしにくいのが利点。

## 前提

- API キー: 環境変数 `DEEPSEEK_API_KEY` → 無ければ `~/.deepseek_token` (perms 600) の順に探す
- どちらも無ければ https://platform.deepseek.com/api_keys で取得するよう案内
- `DEEPSEEK_API_KEY= /deepseek-redteam ...` (明示的に空) は **fallback せず中止** — 機密案件でクラウド送信を止める非常口
- エンドポイント: `https://api.deepseek.com/v1/chat/completions`
- モデル: `deepseek-v4-pro` (思考モード有効・`reasoning_effort: high`)

> **モデル ID は [`config/models.yml`](../../config/models.yml) が単一ソース**。ここを直に書き換えず台帳を先に更新し、`bash scripts/model-doctor.sh` を通すこと。
> 旧 `deepseek-reasoner` (R1) は **2026-07-24 に退役済み**で、呼ぶと失敗する (ADR-0017)。 <!-- model-doctor:allow -->

## 引数の解釈

`$ARGUMENTS` を以下のルールで解釈する:

1. **`--design <path>`** → 設計ドキュメント (Markdown) をレッドチーム
2. **`--diff`** (+ 任意で `--base <branch>`) → 差分をレッドチーム (デフォルト uncommitted)
3. **ファイルパス指定** → そのファイルの内容をレッドチーム
4. **その他のテキスト** → 上記いずれかと併用される追加観点

## 実行手順

### 1. API キー確認

```bash
# 環境変数 → ~/.deepseek_token の順に探す (scripts/test-deepseek.sh と同じ規約)。
# env だけに頼らない理由: ~/.bashrc は非対話シェルで早期 return するため、
# CI・非対話実行・シェルを再起動していないセッションでは env が空になる。
# ただし「明示的に空」(DEEPSEEK_API_KEY= /deepseek-redteam ...) はファイルへ
# fallback せず中止する — 機密案件のクラウド送信を止める非常口を潰さないため。
if [ -z "${DEEPSEEK_API_KEY+set}" ] && [ -f ~/.deepseek_token ]; then
  DEEPSEEK_API_KEY="$(cat ~/.deepseek_token)"
fi
if [ -z "${DEEPSEEK_API_KEY:-}" ]; then
  echo "ERROR: DEEPSEEK_API_KEY が未設定 (または明示的に空) で ~/.deepseek_token もありません"
  echo "https://platform.deepseek.com/api_keys で取得して以下のいずれかを実行:"
  echo "  - export DEEPSEEK_API_KEY=\"...\""
  echo "  - umask 077 && read -s -p 'key: ' k && echo \"\$k\" > ~/.deepseek_token && unset k"
  exit 1
fi
```

### 2. レビュー対象の取得

引数に応じて以下のいずれかで取得し `$CONTENT` に格納:

```bash
# --design <path>
cat "$DESIGN_PATH"

# --diff [--base main]  ← untracked も含める
{
  git diff "${BASE:-HEAD}"
  git ls-files --others --exclude-standard | while read -r f; do
    [ -f "$f" ] || continue
    echo ""
    echo "## untracked: $f"
    cat "$f"
  done
}

# ファイルパス
cat "$FILE_PATH"
```

> `--diff` で `--base` を省略した場合は uncommitted (staged + unstaged + untracked) を対象とする。`--base main` のような既存ブランチ比較時は untracked は無関係なので追加収集しなくてよい (上記スクリプトでは uncommitted ケースのみ untracked を拾う想定)。

### 3. プロンプト組み立て

```
あなたは批判的思考に長けたレッドチーム担当のシニアエンジニアです。
以下の {対象種別: 設計ドキュメント | 差分 | コード} を **徹底的に粗探し** してください。

目的は **致命的な見落としを発見すること**。褒める必要はありません。
以下を順に検討し、思考過程も含めて答えてください:

1. **前提の崩壊**: 暗黙の前提は何か。それが崩れる現実的シナリオは?
2. **エッジケース**: 想定されていない入力・状態・タイミングは?
3. **障害シナリオ**: 部分障害・ネットワーク分断・並行アクセス・リトライ時に何が起きるか?
4. **セキュリティ脅威モデル**: 悪意ある利用者・内部脅威・サプライチェーンから見た弱点は?
5. **運用上の罠**: デプロイ手順・ロールバック・移行・観測性に問題はないか?
6. **代替案**: より単純で堅牢な設計は存在するか? なぜそれを採らないのが妥当か?

各項目で **致命度 (Critical / High / Medium / Low)** を付け、Critical のみ詳細を展開してください。
最後に、もし 1 点だけ直すなら何かを **1 行で** 答えてください。

追加観点: {ARGUMENTS_OR_NONE}

---
{CONTENT}
---
```

### 4. DeepSeek API 呼び出し

```bash
PAYLOAD=$(jq -n \
  --arg content "$PROMPT" \
  '{
    model: "deepseek-v4-pro",
    thinking: {type: "enabled"},
    reasoning_effort: "high",
    messages: [{role: "user", content: $content}],
    max_tokens: 32000
  }')

RESPONSE=$(curl -sf --max-time 600 https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD")

# 思考過程 (reasoning_content) と最終回答を分けて取得
echo "## 思考過程"
echo "$RESPONSE" | jq -r '.choices[0].message.reasoning_content // empty'
echo ""
echo "## 最終回答"
echo "$RESPONSE" | jq -r '.choices[0].message.content'
echo ""
echo "## 使用量"
echo "$RESPONSE" | jq -r '.usage | "  入力 \(.prompt_tokens) / 出力 \(.completion_tokens) (うち思考 \(.completion_tokens_details.reasoning_tokens // 0))"'
```

> `thinking` と `reasoning_effort` は **両方**必要。省くと非思考モードで走り、レッドチームとしての深さが出ない。`reasoning_effort` は `low` / `high` / `max` を取る。

> ⚠️ **`max_tokens` は思考 + 本文の合計上限**。`reasoning_effort: high` で大きめの入力を投げると **思考だけで使い切って本文が空**になる (2026-08-17 実測: 入力 9.5K tok に `max_tokens: 8192` で `reasoning_tokens=8192` / content 空)。Gemini の thinking 枯渇と同型の罠。
> - **`max_tokens: 32000` を下限**とする
> - 応答が空だったら `completion_tokens_details.reasoning_tokens` を見る。`max_tokens` と一致していたら枯渇なので増やすか `reasoning_effort` を下げる
> - 上のスクリプトは使用量を必ず表示する。空応答を黙って「指摘なし」と解釈しないこと

### 5. 結果表示

思考過程と最終回答の両方を表示する。Claude 側で **同意できない指摘があれば反論コメントを付けてよい** (レッドチームの目的は議論の起点を作ること)。

## コマンド例

```bash
# 設計ドキュメントのレッドチーム
/deepseek-redteam --design docs/design/auth-rewrite.md

# 現在の uncommitted 差分のレッドチーム
/deepseek-redteam --diff

# main との差分 + セキュリティ観点
/deepseek-redteam --diff --base main セキュリティ脅威モデル中心で

# 特定ファイルの実装をレッドチーム
/deepseek-redteam src/payment/processor.ts 決済の冪等性
```

## 注意事項

- V4-Pro は思考モードで出力が長くなる (10K-30K token)。タイムアウトは 10 分程度みておく
- コストは安いが、本番コードを送る前にプロジェクトのコンプライアンス要件を確認 (DeepSeek は中国企業の API)
- 機密性が高い場合は代わりに `/local-review` を使う
- **モデル ID をここに直書きしない**。`config/models.yml` を更新してから `bash scripts/model-doctor.sh` で検証する (R1 退役を 3 週間見逃した再発防止・ADR-0017)
- レッドチームは **批判的視点の提供** が目的。指摘の妥当性は Claude/ユーザーが判断する
