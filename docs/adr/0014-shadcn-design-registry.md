# ADR-0014: shadcn custom registry を UI デザインレギュレーションの単一ソースにする

## ステータス

採択 (2026-08-11)

## 文脈

複数の案件で shadcn/ui を使って UI を実装する。案件ごとにデザインは異なるが、**基本方針・レギュレーション** (design tokens、テーマ骨格、radius/spacing/typography、a11y・motion 規約、house-style) は共通で、案件では**その差分だけ**を指示したい。共通部分を各案件でコピペ・再定義すると drift し、AI に毎回フルのデザイン規約を渡すのはトークンも品質も悪化する ([`ADR-0013`](0013-three-layer-knowledge-architecture.md) の「ゼロベース繰り返し」問題のデザイン版)。

shadcn には **custom registry** (JSON over HTTP でコンポーネント/テーマ/トークンを配布) と **`registry:base` / theme preset** の仕組みがあり、これはまさに「共通の基盤 + 差分」を表現するための機構。導入・コマンドの詳細は [`docs/setup/shadcn.md`](../setup/shadcn.md)。

## 決定

**UI デザインレギュレーションを専用の `design-registry` リポジトリ (shadcn custom registry) に単一ソースとして置き、各案件はそれを必ず取り込んだ上で差分だけを重ねる。**

- **design-registry リポ** = デザインの単一ソース (agent-rules の「ルール単一ソース」のデザイン版)。3 層: **base** (定常レギュレーション: OKLCH CSS 変数・tokens・global・a11y/motion) / **theme preset** (ブランド変種) / **house components** (任意)。名前空間 (`@elm` 等) + **version tag で pin**。
- **案件側**は `components.json` の `registries` で参照し、`shadcn add @elm/base` で base を取り込み、**差分 (accent 色・フォント等) だけを theme preset で重ねる**。
- **「必ず反映」を機械保証**: base を pin し、`shadcn add @elm/base --diff` が空であることを CI で検査して drift を防ぐ。
- **AI ワークフロー連結**: `/design-voice` で抽出した個性を theme preset に落として差分に。shadcn MCP は custom registry を参照できるので AI が `@elm/*` を直接 pull。`/project-init` frontend 変種で `@elm` を自動配線。
- agent-rules は雛形 `templates/design-registry/` を提供し、docs/setup/shadcn.md からこの方針を正典として参照する。

## 理由

- **差分運用が構造的に効く**: base を単一ソースにすれば、案件は差分だけを持てばよく、共通部分の drift・コピペ再定義が消える。`--diff` + CI で「必ず反映」を人手でなく機械で保証できる。
- **shadcn 純正機構に乗る**: registry / registry:base / theme preset は shadcn が公式に持つ仕組み。独自の配布層を作るより堅牢で、shadcn MCP/CLI/AI スキルとそのまま噛み合う。
- **agent-rules の思想と一致**: 単一ソース + pin + drift 検査は install.sh --check / lint と同型。デザインにも同じ規律を適用する。
- **専用リポにする理由**: デザイン資産 (トークン・テーマ・コンポーネント) はコードとライフサイクルが違い、複数案件から参照される。agent-rules 本体に混ぜず独立リポにするのが疎結合。private も可 (認証は header + env 展開)。

## 検討した代替案

### 代替案 A: 案件ごとに components.json とテーマを個別定義 (単一ソースなし)
- Pros: リポ追加不要・最も単純。
- 不採用理由: 共通レギュレーションが各案件に散在し drift する。ゼロベース繰り返しそのもの。

### 代替案 B: agent-rules 本体に design tokens を同梱
- Pros: リポを増やさない。
- 不採用理由: デザイン資産とルール/スキルはライフサイクルが異なり、agent-rules を肥大化させる。shadcn registry として配信するには結局 HTTP エンドポイントが要る。疎結合な専用リポが妥当。

### 代替案 C: npm パッケージ (デザインシステムを lib として配布)
- Pros: バージョニング・依存解決が npm で自然。
- 不採用理由: shadcn は「ソースをプロジェクトに取り込む (依存でなくコピー)」思想。npm lib 化すると shadcn CLI/MCP/AI スキルの registry ワークフローから外れ、AI がコンポーネントを add/diff できない。registry の方が shadcn エコシステムと噛み合う。両立させたい場合のみ後日再検討。

### 代替案 D: Figma を単一ソースにし tokens を都度書き出す
- Pros: デザイナー起点なら自然。
- 不採用理由: 実装への「必ず反映」を機械保証しにくい (書き出しが手動)。`/figma tokens` で抽出したものを design-registry に取り込む形なら併用可 (Figma=デザイン発生源、registry=実装単一ソース)。

## 帰結

### Pros
- 案件は差分だけを持てばよく、共通レギュレーションの drift が構造的に消える
- `--diff` + CI で「base が必ず反映されている」ことを機械保証できる
- design-voice / shadcn MCP / project-init と連結し、AI が「base + 差分」で UI を生成できる

### Cons / 限界
- design-registry リポの運用コスト (base の版管理・破壊的変更時の案件への周知) が新たに発生
- registry の項目型 (`registry:base` / theme preset のスキーマ)・build コマンドは shadcn の版依存。実装時に公式スキーマで確定が必要 (雛形は placeholder + 公式リンク)
- private registry の認証 (header + `${TOKEN}`) を CI/各環境に配る運用が要る

### 関連 ADR
- [ADR-0013](0013-three-layer-knowledge-architecture.md) — 単一ソース + 差分 + drift 検査の思想 (本 ADR はそのデザイン版)
- [ADR-0004](0004-deliberate-design-bias.md) — design-voice (house-style 抽出)。抽出した個性を registry の theme preset に落とす
- [ADR-0008](0008-newrelic-connection-hybrid.md) — 認証を env 展開で扱う (トークン直書き禁止) の同型
