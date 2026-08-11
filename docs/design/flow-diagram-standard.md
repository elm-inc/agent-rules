# 業務フロー図の標準 (Mermaid)

業務フロー図を **AI と作るたびに書式がブレたり必須情報が漏れたりするのを防ぐ**ための単一ソース。スキル `/flow-diagram` が本標準に沿って生成し、`scripts/lint-flow-diagram.py` が機械検証する。根拠: [`ADR-0015`](../adr/0015-business-flow-diagram-standard.md)。

> **1 プロファイル運用** (2026-08 時点)。種別ごとに必須項目が変わってきたらプロファイルを増やす (承認フロー / データ処理 / カスタマー対応 等)。増設時は本標準に節を追加し、バリデータにプロファイル引数を足す。

## ファイル

- 命名: `<プロセス名>.flow.md` (バリデータ・paths rule が拾う)
- 雛形: `templates/flow-diagram/example.flow.md` をコピーして frontmatter と図を差し替える
- レンダリング確認: `/docs-publish` (Mermaid をオフライン作図) で見た目を確認する (実行して確かめる)

## 必須情報チェックリスト (記載漏れ防止)

### frontmatter (すべて必須・`actors`/`systems` はリスト)

| 欄 | 内容 |
|---|---|
| `process` | プロセス名 |
| `purpose` | 目的 (何のためのフローか) |
| `owner` | オーナー (責任部門/担当) |
| `actors` | 関与する役割 (リスト) |
| `systems` | 対象システム (リスト) |
| `trigger` | 開始条件 (何が起きたら始まるか) |
| `version` | 版 |
| `updated` | 更新日 (ISO) |

### 図の要素

- **開始**と**すべての終了状態** (正常終了・却下・エラー等) を明示
- 各ステップを**アクター(swimlane)に割当**
- **判断ノードは条件ラベル付きの分岐 ≥2** (`-->|はい|` / `-->|いいえ|`)
- **例外・エラー経路**を必ず描く (`exception` クラスで明示)
- システム/データの受け渡し点を示す
- (任意) SLA・所要時間は本文の補足欄に

## スタイル規約 (書式一貫性)

- **`flowchart TD`** 固定 (方向は上→下)
- **swimlane は `subgraph "<アクター>"`** でレーン分け
- **ノード形状の意味を固定**:

| 形状 | 記法 | 意味 |
|---|---|---|
| stadium | `id([...])` | 開始 / 終了 |
| rectangle | `id[...]` | 処理 |
| diamond | `id{...}` | 判断 |
| parallelogram | `id[/.../]` | 入出力 |
| cylinder | `id[(...)]` | システム / データ |

- **命名**: ステップ = 動詞+目的語、判断 = 疑問形
- **エッジ**: 分岐は必ず条件ラベル。正常系/例外系を `classDef` で色分け
- **`classDef`** は標準色を使う (色もブレさせない):
  ```
  classDef exception fill:#fde2e2,stroke:#c0392b;   /* 例外・エラー */
  classDef auto fill:#e8f0fe,stroke:#3b6fb0;        /* 自動処理 */
  ```
  例外ノード/終了には必ず `:::exception` を付ける (バリデータが存在を要求)。

## 機械検証 (バリデータが FAIL にする条件)

`python3 scripts/lint-flow-diagram.py <file.flow.md>`:

- frontmatter 必須欄の未記入 / `actors`・`systems` が非リスト
- `flowchart TD` でない
- 開始/終了ノード (`([...])`) が 2 つ未満
- 判断ノードの分岐が 2 本未満、または条件ラベルの無い分岐がある
- 例外経路が無い (`classDef exception` 未定義 or 未適用)
- 孤立ノード (エッジ未接続) / 未定義 `classDef` 参照

warning (exit に影響しない): アクターの swimlane 欠落・subgraph 皆無。

CI 例は `templates/flow-diagram/` 参照。案件リポでは `*.flow.md` を CI で lint して drift を防ぐ。
