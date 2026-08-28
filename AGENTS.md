# Codex CLI 設定

**重要: 最初に `~/RULES.md` を読み込み、記載されたルールをすべて遵守すること。**

このファイルは Codex CLI 用の上位ルールである。ツール横断の原則は `~/RULES.md` を正とし、Codex 固有の運用は [`docs/setup/codex-cli.md`](docs/setup/codex-cli.md) を参照する。

## 起動・設定
- 通常利用では `codex --profile agent-rules` を使い、共有 config layer (`~/.codex/agent-rules.config.toml`) を読み込む
- ラッパーを使える環境では `scripts/codex-agent-rules` 経由で起動してよい
- `~/.codex/config.toml`, `~/.codex/auth.json`, project trust, model default は個人・マシン依存として扱い、Git 管理しない
- 共有 MCP は `.codex/*.config.toml` または `.codex/mcp/*.toml` に定義し、シークレット値は書かず `env_vars` / `bearer_token_env_var` の環境変数名だけを共有する

## 作業ルール
- メインワークツリーでは直接コード変更しない。作業前に専用 worktree / branch を作成する
- 既存の未コミット変更はユーザまたは他セッションの作業として扱い、明示許可なく revert しない
- 依存追加、グローバル設定、CI/CD、Docker、ビルド設定の変更は事前確認する
- ファイル探索は `rg` / `rg --files` を優先する
- 変更後は関連テストまたは検証コマンドを実行し、実行不能なら理由を報告する

## スキル・MCP
- Codex skill は `~/.codex/skills/<name>/SKILL.md` を読む前提で、`install.sh` により本リポの `skills/` へ symlink される
- 新規・更新した skill は `scripts/validate-codex-skills.sh` で最低限の互換性を確認する
- MCP の導入・変更時は `scripts/codex-doctor.sh` で symlink、profile、環境変数不足を確認する

## レビュー観点
`codex review --uncommitted` では特に以下を確認する:
- 重大なバグ、セキュリティ、シークレット露出
- 破壊的コマンドや危険な権限変更
- worktree 運用違反、main/master/develop への直接変更
- config drift (`~/.codex/config.toml` への混入、共有 profile と個人設定の混在)
- MCP の秘密値直書き、環境変数名の不足
- テスト・検証不足

## コミット時のフロー
1. コード変更・テスト完了
2. `codex review --uncommitted` でレビューを実施
3. レビュー結果を確認し、重大な指摘があれば修正
4. 問題なければコミットを実行
