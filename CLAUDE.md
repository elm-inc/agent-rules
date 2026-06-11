# Claude Code 設定

**重要: 最初に `~/RULES.md` を読み込み、記載されたルールをすべて遵守すること。**

このファイルは「いつ何のスキルを使うか」のルーティング索引。各仕組みの手順・内部詳細は各 `SKILL.md` / `docs/` にあり、リンクで辿る。

## AI 開発ワークフロー (多層・多モデル)

実装は Claude Opus 4.8、レビュー・検証・テスト生成は **複数 LLM の役割分担 + 機械検証** で多層化する。Anthropic/OpenAI 系に偏らせず Gemini・DeepSeek・ローカル LLM を混ぜる (groupthink 回避)。最上位の Claude Fable 5 は高難度タスク限定でサブエージェント委譲する。
設計判断の根拠: [`docs/adr/0001`](docs/adr/0001-multi-llm-development-workflow.md), [`docs/adr/0002`](docs/adr/0002-multi-model-test-generation.md) / 全体像: [`docs/design/ai-workflow.md`](docs/design/ai-workflow.md)

### 役割分担とスキル

| ロール | モデル / ツール | スキル |
|---|---|---|
| 実装 (主) | Claude Opus 4.8 | (Claude Code 本体) |
| 高難度実装・設計 (委譲) | Claude Fable 5 (subagent) | `/fable-task` |
| 最終レビュー (最高精度・限定) | Claude Fable 5 (subagent) | `/fable-review` |
| 0 次レビュー (高速・無料) | ローカル Qwen2.5-Coder-32B | `/local-review` |
| セカンドオピニオン (異種ベンダー) | Codex (GPT-5) | `/codex-review`, `/codex-task`, `/codex-audit` |
| 設計レッドチーム (思考連鎖) | DeepSeek-R1 | `/deepseek-redteam` |
| リポ横断 (1M context) | Gemini 2.5 Pro | `/gemini-review` |
| テスト観点抽出・実装 | DeepSeek-R1 + Qwen | `/test-generate` (`--brainstorm` / `--implement`) |
| テストデータ生成 | Qwen (バッチ) | `/test-data` |
| テスト健全性検証 | mutation testing | `/mutation-check` |
| 機械検証 | pre-commit (ruff/mypy/semgrep) | (各リポで設定) |

### モデル使い分け (Opus 4.8 / Fable 5)

常用 (セッションモデル) は **Opus 4.8**。Fable 5 は $10/$50 per MTok で Opus の 2 倍 (Max 上限を約 2 倍速く消費) だが、**価値が高い局面では積極的に活用する**。判断の物差しは「**手戻り・正しさ・品質が下流に大きく波及するか**」。以下を検知したら **Claude が自分で判断して** Fable 5 サブエージェントに委譲する (委譲前に一言宣言):

**`/fable-task` (設計・実装・調査)**

| カテゴリ | 該当条件 |
|---|---|
| 設計・アーキテクチャ | 判断が拮抗し誤ると手戻りが大きい (ADR 比較検討・技術選定) / 新規プロジェクト・サブシステムの初期設計・足場づくり / 設計ドキュメント (docs/design・ADR) の起草本体 |
| 難度の高い実装 | 10+ ファイル横断 or 構造的に難しいリファクタ・新機能 / 正しさがクリティカル (並行処理・状態機械・課金/金額計算・データ整合性・認証) |
| 調査・最適化 | 原因不明バグの調査 (一度失敗した or 重大なもの) / パフォーマンスのボトルネック分析と最適化 / 大規模・不慣れなコードベースの横断的な理解が要るタスク |
| 品質の引き上げ | Opus で一度試して質・正しさに不満が残ったとき (Fable で作り直す) |

**`/fable-review` (最終レビュー)**

| 該当条件 |
|---|
| セキュリティ・認証・課金・データ破壊リスクに関わる変更 |
| 公開 API・後方互換性・DB スキーマ/マイグレーションに関わる変更 |
| 並行処理・状態管理・トランザクション境界を含む差分 |
| 大規模変更のマージ前最終確認、レビュー意見が割れた差分 |
| 外部に出る成果物 (顧客提出物・本番デプロイ前) |

**迷ったら**: 影響範囲が広い / 正しさが重要 / 品質が下流に波及するタスクは Fable に回してよい。逆に**局所的・機械的・低リスク**なタスク (定型修正、リネーム、軽微なバグ、調査の一次あたり) は Opus のまま。委譲はサブエージェント単位で行い (セッション全体を Fable にしない)、完全な仕様を最初に一括で渡す。セッション全体を切り替えたい場合のみユーザーが `/model fable` を実行する。

### 標準オーケストレーション (大規模開発)

複数モデルを組み合わせて大規模タスクを進める時の基本形。**司令塔は必ずメインセッションの Claude** (通常 Opus 4.8)。Codex / DeepSeek / Gemini / Qwen はスキル経由で呼ぶ「ツール」であり、司令塔にはならない。

