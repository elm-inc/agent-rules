---
name: linear-plan
description: Linear に Project + サブ Issue 群を一括作成する。複数フェーズに分かれる大きな計画 (リファクタリング、新機能、移行など) を Linear に乗せて進捗管理を始めたいときに使用
argument-hint: "<Project名> [--design <docs/design/path.md>] [--phases \"phase1, phase2, ...\"]"
disable-model-invocation: false
allowed-tools: mcp__linear__* Read Write Edit Bash(git *) Bash(date *)
---

# Linear Project + サブ Issue 一括作成

多段階タスク (Phase 1-N のリファクタなど) を Linear に乗せる。Project を 1 つと、Phase ごとのサブ Issue を一気に作る。

## 用途とタイミング

- 新しいリファクタリング計画を立てた直後 (`docs/design/foo.md` ができたタイミング)
- 既存の進行中タスクを Linear に**遡及登録**するとき
- マイルストーンを Linear で可視化したいとき

単発タスクなら `/linear-issue create` を使う。

## 前提

Linear MCP 認証済 + `docs/design/<plan>.md` (推奨) または会話文脈から Phase 一覧が決まっていること。

## 引数の解釈

- `<Project名>`: 必須。Linear Project のタイトル
- `--design <path>`: `docs/design/<path>.md` を読み込み、Phase 一覧と説明を抽出する
- `--phases "<phase1>, <phase2>, ..."`: design が無い場合の直接指定
- `--team <name>`: team 指定 (省略時は現在のリポから推測)
- `--target-date <YYYY-MM-DD>`: Project の期日
- `--start-phase <N>`: Phase N から作成 (既存 Phase の続きから埋めるとき)
- `--mark-completed "1-3"`: 既に完了している Phase は最初から Done で作成する

## 実行手順

### 1. 計画の構造化
- `--design` 指定: 該当ファイルを読み、Markdown 内の `## Phase N: <タイトル>` セクションを Phase として抽出
- `--phases` 指定: カンマ区切りを Phase 配列にする
- どちらも無い: ユーザーに以下を尋ねる
  - Project のタイトル
  - 概要 (1-2 行)
  - Phase の一覧 (`1. タイトル\n2. タイトル\n...`)
  - 期日 (任意)

### 2. ユーザーへの確認 (作成前)

作成内容を以下の形式で出力し、ユーザーに確認を取る:

```
作成予定:
  Project: <タイトル>
  Team:    <team名>
  期日:    <YYYY-MM-DD or 未設定>
  Description: <冒頭 100 字>

  サブ Issue (<N> 件):
    1. <Phase 1 タイトル>     [state: <Done|Todo>]
    2. <Phase 2 タイトル>     [state: <Done|Todo>]
    ...

このまま作成しますか? (y/N)
```

`y` で承認されたら次へ。

### 3. Project 作成
- Linear MCP の `create_project` 相当を呼ぶ
- description に `docs/design/<path>.md` の GitHub URL を含める

### 4. サブ Issue を順に作成
- 各 Phase について `create_issue` を呼び、`project_id` と `parent_issue_id` を設定
- `--mark-completed` で指定された Phase は state=Completed で作成
- description には Phase の説明 + design ファイルの該当セクションへの fragment リンク

### 5. 双方向リンクの更新
- `docs/design/<path>.md` の冒頭 (frontmatter または最初の段落) に以下を挿入:
  ```markdown
  - Linear Project: [<title>](https://linear.app/.../project/<slug>)
  - Phases: <ID-001>, <ID-002>, ...
  ```

### 6. 結果報告

```
✓ Project 作成: <URL>
✓ サブ Issue 作成: <N> 件
  ELM-001 Phase 1 ... (Done)
  ELM-002 Phase 2 ... (Done)
  ...
  ELM-006 Phase 6 ... (Todo)

次のアクション:
  - 進行中の Phase に着手: /linear-issue start <ID>
  - worktree 作成: /worktree-start <slug> --linear <ID>
  - 状況確認: /linear-status --project <name>
```

## 注意事項

- 一括作成途中で API エラーが出たら、それまでに作成した ID を表示し、中断する
- `--mark-completed` を多用する遡及登録では「履歴のため」コメントを各 Issue に自動で追加する (例: `[Backfill] 2026-05-21 既存実装からの遡及登録`)
- Project の `target_date` が過去なら警告を出す
- 同名の Project が既に存在する場合は警告し、上書きせず中断する
