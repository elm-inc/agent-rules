# Claude Code 設定

**重要: 最初に `~/RULES.md` を読み込み、記載されたルールをすべて遵守すること。**

このファイルは「いつ何のスキルを使うか」のルーティング索引 + プロジェクト横断の判断基準・安全原則。各仕組みの手順・内部詳細は各 `SKILL.md` / `docs/` にあり、リンクで辿る (詳細は重複させない)。3 層ナレッジ構成と昇格ルールの根拠: [`docs/adr/0013`](docs/adr/0013-three-layer-knowledge-architecture.md) / [`docs/design/claude-md-restructure.md`](docs/design/claude-md-restructure.md)。

## AI 開発ワークフロー (多層・多モデル)

実装は **Claude Opus 5** (司令塔・セッションモデル)、レビュー・検証・テスト生成は多層化する。Codex/DeepSeek/Gemini/Qwen はスキル経由で呼ぶ「ツール」で司令塔にはならない。
全体像: [`docs/design/ai-workflow.md`](docs/design/ai-workflow.md) / 根拠: [`docs/adr/0017`](docs/adr/0017-ai-workflow-model-refresh-and-review-layers.md) (ADR-0001 を Supersede), [`docs/adr/0006`](docs/adr/0006-orchestration-methods.md)。

### レビューの 4 層 (層ごとに「何のために置くか」が違う)

| 層 | 目的 | 手段 | いつ |
|---|---|---|---|
| **床 (機械)** | 決定論的に取れるものを 0 円で取る | pre-commit (ruff/mypy/semgrep) | **常時・必須** |
| **床 (LLM)** | 意図と実装の食い違いを独立視点で見る | `/local-review` | **機密案件は必須** / 公開リポは任意 |
| **多様性** | groupthink 回避 | **異ベンダーを 1 つだけ**: 設計 → `/deepseek-redteam` / 横断 → `/gemini-review` / 実装視点 → `/codex-review` | 差分の性質で選ぶ |
| **深さ** | 指摘を敵対的に検証して絞る | `/code-review` (巨大タスクは Workflow ファンアウト) | 品質を上げたいとき |
| **最後の砦** | 下流への波及が大きい変更 | `/fable-review` | 高リスク変更のみ |

**高リスク変更 (セキュリティ・課金・データ破壊・公開 API・並行処理) では「多様性」層を省略しない。** `/code-review` も `/fable-review` も Claude 系なので、砦だけ通すと異ベンダーの独立視点がゼロになる。

> **床は機械と LLM の 2 本立てで、どちらも単独では穴が残る** (2026-08-17 実測: [`docs/design/ai-workflow.md`](docs/design/ai-workflow.md) §4-1)。linter は「ファイル未 close」を数ミリ秒で取るが**意味的バグは全ルールで 0 件**。LLM は off-by-one・lock 範囲・変数同士の `is` を取るが「未 close」は 6/6 見逃した。**和集合で初めて全件**になる。
>
> **`/local-review` の起動条件**: 機密案件 (cloud 送信不可) では**唯一の LLM 選択肢なので必須**。公開リポで異ベンダーを 1 つ回すなら**独立視点として重複するので省略可**。レビュー層の真のコストは計算資源ではなく**読み手の注意**で、0 円でも冗長な指摘は負債になる。

> **安全原則 (多様性はハーネスでは買えない)**: `/code-review` 系の多エージェント検証は**全部 Claude なので groupthink を原理的に解けない**。逆に自前スキルは敵対的検証ループを持たない。**多様性は自前スキル、深さはハーネス**と役割を分け、**異ベンダーは常時 1 つまで** (2 つ回すコストに見合う追加検出は無い)。

| その他のロール | スキル |
|---|---|
| 高難度実装・設計 (Fable 5 subagent) | `/fable-task` |
| セカンドオピニオン (Codex) | `/codex-review`・`/codex-task`・`/codex-audit` |
| テスト観点・実装 / データ / 健全性 | `/test-generate` / `/test-data` / `/mutation-check` |
| 探索・調査の床 (Haiku subagent) | `explorer` / `researcher` (`~/.claude/agents/`) |

