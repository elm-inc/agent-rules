---
title: AI ファースト・ドキュメント整備の設計 (3層モデル)
type: design
status: draft
audience: internal
owner: tomohisa-masaki
updated: 2026-07-03
related:
  - docs/adr/0001-multi-llm-development-workflow.md
  - docs/adr/0003-notion-for-human-shared-docs.md
  - docs/adr/0009-separate-templates-from-docs.md
depends_on: []
supersedes: []
---

# AI ファースト・ドキュメント整備の設計 (3層モデル)

- Linear: (未起票)
- 関連 ADR: [ADR-0011](../adr/0011-ai-first-docs-architecture.md) (AI 軸) / [ADR-0012](../adr/0012-human-facing-docs-publish-model.md) (人間軸)

## 1. 背景・目的

本リポは「git の Markdown が唯一の真実 (SSOT)、SaaS に設計図を置かない」(ADR-0001) を軸に、ADR / architecture / design / setup を in-repo Markdown + Mermaid で運用してきた。ここに **AI ファースト (機械可読)** の観点でドキュメント整備方法・記述ルールを再設計し、加えて **構造管理 (ナレッジグラフ層)** と **人間向け (クライアント・ベンダー) 配布** を体系化する。

制約として本リポは一貫して **二重管理・drift を強く嫌う** (多言語ディレクトリ分割を二重化理由で却下、ADR-0003 の重複禁止)。この価値観を設計の第一原理に据える。

### 調査サマリ (2026-07 時点、出典は §9)

- **`llms.txt`**: 大手 LLM プロバイダ (OpenAI/Anthropic/Google) に**事実上無視されている** (ボットが取得しない・引用数と相関ゼロ)。かつドメイン root で HTTP 配信される前提の規格で、GitHub 上 Markdown を配信しない本リポでは**クローラー向け価値はほぼ無い**。`llms-full.txt` は非標準の実装バリアント。→ SEO 目的では採用しない。**自動生成する索引概念としてのみ再解釈**する。
- **AI ファースト docs の潮流**: `AGENTS.md` (Linux Foundation ホスト、de facto 入口) + `SKILL.md` (能力) + frontmatter-first (先頭の YAML を先読みして本体取得を判断) が主流。機械可読と人間可読は**別ファイルに割らず同一 Markdown を層分け**。セマンティックチャンキングは費用対効果が薄い (固定長で十分)。ADR は「過去の説明」から「将来の制約 (見直し日・無効化条件)」へ。
- **ナレッジグラフ**: docs-as-code の落としどころは**軽量・派生・決定論** (frontmatter / wikilink を構文解析してグラフを導出、Markdown が SSOT、グラフは生成物)。GraphRAG / RDF・OWL は重く drift リスクが高いので後回し。

## 2. 統一原則

> **SSOT は git の Markdown。索引層・グラフ層・人間向け配布物は、すべて SSOT から派生生成する。人が同じ情報を二度書かない。**

この 1 行が全設計を貫く。派生物 (llms.txt、関係グラフ、PDF/slides/Notion) は `_` 接頭辞・生成物として扱い、CI が再生成し、手書きしない (ADR-0009 の「`_` = メタ / それ以外 = 中身」を踏襲)。

## 3. アーキテクチャ (3層 + 人間軸)

```
        ┌─── 派生・生成物 (人は書かない / CI が生成 / drift しない) ───┐
  索引層 │  docs/llms.txt         … エージェント巡回索引 (自動生成)      │
  グラフ層│  docs/_graph/*         … frontmatter から決定論導出 + drift 検出│
        └──────────────────────▲ 生成 ─────────────────────────────┘
                               │
  ┌──── Layer 0 = SSOT: 人が書く唯一の場所 ─────────────────────────┐
  │  in-repo Markdown + YAML frontmatter                            │
  │  docs/{adr,architecture,design,setup}  +  AGENTS.md / SKILL.md   │
  └──────────────────────────│ publish (primary-owner: ADR-0003) ───┘
                             ▼
  ┌──── Layer 3 = 人間向け (別軸・可読性優先) ──────────────────────┐
  │  Notion (協働) / PDF・slides (配布)  ← Markdown から publish 派生 │
  └────────────────────────────────────────────────────────────────┘
```

