---
name: test-generate
description: テスト観点の列挙とテスト実装を生成する。--brainstorm で複数 LLM (DeepSeek-R1 + Qwen + 任意で Distill/Gemini) を並列実行して観点を多面化、--implement で観点ファイルからコード生成。引数なしは旧挙動 (列挙 + 実装を 1 ステップで、Qwen 単独)
argument-hint: "<対象> [--brainstorm | --implement <観点ファイル>] [--with-distill] [--with-gemini] [--property] [--mutants <list>]"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(curl *) Bash(jq *) Bash(cat *) Bash(find *) Bash(ls *) Bash(grep *) Bash(flock *) Bash(docker *) Bash(bash *) Read Write Edit
---

# テスト観点列挙 + 実装生成 (多モデル対応)

ADR-0002 採択により 2 モード化。**観点抽出** (拡散的タスク) は複数 LLM を並列実行して groupthink を防ぎ、**実装** (収束的タスク) は単一モデル (Qwen) で十分という方針。

## モード一覧

| モード | LLM | 用途 |
|---|---|---|
| **引数なし** (旧挙動) | Qwen 単独 | 通常のテスト生成 (列挙 + 実装を 1 ステップで)。**後方互換** |
| **`--brainstorm`** | DeepSeek-R1 (API) + Qwen-32B FP8 (デフォルト 2 モデル)<br>+ `--with-distill` で Distill-14B FP8<br>+ `--with-gemini` で Gemini 2.5 Pro | 観点 (テストケース・境界条件・不変条件) を多面化抽出 |
| **`--implement <観点ファイル>`** | Qwen 単独 | `--brainstorm` の出力 (`.test-brainstorm.md`) を入力にコード生成 |
| **`--property`** | DeepSeek-R1 (発想) + Qwen (実装) | プロパティテスト不変条件 (旧挙動と同じ) |
| **`--mutants <list>`** | Qwen | 生存ミュータントを殺すテスト追加 (旧挙動と同じ) |

## 前提

- ローカル vLLM (Qwen-Coder-32B FP8) は**オンデマンド起動** — Qwen を使う前に `ensure-vllm.sh` で起動保証する (常駐させず、アイドル後は自動停止)。詳細: [`docs/adr/0005`](../../docs/adr/0005-on-demand-local-llm.md)
- `--brainstorm` デフォルト: `DEEPSEEK_API_KEY` 必須 (Distill ローカル化なら `--with-distill` で代替可)
- `--with-distill`: vLLM swap で Distill-Qwen-14B online FP8 を一時起動 (Phase 3 で自動化予定)
- `--with-gemini`: `GEMINI_API_KEY` 必須
- セットアップ: [`docs/setup/local-llm.md`](../../docs/setup/local-llm.md)
- Phase 1 結果: [`docs/setup/notes/phase7-distill-eval.md`](../../docs/setup/notes/phase7-distill-eval.md)

## 排他制御 (Critical, ADR-0002 採択時の安全策)

`--brainstorm` は GPU を順次 swap で使う運用。複数 worktree セッションから同時呼び出しで OOM するため、**`flock` で concurrency=1 を強制**:

```bash
LOCKFILE=/tmp/test-generate-brainstorm.lock
flock -w 600 "$LOCKFILE" bash -c '
  # brainstorm 本体処理
'
```

`--implement` は Qwen 単独で常駐 vLLM を使うため排他不要 (常時並行 OK)。

## 引数の解釈

`$ARGUMENTS` を以下のように解釈:

1. **最初の位置引数**: 対象ファイルパス or `path:functionName`
2. **`--brainstorm`** → 観点抽出モード
3. **`--implement <観点ファイル>`** → 実装モード (観点ファイル必須)
4. **`--with-distill`** → Distill-Qwen-14B FP8 をローカルレッドチームに併用
5. **`--with-gemini`** → Gemini 2.5 Pro を repo 横断 invariant 抽出に併用
6. **`--property`** → プロパティテスト不変条件モード (旧挙動)
7. **`--mutants <path>`** → 生存ミュータント対策 (旧挙動)

