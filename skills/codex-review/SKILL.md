---
name: codex-review
description: Codex CLI にコードレビューを依頼する。コードの変更内容をレビューしてほしい、Codex にレビューさせたい、セカンドオピニオンがほしいときに使用
argument-hint: "[レビュー対象や追加指示（例: --base main, --uncommitted, セキュリティ観点で）]"
disable-model-invocation: false
allowed-tools: Bash(codex *) Bash(git *)
---

# Codex CLI によるコードレビュー

Codex CLI の `review` サブコマンドを使ってコードレビューを実行する。

## 引数の解釈

`$ARGUMENTS` を「**スコープ指定**」と「**カスタム指示**」に分けて読む。
**この 2 つは CLI 側で併用できない** (下の「CLI の制約」参照) ので、解釈もそれを前提にする:

1. **引数なし** → uncommitted な変更（staged + unstaged + untracked）をレビュー
2. **スコープ指定のみ** (`--uncommitted` / `--base <branch>` / `--commit <sha>`)
   → そのフラグ単独で実行する
3. **カスタム指示のみ** (フラグを含まないテキスト)
   → `codex review "<指示>"` で実行する。スコープは **uncommitted 既定**
4. **両方が混在** (例: `--base main セキュリティ観点で`)
   → **そのままでは実行できない。組み立てて失敗させないこと。**
   - `--uncommitted` との混在なら、既定スコープが同じなのでフラグを落として 3 の形にする
   - `--base` / `--commit` との混在は**どう書いても表現できない**ので、
     **ユーザーにどちらを優先するか確認する**
     (指示を捨ててスコープ単独で回すか / スコープを諦めて指示付き uncommitted で回すか)

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

# カスタム指示付きレビュー (スコープは uncommitted 既定。フラグは付けられない)
codex review "セキュリティの観点でレビューしてください"
```

## CLI の制約 (codex-cli 0.149.1 / 2026-08-28 実測)

- **`--uncommitted` / `--base` / `--commit` は 3 つとも PROMPT と併用できない。**
  渡すと `error: the argument '--uncommitted' cannot be used with '[PROMPT]'` で即失敗する。
  `Usage: codex review --uncommitted [PROMPT]` と表示されるのに排他という**上流 CLI 側の不整合**
- 素の `codex review "<指示>"` は動く。スコープは **uncommitted 既定**
- したがって「カスタム指示 + `--base` / `--commit`」は**現状どう書いても不可能**。
  ブランチ差分に観点を効かせたいなら、対象をコミットせずワークツリーに出すか、
  観点を諦めて `--base` 単独で回す

> 上流が直せば併用できるようになる性質の制約なので、**実測バージョンを併記してある**。
> 挙動が変わっていたらここを更新すること (`codex review --help` で確認)。

## 注意事項

- `codex review` は非インタラクティブに実行される
- 出力が長い場合でもすべて表示する
- レビュー結果に対して Claude 側から追加のコメントや要約を付けてもよい
