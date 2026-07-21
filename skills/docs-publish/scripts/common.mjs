// docs-publish 共通ヘルパー。md2pdf / md2docx で共有する。
//   - Chrome/Chromium・pandoc の探索 (環境変数 or 既知パス)
//   - frontmatter 除去・publish:exclude 区間除去 (ADR-0012: 配布物にメタ/内部限定部分を出さない)
//   - audience の検出と fail-closed ガード (external 明示のみ外部配布可)
//   - CJK フォントのプリフライト (未導入だと日本語が豆腐になるため事前警告)
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';

// ---- ブラウザ探索 (自前 DL しない puppeteer-core が使う実行ファイル) ----
export function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const candidates = [
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium', '/usr/bin/chromium-browser',
    '/snap/bin/chromium', '/var/lib/flatpak/exports/bin/org.chromium.Chromium',
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ];
  for (const c of candidates) { try { if (fs.existsSync(c)) return c; } catch { /* noop */ } }
  throw new Error(
    'Chrome/Chromium が見つかりません。CHROME_PATH で実行ファイルを指定してください。\n' +
    '  Debian/Ubuntu: sudo apt-get install -y chromium  (または Google Chrome を導入)\n' +
    '  macOS: brew install --cask google-chrome');
}

export function findPandoc() {
  if (process.env.PANDOC_PATH) return process.env.PANDOC_PATH;
  try { execFileSync('pandoc', ['--version'], { stdio: 'ignore' }); return 'pandoc'; } catch { /* noop */ }
  throw new Error(
    'pandoc が見つかりません。PANDOC_PATH で実行ファイルを指定してください。\n' +
    '  Debian/Ubuntu: sudo apt-get install -y pandoc\n' +
    '  macOS: brew install pandoc\n' +
    '  静的バイナリ: https://github.com/jgm/pandoc/releases');
}

export function escapeHtml(s) {
  return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

// ---- frontmatter 抽出・除去 ----
// 先頭の `---\n ... \n---` を frontmatter として取り出し、本文から落とす。
// 完全な YAML パーサではない (audience 等の単純 key: value を拾う目的)。
export function splitFrontmatter(src) {
  const m = src.match(/^﻿?---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!m) return { meta: {}, body: src, hadFrontmatter: false };
  const meta = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = line.match(/^([A-Za-z0-9_-]+):\s*(.*)$/);
    if (kv) meta[kv[1]] = kv[2].trim().replace(/^["']|["']$/g, '');
  }
  return { meta, body: src.slice(m[0].length), hadFrontmatter: true };
}

// `<!-- publish:begin-exclude -->` ... `<!-- publish:end-exclude -->` 区間を落とす。
// 閉じタグが無い (開きっぱなし) 場合は、意図せぬ全消しを避けるため throw する (fail-closed)。
export function stripPublishExclude(body) {
  const open = /<!--\s*publish:begin-exclude\s*-->/g;
  const close = /<!--\s*publish:end-exclude\s*-->/g;
  const nOpen = (body.match(open) || []).length;
  const nClose = (body.match(close) || []).length;
  if (nOpen !== nClose) {
    throw new Error(`publish:exclude の開閉が不一致 (begin=${nOpen}, end=${nClose})。区間を閉じてください。`);
  }
  let removed = 0;
  const out = body.replace(
    /<!--\s*publish:begin-exclude\s*-->[\s\S]*?<!--\s*publish:end-exclude\s*-->/g,
    () => { removed++; return ''; });
  return { body: out, removed };
}

// audience ガード。requireExternal 時、frontmatter の audience が external 以外なら throw (fail-closed)。
// ADR-0012: 外部配布は audience: external が明示された doc のみ。既定/未設定は internal 扱い。
export function guardAudience(meta, requireExternal) {
  const audience = (meta.audience || 'internal').toLowerCase();
  if (requireExternal && audience !== 'external') {
    throw new Error(
      `--require-external 指定だが frontmatter audience が "${audience}" (external ではない)。\n` +
      '外部配布物は audience: external を明示した doc のみ許可します (fail-closed)。');
  }
  return audience;
}

// 入力 md を publish 用に前処理する: frontmatter 除去 + publish:exclude 除去 + audience ガード。
export function preprocess(src, { requireExternal = false } = {}) {
  const { meta, body: b1 } = splitFrontmatter(src);
  const audience = guardAudience(meta, requireExternal);
  const { body, removed } = stripPublishExclude(b1);
  return { body, meta, audience, excludedRegions: removed };
}

// CJK フォントの存在をベストエフォートで確認 (fc-list があれば)。無ければ null (判定不能)。
export function fontAvailable(family) {
  try {
    const out = execFileSync('fc-list', [], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
    const needle = family.replace(/^["']|["']$/g, '').toLowerCase();
    return out.toLowerCase().includes(needle);
  } catch { return null; }
}

// 既定フォント (テーマの --doc-font 先頭) が入っていなければ警告する。中止はしない。
export function warnIfFontMissing(fontFamily) {
  const primary = fontFamily.split(',')[0].trim();
  const ok = fontAvailable(primary);
  if (ok === false) {
    console.error(
      `WARN: フォント "${primary}" が見つかりません。日本語が豆腐 (□) になる可能性があります。\n` +
      '  Debian/Ubuntu: sudo apt-get install -y fonts-noto-cjk\n' +
      `  または導入済みフォントを --font "<family>" で指定してください (例: fc-list | grep CJK)。`);
  }
}
