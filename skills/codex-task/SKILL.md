---
name: codex-task
description: Codex CLI にコード修正や実装タスクを依頼する。Codex に作業させたい、Codex で実装してほしい、Codex に修正を任せたいときに使用
argument-hint: "<タスクの説明>"
disable-model-invocation: false
allowed-tools: Bash(~/repos/github.com/elm-inc/agent-rules/scripts/codex-run.sh *) Bash(python3 ~/repos/github.com/elm-inc/agent-rules/scripts/harness.py *) Bash(git *)
---

# Codex CLI によるタスク実行

Codex CLI の `exec` サブコマンドを使ってコード修正・実装タスクを非インタラクティブに実行する。

## 引数の解釈

`$ARGUMENTS` をタスクの指示としてそのまま `codex-run.sh exec` に渡す (Codex CLI の `exec` を、送信前の区分確認を内蔵したラッパ経由で呼ぶ・ADR-0023)。

## 実行手順

1. 現在の git 状態を `git status` で確認し、未コミットの変更がないか把握する
2. `$ARGUMENTS` の内容を確認し、タスクの指示が明確かユーザーに確認する（曖昧な場合）
   - **実行の前に、送信前の区分確認を【別のコマンドとして】実行する** (ADR-0023・止めない): `python3 ~/repos/github.com/elm-inc/agent-rules/scripts/harness.py egress-check --preflight --vendor openai`。警告が出たら、送信先と区分をユーザーに一言伝えてから実行に進む (ラッパも送信時に同じ確認をするが、その時点では送信が始まっていて伝える間が無い)
3. `~/repos/github.com/elm-inc/agent-rules/scripts/codex-run.sh exec` を `--approve-for-me` フラグ付きで実行する — **素の `codex` を直接呼ばない** (送信前の区分確認が抜ける)。区分の警告が出たら、ユーザーに一言伝えてから続ける
4. 実行結果をユーザーに表示する
5. 実行後、`git diff` で Codex が行った変更内容を確認し、要約する

## コマンド例

```bash
# 基本的なタスク実行 (workspace-write サンドボックスで承認を自動化)
~/repos/github.com/elm-inc/agent-rules/scripts/codex-run.sh exec --approve-for-me "関数 handleSubmit のエラーハンドリングを追加してください"

# 調査だけさせる (書き込ませない)
~/repos/github.com/elm-inc/agent-rules/scripts/codex-run.sh exec --sandbox read-only "このバグの原因を調査して修正案を提示してください"
```

> **`--full-auto` は codex-cli 0.149.1 で削除された** (2026-08-28 実測。`error: unexpected
> argument '--full-auto' found` で即失敗する)。後継は `--approve-for-me`
> (= workspace-write サンドボックス + 承認の自動化)。挙動が変わっていたら
> `codex exec --help` で確認してここを更新すること。
>
> **モデルは `-m` で固定しない。** Codex CLI が既定モデルを管理する方針
> (`config/models.yml` の codex エントリ / ADR-0017)。

## 注意事項

- `--approve-for-me` を使用するため、Codex はワークスペースへの書き込みを含む操作を自動実行する
- 実行前に未コミットの変更がある場合はユーザーに警告する
- 実行後は必ず `git diff` で変更内容を確認し、意図した変更かユーザーと確認する
- 大きな変更の場合は、ユーザーが確認してからコミットするよう促す
- タイムアウトは長めに設定する（最大10分）
