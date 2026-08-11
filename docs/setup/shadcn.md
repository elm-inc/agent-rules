# shadcn/ui を AI 開発に取り込む

shadcn/ui は「コピペ配布 (依存でなくソース)・Radix/Base UI + Tailwind・CLI + レジストリ」という設計で、**AI エージェント駆動開発と相性が良い**。取り込みは**自作せず公式のものを配線する**のが基本 — shadcn 公式が **MCP サーバ**と **Claude Code 用スキル**を提供しているため、agent-rules で `/shadcn` スキルを一から書く必要はない。

> **バージョン前提**: 本文は 2026-08 時点。shadcn CLI **v4+** (2026-03〜) を最小要件とし、**Tailwind v4** / Base UI 既定 / RSC を前提にする。コマンド名・フラグは版で変わるため、実行前に公式 (`https://ui.shadcn.com/docs`) で最新を確認する。

## 3 層で取り込む

| 層 | 何を | agent-rules での扱い |
|---|---|---|
| **MCP** | Claude Code から直接コンポーネント検索・追加・レジストリ参照 | **per-project** で `.mcp.json` 生成 (global 登録しない = New Relic MCP と同じ流儀) |
| **公式スキル** | `components.json` を読んで project-aware にする Agent Skill | 導入前に skill-audit-checklist で一度監査してから採用 |
| **agent-rules 独自の薄い層** | Tailwind/RSC/components.json 規約 + house-style | `templates/claude-rules/shadcn.md` (paths スコープ) + design-voice 連結 |

## 1. MCP サーバ (per-project)

プロジェクトのルートで:

```bash
pnpm dlx shadcn@latest mcp init --client claude
```

これが `.mcp.json` を生成する (中身は概ね次の形):

```json
{ "mcpServers": { "shadcn": { "command": "npx", "args": ["shadcn@latest", "mcp"] } } }
```

- **global 登録しない**。プロジェクトごとに `.mcp.json` を持つ (New Relic MCP と同型。付け忘れ = 未接続で fail-closed)
- Claude Code の `/mcp` で接続状態を確認できる
- 提供ツール (確認済): `get_init_instructions` / `execute_init` / `get_items` / `get_item` / `add_item` / `execute_add` / `get_blocks`
- `.mcp.json` に**認証トークンを直書きしない** (レジストリ認証は §4 の env 展開で)

## 2. 公式 Claude Code スキル

```bash
pnpm dlx skills add shadcn/ui
# または: /plugin install shadcn@community
```

- `components.json` を自動で読み、CLI 全コマンド/フラグ・Radix/Base UI パターン・レジストリ workflow を Claude に持たせる
- **サードパーティ skill 導入原則を適用**: 公式であっても `docs/setup/skill-audit-checklist.md` で一度監査してから入れる (community skills の約 36% に prompt injection という調査があるため。公式は低リスクだが確認は省かない)。バージョンは pin する

## 3. CLI (AI 自動化向け)

`components.json` がマシン可読な単一ソース (framework / aliases / installed components / icon library / registries)。`shadcn info --json` で AI に context 注入できる。

| コマンド | 用途 | AI 向けフラグ |
|---|---|---|
| `shadcn init --template <next\|vite\|react-router\|astro>` | 初期化 | |
| `shadcn add <name>` | コンポーネント追加 | `-y` (確認スキップ) / `--overwrite` |
| `shadcn search` / `shadcn view --json` | 検索 / 詳細 (機械可読) | `--json` |
| `shadcn info --json` | プロジェクト設定を AI context へ | `--json` |
| `shadcn add ... --dry-run` / `--diff` | **検証ループ用** (提案→確認→実行) | v4+ |

> **検証ループとの接続**: `--dry-run` / `--diff` で「AI が提案 → 差分確認 → 実行」を回せる。本リポの「実行して確かめる」文化とそのまま噛み合う。

## 4. house-style (design-voice との連結)

shadcn 既定のまま使うと「量産感」が出る。これは **`/design-voice` (ADR-0004) が解く問題そのもの**。shadcn 側の受け皿は 2 つ:

- **custom registry の `registry:base` item** — `registry.json` に light/dark の CSS 変数 (OKLCH 推奨) を定義し一括配布
- **theme preset** — 視覚設定のみを配布 (コンポーネント再インストール不要)。`shadcn preset decode` / `apply`

