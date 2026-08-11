---
name: shadcn
description: フロントエンド案件に shadcn/ui を標準どおり導入する。公式 MCP (mcp init・per-project) と公式 skill (監査後 add)・規約 rule・design-registry (@elm/base) 配線を一括。React/shadcn 案件の初期化・設定に使用
argument-hint: "init [--template next|vite|react-router|astro] | mcp | audit-skill | rule | registry | verify"
disable-model-invocation: false
allowed-tools: Bash(pnpm dlx shadcn@latest*) Bash(pnpm dlx skills*) Bash(npx shadcn@latest*) Bash(pnpm shadcn*) Bash(cp *) Bash(ls *) Bash(cat *) Bash(test *) Bash(mkdir -p*) Bash(chmod +x*) Bash(git *) Read Write Edit
---

# shadcn/ui 導入オーケストレーション (標準どおり配線)

shadcn は**公式が MCP と Claude Code スキルを配布**しているので、本スキルは**自作せず公式を配線し、うちの規約を強制する薄い層**。コンポーネントの検索・追加は公式 MCP / 公式 skill に委譲する (このスキルは init/設定の配線だけ)。全体像・版依存の詳細: [`docs/setup/shadcn.md`](../../docs/setup/shadcn.md) / 根拠: [`ADR-0014`](../../docs/adr/0014-shadcn-design-registry.md)。

## 前提

- **対象は案件 (フロントエンド) リポの中で実行する** — agent-rules 自身の上では実行しない (git repo ルートで、package.json がある想定)
- コマンド名・フラグは shadcn の版で変わる。失敗したら [`docs/setup/shadcn.md`](../../docs/setup/shadcn.md) と公式 (`ui.shadcn.com/docs`) で確認

## 引数

- `init [--template <t>]` → 下の全手順を順に実行 (既定)
- `mcp` / `audit-skill` / `rule` / `registry` / `verify` → 個別ステップだけ実行

## 実行手順 (`init`)

### 1. shadcn 初期化

```bash
pnpm dlx shadcn@latest init --template next   # or vite/react-router/astro
```
- 既存プロジェクトで `components.json` があれば init を飛ばす (上書きしない)。Tailwind v4 / RSC (`"rsc": true`) を確認

### 2. MCP サーバ (per-project・global 登録しない)

```bash
pnpm dlx shadcn@latest mcp init --client claude   # .mcp.json 生成
```
- **`.mcp.json` に認証トークンを直書きしない**。private registry は §5 の env 展開で
- `.mcp.json` は各自 `mcp init` で再生成できるため、既定では gitignore でよい (project-init の .gitignore と整合)

### 3. 公式スキルを**監査してから**導入

```bash
pnpm dlx skills add shadcn/ui        # または /plugin install shadcn@community
```
- **導入前に [`docs/setup/skill-audit-checklist.md`](../../docs/setup/skill-audit-checklist.md) で監査**する (公式でも省かない: SKILL/スクリプトの外部送信・自己改変・難読化がないか、allowed-tools の最小性)。問題なければ add、バージョンは pin

### 4. うちの規約 rule を配置 (コピー)

```bash
AR=~/repos/github.com/elm-inc/agent-rules
mkdir -p .claude/rules .claude/hooks
for r in shadcn elm-design-layout elm-design-overrides; do
  test -f ".claude/rules/$r.md" || cp "$AR/templates/claude-rules/$r.md" ".claude/rules/$r.md"
done
test -f .claude/hooks/design-guard.sh || cp "$AR/templates/claude-hooks/design-guard.sh" .claude/hooks/design-guard.sh
chmod +x .claude/hooks/design-guard.sh
```
- symlink でなく**コピー** (他環境で解決される必要があるため)。既存は上書きしない
- `shadcn.md` = shadcn の使い方 / `elm-design-layout.md` = レイアウト・型・余白規約 / `elm-design-overrides.md` = **managed/owned 分離**(カスタムを base 更新から守る)
- **機械ガード**: `.claude/settings.json` の PreToolUse に design-guard を配線 (managed への直接編集を `ask` で止める)。既存 hooks は保持してマージ:
  ```bash
  node -e '
    const fs=require("fs"),p=".claude/settings.json";
    const s=fs.existsSync(p)?JSON.parse(fs.readFileSync(p,"utf8")):{};
    s.hooks=s.hooks||{}; s.hooks.PreToolUse=s.hooks.PreToolUse||[];
    const has=JSON.stringify(s.hooks.PreToolUse).includes("design-guard.sh");
    if(!has)s.hooks.PreToolUse.push({matcher:"Edit|Write|MultiEdit",hooks:[{type:"command",command:"bash .claude/hooks/design-guard.sh"}]});
    fs.writeFileSync(p,JSON.stringify(s,null,2)+"\n");
    console.log(has?"design-guard: already wired":"design-guard: wired");
  '
  ```

