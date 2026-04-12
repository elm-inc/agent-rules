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

### 並列開発フロー
1. メインセッションで `/worktree-start <タスク名> <説明>` を実行
2. 案内されたパスで `cd <path> && claude` で新セッション起動
3. 各セッションで独立して開発（`/worktree-list` で他タスクの状況を随時確認）
4. タスク完了後 `/worktree-finish` でベースブランチにマージ

### タスクレジストリ
- `<repo>/.git/parallel-tasks.json` に全タスク情報を記録
- 全 worktree から共有参照できるため、どのセッションからでも `/worktree-list` で全体を俯瞰可能
- 変更ファイルの重複がある場合は衝突リスクとして警告される
