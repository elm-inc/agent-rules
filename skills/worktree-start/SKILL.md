---
name: worktree-start
description: 並列開発用の git worktree を作成し、タスクをレジストリに登録する。新しいタスクを並列で始めたい、worktree を作りたいときに使用
argument-hint: <タスク名> <タスクの説明>
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(jq *) Bash(cat *) Bash(mkdir *) Bash(date *) Read Write
---

# 並列開発: worktree 作成とタスク登録

git worktree を作成し、並列開発タスクをレジストリに登録する。

## 引数の解釈

`$ARGUMENTS` を以下のように解釈する:
- 第1トークン → タスク名（ブランチ名のサフィックスにも使用。例: `feat-auth`）
- 残り → タスクの説明（例: `ユーザー認証機能の追加`）

タスク名が未指定の場合はユーザーに確認する。

## 実行手順

### 1. 前提確認
- 現在のディレクトリが git リポジトリ内であることを確認
- メインワークツリーのルートパスを取得:
  ```bash
  MAIN_WORKTREE=$(git worktree list --porcelain | head -1 | sed 's/worktree //')
  ```
- 共有 git ディレクトリを取得:
  ```bash
  GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
  ```

### 2. worktree 作成
- ベースブランチ（現在のブランチ）を記録
- worktree のパスは `<メインワークツリーのパス>-worktrees/<タスク名>/`
- ブランチ名は `worktree/<タスク名>`
  ```bash
  WORKTREE_BASE="${MAIN_WORKTREE}-worktrees"
  mkdir -p "$WORKTREE_BASE"
  git worktree add "${WORKTREE_BASE}/<タスク名>" -b "worktree/<タスク名>"
  ```

### 3. タスクレジストリに登録
- レジストリファイル: `${GIT_COMMON_DIR}/parallel-tasks.json`
- 既存ファイルがなければ `{"tasks":[]}` で初期化
- 以下のエントリを追加:
  ```json
  {
    "name": "<タスク名>",
    "branch": "worktree/<タスク名>",
    "worktree_path": "<worktreeのフルパス>",
    "base_branch": "<ベースブランチ>",
    "description": "<タスクの説明>",
    "started_at": "<ISO8601>",
    "status": "active"
  }
  ```
- jq がインストールされていない場合は Python の json モジュールで代替する

### 4. ユーザーへの案内
以下を表示する:

```
worktree を作成しました:
  パス:     <worktree パス>
  ブランチ: worktree/<タスク名>

新しい Claude Code セッションを以下で起動してください:
  cd <worktree パス> && claude

他のタスクの状況は /worktree-list で確認できます。
完了後は /worktree-finish でマージしてください。
```

## 注意事項
- 同名のタスクが既に active の場合はエラーにする
- worktree ディレクトリの親が存在しない場合は作成する
- ベースブランチの最新コミットから分岐する
