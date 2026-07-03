---
title: AI ファースト・ドキュメント・アーキテクチャ (3層・派生生成)
type: adr
status: accepted
audience: internal
owner: tomohisa-masaki
updated: 2026-07-03
review_by: 2026-10-03
invalidation_condition: 大手 LLM (Anthropic/OpenAI/Google) が llms.txt を実際に消費し始めたら索引層の位置づけを再評価 / frontmatter 派生グラフで drift を抑えきれない規模になったら GraphRAG を再検討
related:
  - docs/design/ai-first-docs.md
  - docs/adr/0001-multi-llm-development-workflow.md
  - docs/adr/0009-separate-templates-from-docs.md
depends_on: []
supersedes: []
---

# ADR-0011: AI ファースト・ドキュメント・アーキテクチャ (3層・派生生成)

## ステータス

採択 (2026-07-03)

## 文脈

in-repo Markdown を SSOT とする文書運用 (ADR-0001/0003/0009) に、AI ファースト (機械可読) の記述規約・索引・構造管理 (ナレッジグラフ) を体系化する必要が出た。設計の全体像・調査根拠・受け入れ基準は [docs/design/ai-first-docs.md](../design/ai-first-docs.md) に記す。本 ADR は AI 軸 (Layer 0-2) の決定を記録する。

2026-07 の調査で判明した重要事実:

- **`llms.txt` は大手 LLM プロバイダに事実上無視されている** (ボットが取得しない・引用数と相関ゼロ)。かつドメイン root で HTTP 配信される前提で、GitHub 上 Markdown を配信しない本リポではクローラー向け価値がほぼ無い。
- AI ファースト docs の主流は `AGENTS.md` (入口) + `SKILL.md` (能力) + **frontmatter-first** + 「機械可読と人間可読を別ファイルに割らず同一 Markdown を層分け」。
- ナレッジグラフの docs-as-code での落としどころは **軽量・派生・決定論** (frontmatter/wikilink を解析して導出、Markdown が SSOT)。GraphRAG/RDF は重く drift リスク高。

## 決定

**統一原則: SSOT は git の Markdown。索引層・グラフ層はすべて SSOT から派生生成し、人は同じ情報を二度書かない** (ADR-0009 の「`_` = メタ / それ以外 = 中身」を踏襲)。

- **Layer 0 (記述規約)**: 全 doc に YAML frontmatter (`title` / `type` / `status` / `audience` / `owner` / `updated` / 関係フィールド) を必須化。ADR には future-guard 欄 (`review_by` / `invalidation_condition`) を追加。本文はセクション自己完結・one-fact-one-place。過剰なセマンティックチャンク最適化はしない。
- **Layer 1 (索引層)**: `docs/llms.txt` を frontmatter から**自動生成**する。位置づけは「自リポのエージェント/将来 RAG の巡回索引 + 規格普及への先行投資」であって SEO 目的ではない。**手書き禁止・コミット + CI 鮮度チェック**。`llms-full.txt` は作らない。
- **Layer 2 (グラフ層)**: frontmatter の関係 (`depends_on`/`supersedes`/`superseded_by`/`implements`/`related`) を**構文解析して決定論的にグラフを導出**。関係図 (Mermaid) と drift lint (リンク切れ・supersede 残り・`review_by` 超過・**循環参照**) を CI に出す (以前実体の無かった `/docs-sync` の実装)。グラフ導出は **cycle-safe**。生成物はコミット + 鮮度チェック。
- **不採用 (今回)**: GraphRAG/LightRAG・ベクトル検索・RDF/OWL・MCP doc サーバー・セマンティックチャンキング。派生グラフを持てば後から Markdown 不変で接続できる。

## 理由

- 索引もグラフも**派生生成にすることで二重管理・drift を構造的に消せる** (多言語を二重化理由で却下したのと同じ判断)。
- `llms.txt` は実効性が薄いが、生成コスト ≒0 で自リポの巡回索引を兼ね、将来投資にもなるので「概念のみ」採る (盛らない)。
- グラフは軽量・派生で十分な価値 (ナビゲーション + drift 検出) を得られ、重量級の運用コストを負わない。

## 検討した代替案

- **索引/グラフを都度 grep・オンデマンド生成 (コミットしない)**: CI 負荷は減るが、生成物が GitHub 上で見えず、エージェントもスクリプト実行が要る。→ コミット + 鮮度チェックの方が可視性と drift 防止を両立。
- **GraphRAG を最初から導入**: 複数ホップ推論は強力だが初期化コスト・運用が重く現規模でオーバースペック。→ 派生グラフで前提だけ作り後続に回す。
- **RDF/OWL 正式オントロジー**: 厳密だが手書き二重管理・drift 高リスク。→ 不採用。

## 帰結

### Pros
- 記述規約の底上げ (frontmatter-first) が検索性・エージェント効率に直接効く。
- 索引・グラフが自動追従し、drift を CI で検出できる。
- 将来の RAG/GraphRAG/MCP を Markdown 不変で後付けできる。

### Cons / 限界
- frontmatter 未記入・CI バイパスで drift し得る → 移行猶予後は hard-fail、drift は宿題昇格ルールで追跡。
- グラフは明示関係フィールドのみを捉え、暗黙の関係は拾えない。
- `llms.txt` は当面プロバイダに消費されない (承知の上の先行投資)。

### 将来の検討事項
- llms.txt がプロバイダに消費され始めたら位置づけ再評価 (invalidation_condition)。
- 規模が上がれば GraphRAG/LightRAG を派生グラフ上に接続。

### 関連 ADR
- [ADR-0001](0001-multi-llm-development-workflow.md) — SaaS に設計図を置かない SSOT 方針
- [ADR-0009](0009-separate-templates-from-docs.md) — `_` = メタ / それ以外 = 中身 (派生生成の先例)
- [ADR-0012](0012-human-facing-docs-publish-model.md) — 人間向け配布 (本 ADR と対の人間軸)