## 4. Layer 0 — 記述ルール (SSOT の底上げ)

一番効く投資。機械可読性は同一 Markdown を frontmatter + 見出し + anchor で層分けして得る。

### 4.1 frontmatter スキーマ (全 doc 共通)

```yaml
---
title: <人間可読タイトル>
type: adr | architecture | design | setup | reference | how-to | tutorial | explanation
status: draft | proposed | accepted | superseded | deprecated
audience: internal | external          # 【必須】Layer 3 の分離キー。既定 internal (fail-closed)
owner: <担当>
updated: YYYY-MM-DD
# 関係 (Layer 2 グラフの材料。ここだけに書く = 二度書きしない)
related: [<path>, ...]
depends_on: [<path>, ...]
supersedes: [<path>, ...]
superseded_by: [<path>, ...]
implements: [<path>, ...]
---
```

- `type` は Diátaxis (tutorial/how-to/reference/explanation) + 本リポ固有型 (adr/architecture/design/setup)。検索・RAG での識別性を上げる。
- 関係フィールドは **グラフ層の唯一の材料**。グラフを別管理しない。
- **`audience` は必須・fail-closed**: 未設定/不明は **internal 扱い**。publish パイプラインは `audience: external` が**明示されている doc のみ**外部出力する (既定で漏らさない)。本リポの fail-closed 原則 (New Relic テナント・gh アカウントの取り違え防止) と同型。

### 4.2 ADR 固有の追加欄 (future-guard)

```yaml
review_by: YYYY-MM-DD                   # いつ見直すか
invalidation_condition: <何が変われば無効か>
```

「過去の決定の説明」から「将来の制約」への潮流を反映。ADR-0003 の「1-2 ヶ月後に採択判定」も `review_by` で機械管理できる。

### 4.3 本文の書き方 (retrieval-friendly)

- **セクション自己完結**: H2 を `type` に沿って区切り、「上記」「これ」等の coreference を避ける。安定 anchor を付ける。
- **one-fact-one-place**: 定義・設定・例は単一ファイル。参照はリンクのみ (既存の価値観を lint で強制)。
- **過剰なチャンク最適化はしない**: セマンティックチャンキングは費用対効果が薄い。見出しで自然に区切る程度で十分。
- **人間可読性を犠牲にしない**: frontmatter は機械用、本文は人間用。両立させる。

## 5. Layer 1 — 索引層 (`llms.txt` の再解釈)

**位置づけ (正直に)**: 外部クローラー対策としては無効 (§1)。本リポでは「**自分たちのエージェント (Claude Code / 将来の RAG・MCP doc サーバー) が docs を巡回する機械可読索引**」+「規格普及時の先行投資」として、生成コスト ≒0 で持つ。既存の MEMORY.md 索引・CLAUDE.md ルーティングの docs 版。

- `scripts/gen-docs-index.*` が SSOT の frontmatter を読み、`docs/llms.txt` を生成:
  - H1 = プロジェクト名、blockquote = 要約
  - H2 セクション (ADR / architecture / design) に `[title](path): <要約>` を列挙 (frontmatter から)
  - 低優先 (setup notes 等) は "Optional" 節
- **手書き禁止**。生成物は**リポにコミットしつつ CI で鮮度チェック**する: 「再生成して `git diff` が空でなければ fail」。これで (a) 生成物が GitHub 上で閲覧可能、かつ (b) 手書き編集・drift を機械的に弾ける (`.gitignore` 除外にはしない — 見えなくなるため)。
- `llms-full.txt` (全文結合) は非標準・重複増なので**作らない** (必要になってから)。

## 6. Layer 2 — グラフ層 (ナレッジグラフを構造化レイヤーとして挟む)

