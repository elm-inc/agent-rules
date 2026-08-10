---
name: design-voice
description: AI生成物(UI・スライド)に意図的なデザイン個性を与え median な「AIっぽさ」から離脱させる。参照例から個性を抽出→生成時に注入(ソフト)、仕上げに批評ループで矯正(ハード)。house-style を効かせたい・量産で似通うのを防ぎたいときに使用
argument-hint: "extract <参照...> [--name <profile>] | use <profile> [--persist] | use --list | critic [<target>] [--profile <name>] [--threshold N]"
disable-model-invocation: false
allowed-tools: Bash(python3 *) Bash(cat *) Bash(ls *) Bash(rg *) Bash(fd *) Bash(jq *) Bash(test *) Bash(find *) Bash(head *) Bash(git *) Bash(curl *) Read Write WebFetch
---

# design-voice: 意図的バイアスで「AIっぽさ」から離脱する

生成AIの UI モック・スライドは RLHF が安全な median (青紫グラデ・glassmorphism・Inter/system font・絵文字アイコン・対称3カラム feature card・中央寄せ巨大ヒーロー) へ収束しがちで、一目で「AI製」とわかる。
本 skill は **意図的に偏らせた「デザインDNA」をプロファイルとして context に注入**し、生成物に一貫した個性を与える。さらに **発散機構**で量産時の似通いを避け、**批評ループ**で median 回帰を矯正する。

このリポの3層哲学に対応:

| 層 | 本 skill のモード |
|---|---|
| 随時(authoring) | `extract` — 参照例から個性を言語化してプロファイル生成 |
| 随時(ソフト適用) | `use` — プロファイルを context 注入 + 発散 seed |
| 機械検証(ハード) | `critic` — AI臭スコア採点 + lint + 別モデル judge で再生成促し |

## ディレクトリ構成

```
${SKILL_DIR}/
  SKILL.md
  anti-tells.md              # 全プロファイル共通の「AIっぽさ」ブロックリスト(最重要)
  profiles/
    _template/               # 新規プロファイルの雛形
    <profile-name>/
      dna.md                 # ★バイアス本体(構造化スペック)
      tokens.json            # 機械利用トークン(UIコードへ直接注入)
      references/            # 抽出元(URL一覧・画像説明・コード断片)
  scripts/
    ai_smell_lint.py         # 生成CSS/HTML の tell を静的検出
```

`${SKILL_DIR}` は本 SKILL.md が置かれたディレクトリ。プロファイルはここに集約し、Claude Code / Codex 双方から symlink 経由で共有される。

## 引数の解釈

第1トークンでモードを決める: `extract` / `use` / `critic`。未指定なら現在の active プロファイル(後述)を表示し、3モードの使い方を案内する。

---

## モード 1: `extract <参照...> [--name <profile>]` — 個性の抽出 (authoring)

参照例 (URL / 画像パス / 貼り付けコード / 既存サイトの説明) を受け取り、特徴を**具体値**に言語化して新規プロファイルを作る。

### 手順

1. **参照の取り込み**
   - URL → `WebFetch` で取得、レンダリング済みの見た目・配色・書体・レイアウトを観察
   - 画像パス → `Read` で画像として読み、配色・余白・タイポ・装飾を観察
   - コード断片/CSS → そのまま読み、トークン(色・font・spacing)を抽出
   - 複数参照は「共通して効いている特徴」と「際立つ特徴」を分けて捉える

2. **多面抽出 (発散・任意)**
   単一視点での平均化を避けるため、可能なら別モデルにも同じ参照の特徴抽出を依頼し差分を拾う(このリポの multi-LLM 役割分担を流用):
   ```bash
   # 例: Codex / Gemini に「この参照の際立つ視覚特徴を5つ、具体的な色/書体/レイアウト語で」
   # /codex-task や /gemini-review を併用してもよい。差分は dna.md の Exemplars に反映
   ```
   別モデルが使えない環境ではこの手順を skip してよい。

3. **プロファイル生成**
   - プロファイル名: `--name` 指定 → それ。未指定 → 特徴から kebab-case で命名 (例: `editorial-mono`, `warm-brutalist`)
   - `${SKILL_DIR}/profiles/_template/` をコピーして `${SKILL_DIR}/profiles/<name>/` を作る
   - `dna.md` を埋める。**adjective の羅列でなく、正確な hex・実書体名・具体スニペットで** (few-shot が効く)。下記「dna.md の構造」に従う
   - `tokens.json` に機械利用トークン(色・font-family・radius・spacing スケール)を書く
   - `references/` に出典を残す (URL 一覧 = `references/sources.md`、画像は説明を `references/notes.md` に。再抽出可能にするのが目的)

4. **検証と報告**
   - `anti-tells.md` と突き合わせ、生成した DNA が AI 既定(青/紫・Inter 既定・絵文字アイコン等)に**逆戻りしていないか**自己点検し、該当があれば修正
   - 生成したプロファイル名・主要トークン(palette / type)・参照元を要約表示し、`use <name>` を案内

### dna.md の構造 (バイアスのペイロード)

`_template/dna.md` のセクションを参照例の値で埋める:

