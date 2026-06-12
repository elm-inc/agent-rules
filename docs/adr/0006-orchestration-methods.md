# ADR-0006: オーケストレーションの推奨方式を採り入れる (Spec 駆動 / 役割特化サブエージェント / ファンアウト規律)

## ステータス

採択 (2026-06-11)

ADR-0001 (multi-LLM 開発ワークフロー) を土台に、2026 年時点の業界事例・公式機能を踏まえて運用方式を補強する。役割分担そのものは ADR-0001 を維持し、その上に「方式」を足す。

## 文脈

CLAUDE.md に標準オーケストレーション (Opus 司令塔 + Fable 両端 + 異種ベンダー横やり + Qwen/機械の床) を明文化した。この基本形は業界が 2026 に収束した **Supervisor パターン** (coder + researcher + reviewer を 1 段で束ねる) と一致する。直近事例の調査で、ここに足すと効果が高い「方式」が 3 つ見えた:

1. **Spec-Driven Development**: 実装前に仕様を起草・レビューし、その仕様を「契約」にして実装 → 適合性 (conformance) を検証するループ。出力が意図からズレる prompt drift を防ぐ。ICSE 2026 の査読研究で、アーキテクチャ文書を与えると正しさ・適合性・モジュール性が有意に向上すると報告。
2. **役割特化サブエージェント**: 公式が「探索/検索は Haiku に振ってコスト制御」「1 エージェント 1 責務」「lead の指示文の質が協調信頼性を決める」を明示。
3. **ファンアウトのコスト規律**: サブエージェント多用は約 7 倍トークン。並列は 3-5 が sweet spot、>10 は無益。Max プランでは特に効く。

## 決定

### 1. Spec 駆動 + 適合性チェックを設計フローに組み込む

`docs/design` の各 spec / implementation-plan に**検証可能な受け入れ基準** (完了の定義・制約・非対象) を必ず書く。実装後、マージ前に `/gemini-review` で「受け入れ基準と ADR 制約への適合」を確認する 1 段を標準フローに加える。テンプレ: `templates/docs/design/README.md`。

### 2. 役割特化サブエージェントを `agents/` で配布する

agent-rules に `agents/` を新設し、`install.sh` が `~/.claude/agents/*` へ symlink 同期する (skills と同方式)。初期セットは探索・調査の「床」を安価に固める 2 つ:

| サブエージェント | model | tools | 役割 |
|---|---|---|---|
| `explorer` | haiku | Read, Grep, Glob | コード探索・位置特定・地図化。Bash を持たせず read-only を構造的に強制。司令塔の文脈とコストを節約 |
| `researcher` | haiku | WebSearch, WebFetch, Read | 外部調査 (Web/ドキュメント) → 出典付き要約 (read-only) |

難所実装は既存の `/fable-task`、レビューは既存の多層スキルが担うため、サブエージェントは重複を避けて「探索・調査」に絞る。スキル本体は inherit のまま下げない (ADR の別判断と整合) が、**探索専用サブエージェントは Haiku に振るのが定石**。

> 補足 (2026-06-12 レビュー反映): agent frontmatter は Bash のサブコマンドを制限できないため、explorer の "read-only" を宣言で済ませず **Bash 自体を tools から外して構造的に強制**した (検索の大半は Read/Grep/Glob で賄える)。`git log` 等の文脈付き検索が必要になった場合のみ本体/別エージェントで行う。

### 3. ファンアウトのコスト規律を明文化する

CLAUDE.md の標準オーケストレーションに「並列分解は最大 5、>10 は無益、探索は Haiku、Fable は数少ない難所のみ」を運用規律として記載する。

### 4. 実行時方式はノートに留める (静的ファイル化しない)

決定論的ファンアウト (Workflow: finders→敵対的検証→統合 / loop-until-dry) と Background Agents / Agent Teams は「実行時にどう動かすか」の方式であり、設定ファイルにはしない。CLAUDE.md に運用ノートとして触れ、巨大タスクや協調が要る時に明示的に使う。

## 根拠

- **prompt drift 抑制**: 受け入れ基準を契約にし適合性を検証することで、大規模タスクで出力が意図からズレるのを防ぐ
- **コスト×品質**: 探索・調査を Haiku サブエージェントに逃がし、司令塔 (Opus) の高コスト文脈を温存。Fable は両端の要所のみ
- **再利用性**: 役割特化サブエージェントを agent-rules で配布し、全マシンで `git pull` + `install.sh` で同期

## トレードオフ / 不採用

- **Swarm (数百エージェント) は不採用**: 現状の規模に過剰
- **reviewer サブエージェントは作らない**: 多層レビュースキル (Qwen/Codex/Gemini/Fable) と重複するため
- サブエージェント数を増やしすぎない (lead の指示品質と 1 責務原則を優先)

## 影響範囲

- 追加: `agents/explorer.md`, `agents/researcher.md`, `docs/adr/0006`
- 変更: `install.sh` (agents 同期), `templates/docs/design/README.md` (受け入れ基準), `CLAUDE.md` (標準オーケストレーション拡張)

## 関連

- ADR-0001 (multi-LLM ワークフロー) — 役割分担は維持、方式を補強
- [CLAUDE.md](../../CLAUDE.md) §標準オーケストレーション
