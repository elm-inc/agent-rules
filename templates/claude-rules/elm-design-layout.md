---
paths:
  - "**/*.{tsx,jsx}"
  - "**/app/**"
  - "**/components/**"
  - "**/app/globals.css"
  - "components.json"
---

# elm レイアウト・タイポグラフィ規約 (design-registry 単一ソース)

このファイルは **agent-rules の雛形** (`templates/claude-rules/elm-design-layout.md`)。フロントエンド案件に `/shadcn` 等でコピーして `.claude/rules/elm-design-layout.md` として配置する (symlink でなくコピー)。目的は **複数案件で近いレイアウトを指示したときに、毎回同じ構造・型・余白で出力される**こと。値の単一ソースは design-registry (`@elm/*`)。使い方全体: `docs/setup/shadcn.md` §5 / 根拠: ADR-0014。

> このルールは shadcn の使い方 (`shadcn.md`) と対。あちらは「どう add / いじらないか」、こちらは「house のレイアウト・型・余白をどう使うか」。

## 前提: `@elm/base` と `@elm/app-shell` を取り込む

```bash
pnpm dlx shadcn@latest add @elm/base        # トークン (色・型・余白・sidebar 寸法) + 要素既定
pnpm dlx shadcn@latest add @elm/app-shell   # レイアウト骨格 (sidebar+header+content)。sidebar 等も自動
```

これらが単一ソース。**案件で骨格・トークンを再実装しない**。

## レイアウトは `AppShell` を使う (手組みしない)

- 管理画面・ダッシュボード等の「sidebar + header + content」は **`<AppShell>` を使う**。sidebar/header/content を個別に手組みしない
- 案件が触るのは **2 箇所だけ**: `components/app-sidebar.tsx` のナビ項目 (ロゴ・メニュー・ユーザー) と、`<AppShell header={…}>` に渡すヘッダー内容
- content 幅・余白は AppShell が `--page-max` / `--gutter` / `--section-gap` で規定済み。ページ側で max-width や padding を勝手に付け直さない
- sidebar 幅は `--app-sidebar-width`、`collapsible="icon"` が house 既定。変えない

```tsx
// app/(app)/layout.tsx — Next.js App Router
import { AppShell } from "@/components/app-shell"
export default function Layout({ children }: { children: React.ReactNode }) {
  return <AppShell header={<PageTitle />}>{children}</AppShell>
}
```

## タイポグラフィはトークン/要素既定に従う

- **見出しは `<h1>`〜`<h4>`** をそのまま使う (base の `@layer base` で house サイズ・weight・tracking が既に効く)。または `text-h1`〜`text-h4` ユーティリティ
- **本文は `<p>` / `text-body`、注釈は `<small>` / `text-small`**
- **font-size・line-height を px やハードコードで指定しない** (`text-[18px]` 等を撒かない)。必要なスケールが無ければ base 側 (design-registry) に追加してから使う
- フォントは base の `--font-sans`。個別に別フォントを差し込まない

## 余白・寸法はトークンで

- ページ左右 = `--gutter`、セクション間 = `--section-gap`、content 最大幅 = `--page-max`
- 独自のマジックナンバー余白 (`mt-[37px]` 等) を避け、Tailwind の spacing スケール or 上記トークンで揃える

## 差分の入れ方 (ブランド固有)

- 色・accent の案件差分は **`@elm/theme-<brand>` preset を重ねる** (`shadcn add @elm/theme-<brand>`)。`@elm/base` や `app-shell` の構造は編集しない
- preset が無ければ `/design-voice` で個性を抽出 → theme preset に落とす (docs/setup/shadcn.md §4)
- **性格 (余白リズムの詰め/抜き・見出しの個性・モーション)** は design-voice 層の担当。レギュレーション (この rule) は共通の構造・スケールを保証する係

## やってはいけない

- ❌ sidebar / header / content を AppShell を使わず手組みする (案件ごとに構造がブレる)
- ❌ 見出し/本文の font-size を px でハードコードする
- ❌ `@elm/base` のトークンを案件内で再定義・上書きする (差分は preset で)
- ❌ `components/ui/*` (shadcn primitives) を直接改変する (→ `shadcn.md` 参照)

## AI への指示の型 (これで「毎回同じ」になる)

「サイドバー付きの管理画面を作って」等を受けたら:
1. `@elm/base` + `@elm/app-shell` 前提で `AppShell` を土台に置く
2. 確認するのは **ナビ項目・ヘッダー内容・ブランド accent** だけ (骨格・型・余白は既定)
3. 見出し/本文は要素既定、余白はトークン。新しいスケールが要るなら base に足す提案をする
