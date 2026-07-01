<!-- このファイルは agent-rules/templates/docs/ から展開されたひな形。各プロジェクトに合わせて書き換えてよい。 -->
# Documentation

このプロジェクトのドキュメント基盤。文書化方針は `~/CLAUDE.md` (= `elm-inc/agent-rules/CLAUDE.md`) を参照。

## 構成

| ディレクトリ | 役割 |
|---|---|
| `adr/` | Architecture Decision Records — なぜ・何を決めたか |
| `architecture/` | C4 model + 状態/シーケンス/依存図 — どう動くか |
| `design/` | 実装計画など — これから何をどう作るか |
| `_templates/` | **メタ** (記入用ひな形)。ドキュメント本体ではない → [`_templates/README.md`](_templates/README.md) |

## 原則

- **真理の単一源は git**。Notion / Confluence / Linear Docs 等の SaaS には設計図を置かない
- **すべて Markdown + Mermaid** で記述。GitHub が直接レンダリング
- **AI が完結して触れる**。Claude Code が Read/Edit/Write でフル制御可
- **コードと一緒に進化する**。設計変更時は ADR → 図 → コード の順で更新
- **`_` 接頭辞 = メタ / それ以外 = 中身**。`_templates/` 等のひな形と実ドキュメントを命名で分離し、誤認を防ぐ (`/docs-init` は前者を上書き同期・後者を保護)
