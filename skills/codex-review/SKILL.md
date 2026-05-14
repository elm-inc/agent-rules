---
name: codex-review
description: Codex CLI にコードレビューを依頼する。コードの変更内容をレビューしてほしい、Codex にレビューさせたい、セカンドオピニオンがほしいときに使用
argument-hint: [レビュー対象や追加指示（例: --base main, --uncommitted, セキュリティ観点で）]
disable-model-invocation: false
allowed-tools: Bash(codex *) Bash(git *)
---

# Codex CLI によるコードレビュー

Codex CLI の `review` サブコマンドを使ってコードレビューを実行する。

## 引数の解釈

`$ARGUMENTS` を以下のルールで解釈する:

1. **引数なし** → uncommitted な変更（staged + unstaged + untracked）をレビュー
2. **`--base <branch>`** が含まれる → 指定ブランチとの差分をレビュー
3. **`--commit <sha>`** が含まれる → 指定コミットの変更をレビュー
4. **上記以外のテキスト** → カスタムレビュー指示として `codex review` の PROMPT に渡す

## 実行手順

1. 現在の git 状態を `git status` と `git diff --stat` で確認し、レビュー対象を把握する
2. 引数を解釈して適切な `codex review` コマンドを組み立てる
3. `codex review` を実行する（デフォルトは `--uncommitted`）
4. Codex の出力をそのままユーザーに表示する

## コマンド例

```bash
# uncommitted な変更をレビュー
codex review --uncommitted

# main ブランチとの差分をレビュー
codex review --base main

# 特定コミットをレビュー
codex review --commit abc1234

# カスタム指示付きレビュー
codex review --uncommitted "セキュリティの観点でレビューしてください"

# ブランチ差分 + カスタム指示
codex review --base main "パフォーマンスへの影響を重点的に確認してください"
```

## 注意事項

- `codex review` は非インタラクティブに実行される
- 出力が長い場合でもすべて表示する
- レビュー結果に対して Claude 側から追加のコメントや要約を付けてもよい
