# Claude Code 設定

**重要: 最初に `~/RULES.md` を読み込み、記載されたルールをすべて遵守すること。**

## Codex CLI 連携
Codex CLI（OpenAI）をセカンドオピニオンやタスク委譲に活用する。

### スキル一覧
| スキル | 用途 | コマンド例 |
|--------|------|-----------|
| `/codex-review` | コードレビュー依頼 | `/codex-review`, `/codex-review --base main` |
| `/codex-task` | 修正・実装タスク依頼 | `/codex-task エラーハンドリングを追加` |

### コミット時のフロー
1. コード変更・テスト完了
2. **`/codex-review`** で Codex にレビューを依頼（uncommitted な変更が対象）
3. レビュー結果を確認し、重大な指摘があれば修正
4. 問題なければコミットを実行
