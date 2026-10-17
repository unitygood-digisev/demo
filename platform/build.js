// 把 lib 與 ui.js 內嵌進 page.html，產生可直接發布成 Claude Artifact 的單一檔案。
// 用法：node platform/build.js
const fs = require('fs');
const path = require('path');

const dir = __dirname;
const read = (p) => fs.readFileSync(path.join(dir, p), 'utf8');
const html = read('page.html')
  .replace('/*__CALC__*/', () => read('lib/calc.js'))
  .replace('/*__KB__*/', () => read('lib/kb.js'))
  .replace('/*__UI__*/', () => read('ui.js'));

fs.mkdirSync(path.join(dir, 'dist'), { recursive: true });
const out = path.join(dir, 'dist', 'decision-platform.html');
fs.writeFileSync(out, html);
console.log(`wrote ${path.relative(process.cwd(), out)} (${html.length} chars)`);
