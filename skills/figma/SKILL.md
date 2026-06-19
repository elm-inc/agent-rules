---
name: figma
description: Figma REST API をレート制限に配慮して効率的に使う。version 差分キャッシュ・送信スロットル・429 バックオフ・部分取得/バッチで無駄な呼び出しを構造的に減らす。ファイル取得・ノード部分取得・画像一括書き出し・design tokens 抽出・コメント取得に使用。対話的な「リンク→コード化」は別経路のリモート MCP を案内する
argument-hint: "<subcommand> <key|url> [options] | me | file | nodes | images | tokens | comments | cache status"
disable-model-invocation: false
allowed-tools: Bash(uv *) Bash(cat *) Bash(ls *) Bash(test *) Read Write
---

# Figma 効率アクセス (REST + キャッシュ/スロットル)

Figma REST API は **コストベースのレート制限**で、超過時に `429 + Retry-After` を返す。
本スキルは「無駄な API 呼び出しを構造的に減らす」制御を `scripts/figma.py` に一手に集約し、
レート制限に当たりにくく・当たっても自動で耐えるようにする。

## いつ REST (本スキル) / いつ MCP か

Figma 連携には 2 経路あり、**認証も用途も別**。混同しないこと。

| 経路 | 認証 | 向き | Linux |
|---|---|---|---|
| **REST API (本スキル)** | PAT `~/.figma_token` | ヘッドレス/バッチ/CI/cron。画像一括書き出し・トークン抽出・コメント巡回・キー指定の横断処理。キャッシュ/スロットルを完全制御 | ✅ |
| **リモート MCP** | OAuth (PAT 不可) | 対話的に「このリンク/フレーム→コード化」。Figma 自前の最適化 codegen が効く | ✅ |
| ~~ローカル MCP~~ `127.0.0.1:3845` | — | デスクトップアプリ常駐前提 | ❌ Mac/Win のみ |

- **レート制限が問題になるのは REST 側**。だから本スキルが価値を出す。
- 対話的な単発の「デザイン→コード」は **リモート MCP** が勝る (Figma の codegen)。導入:
  `claude plugin install figma@claude-plugins-official` → `/plugin` → Installed タブで `figma` を OAuth 許可。
  エンドポイントは `https://mcp.figma.com/mcp` (transport `http`)。**PAT は使わない**ので本スキルと併存する。

## トークン・設定の解決順

- token: `--token` > `$FIGMA_TOKEN` > `~/.figma_token` (`figd_` で始まる PAT)
- cache dir: `$FIGMA_CACHE_DIR` > `~/.cache/figma`
- 各種設定: コマンドライン引数 > 環境変数 (`FIGMA_MIN_INTERVAL_MS` 等) > `~/.config/figma.toml` > 既定値

`~/.config/figma.toml` 例:

```toml
min_interval_ms = 600   # 全プロセス共有の最小送信間隔 (≈100 req/min)。429 を避ける床
version_ttl_s   = 60    # この秒数内は file version の再チェックも省略
max_retries     = 4
```

## 効率化の機構 (なぜレート制限に強いか)

1. **version 差分キャッシュ** — 重い「フルファイル取得」の前に軽い `?depth=1` で `version` を取得。
   同一 version の結果はディスクから返し、フル取得をスキップ (`~/.cache/figma/`)。
2. **version-check TTL** — 短時間 (既定 60s) 内は version チェック自体も省略 → 連続アクセスは API 0 回。
3. **ローカルスロットル** — `fcntl` ロックで全プロセス共有の最小送信間隔を保証 (worktree 並列でも床を超えない)。
4. **429 バックオフ** — `Retry-After` 準拠 + 指数 + jitter で自動リトライ。
5. **部分取得 / バッチ** — `--ids` / `--depth` で必要枝だけ、`images` は複数 id を 1 リクエストに集約。
6. **要約デフォルト** — `file`/`nodes` は既定で要約表示 (巨大 JSON でモデル文脈を浪費しない)。全 JSON は `--out`。

## 実行方法

`scripts/figma.py` は PEP 723 inline metadata の self-contained な `uv` スクリプト (グローバル pip 不要)。
スキルとして呼ばれた場合は `${SKILL_DIR}` が渡る:

```bash
uv run ${SKILL_DIR}/scripts/figma.py <subcommand> [options]
```

手動では `~/.claude/skills/figma/scripts/figma.py` (install.sh 後の symlink) を指定。
初回実行時に `uv` が `httpx` を ephemeral 環境に取得する。

## サブコマンド

### `me` — 接続確認 (安価)
```bash
uv run ${SKILL_DIR}/scripts/figma.py me
```

### `file <key|url>` — ファイル取得 (version 差分キャッシュ)
既定は要約 (ページ/トップフレーム名 + id)。全 JSON は `--out`。
```bash
uv run ${SKILL_DIR}/scripts/figma.py file 'https://www.figma.com/design/KEY/Name'
uv run ${SKILL_DIR}/scripts/figma.py file KEY --depth 2          # 浅く取って安価に
uv run ${SKILL_DIR}/scripts/figma.py file KEY --out file.json    # 全 JSON 書き出し
```
`--depth` 浅いほど安価 / `--no-cache` キャッシュ無視 / `--force` version 再取得して再フェッチ。

### `nodes <key|url> --ids a,b,c` — 部分取得
フルファイルではなく指定ノードだけ (`/nodes` エンドポイント)。URL に `node-id` があれば省略可。
```bash
uv run ${SKILL_DIR}/scripts/figma.py nodes KEY --ids 12:34,56:78 --depth 1
uv run ${SKILL_DIR}/scripts/figma.py nodes 'https://figma.com/design/KEY/N?node-id=12-34'
```

### `images <key|url> --ids a,b,c` — 画像一括書き出し
複数 id を 1 リクエストでレンダー → ダウンロード。version 別にキャッシュ済みなら render ごとスキップ。
```bash
uv run ${SKILL_DIR}/scripts/figma.py images KEY --ids 1:2,3:4 --format png --scale 2 --out-dir assets
uv run ${SKILL_DIR}/scripts/figma.py images KEY --ids 1:2 --format svg
```

### `tokens <key|url>` — design tokens 抽出
Variables (Enterprise + `file_variables:read` 必要) を試行 → 無ければローカル Styles を抽出。`/design-voice` 連携に。
```bash
uv run ${SKILL_DIR}/scripts/figma.py tokens KEY --out tokens.json
```

### `comments <key|url>` — コメント一覧
```bash
uv run ${SKILL_DIR}/scripts/figma.py comments KEY
```

### `parse-url <url>` — URL から file key / node-id 抽出 (API 不要)
```bash
uv run ${SKILL_DIR}/scripts/figma.py parse-url 'https://figma.com/design/KEY/N?node-id=12-34'
```

### `cache status` / `cache clear` — キャッシュ可視化・削除 (API 不要)
```bash
uv run ${SKILL_DIR}/scripts/figma.py cache status        # 統計 + 節約できたリクエスト数
uv run ${SKILL_DIR}/scripts/figma.py cache clear         # 全削除
uv run ${SKILL_DIR}/scripts/figma.py cache clear --key KEY
```

## 運用上の注意

- `403` が出たら PAT のスコープ不足を疑う (`file_content:read` / `file_comments:read` / `file_variables:read`)。
  PAT は Figma の Settings → Security → Personal access tokens で必要スコープを付けて再発行。
- まず `--depth` を浅く・`nodes` で部分取得し、必要なときだけフル取得する。これが最大の節約。
- バッチ処理の前後で `cache status` を見て、ヒット率と節約数を確認する。
