# Design DNA: editorial-mono

> 同梱の実例プロファイル。雑誌組版 + スイス・タイポグラフィの規律を web に持ち込む方向。
> 新規プロファイルを作るときの記入例としても参照可。

## 1. Identity statement

印刷された誌面の規律を画面に持ち込む。情報の階層は装飾ではなく**文字組と余白**で表す。
グラデーション・ガラス・薄影カードは使わない。色数は絞り、1色の温かいアクセントだけが強く効く。
左揃えのベースライングリッドで「読ませる」ことを最優先し、中央寄せの巨大ヒーローを拒む。

## 2. Palette

| 役割 | hex | 用途 |
|---|---|---|
| bg | `#f4efe6` | 紙のような温かい背景 |
| surface | `#ffffff` | 本文ブロック面(影は付けない、罫線で分ける) |
| ink | `#1a1a1a` | 本文・見出し(純黒は避け、わずかに温かい黒) |
| accent | `#c1440e` | 主アクセント(朱赤。リンク・強調・図版差し色) |
| accent-2 | `#2d4a3e` | 副アクセント(深緑。引用・補助) |
| muted | `#8a8275` | 罫線・キャプション・補助テキスト |

- **禁止**: 青→紫グラデ、Tailwind 既定の slate/indigo 流用、面のドロップシャドウ
- グラデは使わない。面の分離は 1px の `muted` 罫線で行う

## 3. Typography

- 見出し書体: `"GT Sectra", "Noto Serif JP", serif`(weight 500/700)— セリフで誌面感
- 本文書体: `"Söhne", "Inter Tight", "Noto Sans JP", sans-serif`(weight 400)
- 書体コントラスト: **セリフ見出し × サンセリフ本文**で誌面の対比を作る(全 sans を拒む)
- スケール: 1.333(perfect fourth)modular scale、本文 17px / 行間 1.65
- 組版の癖: 見出しは `letter-spacing: -0.02em` で締める。数字は等幅オールドスタイル。見出しは**左揃え**(中央寄せ禁止)

## 4. Layout grammar

- グリッド: 12 列。本文は 7-8 列に寄せ、右に注釈・余白を残す**非対称**構成
- 密度: 見出し周りは大きく空け、本文は詰める(疎/密のメリハリ)
- 非対称ルール: ヒーローは左寄せ。図版を版面からはみ出させる(ブリード)を許容
- 余白リズム: 8px 基準だが、セクション間は 96px の大きな呼吸を必ず取る
- コンテナ: `max-w-7xl mx-auto` の無批判流用を避け、本文は `66ch` 程度の可読幅に制限

## 5. Motion

- easing: `cubic-bezier(0.2, 0, 0, 1)`(素早く入り、静かに止まる)
- duration: 150–200ms のキビキビ。動きはリンク下線とページ遷移にだけ集中
- 使わない: 全要素一律の scroll fade-up、無意味な hover で動く装飾

## 6. Illustration / iconography

- アイコン: 1.5px の細線、角は直角寄り。**絵文字のアイコン代用は禁止**
- 図像: モノクロ写真 or 単色の幾何図版。均質なフラットストックイラストを避ける

## 7. Copy tone

- 語り口: 断定的で簡潔。誌面のリード文のように、最初の一文で言い切る
- 文長・抑揚: 短文と長文を混ぜる。全箇条書きを同型反復にしない
- 固有性: 抽象語(Seamlessly 等)を避け、具体名詞・数字・固有名を入れる

## 8. Anti-patterns (このプロファイル固有)

- 中央寄せの巨大ヒーロー見出し(このDNAでは左揃え固定)
- 面にドロップシャドウ(罫線で分ける)
- 全要素 sans-serif(見出しは必ずセリフ)

## 9. Exemplars

```html
<!-- 左寄せ・非対称・罫線分割・セリフ見出しのヒーロー -->
<header style="max-width:66ch;padding:96px 24px 48px;background:#f4efe6">
  <p style="font:500 14px/1.4 'Söhne',sans-serif;color:#c1440e;letter-spacing:0.08em;text-transform:uppercase">Field Notes</p>
  <h1 style="font:700 56px/1.05 'GT Sectra',serif;color:#1a1a1a;letter-spacing:-0.02em;margin:.4em 0">
    余白で語る、<br>装飾に頼らない設計。
  </h1>
  <p style="font:400 17px/1.65 'Söhne',sans-serif;color:#1a1a1a;max-width:54ch">
    印刷の規律を画面へ。色は朱赤ひとつ、面は罫線で分ける。
  </p>
</header>
```

```css
/* 面は影でなく罫線で分離。リンクは下線アニメーションだけに動きを集中 */
.card { background:#fff; border:1px solid #8a8275; border-radius:0; }
a { color:#c1440e; text-decoration:none; border-bottom:2px solid #c1440e;
    transition:border-color 180ms cubic-bezier(0.2,0,0,1); }
a:hover { border-color:#2d4a3e; }
```
