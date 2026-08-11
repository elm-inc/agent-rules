---
paths:
  - "**/*.flow.md"
---

# 業務フロー図の規約 (*.flow.md)

このファイルは agent-rules の雛形 (`templates/claude-rules/flow-diagram.md`)。業務フロー図を扱う案件に `.claude/rules/flow-diagram.md` としてコピー配置する。標準の単一ソース: agent-rules `docs/design/flow-diagram-standard.md` / スキル: `/flow-diagram`。

- **標準に従う**: frontmatter 8 欄 (process/purpose/owner/actors/systems/trigger/version/updated) 必須、`flowchart TD`、swimlane は `subgraph`、ノード形状の意味を固定 (`([開始/終了])`/`[処理]`/`{判断}`/`[/入出力/]`/`[(システム)]`)
- **必ず描く**: 開始と全終了状態・判断は条件ラベル付き分岐≥2・**例外経路 (`:::exception`)**・アクター割当
- **完成前に機械検証**: `python3 <agent-rules>/scripts/lint-flow-diagram.py <file>.flow.md` が通る (exit 0) まで完成にしない。CI でも `*.flow.md` を lint する
- 書式・色は標準の `classDef` を使い、案件ごとに勝手に変えない (ブレ防止)
