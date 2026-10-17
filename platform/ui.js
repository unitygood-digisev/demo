// 優樂地決策平台：畫面與資料存取。資料存在這個 Artifact 的共用資料庫（db），
// 只有被分享的人看得到；金額只在總覽頁使用，對外只寫不含金額的 shared/briefing。
(function () {
  'use strict';
  const C = window.MgmtCalc;
  const $ = (id) => document.getElementById(id);
  const S = { projects: [], invoices: [], kb: [], notes: [], briefing: null, loaded: {} };
  let db = null;
  let canWrite = true;
  let tab = 'dash';
  const sel = { project: null, kb: null, note: null };
  const kbFilter = { query: '', kind: null, subtype: null };
  let noteFolder = null;

  const FOLDERS = ['管理層週報', '外部情報摘要', '知識庫素材'];
  const AGENTS = [
    {
      name: '外部情報摘要員', when: '每週一 09:00', folder: '外部情報摘要',
      duty: '彙整過去 7 天台灣與國際 ESG 政策法規、永續顧問同業動態、客戶產業的公開永續消息。每則附發布日期與網址；沒有合格內容就寫「本週無相關內容」。',
      level: '公開',
    },
    {
      name: '公司知識顧問', when: '每週一 08:00；隨時可問', folder: '知識庫素材',
      duty: '把「知識庫素材」筆記整理成公司資料與知識條目寫進知識庫，標資料等級與證據強度。被詢問時只根據知識庫與不含金額的專案摘要回答，並附引用。',
      level: '公開、內部一般；敏感與機密只留索引',
    },
    {
      name: '管理層週報彙整員', when: '每週五 17:00', folder: '管理層週報',
      duty: '讀不含金額的專案摘要與最新外部情報，寫成「本週三件要緊事、專案警示、外部情報、下週待決事項」的週報，並寄到使用者本人信箱。',
      level: '內部一般，不含金額與客戶機密',
    },
  ];

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function linkify(text) {
    return esc(text).replace(/https?:\/\/[^\s<>"']+/g, (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
  }
  const pct = (n) => `${Math.round(n)}%`;
  const today = () => C.formatDate(new Date());
  const newId = (p) => `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  const strip = (o) => { const { id, metrics, ...rest } = o; return JSON.parse(JSON.stringify(rest)); };

  let toastTimer;
  function toast(msg) {
    const t = $('toast');
    t.textContent = msg;
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 4000);
  }

  function dbError(e) {
    const code = e && e.code;
    if (code === 'invalid_argument') {
      canWrite = false;
      applyWriteMode();
      return '你目前只有檢視權限，無法修改資料。';
    }
    if (code === 'quota_exceeded') return '資料庫已滿，請刪除舊資料後再試。';
    if (code === 'resource_exhausted') return '操作太頻繁，請稍候再試。';
    return '暫時無法存取資料庫，請稍後再試。';
  }

  async function put(col, id, data) {
    await db.collection(col).doc(id).set(data);
  }

  async function writeBriefing(store) {
    try { await db.doc('shared/briefing').set(C.buildBriefing(store.projects, store.invoices, new Date())); }
    catch (e) { toast(dbError(e)); }
  }

  // 兩段式刪除：第一次按變成「確定刪除？」，4 秒內再按才刪。
  function armDelete(btn, action) {
    btn.addEventListener('click', async () => {
      if (btn.dataset.armed !== '1') {
        btn.dataset.armed = '1';
        btn.textContent = '確定刪除？';
        setTimeout(() => { btn.dataset.armed = ''; btn.textContent = '刪除'; }, 4000);
        return;
      }
      btn.disabled = true;
      try { await action(); } catch (e) { toast(dbError(e)); btn.disabled = false; }
    });
  }

  function applyWriteMode() {
    document.querySelectorAll('.w').forEach((el) => { el.hidden = !canWrite || !db; });
  }

  // ---------- 分頁 ----------
  function setTab(t) {
    tab = ['dash', 'kb', 'notes', 'team'].includes(t) ? t : 'dash';
    for (const b of $('tabs').querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    for (const v of ['dash', 'kb', 'notes', 'team']) $('view-' + v).hidden = v !== tab;
    try { localStorage.setItem('udp-tab', tab); } catch (e) { /* 忽略 */ }
    render();
  }
  $('tabs').addEventListener('click', (e) => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });

  // ---------- 繪製 ----------
  function render() {
    if (tab === 'dash') renderDash();
    if (tab === 'kb') renderKb();
    if (tab === 'notes') renderNotes();
    if (tab === 'team') renderTeam();
    applyWriteMode();
  }

  function renderDash() {
    const data = C.computeAll(S.projects, S.invoices, new Date());
    const loaded = S.loaded.projects && S.loaded.invoices;
    const empty = loaded && S.projects.length === 0;
    $('dashEmpty').hidden = !empty;
    $('dashBody').hidden = empty || !loaded;
    $('figures').hidden = empty;
    $('btnExport').disabled = S.projects.length === 0;
    const t = data.totals;
    $('figures').innerHTML = [
      ['合約總額', t.contractAmount, ''], ['累計已請款', t.billed, ''],
      ['未收款', t.outstanding, ''], ['逾期應收', t.overdue, t.overdue > 0 ? 'crit' : ''],
    ].map(([k, v, c]) => `<div class="${c}"><div class="k">${k}</div><div class="v">${loaded ? C.formatNTD(v) : '—'}</div></div>`).join('');
    if (!loaded) return;

    $('alerts').innerHTML = data.alerts.length
      ? data.alerts.map((a) => `<li class="sev${a.severity} click" data-id="${esc(a.projectId)}" tabindex="0"><span class="tag">${esc(a.title)}</span><span>${esc(a.message)}</span></li>`).join('')
      : '<li class="muted" style="border:0;display:block">目前沒有需要決定的事。</li>';
    $('projectRows').innerHTML = data.projects.map((p) => `
      <tr class="click ${p.id === sel.project ? 'sel' : ''}" data-id="${esc(p.id)}">
        <td>${esc(p.clientCode || '—')}</td><td>${esc(p.name)}</td>
        <td class="num">${C.formatNTD(p.contractAmount)}</td>
        <td class="num">${pct(p.metrics.billingProgress)}<span class="bar"><i style="width:${Math.min(100, p.metrics.billingProgress)}%"></i></span></td>
        <td>${esc(p.status || '—')}</td>
      </tr>`).join('');
    renderProjectDetail(data);
  }

  function renderProjectDetail(data) {
    const el = $('projectDetail');
    const p = data.projects.find((x) => x.id === sel.project);
    if (!p) { el.innerHTML = '<p class="muted" style="margin:0">從左邊點一則警示或一個專案，查看合約、金額與請款紀錄。</p>'; return; }
    const m = p.metrics;
    const now = new Date();
    const alerts = data.alerts.filter((a) => a.projectId === p.id);
    const invs = [...m.invoices].sort((a, b) => String(a.requestDate || a.dueDate || '').localeCompare(String(b.requestDate || b.dueDate || '')));
    const due = m.daysToDue === null ? '' : `（${m.daysToDue >= 0 ? `剩 ${m.daysToDue} 天` : `已過 ${-m.daysToDue} 天`}）`;
    el.innerHTML = `
      <h2>${esc(p.name)}</h2>
      <h3>合約資訊</h3>
      <dl class="kv">
        <dt>客戶代號</dt><dd>${esc(p.clientCode || '—')}</dd>
        <dt>合約編號</dt><dd>${esc(p.contractNo || '待補（由請款紀錄自動建立）')}</dd>
        <dt>簽約日</dt><dd>${esc(p.signedDate || '—')}</dd>
        <dt>合約到期日</dt><dd>${esc(p.dueDate || '—')}${due}</dd>
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
      ${alerts.length ? `<ul class="alerts">${alerts.map((a) => `<li class="sev${a.severity}"><span class="tag">${esc(a.title)}</span><span>${esc(a.message)}</span></li>`).join('')}</ul>` : '<p class="muted" style="margin:0">沒有警示。</p>'}
      <div class="w">
        <h3>更新進度與狀態</h3>
        <div class="row">
          <label class="f" style="width:8rem">進度（%）<input type="number" id="pProgress" min="0" max="100" value="${esc(p.progress ?? 0)}"></label>
          <label class="f" style="width:9rem">狀態<select id="pStatus">${C.PROJECT_STATUSES.map((s) => `<option ${s === p.status ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
          <button class="btn small" id="pSave" type="button">儲存</button>
          <button class="btn small danger" id="pDelete" type="button">刪除</button>
        </div>
      </div>
      <h3>請款紀錄</h3>
      ${invs.length ? `<ul class="timeline">${invs.map((i) => {
        const st = C.invoiceDisplayStatus(i, now);
        return `<li class="${st === '逾期' ? 'late' : ''}"><strong>${esc(i.period)}</strong> <span class="pill ${st === '逾期' ? 'crit' : ''}">${st}</span><br>
          <span class="small">請款 ${C.formatNTD(i.amount)}${i.requestDate ? `（${esc(i.requestDate)}）` : ''}；應收日 ${esc(i.dueDate || '—')}<br>
          實收 ${C.formatNTD(i.receivedAmount)}${i.receivedDate ? `（${esc(i.receivedDate)}）` : ''}</span></li>`;
      }).join('')}</ul>` : '<p class="muted" style="margin:0">尚無請款紀錄。</p>'}`;

    $('pSave').addEventListener('click', async () => {
      const v = C.parseNumber($('pProgress').value);
      if (v === undefined || v === null || v < 0 || v > 100) { toast('進度請填 0–100 的數字。'); return; }
      const next = { ...strip(S.projects.find((x) => x.id === p.id)), progress: v, status: $('pStatus').value };
      try {
        await put('projects', p.id, next);
        const store = { projects: S.projects.map((x) => (x.id === p.id ? { id: p.id, ...next } : x)), invoices: S.invoices };
        await writeBriefing(store);
        toast('已儲存。');
      } catch (e) { toast(dbError(e)); }
    });
    armDelete($('pDelete'), async () => {
      for (const i of m.invoices) await db.collection('invoices').doc(i.id).delete();
      await db.collection('projects').doc(p.id).delete();
      sel.project = null;
      await writeBriefing({ projects: S.projects.filter((x) => x.id !== p.id), invoices: S.invoices.filter((i) => i.projectId !== p.id) });
      toast('已刪除專案與它的請款紀錄。');
    });
  }

  function pickProject(id) {
    sel.project = id;
    renderDash();
    applyWriteMode();
    if (window.matchMedia('(max-width: 900px)').matches) $('projectDetail').scrollIntoView({ behavior: 'smooth' });
  }
  $('alerts').addEventListener('click', (e) => { const li = e.target.closest('li[data-id]'); if (li) pickProject(li.dataset.id); });
  $('alerts').addEventListener('keydown', (e) => { if (e.key === 'Enter') { const li = e.target.closest('li[data-id]'); if (li) pickProject(li.dataset.id); } });
  $('projectRows').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-id]'); if (tr) pickProject(tr.dataset.id); });

  // ---------- 匯入 ----------
  const impDlg = $('importDlg');
  let pending = null;
  function openImport() {
    pending = null;
    $('importForm').reset();
    $('imp1').hidden = false; $('imp2').hidden = true; $('imp3').hidden = true;
    $('impGo').hidden = true; $('impGo').disabled = false;
    $('impCancel').textContent = '取消';
    impDlg.showModal();
  }
  $('btnImport').addEventListener('click', openImport);
  $('btnImportFirst').addEventListener('click', openImport);
  $('impCancel').addEventListener('click', () => impDlg.close());
  $('importForm').addEventListener('submit', (e) => e.preventDefault());

  $('impFile').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (!window.XLSX) { toast('Excel 讀取元件沒有載入，請重新整理頁面。'); return; }
    try {
      const wb = XLSX.read(await file.arrayBuffer(), { type: 'array', cellDates: true, codepage: 65001 });
      const rows = XLSX.utils.sheet_to_json(wb.Sheets[wb.SheetNames[0]], { defval: '', raw: true });
      if (!rows.length) { toast('檔案第一個工作表沒有資料。'); return; }
      const type = $('impType').value;
      const fields = type === 'project' ? C.PROJECT_FIELDS : C.INVOICE_FIELDS;
      pending = { type, rows, fields, headers: Object.keys(rows[0]) };
      showMapping(C.guessMapping(pending.headers, fields));
    } catch (err) {
      toast('無法讀取檔案，請確認是 .xlsx 或 UTF-8 編碼的 .csv。');
    }
  });

  function currentMapping() {
    const m = {};
    for (const s of $('impMap').querySelectorAll('select')) if (s.value !== '') m[s.dataset.key] = s.value;
    return m;
  }
  function showMapping(mapping) {
    $('impMap').innerHTML = pending.fields.map((f) => `
      <label class="f">${f.label}${f.required ? ' <span class="req">*</span>' : ''}
        <select data-key="${f.key}" id="map-${f.key}"><option value="">（不匯入）</option>
          ${pending.headers.map((h) => `<option value="${esc(h)}" ${mapping[f.key] === h ? 'selected' : ''}>${esc(h)}</option>`).join('')}
        </select></label>`).join('');
    $('impMap').querySelectorAll('select').forEach((s) => s.addEventListener('change', renderPreview));
    $('imp1').hidden = true; $('imp2').hidden = false; $('impGo').hidden = false;
    renderPreview();
  }
  function renderPreview() {
    const mapping = currentMapping();
    const fs = pending.fields;
    $('impPreview').innerHTML = `<thead><tr>${fs.map((f) => `<th>${f.label}</th>`).join('')}<th>檢查</th></tr></thead><tbody>${
      pending.rows.slice(0, 5).map((r) => {
        const res = C.mapRow(r, mapping, fs);
        const rec = res.record || {};
        return `<tr>${fs.map((f) => {
          const v = rec[f.key];
          return `<td>${esc(v === undefined ? '' : (f.type === 'number' && f.key !== 'progress' ? C.formatNTD(v) : v))}</td>`;
        }).join('')}<td>${res.error ? `<span class="pill crit">${esc(res.error)}</span>` : '可匯入'}</td></tr>`;
      }).join('')}</tbody>`;
  }

  $('impGo').addEventListener('click', async () => {
    const { rows, fields, type } = pending;
    const mapping = currentMapping();
    const ok = [], failed = [];
    rows.forEach((r, i) => { const res = C.mapRow(r, mapping, fields); if (res.error) failed.push({ row: i + 2, reason: res.error }); else ok.push(res.record); });
    const work = { projects: S.projects.map(strip).map((d, i) => ({ id: S.projects[i].id, ...d })), invoices: S.invoices.map(strip).map((d, i) => ({ id: S.invoices[i].id, ...d })) };
    const before = new Map([...work.projects, ...work.invoices].map((x) => [x.id, JSON.stringify(x)]));
    const summary = type === 'project' ? C.upsertProjects(work, ok) : C.upsertInvoices(work, ok);
    const changed = [
      ...work.projects.filter((x) => before.get(x.id) !== JSON.stringify(x)).map((x) => ['projects', x]),
      ...work.invoices.filter((x) => before.get(x.id) !== JSON.stringify(x)).map((x) => ['invoices', x]),
    ];
    $('impGo').disabled = true;
    $('imp2').hidden = true; $('imp3').hidden = false;
    let written = 0;
    try {
      for (const [col, x] of changed) {
        $('imp3').innerHTML = `<p>正在寫入 ${written + 1}／${changed.length} 筆…</p>`;
        await put(col, x.id, strip(x));
        written += 1;
      }
      await writeBriefing(work);
    } catch (e) {
      $('imp3').innerHTML = `<p class="errs" style="padding:0">${esc(dbError(e))}已寫入 ${written}／${changed.length} 筆，可以重新匯入同一份檔案補齊，不會重複。</p>`;
      $('impGo').hidden = true; $('impCancel').textContent = '關閉';
      return;
    }
    const msg = type === 'project'
      ? `新增 ${summary.created} 個專案、更新 ${summary.updated} 個專案。`
      : `新增 ${summary.created} 筆請款、更新 ${summary.updated} 筆請款${summary.projectsCreated ? `；另自動建立 ${summary.projectsCreated} 個專案，請再匯入專案清單補上合約資料` : ''}。`;
    $('imp3').innerHTML = `<p><strong>成功 ${ok.length} 筆，失敗 ${failed.length} 筆。</strong>${msg}</p>
      ${failed.length ? `<p class="small" style="margin:0">失敗原因（列號為檔案中的列）：</p><ul class="errs">${failed.slice(0, 50).map((f) => `<li>第 ${f.row} 列：${esc(f.reason)}</li>`).join('')}</ul>${failed.length > 50 ? `<p class="muted small">另有 ${failed.length - 50} 筆未列出。</p>` : ''}` : ''}`;
    $('impGo').hidden = true;
    $('impCancel').textContent = '完成';
  });

  // ---------- 匯出與範本（經過 downloads，由檢視者確認後存檔）----------
  async function offerFile(filename, wb) {
    const dl = window.claude ? await window.claude.use('downloads') : null;
    if (!dl) { toast('這個檢視無法下載檔案，請在 claude.ai 開啟此頁。'); return; }
    const blob = new Blob([XLSX.write(wb, { type: 'array', bookType: 'xlsx' })]);
    try { await dl.save({ filename, data: blob }); }
    catch (e) { if (e && e.code !== 'declined') toast('無法下載，請稍後再試。'); }
  }
  $('btnExport').addEventListener('click', () => {
    const now = new Date();
    const data = C.computeAll(S.projects, S.invoices, now);
    const t = data.totals;
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
      ['項目', '金額（新台幣元）'], ['合約總額', t.contractAmount], ['累計已請款', t.billed],
      ['未收款', t.outstanding], ['逾期應收', t.overdue], [], ['匯出日期', C.formatDate(now)],
    ]), '總覽');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.projects.map((p) => ({
      客戶代號: p.clientCode || '', 專案名稱: p.name, 合約編號: p.contractNo || '', 合約總額: Number(p.contractAmount) || 0,
      簽約日: p.signedDate || '', 合約到期日: p.dueDate || '', 到期倒數天數: p.metrics.daysToDue ?? '', 進度: Number(p.progress) || 0,
      狀態: p.status || '', 已請款: p.metrics.billed, 請款進度: Math.round(p.metrics.billingProgress), 未請款: p.metrics.unbilled,
      已實收: p.metrics.received, 未收款: p.metrics.outstanding, 備註: p.note || '',
    }))), '專案明細');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(S.invoices.map((i) => ({
      專案名稱: i.projectName, 請款期別: i.period, 請款金額: Number(i.amount) || 0, 請款日: i.requestDate || '', 應收日: i.dueDate || '',
      實收日: i.receivedDate || '', 實收金額: Number(i.receivedAmount) || 0, 狀態: C.invoiceDisplayStatus(i, now),
    }))), '請款紀錄');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.alerts.map((a) => ({ 警示: a.title, 說明: a.message }))), '警示');
    offerFile(`管理層總覽_${C.formatDate(now).replace(/\//g, '')}.xlsx`, wb);
  });
  $('btnTemplate').addEventListener('click', () => {
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([C.PROJECT_FIELDS.map((f) => f.label)]), '專案清單');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([C.INVOICE_FIELDS.map((f) => f.label)]), '請款紀錄');
    offerFile('匯入範本.xlsx', wb);
  });

  // ---------- 共用編輯對話框 ----------
  const editDlg = $('editDlg');
  let editCtx = null;
  function openEditor({ title, fields, values, onSave, levelNotice }) {
    editCtx = { onSave };
    $('editTitle').textContent = title;
    $('editFields').innerHTML = fields.map((f) => {
      const v = values[f.key] ?? '';
      const full = f.type === 'textarea' ? ' style="grid-column:1/-1"' : '';
      let input;
      if (f.type === 'select') input = `<select name="${f.key}" id="ed-${f.key}" ${f.required ? 'required' : ''}><option value="">請選擇</option>${f.options.map((o) => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      else if (f.type === 'textarea') input = `<textarea name="${f.key}" id="ed-${f.key}">${esc(v)}</textarea>`;
      else input = `<input name="${f.key}" id="ed-${f.key}" value="${esc(v)}" ${f.required ? 'required' : ''} ${f.type === 'date' ? 'placeholder="YYYY/MM/DD" pattern="\\d{4}/\\d{2}/\\d{2}"' : ''}>`;
      return `<label class="f"${full}>${esc(f.label)}${f.required ? ' <span class="req">*</span>' : ''}${input}</label>`;
    }).join('');
    const level = $('editFields').querySelector('[name="dataLevel"]');
    const notice = () => {
      const on = levelNotice && level && KB.isSensitive(level.value);
      $('editNotice').hidden = !on;
      $('editNotice').textContent = KB.SENSITIVE_WARNING;
    };
    if (level) level.addEventListener('change', notice);
    notice();
    $('editSave').disabled = false;
    editDlg.showModal();
  }
  $('editCancel').addEventListener('click', () => editDlg.close());
  $('editForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const data = Object.fromEntries([...new FormData(e.target).entries()].map(([k, v]) => [k, String(v).trim()]));
    $('editSave').disabled = true;
    try { await editCtx.onSave(data); editDlg.close(); toast('已儲存。'); }
    catch (err) { toast(dbError(err)); $('editSave').disabled = false; }
  });

  // ---------- 知識庫 ----------
  function chip(label, on, attrs) { return `<button type="button" class="chip ${on ? 'on' : ''}" ${attrs}>${esc(label)}</button>`; }
  function renderKb() {
    const loaded = S.loaded.kb;
    const empty = loaded && S.kb.length === 0;
    $('kbEmpty').hidden = !empty;
    $('kbBody').hidden = empty || !loaded;
    if (!loaded) return;
    $('kbKinds').innerHTML = chip('全部', !kbFilter.kind && !kbFilter.subtype, 'data-kind=""') +
      Object.entries(KB.KINDS).map(([k, l]) => chip(l, kbFilter.kind === k, `data-kind="${k}"`)).join('');
    const subs = kbFilter.kind === 'COMPANY_FACT' ? KB.CATEGORIES : kbFilter.kind === 'KNOWLEDGE_ENTRY' ? KB.ENTRY_TYPES
      : [...KB.CATEGORIES.filter((c) => c !== '其他'), ...KB.ENTRY_TYPES];
    $('kbSubs').innerHTML = subs.map((s) => chip(s, kbFilter.subtype === s, `data-sub="${esc(s)}"`)).join('');
    const list = KB.filterItems(S.kb, kbFilter);
    $('kbItems').innerHTML = list.length ? list.map((it) => `
      <li class="${it.id === sel.kb ? 'sel' : ''}"><button type="button" class="rowbtn" data-id="${esc(it.id)}">
        <div>${esc(it.name)}</div>
        <div class="meta"><span class="pill">${esc(KB.KINDS[it.kind] || '')}・${esc(KB.subtypeOf(it) || '—')}</span>
          <span class="pill ${KB.isSensitive(it.dataLevel) ? 'crit' : ''}">${esc(it.dataLevel || '—')}</span>
          <span class="pill">${esc(it.evidence || '—')}</span><span class="pill">${esc(it.updatedDate || '未填日期')}</span></div>
      </button></li>`).join('') : '<li class="muted" style="padding:.6rem .5rem">沒有符合的資料。</li>';

    const it = S.kb.find((x) => x.id === sel.kb);
    const el = $('kbDetail');
    if (!it) { el.innerHTML = '<p class="muted" style="margin:0">從左邊選一筆，查看詳情。</p>'; return; }
    el.innerHTML = `<h2>${esc(it.name)}</h2><p class="muted small" style="margin:.2rem 0 .7rem">${esc(KB.KINDS[it.kind] || '')}</p>
      ${KB.isSensitive(it.dataLevel) ? `<p class="notice" style="margin-bottom:.7rem">${esc(it.dataLevel)}：${esc(KB.SENSITIVE_WARNING)}。</p>` : ''}
      <dl class="kv">${(KB.FIELDS[it.kind] || []).filter((f) => f.key !== 'name').map((f) => `<dt>${esc(f.label)}</dt><dd>${linkify(it[f.key] || '—')}</dd>`).join('')}</dl>
      <div class="row w" style="margin-top:.8rem"><button type="button" class="btn small" id="kbEdit">編輯</button><button type="button" class="btn small danger" id="kbDel">刪除</button></div>`;
    $('kbEdit').addEventListener('click', () => editKb(it.kind, it));
    armDelete($('kbDel'), async () => { await db.collection('kb').doc(it.id).delete(); sel.kb = null; toast('已刪除。'); });
  }
  function editKb(kind, it) {
    openEditor({
      title: `${it ? '編輯' : '新增'}${KB.KINDS[kind]}`,
      fields: KB.FIELDS[kind],
      values: it || { dataLevel: '內部一般', evidence: '待確認', updatedDate: today() },
      levelNotice: true,
      onSave: async (data) => {
        const id = it ? it.id : newId('kb');
        await put('kb', id, { ...(it ? strip(it) : {}), ...data, kind, updatedDate: data.updatedDate || today() });
        sel.kb = id;
      },
    });
  }
  $('kbKinds').addEventListener('click', (e) => {
    const b = e.target.closest('[data-kind]'); if (!b) return;
    const k = b.dataset.kind || null;
    kbFilter.kind = k && kbFilter.kind === k ? null : k;
    kbFilter.subtype = null;
    renderKb();
  });
  $('kbSubs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-sub]'); if (!b) return;
    kbFilter.subtype = kbFilter.subtype === b.dataset.sub ? null : b.dataset.sub;
    renderKb();
  });
  $('kbSearch').addEventListener('input', (e) => { kbFilter.query = e.target.value; renderKb(); applyWriteMode(); });
  $('kbItems').addEventListener('click', (e) => { const b = e.target.closest('[data-id]'); if (b) { sel.kb = b.dataset.id; renderKb(); applyWriteMode(); } });
  $('btnNewFact').addEventListener('click', () => editKb('COMPANY_FACT'));
  $('btnNewEntry').addEventListener('click', () => editKb('KNOWLEDGE_ENTRY'));
  $('btnKbFirst').addEventListener('click', () => editKb('COMPANY_FACT'));

  // ---------- 筆記 ----------
  const NOTE_FIELDS = [
    { key: 'folder', label: '資料夾', type: 'select', options: FOLDERS, required: true },
    { key: 'title', label: '標題', type: 'text', required: true },
    { key: 'dataLevel', label: '資料等級', type: 'select', options: KB.DATA_LEVELS, required: true },
    { key: 'date', label: '日期', type: 'date' },
    { key: 'body', label: '內容', type: 'textarea' },
  ];
  function renderNotes() {
    $('noteFolders').innerHTML = chip('全部', !noteFolder, 'data-folder=""') + FOLDERS.map((f) => chip(f, noteFolder === f, `data-folder="${f}"`)).join('');
    const list = S.notes.filter((n) => !noteFolder || n.folder === noteFolder)
      .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')) || String(b.title || '').localeCompare(String(a.title || '')));
    $('noteItems').innerHTML = !S.loaded.notes ? '<li class="muted" style="padding:.6rem .5rem">載入中…</li>'
      : list.length ? list.map((n) => `<li class="${n.id === sel.note ? 'sel' : ''}"><button type="button" class="rowbtn" data-id="${esc(n.id)}">
        <div>${esc(n.title)}</div>
        <div class="meta"><span class="pill accent">${esc(n.folder)}</span><span class="pill">${esc(n.author || '使用者')}</span><span class="pill">${esc(n.date || '')}</span><span class="pill ${KB.isSensitive(n.dataLevel) ? 'crit' : ''}">${esc(n.dataLevel || '—')}</span></div>
      </button></li>`).join('')
      : `<li class="muted" style="padding:.6rem .5rem">${noteFolder === '知識庫素材' ? '把訪談紀錄、SOP、案例、提案範本放進來，公司知識顧問每週一會整理進知識庫。' : '這個資料夾還沒有筆記。'}</li>`;
    const n = S.notes.find((x) => x.id === sel.note);
    const el = $('noteDetail');
    if (!n) { el.innerHTML = '<p class="muted" style="margin:0">從左邊選一篇筆記。週報、外部情報摘要由員工寫入；知識庫素材由你放入。</p>'; return; }
    el.innerHTML = `<h2>${esc(n.title)}</h2>
      <div class="meta" style="margin:.3rem 0 .8rem"><span class="pill accent">${esc(n.folder)}</span><span class="pill">${esc(n.author || '使用者')}</span><span class="pill">${esc(n.date || '')}</span><span class="pill">${esc(n.dataLevel || '—')}</span></div>
      <div class="prose">${linkify(n.body || '')}</div>
      <div class="row w" style="margin-top:.8rem"><button type="button" class="btn small" id="noteEdit">編輯</button><button type="button" class="btn small danger" id="noteDel">刪除</button></div>`;
    $('noteEdit').addEventListener('click', () => editNote(n));
    armDelete($('noteDel'), async () => { await db.collection('notes').doc(n.id).delete(); sel.note = null; toast('已刪除。'); });
  }
  function editNote(n) {
    openEditor({
      title: n ? '編輯筆記' : '新增筆記',
      fields: NOTE_FIELDS,
      values: n || { folder: noteFolder || '知識庫素材', dataLevel: '內部一般', date: today() },
      levelNotice: true,
      onSave: async (data) => {
        const id = n ? n.id : newId('note');
        await put('notes', id, { ...(n ? strip(n) : { author: '使用者' }), ...data, date: data.date || today() });
        sel.note = id;
      },
    });
  }
  $('noteFolders').addEventListener('click', (e) => { const b = e.target.closest('[data-folder]'); if (!b) return; noteFolder = b.dataset.folder || null; renderNotes(); applyWriteMode(); });
  $('noteItems').addEventListener('click', (e) => { const b = e.target.closest('[data-id]'); if (b) { sel.note = b.dataset.id; renderNotes(); applyWriteMode(); } });
  $('btnNewNote').addEventListener('click', () => editNote());

  // ---------- 員工 ----------
  function renderTeam() {
    $('agents').innerHTML = AGENTS.map((a) => {
      const last = S.notes.filter((n) => n.author === a.name).sort((x, y) => String(y.date || '').localeCompare(String(x.date || '')))[0];
      return `<section class="panel agent">
        <h2>${esc(a.name)}</h2>
        <div class="when">${esc(a.when)}（台北時間）</div>
        <p>${esc(a.duty)}</p>
        <p class="muted small">資料等級：${esc(a.level)}</p>
        <p class="small">最近產出：${last ? `<button type="button" class="chip" data-note="${esc(last.id)}">${esc(last.title)}</button>` : '<span class="muted">尚未產出</span>'}</p>
      </section>`;
    }).join('');
  }
  $('agents').addEventListener('click', (e) => {
    const b = e.target.closest('[data-note]'); if (!b) return;
    sel.note = b.dataset.note; noteFolder = null; setTab('notes');
  });

  let asking = null;
  $('askBtn').addEventListener('click', async () => {
    const q = $('askInput').value.trim();
    if (!q) { toast('請先輸入問題。'); return; }
    const sample = window.claude ? await window.claude.use('sample') : null;
    const out = $('askAnswer');
    if (!sample) { out.hidden = false; out.textContent = '這個檢視無法使用知識顧問，請在 claude.ai 開啟此頁。'; return; }
    if (asking) asking.abort();
    asking = new AbortController();
    const knowledge = S.kb.map((it) => KB.isSensitive(it.dataLevel)
      ? { 名稱: it.name, 類型: KB.KINDS[it.kind], 資料等級: it.dataLevel, 說明: '摘要＋請洽內部（全文不提供）', 摘要: it.summary || '' }
      : Object.fromEntries((KB.FIELDS[it.kind] || []).map((f) => [f.label, it[f.key] || '']).concat([['類型', KB.KINDS[it.kind]]])));
    const briefing = S.projects.length ? C.buildBriefing(S.projects, S.invoices, new Date()) : S.briefing;
    const prompt = `你是優樂地永續服務股份有限公司的「公司知識顧問」，服務執行長、主管與數位轉型實習生。
規則：
1. 只根據下面的「知識庫」與「專案摘要」回答，用繁體中文，簡潔分點。
2. 每個結論後面用【條目名稱】標出引用來源。
3. 資料裡找不到就說「知識庫目前沒有這項資料」，並指出需要補哪一種素材（公司資料、SOP、案例、提案範本、方法論、常見問答）。
4. 不回答金額、應收明細或客戶機密，請對方直接看「管理層總覽」頁。
5. 合約、保密、智慧財產相關解讀一律標【待法務確認】。
6. 證據強度為「推測」或「待確認」的資料，回答時要註明。不要編造。

知識庫（JSON）：
${JSON.stringify(knowledge)}

專案摘要（不含金額，JSON）：
${JSON.stringify(briefing || { note: '尚無專案資料' })}

問題：${q}`;
    out.hidden = false;
    out.textContent = '思考中…';
    $('askBtn').disabled = true;
    try {
      const res = await sample(prompt, { cache: false, signal: asking.signal, onText: ({ text }) => { out.textContent = text; } });
      out.textContent = res.text + (res.truncated ? '\n\n（回答過長，已截斷）' : '');
    } catch (e) {
      if (e && e.code === 'not_granted') out.textContent = '需要允許此頁詢問 Claude 才能使用知識顧問。';
      else if (e && e.code === 'rate_limited') out.textContent = '詢問太頻繁，請稍候再試。';
      else if (!(e && e.name === 'AbortError')) out.textContent = '暫時無法取得回答，請稍後再試。';
    } finally { $('askBtn').disabled = false; }
  });

  // ---------- 啟動 ----------
  let initial = 'dash';
  try { initial = localStorage.getItem('udp-tab') || 'dash'; } catch (e) { /* 忽略 */ }
  const hash = location.hash.replace('#', '');
  if (['dash', 'kb', 'notes', 'team'].includes(hash)) initial = hash;
  document.querySelectorAll('#btnImport,#btnImportFirst,#btnNewFact,#btnNewEntry,#btnKbFirst,#btnNewNote').forEach((b) => b.classList.add('w'));
  setTab(initial);

  (async () => {
    db = window.claude ? await window.claude.use('db') : null;
    if (!db) {
      $('conn').textContent = '無法連到資料庫。請登入 claude.ai 並從 Claude 開啟這個頁面。';
      return;
    }
    const user = await window.claude.use('user');
    if (user) {
      try { if ((await user.can('data.write')) === false) canWrite = false; } catch (e) { /* 未知時保留輸入 */ }
    }
    $('conn').hidden = true;
    const subscribe = (name) => db.collection(name).onSnapshot((snap) => {
      S[name] = snap.docs.map((d) => ({ id: d.id, ...d.data() }));
      S.loaded[name] = true;
      render();
    }, () => {
      S.loaded[name] = true;
      $('conn').hidden = false;
      $('conn').textContent = '部分資料暫時無法載入，請重新整理頁面。';
      render();
    });
    ['projects', 'invoices', 'kb', 'notes'].forEach(subscribe);
    db.doc('shared/briefing').onSnapshot((d) => { S.briefing = d.exists ? d.data() : null; }, () => {});
    render();
  })();
})();