`--brainstorm` と `--implement` は**相互排他**。両方が指定されたらエラー。
両方とも未指定なら**旧挙動** (Qwen 単独で列挙 + 実装を 1 ステップで実行)。

## 実行手順

### Phase A: テストフレームワーク検出 (全モード共通)

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

property-based テストライブラリも検出 (pytest→hypothesis / vitest+jest→fast-check / go→gopter)。

### Phase B-1: `--brainstorm` モード

排他ロックを取得した上で、参加モデル (デフォルト DeepSeek-R1 + Qwen の 2、`--with-*` で追加) を順次 swap して観点を集める。

#### B-1-a. 観点抽出プロンプト (各モデル共通)

```
あなたは熟練のテストエンジニアです。以下のコードについて、テスト観点を**網羅的に列挙**してください。
重複を恐れず、思いつく限りすべて挙げてください。**実装コードは書かないでください**。

カテゴリ別に箇条書きで:
- 正常系の典型ケース
- 境界条件 (最小・最大・空・1 個・オーバーフロー)
- 異常系 (型違反、値域違反、null/None、空コレクション、循環参照)
- 並行・副作用 (race、リエントランシー、idempotency)
- セキュリティ (input validation、injection、auth bypass)
- パフォーマンス (large input、N+1、再帰深さ)
- メタモルフィック関係 / 不変条件 (該当する場合)

各観点に致命度 (High/Medium/Low) を付けてください。

対象コード:
---
{TARGET_CODE}
---
```

#### B-1-b. モデル別実行 (順次 swap)

```bash
BRAINSTORM_TMP=$(mktemp -d)

# 1. DeepSeek-R1 (API、deepseek-reasoner)
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
  curl -sf https://api.deepseek.com/v1/chat/completions \
    -H "Authorization: Bearer $DEEPSEEK_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg c "$PROMPT" '{model:"deepseek-reasoner", messages:[{role:"user", content:$c}], max_tokens:6000}')" \
    | jq -r '.choices[0].message.content' > "$BRAINSTORM_TMP/r1.md"
fi

# 2. Qwen-Coder-32B FP8 (オンデマンド起動、:8000)
bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh || { echo "vLLM を起動できませんでした"; exit 1; }
curl -sf "${LOCAL_LLM_BASE_URL:-http://localhost:8000/v1}/chat/completions" \
  -H "Content-Type: application/json" \
  -d "$(jq -n --arg c "$PROMPT" --arg m "${LOCAL_LLM_MODEL:-qwen-coder}" '{model:$m, messages:[{role:"user", content:$c}], temperature:0.3, max_tokens:3000}')" \
  | jq -r '.choices[0].message.content' > "$BRAINSTORM_TMP/qwen.md"

# 3. (--with-distill) Distill-Qwen-14B FP8 を swap で起動
if [ "$WITH_DISTILL" = "1" ]; then
  docker stop vllm-qwen-coder
  docker run -d --name vllm-test --gpus all --ipc=host -p 8001:8000 \
    -v "$HOME/.cache/huggingface":/root/.cache/huggingface \
    -e HUGGING_FACE_HUB_TOKEN="$(cat ~/.hf_token)" \
    vllm/vllm-openai:latest \
    --model deepseek-ai/DeepSeek-R1-Distill-Qwen-14B \
    --quantization fp8 --max-model-len 16384 --gpu-memory-utilization 0.90 \
    --served-model-name distill --enforce-eager > /dev/null

  # healthcheck (max 5 min)
  for i in $(seq 1 60); do
    curl -sf http://localhost:8001/v1/models > /dev/null 2>&1 && break
    sleep 5
  done

  # 推論
  curl -sf http://localhost:8001/v1/chat/completions \
    -d "$(jq -n --arg c "$PROMPT" '{model:"distill", messages:[{role:"user", content:$c}], temperature:0.3, max_tokens:5000}')" \
    | jq -r '.choices[0].message.content' > "$BRAINSTORM_TMP/distill.md"

  # cleanup + Qwen 復帰 (オンデマンド: ensure-vllm.sh で再起動。--rm のため docker start は使わない)
  docker rm -f vllm-test
  bash ~/repos/github.com/elm-inc/agent-rules/scripts/ensure-vllm.sh
fi

# 4. (--with-gemini) Gemini 2.5 Pro
if [ "$WITH_GEMINI" = "1" ]; then
  curl -sf "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-pro:generateContent?key=$GEMINI_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$(jq -n --arg c "$PROMPT" '{contents:[{parts:[{text:$c}]}], generationConfig:{maxOutputTokens:8192}}')" \
    | jq -r '.candidates[0].content.parts[0].text' > "$BRAINSTORM_TMP/gemini.md"
fi
```

