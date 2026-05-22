# Claude Code 設定

**重要: 最初に `~/RULES.md` を読み込み、記載されたルールをすべて遵守すること。**

## AI 開発ワークフロー (多層・多モデル)

実装は Claude Opus 4.7、レビュー・検証・テスト生成は **複数 LLM の役割分担 + 機械検証** で多層化する。同じ間違いをしないよう、Anthropic/OpenAI 系に偏らせず Gemini・DeepSeek・ローカル LLM を混ぜる。

### 役割分担

| ロール | モデル / ツール | スキル |
|---|---|---|
| 実装 (主) | Claude Opus 4.7 | (Claude Code 本体) |
| 0 次レビュー (高速・無料) | ローカル Qwen2.5-Coder-32B (vLLM, FP8) | `/local-review` |
| セカンドオピニオン (異種ベンダー) | Codex (GPT-5) | `/codex-review`, `/codex-task`, `/codex-audit` |
| 設計レッドチーム (思考連鎖) | DeepSeek-R1 (API) | `/deepseek-redteam` |
| リポ横断 (1M context) | Gemini 2.5 Pro (API) | `/gemini-review` |
| テスト生成 | Qwen (主) + DeepSeek-R1 (property 発想) | `/test-generate` |
| テストデータ生成 | Qwen (バッチ推論) | `/test-data` |
| 機械検証 | pre-commit hooks (ruff/mypy/semgrep/type-check) | (各リポで設定) |

### スキル一覧

| スキル | 用途 | コマンド例 |
|--------|------|-----------|
| `/local-review` | 差分の 0 次レビュー (秒オーダー) | `/local-review`, `/local-review --base main` |
| `/codex-review` | Codex によるセカンドオピニオン | `/codex-review`, `/codex-review --base main` |
| `/codex-audit` | Codex による全体監査 | `/codex-audit`, `/codex-audit セキュリティ` |
| `/codex-task` | Codex に修正・実装を委譲 | `/codex-task エラーハンドリングを追加` |
| `/deepseek-redteam` | 設計・差分の盲点炙り出し | `/deepseek-redteam --design docs/design/foo.md` |
| `/gemini-review` | リポ横断・ADR 整合性レビュー (1M context) | `/gemini-review --scope apps/web` |
| `/test-generate` | テストケース列挙 + 実装生成 | `/test-generate src/utils/date.ts:format` |
| `/test-data` | 業務的に妥当なテストデータ生成 | `/test-data app/models/user.py:User --count 50` |

### コミット時のフロー (推奨)

```
[設計]
  Claude が docs/design/foo.md 起草
   └→ /deepseek-redteam で盲点炙り出し
   └→ (任意) /codex-audit で実装視点ツッコミ

[実装]
  Opus 4.7 で実装

[コミット前]
  /local-review                      ← 0 次 (秒)
  pre-commit hooks (型/lint/semgrep) ← 機械
  (必要時) /test-generate            ← テスト追加
  /codex-review                      ← セカンドオピニオン
  (必要時) /gemini-review            ← リポ横断

[実行検証]
  /verify (Claude Code 標準スキル), E2E
```

軽微な変更では `/local-review` + pre-commit のみで十分。`/gemini-review` は 10+ ファイル変更や ADR drift 疑い時のみ。

### セットアップ

新規マシンでローカル LLM 系スキルを使う前に [`docs/setup/local-llm.md`](docs/setup/local-llm.md) の手順で vLLM サーバを起動する。クラウド系は `GEMINI_API_KEY` / `DEEPSEEK_API_KEY` を `~/.bashrc` に追加。

## 並列開発 (git worktree)
タスクごとに git worktree を分離し、複数の Claude Code セッションで安全に並列開発する。

### スキル一覧
| スキル | 用途 | コマンド例 |
|--------|------|-----------|
| `/worktree-start` | worktree 作成 + タスク登録 (`--linear <ID>` で Issue 連携) | `/worktree-start feat-auth ユーザー認証 --linear ELM-123` |
| `/worktree-list` | 全タスクの状況・衝突リスク確認 | `/worktree-list` |
| `/worktree-finish` | マージ + worktree 削除 (Linear 自動 Done) | `/worktree-finish feat-auth` |

