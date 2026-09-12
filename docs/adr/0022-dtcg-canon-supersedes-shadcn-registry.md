# ADR-0022: UI デザインレギュレーションの単一ソースを design-system-platform の DTCG トークンに移す

## ステータス

採択 (2026-09-12) — [ADR-0014](0014-shadcn-design-registry.md) を Supersede

## 文脈

[ADR-0014](0014-shadcn-design-registry.md) は **`design-registry` の shadcn custom registry を単一ソース**にした。
`registry.json` に OKLCH の cssVars を手書きし、案件は `shadcn add @elm/base` で取り込み、
`--diff` + CI で「必ず反映」を機械保証する、という構成である。

**サーフェスが shadcn ひとつのうちは、これで成立していた。**

その後、デザインを反映したい先が増えた:

- **Figma** — 人がコラボレーションする場。デザイナーの起点
- **Claude Design** — AI が読むカタログ
- **Storybook** — 実行して観測する場（visual regression の基盤）

サーフェスが 4 つになると、どれかを正典にする限り **n:n の同期問題**になる。
さらに、各サーフェスの表現力は一致しない。[`design-system-platform`](https://github.com/elm-inc/design-system-platform) の
Phase 0-6 で実測した制約:

| 実測 | 内容 |
|---|---|
| Figma の tier | `elm.design` は **pro**。Variables REST API は **Enterprise 限定**で読み書きできない |
| MCP の読み取り | `get_variable_defs` は**ノードに束縛された変数**しか返さない（未束縛は `{}`）。`search_design_system` は公開ライブラリ対象で**値を返さない** |
| Figma の格納精度 | 変数の数値は **float32**（正典の `1.15` が `1.149999976158142` で返る） |
| 色空間 | Figma Variables は sRGB。OKLCH との往復は**非可逆**（62 色中 11 色が色域外） |
| 単位 | Figma の変数は単位を持てず、`em` ベースの `tracking-*` は**構造的に反映できない** |
| 命令的スタイル | `@layer base` の要素既定はトークン形式では表現できない |

つまり **shadcn の cssVars を正典にすると、その表現力が正典の上限になる**。

## 決定

**UI デザインレギュレーションの単一ソースを、[`elm-inc/design-system-platform`](https://github.com/elm-inc/design-system-platform) の `tokens/`（vendor-neutral な [DTCG](https://tr.designtokens.org/format/) トークン）に移す。**

- **`design-registry` は廃止せず「生成物の配信エッジ」に縮退**する。`registry.json` は `dsp emit shadcn` の生成物で、**手で編集しない**。配信 URL・version tag・案件側の手順（`shadcn add @elm/base`）は**変わらない**
- shadcn registry / Figma / Claude Design / Storybook は、いずれも **adapter が生成するサーフェス**として扱う
- **反映は一方向**。サーフェス側の編集は `verify()` が drift として報告し、取り込みは人が正典へ PR する
- **スキル定義は agent-rules が単一ソース、実装は platform の `dsp` CLI**。両方に置くと二重ソースになる（[ADR-0013](0013-three-layer-knowledge-architecture.md)）
- **最低ラインは「検証は全自動」ではなく「照合は必ず機械が判定する」**。Figma (pro tier) は反映も読み戻しも人手で、照合だけが自動になる

## ADR-0014 から引き継ぐもの / 変えるもの

| | ADR-0014 | 本 ADR |
|---|---|---|
| 単一ソース + 差分 + drift 検査 | ✅ | **引き継ぐ**（`verify()` として一般化） |
| 案件は `add @elm/base` で取り込み差分だけ重ねる | ✅ | **引き継ぐ**（手順は不変） |
| managed / owned の分離 | ✅ | **引き継ぐ** |
| 正典の場所 | `design-registry/registry.json` | **`design-system-platform/tokens/`（DTCG）** |
| `registry.json` の扱い | 手書きの正典 | **生成物**（手で編集しない） |
| サーフェス | shadcn のみ | shadcn / Figma / Claude Design / Storybook |
| npm 配布 | 退けた（shadcn はソースを取り込む思想） | **デザイン資産は引き続き退ける。ツール（`dsp` CLI）は npm で配る**（別問題） |

## 理由

- **正典が 1 つであることは、同期方向が 1 つであることで初めて保証される**。双方向を許すと衝突規則が必要になり、規則の集合が実質の第二正典になる
- **正典を vendor 形式にすると、その vendor の表現力が正典の上限になる**。DTCG はどのサーフェスからも等距離で、alias と `$type` があるため機械検査（dangling / 循環 / 型別の値形式 / コントラスト）ができる
- **ADR-0014 の核心を捨てるのではなく、サーフェスを 4 つに一般化した**。守っていた性質（単一ソース + pin + drift 検査）は adapter の `verify()` として保存される
- **移行の安全性を機械で示せた**。現行 `registry.json` の cssVars 84 件を DTCG から**バイト等価に再生成**でき、`shadcn build` の成果物 5 件も一致した（変異注入 8/8 で検査器の有効性も確認）

## 検討した代替案

### 代替案 A: ADR-0014 のまま（design-registry を正典に保つ）
- Pros: 移行不要
- 不採用理由: サーフェスが増えた時点で n:n になる。実際 Figma は sRGB・単位なし・モード制約があり、shadcn の cssVars を正典にすると表現力が頭打ちになる

### 代替案 B: Figma を正典にする
- Pros: デザイナー起点として自然
- 不採用理由: **pro tier では Variables REST が使えず書き出しを自動化できない**。「必ず反映」を機械保証できない（ADR-0014 代替案 D と同じ結論が、実測でより強く裏付けられた）

### 代替案 C: 独自スキーマの正典
- 不採用理由: style-dictionary / Tokens Studio / Figma Variables との変換を全て自作することになる。DTCG で足りない部分は adapter テンプレートという逃げ道がある

## 帰結

### Pros
- サーフェスが増えても n:n 同期にならない
- サーフェスごとの制約（pro tier・sRGB・単位なし・セッション認証）を adapter に閉じ込められ、正典が汚れない
- 案件側の手順が変わらないまま正典を差し替えられた（実測: 既存 CSS 変数を 1 つも変えずに 9 件追加）
- 機械検査が**実際に欠落を見つけた**。代表画面をトークンだけで組もうとして組めず、spacing scale と border-width の欠落が判明して足された

### Cons / 限界
- **週次の drift triage という運用コストが構造的に発生する**。これを回さないと正典は形骸化する（最大のリスク）
- **Figma は反映も読み戻しも人手**。Enterprise に上げれば REST で全自動になるが、それは費用対効果の経営判断であって設計判断ではない
- adapter が 4 つあり、MCP / DesignSync の API 変更に追随するコストが要る
- 正典の一部（`em` ベースの `tracking-*`）は Figma に反映できない。これは drift ではなく**対象外**として毎回件数を報告する

### 実機で確認したこと
- shadcn: 現行 `registry.json` と**バイト等価**
- Figma: 静的 plugin で pro tier でも Variables を書ける。読み戻し **89 件すべて誤差ゼロ一致**（float32 に丸めた厳密比較。**許容誤差は置かない** — 恣意的な閾値は閾値未満の実変更を見逃す）
- Claude Design: `DesignSync` で増分同期。plan のパス検査で**パストラバーサル（`tokens/../../escape.html`）を実際に塞いだ**
- 案件: `jooi-portfolio-project` で**意図的な上書き 13 件と実 drift 9 件を区別**して検出

### 関連 ADR
- [ADR-0014](0014-shadcn-design-registry.md) — 本 ADR が Supersede する
- [ADR-0013](0013-three-layer-knowledge-architecture.md) — 単一ソース + 差分 + drift 検査。スキルを platform に置かない理由
- [ADR-0004](0004-deliberate-design-bias.md) — `/design-voice`。character（質の診断）に組み込む
- [ADR-0020](0020-parallel-exploration-and-scoring-oracle.md) — 採点関数がある場合のみ N 並列探索を許す。conformance と character を分ける理由