連結の流れ: **design-voice でプロファイル (パレット・タイポ・radius 等) を抽出 → shadcn の design tokens / theme preset として表現 → custom registry で配布**。これで「house-style を効かせた shadcn コンポーネント」を AI に生成させられる。

private / 社内レジストリの認証は `components.json` の `registries` で env 展開:

```json
{
  "registries": {
    "@acme": { "url": "https://registry.example.com/{name}.json",
               "headers": { "Authorization": "Bearer ${REGISTRY_TOKEN}" } }
  }
}
```

トークンは `.env.local` から読ませ、**値を直書きしない** (New Relic の鍵運用と同型)。

## 5. 案件横断のデザインレギュレーション (design-registry 単一ソース)

案件ごとにデザインは違っても、**基本方針・レギュレーション (トークン・テーマ骨格・a11y/motion 規約) は 1 箇所に定常配置し、案件では差分だけを指示する**のが良い。これは custom registry の `registry:base` で実現できる。**専用リポ `design-registry` を単一ソース**にするのを推奨 (agent-rules の「ルール単一ソース」のデザイン版)。根拠: [`ADR-0014`](../adr/0014-shadcn-design-registry.md)。雛形: `templates/design-registry/`。

| 層 | 中身 | 変更頻度 |
|---|---|---|
| **base (レギュレーション)** | CSS 変数 (OKLCH light/dark)・design tokens (radius/spacing/shadow/typography)・global styles・a11y/motion 規約 | 稀 (定常) |
| **theme preset (ブランド変種)** | 名前付きテーマ。視覚設定のみ配布 (再インストール不要) | 時々 |
| **house components** (任意) | house-style 済みの Button/Form/Layout 等 | 随時 |

名前空間 (`@elm` 等) + **version tag で pin**。案件側は差分だけ:

```jsonc
// 案件の components.json
{ "registries": { "@elm": "https://.../{name}.json" } }
```
```bash
shadcn add @elm/base            # 定常レギュレーションを必ず取り込む
# その上に案件の差分 (accent 色・フォント等) を theme preset で重ねる
```

- **「必ず反映」の機械保証**: base を pin し、`shadcn add @elm/base --diff` が空になることを **CI で検査**して drift を防ぐ (agent-rules の `install.sh --check` / lint と同じ発想)
- **AI への指示**は「base は `@elm` にある。この案件は差分 (accent=X, font=Y) だけ」で済む。`/design-voice` で抽出した個性を theme preset に落として差分にする

## 6. 落とし穴・要確認

- **Tailwind v4 / RSC**: 新規は Base UI 既定 + `tw-animate-css`。Next.js App Router は `components.json` の `"rsc": true`
- **バージョン差**: v3 系プロジェクトに v4 CLI を混ぜない。`shadcn init --template` の対応フレームワークは版で増減する
- **未確認 (依存しない)**: サードパーティ `shadcn-registry-mcp`、`registry:hook` の詳細スキーマ、複数 custom registry の同時利用挙動 — 使う場合は都度確認
- **補完層**: アニメーション系は Magic UI 等が補完。UI プロトタイプ生成は v0 (生成コードは shadcn プロジェクトに drop-in 可)

## 7. 新規フロントエンド案件での導入手順 (まとめ)

```bash
# 1. 足場 (agent-rules L2)
/project-init                                   # docs/rules/settings 雛形
# 2. shadcn 初期化 + MCP
pnpm dlx shadcn@latest init --template next
pnpm dlx shadcn@latest mcp init --client claude # .mcp.json (per-project)
# 3. 公式スキル (監査後)
pnpm dlx skills add shadcn/ui
# 4. house-style
/design-voice extract <参照>                    # → theme preset / registry:base に落とす
# 5. .claude/rules/shadcn.md を配置 (templates/claude-rules/shadcn.md)
```

## 出典 (2026-08-11 参照)

- [MCP Server - shadcn/ui](https://ui.shadcn.com/docs/mcp) / [CLI](https://ui.shadcn.com/docs/cli) / [Claude Code Skills](https://ui.shadcn.com/docs/skills)
- [Registry: Getting Started](https://ui.shadcn.com/docs/registry/getting-started) / [Authentication](https://ui.shadcn.com/docs/registry/authentication)
- [Tailwind v4](https://ui.shadcn.com/docs/tailwind-v4) / [CLI v4 changelog](https://ui.shadcn.com/docs/changelog/2026-03-cli-v4)
