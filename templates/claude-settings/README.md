# claude-settings テンプレート

CLAUDE.md 刈り込み (ADR-0013) で散文ルールから落ちる**操作時の安全原則**を、settings.json の permissions / hook 側で機械 enforcement するためのテンプレート。2 レイヤーある。

## `settings.user.json` — ユーザーレベル (全プロジェクト共通)

`~/.claude/settings.json` に配備する。中身:

- **SessionStart hook**: セッション開始時に `/status` を促す
- **Stop hook**: 終了時にナレッジ昇格候補の台帳追記 (2 回目ルール) と memory 未保存の点検を促す
- **PreToolUse(Bash) hook** → [`scripts/claude-guard.sh`](../../scripts/claude-guard.sh): 生 curl での Figma/New Relic API 直叩き (skill 迂回) を deny、`~/.claude` 配下への symlink 再設定を ask

### 適用モデル (add-only)

**盲目的な自動 merge はしない**。初回はユーザーが手動でマージ (既存 `~/.claude/settings.json` があるため)。以降の drift は `install.sh --check` / `--fix` が **add-only** (新規キーのみ追加・既存キーは上書きしない・衝突は表示して skip) で解消する。純手動だと新しい deny ルールが恒久的に未適用となり安全レベルが劣化するため (redteam 指摘)、上書きしない範囲だけ自動化する。

> ⚠️ 既存の `~/.claude/settings.json` に別の hook がある場合、手で配列に足し込むこと (JSON の hooks は配列 merge が必要)。`install.sh --fix` は最上位キー単位の add-only なので、既に `hooks` キーがある環境では衝突として skip し通知する。

## `settings.project.json` — プロジェクトレベル (雛形)

`/project-init` が対象リポの `<repo>/.claude/settings.json` に配置する空骨格。プロジェクト固有の permissions (よく使う read-only コマンドの allow で確認プロンプトを減らす等) をここに足す。既存があれば上書きしない。

## 検証

`claude-guard.sh` は stdin の PreToolUse JSON を読み、`allow` は無出力 exit 0、`deny`/`ask` は `hookSpecificOutput` JSON を返す。fail-safe (jq 無し等は allow)。単体テストは PR で実施済み。
