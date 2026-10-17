// 驗收：管理層總覽面板計算規則（node --test tests/）
const test = require('node:test');
const assert = require('node:assert');
const C = require('../platform/lib/calc.js');

const TODAY = new Date(2026, 9, 17); // 2026/10/17

function fixture() {
  const store = { projects: [], invoices: [] };
  const projects = [
    { name: '報告書專案', clientCode: 'C001', contractNo: 'K-001', contractAmount: '1,200,000', signedDate: '2026-01-05', dueDate: '2026/12/16', progress: '80', status: '進行中' },
    { name: '碳盤查專案', clientCode: 'C002', contractNo: 'K-002', contractAmount: 500000, signedDate: '2026.03.01', dueDate: '2027/09/30', progress: 30, status: '進行中' },
  ];
  const invoices = [
    { projectName: '報告書專案', period: '第 1 期', amount: 600000, requestDate: '2026/03/01', dueDate: '2026/04/01', receivedDate: '2026/03/28', receivedAmount: 600000 },
    { projectName: '碳盤查專案', period: '第 1 期', amount: 200000, requestDate: '2026/09/01', dueDate: '2026/10/16', receivedAmount: 50000 },
    { projectName: '碳盤查專案', period: '第 2 期', amount: 100000, requestDate: '2026/10/01', dueDate: '2026/11/30' },
  ];
  const pf = C.PROJECT_FIELDS, inf = C.INVOICE_FIELDS;
  const ident = (fields) => Object.fromEntries(fields.map((f) => [f.key, f.key]));
  const pRecs = projects.map((r) => C.mapRow(r, ident(pf), pf)).map((x) => { assert.ok(x.record, x.error); return x.record; });
  const iRecs = invoices.map((r) => C.mapRow(r, ident(inf), inf)).map((x) => { assert.ok(x.record, x.error); return x.record; });
  return { store, pRecs, iRecs };
}

test('四個總覽數字與手算一致', () => {
  const { store, pRecs, iRecs } = fixture();
  C.upsertProjects(store, pRecs);
  C.upsertInvoices(store, iRecs);
  const { totals } = C.computeAll(store.projects, store.invoices, TODAY);
  assert.strictEqual(totals.contractAmount, 1700000);
  assert.strictEqual(totals.billed, 900000);
  assert.strictEqual(totals.outstanding, 250000); // 0 + (300000 - 50000)
  assert.strictEqual(totals.overdue, 150000); // 碳盤查第 1 期，應收日昨天
});

test('三類警示：應收逾期、合約即將到期、請款落後', () => {
  const { store, pRecs, iRecs } = fixture();
  C.upsertProjects(store, pRecs);
  C.upsertInvoices(store, iRecs);
  const { alerts } = C.computeAll(store.projects, store.invoices, TODAY);
  const types = alerts.map((a) => a.type);
  assert.deepStrictEqual(types, ['overdue', 'expiring', 'lagging']);
  assert.match(alerts[0].message, /逾期 1 天，尚欠 NT\$ 150,000/);
  assert.match(alerts[1].message, /60 天後到期/);
  assert.match(alerts[2].message, /進度 80%，請款進度 50%/);
});

test('合約已到期', () => {
  const store = { projects: [{ id: 'p', name: 'X', contractNo: 'K', dueDate: '2026/10/01', progress: 0, status: '進行中' }], invoices: [] };
  const { alerts } = C.computeAll(store.projects, store.invoices, TODAY);
  assert.strictEqual(alerts[0].type, 'expired');
  assert.strictEqual(alerts[0].severity, 0);
});

test('重複匯入不產生重複專案或請款', () => {
  const { store, pRecs, iRecs } = fixture();
  C.upsertProjects(store, pRecs);
  C.upsertInvoices(store, iRecs);
  const r1 = C.upsertProjects(store, pRecs);
  const r2 = C.upsertInvoices(store, iRecs);
  assert.deepStrictEqual(r1, { created: 0, updated: 2 });
  assert.deepStrictEqual(r2, { created: 0, updated: 3, projectsCreated: 0 });
  assert.strictEqual(store.projects.length, 2);
  assert.strictEqual(store.invoices.length, 3);
});

test('請款先匯入時自動建立專案，之後專案匯入補上合約資料', () => {
  const { store, pRecs, iRecs } = fixture();
  const r = C.upsertInvoices(store, iRecs);
  assert.strictEqual(r.projectsCreated, 2);
  C.upsertProjects(store, pRecs);
  assert.strictEqual(store.projects.length, 2);
  assert.ok(store.projects.every((p) => p.contractNo));
});

test('日期與數字解析', () => {
  assert.strictEqual(C.normalizeDate('2026-1-5'), '2026/01/05');
  assert.strictEqual(C.normalizeDate('2026.12.31'), '2026/12/31');
  assert.strictEqual(C.normalizeDate('2026/02/30'), undefined);
  assert.strictEqual(C.normalizeDate(46312), '2026/10/17'); // Excel 日期序號
  assert.strictEqual(C.parseNumber('NT$ 1,200,000'), 1200000);
  assert.strictEqual(C.parseNumber('abc'), undefined);
  assert.strictEqual(C.formatNTD(1200000), 'NT$ 1,200,000');
});

test('匯入失敗原因', () => {
  const r = C.mapRow({ a: '專案', b: '', c: '2026/13/01' }, { name: 'a', contractNo: 'b', dueDate: 'c' }, C.PROJECT_FIELDS);
  assert.match(r.error, /合約到期日.*無法辨識/);
  assert.match(r.error, /缺少合約編號/);
});

test('週報摘要不含金額', () => {
  const { store, pRecs, iRecs } = fixture();
  C.upsertProjects(store, pRecs);
  C.upsertInvoices(store, iRecs);
  const b = C.buildBriefing(store.projects, store.invoices, TODAY);
  const text = JSON.stringify(b);
  assert.ok(!/NT\$|1200000|600000|150000|contractAmount|amount/i.test(text), text);
  assert.strictEqual(b.alerts.length, 3);
  assert.strictEqual(b.alerts[0].message, '碳盤查專案／第 1 期：逾期 1 天');
  assert.strictEqual(b.receivables.filter((r) => !r.settled).length, 2);
});
