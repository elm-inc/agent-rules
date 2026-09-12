---
name: design-system
description: デザインシステムの正典 (DTCG トークン) を各サーフェス (shadcn registry / Figma / Claude Design / Storybook) へ反映し、ズレを検査する。案件で「base が最新か」「トークンを直書きしていないか」を確かめたい、正典を変えたいときに使用
argument-hint: "verify [project|shadcn|figma|claude-design] | score | inventory | usage <token> | emit <surface> | observe"
disable-model-invocation: false
allowed-tools: Bash(node *) Bash(bash *) Bash(pnpm *) Bash(git *) Bash(ls *) Bash(cat *) Bash(test *) Read Write Edit
---

# デザインシステムの反映と検査 (dsp)

**このスキルは薄い配線**です。実装は [`elm-inc/design-system-platform`](https://github.com/elm-inc/design-system-platform) の
`dsp` CLI にあり、ここはそれを呼ぶだけ。スキル定義は agent-rules が単一ソース、実装は platform —
両方に置くと二重ソースになります ([ADR-0013](../../docs/adr/0013-three-layer-knowledge-architecture.md))。

```bash
DSP=~/repos/github.com/elm-inc/design-system-platform
```

無ければ `ghq get elm-inc/design-system-platform` で取得してください。

## 何が正典で、何が生成物か

**正典は `design-system-platform/tokens/` の DTCG トークンだけ**です。
`design-registry` の `registry.json` も、Figma の Variables も、Claude Design のカタログも、
案件の `globals.css` も、**すべて生成物**。値を直したいときは必ず正典を直します。

反映は**一方向**。サーフェス側の編集は drift として検出し、取り込む価値があるものだけ人が正典へ PR します。

## 引数

### `verify project [dir]` — 案件で使う (既定・認証不要)

```bash
node $DSP/cli/dsp.mjs verify project .
```

取り込んだ `@elm/base` が今の正典と揃っているかを見ます。**案件 CI から回せます**。

- **正典にあって案件に無い** → `pnpm dlx shadcn@latest add @elm/base --overwrite` で取り込み直す
- **値が違う (owned 宣言なし)** → `app/theme.overrides.css` (owned) で上書きする。
  `globals.css` (managed) を直接書き換えると次の取り込みで消える

終了コード: `0` = OK / `1` = DRIFT / `2` = UNAVAILABLE (**検査できなかった**。drift と区別する)。

### `inventory` — `@elm` を参照している案件を全部検査する

対象リポの一覧は `~/.config/design-system-platform/repos.json`
(**案件名を含むのでリポジトリに置かない**)。既定は `~/repos/github.com/elm-inc` を走査。

### `usage <token>` — 破壊的変更の前に必ず見る

```bash
node $DSP/cli/dsp.mjs usage spacing-md
```

トークンの改名・削除・型変更は**全案件の UI を静かに壊します**。
PR にはこの出力を必ず添えてください。

### `verify shadcn <registry.json>` / `score` — 正典リポで使う

`score` は 2 つの出口を持ちます:
- **conformance** — 規約適合 (DTCG lint / コントラスト / token 逸脱 / visual regression)。**落とす**
- **character** — 個性・質。**常に exit 0 の診断**。N 並列探索では下位を切るフィルタにのみ使い、最終選択は人

### `verify figma <readback>` / `verify claude-design <dir>` — 人のセッションが要る

Figma (pro tier) は **反映も読み戻しも人手**、照合だけが自動です。
手順: [`docs/runbook/figma.md`](https://github.com/elm-inc/design-system-platform/blob/main/docs/runbook/figma.md) /
[`docs/runbook/claude-design.md`](https://github.com/elm-inc/design-system-platform/blob/main/docs/runbook/claude-design.md)

## 案件に配るもの

| ファイル | 置き場所 |
|---|---|
| agent-rules `templates/claude-rules/design.md` | `.claude/rules/design.md` |
| agent-rules `templates/claude-rules/elm-design-overrides.md` | `.claude/rules/elm-design-overrides.md` |
| platform `templates/ci/design-verify.yml` | `.github/workflows/design-verify.yml` |

> rule の雛形は agent-rules (他の rule と同じ場所)、CI は platform (その CLI を呼ぶため) に置く。

`/shadcn` で shadcn を導入した案件に、このスキルで追加配線します。

## 注意

- **`registry.json` を手で編集しない。** 生成物です。正典を直して `dsp emit shadcn` で作り直します
- **トークンが足りないときに直書きで回避しない。** 直書きできてしまうのは正典に足りないものがある信号で、
  実際 spacing scale と border-width はそうして足されました
