---
name: codex-task
description: Codex CLI にコード修正や実装タスクを依頼する。Codex に作業させたい、Codex で実装してほしい、Codex に修正を任せたいときに使用
argument-hint: "<タスクの説明>"
disable-model-invocation: false
allowed-tools: Bash(codex *) Bash(git *)
---

# Codex CLI によるタスク実行

Codex CLI の `exec` サブコマンドを使ってコード修正・実装タスクを非インタラクティブに実行する。

## 引数の解釈

`$ARGUMENTS` をタスクの指示としてそのまま `codex exec` に渡す。

## 実行手順

1. 現在の git 状態を `git status` で確認し、未コミットの変更がないか把握する
2. `$ARGUMENTS` の内容を確認し、タスクの指示が明確かユーザーに確認する（曖昧な場合）
3. `codex exec` を `--full-auto` フラグ付きで実行する
4. 実行結果をユーザーに表示する
5. 実行後、`git diff` で Codex が行った変更内容を確認し、要約する

## コマンド例

```bash
# 基本的なタスク実行
codex exec --full-auto "関数 handleSubmit のエラーハンドリングを追加してください"

# モデル指定付き
codex exec --full-auto -m o3 "テストカバレッジを改善してください"

# サンドボックスモード指定
codex exec --full-auto --sandbox read-only "このバグの原因を調査して修正案を提示してください"
```

## 注意事項

- `--full-auto` を使用するため、Codex はワークスペースへの書き込みを含む操作を自動実行する
- 実行前に未コミットの変更がある場合はユーザーに警告する
- 実行後は必ず `git diff` で変更内容を確認し、意図した変更かユーザーと確認する
- 大きな変更の場合は、ユーザーが確認してからコミットするよう促す
- タイムアウトは長めに設定する（最大10分）
