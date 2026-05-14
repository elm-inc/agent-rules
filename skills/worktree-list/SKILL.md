---
name: worktree-list
description: 並列開発中の全タスク一覧と各 worktree の変更状況を表示する。他のセッションの進捗を確認したい、衝突リスクを確認したいときに使用
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(jq *) Bash(cat *) Bash(python3 *) Read
---

# 並列開発: タスク一覧と変更状況の確認

全アクティブタスクの状況を表示し、衝突リスクを分析する。

## 実行手順

### 1. レジストリの読み込み
```bash
GIT_COMMON_DIR=$(git rev-parse --git-common-dir)
REGISTRY="${GIT_COMMON_DIR}/parallel-tasks.json"
```
レジストリが存在しない場合は「並列タスクはありません」と表示して終了。

### 2. 各タスクの情報を収集
active なタスクそれぞれについて:

- **基本情報**: タスク名、ブランチ、説明、開始日時
- **変更ファイル一覧**: ベースブランチとの diff からファイル一覧を取得
  ```bash
  git diff --name-only <base_branch>...<task_branch>
  ```
- **コミット一覧**: タスクブランチのコミット
  ```bash
  git log --oneline <base_branch>..<task_branch>
  ```

### 3. 衝突リスクの分析
全アクティブタスクの変更ファイルを比較し、**同じファイルを変更しているタスクの組み合わせ**を検出する。

### 4. 表示フォーマット

```
## 並列開発タスク一覧

### [active] feat-auth (worktree/feat-auth)
  説明: ユーザー認証機能の追加
  開始: 2026-04-12T10:00:00
  パス: /home/user/project-worktrees/feat-auth
  コミット数: 3
  変更ファイル:
    - src/auth.ts
    - src/middleware.ts

### [active] fix-api (worktree/fix-api)
  説明: API エラーハンドリングの修正
  開始: 2026-04-12T11:00:00
  パス: /home/user/project-worktrees/fix-api
  コミット数: 1
  変更ファイル:
    - src/api/handler.ts

---
## 衝突リスク
⚠ feat-auth と fix-api が以下のファイルを同時に変更しています:
  - src/middleware.ts
→ マージ時に衝突する可能性があります。先に一方を /worktree-finish してください。

（衝突リスクがない場合）
✓ 変更ファイルの重複はありません。安全に並列作業を継続できます。
```

### 5. 完了済みタスクの表示
status が completed のタスクがある場合は、末尾に簡潔に表示する。

## 注意事項
- worktree のパスが存在しない（手動削除された等）場合はその旨を警告する
- ブランチが既に削除されている場合もエラーハンドリングする
