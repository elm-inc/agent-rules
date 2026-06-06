# ADR-0004: 生成物に意図的バイアス(デザイン的個性)を与える機構を導入する

## ステータス

提案 (2026-06-06)

## 文脈

生成AIの普及により、AI が作ったと一目でわかる UI モック・プレゼン資料が溢れている。これは品質の問題というより **median への収束**の問題である:

- RLHF は安全な平均値へ出力を引っ張る (青→紫グラデ、glassmorphism、Inter/system-ui 既定、絵文字アイコン、対称3カラム feature card、中央寄せ巨大ヒーロー)
- 強い制約が無いとき、モデルは最頻トークン = 学習分布の最頻値で空白を埋める
- セッションを跨いだ一貫したデザイン視点が無いため、同じ "AIっぽい" 成果物を量産する

本格的な UI デザイン用途でも「安全側に倒す」傾向が個性の欠如を生む。これは ADR-0001 の multi-LLM ワークフロー(品質の多層化)では解けない、**美的方向性の問題**である。

## 決定

**意図的に偏らせた「デザインDNA」をプロファイルとして context へ注入し、生成物に一貫した個性を与える機構** (`design-voice` skill) を導入する。リポの既存3層哲学(常時ルール / 随時 skill / 機械検証)に対応させる:

| 層 | 実装 |
|---|---|
| 随時 (authoring) | `/design-voice extract` — 参照例から個性を言語化してプロファイル生成 |
| 随時 (ソフト適用) | `/design-voice use` — プロファイルを context 注入 + 発散 seed で量産時の似通いを回避 |
| 機械検証 (ハード) | `/design-voice critic` — AI臭スコア採点 (lint + 異種モデル judge) で閾値未満まで再生成 |

### 1. 個性は「参照例から抽出」して定義する

形容詞 (「ミニマルでモダン」) は AI 既定へ回帰するため使わない。実在の参照 (サイト/資料/画像) から**具体値** (正確な hex・実書体名・実コードスニペット) を抽出して `dna.md` + `tokens.json` に固定する。few-shot 的な exemplar コードを核に据える。

### 2. 複数プロファイルを切り替える

案件ごとに house-style を `profiles/<name>/` で持ち、`use <name>` で選択する。単一固定アイデンティティではなく、発散を担保しやすい複数プロファイル制を採る。

### 3. ソフト / ハードの二段運用

通常は `use` の context 注入(ソフト)のみで十分。仕上げや量産時に `critic` の批評ループ(ハード)を回す。critic は機械 lint (`ai_smell_lint.py`) と**生成元とは別モデルの judge** を併用し「自分の宿題を自分で採点」を回避する。

### 4. a11y ガードレールを必須にする

個性化が可読性・コントラスト (WCAG AA)・フォーカス可視を壊さないことを critic で必ず確認する。「奇抜さ」でアクセシビリティを犠牲にしない。

### 5. 配布はリポの既存パターンに乗せる

`skills/design-voice/` 配下に skill + profiles + scripts を集約。`install.sh` の `skills/*/` グロブで Claude Code / Codex 双方へ自動 symlink される。重い DNA スペックは skill (随時読込) に置き、`CLAUDE.md` には索引1行のみ (常時 context の肥大回避)。

## 理由

- **median 回帰は negative constraint が最も効く**: 「AIっぽさ」の手癖 (tell) は well-characterized なので、共通 `anti-tells.md` で明示的に避けるのが高レバレッジ
- **具体値 > 形容詞**: 参照からの抽出 + exemplar コードは、抽象的な指示より確実に出力を動かす
- **量産の似通い対策**: 同一プロファイルでも variation seed で発散させ、median から最も遠い案を主案にする (`scripts/brainstorm-divergence.py` の発想を流用)
- **異種モデル judge**: 生成元と同じモデルで採点すると同じ盲点を見逃す。multi-LLM 資産 (Codex/Gemini) を judge に使う

## 検討した代替案

### 代替案 A: CLAUDE.md / RULES.md に常時ルールとして書く

- Pros: 常時適用、実装不要
- Cons: 全セッションの context を圧迫、案件ごとの切替不可、重いスペックを毎回読む
- 不採用理由: 個性は案件依存。随時 skill のほうが切替・隔離に適する

### 代替案 B: 単一固定アイデンティティ

- Pros: シンプル
- Cons: 案件ごとの個性を出せない、量産時の似通いが残る
- 不採用理由: ユーザー要件 (複数プロファイル切替) に合わない

### 代替案 C: ソフト適用のみ (critic 無し)

- Pros: 軽量
- Cons: context 注入は守られないことがある (median へ流れる)
- 不採用理由: 仕上げ品質の保証に機械的ゲートが要る。二段運用で両取りする

### 代替案 D: 形容詞ベースのスタイル指定 (「brutalist で」等)

- Pros: 最も手軽
- Cons: スタイル名のカーゴカルトで中身が伴わない、再現性が低い
- 不採用理由: 参照例からの具体値抽出のほうが確実に効く

## 帰結

### Pros

- AI っぽい median な見た目から離脱でき、案件ごとに一貫した個性を出せる
- 量産時の似通いを発散機構で抑制
- 機械 lint で "AIっぽさ" を CI/コミット前にゲート可能
- Claude Code / Codex 双方で同一プロファイルを共有

### Cons

- プロファイル authoring に初期コスト (参照集め + 抽出)
- critic ループは計算コストがかかる (軽微な用途には過剰)
- プロファイルが参照からドリフトする可能性 (references/ を残して再抽出で対処)

### 引き受けるリスク

- **過剰な個性化で a11y 低下**: critic の a11y ガードレールで点検
- **lint の取りこぼし / 誤検出**: 機械パートは配色・書体・装飾・絵文字・常套句のみ。レイアウトやコピーの抑揚は LLM judge が補完
- **機密素材の混入**: 参照画像は references/ に置かず観察メモのみ残す (public 同期されるため)

## 関連

- [ADR-0001](0001-multi-llm-development-workflow.md): multi-LLM ワークフロー (異種 judge / 発散の流用元)
- [ADR-0002](0002-multi-model-test-generation.md): 多モデルでの観点発散 (思想的に近い)
- 詳細仕様: [docs/design/design-voice.md](../design/design-voice.md)
- 実装: `skills/design-voice/` (SKILL.md, anti-tells.md, profiles/, scripts/ai_smell_lint.py)

## 改訂履歴

- 2026-06-06 提案
- (採択時) 1-2 プロファイルで実運用してから採択判定