### 並列開発フロー（デフォルト: 単一セッション）
1. `/worktree-start <タスク名> <説明>` で worktree 作成
2. 同一セッション内で `cd <worktree path>` して作業（メインワークツリーでは直接コード変更しない原則は維持）
3. 作業完了後、メインワークツリーに戻って `/worktree-finish` でマージ

### 並列セッションを使う場合（独立タスクを同時進行する時のみ）
- 真に並列化したい時だけ別セッションを起動: `cd <worktree path> && claude`
- 依存関係のあるタスクや逐次進めるタスクは単一セッションで切り替えながら進める

### タスクレジストリ
- `<repo>/.git/parallel-tasks.json` に全タスク情報を記録
- 全 worktree から共有参照できるため、どのセッションからでも `/worktree-list` で全体を俯瞰可能
- 変更ファイルの重複がある場合は衝突リスクとして警告される

## Linear イシュー管理

進捗・期日・ステークホルダー可視化は **Linear** に集約する。AI が読みやすい設計・決定ドキュメントは `docs/` に残し、コードレビューは GitHub PR を使う。各ツールの得意領域だけで運用し、重複を排除する。

### 役割分担

| 関心事 | 担当 |
|---|---|
| 期日・進捗・状態 (Todo/In Progress/Done, cycle) | **Linear** |
| ステークホルダー可視化・優先度・ロードマップ | **Linear** |
| Why (なぜそう決めたか) | `docs/adr/` |
| How (動作・状態機械) | `docs/architecture/` |
| What (詳細仕様・実装計画) | `docs/design/` |
| コード・差分・レビュー | GitHub PR |
| AI セッション文脈 | memory |
| worktree のローカル状態 | `parallel-tasks.json` |

**重複禁止**: Linear Issue description には「短い要約 + docs/design/foo.md へのリンク」だけ書く。本文は docs に。

### Linear 内の構造

- **Project** = 多段階タスク (Phase 1-N のリファクタなど)。期日と進捗率を持つ
- **Issue** = 1 worktree = 1 PR の粒度
- **サブ Issue** = Project 内の Phase。parent-child で表現

### 相互リンク

