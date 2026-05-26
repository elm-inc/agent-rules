---
name: mutation-check
description: 既存のテスト (含 /test-generate 出力) が本当にバグを catch できるかを mutation testing で自己検証する。生存変異率が高ければ /test-generate --mutants で追加生成する連鎖を案内する。AI 生成テストの tautology (実装と同じ誤解で書かれた assertion) を機械的に検出する根本対策
argument-hint: "<対象パス> [--language python|js|ts|auto] [--threshold 90]"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(npx *) Bash(npm *) Bash(uvx *) Bash(mutmut *) Bash(pytest *) Bash(find *) Bash(grep *) Bash(cat *) Bash(jq *) Read
---

# /mutation-check — テストの精度を mutation testing で自己検証

ADR-0001 Phase 4 で判明した「AI 生成 assertion が実コードと不一致になる事例」(例: 60秒 → 期待 "1分" だが実装 "1分0秒") を **機械的に検出する根本対策**。pytest/jest の赤緑では tautology は検出できないが、実装に変異を入れて「テストが落ちないか」を見れば判明する。

## 用途

- `/test-generate` で書いたテストが本当に Critical バグを catch できるか確認したい
- 既存テストのカバレッジは高いが質が不安 (一行通しただけのテストが混ざっていないか)
- リファクタ前に「現テストで安全網が張れているか」を計測したい

## 前提

- **Python**: `mutmut` がインストール済み (or `uvx mutmut` で ad-hoc 実行可)、pytest が動く
- **JS/TS**: `@stryker-mutator/core` + 該当 runner (`@stryker-mutator/jest-runner` 等) が `package.json` の dev dep に
- AI 生成テストの場合: `/test-generate` 実行後の流れで使う

## 引数の解釈

`$ARGUMENTS`:

1. **対象パス** (必須): `src/utils/date.py` / `src/payment/` / `apps/api/src/` 等
2. `--language python|js|ts|auto`: 言語強制指定 (省略時は pyproject.toml / package.json 自動検出)
3. `--threshold <%>`: kill rate の合格基準 (default 90)。これを下回ったら `/test-generate --mutants` 連鎖を案内
4. **その他テキスト**: 上記と併用される追加観点 (今のところ未使用、将来拡張)

## 実行手順

### 1. 言語検出

```bash
if [ -f pyproject.toml ] || find . -maxdepth 2 -name 'pytest.ini' -o -name 'setup.cfg' 2>/dev/null | grep -q .; then
  LANG=python
elif [ -f package.json ]; then
  LANG=$(jq -r '.devDependencies // {} | keys[] | select(test("typescript|stryker"))' package.json | head -1)
  [ -n "$LANG" ] && LANG=ts || LANG=js
else
  echo "ERROR: pyproject.toml / package.json が見つかりません" >&2
  exit 1
fi
```

### 2-A. Python (mutmut) ドライバ

```bash
# 既存テストが緑であることを先に確認 (赤テストがあると mutmut が走らない)
pytest "$TARGET_PATH" -q --no-header 2>&1 | tail -5
[ $? -ne 0 ] && { echo "FAIL: 既存テストが赤。先に修正してから mutation-check を再実行"; exit 2; }

# mutation 実行
# (mutmut が未インストールなら uvx mutmut で ad-hoc)
if command -v mutmut > /dev/null; then
  MUTMUT="mutmut"
else
  MUTMUT="uvx --from mutmut mutmut"
fi

# pyproject.toml に mutmut 設定があるか確認
if ! grep -q '\[tool.mutmut\]' pyproject.toml 2>/dev/null; then
  cat <<EOF
WARNING: pyproject.toml に [tool.mutmut] セクションがないため、デフォルト挙動で走る。
推奨設定を pyproject.toml に追加:

[tool.mutmut]
paths_to_mutate = "$TARGET_PATH"
runner = "pytest -x -q"
tests_dir = "tests"
EOF
fi

$MUTMUT run --paths-to-mutate "$TARGET_PATH" 2>&1 | tail -20
```

### 2-B. JS/TS (Stryker) ドライバ

```bash
# Stryker config が無ければ最小設定を生成
if [ ! -f stryker.conf.json ] && [ ! -f stryker.conf.js ]; then
  cat > stryker.conf.json <<EOF
{
  "\$schema": "./node_modules/@stryker-mutator/core/schema/stryker-schema.json",
  "packageManager": "npm",
  "reporters": ["html", "clear-text", "json"],
  "testRunner": "jest",
  "mutate": ["$TARGET_PATH/**/*.{js,ts}", "!$TARGET_PATH/**/*.test.{js,ts}"],
  "thresholds": { "high": 90, "low": 70, "break": 60 }
}
EOF
fi

npx stryker run 2>&1 | tail -20
```