**採用: 軽量・派生・決定論** (今回の決定)。手書きグラフ DB を別管理せず、Layer 0 の frontmatter を構文解析してグラフを導出する。

- `scripts/docs-graph.*` が frontmatter の関係 (`depends_on` / `supersedes` / `superseded_by` / `implements` / `related`) と doc 間リンクを解析し:
  1. **関係図を再生成** (`docs/_graph/relations.md` に Mermaid、`docs/_graph/graph.json` に機械可読)
  2. **drift 検出を CI に出す** (fitness function):
     - リンク切れ (関係先ファイルが存在しない)
     - supersede 済みなのに他 doc から現役参照が残る
     - `review_by` 超過の ADR
     - `superseded_by` と `supersedes` の非対称 (片方向リンク)
     - **`depends_on` の循環** (A→B→A)。グラフ導出は **cycle-safe** (visited set で無限ループを防ぐ) にし、循環はモデリングの臭いとして drift 報告する
- **生成物はコミット + CI 鮮度チェック** (§5 と同じ「再生成して diff が空か」)。手書き `_graph/` を弾く。
- **drift の逃さない運用**: CI ログに埋もれさせず、超過 `review_by` や未解消 drift は本リポの宿題昇格ルール (3 日以上/共有要 → GitHub Issue、進捗は Linear) に載せて追跡する。
- これは、以前 `architecture/README` が参照するだけで**実体が無かった `/docs-sync`** を、本当に実装するもの。
- **GraphRAG / LightRAG は今回入れない** (初期化コスト・運用が重く現規模でオーバースペック)。派生グラフさえ持てば、後から Markdown を変えずに接続できる。
- **RDF/OWL・正式オントロジーは不採用** (手書き二重管理・drift 高リスク)。

## 7. Layer 3 — 人間向け (クライアント・ベンダー) 配布

AI 軸から**意図的に分離**。ADR-0003 (人間共有 = Notion) を「audience 分離 + publish 派生 + 多フォーマット」で拡張する (今回の決定)。

- **分離キー**: frontmatter `audience: internal | external` (必須・fail-closed、§4.1)。外部配布物を AI ファーストの frontmatter 過多な技術 docs と混ぜない。
- **publish 派生原則** (ADR-0003 重複禁止の具体化): 内部設計 (docs/) を客先共有する場合は、**Markdown から人間向けレンディションを生成して配る**。複製して個別編集 (fork) しない = drift を作らない。primary owner は常に片方 (docs/ か Notion か) に固定。クライアント修正依頼は**生成元 (Markdown) を直し再生成**する (PDF を直接いじらない)。
- **粒度**: audience は **doc 単位**が原則。外部可の決定と内部限定の議論が混ざるなら**ファイルを分割**する (one-fact-one-place と整合)。どうしても 1 ファイルに混在させる場合のみ、`<!-- publish:begin-exclude -->` … `<!-- publish:end-exclude -->` の区間を publish パイプラインが**必ず除去**する (除去に失敗したら外部出力を中止する fail-closed)。
- **多フォーマット (in-repo Markdown DNA のまま)**:
  - Markdown → **スライド**: Marp / reveal.js (登壇・提案)
  - Markdown → **PDF**: pandoc / typst (提案書・納品物)
  - Markdown → **Notion**: 既存 MCP 経由 (協働・議事録は Notion 原本)
  - **Mermaid の描画に注意**: pandoc/Marp は素では Mermaid を描画しない。publish パイプラインに mermaid フィルタ (mermaid-filter / marp mermaid プラグイン等) を必ず組み込み、図が欠落したまま配布されないようにする。
- **読みやすさ**: 外部向けは Diátaxis の explanation/tutorial 寄りの散文にし、配布物に frontmatter・メタを出さない (生成時に除去)。

## 8. 受け入れ基準 (完了の定義)

### 機能要件