#### B-1-c. 観点マージ + 重複除去

各モデルの出力を 1 つの `.test-brainstorm.md` に集約:

```bash
TARGET_BASE=$(basename "$TARGET" | sed 's/\.[^.]*$//')
OUT="$(dirname "$TARGET")/${TARGET_BASE}.test-brainstorm.md"

cat > "$OUT" <<EOF
# テスト観点: $TARGET

由来モデル別の生発想を保持しつつ、最下部にマージ済みリストを示します。

## DeepSeek-R1 (API) が挙げた観点
$([ -f "$BRAINSTORM_TMP/r1.md" ] && cat "$BRAINSTORM_TMP/r1.md" || echo "(skipped)")

## Qwen-Coder-32B が挙げた観点
$([ -f "$BRAINSTORM_TMP/qwen.md" ] && cat "$BRAINSTORM_TMP/qwen.md" || echo "(skipped)")

$([ "$WITH_DISTILL" = "1" ] && echo "## DeepSeek-R1-Distill-Qwen-14B (local FP8) が挙げた観点" && cat "$BRAINSTORM_TMP/distill.md")

$([ "$WITH_GEMINI" = "1" ] && echo "## Gemini 2.5 Pro が挙げた観点" && cat "$BRAINSTORM_TMP/gemini.md")

## マージ済み観点リスト

- [P0] (致命度 High かつ複数モデルで一致)
- [P1] (High かつ単一モデルのみ、または Medium かつ複数モデル一致)
- [P2] (それ以外)

## カバレッジ評価
- 全モデル共通の観点: N 件 (高信頼)
- 単一モデルのみの観点: N 件 (要レビュー — 偶然 or 独自発見)
EOF
```

最終的に Claude が「マージ済み観点リスト」セクションを埋める (手動マージ、観点数 200 件超なら警告 + トップ N に絞る)。

#### B-1-d. disagreement 自動検出 (AGENT-19)

マージ前に `scripts/brainstorm-divergence.py` を実行して、**他モデルと類似度の低い観点 (= 単独モデルだけが拾った重要候補)** をファイル末尾に追記する:

```bash
python3 "$AGENT_RULES/scripts/brainstorm-divergence.py" "$OUT" --inplace --threshold 0.30
```

これにより `## DIVERGENT POINTS` セクションが自動付与される。Claude はこのセクションを優先的にレビューし、マージ済み観点リストの [P0]/[P1] に昇格させる判断材料とする。Phase 8 試運転では DeepSeek-R1 観点 49 (実装と docstring の不一致) がここに flag された実例あり。

threshold チューニング: char n-gram TF-IDF のため日本語短文は類似度が低めに出る傾向。**0.30 推奨 (recall 重視)**、ノイズが多すぎる場合のみ 0.20 に下げる。

**注意 (ADR-0002 採択時の安全策)**: 観点ファイルは内部設計や脆弱性発想が含まれるため、デフォルトで **`.gitignore` 対象推奨** (`*.test-brainstorm.md`)。リポジトリ運用ポリシー次第で明示的にコミット。

### Phase B-2: `--implement <観点ファイル>` モード

排他不要 (Qwen 単独で常駐 vLLM を使用)。観点ファイル → ケース列挙 → コード生成:

