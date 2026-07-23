# CLAUDE.md 再設計 — 3 層ナレッジアーキテクチャと索引の刈り込み

- ステータス: レビュー統合済み (Fable 5 最終レビュー全採用 + deepseek-redteam 統合 §8) — ADR-0013 採択待ち
- 作成: 2026-07-24
- 関連: [ADR-0013](../adr/0013-three-layer-knowledge-architecture.md) (本 design の決定部分) / [ADR-0010](../adr/0010-fable-metered-billing-controls.md) 07-23 改訂 ([PR #19](https://github.com/elm-inc/agent-rules/pull/19)) / [ADR-0009](../adr/0009-separate-templates-from-docs.md) / [ADR-0011](../adr/0011-ai-first-docs-architecture.md)
- 経緯: 方針 v1 (2026-07-23) → Claude Fable 5 最終レビュー (指摘 H1-H4/M1-M6/L1-L3・追加意見 A1-A6 を全採用) → v2 → 本 design doc

## 1. 背景・目的

開発者 1 人 (Claude Code Max プラン) が複数プロジェクトで Claude Code を並行活用している (デモアプリ + 本開発)。各プロジェクトでゼロベースに設計・実装しており、生産性・品質・安全性の観点でプロジェクト横断の共通化が必要。agent-rules がルール・スキル・テンプレの単一集約点 (~/CLAUDE.md 等を symlink 配布) だが、global CLAUDE.md は索引の役割を超えて肥大化し、横断ナレッジを蓄積する仕組みが存在しない。

本 design は (a) CLAUDE.md のあるべき姿、(b) プロジェクト横断ナレッジの 3 層アーキテクチャ、(c) ナレッジ昇格パイプライン、(d) 実行計画を定める。

## 2. 現状 (棚卸し、2026-07-24 実測)

計測方法: `wc -l` / `find ... | wc -l` (main @ 9a814b5)。

| 項目 | 実測 | 備考 |
|---|---|---|
| CLAUDE.md | **280 行** | 自ら掲げる <200 行を 40% 超過。11 セクション |
| RULES.md / AGENTS.md | 61 / 38 行 | Claude+Codex 共通 / Codex 用 |
| .claude/rules/ | 2 ファイル | いずれも agent-rules 内スコープ。stack 別規約は 0 |
| skills/ | 31 個 | description は毎セッション自動ロード = 「第 2 の CLAUDE.md」 |
| scripts/*.sh | 20 個 | |
| docs/ | ADR 12 / design 6 / setup 6 | architecture は README のみ |

### 検出した問題

1. **事実誤り (①で修正、PR #19)**: Fable 課金「7/20〜全部実費」は旧情報。正: Max は週次上限 50% まで included 恒久・超過分のみ従量課金。詳細は ADR-0010 07-23 改訂
2. **肥大化**: ドメイン固有セクション (Figma / New Relic / cad-print / design-voice / シェル環境) が計 ~100 行。スキル description と重複するルーティング表はトークン浪費
3. **drift**: 未掲載スキル 4 (ニッチ hw 系) / 幽霊参照 `/verify` (実在せず要確認)・`/run` (ビルトイン) / **~/.claude/skills に newrelic 未リンク** (symlink 完全性の検証手段が無い)
4. **昇格の仕組み不在**: project memory はプロジェクト毎に隔離 (`~/.claude/projects/<dir>/memory/`)。自己点検 hook は elm-inc の `settings.local.json` にのみ存在し、他プロジェクトで発火しない・git 管理外

## 3. 外部調査の要点 (2026-07 時点)

- 公式: CLAUDE.md は永続指示・**200 行以下 + ruthless pruning** (基準: この指示がないと Claude が誤るか)。`.claude/rules/` の paths スコープ + **symlink 共有を公式明記**。auto memory と役割分離 ([memory](https://code.claude.com/docs/en/memory) / [best-practices](https://code.claude.com/docs/en/best-practices)、2026-07-23 参照)
- skills の team primitive 化 (git 配布・internal marketplace)。curated skills で agent pass rate **+16.2pp**、一方 community skills の **36% に prompt injection 検出** ([Agent Skills Ecosystem Report 2026, agentman.ai](https://agentman.ai/blog/agent-skills-ecosystem-report-2026/)、2026-07-23 参照) → 外部 skill/MCP ガバナンス必須
- spec-driven development: 仕様 + **実行可能な pass/fail チェック**を渡し検証ループを自走させる ([code.claude.com/best-practices](https://code.claude.com/docs/en/best-practices#give-claude-a-way-to-verify-its-work))
- OWASP Agentic Top 10 (2025-12): Agent Goal Hijacking が 1 位。permission + sandbox の 2 層ゲート推奨
- Agent Teams / MDM managed-settings は 1 人体制では過剰 → 見送り

## 4. 設計

### 4.1 CLAUDE.md のあるべき姿 (~150 行、≤200 行を CI で強制)

残す基準 = 「個別スキル・ドキュメントから導けない横断的判断基準」+「**操作時に効く安全原則**」。

構成: ①冒頭 (RULES.md 読込 + 索引宣言) / ②モデル選択・コスト規律 / ③オーケストレーション基本形 (圧縮) / ④ワークフロー (spec-driven 強化) / ⑤worktree・Linear・Notion・docs 索引 (現状維持) / ⑥ドメイン固有 = 1-3 行索引 + 安全原則 / ⑦ナレッジ昇格ルール (~5 行) / ⑧リポ運用。

**残す安全原則 (6 項目)** — 圧縮後も本文に明記:

1. **New Relic**: 案件=別顧客テナント。profile 常時明示・fail-closed。global MCP 登録禁止・`.newrelic-profile`/`.envrc` commit 禁止・鍵を argv に出さない → 詳細 skill/ADR-0008
2. **Figma**: 生 curl 禁止 (レート制御は /figma 経由)。PAT/OAuth 2 経路を混同しない
3. **Fable コスト規律**: 1 タスク 1 委譲・委譲前宣言・statusline 監視 (課金ボックスに統合)
4. **vLLM**: 停止が既定状態。「停止しているので中止」は誤り
5. **サブエージェント規律**: 並列最大 5・探索は Haiku
6. **ADR**: 採択済みは書き換えず Supersede

**降格先の使い分け基準** (Fable レビュー H2 — 本設計の要):

| 種別 | 置き場所 | 理由 |
|---|---|---|
| ファイル編集がトリガーの規約 | `.claude/rules/` (paths) | paths rules は該当ファイル読込時のみロード |
| **操作時の安全原則** | CLAUDE.md 残置 + **permissions で機械的 enforcement** | ファイルを読まずコマンドを打つ瞬間に必要。paths rules では守れない |
| ツール横断 (Codex too) の安全原則 | RULES.md | Codex は CLAUDE.md を読まない |
| ニッチ hw 系スキル (rigol/webcam/atopile/mosh) | `disable-model-invocation: true` | description 常時ロードから除外。索引にも載せない |

- skill description に予算制: **≤160 字・「いつ使うか」必須** (skill-authoring.md に追記)。CLAUDE.md 刈り込みがスキル側肥大で相殺されるのを防ぐ
- `~/.claude/rules/` (ユーザーレベル rules 層) は**使わない**: L1 は CLAUDE.md/RULES.md symlink に一元化し層を増やさない

### 4.2 3 層ナレッジアーキテクチャ

```
L1 判断基準 (agent-rules 本体 → symlink で全プロジェクト常時適用)
   CLAUDE.md (~150 行) / RULES.md / 安全原則 / permissions ベースライン
L2 再利用資産 (プロジェクト初期化時に展開)
   templates/ (docs 構造・settings 雛形・CI) + .claude/rules/ (stack 別) + skills
   → /project-init が一括展開
L3 プロジェクト固有
   各リポ CLAUDE.md + project memory
```

- **L2 の stack 別 rules は初期 0 個で成立する設計**: 昇格パイプライン (4.3) が埋める。中身のないルールの先行量産はしない
- **/project-init は /docs-init を内部で呼ぶ上位オーケストレータ**。docs-init は現行契約 (ADR-0009: メタ上書き / 中身保持) のまま併存
- **symlink vs コピー基準**: プロジェクト repo にコミットされ他環境 (CI・他マシン・clone) で解決される必要があるもの = **コピー** (再実行時 diff 提示で drift 管理) / ユーザーローカル (~/.claude 配下) = **symlink** (git は symlink をパス文字列で保存するため、ホーム配下を指す symlink のコミットは他環境で確実に壊れる)

### 4.3 ナレッジ昇格パイプライン (台帳照合型「2 回目ルール」)

project memory はプロジェクト毎に隔離され「別プロジェクトで 2 回目」を記憶では検知できない。よって**中央台帳への照合**で検知する:

1. **中央台帳**: `docs/notes/promotion-candidates.md` (1 行 1 候補: 日付 / プロジェクト / パターン概要 / 回数)。横断再利用しそうな設計判断・パターンに触れたら **1 回目の時点で候補記録**。記録時に既存候補と照合し、一致 (=2 回目) したらその場で昇格タスク化
   - **台帳の書き込み運用** (redteam 指摘の補強): 他プロジェクトのセッションは agent-rules checkout の台帳ファイルへ**直接追記 (uncommitted でよい)** — ローカル即時反映が照合の本質で、コミットは昇格 PR 時にまとめて行う。追記専用・1 行 1 候補・機械パースしない (照合は Claude が読んで行う) ため、単一マシン運用では conflict・パース破綻は実質発生しない。/status が未コミット台帳エントリも表示する
2. **ユーザーレベル Stop hook** (`~/.claude/settings.json`): セッション終了時の自己点検に「昇格候補の台帳追記・照合」を含める。hook 定義は `templates/claude-settings/` で配布、**適用は手動 + doctor で差分検査** (JSON 自動 merge は既存設定破壊リスクがあるためしない)。現行 elm-inc `settings.local.json` の hook はユーザーレベルへ昇格
3. **/status に候補サマリ表示** (候補数・2 回到達分): 点検が省略されても週次で目に入る回収経路
4. **昇格先判定**: いつ何を使うかの判断 → CLAUDE.md / ツール横断の安全原則 → RULES.md / ファイル種別・stack 規約 → .claude/rules (paths) / 手順 → skill / 初期構造 → template / なぜ → ADR
5. **逆方向 (降格)**: 四半期見直しで参照されなかった行を降格・削除 (ADR-0011 の `review_by` を流用)。L1/L2 の単調増加を防ぐ。**トリガー**: 台帳ヘッダに `review_by` 日付を持たせ、期限超過を /status が警告する (redteam 指摘 M8: カレンダー任せでは実行されない)

### 4.4 トレンド取り込み

- **templates/claude-settings/ 新設**: (a) permissions deny/ask (生 API curl [figma/newrelic]・`rm -rf`・force push・**~/CLAUDE.md や ~/.claude 配下を対象にした `ln -sf` 等の symlink 再設定** [redteam M10])、(b) ユーザーレベル hooks (SessionStart /status 促し・Stop 自己点検 + 昇格点検) の 2 部構成。**「散文ルールの刈り込みで失う抑止力を permissions で置き換える」が本設計の柱**
- **settings の適用モデル (redteam C3 を受けて改訂)**: 初回適用は手動 (テンプレ提示 + ユーザー確認) を維持しつつ、以降の drift は **doctor `--fix` による安全な差分マージ** で解消する — **新規キーのみ追加・既存キーは決して上書きしない (add-only)・衝突は表示して skip**。install.sh 実行時と /status がテンプレとの差分を検知して通知する。純手動 (Fable A6) では新しい deny ルールが恒久的に未適用となり安全レベルが時間とともに劣化するため、「盲目的 auto-merge はしない」の原則は保ったまま add-only に限って自動化する
- **skill/MCP 監査チェックリスト** (redteam H5: 「audit なし導入禁止」の audit を定義): ① SKILL.md/ツール定義の全文読了 (外部送信・自己改変・権限昇格・難読化がないこと) ② 同梱スクリプトの実行内容確認 ③ allowed-tools の最小性 ④ 出所の確認 (公式 marketplace 優先)。docs/setup に checklist として配置し RULES.md から参照
- **design テンプレ必須欄**: 受け入れ基準 (箇条書き) + **各基準の pass/fail を確認する実行可能コマンド/手順** (機械実行不能なら理由)
- RULES.md に「サードパーティ skill/MCP は audit なしで導入しない」を追加 (Codex にも適用)
- **CI lint 恒久化**: CLAUDE.md ↔ skills/ 相互参照チェック + 行数 ≤200 hard-fail (ADR-0011 Layer 2 の CI 基盤に追加)

## 5. 実行計画

| # | 作業 | 状態 |
|---|---|---|
| ① | Fable 課金の事実修正 PR | **完了** — [PR #19](https://github.com/elm-inc/agent-rules/pull/19) |
| ② | 本 design doc + /deepseek-redteam + ADR-0013 | 本ブランチ |
| ③a | 移設先追加 PR (rules/SKILL.md/docs への転記を先に merge) | 未着手。~/CLAUDE.md は symlink で**即・全セッション適用**のため、「どこにも情報がない瞬間」を作らない順序が必須 |
| ③b | 刈り込み PR (削除 + 削除行→移設先の対応表添付 + **新セッションで安全原則クイズ実証**後に merge)。**③a と同一作業日に連続 merge** (redteam H4: stall しても情報は重複保持で喪失しないが、凍結リスクを時間制約で抑える) | 未着手 |
| ④ | /project-init + templates/claude-settings (doctor `--check`/`--fix` 含む) + ニッチスキル disable-model-invocation + CI lint + 監査チェックリスト | 未着手 |

**ロールバック手順** (redteam H6): agent-rules は symlink 配布のため、事故時は **main への revert PR で全セッションに即時波及** — 配布の即時性がそのままロールバックの即時性になる。中間状態は worktree 規律 (メインワークツリーは常に main・クリーン) が前提で、doctor がこの状態 (`git -C ~/repos/.../agent-rules branch --show-current` = main かつクリーン) も検査する (redteam C2a)。

## 6. 受け入れ基準 (各基準に検証手段)

| # | 基準 | 検証手段 |
|---|---|---|
| 1 | CLAUDE.md ≤ 200 行 (目標 150) | `wc -l CLAUDE.md` を CI で hard-fail |
| 2 | 刈り込みの全削除行に移設先がある | ③b PR に「削除行 → 移設先」対応表を添付。CI lint (相互参照) green |
| 3 | 新規空リポで /project-init 1 回で L2 展開が完結 | 実行後 `git status` が生成物のみを示し手作業残タスク 0 (④で実証) |
| 4 | symlink 完全性 | `install.sh --check` が repo skills/ 全ディレクトリの解決済み symlink を機械確認 (現在 newrelic が未リンク = 再現手順あり) |
| 5 | 昇格 hook が全プロジェクトで発火 | ユーザーレベル settings 適用後、agent-rules 以外のリポで新規セッションを起動し Stop hook 発火を 1 回実証 |
| 6 | 課金記述が公式情報と一致 | ADR-0010 改訂の出典 URL を照合 (PR #19 で完了) |
| 7 | 常時ロードコンテキストの削減を定量記録 | 刈り込み前後で新規セッションの context 使用量を記録し本 doc に追記 |
| 8 | 刈り込み後も安全原則が機能 | ③b の worktree ブランチ上で新規セッションに安全原則クイズ (例: NR の別顧客クエリ時に何を確認するか) → 6 原則正答 |

## 7. リスクと対策

| リスク | 対策 |
|---|---|
| 刈り込みで安全原則が失われ事故 | 6 原則の残置リスト明文化 + permissions enforcement + クイズ実証 (基準 8) |
| 昇格パイプラインの形骸化 | 台帳照合型 (記憶に依存しない) + hook + /status 表示の 3 経路。台帳 `review_by` 期限超過を /status が警告 |
| symlink 即時配布による中間状態 | ③a→③b の 2 段 PR + 同一作業日連続 merge。メインワークツリーは常に main・クリーン (worktree 規律) を doctor が検査 |
| settings drift (deny ルール未適用の恒久化) | doctor `--fix` の add-only 差分マージ + install.sh / /status の差分通知。既存キーは上書きしない |
| symlink の差し替え・破損 | doctor が解決先の検証 (期待 target との一致) を機械確認。~/.claude 配下への `ln -sf` を permissions で ask 化。※ ホスト自体の侵害は本設計のスコープ外 (その場合 settings も改変可能) |
| 事故コミットの全セッション波及 | main への revert PR で即時ロールバック (上記手順) |
| L1/L2 の単調増加 (再肥大化) | 行数 CI hard-fail + 四半期降格見直し |

## 8. redteam 統合記録 (2026-07-24, DeepSeek-R1)

指摘 10 件 (Critical 3 / High 3 / Medium 4)。採否と反映先:

| # | 指摘 (致命度) | 採否 | 反映 / 理由 |
|---|---|---|---|
| C1 | 昇格パイプラインの形骸化 (人間の継続的誠実さへの依存) | **採用 (補強)** | 検知は hook (Claude が記録主体)・/status・台帳照合の 3 経路で人の記憶に依存しない設計が既にあるが、四半期見直しのトリガー不在 (M8) を /status の `review_by` 期限警告で補強 (§4.3-5) |
| C2a | agent-rules のブランチ切替が全セッションへ即時伝搬 | **採用** | worktree 規律 (メインワークツリーは常に main・クリーン) を前提として明文化し、doctor の検査項目に追加 (§5 ロールバック) |
| C2b | symlink 差し替え攻撃 | **一部採用** | `~/.claude` 配下対象の `ln -sf` を permissions で ask 化 + doctor が解決先を検証 (§4.4, §7)。ホスト侵害自体はスコープ外と明記 (侵害下では settings も改変可能で、この層では防御不能) |
| C3 | settings 手動適用の恒久的漏れ → 差分自動マージ導入 | **採用 (修正)** | 「もし 1 点だけ直すなら」の指摘。初回手動は維持しつつ、以降の drift は doctor `--fix` の **add-only マージ** (新規キーのみ・上書きなし・衝突 skip + 通知) で解消 (§4.4)。Fable A6 の「盲目的 auto-merge 禁止」と両立 |
| H4 | ③a/③b 分離による情報空白 | **一部採用 + 反論** | 空白期間の実態は「重複保持」であり**情報喪失は起きない** (指摘は誤認)。ただし ③b 凍結リスクは実在するため「同一作業日に連続 merge」の時間制約を追加 (§5) |
| H5 | サードパーティ skill の audit 基準未定義 | **採用** | 4 項目の監査チェックリストを定義し docs/setup 配置・RULES.md から参照 (§4.4) |
| H6 | ロールバック手順未定義 | **採用** | main への revert PR = 即時全セッション波及、を手順として明文化 (§5) |
| M7 | symlink 修復の自動化欠如 | **採用** | doctor `--fix` のスコープに再リンクを含める (§4.4) |
| M9 | 台帳の同時編集破損 | **反論 (運用明記で対応)** | 追記専用・1 行 1 候補・機械パースなし・単一マシンのため実質発生しない。書き込み運用 (uncommitted 追記 + 昇格 PR でコミット) を §4.3-1 に明記 |
| M10 | permissions に symlink 再設定が未指定 | **採用** | deny/ask リストに追加 (§4.4) |

不採用 (Low): 「200 行ちょうどの境界値」(lint は ≤200 で境界含む)、「プロジェクト名の特殊文字」(台帳は機械パースしない)。redteam の代替案のうち「動的解決」「ML 自動検出」は redteam 自身の評価どおり不採用、「差分自動マージ」は上記 C3 の形で採用。