- [ ] 全 doc テンプレ (templates/docs/) に §4.1 frontmatter スキーマが入り、`/docs-init` で展開される
- [ ] ADR テンプレに §4.2 future-guard 欄 (`review_by` / `invalidation_condition`) が入る
- [ ] `docs/llms.txt` が frontmatter から**自動生成**され、**コミット + CI 鮮度チェック**で手書き・drift を弾く
- [ ] frontmatter の関係から**関係グラフが再生成**され、drift lint (リンク切れ / supersede 残り / review_by 超過 / **循環参照**) が CI で回る。グラフ導出は **cycle-safe**
- [ ] `audience` は**必須・fail-closed** (未設定=internal)。外部配布は `external` 明示 doc のみ publish 派生 (Marp/pandoc/Notion)、mermaid フィルタ込み
- [ ] 決定が ADR-0011 (AI 軸) / ADR-0012 (人間軸、ADR-0003 拡張) に記録される

### 制約

- 既存 doc を壊さない (**移行猶予期間中**は frontmatter 欠落を warn、猶予後は CI hard-fail で常態化を防ぐ)
- 二重管理を新たに生まない (索引・グラフ・配布物はすべて派生生成 + 鮮度チェック)
- CLAUDE.md は <200 行の索引を維持 (詳細は本設計書と各 SKILL/README に逃がす)

### 非対象 (out of scope)

- **多言語 (JA/EN) 対応** — 二重化・翻訳 drift 回避のため前回意図的に不採用 (盲点ではなく決定)。必要時はオンデマンド翻訳 (永続化しない)
- GraphRAG / LightRAG / ベクトル検索の構築 (後続。派生グラフで前提だけ作る)
- RDF/OWL・正式オントロジー
- MCP doc サーバーの公開
- セマンティックチャンキング
- `llms-full.txt` の生成

## 9. 出典 (2026-07 調査)

- llms.txt: [Answer.AI 提案 (2024-09-03)](https://www.answer.ai/posts/2024-09-03-llmstxt.html) / [llmstxt.org](https://llmstxt.org/) / [大手ボット無視の監査](https://aeoengine.ai/blog/llms-txt-zero-usage-ai-bots-ignore) / [採用停滞報告](https://ppc.land/llms-txt-adoption-stalls-as-major-ai-platforms-ignore-proposed-standard/)
- AI ファースト docs: [AGENTS.md (GitHub)](https://github.com/agentsmd/agents.md) / [frontmatter-first 論](https://medium.com/@michael.hannecke/frontmatter-first-is-not-optional-context-window-survival-for-local-llms-in-opencode-15809b207977) / [Diátaxis](https://idratherbewriting.com/blog/what-is-diataxis-documentation-framework) / [ADR×AI テンプレ](https://www.institutepm.com/knowledge-hub/ai-architecture-decision-record-template) / [Agent-Friendly Docs](https://dacharycarey.com/2026/02/18/agent-friendly-docs/)
- ナレッジグラフ: [GraphRAG (Microsoft)](https://www.microsoft.com/en-us/research/project/graphrag/) / [Markdown KG for Agents (IWE)](https://dev.to/gimalay/markdown-knowledge-graph-for-humans-and-agents-43c4) / [ADR as Knowledge Graph](https://www.nilus.be/blog/architecture_decision_records_as_knowledge_graph_in_distributed_systems/) / [ADR fitness functions](https://platformtoolsmith.com/blog/operationalizing-adrs-fitness-functions/)

## 10. 段階 (過剰設計を避ける)

| フェーズ | 内容 |
|---|---|
| P1 (今回) | §4 記述規約 + ADR future-guard 欄 + テンプレ更新 + ADR-0011/0012 |
| P2 | `gen-docs-index` (llms.txt 自動生成) + pre-commit 検証 |
| P3 | `docs-graph` (関係図再生成 + drift lint) を CI に |
| P4 | 人間向け publish パイプライン (Marp/pandoc) を skill 化 |
| 後続 | 必要になれば GraphRAG / MCP doc サーバー (Markdown 不変で接続) |