```
以下の観点リストに従って、{FRAMEWORK} 形式でテスト実装を書いてください。
既存テストの規約 (import, setup, naming) に従ってください。
**観点に含まれないものは追加しないでください** (人間が選別した重要観点のみ実装する)。

観点ファイル:
{BRAINSTORM_MD}

既存テスト規約:
{EXISTING_TESTS_SNIPPET}

対象コード:
{TARGET_CODE}
```

Qwen-Coder-32B (常駐 vLLM) で実装生成。

### Phase B-3: 旧挙動 (引数なし、後方互換)

`--brainstorm` も `--implement` も `--property` も `--mutants` も無い場合、旧来の単一ステップ動作 (Qwen 単独で列挙 + 実装を 1 ステップ)。詳細プロンプトは [`SKILL.legacy.md`](SKILL.legacy.md) と同等。

### Phase B-4: `--property` モード (旧挙動を維持)

DeepSeek-R1 で不変条件 (invariants / metamorphic relations) を発想 → Qwen で実装。詳細は SKILL.legacy.md の同セクション。

### Phase B-5: `--mutants <list>` モード (旧挙動を維持)

生存ミュータントリスト + 対象コードを Qwen に渡してテスト追加。詳細は SKILL.legacy.md の同セクション。

### Phase C: テスト実行検証 (実装系モード共通)

> **Phase 4 で判明**: AI 生成 assertion は実コードと**一致しないことがある**。必ず実行して赤緑確認:

```bash
pytest "$NEW_TEST_PATH" -v 2>&1 | tee /tmp/test-result.txt
if [ $? -ne 0 ]; then
  echo "失敗あり。実装 vs assertion のどちらが正しいかを判断:"
  grep -E "FAILED|AssertionError" /tmp/test-result.txt
fi
```

## Qwen context 制約への対処

vLLM `--max-model-len 4096` (現状) 制約下では `max_tokens` を動的に決定:

```bash
MAX_LEN=$(curl -s "${LOCAL_LLM_BASE_URL}/models" | jq -r '.data[0].max_model_len // 4096')
INPUT_TOK=$(( ${#PROMPT} / 4 ))
MAX_OUT=$(( MAX_LEN - INPUT_TOK - 100 ))
[ "$MAX_OUT" -lt 500 ] && MAX_OUT=500
```

Phase 3 で `--max-model-len 8192` 以上に拡張予定。

## コマンド例

```bash
# 旧挙動 (後方互換)
/test-generate src/utils/date.ts:formatDuration

# 観点抽出 (DeepSeek-R1 + Qwen の 2 モデル並列、デフォルト)
/test-generate src/payment/processor.py --brainstorm

# 観点抽出 (Distill ローカル追加 = 機密案件用 3 モデル並列)
/test-generate src/payment/processor.py --brainstorm --with-distill

# 観点抽出 (Gemini で repo 横断 invariant 追加、コスト注意)
/test-generate src/payment/processor.py --brainstorm --with-gemini

# 観点ファイルから実装
/test-generate src/payment/processor.py --implement src/payment/processor.test-brainstorm.md

# プロパティテスト (旧挙動)
/test-generate src/algo/sort.ts --property

# ミュータント対策 (旧挙動)
/test-generate src/auth/token.py --mutants reports/mutants-survived.txt
```

## 注意事項

- `--brainstorm` は GPU swap で 1.5-3 分のレイテンシ追加 (`--with-distill` 時)。バッチ向き
- 同時実行は flock で 1 に制限される。並列ジョブ要求は順次待機
- 観点ファイルが 200 件超なら警告 + トップ N に絞る案内
- `--with-gemini` は **1M context 使用で $0.5-1/回**、月 10-20 回想定で $5-20。opt-in 推奨
- 生成テストは **必ず人間 (or Claude) がレビュー**。AI 生成テストは表面的になりがち
- 旧版動作 (SKILL.legacy.md) は引数なし呼び出しで再現可能。ロールバック手段として保持

## ロールバック

問題が発生した場合:

```bash
cp skills/test-generate/SKILL.legacy.md skills/test-generate/SKILL.md
```

または agent-rules リポで該当 commit を revert。