### 3. 結果集計

```bash
# Python
if [ "$LANG" = "python" ]; then
  KILLED=$($MUTMUT results | grep -c "killed:")
  SURVIVED=$($MUTMUT results | grep -c "survived:")
  TOTAL=$((KILLED + SURVIVED))
  KILL_RATE=$(awk "BEGIN { printf \"%.1f\", $KILLED * 100 / $TOTAL }")
  $MUTMUT results | grep "survived:" > /tmp/mutmut-survived.txt
fi

# Stryker
if [ "$LANG" = "ts" ] || [ "$LANG" = "js" ]; then
  # reports/mutation/mutation.json から JSON 抽出
  KILL_RATE=$(jq '.thresholds.high' reports/mutation/mutation.json)
  # 生存変異のリストは reports/mutation/mutation.html を見るのが手早い
fi
```

### 4. 判定と連鎖案内

```bash
echo "=== mutation testing report ==="
echo "  対象: $TARGET_PATH"
echo "  kill rate: ${KILL_RATE}%"
echo "  threshold: ${THRESHOLD:-90}%"

if [ $(awk "BEGIN { print ($KILL_RATE < ${THRESHOLD:-90}) }") = 1 ]; then
  cat <<EOF

⚠️ kill rate が threshold (${THRESHOLD:-90}%) 未満です。生存変異が catch されていません。

次のアクション (推奨):
  1. 生存変異リスト ($([ "$LANG" = "python" ] && echo "/tmp/mutmut-survived.txt" || echo "reports/mutation/mutation.html")) を確認
  2. /test-generate $TARGET_PATH --mutants /tmp/mutmut-survived.txt
     で生存変異を殺すテストを追加生成
  3. テスト追加後、再度 /mutation-check $TARGET_PATH で再計測

AI 生成テストの場合、特に「assertion が tautology になっている」可能性が高いです。
EOF
else
  echo ""
  echo "✓ kill rate が threshold を満たしています。テストの質は良好。"
fi
```

## 4 層レビュー体系上の位置付け

ADR-0001 + ADR-0002 で確立した 3 層 (機械 / LLM / 人間) に **第 4 層: mutation 検証** を追加する:

| 層 | 担当 | スキル |
|---|---|---|
| 1. 機械 | 型/lint/sec | pre-commit (ruff/mypy/semgrep) |
| 2. AI 多層 | 0次〜横断 | /local-review, /codex-review, /deepseek-redteam, /gemini-review |
| 3. **mutation** | テスト品質 | **/mutation-check ★ 新規** |
| 4. 人間 | 最終 | PR review |

特に AI 生成テスト (`/test-generate`) の品質を担保する目的では、`/test-generate` → `/mutation-check` → (失敗時) `/test-generate --mutants` の **連鎖運用** が要。

## 注意事項

- mutmut/Stryker は **時間がかかる** (10 分〜数時間、対象規模次第)。大規模プロジェクトでは関数/モジュール単位で分割実行を推奨
- 既存テストが赤の状態で走らせると mutmut/Stryker が異常終了する。先に `pytest` / `npm test` を通すこと
- mutation testing は完璧でない: equivalent mutant (意味的に変わらない変異) は false-survive する。85-95% kill rate が現実的目標
- Python では `mutmut` 4.x 以降を推奨 (古い `mutmut 2.x` は CLI 互換性が異なる)
- 巨大ファイル (>2000 行) は mutmut の cache が膨らむため、対象を絞ること

## コマンド例

```bash
# Python 関数の質チェック
/mutation-check src/utils/date.py

# TypeScript モジュール全体
/mutation-check src/payment --language ts

# 厳しめ threshold
/mutation-check src/auth --threshold 95
```

## 関連

- ADR-0001: `docs/adr/0001-multi-llm-development-workflow.md`
- ADR-0002: `docs/adr/0002-multi-model-test-generation.md`
- `/test-generate` (--mutants モードと連鎖):
  `~/.claude/skills/test-generate/SKILL.md`
- Phase 4 で判明した AI assertion 不一致事例:
  `docs/setup/notes/phase4-trial.md`
