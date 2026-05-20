---
name: linear-issue
description: Linear Issue の作成・表示・状態変更を行う。Issue を新規作成したい、状態を In Progress や Done に遷移したい、Issue の詳細を見たいときに使用
argument-hint: <subcommand> [args...]   (create|view|start|done|update)
disable-model-invocation: false
allowed-tools: mcp__linear__* Read Write Edit Bash(git *)
---

# Linear Issue 操作

Linear Issue の作成 / 表示 / 状態遷移を行う。

## 前提

Linear MCP が登録・認証済であること。未登録なら `/linear-status` と同じ案内を表示して中断する。

## サブコマンド

### `create <タイトル>`
新規 Issue を作成する。オプション:
- `--project <name|id>`: 親 Project (省略可。指定無しなら Backlog)
- `--parent <issue-id>`: 親 Issue (サブ Issue として作成)
- `--description <text>`: 本文 (省略時はタイトルのみ)
- `--design <path>`: `docs/design/<path>.md` を読み込み、Issue description に `要約 + 該当ファイルへのリンク` を入れる
- `--priority <0-4>`: 0=No 1=Urgent 2=High 3=Medium 4=Low
- `--assign-self`: 自分にアサイン

実行手順:
1. team を特定 (現在のリポ名から推測 / 複数 team あれば `--team` 必須にする)
2. `--design` 指定なら該当ファイルを読み、冒頭 200 字 + GitHub blob URL を description に入れる
3. Linear MCP の `create_issue` 相当を呼ぶ
4. 作成後、ID とタイトルと URL を表示
5. `--design` で読んだファイルがあれば、その冒頭に `- Linear: <ID>` を挿入する (双方向リンク)

### `view <ID>`
Issue 詳細を表示。
- ID (例: `ELM-123`) を受け取り `get_issue` 相当を呼ぶ
- タイトル / 状態 / Assignee / Project / 親子関係 / description / 直近コメント 3 件 / 紐付く GitHub PR を表示

### `start <ID>`
Issue を In Progress に遷移。
1. `get_issue` で現在の state を確認
2. team の workflow から `Started` 系の state を選択
3. `update_issue` で state を変更
4. もし自分にアサインされていなければアサインも更新
5. parallel-tasks.json に対応する worktree が無ければ、`/worktree-start <slug> --linear <ID>` を提案

### `done <ID>`
Issue を Done に遷移。
1. PR がマージ済か Linear で確認 (GitHub 連携経由)
2. `update_issue` で state を `Completed` に
3. 関連 worktree が active なら `/worktree-finish <name>` を提案

### `update <ID> <field>=<value>`
任意のフィールド更新。例:
- `update ELM-123 priority=High`
- `update ELM-123 assignee=@me`
- `update ELM-123 project=apps/batch-test-refactor`

`update_issue` 相当を呼ぶ。

## 出力

各操作後、以下を表示:
- 操作内容 (例: "ELM-106 を In Progress に遷移しました")
- Issue URL (`https://linear.app/.../issue/ELM-106`)
- 次のアクション候補 (state 遷移の場合は worktree 操作の提案など)

## 注意事項

- Issue ID の team prefix は workspace 設定に依存する (例: ELM, ENG, OPS)。MCP 呼び出し時はそのまま渡す
- ID 未指定でユーザーに尋ねるときは、直近の `parallel-tasks.json` または `git branch` からブランチ名の `worktree/<ID>-*` を抽出して候補を提示する
- `start` した直後に `done` するのは抑止する (誤操作防止)
- description に docs/design リンクを入れる時、リポジトリの GitHub URL は `git config --get remote.origin.url` から組み立てる
