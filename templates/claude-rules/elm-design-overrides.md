---
paths:
  - "**/*.{tsx,jsx,css}"
  - "**/app/**"
  - "**/components/**"
  - "components.json"
---

# elm デザイン: managed / owned 分離ルール (カスタムを base 更新から守る)

このファイルは **agent-rules の雛形** (`templates/claude-rules/elm-design-overrides.md`)。フロントエンド案件に `/shadcn` でコピーして `.claude/rules/elm-design-overrides.md` として配置する。目的は **将来 `@elm/base` が更新されても案件のカスタムが維持され、それ以外は base が反映される**こと。根拠: ADR-0014 / docs/setup/shadcn.md §5。

## 大原則: 2 つの層を混ぜない

| 層 | 実体 | 誰のもの | `shadcn add` で |
|---|---|---|---|
| **managed (上流)** | `app/globals.css` の base ブロック (`:root`/`.dark`/`@theme`)、`components/ui/**` (shadcn primitives)、registry 由来コンポーネント | **@elm / shadcn。編集しない** | **再生成・上書きされる** |
| **owned (案件)** | `app/theme.overrides.css`、案件コンポーネント/ラッパー、nav データ | **案件。自由に編集** | **触られない (保持)** |

> **なぜ**: `@elm/base` は今後も更新される。managed を直接書き換えると、次の `add @elm/base` で**カスタムが消える**。owned 層に書けば、base 更新は managed だけを新しくし、owned が cascade で後勝ちして**カスタムは維持**される。

## カスタムのやり方 (ここだけ守れば安全)

### トークンの値を変えたい (色・radius・型・余白)
- ❌ `app/globals.css` の `:root{}` / `--token` を書き換えない (managed。add で戻る)
- ✅ **`app/theme.overrides.css`** に上書きを書く。base の後に import されるので勝つ:
  ```css
  /* @elm-owned: base 更新で維持される。トークン上書きはここに */
  :root { --primary: oklch(0.60 0.13 200); }   /* 案件 accent */
  .dark  { --primary: oklch(0.70 0.12 200); }
  ```
- 配線 (初回のみ、`/shadcn` が実施): root の `app/layout.tsx` で **globals.css の直後に import**
  ```tsx
  import "./globals.css"
  import "./theme.overrides.css"   // ← base の後。これで override が cascade で勝つ
  ```
  この 2 行の import 順が肝。`@import` を globals.css に足す方式は CSS 仕様上 `@import` が先頭必須で壊れやすいので使わない。

### コンポーネントの見た目/挙動を変えたい
- ❌ `components/ui/*` (primitives) や registry 由来コンポーネントを直接編集しない (add で再生成)
- ✅ **ラッパー**か**案件コンポーネント**を別に作る。見た目は className / トークンで
- 再利用するブランド差分は **`@elm/theme-<brand>` preset** (registry 側) にして `add` で重ねる

## base 更新の運用

- 更新は `pnpm dlx shadcn@latest add @elm/base` (+ 必要なら `@elm/app-shell`) で取り込む。**managed だけが新しくなり、owned は残る**
- 取り込み後 `add @elm/base --diff` が **空**であることを確認 (空でなければ managed が直接編集された証拠 → owned へ移す)。CI でも検査する (drift CI)

## 判定の目印

- ファイル先頭に `@elm-managed` があれば **編集しない** (owned 層へ回す)
- `@elm-owned` は案件の編集対象
- 迷ったら「これは add で再生成されるか?」= Yes なら managed

## AI への指示の型 (「一部カスタム」を受けたとき)

1. **トークンの変更** → `theme.overrides.css` に追記 (globals.css は触らない)
2. **コンポーネントの変更** → ラッパー/案件コンポーネントを作る (`components/ui/*` は触らない)
3. base/primitives を書き換えそうになったら止めて、owned 層での実現方法を提案する
   (PreToolUse ガード `.claude/hooks/design-guard.sh` も managed 編集を `ask` で止める)
