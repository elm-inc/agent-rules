# ADR-0015: 業務フロー図は「標準 + テンプレ + スキル + バリデータ」で作る

## ステータス

採択 (2026-08-11)

## 文脈

業務フローを Mermaid で図式する業務がある。AI と作るたびに (1) **書式・スタイルが変わる** (方向・ノード形状・色・命名のブレ)、(2) **必須情報が漏れる** (終了状態・例外経路・アクター割当・オーナー等) という問題がある。

スキル (プロンプト指示) だけで標準を守らせても、LLM の生成ばらつきで結局ドリフトする。これは CLAUDE.md や操作時安全原則で得た教訓と同じ — **散文ルールより機械 enforcement** ([`ADR-0013`](0013-three-layer-knowledge-architecture.md)・guard・lint の思想)。

## 決定

業務フロー図を **①標準 (単一ソース) + ②テンプレート + ③スキル + ④バリデータ** の「書く→機械検証」ループで作る。

- **① 標準** [`docs/design/flow-diagram-standard.md`](../design/flow-diagram-standard.md): 必須情報チェックリスト (frontmatter 8 欄 + 図の要素) と Mermaid スタイル規約 (flowchart TD・swimlane・ノード形状の意味・classDef 色) を定義。**まず 1 プロファイル**、増えたら節+プロファイル引数を追加。
- **② テンプレート** `templates/flow-diagram/example.flow.md`: 必須 frontmatter + 規約を体現した Mermaid 骨格 (compliant なサンプル)。`<プロセス名>.flow.md` にコピーして使う。
- **③ スキル** `/flow-diagram`: 必須情報を抽出 → 標準スタイルで生成 → ④ を実行 → `/docs-publish` でレンダリング確認。
- **④ バリデータ** `scripts/lint-flow-diagram.py`: 完全性 (必須欄・終了/開始・判断分岐ラベル・例外経路) とスタイル適合を機械チェックし、欠けたら FAIL。**これがドリフト防止の本体**。

案件リポでは `*.flow.md` を CI で lint し、書式ブレ・記載漏れを機械で防ぐ。paths rule 雛形 `templates/claude-rules/flow-diagram.md` を編集時に載せる。

## 理由

- **2 つの不満は別の強制が要る**: 書式ブレ→スタイル規約+lint、記載漏れ→必須項目+lint。どちらもバリデータで機械保証するのが確実。
- **スキル単独では不十分**: プロンプト指示は LLM のばらつきで守られないことがある。lint を通らないと完成にしないことで一貫性を担保する。
- **既存資産と一致**: 単一ソース + テンプレ + 機械検証は CLAUDE.md lint / cad-print / design-registry と同型。`/docs-visualize` (アーキテクチャ図) の業務フロー版。

## 検討した代替案

### 代替案 A: スキル (プロンプト) だけで標準を指示
- Pros: 実装が軽い。
- 不採用理由: LLM 生成のばらつきで書式・記載がドリフトする (まさに今の問題)。機械検証が無いと再発する。

### 代替案 B: テンプレートだけ配って手作業で守る
- Pros: 仕組みが最小。
- 不採用理由: 守れているかの検査が無く、漏れに気づけない。AI 生成では特に守られない。

### 代替案 C: 専用ツール / BPMN 等の外部フォーマット
- Pros: 業務フロー専用の表現力。
- 不採用理由: in-repo Markdown + Mermaid を設計図の基盤とする方針 (ADR-0003/0011) から外れ、AI が読み書きしにくくバイナリ化する。Mermaid + 機械検証で足りる。

## 帰結

### Pros
- 書式が一貫し、必須情報の漏れが機械的に防がれる (lint を通らないと完成しない)
- 標準が単一ソースなので全案件・全セッションで同じ図になる
- `/docs-publish` でレンダリング確認、CI で drift 検査まで繋がる

### Cons / 限界
- バリデータは Mermaid の完全パーサでなく正規表現ベースの構造 lint (ラベルに括弧を入れる等の変則記法には弱い)
- 1 プロファイルのため、種別で必須項目が大きく異なる場合はプロファイル増設が要る (将来対応)

### 関連 ADR
- [ADR-0013](0013-three-layer-knowledge-architecture.md) — 散文より機械 enforcement / 単一ソース + 検査の思想
- [ADR-0011](0011-ai-first-docs-architecture.md) — in-repo Markdown + Mermaid を図の基盤に
- [ADR-0012](0012-human-facing-docs-publish-model.md) — `/docs-publish` による Mermaid レンダリング (確認・配布)
