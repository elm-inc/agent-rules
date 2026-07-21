---
name: docs-publish
description: Markdown (mermaid 図・テーブルを含む) を、図を正しく描画したまま PDF または Word(.docx) に変換する。設計書・提案書・納品物などを人間向けに配布 (publish) したいときに使用。ヘッドレス Chrome で mermaid をオフライン作図するため pandoc/Marp が素で描けない図も欠落しない。frontmatter と publish:exclude 区間を除去し、audience でガードする (ADR-0012)
argument-hint: "pdf|docx <input.md> [output] [--title/--theme/--font/--reference/--shift/--require-external]"
disable-model-invocation: false
allowed-tools: Read Bash(bash ~/repos/github.com/elm-inc/agent-rules/skills/docs-publish/scripts/ensure-deps.sh*) Bash(node ~/repos/github.com/elm-inc/agent-rules/skills/docs-publish/scripts/md2pdf.mjs*) Bash(node ~/repos/github.com/elm-inc/agent-rules/skills/docs-publish/scripts/md2docx.mjs*) Bash(fc-list*)
---

# Markdown → PDF / Word 変換 (mermaid 図を保持)

`docs/**/*.md` (mermaid 図・テーブルを含む) を、図を正しく描画したまま **PDF** または **Word(.docx)** に変換する。これは [ADR-0012](../../docs/adr/0012-human-facing-docs-publish-model.md) / [ai-first-docs §10 P4](../../docs/design/ai-first-docs.md) の「人間向け publish パイプライン」の実装。

## 方式 (なぜ mermaid が欠けないか)

Markdown → HTML (mermaid.js を**同梱してオフライン作図**) → ヘッドレス Chrome で印刷/描画。pandoc/Marp が素で mermaid を描けない問題を、Chrome での事前描画で回避する。LaTeX 不要・**ネットワーク不要**。**全 mermaid ブロックが SVG 化されたか検証**し、未描画があれば非ゼロ終了する。

## 前提 (プリフライトで自動検査・欠如時は導入手順を案内)

- **Node.js 18+**、依存 (markdown-it / mermaid / puppeteer-core) は初回に `ensure-deps.sh` が `npm ci` で用意する (node_modules はコミットしない。ADR-0005 方式)
- **Chrome / Chromium** (PDF・docx 共通。既知パスを自動探索、無ければ `CHROME_PATH`)
- **pandoc** (docx のみ。無ければ `PANDOC_PATH`)
- **CJK フォント** (日本語を含む場合。未導入だと豆腐になるため警告する。`--font` で導入済みフォントを指定可)

## 引数の解釈

- 第1引数: `pdf` | `docx` (省略時は出力拡張子から推定、それも無ければ `pdf`)
- 第2引数: 入力 `.md`
- 第3引数: 出力パス (省略時は入力の拡張子を `.pdf`/`.docx` に変えたもの)

## 実行手順

1. **依存を用意** (冪等・初回のみ実体導入):
   ```bash
   bash ~/repos/github.com/elm-inc/agent-rules/skills/docs-publish/scripts/ensure-deps.sh
   ```
2. **変換** (絶対パスで呼ぶ):
   ```bash
   # PDF
   node ~/repos/github.com/elm-inc/agent-rules/skills/docs-publish/scripts/md2pdf.mjs <in.md> <out.pdf> [--title "フッタ名"] [--theme f.css] [--font '"<family>"']
   # Word(.docx)
   node ~/repos/github.com/elm-inc/agent-rules/skills/docs-publish/scripts/md2docx.mjs <in.md> <out.docx> [--reference テンプレ.docx] [--shift -1] [--font '"<family>"']
   ```
3. **結果を確認**: `mermaid blocks: N  rendered svg: N` が一致していること (不一致=図の描画失敗で非ゼロ終了)。`audience:` 行と `publish:exclude N 区間を除去` を確認する。
4. 生成物のパスと図の枚数をユーザーに報告する。

## オプション

| フラグ | 対象 | 意味 |
|---|---|---|
| `--title "<名>"` | pdf | フッタ中央の文書名 (既定: 入力ファイル名) |
| `--theme <file.css>` | pdf | 体裁テーマを差し替え (既定: `themes/default.css`。A4・章ごと改ページ) |
| `--font '"<family>"'` | 両方 | 本文/図のフォント (既定: `Noto Sans CJK JP`)。`fc-list \| grep CJK` で導入済みを確認 |
| `--reference <docx>` | docx | 既存 Word のスタイル (見出し・表・フォント) を引き継ぐ |
| `--shift <n>` | docx | 見出しレベルシフト (既定 -1: md の `#` → Word Title、`##` → Heading1) |
| `--require-external` | 両方 | frontmatter `audience` が `external` 以外なら中止 (外部配布用の fail-closed ガード) |

## ADR-0012 連携 (配布物に出さないもの)

- **frontmatter を除去**して描画する (機械用メタを配布物に出さない)。
- **`<!-- publish:begin-exclude -->` … `<!-- publish:end-exclude -->` 区間を除去**する (内部限定部分を配布物に出さない)。開閉が不一致なら中止 (fail-closed)。
- **顧客・ベンダーに配る成果物では `--require-external` を付ける** (`audience: external` の明示がない doc の外部出力を防ぐ)。

## 注意

- クライアント修正依頼は**生成元 Markdown を直して再生成**する (PDF/docx を直接いじらない。ADR-0012 の publish 派生原則)。
- 体裁 (フォント・表・改ページ・余白) は `themes/default.css` と `md2pdf.mjs` の `page.pdf({...})` margin で調整する。
- 本当に依存を導入できない (オフライン等) ときのみ中止し、理由を報告する。
