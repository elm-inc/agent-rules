# MCP サーバ セットアップ (Linear / Notion)

各マシンで 1 回だけ実行する MCP サーバ登録手順。運用ルール (役割分担・重複禁止) は `CLAUDE.md` の各セクションを参照。

## Linear MCP

進捗・期日・ステークホルダー可視化を担う。

```bash
claude mcp add --transport http --scope user linear https://mcp.linear.app/mcp
# Claude Code セッション内で /mcp linear → OAuth 認証
```

> **注記**: 旧 `--transport sse https://mcp.linear.app/sse` は 2026-04-08 で deprecated。既に SSE で登録済みの場合は `claude mcp remove linear -s user` してから上記コマンドで再登録する。
> 移行ガイド: https://linear.app/docs/mcp

## Notion MCP

会議資料・顧客提出物・ステータス共有など人間相手の共有ドキュメント用。Notion MCP server (公式、HTTP + OAuth) を Claude Code から叩く。

```bash
claude mcp add --transport http --scope user notion https://mcp.notion.com/mcp
# Claude Code セッション内で /mcp notion → OAuth 認証 (ブラウザが開く)
```

### 主要 MCP tool

| Tool | 用途 |
|---|---|
| `notion-fetch` | 既存ページ取得 (URL or ID 直指定、Notion AI 不要) |
| `notion-create-pages` | 新規ページ作成 (parent ページ or database を指定) |
| `notion-update-page` | プロパティ・本文の更新 |
| `notion-create-comment` | ページにコメント追加 |
| `notion-search` | キーワード検索 (**Notion AI 課金必須**、当面使わない) |

### AI から Notion へ書く時のクセ

- Markdown と完全互換ではない (block 構造)。**平文 + paragraph / heading / bullet list** のみで書く
- 複雑なレイアウト (カラム、トグル、callout) は人間が手動編集
- **重要な決定は必ず docs/adr/ に残してから** Notion にコピー (逆順禁止)
- 機密案件のコード断片 / 内部 token を Notion に貼らない

### 注意事項

- Notion MCP の権限は OAuth ユーザの権限を継承 (個別ページ制限なし)。共有範囲は Notion 側のページ共有設定で管理
- `notion-search` (= Notion AI) は当面使わず、`notion-fetch` で URL 直指定する
- rate limit: 180 req/min (search は 30 req/min)
- 月次評価 (`docs/design/ai-workflow.md` §8 と同期) で「Notion 重複ドリフト」を点検

詳細な設計判断は [`docs/adr/0003-notion-for-human-shared-docs.md`](../adr/0003-notion-for-human-shared-docs.md) を参照。
