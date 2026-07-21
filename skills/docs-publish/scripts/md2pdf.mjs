// Markdown (mermaid 図 + テーブル) → PDF 変換。
//
// 方式: Markdown → HTML (mermaid.js を同梱してオフライン作図) → ヘッドレス Chrome で印刷。
//   - LaTeX 不要。日本語はシステムの CJK フォントで描画 (要インストール)。
//   - mermaid はローカルの node_modules から読み込むためネットワーク不要。
//   - 全 mermaid ブロックが SVG 化されたか検証し、未描画があれば非ゼロ終了する。
//
// 使い方:
//   node md2pdf.mjs <input.md> <output.pdf> [options]
//     --title "フッタタイトル"   フッタ中央の文書名 (既定: 入力ファイル名)
//     --theme <file.css>          体裁テーマ (既定: ../themes/default.css)
//     --font  "<family>"          本文/図のフォント (既定: テーマの --doc-font)
//     --require-external          frontmatter audience が external 以外なら中止 (外部配布用ガード)
// 環境変数:
//   CHROME_PATH  … Chrome/Chromium 実行ファイルのパス (未指定時は既知の場所を探索)
//
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import MarkdownIt from 'markdown-it';
import puppeteer from 'puppeteer-core';
import { findChrome, preprocess, warnIfFontMissing } from './common.mjs';

const SCDIR = path.dirname(fileURLToPath(import.meta.url));

// ---- 引数パース ----
const raw = process.argv.slice(2);
const pos = [];
let title = null, theme = null, font = null, requireExternal = false;
for (let i = 0; i < raw.length; i++) {
  const a = raw[i];
  if (a === '--title') title = raw[++i] ?? null;
  else if (a.startsWith('--title=')) title = a.slice('--title='.length);
  else if (a === '--theme') theme = raw[++i] ?? null;
  else if (a.startsWith('--theme=')) theme = a.slice('--theme='.length);
  else if (a === '--font') font = raw[++i] ?? null;
  else if (a.startsWith('--font=')) font = a.slice('--font='.length);
  else if (a === '--require-external') requireExternal = true;
  else if (a.startsWith('--')) { /* 未知フラグは無視 */ }
  else pos.push(a);
}
const SRC = pos[0];
const OUT = pos[1];
if (!SRC || !OUT) {
  console.error('usage: node md2pdf.mjs <input.md> <output.pdf> [--title "..."] [--theme f.css] [--font "family"] [--require-external]');
  process.exit(1);
}
if (!title) title = path.basename(SRC).replace(/\.md$/i, '');

// ---- 前処理 (frontmatter 除去 + publish:exclude 除去 + audience ガード) ----
const rawSource = fs.readFileSync(SRC, 'utf8');
const { body: source, audience, excludedRegions } = preprocess(rawSource, { requireExternal });
console.log(`audience: ${audience}${excludedRegions ? `  (publish:exclude ${excludedRegions} 区間を除去)` : ''}`);

// ---- テーマ CSS 読み込み + フォント差し替え ----
const themePath = theme ? path.resolve(theme) : path.join(SCDIR, '..', 'themes', 'default.css');
let css = fs.readFileSync(themePath, 'utf8');
// mermaid に渡すフォント: --font 指定があればそれ、無ければテーマの --doc-font 既定値
let mermaidFont = '"Noto Sans CJK JP","Noto Sans",sans-serif';
const m = css.match(/--doc-font:\s*([^;]+);/);
if (m) mermaidFont = m[1].trim();
if (font) { css = `:root{--doc-font:${font};}\n` + css; mermaidFont = font; }
warnIfFontMissing(mermaidFont);

// ---- Markdown → HTML ----
const mdit = new MarkdownIt({ html: false, linkify: false, typographer: false, breaks: false });
const escapeHtml = mdit.utils.escapeHtml;
const defaultFence = mdit.renderer.rules.fence.bind(mdit.renderer.rules);
mdit.renderer.rules.fence = (tokens, idx, options, env, self) => {
  const token = tokens[idx];
  const info = (token.info || '').trim().split(/\s+/)[0];
  if (info === 'mermaid') {
    return `<div class="mermaid-wrap"><pre class="mermaid">${escapeHtml(token.content)}</pre></div>\n`;
  }
  return defaultFence(tokens, idx, options, env, self);
};

