# ADR-0013: 3 層ナレッジアーキテクチャと台帳型昇格ルール

## ステータス

採択 (2026-07-24)

## 文脈

複数プロジェクトで Claude Code を並行活用しているが、各プロジェクトで設計・実装をゼロベースに行っており、横断で再利用できるはずのナレッジ (設計判断・実装パターン・規約・初期構成) が蓄積されない。同時に、global CLAUDE.md (agent-rules 管理・symlink 配布) は 280 行と自ら掲げる 200 行上限を超過し、スキル description と重複するルーティング表がトークンを浪費している。

前提となる事実 (詳細: [docs/design/claude-md-restructure.md](../design/claude-md-restructure.md)):

- 公式ベストプラクティスは CLAUDE.md ≤200 行 + ruthless pruning、`.claude/rules/` の paths スコープと symlink 共有を明記
- **paths スコープ rules は「該当ファイル読込時」にしかロードされない** — New Relic テナント取り違えや Figma 生 curl のような「操作時」の安全原則の置き場にならない
- **project memory はプロジェクト毎に隔離**されており、「別プロジェクトで同じことを 2 回した」ことを記憶ベースでは検知できない。既存の自己点検 hook は elm-inc の `settings.local.json` にのみ存在し他プロジェクトで発火しない
- community skills の 36% に prompt injection が検出されており、外部 skill/MCP の無審査導入はリスク

## 決定

プロジェクト横断ナレッジを **3 層**で管理し、**台帳照合型の昇格ルール**で層間を接続する。

1. **L1 判断基準** (agent-rules 本体 → symlink で全プロジェクト常時適用): CLAUDE.md (~150 行・≤200 行 CI 強制) / RULES.md / 操作時の安全原則 6 項目 / permissions ベースライン。`~/.claude/rules/` 層は使わない (層を増やさない)
2. **L2 再利用資産** (プロジェクト初期化時に展開): templates (docs 構造・settings 雛形・CI) + stack 別 `.claude/rules/` + skills。新設 `/project-init` (docs-init を内部で呼ぶ上位オーケストレータ) が一括展開。**リポにコミットする資産はコピー、~/.claude 配下は symlink**。stack 別 rules は初期 0 個で成立し昇格が埋める
3. **L3 プロジェクト固有**: 各リポ CLAUDE.md + project memory

**昇格ルール (2 回目ルール・台帳照合型)**: 横断再利用しそうな設計判断・パターンは 1 回目に中央台帳 `docs/notes/promotion-candidates.md` へ記録し (uncommitted 追記でよい・コミットは昇格 PR 時)、記録時に既存候補と照合。一致 (=2 回目) したら agent-rules へ昇格する。昇格先判定: 判断 → CLAUDE.md / ツール横断安全原則 → RULES.md / ファイル種別規約 → paths rules / 手順 → skill / 初期構造 → template / なぜ → ADR。検知経路はユーザーレベル Stop hook と /status の候補サマリ表示で三重化する。**逆方向**として四半期見直し (台帳 `review_by` 期限を /status が警告) で参照されない行を降格・削除する。

**settings の適用モデル**: 初回適用は手動 (テンプレ提示 + ユーザー確認)。以降の drift は doctor `--fix` による **add-only 差分マージ** (新規キーのみ追加・既存キーは上書きしない・衝突は表示して skip) で解消し、install.sh / /status が差分を通知する。盲目的な自動 merge はしない。

**CLAUDE.md の刈り込み原則**: 残すのは「個別スキル・ドキュメントから導けない横断的判断基準」と「操作時に効く安全原則」のみ。ドメイン固有詳細は paths rules・docs・SKILL.md へ降格し、**散文ルールで失う抑止力は permissions (deny/ask) の機械的 enforcement で置き換える**。刈り込みは「移設先追加 → 削除」の 2 段 PR で行う (symlink 即時配布のため)。

## 理由

- **台帳照合型にした理由**: 記憶 (memory) ベースの「2 回目」検知は project memory の隔離により構造的に不可能。台帳は 1 回目の記録時点で照合が完結し、検知が人・モデルの記憶力に依存しない
- **操作時の安全原則を CLAUDE.md に残す理由**: paths rules はファイルを読まずコマンドを打つ瞬間 (テナント誤クエリ・生 curl) にコンテキストへ存在しない。常時ロードされる CLAUDE.md と permissions の 2 層だけがその瞬間に効く
- **permissions 置き換えを柱にする理由**: 行数を消費せず、prompt injection 下でも機能する機械的抑止。公式の permission + sandbox 2 層ゲート推奨とも一致
- **初期 0 個の L2 rules**: 中身のないルールの先行量産は「この指示がないと誤るか」基準に反する。実需 (2 回目) 駆動で埋める方が形骸化しない

