# MCP サーバ セットアップ (Linear / Notion / Figma / New Relic)

各マシンで 1 回だけ実行する MCP サーバ登録手順 (New Relic のみ per-project)。運用ルール (役割分担・重複禁止) は `CLAUDE.md` の各セクションを参照。

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

## Figma (REST スキル + リモート MCP の併用)

Figma へのアクセスは**認証も用途も別の 2 経路**を使い分ける (混同しない):

| 経路 | 認証 | 向き |
|---|---|---|
| `/figma` スキル (REST API) | PAT `~/.figma_token` | ヘッドレス/バッチ: 画像一括書き出し・design tokens 抽出・コメント巡回・キー横断。**レート制限は skill が version 差分キャッシュ + スロットル + 429 バックオフで制御** |
| リモート MCP `https://mcp.figma.com/mcp` | OAuth (**PAT 不可**) | 対話的に「このリンク/フレーム→コード化」。Figma 自前の codegen が勝る |

リモート MCP の導入:

```bash
claude plugin install figma@claude-plugins-official
# Claude Code セッション内で /plugin → OAuth 許可
```

- **ローカル MCP (`127.0.0.1:3845`) はデスクトップアプリ常駐前提で Linux 不可**。Linux 環境では上記 2 経路のみ (plugin のローカル接続を試みない)
- レート制限を気にする処理 (一括/横断/CI) は必ず `/figma` 経由 (**Figma API を生 curl で叩かない**)。`/figma cache status` でキャッシュにより節約できたリクエスト数を確認できる
- 抽出した design tokens は `/design-voice` のプロファイル素材にできる

## New Relic (per-project MCP)

案件=別顧客テナントのため、**New Relic MCP は global 登録しない** (付け忘れ=接続不能で fail-closed に倒す)。運用原則・2 経路の詳細は [`docs/adr/0008`](../adr/0008-newrelic-connection-hybrid.md) と `skills/newrelic/SKILL.md` を参照。

| 経路 | 認証 | 向き |
|---|---|---|
| `/newrelic` スキル (NerdGraph 直) | profile `~/.newrelic/<名>.env` (600) | ヘッドレス/バッチ/CI/**複数顧客横断**。`--profile` 明示でテナント取り違えを防ぐ |
| per-project 公式リモート MCP | User Key (`NRAK-*`) / OAuth | **単一テナント repo** の対話探索 (NRQL/ダッシュボード/アラート) |

per-project MCP の導入 (**`.mcp.json` の手書き禁止**):

```bash
/newrelic init <repo-dir> --profile <名>   # .newrelic-profile + .mcp.json + .gitignore を生成
# 接続後・不安時: /newrelic doctor で「MCP と skill が同一顧客を指す」三者一致を検証してから対話する
```

- `.newrelic-profile`・`.envrc` は **commit しない** (生成される .gitignore が除外。顧客名漏洩防止)。鍵は argv に出さず profile ファイルから読む
- リージョンは US 既定・EU 切替
