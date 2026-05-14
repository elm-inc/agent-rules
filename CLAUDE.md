# Claude Code 設定

**重要: 最初に `~/RULES.md` を読み込み、記載されたルールをすべて遵守すること。**

## Codex CLI 連携
Codex CLI（OpenAI）をセカンドオピニオンやタスク委譲に活用する。

### スキル一覧
| スキル | 用途 | コマンド例 |
|--------|------|-----------|
| `/codex-review` | 差分のコードレビュー依頼 | `/codex-review`, `/codex-review --base main` |
| `/codex-audit` | プロジェクト全体の網羅的レビュー | `/codex-audit`, `/codex-audit セキュリティ` |
| `/codex-task` | 修正・実装タスク依頼 | `/codex-task エラーハンドリングを追加` |

### コミット時のフロー
1. コード変更・テスト完了
2. **`/codex-review`** で Codex にレビューを依頼（uncommitted な変更が対象）
3. レビュー結果を確認し、重大な指摘があれば修正
4. 問題なければコミットを実行

## 並列開発 (git worktree)
タスクごとに git worktree を分離し、複数の Claude Code セッションで安全に並列開発する。

### スキル一覧
| スキル | 用途 | コマンド例 |
|--------|------|-----------|
| `/worktree-start` | worktree 作成 + タスク登録 | `/worktree-start feat-auth ユーザー認証の追加` |
| `/worktree-list` | 全タスクの状況・衝突リスク確認 | `/worktree-list` |
| `/worktree-finish` | マージ + worktree 削除 | `/worktree-finish feat-auth` |

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
