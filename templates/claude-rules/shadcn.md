---
paths:
  - "components.json"
  - "**/*.{tsx,jsx}"
  - "**/components/ui/**"
  - "**/tailwind.config.{ts,js}"
  - "**/app/globals.css"
---

# shadcn/ui 規約 (フロントエンド案件)

このファイルは **agent-rules の雛形** (`templates/claude-rules/shadcn.md`)。shadcn を使うプロジェクトに `/project-init` 等でコピーして `.claude/rules/shadcn.md` として配置する (symlink でなくコピー — 他環境で解決される必要があるため)。導入・全体像: `docs/setup/shadcn.md`。

## コンポーネントの追加・更新

- コンポーネントは**手でコピーせず `shadcn add <name>` で追加**する (`-y` で確認スキップ、`--overwrite` は差分確認後)。MCP が使えるなら `get_item` → `add_item` 経由
- 更新前に **`shadcn add <name> --diff`** でローカル改変との差分を確認 (提案→確認→実行)。破壊的上書きをいきなりしない
- **`components.json` が単一ソース** (framework / aliases / installed / registries)。手で矛盾させない。設定は `shadcn info --json` で参照

## primitives を直接いじらない

- `components/ui/*` (生成された primitives) は**直接改変しない**。振る舞い変更は**ラッパーコンポーネントを別途作る**か、theme / CSS 変数で行う (再生成で上書きされるため)
- 見た目のカスタムは **CSS 変数 (OKLCH) / theme preset** で。個別コンポーネントにハードコードした色・radius を撒かない

## Tailwind v4 / RSC

- **Tailwind v4** 構文を使う (`@theme` / CSS-first)。v3 の設定を混ぜない
- Next.js App Router は `components.json` の **`"rsc": true`**。Client 境界 (`"use client"`) を必要な最小範囲に留める
- アニメーションは `tw-animate-css` (v4 既定)

## house-style (量産感の回避)

- shadcn 既定のまま量産しない。**house-style は `/design-voice` で抽出したプロファイルを theme preset / `registry:base` に落として適用**する (docs/setup/shadcn.md §4)
- **定常レギュレーションは design-registry (`@elm/base`) を単一ソースに取り込む** (`shadcn add @elm/base`)。この案件では**差分 (accent 色・フォント等) だけ**を theme preset で重ねる。base を案件内で勝手に再定義しない (ADR-0014・docs/setup/shadcn.md §5)
- 新規 UI は「`@elm/base` (レギュレーション) + 案件差分」を前提に生成する
- **レイアウト・型・余白の house 規約は `elm-design-layout.md` を参照** (`@elm/app-shell` を土台にし、見出し/本文/余白はトークン。近いレイアウトを毎回同じ構造で出す係)

## 認証・秘匿

- private/社内レジストリのトークンは `components.json` に直書きせず **`.env.local` から env 展開** (`${REGISTRY_TOKEN}`)。値をコミットしない
- `.mcp.json` にトークンを埋めない
