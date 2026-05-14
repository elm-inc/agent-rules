# Prompt: アーキテクチャ可視化

新プロジェクトの Claude Code セッションで「同じように可視化してほしい」と伝えるときのプロンプト集。drive-partner で実証した C4 + 状態機械 + シーケンス図 + モジュール依存図を生成する。

## 前提

新マシン or `agent-rules` 未導入のマシンでは事前に:

```bash
git clone https://github.com/elm-inc/agent-rules ~/repos/github.com/elm-inc/agent-rules
~/repos/github.com/elm-inc/agent-rules/install.sh
# 既存マシンは pull のみで OK
git -C ~/repos/github.com/elm-inc/agent-rules pull
```

これで `/docs-init` `/docs-visualize` `/adr-new` を含む全スキルと、`~/CLAUDE.md` の方針が揃う。

---

## 最短版 (まずこれで十分)

```
このプロジェクトを C4 model で可視化してください。
docs/ が未整備なら /docs-init を先に、その後 /docs-visualize で図を生成。
参考: elm-inc/drive-partner の docs/architecture/
```

---

## フル版 (明示的に手順を指示)

```
このプロジェクトのアーキテクチャと実装を可視化してください。

手順:
1. docs/ がなければ /docs-init で標準構造 (adr/ architecture/ design/) を展開
2. /docs-visualize でアーキテクチャ図を生成
   - C4 model: 0-context (L1) / 1-containers (L2) / 2-components (L3)
   - 状態機械があれば 3-state-machine
   - 主要シナリオ 2〜3 個を 4-sequence-<名>
   - 必要なら 5-data-flow-<名>
   - モジュール数 ≥5 なら 6-module-dependencies
3. 各図に「ポイント」セクションと関連 ADR / 実装ファイルへのリンクを含める

参考実装: elm-inc/drive-partner の docs/architecture/
方針: ~/CLAUDE.md の「ドキュメント・図式」セクション
```

---

## 自然言語のトリガー (スキルが auto invoke される)

`/docs-visualize` の description に下記キーワードが含まれているので、自然言語でも skill が呼ばれる:

- 「このプロジェクトを可視化して」
- 「アーキテクチャ図を作って」
- 「全体像を Mermaid で見たい」
- 「視覚化して」

スキルが想定通り動かない場合は、上の「最短版」「フル版」で明示する。

---

## 期待される成果物

- `docs/architecture/README.md` (索引)
- `docs/architecture/0-context.md` 〜 `6-module-dependencies.md` のうち該当する図
- 各図は `flowchart + subgraph + classDef` で記述、theme/色明示でダークモード対応
- 末尾に関連 ADR / 実装ファイルへのリンク
- コミットメッセージ案 (PR で diff レビューしやすい単位)

---

## 追加の指示パターン

| 目的 | 追加で言うべきこと |
|---|---|
| 部分的に可視化 | `/docs-visualize --scope auth`（機能スコープを絞る) |
| 既存図の更新 | 「過去の図と差分を確認してから書き直して。差分がある部分だけ更新」 |
| 設計判断も残す | 「重要な決定は /adr-new で ADR にしてから図を更新して」 |
| 不要な図を削る | 「内容が薄い図は作らずスキップして」 |
| 部分実装でも書く | 「コードから読み取れる範囲だけ書いて、未実装部分は TODO コメント」 |

---

## トラブルシュート

| 症状 | 対応 |
|---|---|
| GitHub のダークモードで黒背景 + 灰文字 | cheatsheet の theme 明示 + classDef `color:#000` を使っているか確認。古い C4 plugin 構文が残っていたら flowchart に置換 |
| テキスト重なり | C4Context/Container/Component 構文を flowchart + subgraph に置換 (drive-partner の commit 43dbb09 が参考) |
| 図が大きすぎる | 各図を 1 つの責務に絞る。subgraph 階層を浅くする |
| ADR との内容ずれ | 「ADR と図の整合を確認して、ズレを ADR 更新で吸収するか図を直すか提案して」と頼む |