1. **Identity statement** — アートディレクター視点のPOVを1段落
2. **Palette** — 正確な hex + 役割。**AI既定(青/紫グラデ)を明示的に禁止**
3. **Typography** — 書体・スケール・ペアリング・ウェイト。**system-ui / Inter 既定からの離脱を明示**
4. **Layout grammar** — グリッド・密度・非対称ルール・余白リズム
5. **Motion** — easing・duration の性格
6. **Illustration / iconography** — スタイルと出所。**絵文字アイコン代用の可否を明記**
7. **Copy tone** — スライド/テキスト部分の語り口
8. **Anti-patterns** — このプロファイル固有で避ける手癖
9. **Exemplars** — 声を体現する具体コード/マークアップ断片(few-shot の核。2-3個)

---

## モード 2: `use <profile> [--persist]` / `use --list` — 適用 (ソフト層)

選択プロファイルを context に読み込み、以降の UI/スライド生成を偏らせる。

### 手順

1. **`use --list`** なら `${SKILL_DIR}/profiles/` を列挙(`_template` を除く)。各プロファイルの Identity statement 1行と主要 palette を表示して終了。

2. **プロファイル読込**
   - `${SKILL_DIR}/profiles/<profile>/dna.md` + `tokens.json` + 共通 `${SKILL_DIR}/anti-tells.md` を `Read` で読む
   - 存在しなければ `use --list` の候補を提示してエラー

3. **適用宣言**
   以降このセッションで UI/スライドを生成する際は:
   - `tokens.json` の色・書体・spacing を**実コードに直接使う**(Tailwind config / CSS 変数 / インラインに反映)
   - `dna.md` の layout grammar・motion・copy tone に従う
   - `anti-tells.md` の項目を**生成前に避ける**(negative constraint)

4. **発散 seed (量産回避)**
   同じプロファイルでも出力が似通わないよう、生成ごとに DNA の許容空間内から **variation axis を1つ選ぶ**(例: 密度=疎/密、装飾=最小/過剰、非対称の強度)。
   複数案を求められたら N 候補を出し、互いの divergence を意識して**最も median から遠い案**を主案にする。`scripts/brainstorm-divergence.py`(リポ既存)の発想を流用してよい。

5. **`--persist` 指定時**
   プロジェクトルート(`git rev-parse --show-toplevel`)に `.design-voice` を書き、プロファイル名のみ記録する。次セッション以降、UI 作業前にこのファイルを読めば自動で同じ個性を再適用できる。
   ```bash
   echo "<profile>" > "$(git rev-parse --show-toplevel)/.design-voice"
   ```

6. 適用したプロファイル名と「効かせる主要トークン」を1画面で要約し、仕上げに `critic` を回すことを案内。

---

## モード 3: `critic [<target>] [--profile <name>] [--threshold N]` — 批評ループ (ハード層)

生成物を採点し、AI臭が閾値を超えていれば具体違反を出して再生成を促す。仕上げ工程で使う。

### 対象の解決
- `<target>` 指定 → そのファイル/ディレクトリ
- 未指定 → 直近の生成物 or git の未コミット変更から UI/スライド成果物を推定
- プロファイル: `--profile` → それ。未指定 → `.design-voice` → active プロファイル

### 手順

1. **機械パート (lint)**
   ```bash
   python3 ${SKILL_DIR}/scripts/ai_smell_lint.py <target> --profile ${SKILL_DIR}/profiles/<name>/tokens.json
   ```
   生成 CSS/HTML/JSX から tell(Inter/system-ui 既定・blue-purple グラデ・`backdrop-blur`・絵文字アイコン・汎用角丸+薄影カード等)を grep 検出し、件数とファイル:行を出す。

2. **LLM パート (異種 judge)**
   生成元と**別モデル**を judge にして「自分の宿題を自分で採点」を回避(`/codex-review` や `/gemini-review` を併用可)。観点:
   - `anti-tells.md` の各項目に該当するか
   - `dna.md` の palette / type / layout grammar / copy tone を**守れているか**(個性が薄まっていないか)
   - **a11y ガードレール**: 個性化でコントラスト比(WCAG AA)・本文可読性・フォーカス可視を壊していないか

3. **採点とループ**
   - lint 件数 + judge の指摘から **AI臭スコア(0-100、低いほど良)** を算出
   - `--threshold`(既定 30)未満になるまで、具体違反を列挙 → 修正/再生成 → 再採点 を繰り返す
   - 各ラウンドで「何を直したか」を1行で残す

4. 最終スコア・残違反(あれば)・a11y 判定を要約報告。

---

## 注意事項

- **adjective より具体値と実例**: 「ミニマルでモダン」のような形容詞は AI 既定に回帰する。dna.md は必ず hex・書体名・実コードスニペットで書く。
- **個性 ≠ 奇抜さで可読性を犠牲にしない**: critic の a11y ガードレールを必ず通す。コントラスト・可読性・フォーカスは死守。
- **context 肥大の回避**: 重いスペックは本 skill(随時読込)に置き、`CLAUDE.md` には索引1行のみ。常時 context に展開しない。
- **プロファイルは参照を残す**: `references/` を消さない。DNA がドリフトしたら参照から再 `extract` できる。
- **Codex parity**: frontmatter は許可キーのみ(`scripts/validate-codex-skills.sh` で検証)。description に山括弧を入れない。
- 発散と批評は計算コストがかかる。軽微な用途は `use` のソフト適用のみで十分。仕上げや量産時に `critic` を回す。

## 関連

- 設計判断: `docs/adr/` の design-voice ADR、詳細仕様 `docs/design/design-voice.md`
- 流用元: `scripts/brainstorm-divergence.py`(発散)、`mutation-check` skill(機械的自己検証ループ)、`CLAUDE.md` の multi-LLM 役割分担(多面抽出 / 異種 judge)
