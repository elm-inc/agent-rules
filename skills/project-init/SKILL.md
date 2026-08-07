---
name: project-init
description: 新規プロジェクトに agent-rules の再利用資産 (L2) を一括展開する。docs 標準構造・.claude/rules 置き場・settings 雛形・最小 CLAUDE.md・.gitignore を用意し、ゼロベース設計の初期工数を減らす。新しいリポで開発を始めるとき・プロジェクトの足場を作るときに使用
argument-hint: "[--force] (既存ファイルも上書き。既定はスキップ)"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(ls *) Bash(find *) Bash(mkdir *) Bash(cp *) Bash(test *) Bash(cat *) Read Write Edit
---

# プロジェクト足場の初期化 (L2 資産の展開)

新しいプロジェクト repo に、agent-rules の**再利用資産 (3 層の L2)** を一括展開する上位スキル。ゼロベース設計の繰り返しを減らすのが目的 ([`ADR-0013`](../../docs/adr/0013-three-layer-knowledge-architecture.md))。内部で `/docs-init` 相当の docs 展開を呼び、加えて settings 雛形・最小 CLAUDE.md・.claude/rules 置き場・.gitignore を用意する。

- **L1 (判断基準・安全原則)** は `~/CLAUDE.md`・`~/RULES.md` の symlink で既に全プロジェクトに効いている (このスキルの対象外)
- **L2 = このスキルが展開する再利用資産**
- **L3 (プロジェクト固有)** は生成した最小 CLAUDE.md と memory にユーザーが足していく

## 展開ルール (symlink でなくコピー)

**プロジェクト repo にコミットされ他環境 (CI・他マシン・clone) で解決される必要があるものは symlink でなくコピー**する (git は symlink をパス文字列で保存するため、`~/repos/...` を指す symlink は他環境で壊れる)。再実行時は既存を上書きせず差分を提示する。`.claude/rules` の stack 別ルールは**初期 0 個で成立** — 昇格パイプライン (2 回目ルール) が埋めるので、中身のないルールを先に量産しない。

## 引数

- `--force`: 既存ファイルがあっても上書き (既定はスキップしてログ)

## 実行手順

### 1. 対象の確認

```bash
git rev-parse --show-toplevel   # repo ルート。git repo でなければエラー終了
```
- **agent-rules 自身の上では実行しない** (別リポの初期化用)。ルートが agent-rules canonical path なら警告して中止
- テンプレ元: `/home/elmo/repos/github.com/elm-inc/agent-rules/templates/`

### 2. docs 標準構造

`/docs-init` と同じ展開を行う (契約も同じ: メタ `_templates/` は常に上書き同期・中身は既存スキップ)。`templates/docs/` → `<repo>/docs/`。詳細は [`skills/docs-init/SKILL.md`](../docs-init/SKILL.md) に従う。

### 3. .claude/ の足場

```bash
mkdir -p <repo>/.claude/rules
# settings 雛形 (プロジェクトレベル。既存なら skip)
test -f <repo>/.claude/settings.json || cp templates/claude-settings/settings.project.json <repo>/.claude/settings.json
```
- `.claude/rules/` は**空で作る** (README も置かない。stack 別ルールは昇格で足す)。使い方は L1 の索引と `templates/claude-rules/README.md` を参照

### 4. 最小 CLAUDE.md (L3 stub)

```bash
test -f <repo>/CLAUDE.md || cp templates/project-claude-md.md <repo>/CLAUDE.md
```
- **既存の CLAUDE.md は絶対に上書きしない** (`--force` でも確認を挟む)。展開後、`<プロジェクト名>` 等プレースホルダの穴埋めをユーザーに促す

### 5. .gitignore への追記 (重複しないよう確認してから)

案件で使う可能性のある秘匿ファイルを予防的に無視 (既に記載があれば足さない):
```
.newrelic-profile
.envrc
.mcp.json
```
> New Relic の `.newrelic-profile`/`.envrc` は顧客名漏洩防止で commit 禁止 (安全原則)。`/newrelic init` を使う場合はそちらが専用 .gitignore を生成するため二重にならないよう確認する。

### 6. ユーザーレベル settings の確認 (促しのみ)

L1 の安全原則を機械 enforcement する `~/.claude/settings.json` (permissions/hook) が未適用なら、`templates/claude-settings/settings.user.json` の手動マージ or `install.sh --fix` を案内する (このスキルは ~/.claude を勝手に触らない)。

### 7. 結果サマリ

- 作成 / スキップしたファイル一覧
- `git status` が生成物のみを示すことを確認 (手作業残タスク 0 が目標)
- 次アクション: `<repo>/CLAUDE.md` の穴埋め → `/adr-new <題>` で最初の ADR → `/docs-visualize` で全体像

### 8. (任意) git add

ユーザー確認の上で新規ファイルを `git add`。コミットはしない。

## 注意

- 既存ファイルは既定で上書きしない (docs メタ `_templates/` のみ常に同期、docs-init と同契約)
- symlink は張らない (§展開ルール)。ユーザーレベル資産 (~/.claude) はこのスキルの対象外
