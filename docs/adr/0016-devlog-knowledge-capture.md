# ADR-0016: AI 開発の会話ナレッジを transcript から蒸留して残す (dev-log)

## ステータス

採択 (2026-08-11)

## 文脈

Claude Code で会話しながら開発するアプローチが一般化した。その **craft** — どう状況を説明し・どんな依頼をかけ・どう調整 (steering) し・設計やテストをどう会話で作り込むか — は再利用価値の高いナレッジだが、長い期間では会話が失われると認識されていた。

しかし調査の結果、**会話は失われていない**: Claude Code はセッション全文を `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` に永続化している (role・内容・model・usage・timestamp。サブエージェントログ含む)。本リポの `fable-usage.sh` も既にこれを読んでいる。つまり課題は「ログを取ること」ではなく、**既存の生ログを蒸留し・必要な粒度で出し・機密を守って保管すること**。

制約: transcript には**顧客案件の内容が混ざる** (public リポに生ログを置けない。jooi の教訓と同型)。

## 決定

**既存の transcript を単一ソースに、`/devlog` スキルで粒度別に蒸留し、私的ストアに残す。抽象化した craft パターンだけを agent-rules へ昇格する。**

- **ソース**: `~/.claude/projects/**/*.jsonl` (新規ログ機構は作らない)。会話ターンを抽出して蒸留。
- **粒度**: `summary` / `retro` (主力) / `playbook` (横断の型) / `excerpt` (注釈付き抜粋)。標準フォーマットで書式ブレ・記載漏れを防ぐ ([`docs/design/devlog-standard.md`](../design/devlog-standard.md))。
- **保管 (機密)**: 生の dev-log は `dev-log/` (**gitignore・ローカル専用**)。public に上げるのは案件名・内部設計を**スクラブした抽象パターンだけ**。
- **昇格**: retro の「再利用できる型」を台帳 (ローカル) 経由で 2 回目に agent-rules へ (skill/rule/プレイブック)。台帳・design-registry と同じ「私的な生 + 公開の抽象」構造。
- **タイミング**: オンデマンド + Stop hook の促し + 週次ロールアップ (任意)。

## 理由

- **生ログは既にある**: 新規ログ機構は不要で、蒸留に集中できる。手動リアルタイムメモは漏れるが、transcript は安全網。
- **粒度分離**: 「1 行要約」から「横断プレイブック」まで用途が違う。1 スキルの引数で出し分ける。
- **機密の構造分離**: 生 = 私的、抽象 = 公開。台帳・design-registry で確立したパターンを踏襲し、jooi 型のリークを構造的に防ぐ。
- **既存資産と接続**: 昇格台帳 (ADR-0013)・docs-publish (ADR-0012)・Stop hook にそのまま乗る。

## 検討した代替案

### 代替案 A: リアルタイムで手動メモを取る
- 不採用理由: 会話に集中していると漏れる。transcript が既に全量あるので蒸留の方が確実。手動メモは補助に留める。

### 代替案 B: 生 transcript をそのまま保管・検索
- 不採用理由: 5MB/セッション級で冗長、tool ノイズが多く、機密が生のまま。蒸留 + 私的保管が扱いやすい。

### 代替案 C: 蒸留結果を agent-rules (public) に置く
- 不採用理由: 顧客案件の内容が混ざるため public 不可。抽象化したものだけを昇格する。

### 代替案 D: 外部ツール (専用ログ SaaS) に送る
- 不採用理由: 機密の外部送信リスク。in-repo (私的) + Markdown の方針を保つ。

## 帰結

### Pros
- 消えると思われていた会話 craft が、既存 transcript から粒度別に取り出せる
- 機密は私的ストアに隔離、抽象パターンだけ公開昇格 (リーク防止)
- 昇格台帳・docs-publish・Stop hook と接続し運用に乗る

### Cons / 限界
- 蒸留は会話から読み取れた範囲 (LLM の要約品質に依存)。捏造しない運用が要る
- 私的ストアは単一マシン (複数マシン集約は将来課題 or 別 private repo)
- Stop hook の促しは適度に (毎回だとノイズ)

### 関連 ADR
- [ADR-0013](0013-three-layer-knowledge-architecture.md) — 昇格ルール / 私的な生 + 公開の抽象
- [ADR-0012](0012-human-facing-docs-publish-model.md) — docs-publish で共有用に出力
- [ADR-0010](0010-fable-metered-billing-controls.md) — transcript を読む先例 (fable-usage.sh)
