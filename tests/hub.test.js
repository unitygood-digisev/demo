// 驗收：管理中樞的進度、待辦與時程規則（node --test tests/*.test.js）
const test = require('node:test');
const assert = require('node:assert');
const H = require('../platform/lib/hub.js');
const seed = require('../platform/seed/hub-seed.json');

const TODAY = new Date(2026, 10, 4); // 2026/11/04

test('八大系統：3 個完成、5 個未開始', () => {
  const s = H.moduleSummary(seed.modules);
  assert.strictEqual(s.total, 8);
  assert.strictEqual(s.done, 3);
  assert.strictEqual(s.byStatus.notstarted, 5);
});

test('數位轉型進度依時數估計，與 roadmap 一致', () => {
  const p = H.transformationProgress(seed.modules, seed.meta.foundationHours, seed.meta.weeklyHours);
  assert.deepStrictEqual(p.done, { min: 28, max: 36 }); // 階段 0、1、2、4
  assert.deepStrictEqual(p.remaining, { min: 42, max: 70 }); // 系統 2：10–14，其他四個各 8–14
  assert.strictEqual(p.pct, 36);
  assert.ok(p.pctLow < p.pct && p.pct < p.pctHigh);
  assert.deepStrictEqual(p.weeks, { min: 6, max: 12 });
});

test('待辦排序：逾期在前，完成在後', () => {
  const tasks = [
    { title: 'a', status: '完成', due: '2026/10/01' },
    { title: 'b', status: '待辦', priority: '低' },
    { title: 'c', status: '待辦', priority: '中', due: '2026/11/01' },
    { title: 'd', status: '待辦', priority: '高', due: '2026/11/08' },
  ];
  assert.deepStrictEqual(H.sortTasks(tasks, TODAY).map((t) => t.title), ['c', 'd', 'b', 'a']);
  assert.strictEqual(H.taskState(tasks[1], TODAY), 'open');
  assert.strictEqual(H.taskState(tasks[3], TODAY), 'soon');
});

test('待辦篩選與統計', () => {
  const open = H.filterTasks(seed.tasks, { status: '未完成' });
  assert.ok(open.length > 0 && open.every((t) => t.status !== '完成'));
  const s = H.taskSummary(seed.tasks, TODAY);
  assert.strictEqual(s.open + s.done, seed.tasks.length);
  assert.ok(s.decisions >= 5);
  for (const t of seed.tasks) {
    assert.ok(H.TASK_STATUS.includes(t.status), t.title);
    assert.ok(H.OWNERS.includes(t.owner), t.owner);
    assert.ok(H.PRIORITY.includes(t.priority), t.title);
  }
});

test('時程分成已發生與即將到來；只有月份的視為當月', () => {
  const { past, upcoming } = H.splitMilestones([
    { date: '2026/10/15', title: 'x' }, { date: '2027/04', title: 'y' }, { date: '2026/11/03', end: '2026/11/30', title: 'z' },
  ], TODAY);
  assert.deepStrictEqual(past.map((m) => m.title), ['x']);
  assert.deepStrictEqual(upcoming.map((m) => m.title), ['z', 'y']);
});

test('種子資料彼此對得上', () => {
  const areas = new Set([...seed.modules.map((m) => m.id), ...seed.initiatives.map((i) => i.id), 'platform']);
  for (const t of seed.tasks) assert.ok(areas.has(t.area), `${t.title} → ${t.area}`);
  const ids = seed.tasks.map((t) => t.id);
  assert.strictEqual(new Set(ids).size, ids.length);
});

test('只寫月份的期限以月底計算', () => {
  const t = { status: '待辦', due: '2026/12' };
  assert.strictEqual(H.taskState(t, new Date(2026, 11, 26)), 'soon');
  assert.strictEqual(H.taskState(t, new Date(2026, 11, 2)), 'open');
  assert.strictEqual(H.taskState(t, new Date(2027, 0, 2)), 'overdue');
});

test('步驟分類與總控試算表上色規則一致', () => {
  assert.strictEqual(H.stepClass('已完成'), 'done');
  for (const s of ['未開始', '未到時程', '待辦', '可開始', '可開始（資料不全）', '等待決定']) assert.strictEqual(H.stepClass(s), 'todo', s);
  for (const s of ['進行中', '修訂清單已核定', '提示詞草稿', '可試用']) assert.strictEqual(H.stepClass(s), 'doing', s);
  const db = seed.initiatives.find((i) => i.id === 'ulddb');
  assert.deepStrictEqual(H.stepSummary(db.steps), { total: 25, done: 4, doing: 6, todo: 15 });
});
