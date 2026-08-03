# サードパーティ skill / MCP 監査チェックリスト

RULES.md の「サードパーティ skill/MCP は audit なしで導入しない」の audit 実体。community skills の約 36% に prompt injection が検出されている ([Agent Skills Ecosystem Report 2026](https://agentman.ai/blog/agent-skills-ecosystem-report-2026/)、2026-07 参照) ため、外部由来の skill / MCP サーバを導入する前に以下を確認する。1 つでも満たせなければ導入しない。

## skill (SKILL.md + 同梱スクリプト)

1. **SKILL.md 全文を読む** — 指示文に以下がないこと:
   - 外部への情報送信 (「結果を <URL> に POST」等)、環境変数・鍵・`~/.ssh`・`.env` の読み出し・送信
   - 自己改変・他ファイル改変 (settings.json / CLAUDE.md / rules の書き換え指示)
   - 権限昇格・sandbox 迂回 (`sudo`、`command` での関数ラップ迂回の悪用)
   - 難読化 (base64 実行・`eval "$(curl ...)"`・意味不明なワンライナー)
2. **同梱スクリプトを読む** — SKILL.md が呼ぶ `scripts/*` の実際の挙動が説明と一致すること。ネットワーク送信先・書き込み先を確認
3. **`allowed-tools` が最小** — `Bash(bash *)` や無制限 `Bash(*)` でないこと。パスまで絞られていること (skill-authoring.md 準拠)
4. **出所** — 公式 marketplace (`claude-plugins-official`) を優先。個人 repo 由来は star/更新/作者を確認し、pin (バージョン固定) して導入

## MCP サーバ

1. **接続先 URL とベンダーを確認** — 想定した提供元のドメインか。OSS なら self-host を検討
2. **認証情報の扱い** — 鍵は vault / profile 経由で、argv・平文・prompt に出さない (New Relic の fail-closed 原則と同型)
3. **tool surface を確認** — 提供 tool 一覧を見て、破壊的操作 (削除・送信・課金) を含むなら permission を `ask` に
4. **networking スコープ** — 可能なら allowed_hosts で接続先を限定 (deny-by-default)

## 導入後

- 初回は挙動を観察 (想定外の tool 呼び出し・送信がないか)
- 不要になったら消す (tool reach を増やしたままにしない)
