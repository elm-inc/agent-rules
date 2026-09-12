---
paths:
  - "**/*.{tsx,jsx,css,scss}"
  - "**/*.module.css"
  - "tailwind.config.*"
  - "components.json"
---

# elm デザイン: 正典のトークンだけで組む

このファイルは **agent-rules の雛形** (`templates/claude-rules/design.md`)。
案件に `.claude/rules/design.md` として配置する。実装 (`dsp` CLI) は design-system-platform にある。managed / owned の分け方は
[`elm-design-overrides.md`](elm-design-overrides.md) を参照 (両方置く)。

## 原則: 値を直書きしない

色・余白・角丸・境界線・書体・文字サイズは**すべて正典のトークン**から取る。

```tsx
// ❌ 直書き
<div style={{ padding: "12px 16px", border: "1px solid #e4e4e7", borderRadius: 10 }} />

// ✅ トークン
<div style={{
  padding: "var(--spacing-sm) var(--spacing-md)",
  border: "var(--border-width) solid var(--border)",
  borderRadius: "var(--radius)",
}} />
```

Tailwind のユーティリティなら `p-md` / `gap-lg` / `px-sm` が使える
(`--spacing-*` は Tailwind の名前空間なので、既定の `p-4` とも共存する)。

## 使えるトークン

| 分類 | トークン |
|---|---|
| 役割色 | `--background` `--foreground` `--card(-foreground)` `--popover(-foreground)` `--primary(-foreground)` `--secondary(-foreground)` `--muted(-foreground)` `--accent(-foreground)` `--destructive` `--border` `--input` `--ring` `--chart-1..5` `--sidebar*` |
| 余白 | `--spacing-2xs` `xs` `sm` `md` `lg` `xl` `2xl` `3xl` / `--gutter` `--section-gap` |
| 型 | `--font-sans` `--text-display` `--text-h1..h4` `--text-body` `--text-small` `--leading-*` `--tracking-*` |
| その他 | `--radius` `--border-width` `--page-max` `--app-sidebar-width*` |

`h1`〜`h4` / `p` / `small` は `@layer base` で既に揃っているので、**見出しに font-size を指定しない**。

## 足りないトークンがあったら

**直書きで回避しない。** 直書きできてしまうのは正典に足りないものがある信号なので、
design-system-platform に Issue を立てる (実際 spacing scale と border-width はそうして足された)。

どうしても必要なら、**理由を書いて抑制する**:

```tsx
<div style={{ /* ds-allow[寸法リテラル]: カタログ自身のレイアウト。デザインシステムの利用箇所ではない */ gridTemplateColumns: "220px 1fr" }} />
```

抑制は**規則ごと**に書く (`ds-allow[寸法リテラル]`)。行単位で全部消せると、
余白を抑制したつもりで同じ行のハードコード色まで黙って消える。

## 値を変えたい (案件のカスタム)

`app/globals.css` (managed) は**触らない**。次の `shadcn add @elm/base` で消える。
`app/theme.overrides.css` (owned) で上書きする。詳細は `elm-design-overrides.md`。

## 検査

```bash
pnpm dlx @elm/dsp verify project .   # 取り込んだ base が正典と揃っているか
```

CI にも同じものを置く (`templates/ci/design-verify.yml`)。
