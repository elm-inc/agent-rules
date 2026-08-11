---
name: flow-diagram
description: 業務フロー図 (Mermaid) を標準スタイル + 必須情報チェックリストに沿って作成/更新し、lint-flow-diagram.py で書式一貫性と記載漏れを機械検証する。業務フロー・プロセス図を作りたい/直したいときに使用
argument-hint: "<プロセスの説明 or 対象 .flow.md> [--check <file>]"
disable-model-invocation: false
allowed-tools: Bash(python3 ~/repos/github.com/elm-inc/agent-rules/scripts/lint-flow-diagram.py*) Bash(python3 ~/.claude/skills/*) Bash(cp *) Bash(ls *) Bash(cat *) Bash(test *) Read Write Edit
---

# 業務フロー図の作成 (標準準拠 + 機械検証)

業務フローを Mermaid で図式する。**作るたびに書式がブレる/必須情報が漏れる**のを防ぐため、標準に沿って生成し**バリデータが通るまで完成にしない**。標準: [`docs/design/flow-diagram-standard.md`](../../docs/design/flow-diagram-standard.md) / 根拠: [`ADR-0015`](../../docs/adr/0015-business-flow-diagram-standard.md)。

## 引数

- **プロセスの説明** → 新規作成
- **`.flow.md` パス** → その図の更新
- **`--check <file>`** → バリデータだけ実行

## 実行手順

### 1. 標準を読む

`docs/design/flow-diagram-standard.md` の**必須情報チェックリスト**と**スタイル規約**を読み込む (毎回。ここが単一ソース)。

### 2. 必須情報を集める (記載漏れ防止)

frontmatter 8 欄 (process/purpose/owner/actors/systems/trigger/version/updated) と、図の必須要素 (開始・全終了状態・アクター割当・条件ラベル付き分岐・**例外経路**・システム受け渡し) を会話・資料から埋める。**欠けている項目はユーザーに 1 回まとめて確認する** (推測で埋めない)。

### 3. テンプレから生成

`templates/flow-diagram/example.flow.md` をコピーして `<プロセス名>.flow.md` を作り、frontmatter と Mermaid を差し替える。スタイル規約 (flowchart TD・subgraph swimlane・ノード形状の意味・classDef 色) を厳守。例外ノード/終了には `:::exception` を付ける。

### 4. バリデータで機械検証 (必須)

```bash
python3 ~/repos/github.com/elm-inc/agent-rules/scripts/lint-flow-diagram.py <file.flow.md>
```
- **FAIL が出たら直して再実行**。通る (exit 0) まで完成にしない
- warning (swimlane 欠落等) も可能な限り解消する

### 5. レンダリングで確認

`/docs-publish` で Mermaid をオフライン作図し、見た目・分岐・レーンを目視確認する (実行して確かめる)。おかしければ 3 に戻る。

### 6. 結果

作成/更新したファイルパス、lint 結果、レンダリング確認の要点を提示。案件リポなら `*.flow.md` を CI で lint する設定を促す。

## 注意

- バリデータは正規表現ベースの構造 lint。ラベルに括弧を入れる等の変則記法は避ける (標準の記法に従う)
- 種別で必須項目が大きく違う場合はプロファイル増設を検討 (現状 1 プロファイル。標準 doc に節追加 + バリデータ拡張)
