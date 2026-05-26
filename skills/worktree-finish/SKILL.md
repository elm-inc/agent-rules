---
name: worktree-finish
description: 並列開発タスクを完了し worktree のブランチをベースブランチにマージする。タスクが完了した、worktree をマージしたいときに使用
argument-hint: "[タスク名]"
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(jq *) Bash(cat *) Bash(python3 *) mcp__linear__* Read Write
---

# 並列開発: タスク完了とマージ

worktree のブランチをベースブランチにマージし、クリーンアップする。

## 引数の解釈
- `$ARGUMENTS` にタスク名が指定されている → そのタスクを対象
- 未指定 → 現在の worktree に対応するタスクを自動検出（現在のブランチ名から判定）

## 実行手順

### 1. 対象タスクの特定
```bash
GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
REGISTRY="${GIT_COMMON_DIR}/parallel-tasks.json"
```
レジストリからタスク情報（name, branch, worktree_path, base_branch）を取得。

### 2. 事前チェック
- 対象 worktree に未コミットの変更がないか確認
  ```bash
  git -C <worktree_path> status --porcelain
  ```
- 未コミットの変更がある場合はユーザーに警告し、続行するか確認する

### 3. 衝突チェック（ドライラン）
マージ前に衝突の有無を確認する:
```bash
# メインワークツリーで実行
git merge --no-commit --no-ff <task_branch> 2>&1
git merge --abort
```
衝突がある場合は衝突ファイルを表示し、ユーザーに判断を委ねる:
- 手動解決してからマージ
- タスクブランチ側で rebase してから再試行

### 4. マージ実行
衝突がなければベースブランチにマージ:
```bash
# メインワークツリーに移動してマージ
MAIN_WORKTREE=$(git worktree list --porcelain | head -1 | sed 's/worktree //')
git -C "$MAIN_WORKTREE" checkout <base_branch>
git -C "$MAIN_WORKTREE" merge --no-ff <task_branch> -m "merge: worktree/<タスク名> を <base_branch> にマージ"
```

### 5. クリーンアップ
```bash
# worktree を削除
git worktree remove <worktree_path>
# ブランチを削除
git branch -d <task_branch>
```

### 6. レジストリ更新
タスクの status を `completed` に変更し、`finished_at` を記録。

### 7. Linear Issue 連携 (linear_issue_id がある場合のみ)
レジストリに `linear_issue_id` が記録されていれば:
- Linear MCP の `update_issue` 相当で state を `Done` (`Completed`) に遷移
- Linear MCP が未認証なら警告のみ出して skip (マージ自体は完了済み)
- 失敗してもマージ結果は変えない (Linear 同期はベストエフォート)

### 8. 結果表示
```
タスク「<タスク名>」を完了しました:
  マージ先: <base_branch>
  コミット数: N
  変更ファイル数: N
  worktree: 削除済み
  ブランチ: 削除済み
  Linear:   <ELM-123 Done に遷移>  ← linear_issue_id 記録あり時のみ
```

## 注意事項
- **マージ先は必ずベースブランチ**（タスク開始時に記録したブランチ）
- 現在のセッションが対象 worktree 内にいる場合、worktree 削除前にメインワークツリーへの移動が必要であることを案内する
- `main` / `master` への直接マージは RULES.md のルールに従い禁止。ベースブランチがこれらの場合は警告する
