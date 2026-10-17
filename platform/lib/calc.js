// 管理層總覽面板：計算與匯入規則。全部是固定公式，不呼叫任何大模型或外部服務。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.MgmtCalc = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const DAY = 24 * 60 * 60 * 1000;
  const PROJECT_STATUSES = ['進行中', '待結案', '已結案'];
  const INVOICE_STATUSES = ['已請款', '已收款', '逾期'];

  const PROJECT_FIELDS = [
    { key: 'name', label: '專案名稱', type: 'string', required: true, aliases: ['專案', '名稱', 'project'] },
    { key: 'clientCode', label: '客戶代號', type: 'string', aliases: ['客戶', 'client'] },
    { key: 'contractNo', label: '合約編號', type: 'string', required: true, aliases: ['合約號', '契約編號', 'contract'] },
    { key: 'contractAmount', label: '合約總額', type: 'number', aliases: ['合約金額', '總額', 'amount'] },
    { key: 'signedDate', label: '簽約日', type: 'date', aliases: ['簽約日期'] },
    { key: 'dueDate', label: '合約到期日', type: 'date', aliases: ['到期日', '合約迄日'] },
    { key: 'progress', label: '進度', type: 'number', aliases: ['進度%', '目前進度', 'progress'] },
    { key: 'status', label: '狀態', type: 'string', aliases: ['status'] },
    { key: 'note', label: '備註', type: 'string', aliases: ['note'] },
  ];

  const INVOICE_FIELDS = [
    { key: 'projectName', label: '專案名稱', type: 'string', required: true, aliases: ['專案', 'project'] },
    { key: 'period', label: '請款期別', type: 'string', required: true, aliases: ['期別', '期數'] },
    { key: 'amount', label: '請款金額', type: 'number', aliases: ['金額'] },
    { key: 'requestDate', label: '請款日', type: 'date', aliases: ['請款日期'] },
    { key: 'dueDate', label: '應收日', type: 'date', aliases: ['應收日期', '付款期限'] },
    { key: 'receivedDate', label: '實收日', type: 'date', aliases: ['收款日', '實收日期'] },
    { key: 'receivedAmount', label: '實收金額', type: 'number', aliases: ['收款金額', '已收金額'] },
    { key: 'status', label: '狀態', type: 'string', aliases: ['status'] },
  ];

  function pad(n) { return String(n).padStart(2, '0'); }

  function startOfDay(d) { return new Date(d.getFullYear(), d.getMonth(), d.getDate()); }

  // 接受 YYYY/MM/DD、YYYY-MM-DD、YYYY.MM.DD、Date 物件與 Excel 日期序號；回傳 Date 或 null。
  function parseDate(value) {
    if (value === null || value === undefined || value === '') return null;
    if (value instanceof Date) return isNaN(value) ? null : startOfDay(value);
    if (typeof value === 'number') {
      if (value < 1 || value > 2958465) return null;
      const d = new Date(Math.round((value - 25569) * DAY));
      return new Date(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
    }
    const m = String(value).trim().match(/^(\d{4})[\/\-.](\d{1,2})[\/\-.](\d{1,2})$/);
    if (!m) return undefined;
    const y = +m[1], mo = +m[2], da = +m[3];
    const d = new Date(y, mo - 1, da);
    if (d.getFullYear() !== y || d.getMonth() !== mo - 1 || d.getDate() !== da) return undefined;
    return d;
  }

  function formatDate(d) {
    if (!d) return '';
    return `${d.getFullYear()}/${pad(d.getMonth() + 1)}/${pad(d.getDate())}`;
  }

  // 正規化日期字串；空值回傳 ''，無法辨識回傳 undefined。
  function normalizeDate(value) {
    const d = parseDate(value);
    if (d === undefined) return undefined;
    return d ? formatDate(d) : '';
  }

  // 去掉 NT$、逗號、空白與 %；空值回傳 null，無法辨識回傳 undefined。
  function parseNumber(value) {
    if (value === null || value === undefined || value === '') return null;
    if (typeof value === 'number') return isFinite(value) ? value : undefined;
    const s = String(value).replace(/NT\$|\$|元|,|，|%|\s/gi, '');
    if (s === '') return null;
    const n = Number(s);
    return isFinite(n) ? n : undefined;
  }

  function daysBetween(from, to) {
    return Math.round((startOfDay(to) - startOfDay(from)) / DAY);
  }

  function formatNTD(n) {
    const v = Math.round(Number(n) || 0);
    return 'NT$ ' + v.toLocaleString('en-US');
  }

  function invoiceOverdue(inv, today) {
    const amount = Number(inv.amount) || 0;
    const received = Number(inv.receivedAmount) || 0;
    const due = parseDate(inv.dueDate);
    if (!(amount > 0) || received >= amount || !due) return null;
    const days = daysBetween(due, today);
    if (days <= 0) return null;
    return { days, owed: amount - received };
  }

  function invoiceDisplayStatus(inv, today) {
    const amount = Number(inv.amount) || 0;
    if (amount > 0 && (Number(inv.receivedAmount) || 0) >= amount) return '已收款';
    if (invoiceOverdue(inv, today)) return '逾期';
    return inv.status && INVOICE_STATUSES.includes(inv.status) && inv.status !== '已收款' && inv.status !== '逾期'
      ? inv.status : '已請款';
  }

  function computeProject(project, invoices, today) {
    const own = invoices.filter((i) => i.projectId === project.id);
    const contract = Number(project.contractAmount) || 0;
    const billed = own.reduce((s, i) => s + (Number(i.amount) || 0), 0);
    const received = own.reduce((s, i) => s + (Number(i.receivedAmount) || 0), 0);
    const due = parseDate(project.dueDate);
    return {
      billed,
      received,
      unbilled: Math.max(0, contract - billed),
      outstanding: Math.max(0, billed - received),
      billingProgress: contract > 0 ? (billed / contract) * 100 : 0,
      daysToDue: due ? daysBetween(today, due) : null,
      invoices: own,
    };
  }

  // 嚴重度：0 最急。依嚴重度、再依天數或差距排序。
  // publicMessage 不含金額，供週報與知識顧問使用；沒有另外指定時與 message 相同。
  function computeAll(projects, invoices, today) {
    today = startOfDay(today || new Date());
    const rows = projects.map((p) => ({ ...p, metrics: computeProject(p, invoices, today) }));
    const alerts = [];
    let overdueTotal = 0;

    for (const p of rows) {
      for (const inv of p.metrics.invoices) {
        const od = invoiceOverdue(inv, today);
        if (od) {
          overdueTotal += od.owed;
          alerts.push({
            type: 'overdue', severity: 0, projectId: p.id, sortKey: -od.days,
            title: '應收逾期',
            message: `${p.name}／${inv.period}：逾期 ${od.days} 天，尚欠 ${formatNTD(od.owed)}`,
            publicMessage: `${p.name}／${inv.period}：逾期 ${od.days} 天`,
          });
        }
      }
      const d = p.metrics.daysToDue;
      if (d !== null && p.status !== '已結案') {
        if (d < 0) {
          alerts.push({
            type: 'expired', severity: 0, projectId: p.id, sortKey: d,
            title: '合約已到期', message: `${p.name}：合約已到期 ${-d} 天`,
          });
        } else if (d <= 90) {
          alerts.push({
            type: 'expiring', severity: 1, projectId: p.id, sortKey: d,
            title: '合約即將到期', message: `${p.name}：合約 ${d} 天後到期（${p.dueDate}）`,
          });
        }
      }
      const gap = (Number(p.progress) || 0) - p.metrics.billingProgress;
      if (gap >= 20) {
        alerts.push({
          type: 'lagging', severity: 2, projectId: p.id, sortKey: -gap,
          title: '請款落後',
          message: `${p.name}：進度 ${Math.round(Number(p.progress) || 0)}%，請款進度 ${Math.round(p.metrics.billingProgress)}%，落後 ${Math.round(gap)} 個百分點`,
        });
      }
    }
    for (const a of alerts) if (!a.publicMessage) a.publicMessage = a.message;
    alerts.sort((a, b) => a.severity - b.severity || a.sortKey - b.sortKey);

    const totals = {
      contractAmount: rows.reduce((s, p) => s + (Number(p.contractAmount) || 0), 0),
      billed: rows.reduce((s, p) => s + p.metrics.billed, 0),
      outstanding: rows.reduce((s, p) => s + p.metrics.outstanding, 0),
      overdue: overdueTotal,
    };
    return { projects: rows, alerts, totals };
  }

  // 依欄位對映把一列原始資料轉成記錄；回傳 { record } 或 { error }。
  function mapRow(raw, mapping, fields) {
    const record = {};
    const errors = [];
    for (const f of fields) {
      const src = mapping[f.key];
      const value = src === undefined || src === '' ? undefined : raw[src];
      if (f.type === 'number') {
        const n = parseNumber(value);
        if (n === undefined) errors.push(`${f.label}「${value}」不是數字`);
        else if (n !== null) record[f.key] = n;
      } else if (f.type === 'date') {
        const d = normalizeDate(value);
        if (d === undefined) errors.push(`${f.label}「${value}」日期格式無法辨識`);
        else if (d) record[f.key] = d;
      } else if (value !== undefined && value !== null && String(value).trim() !== '') {
        record[f.key] = String(value).trim();
      }
      if (f.required && (record[f.key] === undefined || record[f.key] === '')) {
        errors.push(`缺少${f.label}`);
      }
    }
    if (record.progress !== undefined && (record.progress < 0 || record.progress > 100)) {
      errors.push('進度必須介於 0–100');
    }
    return errors.length ? { error: errors.join('；') } : { record };
  }

  function guessMapping(headers, fields) {
    const mapping = {};
    const norm = (s) => String(s).replace(/[\s（）()％%]/g, '').toLowerCase();
    for (const f of fields) {
      const names = [f.label, f.key, ...(f.aliases || [])].map(norm);
      const hit = headers.find((h) => names.includes(norm(h)));
      if (hit !== undefined) mapping[f.key] = hit;
    }
    return mapping;
  }

  let idCounter = 0;
  function newId(prefix) {
    idCounter += 1;
    return `${prefix}_${Date.now().toString(36)}_${idCounter.toString(36)}`;
  }

  // 專案以合約編號為鍵；找不到時再找由請款匯入自動建立、尚無合約編號的同名專案。
  function upsertProjects(store, records) {
    let created = 0, updated = 0;
    for (const r of records) {
      let p = store.projects.find((x) => x.contractNo && x.contractNo === r.contractNo);
      if (!p) p = store.projects.find((x) => !x.contractNo && x.name === r.name);
      if (p) { Object.assign(p, r); updated += 1; }
      else { store.projects.push({ id: newId('prj'), status: '進行中', progress: 0, ...r }); created += 1; }
    }
    return { created, updated };
  }

  // 請款以「專案名稱＋期別」為鍵；專案不存在時先建立專案。
  function upsertInvoices(store, records) {
    let created = 0, updated = 0, projectsCreated = 0;
    for (const r of records) {
      let p = store.projects.find((x) => x.name === r.projectName);
      if (!p) {
        p = { id: newId('prj'), name: r.projectName, contractNo: '', status: '進行中', progress: 0 };
        store.projects.push(p);
        projectsCreated += 1;
      }
      const rec = { ...r, projectId: p.id };
      const inv = store.invoices.find((x) => x.projectName === r.projectName && x.period === r.period);
      if (inv) { Object.assign(inv, rec); updated += 1; }
      else { store.invoices.push({ id: newId('inv'), ...rec }); created += 1; }
    }
    return { created, updated, projectsCreated };
  }

  // 給週報彙整員與知識顧問的摘要：只有非金額欄位。
  function buildBriefing(projects, invoices, today) {
    today = startOfDay(today || new Date());
    const data = computeAll(projects, invoices, today);
    return {
      updatedDate: formatDate(today),
      note: '本摘要不含金額與客戶機密；應收逾期只列專案、期別與應收日。',
      projects: data.projects.map((p) => ({
        name: p.name,
        progress: Number(p.progress) || 0,
        billingProgress: Math.round(p.metrics.billingProgress),
        status: p.status || '',
        dueDate: p.dueDate || '',
      })),
      receivables: invoices.map((i) => ({
        projectName: i.projectName,
        period: i.period,
        dueDate: i.dueDate || '',
        settled: (Number(i.amount) || 0) > 0 && (Number(i.receivedAmount) || 0) >= (Number(i.amount) || 0),
      })),
      alerts: data.alerts.map((a) => ({ type: a.type, title: a.title, message: a.publicMessage })),
    };
  }

  return {
    buildBriefing,
    PROJECT_FIELDS, INVOICE_FIELDS, PROJECT_STATUSES, INVOICE_STATUSES,
    parseDate, formatDate, normalizeDate, parseNumber, daysBetween, formatNTD,
    invoiceOverdue, invoiceDisplayStatus, computeProject, computeAll,
    mapRow, guessMapping, upsertProjects, upsertInvoices,
  };
});