- Branch 名: `worktree/<linear-id-lowercase>-<task-name>` → Linear が PR を自動紐付け
- Commit message: `feat: ... (ELM-123)`
- docs/design/*.md 冒頭: `- Linear: ELM-123`
- Linear Issue description: `docs/design/foo.md` への GitHub blob URL

### スキル一覧

| スキル | 用途 | コマンド例 |
|--------|------|-----------|
| `/linear-status` | Project / Issue / cycle の現状表示 | `/linear-status`, `/linear-status --mine` |
| `/linear-issue` | Issue の作成・表示・状態変更 | `/linear-issue create "Phase 6 着手"`, `/linear-issue done ELM-106` |
| `/linear-plan` | Project + サブ Issue を一括作成 (大規模計画用) | `/linear-plan "apps/batch test refactor" --design test-refactor-plan.md` |

worktree との統合は `/worktree-start <name> --linear <ID>` で行う (Issue を In Progress に遷移、`/worktree-finish` で Done に遷移)。

### 初回セットアップ

各マシンで 1 回だけ実行:

```bash
claude mcp add --transport sse --scope user linear https://mcp.linear.app/sse
# Claude Code セッション内で /mcp linear → OAuth 認証
```

### 運用フロー

1. 新計画 → `docs/design/foo.md` を書く → `/linear-plan` で Project + サブ Issue 作成
2. Phase 着手 → `/worktree-start <name> --linear <ID>` で worktree 作成 + Issue を In Progress
3. 実装 → コミット message に Issue ID 埋め込み (`feat: ... (ELM-123)`)
4. PR → branch 名から Linear が自動で PR を紐付け
5. マージ → `/worktree-finish` が Issue を Done に遷移

### Linear Docs は使わない

ドキュメント本体は `docs/` (Markdown) に置く。Linear の **Docs/Wiki 機能** は AI 摩擦・vendor lock-in のため採用しない (Issue 管理のみ Linear を使う)。

## ドキュメント・図式

設計と実装の可視化は **in-repo Markdown + Mermaid** を基盤とする。Notion / Confluence / Linear Docs などの SaaS には設計図を置かない（vendor lock-in、AI 摩擦、コード/ドキュメント分断のため）。

### 構造規約

各リポジトリの `docs/` 配下に以下の構造で配置する。雛形は `agent-rules/templates/docs/`。

| ディレクトリ | 内容 |
|--------|------|
| `docs/adr/` | Architecture Decision Records（なぜ・何を決めたか） |
| `docs/architecture/` | C4 model + 状態/シーケンス/依存図（どう動くか） |
| `docs/design/` | 実装計画・仕様（これから何をどう作るか） |

### スキル一覧

| スキル | 用途 | コマンド例 |
|--------|------|-----------|
| `/docs-init` | 新プロジェクトに docs/ 標準構造を展開 | `/docs-init` |
| `/docs-visualize` | C4 + 状態機械 + シーケンスで可視化 | `/docs-visualize`, `/docs-visualize --scope auth` |
| `/adr-new` | 通し番号自動採番で ADR を作成 | `/adr-new プラットフォーム選定` |

### 関連プロンプト

人間が手元でコピペするためのプロンプト雛形は `agent-rules/prompts/` に置く:

- [`prompts/docs-visualize.md`](prompts/docs-visualize.md) — 新プロジェクトで可視化を依頼するときのコピペ用文面 (最短版・フル版・自然言語トリガー・トラブルシュート付き)

### ADR 運用ルール

- ファイル名: `NNNN-kebab-case-title.md`（4 桁ゼロ埋め、欠番なし）
- 採択した ADR は **書き換えない**。変更は新規 ADR で旧 ADR を Supersede する
- 採択日は ISO 形式（`YYYY-MM-DD`）
- 関連 ADR は相互リンクで参照

### 図式の方針

- **Mermaid を第一選択**（GitHub がネイティブレンダリング、Claude が完全に書ける）
- Mermaid で表現力が足りない場合に **D2** を補完的に利用
- 採用しない: Notion / Confluence / Linear Docs / 設計図のバイナリ画像

### C4 model レベルの使い分け

| レベル | 推奨ファイル | 用途 |
|--------|--------------|------|
| L1 Context | `0-context.md` | システム境界、外部との関係 |
| L2 Container | `1-containers.md` | アプリ内の主要要素 |
| L3 Component | `2-components.md` | Container 内の結線 |
| L4 Code | （必要時のみ） | クラス図など |

補足図（状態機械、シーケンス、データフロー、依存）は L2/L3 と並べて配置する。

### 更新順

設計変更時は **ADR（なぜ）→ architecture（どう動くか）→ コード（実装）** の順で更新する。図がコードから drift しないよう注意する。

## このリポジトリ (agent-rules) の運用

`agent-rules` リポは **ルール・テンプレート・スキルの単一ソース**。各マシンの `~/CLAUDE.md`, `~/RULES.md`, `~/AGENTS.md`, `~/.claude/skills/*` は本リポへの symlink で同期する。

### 新マシン or 再セットアップ

```bash
git clone https://github.com/elm-inc/agent-rules ~/repos/github.com/elm-inc/agent-rules
~/repos/github.com/elm-inc/agent-rules/install.sh
```

`install.sh` は idempotent。既存 symlink はスキップ、不足分だけ追加する。

### 改善の反映

- 仕様や運用の改善は agent-rules リポへの PR ベースで行う
- 採用された改善は他マシンで `git pull` + `install.sh` で同期される
- 大きな方針変更は ADR として残す（このリポ自身も `docs/adr/` を持つ）