### モデル使い分け (Opus 5 / Fable 5)

常用は **Opus 5**。**Fable 5** は「**手戻り・正しさ・品質が下流に大きく波及するか**」を物差しに、価値が高い局面で subagent 委譲する (委譲前に一言宣言し「なぜ Opus では不足か」を 1 行添える)。局所的・機械的・低リスクなタスクは Opus のまま。使いどころの条件表は各 SKILL.md (`/fable-task` = 設計/難実装/調査/品質引き上げ、`/fable-review` = セキュリティ・課金・公開 API・並行処理などの高リスク変更に限定)。セッション全体を Fable にするのは単発・完全自律の超高難度ミッションのみ (`/model fable`)。**Opus 5 は 4.8 と同価格で能力が上がったため、Fable に投げる閾値は以前より高く取る** (まず Opus 5 を effort 高めで試す)。

> 🔒 **安全原則 (モデル ID は台帳が単一ソース)**: スキル/スクリプトにモデル ID を直書きしない。[`config/models.yml`](config/models.yml) を先に更新し `bash scripts/model-doctor.sh` を通す。**ベンダーは黙ってモデルを消す** — `deepseek-reasoner` の退役に 3 週間気づけず `/deepseek-redteam` が壊れたままだった事故の再発防止 (ADR-0017)。CI (`model-drift.yml`) が drift を落とす。 <!-- model-doctor:allow (事故の説明として言及) -->

> 💰 **安全原則 (Fable コスト規律・従量課金 2026-07-20〜)**: Fable 5 は Max では**週次上限の 50% まで included (恒久)、超過分のみ実費** ($10/$50 per MTok = Opus の 2 倍)。included 枠があっても「余っているから念のため Fable」は不成立 (Opus 等と週次上限を食い合う)。**1 タスク 1 委譲 (往復＝追加実費)・委譲前宣言・statusline 監視**を徹底。当月 $ は `scripts/fable-usage.sh` が集計し statusline に常時表示 (included 未考慮の上限見積り・実費の正は Console。予算 $100/月 = 超過分への予算)。超過後も止めないが起動前に要否を都度確認 (人手ゲート)。根拠: [`docs/adr/0010`](docs/adr/0010-fable-metered-billing-controls.md) (07-23 改訂)

### 運用規律・実行方式

- **並列分解は最大 5、>10 は無益** (サブエージェント多用はトークン約 7 倍)。探索・調査は Haiku subagent に、Fable は数少ない難所のみ (**安全原則: サブエージェント規律**)
- 巨大タスクで網羅性が要る時は決定論的な並列ファンアウト (Workflow: finders→敵対的検証→統合 / loop-until-dry) を明示的に使う。協調が要る独立セッション群は Background Agents / Agent Teams を検討 (worktree 並列の次段)
- 各レビュー層の所見は **集約→重複排除→重要度ランク付け** してから対処 (敵対的検証)

### コミット時のフロー (推奨)

```
[設計] docs/design/foo.md 起草 (受け入れ基準 + 検証手段付き) → /deepseek-redteam
[実装] Opus 5 (高難度は /fable-task で Fable 5 委譲)
[コミット前] 床(機械): pre-commit (ruff/mypy/semgrep)          ← 常時・必須
             床(LLM):  /local-review — 機密案件は必須 / 公開リポは任意
                       (必要時) /test-generate
             多様性: 異ベンダーを 1 つ選ぶ
                     設計を疑う→/deepseek-redteam / 10+ファイル・ADR drift→/gemini-review
                     実装視点→/codex-review
             深さ:   /code-review (敵対的検証)
             砦:     /fable-review (高リスク変更のみ)
[実行検証] /verify, /run, E2E (UI はスクショ)
```
軽微な変更では **床のみ**で十分。機械層 (pre-commit) は常時必須、LLM 層は文脈で判断する。多様性と深さは毎回回さない。