## 検討した代替案

### 代替案 A: 現状維持 (プロジェクト毎ゼロベース + 肥大 CLAUDE.md)
- Pros: 移行コスト 0。
- 不採用理由: ゼロベース設計の繰り返しが続き、CLAUDE.md の全プロジェクト×全サブエージェントへのトークン浪費も解消されない。

### 代替案 B: memory ベースの昇格 (共有 memory ディレクトリ)
- Pros: 既存の memory 運用の延長で導入が軽い。
- 不採用理由: project memory は隔離が仕様であり、共有化はプロジェクト文脈の混線を招く。「2 回目」の照合主体も結局定まらない。

### 代替案 C: monorepo 化 (全プロジェクトを 1 リポに集約)
- Pros: ナレッジ共有は自明になる。
- 不採用理由: 顧客案件 (別テナント・別リポ) を混在できない。受託構造と相容れない。

### 代替案 D: MDM / managed-settings による強制配布
- Pros: 強制力が最も高い。
- 不採用理由: 開発者 1 人の体制に過剰。テンプレ + 初回手動適用 + doctor の add-only 差分マージで十分。

### 代替案 D': settings を純手動適用のみで運用 (自動マージ一切なし)
- Pros: 既存設定破壊リスクが理論上ゼロ。
- 不採用理由: redteam (DeepSeek-R1) の指摘どおり、手動は確実に漏れ、新しい deny ルールが恒久的に未適用となって**安全レベルが時間とともに劣化する**。add-only マージ (既存キーを決して上書きしない) は破壊リスクを構造的に排除しつつ drift を防げる。

### 代替案 E: ドメイン安全原則も paths rules へ全降格
- Pros: CLAUDE.md が最小化する。
- 不採用理由: paths rules のロード条件 (ファイル読込時) と安全原則の発火条件 (操作時) が一致しない。事故防止に直結する情報が必要な瞬間にコンテキストへ無い。

## 帰結

### Pros
- 「2 回目」が仕組みで検知され、ゼロベース設計の繰り返しが構造的に減る
- CLAUDE.md が ~150 行に戻り、全プロジェクト・全サブエージェントの常時ロードコンテキストが削減される (乗算で効く)
- 安全原則は残置 + permissions の 2 層で刈り込み前より強くなる

### Cons / 限界
- 台帳運用・四半期見直しの規律コストが残る (hook + /status 表示で軽減するが 0 にはならない)
- settings 雛形は手動適用のため、適用漏れは doctor 検出まで顕在化しない
- 効果 (初期工数削減) の定量評価は /project-init 運用開始後にしか得られない

### 受け入れ基準・実行計画

[docs/design/claude-md-restructure.md](../design/claude-md-restructure.md) §5-6 に記載 (基準は各々検証手段付き)。

### 関連 ADR
- [ADR-0009](0009-separate-templates-from-docs.md) — templates 分離 (L2 の基盤。/project-init は docs-init の契約を保ったまま上位で呼ぶ)
- [ADR-0010](0010-fable-metered-billing-controls.md) — コスト規律 (CLAUDE.md 残置の安全原則 3 に対応)
- [ADR-0011](0011-ai-first-docs-architecture.md) — エビデンス規律・CI 基盤 (行数/相互参照 lint の載せ先)
- [ADR-0001](0001-multi-llm-development-workflow.md) / [ADR-0006](0006-orchestration-methods.md) — 本 ADR が索引を刈り込む対象のワークフロー本体

## 改訂履歴

- **2026-08-11 追記 (台帳のローカル専用化)**: 昇格台帳 `docs/notes/promotion-candidates.md` を **gitignore・ローカル専用**に変更した。agent-rules は public リポであり、台帳に他プロジェクト (機密顧客案件を含む) の名称・内部設計が生エントリとして蓄積されるのは情報リーク源になるため。本文の「uncommitted 追記でよい・コミットは昇格 PR 時」は次のとおり訂正する: **台帳自体は commit しない**。commit するのは昇格後の**抽象化された rule / ADR** だけ (案件名・内部設計を落とした一般形)。検知・照合はローカルの台帳で従来どおり機能する (単一マシン運用が前提。複数マシン集計は将来課題のまま)。
