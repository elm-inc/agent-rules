---
name: docs-visualize
description: コードと既存設計を読み解いてプロジェクトを C4 model + 状態機械 + シーケンス図で可視化する。docs/architecture/ に Mermaid で書き出す。「可視化」「アーキテクチャ図」「視覚化」「全体像」を要求されたときに使用
argument-hint: "[--scope <絞り込み>] [--force]"
disable-model-invocation: false
allowed-tools: Bash(ls *) Bash(find *) Bash(cat *) Bash(grep *) Bash(rg *) Bash(git *) Bash(wc *) Read Write Edit
---

# プロジェクトのアーキテクチャを可視化

カレントワーキングディレクトリ (= git リポジトリのルート) のコードと既存ドキュメントを読み解き、C4 model 準拠のアーキテクチャ図群を `docs/architecture/` に Mermaid で書き出す。

## 引数の解釈

- `--scope <キーワード>`: 特定の機能・モジュールに絞った視点で図を描く (例: `--scope auth`)
- `--force`: 既存ファイルを上書き (デフォルトはスキップ + ユーザー確認)
- 引数なし: プロジェクト全体を対象

## 前提条件

- `docs/architecture/` が無ければ、先に `/docs-init` の実行を提案する
- `docs/architecture/README.md` と `cheatsheet.md` は agent-rules テンプレから展開されている前提

## 実行手順

### 1. プロジェクト構造の把握

以下を順に確認:
- リポジトリ言語・スタック (`Sources/`, `src/`, `lib/` などの主要ディレクトリ)
- 主要な依存関係宣言 (`Package.swift`, `package.json`, `Cargo.toml`, `pyproject.toml` 等)
- 既存の ADR (`docs/adr/`) — 設計決定を理解
- `README.md`
- 既存の `docs/design/`

### 2. システム境界・依存関係の抽出

コードから次を読み取る:
- 外部 API 呼び出し (URLSession, fetch, requests, http client 等)
- ユーザー入力の経路 (UI / HTTP / CLI など)
- データストア (ファイル / DB / Keychain など)
- 主要な内部モジュール

### 3. C4-like 図の生成

**重要**: Mermaid の `C4Context` / `C4Container` / `C4Component` 構文は **使わない** (長ラベルでレイアウトが崩れる既知問題)。**`flowchart` + `subgraph` + `classDef`** で同等表現する。詳しい記法は `docs/architecture/cheatsheet.md` を参照。

すべての Mermaid ブロックの冒頭に `%%{init: {'theme':'default'}}%%` を入れ、`classDef` で `fill / stroke / stroke-width / color:#000` を全指定 (ダーク/ライト両モード対応)。

#### 3-1. `0-context.md` (L1 Context)
- システム本体・外部 API・主要ペルソナを flowchart で配置
- ペルソナは `(())` (rounded)、外部は `subgraph external` でくくる
- 末尾に「ポイント」セクションで主要な前提を箇条書き

#### 3-2. `1-containers.md` (L2 Container)
- アプリ内の主要 container (主要モジュール群) を `subgraph app` 内に列挙
- 外部要素との関係を維持しつつ、内部の結線を可視化
- Container は実装ディレクトリ・ファイル名と対応させる
- DB / ストアは `[(...)]` (round-edge) で示す

#### 3-3. `2-components.md` (L3 Component)
- 重要な container (例: 中心的な Coordinator / Service) の内部結線
- **すべての container を L3 で展開しない** (情報過多になる)
- ファイル数の多い / 結線が密な container だけ詳述する

### 4. 補足図の生成 (該当する場合のみ)

| ファイル名 | 条件 | Mermaid 種 |
|---|---|---|
| `3-state-machine.md` | enum / state 型がコードに存在 | `stateDiagram-v2` |
| `4-sequence-<シナリオ>.md` | 重要ユーザーシナリオ (2〜3 個上限が目安) | `sequenceDiagram` |
| `5-data-flow-<名>.md` | データ変換が中心のシステム | `flowchart` |
| `6-module-dependencies.md` | モジュール数 ≥ 5 | `flowchart` + `subgraph` |

該当しない種の図はスキップする (無理に作らない)。

### 5. 図と他成果物のリンク

各図ファイルの末尾に `## 関連` セクションを追加し、以下を列挙:
- 関連 ADR へのリンク
- 該当する実装ファイル / ディレクトリへのリンク
- 関連する他の図 (状態機械やシーケンス)

### 6. README 更新

`docs/architecture/README.md` の索引を更新し、生成した図ファイルを表に追加する。

### 7. 結果報告

ユーザーに以下を伝える:
- 作成 / 更新 / スキップしたファイル一覧
- 検出した特徴 (例: 「8 モジュール、状態機械 1 個、外部 API 2 個、シーケンス図 3 本」)
- 次のアクション提案:
  - 不足を感じる図があれば追加 (`--scope` で部分的可視化)
  - 大きな設計変更時は `/adr-new` で ADR を残す

## 注意点

- **drift を生まない**: 既存ファイルがあれば、勝手に上書きせずユーザー確認 (`--force` 指定時のみ上書き)
- **過剰な詳細を入れない**: L3 をすべての container に展開すると情報過多。中心 component に絞る
- **コードと一致させる**: モジュール名・ファイル名・関数名は実コードと正確に揃える (推測で名前を作らない)
- **Mermaid 構文を確認**: 各図は GitHub プレビューでレンダリングできる前提で書く。閉じ括弧・改行・特殊文字に注意
- **C4 plugin は使わない**: `C4Context` / `C4Container` / `C4Component` はレイアウトが崩れる。flowchart + subgraph で同等表現する
- **テーマ明示**: 冒頭に `%%{init: {'theme':'default'}}%%` を必ず入れる
- **色は両モード対応**: classDef で `color:#000` を含めて fill / stroke / stroke-width を全指定 (cheatsheet の色パレットを参照)
- **状態機械のラベル**: `\n` は使わず 1 行の短い動詞で書く。詳細は本文の表に逃がす
- **コード分析の限界を認める**: 動的な振る舞いや状態遷移はコードから完全には読めない。推測した箇所は ADR で確認するか、ユーザーに尋ねる

## 関連

- 文書化方針: `~/CLAUDE.md` の「ドキュメント・図式」セクション
- 凡例: `docs/architecture/cheatsheet.md` (= `agent-rules/templates/docs/architecture/cheatsheet.md`)
- 既存例: `elm-inc/drive-partner` の `docs/architecture/` (commit 9c2d2d7)
