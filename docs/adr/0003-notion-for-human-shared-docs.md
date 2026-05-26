# ADR-0003: 人間共有ドキュメントは Notion を併用する (in-repo Markdown 一本化方針の例外整理)

## ステータス

提案 (2026-05-26)

## 文脈

ADR-0001 で AI 開発ワークフロー全般の方針として **「Notion / Confluence / Linear Docs などの SaaS には設計図を置かない (vendor lock-in、AI 摩擦、コード/ドキュメント分断のため)」** と決めた。これにより:

- ADR / design / architecture / setup notes は `docs/` 配下の Markdown
- Issue 管理は Linear (Docs 機能は使わない)
- 図式は Mermaid

この方針は AI 開発の **継続性・検索性・git 履歴** に強く効いており、運用 6 ヶ月で大きな成果が出ている (Phase 1-8 の蓄積、ADR-0001/0002 採択フロー等)。

一方、運用を続ける中で **「人間相手の共有ドキュメント」**については in-repo Markdown が機能不全になる場面が出てきた:

- **顧客提出物 / 提案書**: 顧客は GitHub アカウントを持たない、PR レビュー UI には慣れていない
- **会議資料 / 議事録**: 複数人の同時編集、コメント、リアクションが Markdown だと弱い
- **ステータス共有 (週次 / 月次)**: 社内メンバーが流し見しやすい場所 (Slack 統合等) が望ましい
- **オンボーディング資料**: 検索性 + リッチコンテンツ (動画埋込等) が必要

これらは AI ワークフローの主要文書 (ADR / design / setup) と性格が異なる。同じツール (in-repo Markdown) で扱うと無理が出る。

加えて 2026-05 時点で **Notion 公式 MCP server** が GA、Claude Code から OAuth + HTTP transport で接続できるようになった (Linear MCP と同じパターン)。これにより「Notion へ AI が直接書く / 読む」が現実的になった。

## 決定

ADR-0001 の方針を **「設計図 (ADR/design/architecture/setup)」** に限定して再解釈し、**「人間共有ドキュメント」** には Notion を併用する。

### 1. 役割分担を明文化する

| ドキュメント種別 | 置き場所 | 理由 |
|---|---|---|
| ADR (なぜ決めたか) | `docs/adr/` (in-repo) | コードとの近接性、git 履歴、AI 再生成耐性 |
| architecture (どう動くか) | `docs/architecture/` (in-repo) | 同上、Mermaid 図 |
| design (何を作るか) | `docs/design/` (in-repo) | 同上 |
| setup notes / runbook | `docs/setup/` (in-repo) | 同上、コードと一緒に bump |
| Issue 管理 | Linear | ADR-0001 既定 |
| **会議資料 / 議事録** | **Notion** (本 ADR) | 同時編集、リアクション |
| **顧客提出物 / 提案書** | **Notion** (本 ADR) | 顧客に GitHub アカ不要、リッチ表現 |
| **ステータス共有 (週次/月次)** | **Notion** (本 ADR) | Slack 統合、流し見しやすい UI |
| **オンボーディング資料** | **Notion** (本 ADR) | 検索性、video/image 埋込 |

### 2. 重複禁止ルール (重要)

**同じ内容を docs/ と Notion の両方に置かない**。各情報の primary owner を 1 つに決める:

- 設計の **why / how / what** は docs/ が primary、Notion からは GitHub blob URL でリンク
- 会議で決めた事項 (議事録) は Notion が primary、設計に昇格したら docs/adr/ に「(議事録: Notion URL)」と注記
- ステータス共有は Notion が primary、内容は Linear Issue から自動引用 or 手動コピペ

### 3. Notion 側の Workspace / Database 設計

elm-inc workspace 内に以下を新設 (運用開始時に手動):

- **`Meeting Notes`** database — 議事録 (タグ: 顧客名 / プロジェクト / 日付)
- **`Customer Deliverables`** database — 顧客提出物 (タグ: 顧客名 / 種別 / ステータス)
- **`Weekly Status`** page — 週次サマリ (Linear Project status をパイプライン的に集約)
- **`Onboarding`** page — オンボーディング資料

### 4. AI 摩擦の許容

Notion content は Markdown と完全互換ではない (block 構造、limited inline format)。AI は:

