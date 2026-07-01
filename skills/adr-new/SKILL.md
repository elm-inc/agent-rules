---
name: adr-new
description: 新しい ADR を docs/adr/ に作成する。通し番号を自動採番し、テンプレを展開してファイルを開く準備をする。タイトル文字列を引数で受け取る
argument-hint: "<ADRタイトル>"
disable-model-invocation: false
allowed-tools: Bash(ls *) Bash(find *) Bash(cat *) Bash(date *) Bash(sed *) Read Write Edit
---

# 新しい ADR を採番＋テンプレ展開

カレントワーキングディレクトリの git リポジトリで、`docs/adr/` に新規 ADR ファイルを作成する。

## 引数の解釈

- `$ARGUMENTS`: ADR のタイトル文字列 (例: "プラットフォームに iOS Native を採用")
- 引数なし: ユーザーにタイトルを尋ねる

## 実行手順

### 1. 採番
既存 ADR から次の番号を計算:
```bash
ls docs/adr/[0-9]*.md 2>/dev/null \
  | sed -n 's|.*/0*\([0-9]*\)-.*|\1|p' \
  | sort -n \
  | tail -1
```
最大値 + 1 を 4 桁ゼロ埋め (`0011`, `0012`, ...)。

### 2. ファイル名生成
- タイトルを kebab-case 化 (スペース → `-`、日本語はそのまま許容)
- ファイル名: `docs/adr/NNNN-<kebab-title>.md`

### 3. テンプレ取得
ひな形 (空フォーム) を読み込む。優先順位:

1. プロジェクトローカルの `docs/_templates/adr.md` (あれば。`/docs-init` が展開済み)
2. なければ agent-rules 正本 `/home/elmo/repos/github.com/elm-inc/agent-rules/templates/docs/_templates/adr.md`

読み込んだら以下を置換:

- `ADR-NNNN` → `ADR-<採番>`
- `タイトル` → `<引数で渡された日本語タイトル>`
- `YYYY-MM-DD` → 今日の日付 (`date +%Y-%m-%d`)

### 4. ファイル書き出し
置換結果を `docs/adr/NNNN-<kebab-title>.md` に書き込む (Write tool)。

### 5. 結果報告
- 作成したファイルパス
- 次のアクション: 「ファイルを開いて内容を埋めてください」または、すでに会話の文脈から決定事項が明確なら、直接埋める提案

### 6. (任意) memory 更新
elm-inc/CLAUDE.md の指示に従い、project memory に ADR の存在を記録するかをユーザーに尋ねる。

## 注意

- `docs/adr/` が存在しなければ `/docs-init` 実行を提案
- ファイル名の重複は採番ロジックで防がれるはずだが、万一あれば警告して中断