// `---`(hr) が章見出し(## / h2) の直前に来る場合は、改ページと重複してほぼ空白の
// ページを生むため落とす。
const env = {};
const tokens = mdit.parse(source, env);
const kept = tokens.filter((t, i) => {
  if (t.type === 'hr') {
    const nxt = tokens[i + 1];
    if (nxt && nxt.type === 'heading_open' && nxt.tag === 'h2') return false;
  }
  return true;
});
const bodyHtml = mdit.renderer.render(kept, mdit.options, env);

const mermaidJs = fs.readFileSync(path.join(SCDIR, '..', 'node_modules/mermaid/dist/mermaid.min.js'), 'utf8');

const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>${css}</style></head>
<body><main class="doc">${bodyHtml}</main>
<script>${mermaidJs}</script>
<script>
(async () => {
  try {
    mermaid.initialize({
      startOnLoad: false, theme: 'default', securityLevel: 'loose',
      fontFamily: ${JSON.stringify(mermaidFont)},
      flowchart: { useMaxWidth: true, htmlLabels: true },
      sequence: { useMaxWidth: true }, er: { useMaxWidth: true },
      gantt: { useMaxWidth: true }, class: { useMaxWidth: true }, state: { useMaxWidth: true }
    });
    await mermaid.run({ querySelector: 'pre.mermaid' });
    window.__mermaidDone = true;
  } catch (e) {
    window.__mermaidError = String((e && e.stack) || e);
    window.__mermaidDone = true;
  }
})();
</script></body></html>`;

// 一時 HTML は tmpdir に一意名で書く (共有スキル + 並行実行でも衝突しない)。
const htmlPath = fs.mkdtempSync(path.join(os.tmpdir(), 'md2pdf-')) + '/page.html';
fs.writeFileSync(htmlPath, html);

const footerTitle = title.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));

const browser = await puppeteer.launch({
  executablePath: findChrome(), headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none'],
});
try {
  const page = await browser.newPage();
  const msgs = [];
  page.on('console', (m2) => msgs.push(`[${m2.type()}] ${m2.text()}`));
  page.on('pageerror', (e) => msgs.push(`[pageerror] ${e.message}`));
  await page.goto('file://' + htmlPath, { waitUntil: 'load', timeout: 180000 });
  await page.waitForFunction('window.__mermaidDone === true', { timeout: 180000 });

  const err = await page.evaluate(() => window.__mermaidError || null);
  const svgCount = await page.evaluate(() => document.querySelectorAll('pre.mermaid svg').length);
  const mmBlocks = await page.evaluate(() => document.querySelectorAll('pre.mermaid').length);
  console.log(`mermaid blocks: ${mmBlocks}  rendered svg: ${svgCount}`);
  if (err) { console.error('MERMAID ERROR:\n' + err); process.exitCode = 1; }
  if (svgCount !== mmBlocks) { console.error(`WARN: ${mmBlocks - svgCount} 個の mermaid が未描画`); process.exitCode = 1; }
  if (msgs.length) console.log('CONSOLE:\n' + msgs.slice(0, 40).join('\n'));

  await page.pdf({
    path: OUT, format: 'A4', printBackground: true,
    margin: { top: '16mm', bottom: '16mm', left: '12mm', right: '12mm' },
    displayHeaderFooter: true,
    headerTemplate: '<div></div>',
    footerTemplate: `<div style="font-size:8px;width:100%;text-align:center;color:#9aa0a6;font-family:sans-serif;padding-top:2px;">${footerTitle} &nbsp;—&nbsp; <span class="pageNumber"></span> / <span class="totalPages"></span></div>`,
  });
} finally {
  await browser.close();
  fs.rmSync(path.dirname(htmlPath), { recursive: true, force: true });
}
const kb = Math.round(fs.statSync(OUT).size / 1024);
console.log(`WROTE ${OUT} (${kb} KB)`);
