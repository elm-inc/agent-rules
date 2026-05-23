---
name: worktree-start
description: 並列開発用の git worktree を作成し、タスクをレジストリに登録する。新しいタスクを並列で始めたい、worktree を作りたいときに使用
argument-hint: <タスク名> <タスクの説明> [--linear <ID>] [--no-remote]
disable-model-invocation: false
allowed-tools: Bash(git *) Bash(jq *) Bash(cat *) Bash(mkdir *) Bash(date *) mcp__linear__* Read Write
---

# 並列開発: worktree 作成とタスク登録

git worktree を作成し、並列開発タスクをレジストリに登録する。Linear Issue ID を指定すれば、ブランチ名に ID を埋め込み、Linear 側の状態を In Progress に遷移させる。

## 引数の解釈

`$ARGUMENTS` を以下のように解釈する:
- 第1トークン → タスク名（ブランチ名のサフィックスにも使用。例: `feat-auth`）
- 残り → タスクの説明（例: `ユーザー認証機能の追加`）
- `--linear <ID>`: Linear Issue ID (例: `ELM-123`)。指定すると:
  - ブランチ名が `worktree/<linear-id-lowercase>-<タスク名>` になる (Linear 側で PR 自動紐付け)
  - Linear Issue を In Progress に遷移
  - `parallel-tasks.json` に `linear_issue_id` を記録
- `--no-remote`: Remote Control 付き起動コマンドを案内しない。指定しない場合 (デフォルト) は最終案内に `claude --remote-control "<タスク名>"` を含める (iPhone 公式 Claude アプリの Code タブから push 通知・状態確認可能)

タスク名が未指定の場合はユーザーに確認する。Linear 運用ポリシー (project_linear_workflow メモリ) に従い、ステークホルダー可視化が必要な作業は `--linear` を付ける。

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
- ブランチ名:
  - `--linear <ID>` 指定なし: `worktree/<タスク名>`
  - `--linear <ID>` 指定あり: `worktree/<ID-lowercase>-<タスク名>` (例: `worktree/elm-123-feat-auth`)
  ```bash
  WORKTREE_BASE="${MAIN_WORKTREE}-worktrees"
  mkdir -p "$WORKTREE_BASE"
  git worktree add "${WORKTREE_BASE}/<タスク名>" -b "<ブランチ名>"
  ```

### 3. Linear Issue 連携 (--linear 指定時のみ)
- Linear MCP の `get_issue` 相当で Issue が存在することを確認
- 既に Done/Cancelled なら警告して中断 (`--force` で続行可)
- `update_issue` 相当で state を `In Progress` (`Started`) に遷移
- Issue の Assignee が未設定なら自分にアサイン
- Issue URL を控えてレジストリと最終案内に含める

### 4. タスクレジストリに登録
- レジストリファイル: `${GIT_COMMON_DIR}/parallel-tasks.json`
- 既存ファイルがなければ `{"tasks":[]}` で初期化
- 以下のエントリを追加:
  ```json
  {
    "name": "<タスク名>",
    "branch": "<ブランチ名>",
    "worktree_path": "<worktreeのフルパス>",
    "base_branch": "<ベースブランチ>",
    "description": "<タスクの説明>",
    "started_at": "<ISO8601>",
    "status": "active",
    "linear_issue_id": "<ELM-123 or null>",
    "linear_issue_url": "<URL or null>"
  }
  ```
- jq がインストールされていない場合は Python の json モジュールで代替する

### 5. ユーザーへの案内
以下を表示する (Linear 連携時は Issue 情報も含める)。デフォルトでは Remote Control 付きの起動コマンドを案内する。`--no-remote` が指定された場合は `--remote-control ...` 部分を省く。

```
worktree を作成しました:
  パス:     <worktree パス>
  ブランチ: <ブランチ名>
  Linear:   <ELM-123 In Progress に遷移>  ← --linear 指定時のみ
            <Issue URL>

新しい Claude Code セッションを以下で起動してください:
  cd <worktree パス> && claude --remote-control "<タスク名>"   ← --no-remote 指定時は `claude` のみ

(iPhone 公式 Claude アプリの Code タブから push 通知・接続切替が可能。Pro プラン以上必須)

他のタスクの状況は /worktree-list で確認できます。
完了後は /worktree-finish でマージしてください。
```

## 注意事項
- 同名のタスクが既に active の場合はエラーにする
- worktree ディレクトリの親が存在しない場合は作成する
- ベースブランチの最新コミットから分岐する
- `--linear` 指定時に Linear MCP が未認証なら、Issue 連携部分だけ skip して警告を出し、worktree 作成自体は継続する (`linear_issue_id` のみレジストリに記録)
- Linear ID は大文字小文字を区別しない (`elm-123` / `ELM-123` どちらでも受け付け、ブランチ名は lowercase に統一)
