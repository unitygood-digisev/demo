// 管理層總覽面板：畫面。資料只存在瀏覽器 localStorage，不呼叫任何外部服務。
(function () {
  'use strict';
  const C = window.MgmtCalc;
  const STORE_KEY = 'mgmt-dashboard-v1';
  const $ = (id) => document.getElementById(id);

  let store = load();
  let selectedId = null;

  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        if (Array.isArray(s.projects) && Array.isArray(s.invoices)) return s;
      }
    } catch (e) { /* 無痕視窗或封鎖儲存時，用空資料 */ }
    return { projects: [], invoices: [] };
  }

  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); }
    catch (e) { alert('瀏覽器無法儲存資料（可能是無痕模式或空間不足），重新整理後資料會消失。'); }
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const pct = (n) => `${Math.round(n)}%`;

  function render() {
    const data = C.computeAll(store.projects, store.invoices, new Date());
    const empty = store.projects.length === 0;
    $('empty').hidden = !empty;
    $('split').hidden = empty;
    $('btnExport').disabled = empty;

    const t = data.totals;
    $('cards').innerHTML = [
      ['合約總額', t.contractAmount, ''],
      ['累計已請款', t.billed, ''],
      ['未收款', t.outstanding, ''],
      ['逾期應收', t.overdue, t.overdue > 0 ? 'warn' : ''],
    ].map(([label, v, cls]) => `<div class="card ${cls}"><div class="label">${label}</div><div class="value">${C.formatNTD(v)}</div></div>`).join('');

    $('alerts').innerHTML = data.alerts.length
      ? data.alerts.map((a) => `<li class="sev${a.severity}" data-id="${esc(a.projectId)}"><span class="tag">${esc(a.title)}</span>${esc(a.message)}</li>`).join('')
      : '<li class="muted" style="cursor:default;border:0">目前沒有需要決定的事。</li>';

    $('projectRows').innerHTML = data.projects.map((p) => `
      <tr data-id="${esc(p.id)}" class="${p.id === selectedId ? 'selected' : ''}">
        <td>${esc(p.clientCode || '—')}</td>
        <td>${esc(p.name)}</td>
        <td class="num">${C.formatNTD(p.contractAmount)}</td>
        <td class="num">${pct(p.metrics.billingProgress)}</td>
        <td>${esc(p.status || '—')}</td>
      </tr>`).join('');

    renderDetail(data);
  }

  function renderDetail(data) {
    const el = $('detail');
    const p = data.projects.find((x) => x.id === selectedId);
    if (!p) { el.innerHTML = '<p class="muted">從左邊選一個專案或警示，查看詳情。</p>'; return; }
    const m = p.metrics;
    const today = new Date();
    const alerts = data.alerts.filter((a) => a.projectId === p.id);
    const invoices = [...m.invoices].sort((a, b) => String(a.requestDate || a.dueDate || '').localeCompare(String(b.requestDate || b.dueDate || '')));

    el.innerHTML = `
      <h2>${esc(p.name)}</h2>
      <h3>合約資訊</h3>
      <dl class="kv">
        <dt>客戶代號</dt><dd>${esc(p.clientCode || '—')}</dd>
        <dt>合約編號</dt><dd>${esc(p.contractNo || '待補（由請款紀錄自動建立）')}</dd>
        <dt>簽約日</dt><dd>${esc(p.signedDate || '—')}</dd>
        <dt>合約到期日</dt><dd>${esc(p.dueDate || '—')}${m.daysToDue === null ? '' : `（${m.daysToDue >= 0 ? `剩 ${m.daysToDue} 天` : `已過 ${-m.daysToDue} 天`}）`}</dd>
        <dt>備註</dt><dd>${esc(p.note || '—')}</dd>
      </dl>
      <h3>金額</h3>
      <dl class="kv">
        <dt>合約總額</dt><dd>${C.formatNTD(p.contractAmount)}</dd>
        <dt>已請款</dt><dd>${C.formatNTD(m.billed)}（${pct(m.billingProgress)}）</dd>
        <dt>未請款</dt><dd>${C.formatNTD(m.unbilled)}</dd>
        <dt>已實收</dt><dd>${C.formatNTD(m.received)}</dd>
        <dt>未收款</dt><dd>${C.formatNTD(m.outstanding)}</dd>
      </dl>
      <h3>警示原因</h3>
      ${alerts.length ? `<ul class="alerts">${alerts.map((a) => `<li class="sev${a.severity}" style="cursor:default"><span class="tag">${esc(a.title)}</span>${esc(a.message)}</li>`).join('')}</ul>` : '<p class="muted">沒有警示。</p>'}
      <h3>更新進度與狀態</h3>
      <div class="edit-row">
        <label class="field" style="margin:0;width:8rem">進度（%）<input type="number" id="editProgress" min="0" max="100" value="${esc(p.progress ?? 0)}"></label>
        <label class="field" style="margin:0;width:9rem">狀態<select id="editStatus">${C.PROJECT_STATUSES.map((s) => `<option ${s === p.status ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
        <button class="btn small" id="btnSaveProject" type="button">儲存</button>
      </div>
      <h3>請款紀錄</h3>
      ${invoices.length ? `<ul class="timeline">${invoices.map((i) => {
        const st = C.invoiceDisplayStatus(i, today);
        return `<li class="${st === '逾期' ? 'overdue' : ''}">
          <strong>${esc(i.period)}</strong> <span class="badge ${st === '逾期' ? 'danger' : ''}">${st}</span><br>
          請款 ${C.formatNTD(i.amount)}${i.requestDate ? `（${esc(i.requestDate)}）` : ''}；應收日 ${esc(i.dueDate || '—')}<br>
          實收 ${C.formatNTD(i.receivedAmount)}${i.receivedDate ? `（${esc(i.receivedDate)}）` : ''}
        </li>`;
      }).join('')}</ul>` : '<p class="muted">尚無請款紀錄。</p>'}`;

    $('btnSaveProject').addEventListener('click', () => {
      const v = C.parseNumber($('editProgress').value);
      if (v === undefined || v === null || v < 0 || v > 100) { alert('進度請填 0–100 的數字。'); return; }
      const target = store.projects.find((x) => x.id === p.id);
      target.progress = v;
      target.status = $('editStatus').value;
      save();
      render();
    });
  }

  function select(id) {
    selectedId = id;
    render();
    if (window.matchMedia('(max-width: 860px)').matches) $('detail').scrollIntoView({ behavior: 'smooth' });
  }

  $('alerts').addEventListener('click', (e) => { const li = e.target.closest('li[data-id]'); if (li) select(li.dataset.id); });
  $('projectRows').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-id]'); if (tr) select(tr.dataset.id); });

  // ---- 匯入 ----
  const dlg = $('importDialog');
  let pending = null; // { type, headers, rows, fields }

  function openImport() {
    pending = null;
    $('importForm').reset();
    $('importStep1').hidden = false;
    $('importStep2').hidden = true;
    $('importStep3').hidden = true;
    $('importConfirm').hidden = true;
    $('importCancel').textContent = '取消';
    dlg.showModal();
  }

  $('btnImport').addEventListener('click', openImport);
  $('btnImportFirst').addEventListener('click', openImport);
  $('importCancel').addEventListener('click', () => dlg.close());
  $('importForm').addEventListener('submit', (e) => e.preventDefault());

  $('importFile').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const buf = await file.arrayBuffer();
      const wb = XLSX.read(buf, { type: 'array', cellDates: true, codepage: 65001 });
      const sheet = wb.Sheets[wb.SheetNames[0]];
      const rows = XLSX.utils.sheet_to_json(sheet, { defval: '', raw: true });
      if (!rows.length) { alert('檔案第一個工作表沒有資料。'); return; }
      const headers = Object.keys(rows[0]);
      const type = $('importType').value;
      const fields = type === 'project' ? C.PROJECT_FIELDS : C.INVOICE_FIELDS;
      pending = { type, headers, rows, fields };
      showMapping(C.guessMapping(headers, fields));
    } catch (err) {
      alert('無法讀取檔案，請確認是 .xlsx 或 UTF-8 編碼的 .csv。');
    }
  });

  function currentMapping() {
    const mapping = {};
    for (const sel of $('mapping').querySelectorAll('select')) if (sel.value !== '') mapping[sel.dataset.key] = sel.value;
    return mapping;
  }

  function showMapping(mapping) {
    const { headers, fields } = pending;
    $('mapping').innerHTML = fields.map((f) => `
      <label>${f.label}${f.required ? ' <span class="req">*</span>' : ''}
        <select data-key="${f.key}">
          <option value="">（不匯入）</option>
          ${headers.map((h) => `<option value="${esc(h)}" ${mapping[f.key] === h ? 'selected' : ''}>${esc(h)}</option>`).join('')}
        </select>
      </label>`).join('');
    $('mapping').querySelectorAll('select').forEach((s) => s.addEventListener('change', renderPreview));
    $('importStep1').hidden = true;
    $('importStep2').hidden = false;
    $('importConfirm').hidden = false;
    renderPreview();
  }

  function renderPreview() {
    const { rows, fields } = pending;
    const mapping = currentMapping();
    const head = `<thead><tr>${fields.map((f) => `<th>${f.label}</th>`).join('')}<th>檢查</th></tr></thead>`;
    const body = rows.slice(0, 5).map((r) => {
      const res = C.mapRow(r, mapping, fields);
      const rec = res.record || {};
      return `<tr>${fields.map((f) => {
        const v = rec[f.key];
        return `<td>${esc(v === undefined ? '' : (f.type === 'number' && f.key !== 'progress' ? C.formatNTD(v) : v))}</td>`;
      }).join('')}<td>${res.error ? `<span class="badge danger">${esc(res.error)}</span>` : '可匯入'}</td></tr>`;
    }).join('');
    $('preview').innerHTML = head + `<tbody>${body}</tbody>`;
  }

  $('importConfirm').addEventListener('click', () => {
    const { rows, fields, type } = pending;
    const mapping = currentMapping();
    const ok = [];
    const failed = [];
    rows.forEach((r, idx) => {
      const res = C.mapRow(r, mapping, fields);
      if (res.error) failed.push({ row: idx + 2, reason: res.error });
      else ok.push(res.record);
    });
    let summary;
    if (type === 'project') {
      const r = C.upsertProjects(store, ok);
      summary = `新增 ${r.created} 個專案、更新 ${r.updated} 個專案。`;
    } else {
      const r = C.upsertInvoices(store, ok);
      summary = `新增 ${r.created} 筆請款、更新 ${r.updated} 筆請款${r.projectsCreated ? `；另自動建立 ${r.projectsCreated} 個專案，請再匯入專案清單補上合約資料` : ''}。`;
    }
    save();
    $('importResult').innerHTML = `
      <p><strong>成功 ${ok.length} 筆，失敗 ${failed.length} 筆。</strong> ${summary}</p>
      ${failed.length ? `<p>失敗原因（列號為檔案中的列）：</p><ul class="errors">${failed.slice(0, 50).map((f) => `<li>第 ${f.row} 列：${esc(f.reason)}</li>`).join('')}</ul>${failed.length > 50 ? `<p class="muted">另有 ${failed.length - 50} 筆未列出。</p>` : ''}` : ''}`;
    $('importStep2').hidden = true;
    $('importStep3').hidden = false;
    $('importConfirm').hidden = true;
    $('importCancel').textContent = '完成';
    render();
  });

  // ---- 匯出：只在使用者按下時產生檔案 ----
  $('btnExport').addEventListener('click', () => {
    const today = new Date();
    const data = C.computeAll(store.projects, store.invoices, today);
    const wb = XLSX.utils.book_new();
    const t = data.totals;
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
      ['項目', '金額（新台幣元）'],
      ['合約總額', t.contractAmount],
      ['累計已請款', t.billed],
      ['未收款', t.outstanding],
      ['逾期應收', t.overdue],
      [],
      ['匯出日期', C.formatDate(today)],
    ]), '總覽');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.projects.map((p) => ({
      客戶代號: p.clientCode || '', 專案名稱: p.name, 合約編號: p.contractNo || '',
      合約總額: Number(p.contractAmount) || 0, 簽約日: p.signedDate || '', 合約到期日: p.dueDate || '',
      到期倒數天數: p.metrics.daysToDue ?? '', 進度: Number(p.progress) || 0, 狀態: p.status || '',
      已請款: p.metrics.billed, 請款進度: Math.round(p.metrics.billingProgress), 未請款: p.metrics.unbilled,
      已實收: p.metrics.received, 未收款: p.metrics.outstanding, 備註: p.note || '',
    }))), '專案明細');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(store.invoices.map((i) => ({
      專案名稱: i.projectName, 請款期別: i.period, 請款金額: Number(i.amount) || 0, 請款日: i.requestDate || '',
      應收日: i.dueDate || '', 實收日: i.receivedDate || '', 實收金額: Number(i.receivedAmount) || 0,
      狀態: C.invoiceDisplayStatus(i, today),
    }))), '請款紀錄');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.alerts.map((a) => ({ 警示: a.title, 說明: a.message }))), '警示');
    XLSX.writeFile(wb, `mgmt-overview_${C.formatDate(today).replace(/\//g, '')}.xlsx`);
  });

  render();
})();
