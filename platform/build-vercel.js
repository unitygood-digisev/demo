// 產生 Vercel 網站版：唯讀快照＋密碼保護。
// 用法：node platform/build-vercel.js <快照資料夾>
// 快照資料夾是用 ArtifactData list 加 out_dir 匯出的 <集合>/<文件>.json；不含 projects、invoices（金額）。
const fs = require('fs');
const path = require('path');

const snapDir = process.argv[2];
if (!snapDir) { console.error('請指定快照資料夾'); process.exit(1); }
const dir = __dirname;
const site = path.join(dir, '..', 'site');
const read = (p) => fs.readFileSync(path.join(dir, p), 'utf8');

const COLS = ['modules', 'initiatives', 'tasks', 'milestones', 'docs', 'routines', 'notes', 'kb'];
function loadCol(name) {
  const d = path.join(snapDir, name);
  if (!fs.existsSync(d)) return [];
  return fs.readdirSync(d).filter((f) => f.endsWith('.json'))
    .map((f) => ({ id: f.slice(0, -5), ...JSON.parse(fs.readFileSync(path.join(d, f), 'utf8')) }));
}
const metaFile = path.join(snapDir, 'hub', 'meta.json');
const snapshot = {
  exportedAt: process.env.SNAPSHOT_DATE || new Date().toISOString().slice(0, 10).replace(/-/g, '/'),
  meta: fs.existsSync(metaFile) ? JSON.parse(fs.readFileSync(metaFile, 'utf8')) : null,
};
for (const c of COLS) snapshot[c] = loadCol(c);

const body = read('page.html')
  .replace('<script>\n/*__CALC__*/', '<script src="snapshot.js"></script>\n<script>\n/*__CALC__*/')
  .replace('/*__CALC__*/', () => read('lib/calc.js'))
  .replace('/*__KB__*/', () => read('lib/kb.js'))
  .replace('/*__HUB__*/', () => read('lib/hub.js'))
  .replace('/*__UI__*/', () => read('ui.js'));
// Artifact 發布時會自動包上的外框，網站版要自己加。
const html = `<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head><body>
${body}
</body></html>
`;

fs.mkdirSync(site, { recursive: true });
fs.writeFileSync(path.join(site, 'index.html'), html);
fs.writeFileSync(path.join(site, 'snapshot.js'), `window.__UDP_SNAPSHOT__ = ${JSON.stringify(snapshot)};\n`);
console.log(`site/index.html ${html.length} chars; snapshot ${COLS.map((c) => `${c} ${snapshot[c].length}`).join('、')}`);
