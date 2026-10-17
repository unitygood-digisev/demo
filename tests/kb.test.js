// 驗收：公司知識庫搜尋與篩選（node --test tests/*.test.js）
const test = require('node:test');
const assert = require('node:assert');
const KB = require('../platform/lib/kb.js');

const items = [
  { id: '1', kind: 'COMPANY_FACT', name: '永續報告書撰寫', category: '服務項目', detail: '依 GRI 準則協助資料蒐集與撰寫', dataLevel: '公開', updatedDate: '2026/10/01' },
  { id: '2', kind: 'KNOWLEDGE_ENTRY', name: '碳盤查啟動會議 SOP', entryType: 'SOP', summary: '啟動會議要確認組織邊界', tags: '碳盤查,ISO 14064', dataLevel: '內部一般', updatedDate: '2026/10/10' },
];

test('關鍵字可搜尋到公司資料與知識條目', () => {
  assert.deepStrictEqual(KB.filterItems(items, { query: 'GRI' }).map((i) => i.id), ['1']);
  assert.deepStrictEqual(KB.filterItems(items, { query: 'iso 14064' }).map((i) => i.id), ['2']);
  assert.deepStrictEqual(KB.filterItems(items, { query: '組織邊界' }).map((i) => i.id), ['2']);
});

test('分類篩選與取消；依更新日新到舊', () => {
  assert.deepStrictEqual(KB.filterItems(items, { kind: 'COMPANY_FACT' }).map((i) => i.id), ['1']);
  assert.deepStrictEqual(KB.filterItems(items, { subtype: 'SOP' }).map((i) => i.id), ['2']);
  assert.deepStrictEqual(KB.filterItems(items, {}).map((i) => i.id), ['2', '1']);
});

test('內部敏感與客戶機密顯示警示', () => {
  assert.ok(KB.isSensitive('內部敏感'));
  assert.ok(KB.isSensitive('客戶機密'));
  assert.ok(!KB.isSensitive('內部一般'));
  assert.strictEqual(KB.SENSITIVE_WARNING, '此等級只建議存摘要與索取方式，不要存客戶名稱、金額或機密全文');
});
