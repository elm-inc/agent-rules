# 設計: `/newrelic` — New Relic 接続 (per-project MCP + skill ハイブリッド)

- ステータス: 実装済み (PR #11)。決定の根拠は [ADR-0008](../adr/0008-newrelic-connection-hybrid.md) (採択 + /deepseek-redteam 追記 §A–G)。実機検証 TODO は §11 + GitHub Issue
- 関連: Figma 接続 (REST skill + リモート MCP) の前例。実装は `skills/figma/scripts/figma.py` のスロットル/バックオフ/設定解決を踏襲

## 1. 目的 / 非目的

**目的**: Claude Code から New Relic を、**案件 (=別顧客テナント) を取り違えずに**扱う。対話探索は公式リモート MCP、バッチ/CI/横断は自前 `/newrelic` skill に分担し、どちらも「いまどの顧客アカウントを見ているか」を**明示・検証可能**にする。

**非目的 (現スコープ外)**: データ ingest (License Key 経由の APM/インフラ計装)、ダッシュボード/アラートの本格 CRUD ウィザード (閲覧と最小操作に限定)、鍵の中央管理 (Vault/Secrets Manager は将来。ADR §G)、FedRAMP/HIPAA アカウントでの MCP 利用 (公式が禁止、skill のみに倒す)。

## 2. 役割分担

| レイヤ | 持ち物 |
|---|---|
| **案件 repo (毎回)** | `.newrelic-profile` (使う profile 名、**repo ローカル・`.gitignore`**) と (任意) `.envrc`。1案件=1repo の対話はこれで「居場所=顧客」に固定 |
| **per-project 公式 MCP (対話)** | `.mcp.json` (リモート MCP 登録。リージョン URL + 鍵は env 参照)。NRQL/ダッシュボード/アラートの NR メンテ tool surface。**`/newrelic init` が `.newrelic-profile` から生成** (手書き禁止) |
| **`/newrelic` skill (バッチ/CI/横断・agent-rules)** | NerdGraph (GraphQL) クライアント。profile 解決 (fail-closed)・3者一致検証・レート/リージョン制御・監査ログ。`--profile` 明示でマルチテナント横断を安全に |
| **ユーザーの鍵保管 (リポ外)** | `~/.newrelic/<profile>.env` (`NEW_RELIC_API_KEY`/`NEW_RELIC_ACCOUNT_ID`/`NEW_RELIC_REGION`, `chmod 600`) |

**経路の使い分け** (ADR §B): per-project MCP は**単一テナント repo の対話専用**。複数顧客を横断する共通 repo (全顧客集計・移行) は MCP に頼らず **skill の `--profile` を呼び出し毎に**使う。

## 3. アーキテクチャ — プロファイルの単一ソース化 (ADR §A の核)

```
                  ~/.newrelic/<profile>.env   (鍵+accountId+region, 600, リポ外)
                         ▲ 唯一の鍵の出所
                         │
   repo/.newrelic-profile (= profile 名。唯一の "どの顧客か" の真実、gitignore)
        │                          │
        │ /newrelic init 生成       │ /newrelic <cmd> が解決
        ▼                          ▼
   repo/.mcp.json (対話)      skill (バッチ/横断)
   region URL + ${KEY} env    NerdGraph 直 + accountId
        │                          │
        └────────► doctor/whoami が3者一致を検証 ◄────┘
           (.mcp.json の region == profile == 鍵が実際に見える account)
                     不一致なら即エラー (誤爆を起動前に止める)
```

- **単一ソース**: 顧客の同定は常に `.newrelic-profile` 起点。MCP 側の `.mcp.json` を手書きさせず init が profile から生成するので、**MCP と skill が別アカウントを指す事故 (ADR §A) が構造的に起きない**。
- **env のバインド (誤爆防止の要)**: 公式 MCP はリモート (URL) で `${NEW_RELIC_API_KEY}` を Claude Code の環境から解決する。これが別 profile の鍵だと誤爆するので、**repo の `.envrc` (direnv, gitignore) が `.newrelic-profile` の profile を自動 export** する方式を推奨 (cd で正しい鍵が入る)。direnv 不使用なら `nr-claude` ラッパ (profile を export して `claude` 起動) を提供。
- **doctor の不変条件**: `.mcp.json` の region URL == profile.region、Claude Code が注入する `$NEW_RELIC_API_KEY` == profile の鍵、その鍵が NerdGraph で profile.account_id を**実際に見られる** (`actor.account(id:)` が非 null)。1 つでも崩れたらエラー。

## 4. スキル構成 (agent-rules)

```
skills/newrelic/
  SKILL.md                  # ルーティング + 経路の使い分け + 安全規律
  scripts/
    newrelic.py             # PEP723 uv CLI。NerdGraph client(throttle+backoff)、
                            #   profile 解決(fail-closed)、3者一致検証、監査ログ
  templates/
    mcp.json.tmpl           # per-project リモート MCP (region URL + ${NEW_RELIC_API_KEY})
    envrc.tmpl              # 任意: .newrelic-profile → profile env を direnv で自動 export
    profile.env.tmpl        # ~/.newrelic/<name>.env の雛形 (key/account/region)
    gitignore-snippet       # .newrelic-profile / .envrc / *.nrql.local を ignore
  reference/
    nerdgraph-queries.md    # whoami/nrql/entities/dashboards/alerts の GraphQL 断片
```
`install.sh` が `skills/*/` を自動 symlink。**New Relic MCP は global (`~/.claude`) に登録しない** (ADR §C。付け忘れは接続不能=fail-closed であって誤爆にしない)。

## 5. サブコマンド

| コマンド | 役割 |
|---|---|
| `init [dir] --profile <name>` | 雛形展開: `.newrelic-profile` 書込 + profile から `.mcp.json` 生成 + `.gitignore`/`.envrc` 整備。profile env 不在なら拒否。FedRAMP/HIPAA profile は `.mcp.json` を作らず skill 専用にする |
| `doctor` | **3者一致検証** (§3)。起動時/不安時に。不一致を具体的に指摘 |
| `whoami` | 軽量確認: いま解決される profile と「鍵が実際に見える account/region」を表示 (= `gh auth status` 相当) |
| `nrql "<NRQL>" [--profile p]` | NerdGraph で NRQL 実行。account は profile から |
| `entities [--query <name>] [--type ...]` | エンティティ検索 (entitySearch) |
| `dashboards [list\|get <guid>]` | ダッシュボード一覧/取得 |
| `alerts [list\|policies\|...]` | アラート参照 (既定 read)。**書込系は profile を再表示して確認** |
| `profile list\|show\|path` | `~/.newrelic/*.env` の **名前のみ**列挙 / 解決結果表示 / パス |

- 全コマンドは**冒頭にアクティブ profile を echo** (`[profile=acme-prod account=1234567 region=us]`)。
- 破壊的/書込系 (alerts 変更等) は profile を再掲して明示確認。

## 6. プロファイル解決と設定 (fail-closed)

**解決順 (ADR §C)**: `--profile <name>` > `.newrelic-profile` (cwd→repo ルートを探索) > **エラー**。
- **既定へ黙って倒さない**。`$NEW_RELIC_DEFAULT_PROFILE` のような暗黙既定は持たない。
- profile 検証: `~/.newrelic/<name>.env` が存在し perms 600、3 キー (`NEW_RELIC_API_KEY`/`NEW_RELIC_ACCOUNT_ID`/`NEW_RELIC_REGION`) が揃い、region∈{us,eu}。1 つでも欠ければハードエラー。
- `.newrelic-profile` が空/改行のみ/未知 profile 名 → ハードエラー (フォールバック禁止)。
- **EU 鍵の sanity check**: region=us なのに鍵が EU prefix (またはその逆) なら警告して停止。

**設定の解決順** (figma 踏襲): 引数 > 環境変数 > `~/.config/newrelic.toml` > 既定。

```toml
# ~/.config/newrelic.toml
max_concurrency = 8     # NerdGraph 同時25/user の下に自前で床を引く
min_interval_ms = 0     # 必要なら送信間隔の床
max_retries     = 4     # 429/5xx のリトライ上限
```

## 7. 安全機構 (ADR §A–G の実装)

| ADR | 実装 |
|---|---|
| §A 経路同期 | profile 単一ソース + init 生成 + `doctor` 3者一致検証 |
| §B 横断 | 共有 repo は `--profile` 明示。per-project MCP は単一テナント対話のみ |
| §C fail-closed | 解決不能=ハードエラー / global MCP 不登録 / perms 600 強制 |
| §D 漏洩 | `.newrelic-profile`・`.envrc` は `.gitignore`。profile 名は非識別的を推奨 |
| §E 監査 | `~/.newrelic/audit.log` (JSONL) に呼び出し毎追記 (§8) |
| §F 鍵経路 | 鍵は **argv に出さない** (profile ファイルから読む)。`${KEY}` の env 展開がログに出ないか実機検証 (§9) |
| §G 将来 | 公式 MCP 改ざん時も skill(NerdGraph 直) が信頼最小 fallback。Vault は案件増で再検討 |

## 8. 監査ログ (ADR §E)

`~/.newrelic/audit.log` に 1 行 JSONL を追記。事故時に「いつ・どの顧客テナントに・何をしたか」を追跡可能にする。**鍵と NRQL の生機密値は記録しない** (NRQL は SHA-256 ハッシュのみ)。

```json
{"ts":"2026-06-21T09:00:00Z","profile":"acme-prod","account_id":1234567,"region":"us","cmd":"nrql","nrql_sha256":"…","status":"ok","latency_ms":312}
```

## 9. レート制限・リージョン

- **エンドポイント** (profile.region で切替): US `https://api.newrelic.com/graphql` / EU `https://api.eu.newrelic.com/graphql`。MCP は US `https://mcp.newrelic.com/mcp/` / EU `https://mcp.eu.newrelic.com/mcp/`。
- **同時数**: NerdGraph は同時 25/user (超過で 429)。skill は `max_concurrency` (既定 8) で自前の床を引き、横断バッチでも余裕を残す。
- **429/5xx**: `Retry-After` 準拠 + 指数 + jitter で自動リトライ (figma の `Client` 機構を流用)。
- NRQL は 3,000 queries/account/min。通常用途では当たらない。

## 10. NerdGraph クエリ (reference)

```graphql
# whoami: 鍵の持ち主 + 見える account
{ actor { user { id name email } accounts { id name } } }

# account 可視性検証 (doctor): null/error なら鍵がその account を見られない
{ actor { account(id: <PROFILE_ACCOUNT_ID>) { id name } } }

# nrql
{ actor { account(id: <ID>) { nrql(query: "<NRQL>") { results } } } }

# entity 検索
{ actor { entitySearch(query: "name LIKE '%<q>%'") { results { entities { guid name entityType } } } } }
```

## 11. 実機検証項目 (ADR 追記より)

- 公式 MCP に 1 案件 repo で実接続し、**NRAK ヘッダ方式 / OAuth のどちらが運用しやすいか**確認。
- `.mcp.json` の `${NEW_RELIC_API_KEY}` 展開値が Claude Code のログ/エラー/履歴に**残らないか**検証 (残るなら token helper か OAuth に切替)。
- Claude Code の **MCP 設定継承** (親子 `.claude/settings.json`・解決順) で子 repo が親の古い設定を継承して誤爆しないか。
- `doctor` の 3者一致検証が、鍵すり替え/region 取り違え/account 不可視を実際に検出するか (意図的に壊して確認)。
- `~/.newrelic_token` (既存) を最初の profile に流用し、`whoami`→`nrql` まで実機疎通。

## 12. 未解決 / 将来

- 既存稼働 repo への**後付け移行手順** (init 一括 + doctor 一斉検証) の具体化。
- FedRAMP/HIPAA profile のフラグ (`mcp_allowed=false`) と init の分岐を確定。
- 鍵の中央管理 (Vault/Secrets Manager) — 案件数増・チーム共有が進んだ段階で ADR 追補。
- ダッシュボード/アラートの書込操作をどこまで skill に持たせるか (現状は閲覧 + 最小)。
```
