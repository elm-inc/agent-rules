# design-registry 雛形 (shadcn custom registry / デザイン単一ソース)

UI デザインレギュレーションを **shadcn custom registry** として 1 リポに定常配置し、各案件はそれを取り込んで差分だけを重ねるための雛形。方針: [`ADR-0014`](../../docs/adr/0014-shadcn-design-registry.md) / 使い方全体: [`docs/setup/shadcn.md`](../../docs/setup/shadcn.md)。

> **版依存の注意**: `registry.json` の項目型 (`registry:base` / `registry:style` / `registry:theme`) と preset コマンド・build 手順は shadcn の版で変わる。実装時に公式スキーマ (`https://ui.shadcn.com/docs/registry`) で確定すること。本雛形は骨格 + placeholder。

## これをリポにする

agent-rules 内では雛形。実際に使うときは専用リポにコピーして配信する:

```bash
# 例 (名称・可視性は用途に応じて。private も可)
cp -r templates/design-registry /tmp/design-registry && cd /tmp/design-registry
gh repo create elm-inc/design-registry --private --source=. --push   # 名称/可視性は要確認
```
配信は GitHub Pages / raw / 任意の静的ホスティング (JSON over HTTP なら何でも)。

## 構成

```
design-registry/
├─ registry.json           # レジストリ定義 (items: base / theme presets / house components)
├─ base/
│  └─ theme.css            # 定常レギュレーション: OKLCH CSS 変数 (light/dark) + tokens
├─ themes/                 # ブランド変種 (theme preset)。案件差分の受け皿
│  └─ .gitkeep
├─ components/             # house-style 済みコンポーネント (任意)
│  └─ .gitkeep
└─ .github/workflows/registry-ci.yml   # registry.json の検証/build
```

- **base** = 変えない定常部 (トークン・テーマ骨格・a11y/motion 規約)。ここが「レギュレーション」
- **themes** = ブランド/案件ごとの視覚差分 (accent 色・フォント等) を preset として置く
- **components** = house-style を焼き込んだ再利用コンポーネント (任意)

## 案件側の使い方 (差分だけ)

```jsonc
// 案件の components.json
{
  "registries": {
    "@elm": { "url": "https://<host>/{name}.json",
              "headers": { "Authorization": "Bearer ${REGISTRY_TOKEN}" } }  // private のとき
  }
}
```
```bash
shadcn add @elm/base            # 定常レギュレーションを必ず取り込む (base を pin)
shadcn add @elm/theme-<brand>   # 案件のブランド差分だけを重ねる
```

## 「必ず反映」を CI で保証 (drift 検査)

案件側 CI に「base が最新か」を検査するステップを入れる (雛形: 下記)。`--diff` が差分を出したら fail させ、base の再取り込みを促す:

```yaml
# 案件リポの .github/workflows に置く例
- name: design-registry drift check
  run: |
    npx shadcn@latest add @elm/base --diff | tee /tmp/diff
    test ! -s /tmp/diff  # 差分があれば fail (base 未反映)
```
> `--diff` の正確な出力仕様・exit code は版依存。実運用前に確認してしきい値を決める。

## AI ワークフロー連結

- `/design-voice extract <参照>` で個性を抽出 → `themes/` の theme preset に落として差分化
- shadcn MCP は `registries` を参照するので、AI が `@elm/*` を直接検索・add できる
- `/project-init` frontend 変種で案件の `components.json` に `@elm` を自動配線
