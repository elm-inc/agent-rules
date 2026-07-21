// Markdown (mermaid 図 + テーブル) → Word(.docx) 変換。
//
// 方式: 各 ```mermaid ブロックを高解像度 PNG に描画 → 画像参照に差し替え →
//        pandoc で docx 化。--reference で既存 Word のスタイル (見出し・表・
//        フォント) を引き継ぐ。
//
// 使い方:
//   node md2docx.mjs <input.md> <output.docx> [options]
//     --reference <docx>   スタイル参照元の Word (省略可)
//     --shift <n>          見出しレベルシフト (既定 -1: md の # → Word Title)
//     --font "<family>"    mermaid 描画フォント (既定: Noto Sans CJK JP)
//     --require-external   frontmatter audience が external 以外なら中止
// 環境変数:
//   CHROME_PATH  … Chrome/Chromium 実行ファイル (mermaid 描画に使用)
//   PANDOC_PATH  … pandoc 実行ファイル (未指定時は PATH を探索)
//
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import puppeteer from 'puppeteer-core';
import { findChrome, findPandoc, escapeHtml, preprocess, warnIfFontMissing } from './common.mjs';

const SCDIR = path.dirname(fileURLToPath(import.meta.url));

// ---- 引数 ----
const raw = process.argv.slice(2);
const pos = []; let ref = null, shift = '-1', font = null, requireExternal = false;
for (let i = 0; i < raw.length; i++) {
  const a = raw[i];
  if (a === '--reference') ref = raw[++i];
  else if (a.startsWith('--reference=')) ref = a.slice('--reference='.length);
  else if (a === '--shift') shift = raw[++i];
  else if (a.startsWith('--shift=')) shift = a.slice('--shift='.length);
  else if (a === '--font') font = raw[++i];
  else if (a.startsWith('--font=')) font = a.slice('--font='.length);
  else if (a === '--require-external') requireExternal = true;
  else if (a.startsWith('--')) { /* ignore */ }
  else pos.push(a);
}
const SRC = pos[0], OUT = pos[1];
if (!SRC || !OUT) {
  console.error('usage: node md2docx.mjs <in.md> <out.docx> [--reference ref.docx] [--shift -1] [--font "family"] [--require-external]');
  process.exit(1);
}

// ---- プリフライト (欠けていれば早期に案内して中止) ----
const chrome = findChrome();
const pandoc = findPandoc();
const mermaidFont = font || '"Noto Sans CJK JP","Noto Sans",sans-serif';
warnIfFontMissing(mermaidFont);

// ---- 前処理 (frontmatter 除去 + publish:exclude 除去 + audience ガード) ----
const rawSource = fs.readFileSync(SRC, 'utf8');
const { body: preprocessed, audience, excludedRegions } = preprocess(rawSource, { requireExternal });
console.log(`audience: ${audience}${excludedRegions ? `  (publish:exclude ${excludedRegions} 区間を除去)` : ''}`);
const lines = preprocessed.split('\n');

// ```mermaid ... ``` ブロックを抽出
const blocks = [];
for (let i = 0; i < lines.length; i++) {
  if (/^```+\s*mermaid\s*$/.test(lines[i])) {
    const start = i; const buf = [];
    i++;
    while (i < lines.length && !/^```+\s*$/.test(lines[i])) { buf.push(lines[i]); i++; }
    blocks.push({ start, end: i, code: buf.join('\n') });
  }
}

const assetDir = fs.mkdtempSync(path.join(os.tmpdir(), 'md2docx-'));
const mermaidJs = fs.readFileSync(path.join(SCDIR, '..', 'node_modules/mermaid/dist/mermaid.min.js'), 'utf8');

async function renderMermaid() {
  if (blocks.length === 0) return [];
  const browser = await puppeteer.launch({
    executablePath: chrome, headless: true,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none'],
  });
  const results = [];
  try {
    for (let k = 0; k < blocks.length; k++) {
      const page = await browser.newPage();
      await page.setViewport({ width: 1600, height: 1200, deviceScaleFactor: 3 });
      const html = `<!doctype html><html lang="ja"><head><meta charset="utf-8"><style>
        body{margin:0;background:#fff} pre.mermaid{display:inline-block;background:#fff;padding:6px;margin:0}
        </style></head><body>
        <pre class="mermaid">${escapeHtml(blocks[k].code)}</pre>
        <script>${mermaidJs}</script>
        <script>(async()=>{try{mermaid.initialize({startOnLoad:false,theme:'default',securityLevel:'loose',
          fontFamily:${JSON.stringify(mermaidFont)},
          flowchart:{useMaxWidth:false,htmlLabels:true},sequence:{useMaxWidth:false},er:{useMaxWidth:false}});
          await mermaid.run({querySelector:'pre.mermaid'});window.__d=true;}
          catch(e){window.__e=String((e&&e.stack)||e);window.__d=true;}})();</script>
        </body></html>`;
      await page.setContent(html, { waitUntil: 'load' });
      await page.waitForFunction('window.__d===true', { timeout: 60000 });
      const err = await page.evaluate(() => window.__e || null);
      const el = await page.$('pre.mermaid svg');
      if (err || !el) {
        console.error(`mermaid ERROR (block ${k + 1}):\n${err || 'svg 未生成'}`);
        process.exitCode = 1; results.push(null); await page.close(); continue;
      }
      const box = await el.boundingBox();
      const png = path.join(assetDir, `diagram-${String(k + 1).padStart(2, '0')}.png`);
      await el.screenshot({ path: png });
      const widthCm = Math.min((box.width / 96) * 2.54, 16); // A4 本文幅に収める
      results.push({ png, widthCm });
      await page.close();
    }
  } finally { await browser.close(); }
  return results;
}

const rendered = await renderMermaid();
console.log(`mermaid: ${blocks.length} ブロック描画`);

// ```mermaid ブロックを ![](png){width=..} に差し替えた作業用 md を生成
const startIdx = new Map(blocks.map((b, idx) => [b.start, idx]));
const out = [];
for (let i = 0; i < lines.length; i++) {
  if (startIdx.has(i)) {
    const idx = startIdx.get(i);
    const r = rendered[idx];
    if (r) out.push(`![](${r.png}){width=${r.widthCm.toFixed(1)}cm}`);
    i = blocks[idx].end; // 閉じフェンスまでスキップ (for が +1 する)
    continue;
  }
  out.push(lines[i]);
}
const workMd = path.join(assetDir, 'work.md');
fs.writeFileSync(workMd, out.join('\n'));

// pandoc
const args = ['-f', 'markdown', workMd, '-o', OUT,
  `--shift-heading-level-by=${shift}`, '--resource-path', assetDir];
if (ref) args.push(`--reference-doc=${path.resolve(ref)}`);
execFileSync(pandoc, args, { stdio: 'inherit' });

console.log(`WROTE ${OUT} (${Math.round(fs.statSync(OUT).size / 1024)} KB) — ${blocks.filter((_, i) => rendered[i]).length} 図を挿入`);
fs.rmSync(assetDir, { recursive: true, force: true });
