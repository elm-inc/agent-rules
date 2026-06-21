# ADR-0008: New Relic 接続 — per-project 公式 MCP + /newrelic skill のハイブリッド

## ステータス

採択 (2026-06-21)
<!-- /deepseek-redteam を Claude が敵対的検証し追記 §A-G を反映 + ユーザー合意済み。実装は PR #11 (/newrelic skill)。前提: 案件=別顧客テナント / 1案件=1repo / 対話もバッチも両方使う。実機検証は GitHub Issue 化して残す。 -->

## 文脈

Claude Code から **New Relic** を操作したい。本環境の用途は受託 (consulting) であり、**案件ごとに別顧客の New Relic テナント (アカウント) を触る**。誤って別顧客のテナントにクエリすれば**顧客データの混線**になる。これは既に経験した **gh の `_chd` サイレント切替で merge が壊れた事故** ([memory] gh-account-elm-inc) と同じリスク階層であり、ユーザーは明示的に「**プロファイルを指定した運用**」を要望している。

接続方式を決めるにあたり、以下を調査で確定した (2025〜2026 時点):

- **公式リモート MCP server が存在する** (2025-11-04 public preview)。US `https://mcp.newrelic.com/mcp/` / EU `https://mcp.eu.newrelic.com/mcp/`。NRQL クエリ・ダッシュボード・アラート管理・discovery に対応。Claude Code 公式対応。認証は **User API Key (`NRAK-*`)** または **OAuth (ブラウザログイン)**。FedRAMP/HIPAA アカウントは利用禁止。
- **API は NerdGraph (GraphQL)**。エンドポイント US `api.newrelic.com/graphql` / EU `api.eu.newrelic.com/graphql`。
- **API キー種別**: User Key (`NRAK-*`, NerdGraph クエリ/設定用・ユーザー紐付け) / License Key (ingest 用・アカウント毎) / Browser / Mobile。本用途 (クエリ・参照) は **User Key**。
- **マルチアカウント**: 1 User Key は権限スコープ内で複数 account を跨げ、クエリ時に `accountId` を指定する。ただし**別顧客テナント (別 organization) はそもそも認証ドメインが分かれ、鍵も別**になるのが通常。
- **リージョン**: US / EU でデータセンター・API・MCP・UI が完全分離。organization 作成時に確定、後から変更不可。**EU の鍵は prefix で判別可能**。
- **レート制限 (NerdGraph)**: 同時リクエスト **25/ユーザー** (超過で HTTP 429)、NRQL は 3,000 queries/account/min。頻度制限ではなく同時数制限。
- **OAuth リモート MCP は headless/cron で不安定**: 本リポの運用方針 (CLAUDE.md) 自身が「対話認証の MCP は headless/cron 実行で不在になり得る」と注記している。
- 本リポには **Figma で同型の前例**がある: レート制限配慮の REST skill (`/figma`, ヘッドレス/バッチ) と対話用リモート MCP を**併用**するハイブリッド (ADR-0001 の重複排除思想下)。

設計の制約として、ユーザーの作業フローは確認済みで **「対話も自動化も両方使う」「1 案件 = 1 repo」**である。

## 決定

agent-rules に **New Relic 接続をハイブリッド**で実装する。Figma の前例 (REST skill + リモート MCP) を踏襲し、**用途で経路を分ける**。

設計の最上位原則は **「アクティブな顧客アカウントを常に明示・検証可能にし、global/暗黙にしない」** (gh `_chd` 事故の教訓)。

### 1. 対話レイヤー = 公式リモート MCP を「案件 repo 毎」に登録

- 各案件 repo の `.mcp.json` (または `.claude/settings.json`) に New Relic MCP を登録する。**プロファイル = 今いる repo** となり、repo に入れば自動でその顧客のテナントに繋がる (**構造的に誤爆しない**)。
- 鍵は `.mcp.json` に直書きせず **env 参照** (`${NEW_RELIC_API_KEY}` 等)。リージョンに応じて US/EU エンドポイントを使い分ける。
- 登録テンプレを `templates/` に置き、`/newrelic init <repo>` で展開可能にする。

### 2. バッチ/CI/横断レイヤー = 自前 `/newrelic` skill (NerdGraph)

- `/figma` の構造を踏襲した REST (NerdGraph GraphQL) skill。
- **プロファイル管理**: `~/.newrelic/<profile>.env` に `NEW_RELIC_API_KEY` / `NEW_RELIC_ACCOUNT_ID` / `NEW_RELIC_REGION` (`us`|`eu`) を束ねる (`~/.*_token` 規約の発展形、`chmod 600`)。
- **解決順**: `--profile <案件>` > repo 直下 `.newrelic-profile` (1案件=1repo なので自動解決) > エラー (黙って既定を使わない)。
- **毎回アクティブ profile を冒頭に echo** (gh の教訓)。`whoami` サブコマンドで「鍵が実際に見ているアカウント/リージョン」を検証 (= `gh auth status` 相当の安全弁)。
- **サブコマンド (案)**: `whoami` / `nrql "<NRQL>"` / `entities` / `dashboards` / `alerts`。
- **レート制限制御を自前で握る**: 同時 25 を上限にバッチ、429 バックオフ、リージョン別エンドポイント切替 (figma skill のスロットル/バックオフ機構を踏襲)。

