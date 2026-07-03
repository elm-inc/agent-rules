---
title: 人間向けドキュメントの publish モデル (audience 分離・多フォーマット)
type: adr
status: accepted
audience: internal
owner: tomohisa-masaki
updated: 2026-07-03
review_by: 2026-10-03
invalidation_condition: Notion 以外の共有先が主流になる / publish パイプライン (Marp/pandoc) の運用コストが便益を上回る場合は再評価
related:
  - docs/design/ai-first-docs.md
  - docs/adr/0003-notion-for-human-shared-docs.md
depends_on:
  - docs/adr/0003-notion-for-human-shared-docs.md
supersedes: []
---

# ADR-0012: 人間向けドキュメントの publish モデル (audience 分離・多フォーマット)

## ステータス

採択 (2026-07-03)

## 文脈

クライアント・ベンダーなど人の間の意思疎通・合意形成のためのドキュメントは、AI ファーストの技術文書 (ADR-0011) とは性格が異なり、読みやすさ・適度な分離・多様なフォーマット対応が要る。ADR-0003 で「人間共有ドキュメントは Notion 併用、設計図は in-repo Markdown」を決めているので、本 ADR はその**拡張**として人間軸 (Layer 3) を体系化する。設計詳細は [docs/design/ai-first-docs.md §7](../design/ai-first-docs.md) を参照。

## 決定

ADR-0003 を維持しつつ、**「audience 分離 + publish 派生 + 多フォーマット」** を追加する。

- **audience 分離 (fail-closed)**: frontmatter `audience: internal | external` を**必須**とし、**未設定/不明は internal 扱い**。publish パイプラインは `audience: external` が明示された doc のみ外部出力する (既定で漏らさない)。本リポの fail-closed 原則 (New Relic テナント・gh アカウント取り違え防止) と同型。
- **publish 派生原則** (ADR-0003 重複禁止の具体化): 内部設計 (docs/) を客先共有する場合は、**Markdown から人間向けレンディションを生成して配る**。複製して個別編集 (fork) しない。クライアント修正依頼は生成元 (Markdown) を直して再生成する (配布物を直接いじらない)。primary owner は常に片方に固定。
- **粒度**: audience は doc 単位が原則。外部可と内部限定が混ざるならファイルを分割する。どうしても混在させる場合のみ `<!-- publish:begin-exclude -->` … `<!-- publish:end-exclude -->` 区間を publish 時に必ず除去 (除去失敗時は外部出力を中止)。
- **多フォーマット (in-repo Markdown DNA のまま)**: Markdown → スライド (Marp/reveal.js) / PDF (pandoc/typst) / Notion (既存 MCP)。Mermaid は素の pandoc/Marp で描画されないため、publish に mermaid フィルタを必ず組み込む。
- **読みやすさ**: 外部向けは explanation/tutorial 寄りの散文にし、配布物に frontmatter・メタを出さない (生成時に除去)。

## 理由

- 人間向けは「協働・可読性・多フォーマット」が要件で、AI ファーストの frontmatter 過多な技術文書と混ぜると双方が劣化する → 明示的に分離する。
- publish 派生にすることで ADR-0003 の重複禁止を実装レベルで守れる (fork 編集による drift を作らない)。
- audience の fail-closed で、内部情報の client 漏洩という最悪ケースを構造的に防ぐ。

## 検討した代替案

- **doc/ に配布物も置く (audience 分離なし)**: 技術文書と混在し可読性・機密管理が破綻。→ 分離。
- **Notion に全部集約**: ADR-0003 で却下済み (AI 摩擦・vendor lock-in・git 履歴喪失)。
- **配布物を複製して個別編集**: 最も楽だが drift の温床。→ publish 派生に限定。
- **section 単位の audience を第一級に**: 柔軟だが複雑・漏洩リスク増。→ doc 単位 + 例外的な exclude 区間に留める。

## 帰結

### Pros
- 客先共有物の可読性・多フォーマット対応が上がる。
- 内部情報の外部漏洩を fail-closed で防ぐ。
- 二重管理を生まず ADR-0003 の重複禁止を実装で担保。

### Cons / 限界
- publish パイプライン (Marp/pandoc + mermaid フィルタ) の構築・保守コスト (P4)。
- 混在 doc の exclude 区間運用は人手依存 (漏れると漏洩) → 原則は分割、exclude は例外。
- Notion 原本と docs/ 派生の primary owner 判断が引き続き人手 (ADR-0003 の Con を継承)。

### 将来の検討事項
- publish の skill 化 (Markdown → Marp/pandoc/Notion) は設計書 §10 の P4。

### 関連 ADR
- [ADR-0003](0003-notion-for-human-shared-docs.md) — 人間共有 = Notion (本 ADR が拡張)
- [ADR-0011](0011-ai-first-docs-architecture.md) — AI 軸 (本 ADR と対)