| モデル | 役割 |
|---|---|
| **Opus 4.8 = 司令塔** | 計画・分解・分配・統合・実装の主。トークン最多のセッションを 1x コストに保つ |
| **Fable 5 = 両端の専門脳** | 全体設計/分解の起草 (要所) と高リスク変更の最終レビュー (`/fable-task`・`/fable-review` subagent) |
| **Codex = 異種ベンダーの横やり + 独立系統の並列実装** | 盲点ヘッジ + 別系統を丸ごと委譲して真の並列化 (`/codex-task`・`/codex-review`) |
| **DeepSeek-R1 / Gemini = レッドチーム / リポ横断整合** | 設計の破綻炙り (`/deepseek-redteam`) と 1M context での全体整合 (`/gemini-review`) |
| **Qwen + pre-commit = 床** | 0 次レビュー (`/local-review`) と機械検証の最前段フィルタ |

```
[設計] Fable 起草 → /deepseek-redteam で redteam → (必要なら) /gemini-review で横断整合
[実装] Opus 司令塔、worktree で並列分解:
        難所→Fable subagent (/fable-task) / 独立系統→Codex 委譲 (/codex-task) / 大半→Opus 自身
[レビュー] /local-review (0次) → pre-commit (機械) → /codex-review (異種)
          → (10+ファイル/drift 疑い) /gemini-review → (高リスクのみ) /fable-review (最終)
```

**例外**: 単発・完全自律の超高難度ミッション (一晩でサブシステム移行など) は、Fable を司令塔にして `/model fable` で走らせる方が良い (完全な仕様を一括投入し long-horizon 自律を活かす。コストは割り切る)。対話的・多段の大規模開発は上記の Opus 司令塔型が勝る。

### コミット時のフロー (推奨)

```
[設計] docs/design/foo.md 起草 → /deepseek-redteam で盲点炙り出し → (任意) /codex-audit
[実装] Opus 4.8 (高難度は /fable-task で Fable 5 委譲)
[コミット前] /local-review → pre-commit → (必要時) /test-generate → /codex-review
             → (10+ファイル/ADR drift 疑い時) /gemini-review → (高リスク変更のみ) /fable-review
[実行検証] /verify, E2E
```

軽微な変更では `/local-review` + pre-commit のみで十分。

### セットアップ・トラブル対処

- ローカル LLM (vLLM) 起動: [`docs/setup/local-llm.md`](docs/setup/local-llm.md)。API キーは `scripts/env-snippet.sh` (`~/.*_token` 方式)
- よくある不具合 (vLLM OOM / Gemini 応答空 / HF DL ストール / Distill 評価) の対処は [`docs/design/ai-workflow.md`](docs/design/ai-workflow.md) と各 `SKILL.md` に集約

## 並列開発 (git worktree)

タスクごとに worktree を分離し、安全に並列開発する。

| スキル | 用途 |
|--------|------|
| `/worktree-start <名> <説明>` | worktree 作成 + タスク登録 (`--linear <ID>` で Issue 連携) |
| `/worktree-list` | 全タスクの状況・衝突リスク確認 |
| `/worktree-finish [名]` | マージ + worktree 削除 (Linear 自動 Done) |

- **デフォルトは単一セッション**: `/worktree-start` → 同一セッション内で `cd <worktree>` して作業 → メインに戻り `/worktree-finish`。メインワークツリーでは直接コード変更しない原則を維持
- 真に並列化する独立タスクのみ別セッション: `cd <worktree> && claude --remote-control "<名>"` (Remote Control 不要なら `--no-remote`)
- タスクレジストリは `<repo>/.git/parallel-tasks.json` に記録、全 worktree から共有参照

## Linear イシュー管理

進捗・期日・ステークホルダー可視化は **Linear** に集約。設計・決定は `docs/`、コードレビューは GitHub PR。重複を排除する。
セットアップ (MCP 登録): [`docs/setup/mcp-servers.md`](docs/setup/mcp-servers.md)

### 役割分担 (何をどこに置くか)

| 関心事 | 担当 |
|---|---|
| 期日・進捗・状態・優先度・ロードマップ | **Linear** |
| Why (なぜ決めたか) | `docs/adr/` |
| How (動作・状態機械) | `docs/architecture/` |
| What (詳細仕様・実装計画) | `docs/design/` |
| コード・差分・レビュー | GitHub PR |
| AI セッション文脈 | memory |

**重複禁止**: Linear Issue description は「短い要約 + docs/design/foo.md へのリンク」のみ。本文は docs に。**Linear の Docs/Wiki 機能は使わない** (AI 摩擦・vendor lock-in)。

### スキルと構造

| スキル | 用途 |
|--------|------|
| `/linear-status` | Project / Issue / cycle の現状表示 |
| `/linear-issue` | Issue の作成・表示・状態変更 |
| `/linear-plan` | Project + サブ Issue を一括作成 (大規模計画用) |