- Notion から「読む」: `notion-fetch` で取得した結果を Markdown 相当として解釈
- Notion へ「書く」: 平文 + 簡単な block (paragraph, heading, bullet) のみ。複雑なレイアウトは人間が手動編集
- **重要な決定は必ず docs/adr/ に残してから Notion にコピー** (リバース順は禁止)

### 5. セキュリティ・コンプライアンス

- Notion MCP は OAuth ユーザの権限をそのまま継承 (個別ページ制限なし)
- 機密案件のコード断片 / 内部 token を Notion に貼らない (これは docs/ も同様)
- Notion AI 機能 (`notion-search` 等) は要 Notion AI 課金。当面は使わない (`notion-fetch` で URL 直指定する)

## 理由

### Why Notion を併用するのか

- **人間相手の編集体験**: 同時編集 / コメント / リアクション / 通知統合は SaaS の優位
- **顧客との接点**: 顧客に GitHub アカウントを発行するコストよりも、Notion 1 ページ共有のほうが軽い
- **2026-05 時点で MCP 経由 AI 連携が成立**: AI 摩擦を回避しつつ Notion を使える状態になった (これ以前は AI が触れず使えなかった)

### Why "設計図は in-repo" を死守するのか

- ADR-0001 の根拠 (vendor lock-in、AI 摩擦、git 履歴) は引き続き有効
- 設計の真実は **コードと同じ git 履歴** にあるべき (PR 単位で diff 可能)
- AI 再生成耐性: Notion がサービス停止しても docs/ は残る

## 検討した代替案

### 代替案 A: 全部 in-repo Markdown を維持

- Pros: 一貫性、運用シンプル
- Cons: 顧客提出 / 会議資料の機能不全継続、組織コミュニケーションコスト増
- 不採用理由: 既に運用 6 ヶ月で限界が見えた

### 代替案 B: 全部 Notion に移行

- Pros: 編集体験統一
- Cons: ADR-0001 の "AI 摩擦回避" 利点を捨てる、vendor lock-in、git 履歴喪失
- 不採用理由: AI ワークフローの中核を Notion に置くと PR/差分レビュー困難

### 代替案 C: GitHub Wiki / Discussions を使う

- Pros: GitHub 内で完結、git 履歴あり (Wiki)
- Cons: 顧客との接点には依然弱い、リッチ表現も限定
- 不採用理由: 顧客提出物の用途で Notion に劣る

### 代替案 D: Confluence / Docbase / Zenn 等の別 SaaS

- Pros: 似た機能
- Cons: Notion MCP が公式に整備されている (2026-05 時点) のに対し、他は AI 連携が弱い
- 不採用理由: AI 連携の差で Notion 優位

## 帰結

### Pros

- 顧客提出 / 会議 / ステータス共有の UX 改善
- AI ワークフローの主要文書は docs/ 維持で品質保持
- Notion MCP 経由で Claude が「書く / 読む」できる
- 重複禁止ルールで分散の害を最小化

### Cons

- 運用に注意 (どっちに書くべきか毎回判断)
- Notion サービス停止 / 値上げのリスク
- AI が複雑な Notion block を扱えない (人間手動編集が必要なケース)

### 引き受けるリスク

- **重複によるドリフト**: 重複禁止ルールが守られないと docs/ と Notion で矛盾発生 → 月次評価で点検
- **OAuth トークン失効**: Notion MCP は OAuth、6 ヶ月程度で再認証が必要
- **Notion AI 課金圧**: `notion-search` を使いたくなったら Notion AI 課金検討、現状は `notion-fetch` (URL 直指定) で代替

## 関連

- [ADR-0001](0001-multi-llm-development-workflow.md): SaaS に設計図を置かない方針 (本 ADR で例外を整理)
- [ADR-0002](0002-multi-model-test-generation.md): テスト工程多モデル化 (関連なし、参考)
- agent-rules CLAUDE.md "Notion 連携" セクション (本 ADR の運用ガイド)
- Notion MCP server: https://github.com/makenotion/notion-mcp-server
- Notion 公式 docs: https://developers.notion.com/guides/mcp/overview

## 改訂履歴

- 2026-05-26 提案
- (採択時) 1-2 ヶ月運用してから採択判定
