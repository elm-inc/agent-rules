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

> ✅ **稼働中**: [`elm-inc/design-registry`](https://github.com/elm-inc/design-registry) (public) が GitHub Pages で配信中 (`https://elm-inc.github.io/design-registry/r/{name}.json`)。item:
> - **`base`** (`registry:theme` + `extends:none`) — 色 (OKLCH light/dark, 由来 shadcn/create preset `b1ZOy0qg4` = indigo/zinc) + **型 scale** (`--text-h1` 等 + `@layer base` の h1..p 既定) + **余白** (`--gutter`/`--section-gap`/`--page-max`) + **sidebar 寸法** (`--app-sidebar-width` 等)
> - **`app-shell`** (`registry:component`) — Next.js App Router 想定の sidebar+header+content 骨格。`add @elm/app-shell` で shadcn sidebar 等も自動取り込み
> - **`theme-example`** (preset 雛形) — 案件のブランド差分を base の上に重ねる例
>
> `add @elm/base` → `add @elm/app-shell` → preset の順、および `app-shell` が base トークンを消費することを実地検証済み。**性格 (書体の個性・余白リズム)** は `/design-voice` 層で足す。

| 層 | 中身 | 変更頻度 |
|---|---|---|
| **base (レギュレーション)** | CSS 変数 (OKLCH light/dark)・design tokens (radius/spacing/shadow/typography)・global styles・a11y/motion 規約 | 稀 (定常) |
| **theme preset (ブランド変種)** | 名前付きテーマ。視覚設定のみ配布 (再インストール不要) | 時々 |
| **house components** (任意) | house-style 済みの Button/Form/Layout 等 | 随時 |

名前空間 (`@elm` 等) + **version tag で pin**。案件側は差分だけ:

```jsonc
// 案件の components.json
{ "registries": { "@elm": "https://elm-inc.github.io/design-registry/r/{name}.json" } }
```
```bash
shadcn add @elm/base            # 定常レギュレーション (色・型・余白・sidebar 寸法) を必ず取り込む
shadcn add @elm/app-shell       # レイアウト骨格 (sidebar+header+content)。近いレイアウトはこれを土台に
# その上に案件の差分 (accent 色・フォント等) を theme preset で重ねる
```

- **「必ず反映」の機械保証**: base を pin し、`shadcn add @elm/base --diff` が空になることを **CI で検査**して drift を防ぐ (agent-rules の `install.sh --check` / lint と同じ発想)
- **AI への指示の一貫性**: 案件に **`.claude/rules/elm-design-layout.md`** (雛形: `templates/claude-rules/`) を配ると、「サイドバー付き管理画面を作って」等の指示が毎回 `AppShell` + base トークンで出力される (`/shadcn` step 4 が自動配置)。「base は `@elm` にある。差分だけ」で済む
- **性格**は `/design-voice` で抽出して theme preset に落とす。レギュレーション (共通の構造・型・余白) と個性 (性格) を層分けする

### 5.1 managed / owned 分離 (カスタムを base 更新から守る)

`@elm/base` は今後も更新される。案件で「一部だけカスタム」する際に **base (managed) を直接書き換えると、次の `add @elm/base` でカスタムが消える**。これを構造的に防ぐ:

| 層 | 実体 | `add` で | カスタムはここ |
|---|---|---|---|
| **managed** | `globals.css` の base 域・`components/ui/*`・registry 由来 | 再生成・上書き | ❌ 書かない |
| **owned** | `app/theme.overrides.css`・ラッパー/案件コンポーネント | 触られない | ✅ ここに書く |

- **トークン上書き** → `app/theme.overrides.css` に `:root{}`/`.dark{}` で書き、root `layout.tsx` で **`globals.css` の直後に import** (cascade で後勝ち)。base 更新は managed だけ新しくし、owned は維持 = **「カスタム維持 × それ以外は base 反映」**が成立
- **コンポーネント** → `components/ui/*` を編集せずラッパー/案件コンポーネントで
- **3 手で徹底** (`/shadcn` が配線): ① rule `elm-design-overrides.md` (managed/owned を明文化) ② PreToolUse ガード `.claude/hooks/design-guard.sh` (managed への直接編集を `ask` で止める) ③ drift CI (`templates/ci/design-registry-drift.yml`、`--diff` が空でないと fail)。散文だけに頼らず機械で強制する。根拠: ADR-0014

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