> **安全原則 (vLLM は停止が既定)**: ローカル LLM (vLLM) は普段停止しているのが正常 (オンデマンド起動)。`/local-review`・`/test-generate`・`/test-data` は `ensure-vllm.sh` で自動起動する (初回 1-2 分・アイドル 15 分で自動停止。現行モデル: Qwen3-Coder-30B-A3B AWQ4bit)。**「vLLM が停止しているのでローカルレビューを中止」は誤り** — 停止は既定状態であって利用不可ではない。自前で `:8000` を叩いて落ちていても中止せずスキル経由で起動して続行。本当に起動不可 (GPU 専有等) のときのみ `/codex-review` に切替。根拠: [`docs/adr/0005`](docs/adr/0005-on-demand-local-llm.md) / セットアップ: [`docs/setup/local-llm.md`](docs/setup/local-llm.md)

### Claude Code 開発プラクティス (公式準拠)

- **開発ループ**: Explore → Plan → Review → Execute。高リスク・大規模変更は **plan モード**で計画をレビューしてから実行
- **文脈管理**: CLAUDE.md は <200 行の索引に保つ。ファイル種別ごとの規約は `.claude/rules/*.md` (`paths:` スコープ・該当ファイル読込時のみロード) に逃がす。雛形: [`templates/claude-rules/`](templates/claude-rules/README.md)
- 公式ガイド: [common-workflows](https://code.claude.com/docs/en/common-workflows) / [permission-modes](https://code.claude.com/docs/en/permission-modes) / [memory](https://code.claude.com/docs/en/memory)

## ナレッジ昇格ルール (プロジェクト横断共通化)

各プロジェクトでゼロベース設計を繰り返さないための仕組み ([`ADR-0013`](docs/adr/0013-three-layer-knowledge-architecture.md))。3 層構成: **L1 判断基準** (本ファイル・RULES.md — symlink で全プロジェクト常時適用) / **L2 再利用資産** (`templates/`・`.claude/rules/`・skills — `/project-init` で展開) / **L3 プロジェクト固有** (各リポ CLAUDE.md・memory)。

**2 回目ルール (台帳照合型)**: 横断再利用しそうな設計判断・実装パターン・調査に触れたら **1 回目に中央台帳 `docs/notes/promotion-candidates.md` へ記録**。記録時に既存候補と照合し、**一致 (=2 回目) したら agent-rules へ昇格**する。project memory はプロジェクト毎に隔離されるため、この台帳が唯一の横断検知点。**台帳は gitignore・ローカル専用** (機密案件情報が public に混入するのを防ぐ)。**コミットするのは昇格後の抽象化された rule/ADR だけ** — 台帳の生エントリ (案件名・内部設計を含みうる) は commit しない。

**昇格先**: いつ何を使うかの判断 → 本ファイル / ツール横断 (Codex too) の安全原則 → RULES.md / ファイル種別・stack 規約 → `.claude/rules/*.md` / 手順 → skill / 初期構造 → template / なぜ → ADR。**逆方向**: 四半期見直しで参照されない行を降格・削除 (再肥大化防止)。

**会話 craft の記録**: `/devlog` — セッションの会話 (説明・依頼・調整・設計/テストの作り込み) を Claude Code の transcript から蒸留し、**私的 dev-log (`dev-log/`・gitignore) に粒度別** (retro/summary/playbook/excerpt) で残す。会話は消えず transcript に永続化されている。良い型はスクラブして上記台帳経由で昇格。根拠: [`ADR-0016`](docs/adr/0016-devlog-knowledge-capture.md) / 標準: [`docs/design/devlog-standard.md`](docs/design/devlog-standard.md)。

## 並列開発 (git worktree)

タスクごとに worktree を分離。**メインワークツリーでは直接コード変更しない** (常に main・クリーンを保つ)。

| スキル | 用途 |
|--------|------|
| `/worktree-start <名> <説明>` | worktree 作成 + タスク登録 (`--linear <ID>` で Issue 連携 / `--tab` で別 zellij タブに引き継ぎ起動) |
| `/worktree-list` / `/worktree-finish [名]` | 状況・衝突リスク確認 / マージ + 削除 (Linear 自動 Done) |

- 既定は単一セッション (`/worktree-start` → `cd <worktree>` → 作業 → メインに戻り `/worktree-finish`)。真に並列化する独立タスクのみ `--tab` で別セッション (子は親の会話を継がないため引き継ぎ doc `<共有.git>/worktree-tasks/<ID>-<名>.md` が要)
- レジストリ `<repo>/.git/parallel-tasks.json` を全 worktree から共有参照。多数セッション並行時は `claude agents` (Agent View) をハブに `/worktree-list`・`/status` と併用。ランブック: [`docs/setup/session-management.md`](docs/setup/session-management.md)
- **現状把握は `/status`**: セッション開始時や「今どうなってる?」で、最近の commit・open PR/Issue・project memory・未コミット変更を集約表示する

## Linear イシュー管理

進捗・期日・ステークホルダー可視化は **Linear** に集約。設計・決定は `docs/`、コードレビューは GitHub PR (重複排除)。セットアップ: [`docs/setup/mcp-servers.md`](docs/setup/mcp-servers.md)。

- 役割分担: 期日/進捗/状態/優先度 → Linear / Why → `docs/adr/` / How → `docs/architecture/` / What → `docs/design/` / コード → GitHub PR / AI 文脈 → memory
- **重複禁止**: Issue description は「短い要約 + docs リンク」のみ。**Linear の Docs/Wiki 機能は使わない** (vendor lock-in)
- **Project** = 多段階 / **Issue** = 1 worktree = 1 PR / **サブ Issue** = Phase。相互リンク: branch `worktree/<linear-id>-<task>` / commit `feat: ... (ELM-123)` / docs 冒頭 `- Linear: ELM-123`
- スキル: `/linear-status` (現状表示) / `/linear-issue` (作成・状態変更) / `/linear-plan` (Project + サブ Issue 一括作成)

## Notion 連携 (人間共有用)

人間相手の共有ドキュメント (会議資料・議事録・顧客提出物・オンボーディング) に Notion を併用。設計図は in-repo のまま。根拠: [`docs/adr/0003`](docs/adr/0003-notion-for-human-shared-docs.md) / MCP tool・書き込みのクセ: [`docs/setup/mcp-servers.md`](docs/setup/mcp-servers.md)。

**重複禁止**: 同じ内容を docs/ と Notion の両方に置かない。設計/ADR は docs/ が primary (Notion からは GitHub blob URL でリンク)、議事録は Notion が primary (決定を docs/adr/ に昇格時は「(議事録: Notion URL)」注記)。

## ドキュメント・図式

設計と実装の可視化は **in-repo Markdown + Mermaid** が基盤 (不足なら D2)。Notion / Confluence / Linear Docs / バイナリ画像は設計図に使わない。構造の雛形: `templates/docs/` (メタと本体の分離は [`ADR-0009`](docs/adr/0009-separate-templates-from-docs.md) / AI-first 構成は [`ADR-0011`](docs/adr/0011-ai-first-docs-architecture.md))。

- ディレクトリ: `docs/adr/` (なぜ) / `docs/architecture/` (C4 + 状態/シーケンス図) / `docs/design/` (実装計画・仕様) / `docs/_templates/` (記入用ひな形)
- スキル: `/docs-init` (標準構造展開) / `/docs-visualize` (C4 + 状態機械で可視化) / `/adr-new <題>` (自動採番) / `/docs-publish pdf|docx <md>` (mermaid 保持のまま人間向け配布・[`ADR-0012`](docs/adr/0012-human-facing-docs-publish-model.md))
- **業務フロー図** `/flow-diagram` — Mermaid の業務フローを標準スタイル + 必須情報で作り、`lint-flow-diagram.py` で書式ブレ・記載漏れを機械検証 (通るまで完成にしない)。標準: [`docs/design/flow-diagram-standard.md`](docs/design/flow-diagram-standard.md) / 根拠 [`ADR-0015`](docs/adr/0015-business-flow-diagram-standard.md)
- **安全原則 (ADR 運用)**: ファイル名 `NNNN-kebab-case.md` (欠番なし)、**採択済みは書き換えず新規 ADR で Supersede**、採択日 ISO 形式。**更新順**: ADR (なぜ) → architecture (どう動くか) → コード (drift 注意)

## ドメイン固有スキル (詳細は各 SKILL.md / docs)

各スキルの description は毎セッション自動ロードされるため、ここには**索引 1 行 + 操作時の安全原則**のみ置く (手順は重複させない)。

- **デザイン個性付け** `/design-voice` — median な「AIっぽさ」を意図的バイアスで回避 (`extract`/`use`/`critic`)。根拠 [`ADR-0004`](docs/adr/0004-deliberate-design-bias.md)
- **shadcn/ui** `/shadcn` (フロントエンド) — 案件に shadcn を標準どおり導入 (init/mcp/公式skill監査導入/rule配置/@elm/base 配線)。**自作せず公式を配線** (MCP は per-project・global 登録しない / 公式スキルは監査後 add / house-style は `/design-voice`・design-registry と連結)。詳細: [`docs/setup/shadcn.md`](docs/setup/shadcn.md) / 根拠 [`ADR-0014`](docs/adr/0014-shadcn-design-registry.md)
- **Figma** `/figma` — 画像取込・design tokens 抽出・画像一括書き出し (REST)。対話的コード化は別経路のリモート MCP。**安全原則: Figma API を生 curl で叩かない (レート制御は必ず `/figma` 経由)・PAT/OAuth の 2 経路を混同しない・ローカル MCP は Linux 不可**。導入は [`docs/setup/mcp-servers.md`](docs/setup/mcp-servers.md)
- **New Relic** `/newrelic` — 案件=別顧客テナント (取り違え=顧客データ混線、gh `_chd` 事故と同型)。**安全原則: いまどの顧客アカウントかを常に明示・検証可能にし暗黙の既定に倒さない (fail-closed)・New Relic MCP は global 登録しない・`.newrelic-profile`/`.envrc` は commit しない・鍵は argv に出さない**。接続後は `/newrelic doctor` で三者一致を検証。根拠 [`ADR-0008`](docs/adr/0008-newrelic-connection-hybrid.md) / 導入 [`docs/setup/mcp-servers.md`](docs/setup/mcp-servers.md)
- **3D プリンタ造形** `/cad-print` — build123d で「書く→診断→視認→調整」。嵌合較正は `fit()` で一点管理 (マジックナンバー禁止)。根拠 [`ADR-0007`](docs/adr/0007-build123d-3d-printing-cad-skill.md)
- **シェル環境** `/cli-help` — モダン CLI (rg/fd/bat/eza…) の即引き + soft reminder。導入・全停止 (`MODERN_CLI_HINTS=0`): [`docs/setup/modern-cli-setup.md`](docs/setup/modern-cli-setup.md)
- ハードウェア系 (`/rigol-dho804` / `/webcam-jetson` / `/atopile-view` / `/mosh-clean`) はユーザー明示起動 (常時ロード対象外)

## このリポジトリ (agent-rules) の運用

`agent-rules` は **ルール・テンプレート・スキルの単一ソース**。各マシンの `~/CLAUDE.md`, `~/RULES.md`, `~/AGENTS.md`, `~/.claude/skills/*` は本リポへの symlink で同期する (= main への変更は全セッションに即時配布。事故時は main への revert PR で即時ロールバック)。

```bash
git clone https://github.com/elm-inc/agent-rules ~/repos/github.com/elm-inc/agent-rules
~/repos/github.com/elm-inc/agent-rules/install.sh   # idempotent。既存 symlink はスキップ
```

- 改善は本リポへの PR ベース。採用後は他マシンで `git pull` + `install.sh` で同期
- 大きな方針変更は ADR として残す (このリポ自身も `docs/adr/` を持つ)