### 5. design-registry (@elm/base) を配線

house-style の定常レギュレーションを単一ソースから取り込む (ADR-0014):

- `components.json` の `registries` に `@elm` を追加: `"@elm": "https://elm-inc.github.io/design-registry/r/{name}.json"` (public・稼働中)。private registry を使う場合のみ `{ "url": ..., "headers": { "Authorization": "Bearer ${REGISTRY_TOKEN}" } }` 形式 (値は `.env.local`、直書き禁止)
```bash
pnpm dlx shadcn@latest add @elm/base        # 定常レギュレーション (色・型・余白・sidebar 寸法) を取り込む
pnpm dlx shadcn@latest add @elm/app-shell   # レイアウト骨格 (sidebar+header+content, Next App Router)。sidebar 等も自動
```
- この案件では**差分 (accent 色・フォント等) だけ**を theme preset で重ねる。base を案件内で再定義しない
- レイアウトは `@elm/app-shell` の `AppShell` を土台にし、ナビ項目と header だけ差し替える (骨格・型・余白は base 既定)。詳細は配置した `.claude/rules/elm-design-layout.md`
- design-registry 未整備なら、house-style は `/design-voice` で抽出 → theme preset に落とす (§docs/setup/shadcn.md §4-5)

**owned 層のセットアップ (カスタムを base 更新から守る / `elm-design-overrides.md`)**:

- 空の **`app/theme.overrides.css`** を作り、**root の `app/layout.tsx` で `globals.css` の直後に import** する (この 2 行の順が肝。base の後に来て cascade で勝つ)。以後トークンの上書きは全部ここへ。`globals.css` (managed) は触らない
  ```tsx
  import "./globals.css"
  import "./theme.overrides.css"   // ← base の後。add @elm/base では触られない = 維持される
  ```
  ```css
  /* app/theme.overrides.css — @elm-owned: base 更新で維持。トークン上書きはここに */
  ```
- **drift CI** (任意・推奨): `templates/ci/design-registry-drift.yml` を案件の `.github/workflows/` に置くと、`add @elm/base --diff` が空でない (=managed 直接編集) 時に CI が fail する

### 6. 接続確認

- Claude Code の `/mcp` で shadcn MCP が接続済みか確認
- `pnpm dlx shadcn@latest info --json` でプロジェクト設定を確認 (framework/registries/installed)

### 7. 結果

生成/配置したもの (`.mcp.json`・`.claude/rules/{shadcn,elm-design-layout,elm-design-overrides}.md`・`.claude/hooks/design-guard.sh` + settings 配線・`app/theme.overrides.css` + layout 配線・`components.json` の registries)・監査結果・接続確認を提示。カスタムは **owned 層 (theme.overrides.css / ラッパー) に書き、managed (globals.css の base 域・`components/ui/*`) は触らない**旨を明示 (ガードが `ask` で止める)。以後のコンポーネント追加は公式 MCP (`get_item`/`add_item`) or `shadcn add`。

## 注意

- **agent-rules 上で実行しない** (案件リポ用)
- コンポーネントの追加・更新の本体は公式 MCP/skill/CLI。本スキルは init/設定の配線と規約強制に限定する
- `--dry-run` / `--diff` を使えば「提案→確認→実行」で安全に (検証ループ)