### 3. 安全装置 (両レイヤー共通)

- repo ↔ profile の対応を repo 直下 `.newrelic-profile` (repo ローカル・`.gitignore` 対象、**commit しない**) で固定。1案件=1repo の対話用。**共有/横断作業はこのファイルに頼らず明示 `--profile` を使う** (理由は追記 §A/§B)。
- skill は破壊的・書き込み系操作 (アラート変更等) で**アクティブ profile を再表示して確認**する。
- 鍵は repo に commit しない (`.gitignore` で `.env`・`~/.newrelic/` 方式)。

詳細仕様は別途 `docs/design/newrelic-skill.md` に展開する。

## 理由

- **顧客テナント混線の防止が最優先**: 案件=別顧客なので、誤爆は技術問題でなく信頼問題。per-project MCP は「repo に縛る」ことで誤爆を構造的に消し、skill は「明示 profile + 毎回 echo + whoami」で検証可能にする。単一 global MCP はこの原則に反するため却下。
- **両用途を最小コストで満たす**: 対話は公式 MCP に乗れば NRQL/ダッシュボード/アラートの tool surface を NR がメンテしてくれる (自前実装不要)。自動化は OAuth MCP が headless で不安定なため skill が必須。役割を分けると双方の長所を取れる。
- **1案件=1repo と相性が良い**: per-project `.mcp.json` でプロファイルが「居場所」に一意化され、手動切替が不要。
- **前例との整合**: Figma の REST skill + リモート MCP ハイブリッド (ADR-0001) と同型で、重複を作らず学習コストも低い。
- **レート制御の必要性**: 横断/CI で複数アカウントを叩くと同時 25 制限に当たる。skill 側で握れば figma 同様に構造的に回避できる。

## 検討した代替案

### 代替案 A: 単一 global MCP に 1 アカウント分の鍵を入れる
- Pros: 設定が最小、すぐ繋がる。
- Cons: どの顧客テナントを見ているかが暗黙。gh `_chd` と同型の**サイレント誤爆**が起きる。複数案件の切替に弱い。
- 不採用理由: 最上位原則 (明示・検証可能) に正面衝突。受託で最も避けたい事故を誘発する。

### 代替案 B: `/newrelic` skill のみ (MCP を使わない)
- Pros: 全用途を 1 経路に統一、明示 profile を徹底できる。
- Cons: 対話的な NRQL 探索・ダッシュボード/アラート操作を全部自前実装することになり、NR が公式 MCP で提供する tool surface を捨てる。
- 不採用理由: 対話用途では公式 MCP の方が低コストで高機能。両方使う要望に対し非効率。

### 代替案 C: 公式 MCP のみ (skill を作らない)
- Pros: 自前コードゼロ、公式メンテに乗れる。
- Cons: OAuth/対話前提で **headless/CI/cron で不安定** (CLAUDE.md 注記)。横断バッチのレート制御を握れない。`--profile` 明示運用が MCP の登録単位に縛られる。
- 不採用理由: 自動化要件を満たせない。per-project 登録だけでは「共有 ops から複数案件横断」に弱い。

### 代替案 D: 生 curl で NerdGraph を直接叩く
- Pros: 依存ゼロ。
- Cons: レート制限・リージョン・profile 解決・安全 echo を毎回手書き。figma で「生 curl 禁止」とした理由と同じ轍。
- 不採用理由: 構造的な誤爆/レート事故の温床。skill に集約すべき。

## 帰結

### Pros
- 対話 (公式 MCP) と自動化 (skill) の双方を、それぞれ最適な経路で満たす。
- per-project MCP で「居場所=顧客」が一意化し、対話での誤爆が構造的に消える。
- skill 側は明示 profile + echo + `whoami` で、バッチ/横断でも顧客を取り違えない。
- レート制限・リージョン分離・鍵分離を skill が一元制御 (figma 踏襲)。
- 前例 (Figma ハイブリッド) と同型で学習・保守コストが低い。

### Cons
- **2 経路の二重メンテ**: MCP 登録テンプレと skill の両方を保守する必要 (用途が分かれているので重複ロジックは最小化する)。
- **鍵管理の責任**: `~/.newrelic/<profile>.env` と repo の env 参照が散る。漏洩経路 (`.env` の commit 等) を redteam で要確認。
- **公式 MCP は public preview**: 仕様変更リスク。skill 側 (NerdGraph 直) が安定基盤として残るので致命的ではない。
- **profile 解決の取り違えリスク**: `.newrelic-profile` 不在時の挙動 (黙って既定を使わずエラー) を厳格化する必要。

