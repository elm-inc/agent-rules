# elm-inc ハーネス・アーキテクチャ: 標準化とプロダクト固有事情の両立

- Linear: AGENT-25
- ステータス: 合意 (2026-09-18) — Fable 5.1 レビュー反映済み (§11)。Phase 1 実装中
- 関連: [stack-governance.md](stack-governance.md) (本設計の「スタック Profile」) / [ADR-0013](../adr/0013-three-layer-knowledge-architecture.md) (3 層ナレッジ・本設計が拡張する) / [ADR-0017](../adr/0017-ai-workflow-model-refresh-and-review-layers.md) / [ADR-0018](../adr/0018-port-inventory-and-registry.md) / [ADR-0020](../adr/0020-parallel-exploration-and-scoring-oracle.md)

## 1. 背景

AI エージェントを「モデル + ハーネス」と捉え、モデルの外側 (文脈・ツール・ガードレール・フィードバック・検証) を設計対象にする考え方が「ハーネスエンジニアリング」として 2026 年に定着しつつある (Böckeler, [Harness Engineering for Coding Agents](https://martinfowler.com/articles/harness-engineering.html) / OpenAI, [Harness engineering](https://openai.com/index/harness-engineering/) / Anthropic, [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents))。一方で「標準ハーネスを複数プロダクトに配り、版を管理し、プロダクトごとに上書きする」実践の公開事例はほとんど無い。

agent-rules は実質的に elm-inc のハーネスそのものだが、次の点で「標準化しつつプロダクト固有事情に対応し、安定運用する」要求を満たせていない。

### 1-1. 実測 (2026-09-18・ローカル clone 約 75 リポ)

| 観点 | 実態 | 帰結 |
|---|---|---|
| 案件側のハーネス | `.claude/settings.json` を持つのは約 9 件、Claude 関連ファイルが一切無いのが 40 件 | 標準化は L1 (symlink) だけで届いており、**プロダクト固有の対応は機械可読な置き場が無い** |
| 機密案件の扱い | 外部 LLM への送信を止めるのは「実行時に `DEEPSEEK_API_KEY=` と空にする」非常口のみ (4 スキル)。どのリポが機密かの機械可読な記録は無い | **人が忘れれば、誰も気づかないまま外部 LLM へ送信される** |
| 案件固有の目印 | `.no-linear`・`.newrelic-profile`・(提案中だった) `.stack.yml` が個別に存在 | 目印が増えるほど、どれを見ればよいかが分散する |
| 配布 | 全資産が symlink で main から即時配布 | 1 つの変更が全セッションに一斉に効く。版の固定も段階展開もできない |
| settings の配布 | `install.sh --fix` はトップレベルのキー単位の add-only マージ | **`hooks` キーを既に持つマシンには新しい hook を配れない** (Fable D-1) |

## 2. 目標・非目標・脅威モデル

### 目標
1. **標準化**: 全案件が同じ中核 (安全原則・レビュー層・ワークフロー) で動く
2. **固有事情への対応**: 案件ごとの違い (機密性・スタック・利用モジュール) を**宣言として機械可読に持ち**、ハーネスがそれに応じて振る舞いを変える
3. **安定運用**: ハーネス自体の変更を版で管理し、壊れたこと・止まったことを計器で検知できる

### 脅威モデル (2026-09-18 ユーザー決定)

**対象は「Claude Code の通常の利用で、うっかり不適切な送信をしてしまう」ことだけ**。具体的には:
- 機密の案件で、外部 LLM に送るスキル (`/deepseek-redteam`・`/gemini-review`・`/codex-review` 等) を使ってしまう
- 公開の repo で作業中に、`--scope` などで別の機密 repo のコードを送ってしまう
- 区分を宣言し忘れた repo で送ってしまう

**対応は「送信の前に伝える」であって、遮断ではない**。システムで強く規制すると、開発以前に作業が止まる懸念があるため (ユーザー判断)。

### 非目標
- 送信の**遮断** (hook の deny・許可リスト方式・ネットワーク分離)
- 意図的な持ち出し・改ざんへの防御 (prompt injection されたエージェントが宣言や検知器を書き換える、ラッパや `eval` で検知を迂回する等)
- MCP 経由の送信 (Slack・Notion・Drive・Chrome で他社 LLM の UI に貼る等)・Artifact 公開・別 org への `git push` — Phase 4 で検知の追加を検討する
- Claude Code を経由しない利用 (手打ちのシェル、Codex 単体セッション)。ただし送信ヘルパを共有するため、結果的に通知は出る
- 案件コードの秘匿そのもの (Claude Code 自体が Anthropic に送信する。本設計が扱うのは**それ以外のベンダー**への送信)
- Backstage 等のポータル構築

## 3. 構成モデル

### 3-1. 構成要素 4 種

Böckeler の Guides / Sensors に、本リポが既に依存している 2 種を加える。

| 種類 | 役割 | 機械的 | 推論的 (LLM) |
|---|---|---|---|
| **Guides** | 事前に導く | テンプレート・golden path・radar・生成 (`dsp emit`) | CLAUDE.md・RULES.md・rules・スキル・ADR |
| **Sensors** | 事後・直前に検知して伝える | pre-commit・テスト・doctor 群・drift CI・osv・**送信の検知 (§6)** | `/local-review`・`/codex-review`・`/code-review`・`/fable-review` |
| **Gates** | 機械的に止める | permissions・既存の PreToolUse hook・CI 必須チェック・予算上限 | — |
| **Meters** | ハーネス自体を監視する | statusline・frontier-usage・`/status`・linear-audit・doctor の最終成功時刻 | — |

- **既定は Sensor (検知して伝える)。Gate は、ユーザーが止めることを明示的に選んだものだけに使う** (本設計の機密の扱いは Sensor)
- **Sensor は黙って止まってはいけない**。判定できなかったこと自体を伝え、計器に残す (frontier-usage の jq abort で予算ガードが 10 倍過少報告した事故の教訓)

### 3-2. 3 層

| 層 | 中身 | 配布経路 |
|---|---|---|
| **Core** (全案件) | 安全原則・レビュー層・ワークフロー定義・**送信の検知** | **即時チャネル** (§5) |
| **Profile** (特性で選ぶ部品) | `sensitivity/*` (public・internal・confidential)・`stack/*` (web-next 等)・`module/*` (linear・design-system・newrelic) | **版固定チャネル** (§5・Phase 3) |
| **Local** (プロダクト固有) | 案件 CLAUDE.md・ADR・`.harness.yml` (宣言と上書き理由) | 各案件 repo またはローカル宣言 |

- Profile は**案件名でなく特性で選ぶ**。public な本リポに案件名を出さずに済む (ADR-0018 と同じ理由)
- **送信の検知は Profile に置かない**。Profile は案件側で有効化するものなので、有効化し忘れた案件で検知が消える。検知は Core に置き、宣言を**読む**だけにする

## 4. 宣言ファイル `.harness.yml`

```yaml
harness: 1                        # スキーマ版 (無い・未知なら本設計のファイルではないとみなし、未宣言扱い)
sensitivity: confidential         # public | internal | confidential
profiles:                         # Phase 2 以降で使う
  - stack/spa-vite-fastapi
  - module/linear
pin: harness-2026.10.0            # ハーネス本体の版 (Phase 3 以降・§9-2)
stack:                            # stack-governance の宣言 (旧 .stack.yml)。radar の pin は stack.radar (§9-2)
  radar: radar-2026-09-14
  gate: report
  constraints: []
  deviations: []
```

- **置き場**: repo ルートの `.harness.yml`、または**ローカル宣言** `~/.config/agent-rules/harness/<host>/<org>/<repo>.yml`。repo の識別は `origin` の URL を正規化したもの (`git@` / `https://` / 末尾 `.git` の揺れを吸収)
- **worktree ではメインワークツリーの宣言を読む** (`git rev-parse --git-common-dir` から復元。`scripts/port-inventory.py` と同じ)
- `.claude/` 配下にしないのは、Codex など Claude Code 以外のツールからも読む宣言だから
- `harness:` キーを必須にするのは、同名の無関係なファイル (CI/CD 製品 Harness の設定等) を誤読しないため (Fable B-5)
- **既存の目印は当面読み続ける**: `.no-linear` は `module/linear` を外した扱い。移行後に廃止

### 4-1. 区分の解決

1. repo の `.harness.yml` とローカル宣言の**うち厳しい方を採る** (confidential > internal > public)。顧客 repo の上流が `public` と書いたファイルを `git pull` で取り込んでも、区分が下がらない (Fable B-1)
2. どちらも無い → **未宣言**。通知上は confidential と同じに扱い、「未宣言の repo から送信します」と伝える (決定 1 の読み替え)
3. 読めない (YAML の parse 失敗・PyYAML 不在・git root の特定失敗・未知の値) → **判定不能**。「判定できませんでした」と伝えて計器に残す。黙って public に倒さない
4. `stack:` セクションは安全の概念ではないため、区分と違い「repo 側を優先・無ければローカル」とする

## 5. 配布: 2 つのチャネル

| チャネル | 対象 | 仕組み | なぜ |
|---|---|---|---|
| **即時** | CLAUDE.md・RULES.md・ユーザーレベル hook・送信ヘルパ (`scripts/lib/`)・台帳 (`config/*.yml`) | 現行の symlink + `install.sh` | 安全や検知の修正を 75 件の PR 待ちにしない。plugin では CLAUDE.md/rules を配れない (公式仕様) |
| **版固定** | スキル本文・agent・Profile の hook・radar・golden path | Claude Code plugin (本リポを marketplace にする)。案件は `.claude/settings.json` で Profile を選ぶ | 変更の影響範囲を案件ごとに制御し、壊れた版を案件側で止められる |
| (第 3 の経路) | `.claude/rules` 雛形・案件 CLAUDE.md 雛形 | `/project-init` のコピー | plugin で配れず、案件にコミットされるもの (Fable D-6) |

### 5-1. 版固定チャネルの前提 (Phase 3 の関門・Fable D 群)

plugin 化には未解決の前提が 4 つある。**すべて解消するまで Phase 3 に入らない**。Phase 1-2 はこれらに依存しない。

1. **案件ごとに版を pin できるか** — docs エージェントは「版は marketplace 側で決まる」、Fable は「project settings の `pluginVersions` で可」と回答が割れている。実機で確認する
2. **スキルが呼ぶ scripts・台帳は main に追従したまま** — スキル本文だけ pin しても、`~/repos/.../scripts/...` を絶対パスで呼ぶ限り版はずれる。plugin に scripts を同梱して `${CLAUDE_PLUGIN_ROOT}` で参照するか、「版固定はスキル本文のみ」と割り切るかを決める
3. **名前空間** — plugin のスキルは `/agent-rules:status` になる。既存の呼び名・他スキルからの参照・台帳の照合キーが変わる。`~/.claude/skills` の symlink を残すと二重ロードで description 予算が倍になる
4. **Codex との非対称** — Codex は同じ `skills/` を symlink で読んでいる。Claude だけ版固定になる移行期の扱いを決める

### 5-2. 即時チャネルの修正 (新しい hook を足す前に必須)

`install.sh --fix` の add-only マージは**トップレベルのキー単位**なので、`hooks` を既に持つマシンに新しい matcher を配れず、`--check` もそれを検出しない。今後 hook を足す前に、hook entry 単位の add-only マージ + nested drift の検出に直す。**Phase 1 は新しい hook を足さない設計にしたので、これに依存しない**。

## 6. Phase 1: 送信の検知と通知

### 6-1. 検知の置き場所: 送信ヘルパ + スキルの事前チェック

本リポの外部 LLM への送信は、ほぼ少数のヘルパに集約されている (2026-09-18 実ファイルで確認):

| ヘルパ | 使っているもの | 状態 |
|---|---|---|
| `scripts/lib/curl-secret.sh` の `curl_auth_bearer` / `curl_auth_header` | deepseek-redteam・gemini-review・test-generate・model-doctor・track-cost・test-deepseek/test-gemini | 既存 |
| `skills/nano-banana/scripts/nano_banana.py` | nano-banana | 既存 |
| `scripts/codex-astra.sh` | codex-review `--astra` | 既存 |
| **`scripts/codex-run.sh` (新設)** | codex-review (通常)・codex-task・codex-audit | **現状はスキルが `codex exec` / `codex review` を直接呼んでいる**。検知を入れた薄いラッパを新設し、3 スキルと `allowed-tools` をラッパ経由に書き換える |

ここに検知を置く。**hook ではなくヘルパに置く理由** (Fable A-1・A-2・A-6):
- 既存 hook 方式 (`claude-guard.sh` の先頭コマンド語判定) は、関数名 `curl_auth_bearer` と継続行の URL を見られず、**本リポの実際の送信を 8 件中 0 件しか検出できなかった** (Fable の実測)
- ユーザーが `/deepseek-redteam` と打ち込んだ場合、スキルは Skill ツールを経由せず展開されるため、Skill を対象にした hook は発火しない
- ヘルパなら、呼ばれ方 (ユーザー入力・モデルの判断・サブエージェント・Codex) に関係なく同じ判定になる
- 新しい hook が要らないので、§5-2 の配布問題を回避できる

### 6-2. 何をするか

1. **事前チェック** (伝えるタイミングを送信の前にするため): 送信するスキルは、送信前の最初の手順で `harness-egress-check <vendor> --target <送る対象のパス>...` を実行する。警告が出たら**ユーザーに一言伝えてから進む** (確認待ちで止めない)
2. **ヘルパ内のチェック** (事前チェックを飛ばした場合の保険): 送信ヘルパが同じ判定を行い、許可外なら stderr に警告を出して**そのまま送信を続ける**
3. **判定**: cwd の repo と送信対象のすべてのパスの区分を解決し、**最も厳しいもの**で「そのベンダーに送ってよいか」を台帳 (§6-3) で判定する (Fable A-5: 公開 repo から別の機密 repo を送る動線)
   - **対象パスの受け渡し契約**: 送信するスキルは事前チェックの前に `HARNESS_EGRESS_TARGETS` (送る対象のパスをコロン区切り) を export する。事前チェック (`--target`) と送信ヘルパの両方がこれを読む。既存のヘルパは認証情報と curl 引数しか受け取らず、送る内容の出所を知らないため (codex-review P2)
   - 未設定なら cwd の repo だけで判定する。**事前チェックを飛ばし、かつ環境変数も無いまま別 repo のコードを送ると検知できない** — これは残余リスクとして受け入れる
4. **記録**: 警告と判定不能を `~/.local/state/agent-rules/egress.log` に残す (案件名を含むためローカルのみ)。事前チェック (`--preflight`) は記録せず、実際の送信側だけを数える (二重計上しない)
6. **判定対象の拾い方** (codex-review 指摘を反映): cwd は常に含める。curl は引数を解析し、本文を送る呼び出しの宛先だけを見る (値を取るオプションの値を宛先と誤認しない・`--url=` 等の表記も扱う)。Codex は `-C` / `--cd` / `--add-dir` で指定されたディレクトリも対象に加える
5. **既存の非常口 (`KEY=` を空にする) は残す**。「伝える」だけでなく本当に止めたいときの手段として

警告の例:
```
⚠ 外部送信の確認: この送信は DeepSeek (api.deepseek.com) に届きます。
   対象 ~/repos/github.com/<org>/<repo> の区分は confidential です (ローカル宣言)。
   止めるには中断してください。意図どおりなら続行されます。
```

### 6-3. 送信先台帳 `config/egress.yml`

どのヘルパ・エンドポイントがどのベンダーへ送るかと、区分ごとに**警告なしで**送ってよいベンダーを 1 か所で持つ (モデル台帳と同じ規律・直書き禁止)。

実装は [`config/egress.yml`](../../config/egress.yml) が正。要点:

```yaml
vendors:
  deepseek: { name: DeepSeek, hosts: [api.deepseek.com] }
  google:   { name: Google (Gemini), hosts: [generativelanguage.googleapis.com] }
  openai:   { name: OpenAI (Codex), hosts: [api.openai.com, chatgpt.com] }
  local:    { name: ローカル LLM, hosts: [localhost, 127.0.0.1] }

helpers: [scripts/lib/curl-secret.sh, skills/nano-banana/scripts/nano_banana.py, scripts/codex-run.sh, scripts/codex-astra.sh]

# 内容を送らない問い合わせは警告しない (Fable A-9: /status の自動 probe を誤検知しない)。
# 主規則は送信ヘルパ側の「本文 (-d/--data*/-F/--json/-T) の無いリクエストは検知しない」。
# ここには本文を送るが内容を含まない既知の問い合わせだけを載せる (現状は無し)
metadata_urls: []

allow:                    # 区分ごとに警告なしで送ってよいベンダー (Anthropic はセッション自体なので対象外)
  public:       [deepseek, google, openai, local]
  internal:     [google, openai, local]     # DeepSeek だけ警告 (§9-1)
  confidential: [local]
  undeclared:   [local]                     # 未宣言は confidential と同じ
```

### 6-4. 計器 (検知が黙って止まらないために)

`/status` に次を 1 行ずつ出す (0 件なら無音):
- 直近 7 日の送信警告の件数 (ログから)
- 判定不能の件数
- 未宣言の repo の数
- 台帳 `config/egress.yml` の parse 状態

さらに CI で「送信がすべてヘルパを通っているか」を検査する (§6-6 AC-1)。**ヘルパを経由しない送信が新しく書かれた時点で CI が落ちる**ので、検知の穴が増えない。

### 6-5. `/harness-audit` (初回の区分付け)

1. 全リポを走査し、区分の**案**を 1 ファイルにまとめて出す (根拠: org・既知の個人/社内リポ・README の記述等。**最終判断はユーザー**)
2. ユーザーが確認した区分を、**全リポについてローカル宣言として一括で書く** (1 回の確認で済ませる。各 repo の作業ツリーを汚さない — Fable C-4)
3. repo に `.harness.yml` をコミットしたい自社リポは、repo ごとの PR として別に行う
4. 出力は案件名を含むため**ローカルにだけ**置く (本リポの作業ツリーに差分を残さない)

### 6-6. 受け入れ基準 (Phase 1)

| # | 基準 | 検証手段 |
|---|---|---|
| AC-1 | `skills/**/SKILL.md`・`skills/**/scripts/**`・`scripts/**`・`agents/**` の中で外部 LLM に届く箇所 (エンドポイントの URL と `codex exec` / `codex review` の呼び出し) が、**すべて送信ヘルパ経由**である | コーパス試験: 該当行を機械抽出し、ヘルパ外の送信が 1 件でもあれば CI fail。変異注入 (`scripts/` と `skills/*/scripts/` の両方に生の `curl https://api.deepseek.com` を足す → 赤) で検査器自体を検査 (Fable F-1・F-2 / codex-review P2) |
| AC-2 | confidential・未宣言の repo で送信スキルを使うと、**送信の前に**警告が表示され、処理は止まらずに続く | 各スキルの事前チェック手順を実機で 1 回ずつ + ヘルパの表駆動テスト (区分 4 × ベンダー 4) で「警告あり・exit 0」 |
| AC-3 | public 宣言の agent-rules 自身では、警告が 1 件も出ない (ノイズ 0) | 実機で `/deepseek-redteam`・`/gemini-review`・`/codex-review` |
| AC-4 | 公開 repo の cwd から機密 repo を対象に指定すると、機密側の区分で警告される。**事前チェックを通さずヘルパを直接呼んでも** `HARNESS_EGRESS_TARGETS` があれば同じ判定になる | fixture (事前チェック経由と、ヘルパ直呼びの 2 通り) |
| AC-5 | repo の宣言が public・ローカル宣言が confidential のとき、confidential で判定される | fixture |
| AC-6 | 内容を送らない問い合わせ (`/status` の自動 probe・残高確認) では警告しない | model-doctor・track-cost を confidential の cwd で実行し、**警告ログの行数が増えないこと**で確認 (model-doctor は stderr を捨てるため画面では判定できない) |
| AC-7 | 判定不能 (parse 失敗・PyYAML 不在・未知の値・git 外) は「判定できませんでした」と伝え、ログに残る。**黙って public 扱いにしない** | 各状態を fixture 化し、警告文の理由コードまで一致を確認 (Fable F-4) |
| AC-8 | worktree からメインワークツリーの宣言が読まれる | worktree fixture |
| AC-9 | `/status` に §6-4 の計器が出る (0 件なら無音) | ログを fixture で用意して表示を確認 |
| AC-10 | `/harness-audit` 実行後、本リポの作業ツリーに差分が無い | 実行前後の `git status --porcelain` |

## 7. 安定運用: Sensors と Meters (Phase 2 以降)

- **`/harness-doctor`** (Phase 4): 案件ごとに「宣言があるか」「pin がどれだけ古いか」「選んだ Profile が要求する Sensors (pre-commit・CI・依存更新 bot) が実際に入っているか」「stack の 4 軸 (stack-governance §4-3)」を 🔴/🟡 で報告。合成スコアは作らない。計器の停止は 🔴
- **ハーネスの回帰テスト**: スキルを変える PR で `claude plugin eval` を回し、plugin なしとの差を測る (費用上限付き)。検知器は表駆動 fixture + 変異注入で検査器自体を検査する
- **ワークフローの遵守計測**: linear-audit と同じく「実際に回っているか」を測る。ただし行動に繋がるものだけを測る
- **掃除**: `/skill-doctor` で使われていないスキル、`review_by` を過ぎた rules を四半期見直しで降格・削除する (ADR-0013 の逆方向ルールの機械化)

## 8. 段階計画

| Phase | 内容 | 依存 |
|---|---|---|
| **1 (着手)** | `config/egress.yml` + `.harness.yml` v1 (sensitivity のみ) + 読み取りライブラリ + `harness-egress-check` + 送信ヘルパへの組み込み + 送信スキルの事前チェック手順 + `/status` の計器 + `/harness-audit` + コーパス試験 CI | なし |
| 2 | stack Profile (stack-governance Phase 1-2 を `.harness.yml` の `stack:` で実装) | Phase 1 の読み取りライブラリ |
| 3 | plugin 化 (スキル本文・Profile) + `/project-init` をハーネスの導入/更新に拡張 | §5-1 の前提 4 つ・§5-2 の install.sh 修正 |
| 4 | `/harness-doctor`・plugin eval・遵守計測・MCP 経由の送信の検知 | Phase 2-3 |

## 9. 決定事項 (2026-09-18 ユーザー決定)

1. **internal 区分で警告するのは DeepSeek だけ** — OpenAI (Codex)・Google (Gemini) は警告しない。DeepSeek は中国企業の API で、スキル自身もコンプライアンス確認を促しているため。confidential と未宣言はローカル LLM 以外すべて警告する
2. **pin は 2 本に分ける** — `.harness.yml` の `pin:` (ハーネス本体の版・Claude Code が読む) と `stack.radar:` (radar の tag・案件 CI が読む)。2026-09-14 の「一本化」は、Fable の指摘 (E-2) で読み手も更新頻度も違うと分かったため変更した。宣言ファイルが 1 つである点は変わらない

## 10. 検討した代替案

### A. 送信を遮断する (hook の deny・許可リスト方式)
- 不採用理由: ユーザー判断 (作業が止まる懸念)。加えて Fable のレビューで、遮断を成立させるには回避経路 (ラッパ・`python3 -c`・`bash -c`・未登録ベンダー・宣言や検知器の改ざん) の列挙が際限なく広がり、それ自体が大きな保守負債になると分かった

### B. hook で検知する (Skill と Bash の二段)
- 不採用理由: 実測で本リポの送信を 8 件中 0 件しか検出できず、ユーザー入力のスラッシュコマンドでは発火しない (Fable A-1・A-2)。さらに新しい hook は現行の `install.sh` では配布できない (§5-2)

### C. ネットワーク分離 (`bwrap --unshare-net` + 許可リスト proxy)
- 不採用理由: 意図的な持ち出しまで塞げる唯一の構造的な手段だが、脅威モデル (§2) の対象外。遮断でもあるためユーザー判断にも反する。必要になったら再検討する

### D. 宣言を中央の台帳 (agent-rules) に集約する
- 不採用理由: 案件名が public repo に出る (ADR-0018・ADR-0021 と同じ)

### E. 区分を skill ごとの引数・環境変数で都度指定する (現状維持)
- 不採用理由: 人が忘れた時点で、誰も気づかないまま送信される

## 11. Fable 5.1 レビュー反映記録 (2026-09-18)

脅威モデルを「通常利用でのうっかり送信・遮断せず通知」に絞った (ユーザー判断) ため、指摘は 3 つに分かれた。

| 指摘 (致命度) | 判定 | 対応 |
|---|---|---|
| A-1 Bash 層が実送信を 0/8 件しか検出しない (Critical) | **採用** | 検知を送信ヘルパに移す (§6-1) |
| A-2 ユーザー入力のスラッシュコマンドで Skill hook が発火しない (Critical) | **採用** | 同上 + スキルの事前チェック手順 (§6-2) |
| A-6 検問所を送信ヘルパに置く (Critical) | **採用** | §6-1 の中心 |
| D-1 `install.sh` が新しい hook を配れない (Critical) | **採用 (前提として)** | Phase 1 は hook を足さない。hook を足す前の必須修正として §5-2 に記録 |
| C-2 gate の script・台帳・settings が改ざん可能 (Critical) | **脅威モデル外** | 意図的な改ざんは非目標 (§2) |
| A-5 cwd と送信対象が違う (High) | **採用** | `--target` の区分も解決し最も厳しいものを採る (§6-2) |
| B-1 repo 優先だと上流の pull で区分が下がる (High) | **採用** | 厳しい方を採る (§4-1) |
| A-3 ラッパ経由の迂回 / A-4 未登録ベンダーが素通り (High) | **脅威モデル外 (一部採用)** | 意図的な迂回は非目標。通常利用の送信はヘルパ経由であることを AC-1 のコーパス試験で担保 |
| B-2 origin 付け替えで宣言を借用 / C-1 宣言の書き込み保護が列挙防御 (High) | **脅威モデル外** | 宣言の保護はしない (§2) |
| D-2 plugin で版固定しても scripts は main 追従 / D-3 名前空間 / D-4 Codex との二重管理 (High) | **採用 (Phase 3 の関門)** | §5-1 の前提 2〜4 |
| E-1〜E-3 stack-governance との矛盾 (`.stack.yml` の残存・pin の結合・顧客 repo の CI) (High) | **採用** | stack-governance.md を改稿。pin の分離は §9-2 で確認 |
| F-1・F-2 AC が実コマンドを通していない・変異注入が無い (High) | **採用** | AC-1 のコーパス試験 + 変異注入 |
| A-9 メタデータ問い合わせの誤検知 (Medium) | **採用** | `metadata_only` (§6-3) |
| B-5 ファイル名の衝突 (Medium) | **採用** | `harness:` キー必須 (§4) |
| B-6・B-7 fail-closed の衝突・hook の故障は素通り (Medium) | **採用 (形を変えて)** | 判定不能を伝えて計器に残す (§4-1・§6-4)。hook は使わない |
| C-4 `/harness-audit` で 75 回の確認・作業ツリーの汚染 (Medium) | **採用** | ローカル宣言を 1 回の確認で一括 (§6-5) |
| D-5 `pluginVersions` で案件別 pin 可 (Medium) | **要実機確認** | docs エージェントと回答が割れている (§5-1-1) |
| D-6 rules 雛形は版固定チャネルで配れない (Medium) | **採用** | 第 3 の経路として表に追加 (§5) |
| A-7 ネットワーク分離の却下理由が弱い (Medium) | **脅威モデル外** | §10-C に理由を書き直し |
| A-8 hook で見えない経路 (MCP・Artifact・git push・Codex 単体) (Medium) | **非目標として明記** | §2。MCP は Phase 4 で検知を検討 |
| C-3 `ask` の挙動が未定義 (Medium) | **不要になった** | `ask` を使わない |
