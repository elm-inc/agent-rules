# design-voice: AI生成物への意図的バイアス機構 — 詳細仕様

- ADR: [ADR-0004](../adr/0004-deliberate-design-bias.md)
- 実装: `skills/design-voice/`

## 1. 目的

生成AIの UI/スライドが median (青紫グラデ・glassmorphism・Inter 既定・絵文字アイコン・対称3カラム…) に収束し「一目でAI製」になる問題を、**意図的に偏らせたデザインDNAの注入**で解く。一貫した個性を与え、量産時の似通いを発散で抑え、仕上げに機械+LLM の批評ループで median 回帰を矯正する。

対象生成物: **UI/フロントエンド** (HTML/CSS/JSX/Tailwind 等) と **プレゼン/スライド** (Marp/reveal/pptx)。

## 2. 全体構成

```
skills/design-voice/
  SKILL.md            # 3モードの manifest + 手順
  anti-tells.md       # 全プロファイル共通の「AIっぽさ」ブロックリスト
  profiles/
    _template/        # 新規プロファイルの雛形
    <name>/
      dna.md          # 構造化スペック(バイアス本体)
      tokens.json     # 機械利用トークン
      references/      # 抽出元(再抽出用に保持)
  scripts/
    ai_smell_lint.py  # 生成物の tell を静的検出(機械パート)
```

## 3. データモデル

### dna.md (9セクション)

Identity statement / Palette / Typography / Layout grammar / Motion / Illustration・iconography / Copy tone / Anti-patterns / Exemplars。
**形容詞でなく具体値**(hex・実書体名・実コードスニペット)で書くのが鉄則。Exemplars の few-shot コードが出力を最も強く動かす。

### tokens.json

色・font・scale・radius・space・motion・`forbid`(禁止グラデ/書体/効果)。UI コードへ**直接注入**する機械可読トークン。dna.md と同期させる。

### anti-tells.md

配色 / タイポ / レイアウト / 装飾 / アイコン / コピー / モーション / スライドの各カテゴリで median な手癖を列挙。原則は「特定手法の絶対禁止ではなく、**無自覚な既定値としての出力を禁止**」。DNA が意図的に選ぶ場合は可。

## 4. 3つのモード

### extract (authoring)
参照 (URL/画像/コード) → 特徴を具体値に言語化 → `profiles/<name>/` 生成。可能なら別モデルにも抽出させ差分を拾う(平均化回避)。出典は `references/` に残す。

### use (ソフト層)
`dna.md` + `tokens.json` + `anti-tells.md` を context 注入。以降の生成で tokens を実コードに使い、anti-tells を避ける。各生成で variation axis を選び発散(量産の似通い回避)。`--persist` でプロジェクト直下 `.design-voice` にプロファイル名を記録し次セッションへ引継ぎ。

### critic (ハード層)
1. **機械パート**: `ai_smell_lint.py <target> --profile tokens.json` で配色・書体・装飾・絵文字・常套句の tell を検出、AI臭スコア算出。
2. **LLM パート**: 生成元と別モデルの judge が anti-tells 該当 / DNA 遵守 / a11y を評価。
3. **ループ**: `--threshold`(既定30)未満まで違反列挙→修正→再採点。

## 5. ai_smell_lint.py の仕様

- 標準ライブラリのみ(依存なし)。対象: `.css/.scss/.html/.jsx/.tsx/.js/.ts/.vue/.svelte/.astro/.md/.mdx`
- 検出: 青紫グラデ(Tailwind utility + CSS hex)、Inter/system-ui 既定、backdrop-blur、角丸+薄影カード、transition-all duration-300、max-w-7xl mx-auto、AI常套句、絵文字アイコン
- 重み付き合算で score(0-100、高いほど median)。`--threshold` 以上で exit 1(critic ループ / CI ゲート用)
- `--json` で機械可読出力。`node_modules/.git/dist/build/.next` は除外
- **守備範囲**: 機械的に拾える tell のみ。レイアウトの単調さ・コピーの抑揚・モーション設計は LLM judge が担当

## 6. リポ規約への適合

- `install.sh` の `skills/*/` グロブで Claude/Codex 双方へ自動 symlink(install.sh 変更不要)
- frontmatter は許可キーのみ。`scripts/validate-codex-skills.sh` で検証(exit 0 確認済み)
- `CLAUDE.md` に索引1行のみ。重いスペックは skill 側(随時読込)

## 7. 既存資産の再利用

- `scripts/brainstorm-divergence.py` — use の候補発散
- `mutation-check` skill — critic の「機械的自己検証 + 閾値ループ」構造
- multi-LLM 役割分担(CLAUDE.md) — extract の多面抽出 / critic の異種 judge

## 8. 今後の拡張余地

- profiles のバージョニングと A/B(どのプロファイルが刺さったかの記録)
- スライド特化 lint(Marp front-matter / レイアウト均質性の検出)
- pre-commit hook 化(UI 差分に lint を自動適用)
- tokens.json → Tailwind config / CSS 変数の自動生成スクリプト