### 実機検証 / 将来の検討事項
- 公式 MCP を 1 案件 repo で実接続し、NRAK と OAuth のどちらが運用しやすいか確認。
- `.mcp.json` の env 参照で鍵がログ/履歴に漏れないか検証。
- skill の `whoami` が「鍵が見ているアカウント・リージョン」を確実に返すか (NerdGraph `actor.user` / `actor.accounts`)。
- 案件のリージョン分布 (US/EU 偏り or 混在) を確認し、テンプレ既定値を決める。
- FedRAMP/HIPAA アカウントが対象になる場合、公式 MCP は使えないため skill のみに倒す分岐を design に明記。

### 関連 ADR
- [ADR-0001](0001-multi-llm-development-workflow.md) — 重複排除の思想・設計は Opus 起草 + /deepseek-redteam で redteam。
- Figma 接続 (REST skill + リモート MCP 併用) の前例 — CLAUDE.md「Figma 連携」節。
- [memory] gh-account-elm-inc — サイレント誤アカウント事故の教訓 (本 ADR の最上位原則の出所)。
- 詳細設計: [`docs/design/newrelic-skill.md`](../design/newrelic-skill.md)。

## 追記 (2026-06-21 — /deepseek-redteam 反映)

DeepSeek-R1 のレッドチームを Claude が敵対的検証 (集約→重複排除→ランク付け) し、Critical/High を反映する。決定の骨子 (ハイブリッド) は不変、安全機構を強化する。R1 の「1点直すなら MCP 廃止・skill 一本化」は**不採用** (ハイブリッドの主目的=NR メンテの tool surface を失う)。代わりに R1 自身の代替策である**経路間の一致検証**を採る。

- **§A 二重経路の非同期を構造的に封じる (Critical)**: MCP と skill が別アカウントを指す事故を防ぐため、**プロファイルの単一ソース化**を強制する。`.newrelic-profile` を唯一の真実とし、`/newrelic init` が**そこから `.mcp.json` を生成**する (手書きさせない)。`whoami`/doctor は「`.mcp.json` が指すアカウント = `.newrelic-profile` のアカウント = 鍵が実際に見ているアカウント」の三者一致を検証し、不一致ならエラー。

- **§B 横断/共有 repo の扱いを明示 (Critical)**: 「1案件=1repo」は対話の既定パターンであり普遍前提ではない。**複数顧客を横断する共通 repo (全顧客ダッシュボード集計・移行作業等) は per-project MCP に頼らず、skill の明示 `--profile <案件>` を呼び出し毎に使う**。per-project MCP は単一テナント repo の対話専用と位置づけを限定する。

- **§C fail-closed と global 不在 (Critical)**: profile が解決不能 (`--profile` 無し かつ `.newrelic-profile` 無し/空/不正/未知名) のとき、**黙って既定に倒さず必ずハードエラー**。`~/.newrelic/<profile>.env` のパーミッションが 600 でなければ拒否。さらに **New Relic MCP を global (ユーザー/グローバル settings) に登録しない**。これにより per-project 設定の付け忘れは「接続不能 (fail-closed)」になり、グローバル MCP への**サイレント誤爆にならない**。

- **§D `.newrelic-profile` は commit しない (Critical/情報漏洩)**: commit するとプロファイル名経由で**顧客との取引関係が git 履歴に漏れる**。`.gitignore` 対象とし repo ローカルに留める (1案件=1repo なら binding は自明)。プロファイル名自体も顧客名直書きを避け非識別的にする。

- **§E 監査証跡 (High/フォレンジック)**: skill は呼び出し毎に `timestamp / profile / accountId / region / サブコマンド` をローカル監査ログ (`~/.newrelic/audit.log`) に追記する。鍵・NRQL の機密値は記録しない。これにより事故時に「いつどの顧客テナントに何を投げたか」を追跡可能にする。`whoami` の明示確認と併用。

- **§F 鍵漏洩経路の遮断 (High)**: 鍵は **argv に渡さない** (`--profile` は名前のみ、鍵は profile ファイルから読む) → シェル履歴/プロセスリスト漏洩を封じる。`.mcp.json` の `${NEW_RELIC_API_KEY}` env 展開が Claude Code のログ/エラーに出ないかを実機検証し、漏れるなら token helper や OAuth に切替 (検証項目)。

- **§G Low/将来 (留意のみ)**: ① 公式 MCP は public preview ゆえサプライチェーン改ざんリスクがあるが、skill (NerdGraph 直) が**信頼最小化されたフォールバック基盤**として残るので致命的でない。② 両経路同時のリトライで NerdGraph 同時25制限に当たり得る (per-user)、実発生は稀で Low。③ 鍵の中央管理 (Vault / Secrets Manager, 代替案 F) は「最小構成で始める」方針に反するため現段階見送り、案件数増加・チーム共有が進んだ時点で再検討。

### redteam で追加された検証項目
- Claude Code の MCP 設定継承 (親子 `.claude/settings.json` の解決順) で、子 repo が親の古い MCP 設定を継承して誤爆しないか実機確認。
- `.mcp.json` env 参照の展開値がログ/履歴に残らないか検証 (§F)。
- 既存稼働 repo への後付け移行手順 (init 一括適用 + 一致検証) を design に明記。
