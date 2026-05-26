---
name: status
description: 現状把握のブリーフィング。最近のコミット、open PR/Issue、worktree タスク、project memory、未コミット変更を一覧表示する。セッション開始時や「今どうなってる？」を確認したいときに使用
argument-hint: "[--since <期間>] [--repo <名前>]"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(gh *) Bash(ls *) Bash(find *) Bash(cat *) Bash(jq *) Bash(date *) Bash(python3 *) Read
---

# プロジェクト状況ブリーフィング

elm-inc プロジェクト全体の現状を 1 画面に集約して表示する。

## 引数の解釈

`$ARGUMENTS` を解釈する:
- `--since <期間>`: 期間を上書き (例: `--since "3 days ago"`、デフォルト 7 日)
- `--repo <名前>`: 特定リポジトリに絞る (例: `--repo tamayori`)
- 引数なし: デフォルト (直近 7 日、全リポジトリ)

## 実行手順

### 1. スコープ決定
- ルート: `/home/elmo/repos/github.com/elm-inc`
- 対象リポジトリ検出:
  ```bash
  find /home/elmo/repos/github.com/elm-inc -maxdepth 2 -name ".git" -type d -printf "%h\n" | sort
  ```
- `--repo <名前>` 指定時はそれだけに絞る

### 2. 各リポジトリから機械情報を収集
各リポジトリについて並列に:

**git 情報**:
```bash
cd <repo>
git log --since="<期間>" --oneline          # 直近コミット
git status --short                           # 未コミット変更
git branch --show-current                    # 現在のブランチ
```

**GitHub 情報**（`gh auth status` で認証済みの場合のみ）:
```bash
gh pr list --state open --json number,title,author,updatedAt,isDraft
gh issue list --state open --json number,title,labels,assignees,updatedAt
```

**並列タスクレジストリ**:
```bash
REGISTRY="$(git rev-parse --git-common-dir)/parallel-tasks.json"
# 存在すれば内容を読む
```

### 3. Project Memory を確認
```bash
MEMORY_DIR=/home/elmo/.claude/projects/-home-elmo-repos-github-com-elm-inc/memory
```

- `MEMORY.md` を読む (インデックス)
- 最近更新されたメモリファイルの概要を取得:
  ```bash
  ls -t $MEMORY_DIR/*.md | head -10
  ```
- 各ファイルの frontmatter `description` と `type` を抽出

### 4. 出力フォーマット

以下の markdown を出力する (セクションに情報がなければ省略):

```markdown
# 📅 プロジェクト状況  (<today>)

## 🎯 直近 <期間> の変化
- **<repo>** (<branch>): <N> commits
  - <最新 3 件のコミットメッセージ>
- (変更がないリポジトリは省略)

## 🔄 進行中 (未コミット)
- **<repo>** (<branch>): <N> files modified, <M> untracked
  - 主な変更: <git status --short の要約>
- (clean なリポジトリは省略)

## 📮 Open PR
| Repo | # | Title | Author | Updated |
|---|---|---|---|---|
| tamayori | #1 | refactor(ci): ... | @tomohisa-masaki | 2h ago |
- draft は [DRAFT] マークを付ける

## 📋 Open Issues
| Repo | # | Title | Labels | Updated |
|---|---|---|---|---|

## 🌳 並列 Worktree タスク
- **<task-name>** (<branch>): <description> — started <date>
- (なければ省略)

## 🧠 最近の決定・依頼 (memory)
- **<date>**: <memory description> (`<type>`)
- 直近 7 日以内のものを優先、古いものは件数のみ

## ⚠ 注意
- (長く残っている uncommitted 変更、レビュー未対応 PR 等があれば警告)
```

### 5. サマリと次アクションの提案

最後に 2〜3 行で:
- 「前回から何が進んだか」
- 「今日優先すべきもの」の推測

例:
> 前回セッション（4/22）から deploy-jetson.yml の Jetson runner 化が完了。tamayori main に hw/proto の未コミット変更 13 ファイルが滞留中なので、本日は hw 側の整理が候補。

## 注意事項

- `gh` がレート制限中のときは GitHub 情報をスキップして他を優先表示
- メモリファイルが存在しない場合はそのセクションを "(未初期化)" と表示
- 出力が長くなる場合も 1 画面で全体像が掴めるよう、各セクションは 5 行以内に抑える
- 詳細は「`/status --repo <name>` で絞り込める」と最後にヒントを付ける