- **Project** = 多段階タスク / **Issue** = 1 worktree = 1 PR / **サブ Issue** = Phase
- 相互リンク: branch `worktree/<linear-id>-<task>` (PR 自動紐付け) / commit `feat: ... (ELM-123)` / docs 冒頭 `- Linear: ELM-123`
- 運用フロー: `docs/design/foo.md` → `/linear-plan` → `/worktree-start <名> --linear <ID>` (In Progress) → 実装 → PR → `/worktree-finish` (Done)

## Notion 連携 (人間共有用)

人間相手の共有ドキュメント (会議資料・議事録・顧客提出物・ステータス共有・オンボーディング) に Notion を併用する。設計図は in-repo (ADR-0001) のまま。
根拠: [`docs/adr/0003`](docs/adr/0003-notion-for-human-shared-docs.md) / セットアップ・MCP tool・書き込み時のクセ: [`docs/setup/mcp-servers.md`](docs/setup/mcp-servers.md)

**重複禁止**: 同じ内容を docs/ と Notion の両方に置かない。設計/ADR は docs/ が primary (Notion からは GitHub blob URL でリンク)、議事録は Notion が primary (決定事項を docs/adr/ に昇格時は「(議事録: Notion URL)」と注記)。

## ドキュメント・図式

設計と実装の可視化は **in-repo Markdown + Mermaid** が基盤 (Mermaid で不足なら D2)。Notion / Confluence / Linear Docs / バイナリ画像は設計図に使わない。
根拠: [`docs/adr/0004`](docs/adr/0004-deliberate-design-bias.md) / 構造の雛形: `agent-rules/templates/docs/`

| ディレクトリ | 内容 |
|--------|------|
| `docs/adr/` | Architecture Decision Records (なぜ・何を決めたか) |
| `docs/architecture/` | C4 model (L1 Context → L4 Code) + 状態/シーケンス/依存図 |
| `docs/design/` | 実装計画・仕様 |

| スキル | 用途 |
|--------|------|
| `/docs-init` | 新プロジェクトに docs/ 標準構造を展開 |
| `/docs-visualize` | C4 + 状態機械 + シーケンスで可視化 |
| `/adr-new <題>` | 通し番号自動採番で ADR 作成 |

- **ADR 運用**: ファイル名 `NNNN-kebab-case.md` (欠番なし)、採択済みは書き換えず新規 ADR で Supersede、採択日は ISO 形式
- **更新順**: ADR (なぜ) → architecture (どう動くか) → コード (実装)。図が drift しないよう注意
- 人間がコピペするプロンプト雛形は [`prompts/docs-visualize.md`](prompts/docs-visualize.md)

## デザイン個性付け (AIっぽさ回避)

生成 AI の UI/スライドが median (青紫グラデ・glassmorphism・Inter 既定…) に収束する問題を、意図的に偏らせたデザイン DNA の注入で解く。
根拠: [`docs/adr/0004`](docs/adr/0004-deliberate-design-bias.md) / 内部: `skills/design-voice/` (`anti-tells.md`, `scripts/ai_smell_lint.py`)

| スキル | 用途 |
|--------|------|
| `/design-voice extract` | 参照例から個性を抽出しプロファイル生成 |
| `/design-voice use` | プロファイルを context 注入 (ソフト適用) |
| `/design-voice critic` | 「AI臭スコア」採点 + 閾値未満まで再生成 (ハード、a11y ガードレール必須) |

軽微な用途は `use` のソフト適用のみ。仕上げ・量産時に `critic` を回す。

## シェル環境 (モダン CLI ツール)

Rust 製モダン CLI (`rg`, `fd`, `bat`, `eza`, `dust`, `btm`, `procs`, `delta`, `sd`, `hyperfine`, `tldr`, `jless`, `tokei`, `zoxide`) を使いこなすための仕組み。

- `/cli-help <tool>` で使い方を即引き (旧コマンド名でも逆引き可)。シェルでは `cheat <tool>` 関数 + soft reminder (`grep`/`find`/`cat` 等を関数ラップ、`command grep` でバイパス)
- 仕組みの有効化は `install.sh` が `~/.bashrc` に追記。全停止は `export MODERN_CLI_HINTS=0`
- 推奨ツールの一括導入: `bash scripts/install-modern-cli.sh` (cargo 経由、`install.sh` 本体には含めない)

## このリポジトリ (agent-rules) の運用

`agent-rules` は **ルール・テンプレート・スキルの単一ソース**。各マシンの `~/CLAUDE.md`, `~/RULES.md`, `~/AGENTS.md`, `~/.claude/skills/*` は本リポへの symlink で同期する。

```bash
git clone https://github.com/elm-inc/agent-rules ~/repos/github.com/elm-inc/agent-rules
~/repos/github.com/elm-inc/agent-rules/install.sh   # idempotent。既存 symlink はスキップ
```

- 改善は本リポへの PR ベース。採用後は他マシンで `git pull` + `install.sh` で同期
- 大きな方針変更は ADR として残す (このリポ自身も `docs/adr/` を持つ)
