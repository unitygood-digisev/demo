// 優樂地管理中樞：八大系統、數位轉型進度、待辦與時程的計算。全部是固定規則，不呼叫大模型。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.Hub = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const MODULE_STATUS = {
    live: { label: '上線中', tone: 'good', done: true },
    done: { label: '已完成', tone: 'good', done: true },
    built: { label: '程式完成', tone: 'good', done: true },
    building: { label: '開發中', tone: 'info', done: false },
    planned: { label: '已排定', tone: 'info', done: false },
    notstarted: { label: '未開始', tone: 'idle', done: false },
  };
  const STAGES = ['規格', '計畫', '程式', '測試', '上線'];

  const TASK_STATUS = ['待辦', '進行中', '等待決定', '等待資料', '完成'];
  const PRIORITY = ['高', '中', '低'];
  const OWNERS = ['執行長', '副執行長', '副營運長', '各部門主管', '品牌行銷部', '公司管理員', '專案負責人', '資料管理員', '實習生'];

  function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }
  function parseDate(s) {
    if (!s) return null;
    const m = String(s).match(/^(\d{4})[\/\-.](\d{1,2})(?:[\/\-.](\d{1,2}))?$/);
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, m[3] ? +m[3] : 1);
  }
  function daysBetween(a, b) { return Math.round((startOfDay(b) - startOfDay(a)) / 86400000); }

  function isDone(m) { return Boolean((MODULE_STATUS[m.status] || {}).done); }

  // 系統數量與狀態分布
  function moduleSummary(modules) {
    const byStatus = {};
    for (const m of modules) byStatus[m.status] = (byStatus[m.status] || 0) + 1;
    const done = modules.filter(isDone).length;
    return { total: modules.length, done, notDone: modules.length - done, byStatus };
  }

  // 數位轉型進度：已完成工作的估計時數 ÷（已完成 + 剩下）。
  // 低值＝已完成取下限、剩下取上限；高值反過來；中間值兩邊都取中點。
  // extraDone 是不屬於任何系統、但已完成的共用工作（例如階段 0 骨架）。
  function transformationProgress(modules, extraDone = { min: 0, max: 0 }, weeklyHours = { min: 6, max: 8 }) {
    const sum = (list, k) => list.reduce((s, m) => s + (Number((m.hours || {})[k]) || 0), 0);
    const doneList = modules.filter(isDone);
    const todoList = modules.filter((m) => !isDone(m));
    const done = { min: sum(doneList, 'min') + (extraDone.min || 0), max: sum(doneList, 'max') + (extraDone.max || 0) };
    const remaining = { min: sum(todoList, 'min'), max: sum(todoList, 'max') };
    const pct = (d, r) => (d + r > 0 ? Math.round((d / (d + r)) * 100) : 0);
    const mid = (o) => (o.min + o.max) / 2;
    return {
      done, remaining,
      pct: pct(mid(done), mid(remaining)),
      pctLow: pct(done.min, remaining.max),
      pctHigh: pct(done.max, remaining.min),
      weeks: {
        min: weeklyHours.max > 0 ? Math.ceil(remaining.min / weeklyHours.max) : null,
        max: weeklyHours.min > 0 ? Math.ceil(remaining.max / weeklyHours.min) : null,
      },
    };
  }

  // 待辦：逾期、近期與排序（未完成在前；優先度高在前；有期限的依期限）
  function taskState(t, today) {
    if (t.status === '完成') return 'done';
    const due = parseDate(t.due);
    if (!due) return 'open';
    const d = daysBetween(today, due);
    if (d < 0) return 'overdue';
    if (d <= 7) return 'soon';
    return 'open';
  }
  function sortTasks(tasks, today) {
    const rank = { overdue: 0, soon: 1, open: 2, done: 3 };
    const pr = (p) => { const i = PRIORITY.indexOf(p); return i < 0 ? 9 : i; };
    return [...tasks].sort((a, b) => {
      const sa = taskState(a, today), sb = taskState(b, today);
      if (rank[sa] !== rank[sb]) return rank[sa] - rank[sb];
      if (pr(a.priority) !== pr(b.priority)) return pr(a.priority) - pr(b.priority);
      return String(a.due || '9999').localeCompare(String(b.due || '9999'));
    });
  }
  function filterTasks(tasks, { owner = null, status = null, area = null, kind = null, query = '' } = {}) {
    const q = query.trim().toLowerCase();
    return tasks.filter((t) =>
      (!owner || t.owner === owner) &&
      (!status || (status === '未完成' ? t.status !== '完成' : t.status === status)) &&
      (!area || t.area === area) &&
      (!kind || t.kind === kind) &&
      (!q || [t.title, t.note, t.source].join('\n').toLowerCase().includes(q)));
  }
  function taskSummary(tasks, today) {
    const open = tasks.filter((t) => t.status !== '完成');
    return {
      open: open.length,
      done: tasks.length - open.length,
      decisions: open.filter((t) => t.kind === '決策').length,
      overdue: open.filter((t) => taskState(t, today) === 'overdue').length,
      soon: open.filter((t) => taskState(t, today) === 'soon').length,
    };
  }

  // 時程：依日期排序，分成已發生與即將到來；只有月份的里程碑以當月 1 日排序
  function splitMilestones(milestones, today) {
    const sorted = [...milestones].sort((a, b) => String(a.date).localeCompare(String(b.date)));
    const t = startOfDay(today);
    const past = [], upcoming = [];
    for (const m of sorted) {
      const end = parseDate(m.end || m.date);
      (end && end < t ? past : upcoming).push(m);
    }
    return { past, upcoming };
  }

  return {
    MODULE_STATUS, STAGES, TASK_STATUS, PRIORITY, OWNERS,
    parseDate, daysBetween, isDone, moduleSummary, transformationProgress,
    taskState, sortTasks, filterTasks, taskSummary, splitMilestones,
  };
});
