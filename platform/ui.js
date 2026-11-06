// 優樂地管理中樞：畫面與資料存取。資料存在這個 Artifact 的共用資料庫（db），只有被分享的人看得到。
// 金額只在「專案財務」頁使用；對 AI 員工與知識顧問只提供不含金額的 shared/briefing。
(function () {
  'use strict';
  const C = window.MgmtCalc;
  const H = window.Hub;
  const $ = (id) => document.getElementById(id);
  const COLS = ['projects', 'invoices', 'kb', 'notes', 'modules', 'initiatives', 'tasks', 'milestones', 'docs', 'routines'];
  const S = { meta: null, briefing: null, loaded: {} };
  COLS.forEach((c) => { S[c] = []; });
  let db = null;
  let canWrite = true;
  let tab = 'home';
  const TABS = ['home', 'mods', 'inits', 'tasks', 'time', 'notes', 'kb', 'dash', 'docs'];
  const sel = { project: null, kb: null, note: null };
  const kbFilter = { query: '', kind: null, subtype: null };
  const taskFilter = { owner: null, status: '未完成', area: null, kind: null, query: '' };
  let modFilter = null;
  let noteFolder = null;

  const FOLDERS = ['管理層週報', '外部情報摘要', '知識庫素材'];
  const AGENTS = [
    { name: '外部情報摘要員', when: '每週一 09:00', duty: '彙整過去 7 天的 ESG 政策法規、同業與客戶產業公開消息，每則附發布日期與網址。' },
    { name: '公司知識顧問', when: '每週一 08:00', duty: '把「知識庫素材」筆記整理成公司資料與知識條目，標資料等級與證據強度。' },
    { name: '管理層週報彙整員', when: '每週五 17:00', duty: '讀不含金額的摘要與最新情報，寫成「本週三件要緊事、專案警示、外部情報、下週待決事項」。' },
    { name: '後台更新員', when: '每週一 07:30', duty: '更新八大系統的程式進度、AI 排程的最近執行結果，並記錄本週變化。' },
  ];

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }
  function linkify(text) {
    return esc(text).replace(/https?:\/\/[^\s<>"'）]+/g, (u) => `<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
  }
  function safeUrl(u) { return /^https:\/\//.test(String(u || '')) ? esc(u) : '#'; }
  const pct = (n) => `${Math.round(n)}%`;
  const now = () => new Date();
  const today = () => C.formatDate(now());
  const newId = (p) => `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
  const strip = (o) => { const { id, metrics, ...rest } = o; return JSON.parse(JSON.stringify(rest)); };
  const byOrder = (k) => (a, b) => (Number(a[k]) || 0) - (Number(b[k]) || 0);
  function areaName(id) {
    const m = S.modules.find((x) => x.id === id);
    if (m) return `系統 ${m.no} ${m.name}`;
    const i = S.initiatives.find((x) => x.id === id);
    return i ? i.name : (id || '—');
  }
  function shortArea(id) {
    const m = S.modules.find((x) => x.id === id);
    if (m) return `系統 ${m.no}`;
    const i = S.initiatives.find((x) => x.id === id);
    return i ? i.name.replace(/（.*?）/g, '') : (id || '—');
  }
  function modPill(status) {
    const s = H.MODULE_STATUS[status] || { label: status || '—', tone: 'idle' };
    return `<span class="pill ${s.tone}">${esc(s.label)}</span>`;
  }
  function taskPill(t) {
    const st = H.taskState(t, now());
    if (st === 'done') return '<span class="pill good">完成</span>';
    if (st === 'overdue') return '<span class="pill crit">已逾期</span>';
    const tone = t.status === '等待決定' ? 'warn' : t.status === '等待資料' ? 'info' : 'idle';
    return `<span class="pill ${tone}">${esc(t.status)}</span>`;
  }
  function stepTone(s) {
    return { 完成: 'good', 進行中: 'info', 等待決定: 'warn', 等待資料: 'info', 未開始: 'idle' }[s] || 'idle';
  }

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
    if (code === 'invalid_argument') { canWrite = false; applyWriteMode(); return '你目前只有檢視權限，無法修改資料。'; }
    if (code === 'quota_exceeded') return '資料庫已滿，請刪除舊資料後再試。';
    if (code === 'resource_exhausted') return '操作太頻繁，請稍候再試。';
    return '暫時無法存取資料庫，請稍後再試。';
  }
  async function put(col, id, data) { await db.collection(col).doc(id).set(data); }
  async function writeBriefing(store) {
    try { await db.doc('shared/briefing').set(C.buildBriefing(store.projects, store.invoices, now())); }
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
    document.querySelectorAll('input.check').forEach((el) => { el.disabled = !canWrite || !db; });
  }

  // ---------- 分頁 ----------
  function setTab(t) {
    tab = TABS.includes(t) ? t : 'home';
    for (const b of $('tabs').querySelectorAll('button')) b.setAttribute('aria-selected', String(b.dataset.tab === tab));
    for (const v of TABS) $('view-' + v).hidden = v !== tab;
    try { localStorage.setItem('udp-tab', tab); } catch (e) { /* 忽略 */ }
    render();
  }
  $('tabs').addEventListener('click', (e) => { const b = e.target.closest('button[data-tab]'); if (b) setTab(b.dataset.tab); });
  document.addEventListener('click', (e) => { const b = e.target.closest('[data-goto]'); if (b) { setTab(b.dataset.goto); window.scrollTo(0, 0); } });

  function render() {
    ({ home: renderHome, mods: renderMods, inits: renderInits, tasks: renderTasks, time: renderTime,
      notes: renderNotes, kb: renderKb, dash: renderDash, docs: renderDocs })[tab]();
    applyWriteMode();
  }

  // ---------- 總覽 ----------
  function progressNumbers() {
    const meta = S.meta || {};
    return H.transformationProgress(S.modules, meta.foundationHours, meta.weeklyHours);
  }
  function renderHome() {
    if (!S.loaded.modules || !S.loaded.tasks) {
      $('homeLead').textContent = db ? '正在載入進度…' : '連上資料庫後會顯示八大系統與待辦。';
      return;
    }
    const ms = H.moduleSummary(S.modules);
    const ts = H.taskSummary(S.tasks, now());
    const p = progressNumbers();
    const meta = S.meta || {};
    const routinesOk = S.routines.filter((r) => r.lastStatus === '成功').length;
    const latestReport = S.notes.filter((n) => n.folder === '管理層週報' && n.author === '管理層週報彙整員').sort((a, b) => String(b.date).localeCompare(String(a.date)))[0];

    $('homeLead').innerHTML = ms.total
      ? `八大系統中 <strong>${ms.done} 個完成並在用</strong>，${ms.notDone} 個還沒開始；依時數估計，數位轉型約完成 <strong>${p.pct}%</strong>。目前有 <strong>${ts.decisions} 件事等主管決定</strong>${ts.overdue ? `，${ts.overdue} 件待辦已逾期` : ''}。`
      : '還沒有系統資料。';

    $('homeFigures').innerHTML = [
      ['系統完成', `${ms.done}／${ms.total}`, `${ms.notDone} 個未開始`, 'good'],
      ['數位轉型進度', `${p.pct}%`, `區間 ${p.pctLow}–${p.pctHigh}%`, ''],
      ['剩下工時', `${p.remaining.min}–${p.remaining.max} 小時`, `約 ${p.weeks.min}–${p.weeks.max} 週`, ''],
      ['等主管決定', `${ts.decisions} 件`, `未完成待辦 ${ts.open} 件`, ts.decisions ? 'crit' : ''],
      ['AI 排程', `${S.routines.length} 個`, `最近執行成功 ${routinesOk} 個`, ''],
      ['最新週報', latestReport ? latestReport.date.slice(5) : '—', latestReport ? '管理層週報彙整員' : '尚無', ''],
    ].map(([k, v, s, c]) => `<div class="${c}"><div class="k">${k}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`).join('');

    $('homeNext').innerHTML = `<h2>下一步（只列一項）</h2><p>${esc(meta.nextStep || '—')}</p>
      ${meta.nextStepUrl ? `<p class="small"><a href="${safeUrl(meta.nextStepUrl)}" target="_blank" rel="noopener">打開問題清單</a></p>` : ''}
      <p class="muted small">資料更新：${esc(meta.updatedDate || '—')}</p>`;

    const decisions = H.sortTasks(S.tasks.filter((t) => t.kind === '決策' && t.status !== '完成'), now()).slice(0, 7);
    $('homeDecisions').innerHTML = decisions.length ? decisions.map(taskRow).join('') : '<li class="muted" style="display:block">沒有等待決定的事。</li>';

    $('homeMods').innerHTML = [...S.modules].sort(byOrder('no')).map((m) => `
      <button type="button" data-mod="${esc(m.id)}"><span class="n">${esc(m.no)}</span><span>${esc(m.name.replace(/（.*?）/g, ''))}</span>${modPill(m.status)}</button>`).join('');

    $('homeProgress').innerHTML = `
      <div class="bigbar" role="img" aria-label="數位轉型約完成 ${p.pct}%"><b style="left:${p.pctLow}%;width:${p.pctHigh - p.pctLow}%"></b><i style="width:${p.pct}%"></i></div>
      <p class="small" style="margin:.2rem 0">已完成約 ${p.done.min}–${p.done.max} 小時，剩下約 ${p.remaining.min}–${p.remaining.max} 小時；以每週 ${(meta.weeklyHours || {}).min || 6}–${(meta.weeklyHours || {}).max || 8} 小時計算，約還要 ${p.weeks.min}–${p.weeks.max} 週。</p>
      <p class="muted small" style="margin:0">${esc(meta.progressMethod || '')}</p>`;

    const { upcoming } = H.splitMilestones(S.milestones, now());
    $('homeTimeline').innerHTML = upcoming.slice(0, 5).map(msRow).join('') || '<li class="muted">沒有排定的時程。</li>';
  }
  $('homeMods').addEventListener('click', (e) => {
    const b = e.target.closest('[data-mod]'); if (!b) return;
    modFilter = null; setTab('mods');
    const el = document.getElementById('mod-' + b.dataset.mod);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  // ---------- 八大系統 ----------
  function renderMods() {
    const counts = H.moduleSummary(S.modules).byStatus;
    const statuses = Object.keys(H.MODULE_STATUS).filter((k) => counts[k]);
    $('modFilter').innerHTML = chip('全部', !modFilter, 'data-mf=""') + statuses.map((k) => chip(`${H.MODULE_STATUS[k].label} ${counts[k]}`, modFilter === k, `data-mf="${k}"`)).join('');
    const list = [...S.modules].sort(byOrder('no')).filter((m) => !modFilter || m.status === modFilter);
    $('modCards').innerHTML = !S.loaded.modules ? '<p class="muted">載入中…</p>' : list.map((m) => {
      const stage = Number(m.stage) || 0;
      const open = S.tasks.filter((t) => t.area === m.id && t.status !== '完成');
      return `<section class="panel mod" id="mod-${esc(m.id)}">
        <div class="no">系統 ${esc(m.no)}・${esc(m.phase || '')}</div>
        <div class="panel-head" style="margin:0"><h2>${esc(m.name)}</h2>${modPill(m.status)}</div>
        <div><div class="track">${H.STAGES.map((s, i) => `<span class="${i < stage ? 'on' : ''}" title="${s}"></span>`).join('')}</div>
          <div class="track-labels">${H.STAGES.map((s) => `<span>${s}</span>`).join('')}</div></div>
        <p class="small" style="margin:0">${esc(m.summary || '')}</p>
        ${(m.blockers || []).length ? `<div><div class="small muted">現在卡在哪裡</div><ul>${m.blockers.map((b) => `<li>${esc(b)}</li>`).join('')}</ul></div>` : ''}
        <div class="nextline"><span class="muted">下一步：</span>${esc(m.nextStep || '—')}</div>
        <div class="meta"><span class="pill">資料等級 ${esc(m.dataLevel || '—')}</span><span class="pill">估計 ${esc((m.hours || {}).min)}–${esc((m.hours || {}).max)} 小時</span>${open.length ? `<span class="pill warn">相關待辦 ${open.length}</span>` : ''}</div>
        <div class="row">${m.specUrl ? `<a class="small" href="${safeUrl(m.specUrl)}" target="_blank" rel="noopener">規格</a>` : ''}
          <button type="button" class="btn small ghost w" data-editmod="${esc(m.id)}">更新</button>
          ${open.length ? `<button type="button" class="btn small ghost" data-modtasks="${esc(m.id)}">看待辦</button>` : ''}</div>
      </section>`;
    }).join('');
  }
  $('modFilter').addEventListener('click', (e) => { const b = e.target.closest('[data-mf]'); if (!b) return; modFilter = b.dataset.mf || null; render(); });
  $('modCards').addEventListener('click', (e) => {
    const ed = e.target.closest('[data-editmod]');
    if (ed) { editModule(S.modules.find((m) => m.id === ed.dataset.editmod)); return; }
    const tk = e.target.closest('[data-modtasks]');
    if (tk) { Object.assign(taskFilter, { area: tk.dataset.modtasks, status: '未完成', owner: null, kind: null, query: '' }); setTab('tasks'); }
  });
  function editModule(m) {
    if (!m) return;
    openEditor({
      title: `更新系統 ${m.no} ${m.name}`,
      fields: [
        { key: 'status', label: '狀態', type: 'select', options: Object.keys(H.MODULE_STATUS), labels: Object.fromEntries(Object.entries(H.MODULE_STATUS).map(([k, v]) => [k, v.label])), required: true },
        { key: 'stage', label: '完成到哪一步（0–5：規格、計畫、程式、測試、上線）', type: 'text' },
        { key: 'nextStep', label: '下一步', type: 'text' },
        { key: 'blockers', label: '現在卡在哪裡（一行一項）', type: 'textarea' },
      ],
      values: { ...m, blockers: (m.blockers || []).join('\n'), stage: String(m.stage ?? '') },
      onSave: async (d) => {
        const stage = Math.max(0, Math.min(5, parseInt(d.stage, 10) || 0));
        await put('modules', m.id, { ...strip(m), status: d.status, stage, nextStep: d.nextStep, blockers: d.blockers.split('\n').map((x) => x.trim()).filter(Boolean), updatedDate: today() });
      },
    });
  }

  // ---------- 數轉專案 ----------
  function renderInits() {
    $('initCards').innerHTML = !S.loaded.initiatives ? '<p class="muted">載入中…</p>' : [...S.initiatives].sort(byOrder('order')).map((i) => {
      const steps = i.steps || [];
      const done = steps.filter((s) => s.status === '完成').length;
      const open = S.tasks.filter((t) => t.area === i.id && t.status !== '完成').length;
      const tone = i.status === '完成' ? 'good' : i.status === '暫停' ? 'idle' : 'info';
      return `<section class="panel mod">
        <div class="panel-head" style="margin:0"><h2>${esc(i.name)}</h2><span class="pill ${tone}">${esc(i.status)}</span></div>
        <p class="small" style="margin:0">${esc(i.summary || '')}</p>
        <p class="small" style="margin:0"><span class="muted">現況：</span>${esc(i.phase || '—')}</p>
        ${steps.length ? `<div><div class="small muted">步驟 ${done}／${steps.length} 完成</div>
          <div class="bigbar" style="margin:.3rem 0 .5rem"><i style="width:${steps.length ? Math.round(done / steps.length * 100) : 0}%"></i></div>
          <ul class="steps">${steps.map((s) => `<li><span><span class="pill ${stepTone(s.status)}">${esc(s.status)}</span></span><span>${esc(s.name)}${s.note ? `<span class="muted small">：${esc(s.note)}</span>` : ''}</span></li>`).join('')}</ul></div>` : ''}
        ${(i.links || []).length ? `<ul class="links">${i.links.map((l) => `<li><a href="${safeUrl(l.url)}" target="_blank" rel="noopener">${esc(l.label)}</a></li>`).join('')}</ul>` : ''}
        ${open ? `<div><button type="button" class="btn small ghost" data-inittasks="${esc(i.id)}">相關待辦 ${open} 件</button></div>` : ''}
      </section>`;
    }).join('');
  }
  $('initCards').addEventListener('click', (e) => {
    const b = e.target.closest('[data-inittasks]'); if (!b) return;
    Object.assign(taskFilter, { area: b.dataset.inittasks, status: '未完成', owner: null, kind: null, query: '' });
    setTab('tasks');
  });

  // ---------- 待辦清單 ----------
  function taskRow(t) {
    const done = t.status === '完成';
    return `<li class="${done ? 'done' : ''}" data-task="${esc(t.id)}">
      <input type="checkbox" class="check" ${done ? 'checked' : ''} aria-label="標記完成：${esc(t.title)}" data-toggle="${esc(t.id)}">
      <div><div class="t-title">${esc(t.title)}</div>
        ${t.note ? `<div class="t-note">${esc(t.note)}</div>` : ''}
        <div class="meta">${taskPill(t)}<span class="pill accent">${esc(t.owner || '未指定')}</span><span class="pill">${esc(shortArea(t.area))}</span>${t.kind ? `<span class="pill">${esc(t.kind)}</span>` : ''}${t.priority === '高' ? '<span class="pill warn">優先</span>' : ''}${t.due ? `<span class="pill">期限 ${esc(t.due)}</span>` : ''}</div></div>
      <button type="button" class="btn small ghost w" data-edittask="${esc(t.id)}">編輯</button>
    </li>`;
  }
  function options(el, list, current, allLabel) {
    el.innerHTML = `<option value="">${allLabel}</option>` + list.map(([v, l]) => `<option value="${esc(v)}" ${v === current ? 'selected' : ''}>${esc(l)}</option>`).join('');
  }
  function renderTasks() {
    const owners = [...new Set([...H.OWNERS, ...S.tasks.map((t) => t.owner).filter(Boolean)])].filter((o) => S.tasks.some((t) => t.owner === o));
    options($('fOwner'), owners.map((o) => [o, o]), taskFilter.owner, '全部');
    options($('fStatus'), [['未完成', '未完成（全部）'], ...H.TASK_STATUS.map((s) => [s, s])], taskFilter.status, '全部');
    const areas = [...[...S.modules].sort(byOrder('no')).map((m) => [m.id, `系統 ${m.no} ${m.name.replace(/（.*?）/g, '')}`]), ...[...S.initiatives].sort(byOrder('order')).map((i) => [i.id, i.name])];
    options($('fArea'), areas, taskFilter.area, '全部');
    $('fKind').value = taskFilter.kind || '';
    const s = H.taskSummary(S.tasks, now());
    $('taskFigures').innerHTML = [['未完成', s.open, ''], ['等主管決定', s.decisions, s.decisions ? 'crit' : ''], ['7 天內到期', s.soon, ''], ['已完成', s.done, 'good']]
      .map(([k, v, c]) => `<div class="${c}"><div class="k">${k}</div><div class="v">${v}</div></div>`).join('');
    const list = H.sortTasks(H.filterTasks(S.tasks, taskFilter), now());
    $('taskList').innerHTML = !S.loaded.tasks ? '<li class="muted" style="display:block">載入中…</li>'
      : list.length ? list.map(taskRow).join('') : '<li class="muted" style="display:block">沒有符合的待辦。</li>';
  }
  [['fOwner', 'owner'], ['fStatus', 'status'], ['fArea', 'area'], ['fKind', 'kind']].forEach(([id, k]) => {
    $(id).addEventListener('change', (e) => { taskFilter[k] = e.target.value || null; renderTasks(); applyWriteMode(); });
  });
  $('fQuery').addEventListener('input', (e) => { taskFilter.query = e.target.value; renderTasks(); applyWriteMode(); });

  async function toggleTask(id, checked) {
    const t = S.tasks.find((x) => x.id === id);
    if (!t) return;
    const next = { ...strip(t), status: checked ? '完成' : (t.prevStatus || '待辦'), doneDate: checked ? today() : '' };
    if (checked) next.prevStatus = t.status;
    try { await put('tasks', id, next); toast(checked ? '已標記完成。' : '已改回未完成。'); }
    catch (e) { toast(dbError(e)); render(); }
  }
  document.addEventListener('change', (e) => {
    const c = e.target.closest('input[data-toggle]');
    if (c) toggleTask(c.dataset.toggle, c.checked);
  });
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-edittask]');
    if (b) editTask(S.tasks.find((t) => t.id === b.dataset.edittask));
  });
  function taskFields() {
    const areas = [...[...S.modules].sort(byOrder('no')).map((m) => m.id), ...[...S.initiatives].sort(byOrder('order')).map((i) => i.id)];
    return [
      { key: 'title', label: '要做什麼', type: 'text', required: true },
      { key: 'owner', label: '負責人', type: 'select', options: H.OWNERS, required: true },
      { key: 'status', label: '狀態', type: 'select', options: H.TASK_STATUS, required: true },
      { key: 'area', label: '所屬系統或專案', type: 'select', options: areas, labels: Object.fromEntries(areas.map((a) => [a, areaName(a)])), required: true },
      { key: 'kind', label: '類型', type: 'select', options: ['決策', '資料', '行動'] },
      { key: 'priority', label: '優先度', type: 'select', options: H.PRIORITY },
      { key: 'due', label: '期限', type: 'date' },
      { key: 'source', label: '出處', type: 'text' },
      { key: 'note', label: '說明', type: 'textarea' },
    ];
  }
  function editTask(t) {
    openEditor({
      title: t ? '編輯待辦' : '新增待辦',
      fields: taskFields(),
      values: t || { status: '待辦', priority: '中', kind: '行動', area: taskFilter.area || 'mgmt' },
      onSave: async (d) => { await put('tasks', t ? t.id : newId('t'), { ...(t ? strip(t) : { createdDate: today() }), ...d }); },
      extraButton: t ? { label: '刪除', action: async () => { await db.collection('tasks').doc(t.id).delete(); } } : null,
    });
  }
  $('btnNewTask').addEventListener('click', () => editTask());

  // ---------- 時程 ----------
  function msRow(m) {
    const past = H.splitMilestones([m], now()).past.length > 0;
    const cls = m.type === '閘門' ? 'gate' : past ? '' : 'future';
    const when = m.end ? `${m.date}–${m.end}` : m.date;
    return `<li class="${cls}"><div class="when">${esc(when)}・${esc(m.type || '')}</div><div>${esc(m.title)}</div><div class="muted small">${esc(shortArea(m.area))}</div></li>`;
  }
  function renderTime() {
    const { past, upcoming } = H.splitMilestones(S.milestones, now());
    $('timeUp').innerHTML = upcoming.map(msRow).join('') || '<li class="muted">沒有排定的時程。</li>';
    $('timePast').innerHTML = [...past].reverse().map(msRow).join('') || '<li class="muted">還沒有。</li>';
  }

  // ---------- 文件與排程 ----------
  function renderDocs() {
    const groups = {};
    for (const d of S.docs) (groups[d.group || '其他'] = groups[d.group || '其他'] || []).push(d);
    $('docGroups').innerHTML = Object.entries(groups).map(([g, list]) => `<div class="docgroup"><h3 style="margin:0">${esc(g)}</h3>
      <ul class="doclist">${list.sort((a, b) => String(a.id).localeCompare(String(b.id))).map((d) => `<li><a href="${safeUrl(d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a></li>`).join('')}</ul></div>`).join('')
      || '<p class="muted">載入中…</p>';
    $('routineRows').innerHTML = S.routines.sort((a, b) => String(a.id).localeCompare(String(b.id))).map((r) => `<tr>
      <td>${esc(r.name)}</td><td>${esc(r.schedule)}</td><td>${esc(r.recipient || '')}</td>
      <td>${esc(r.lastRun || '—')} <span class="pill ${r.lastStatus === '成功' ? 'good' : r.lastStatus ? 'crit' : 'idle'}">${esc(r.lastStatus || '未知')}</span></td></tr>`).join('');
    $('agents').innerHTML = AGENTS.map((a) => {
      const last = S.notes.filter((n) => n.author === a.name).sort((x, y) => String(y.date || '').localeCompare(String(x.date || '')))[0];
      return `<div class="agent"><strong>${esc(a.name)}</strong> <span class="muted small">${esc(a.when)}</span>
        <p class="small" style="margin:.2rem 0">${esc(a.duty)}</p>
        <p class="small" style="margin:0">最近產出：${last ? `<button type="button" class="chip" data-note="${esc(last.id)}">${esc(last.title)}</button>` : '<span class="muted">尚未產出</span>'}</p></div>`;
    }).join('');
  }
  $('agents').addEventListener('click', (e) => { const b = e.target.closest('[data-note]'); if (!b) return; sel.note = b.dataset.note; noteFolder = null; setTab('notes'); });

  // ---------- 專案財務（系統 2 試作）----------
  function renderDash() {
    const data = C.computeAll(S.projects, S.invoices, now());
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
    const alerts = data.alerts.filter((a) => a.projectId === p.id);
    const invs = [...m.invoices].sort((a, b) => String(a.requestDate || a.dueDate || '').localeCompare(String(b.requestDate || b.dueDate || '')));
    const due = m.daysToDue === null ? '' : `（${m.daysToDue >= 0 ? `剩 ${m.daysToDue} 天` : `已過 ${-m.daysToDue} 天`}）`;
    el.innerHTML = `
      <h2>${esc(p.name)}</h2>
      <h3>合約資訊</h3>
      <dl class="kv"><dt>客戶代號</dt><dd>${esc(p.clientCode || '—')}</dd><dt>合約編號</dt><dd>${esc(p.contractNo || '待補（由請款紀錄自動建立）')}</dd>
        <dt>簽約日</dt><dd>${esc(p.signedDate || '—')}</dd><dt>合約到期日</dt><dd>${esc(p.dueDate || '—')}${due}</dd><dt>備註</dt><dd>${esc(p.note || '—')}</dd></dl>
      <h3>金額</h3>
      <dl class="kv"><dt>合約總額</dt><dd>${C.formatNTD(p.contractAmount)}</dd><dt>已請款</dt><dd>${C.formatNTD(m.billed)}（${pct(m.billingProgress)}）</dd>
        <dt>未請款</dt><dd>${C.formatNTD(m.unbilled)}</dd><dt>已實收</dt><dd>${C.formatNTD(m.received)}</dd><dt>未收款</dt><dd>${C.formatNTD(m.outstanding)}</dd></dl>
      <h3>警示原因</h3>
      ${alerts.length ? `<ul class="alerts">${alerts.map((a) => `<li class="sev${a.severity}"><span class="tag">${esc(a.title)}</span><span>${esc(a.message)}</span></li>`).join('')}</ul>` : '<p class="muted" style="margin:0">沒有警示。</p>'}
      <div class="w"><h3>更新進度與狀態</h3><div class="row">
        <label class="f" style="width:8rem">進度（%）<input type="number" id="pProgress" min="0" max="100" value="${esc(p.progress ?? 0)}"></label>
        <label class="f" style="width:9rem">狀態<select id="pStatus">${C.PROJECT_STATUSES.map((s) => `<option ${s === p.status ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
        <button class="btn small" id="pSave" type="button">儲存</button><button class="btn small danger" id="pDelete" type="button">刪除</button></div></div>
      <h3>請款紀錄</h3>
      ${invs.length ? `<ul class="timeline">${invs.map((i) => {
        const st = C.invoiceDisplayStatus(i, now());
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
        await writeBriefing({ projects: S.projects.map((x) => (x.id === p.id ? { id: p.id, ...next } : x)), invoices: S.invoices });
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
    render();
    if (window.matchMedia('(max-width: 900px)').matches) $('projectDetail').scrollIntoView({ behavior: 'smooth' });
  }
  $('alerts').addEventListener('click', (e) => { const li = e.target.closest('li[data-id]'); if (li) pickProject(li.dataset.id); });
  $('alerts').addEventListener('keydown', (e) => { if (e.key === 'Enter') { const li = e.target.closest('li[data-id]'); if (li) pickProject(li.dataset.id); } });
  $('projectRows').addEventListener('click', (e) => { const tr = e.target.closest('tr[data-id]'); if (tr) pickProject(tr.dataset.id); });

  // 匯入
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
    } catch (err) { toast('無法讀取檔案，請確認是 .xlsx 或 UTF-8 編碼的 .csv。'); }
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
        return `<tr>${fs.map((f) => { const v = rec[f.key]; return `<td>${esc(v === undefined ? '' : (f.type === 'number' && f.key !== 'progress' ? C.formatNTD(v) : v))}</td>`; }).join('')}<td>${res.error ? `<span class="pill crit">${esc(res.error)}</span>` : '可匯入'}</td></tr>`;
      }).join('')}</tbody>`;
  }
  $('impGo').addEventListener('click', async () => {
    const { rows, fields, type } = pending;
    const mapping = currentMapping();
    const ok = [], failed = [];
    rows.forEach((r, i) => { const res = C.mapRow(r, mapping, fields); if (res.error) failed.push({ row: i + 2, reason: res.error }); else ok.push(res.record); });
    const work = { projects: S.projects.map((x) => ({ id: x.id, ...strip(x) })), invoices: S.invoices.map((x) => ({ id: x.id, ...strip(x) })) };
    const before = new Map([...work.projects, ...work.invoices].map((x) => [x.id, JSON.stringify(x)]));
    const summary = type === 'project' ? C.upsertProjects(work, ok) : C.upsertInvoices(work, ok);
    const changed = [
      ...work.projects.filter((x) => before.get(x.id) !== JSON.stringify(x)).map((x) => ['projects', x]),
      ...work.invoices.filter((x) => before.get(x.id) !== JSON.stringify(x)).map((x) => ['invoices', x]),
    ];
    $('impGo').disabled = true; $('imp2').hidden = true; $('imp3').hidden = false;
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
  // 匯出與範本（經過 downloads，由檢視者確認後存檔）
  async function offerFile(filename, wb) {
    if (!window.claude) { XLSX.writeFile(wb, filename); return; }
    const dl = await window.claude.use('downloads');
    if (!dl) { toast('這個檢視無法下載檔案，請在 claude.ai 開啟此頁。'); return; }
    const blob = new Blob([XLSX.write(wb, { type: 'array', bookType: 'xlsx' })]);
    try { await dl.save({ filename, data: blob }); } catch (e) { if (e && e.code !== 'declined') toast('無法下載，請稍後再試。'); }
  }
  $('btnExport').addEventListener('click', () => {
    const d = now();
    const data = C.computeAll(S.projects, S.invoices, d);
    const t = data.totals;
    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([['項目', '金額（新台幣元）'], ['合約總額', t.contractAmount], ['累計已請款', t.billed], ['未收款', t.outstanding], ['逾期應收', t.overdue], [], ['匯出日期', C.formatDate(d)]]), '總覽');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.projects.map((p) => ({
      客戶代號: p.clientCode || '', 專案名稱: p.name, 合約編號: p.contractNo || '', 合約總額: Number(p.contractAmount) || 0, 簽約日: p.signedDate || '', 合約到期日: p.dueDate || '',
      到期倒數天數: p.metrics.daysToDue ?? '', 進度: Number(p.progress) || 0, 狀態: p.status || '', 已請款: p.metrics.billed, 請款進度: Math.round(p.metrics.billingProgress),
      未請款: p.metrics.unbilled, 已實收: p.metrics.received, 未收款: p.metrics.outstanding, 備註: p.note || '',
    }))), '專案明細');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(S.invoices.map((i) => ({
      專案名稱: i.projectName, 請款期別: i.period, 請款金額: Number(i.amount) || 0, 請款日: i.requestDate || '', 應收日: i.dueDate || '', 實收日: i.receivedDate || '', 實收金額: Number(i.receivedAmount) || 0, 狀態: C.invoiceDisplayStatus(i, d),
    }))), '請款紀錄');
    XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(data.alerts.map((a) => ({ 警示: a.title, 說明: a.message }))), '警示');
    offerFile(`管理層總覽_${C.formatDate(d).replace(/\//g, '')}.xlsx`, wb);
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
  function openEditor({ title, fields, values, onSave, levelNotice, extraButton }) {
    editCtx = { onSave };
    $('editTitle').textContent = title;
    $('editFields').innerHTML = fields.map((f) => {
      const v = values[f.key] ?? '';
      const full = f.type === 'textarea' ? ' style="grid-column:1/-1"' : '';
      let input;
      if (f.type === 'select') input = `<select name="${f.key}" id="ed-${f.key}" ${f.required ? 'required' : ''}><option value="">請選擇</option>${f.options.map((o) => `<option value="${esc(o)}" ${o === v ? 'selected' : ''}>${esc((f.labels || {})[o] || o)}</option>`).join('')}</select>`;
      else if (f.type === 'textarea') input = `<textarea name="${f.key}" id="ed-${f.key}">${esc(v)}</textarea>`;
      else input = `<input name="${f.key}" id="ed-${f.key}" value="${esc(v)}" ${f.required ? 'required' : ''} ${f.type === 'date' ? 'placeholder="YYYY/MM/DD" pattern="\\d{4}/\\d{2}/\\d{2}"' : ''}>`;
      return `<label class="f"${full}>${esc(f.label)}${f.required ? ' <span class="req">*</span>' : ''}${input}</label>`;
    }).join('') + (extraButton ? `<div style="grid-column:1/-1"><button type="button" class="btn small danger" id="edExtra">${esc(extraButton.label)}</button></div>` : '');
    if (extraButton) armDelete($('edExtra'), async () => { await extraButton.action(); editDlg.close(); toast('已刪除。'); });
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
    $('kbKinds').innerHTML = chip('全部', !kbFilter.kind && !kbFilter.subtype, 'data-kind=""') +
      Object.entries(KB.KINDS).map(([k, l]) => chip(l, kbFilter.kind === k, `data-kind="${k}"`)).join('');
    const subs = kbFilter.kind === 'COMPANY_FACT' ? KB.CATEGORIES : kbFilter.kind === 'KNOWLEDGE_ENTRY' ? KB.ENTRY_TYPES
      : [...KB.CATEGORIES.filter((c) => c !== '其他'), ...KB.ENTRY_TYPES];
    $('kbSubs').innerHTML = subs.map((s) => chip(s, kbFilter.subtype === s, `data-sub="${esc(s)}"`)).join('');
    const list = KB.filterItems(S.kb, kbFilter);
    $('kbItems').innerHTML = !S.loaded.kb ? '<li class="muted" style="padding:.6rem .5rem">載入中…</li>' : list.length ? list.map((it) => `
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
      ${KB.isSensitive(it.dataLevel) ? `<p class="notice">${esc(it.dataLevel)}：${esc(KB.SENSITIVE_WARNING)}。</p>` : ''}
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
    render();
  });
  $('kbSubs').addEventListener('click', (e) => { const b = e.target.closest('[data-sub]'); if (!b) return; kbFilter.subtype = kbFilter.subtype === b.dataset.sub ? null : b.dataset.sub; render(); });
  $('kbSearch').addEventListener('input', (e) => { kbFilter.query = e.target.value; render(); });
  $('kbItems').addEventListener('click', (e) => { const b = e.target.closest('[data-id]'); if (b) { sel.kb = b.dataset.id; render(); } });
  $('btnNewFact').addEventListener('click', () => editKb('COMPANY_FACT'));
  $('btnNewEntry').addEventListener('click', () => editKb('KNOWLEDGE_ENTRY'));

  // ---------- 情報與週報（筆記）----------
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
    if (!n) { el.innerHTML = '<p class="muted" style="margin:0">從左邊選一篇筆記。週報、外部情報摘要由 AI 員工寫入；知識庫素材由你放入。</p>'; return; }
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
  $('noteFolders').addEventListener('click', (e) => { const b = e.target.closest('[data-folder]'); if (!b) return; noteFolder = b.dataset.folder || null; render(); });
  $('noteItems').addEventListener('click', (e) => { const b = e.target.closest('[data-id]'); if (b) { sel.note = b.dataset.id; render(); } });
  $('btnNewNote').addEventListener('click', () => editNote());

  // ---------- 問公司知識顧問 ----------
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
    const systems = [...S.modules].sort(byOrder('no')).map((m) => ({ 名稱: `系統 ${m.no} ${m.name}`, 狀態: (H.MODULE_STATUS[m.status] || {}).label, 卡點: m.blockers, 下一步: m.nextStep, 資料等級: m.dataLevel }));
    const initiatives = S.initiatives.map((i) => ({ 名稱: i.name, 狀態: i.status, 現況: i.phase, 步驟: (i.steps || []).map((s) => `${s.name}：${s.status}`) }));
    const openTasks = S.tasks.filter((t) => t.status !== '完成').map((t) => ({ 待辦: t.title, 負責人: t.owner, 狀態: t.status, 期限: t.due || '' }));
    const briefing = S.projects.length ? C.buildBriefing(S.projects, S.invoices, now()) : S.briefing;
    const prompt = `你是優樂地永續服務股份有限公司的「公司知識顧問」，服務執行長、主管與數位轉型實習生。
規則：
1. 只根據下面提供的資料回答，用繁體中文，第一句講結論，再簡潔分點。
2. 每個結論後面用【名稱】標出引用來源（知識庫條目、系統名稱、專案名稱或待辦）。
3. 資料裡找不到就說「目前沒有這項資料」，並指出需要補哪一種素材。
4. 不回答金額、應收明細或客戶機密，請對方直接看「專案財務」頁。
5. 合約、保密、智慧財產相關解讀一律標【待法務確認】。
6. 證據強度為「推測」或「待確認」的資料，回答時要註明。不要編造。

知識庫（JSON）：${JSON.stringify(knowledge)}
八大系統（JSON）：${JSON.stringify(systems)}
數位轉型專案（JSON）：${JSON.stringify(initiatives)}
未完成待辦（JSON）：${JSON.stringify(openTasks)}
專案摘要（不含金額，JSON）：${JSON.stringify(briefing || { note: '尚無專案財務資料' })}

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
  let initial = 'home';
  try { initial = localStorage.getItem('udp-tab') || 'home'; } catch (e) { /* 忽略 */ }
  const hash = location.hash.replace('#', '');
  if (TABS.includes(hash)) initial = hash;
  setTab(initial);

  (async () => {
    // 網站版（Vercel）沒有 Claude 的資料庫：改用匯出的唯讀快照，不含專案財務資料。
    const snap = !window.claude && window.__UDP_SNAPSHOT__;
    if (snap) {
      S.meta = snap.meta || null;
      COLS.forEach((c) => { S[c] = Array.isArray(snap[c]) ? snap[c] : []; S.loaded[c] = true; });
      canWrite = false;
      $('conn').innerHTML = `唯讀快照，資料截至 ${esc(snap.exportedAt || '—')}。要更新進度、勾選待辦或問知識顧問，請到 <a href="https://claude.ai/artifact/WRwZtths21n7A2CVemw6RU" target="_blank" rel="noopener">Claude 版</a>。`;
      render();
      return;
    }
    db = window.claude ? await window.claude.use('db') : null;
    if (!db) { $('conn').textContent = '無法連到資料庫。請登入 claude.ai 並從 Claude 開啟這個頁面。'; return; }
    const user = await window.claude.use('user');
    if (user) { try { if ((await user.can('data.write')) === false) canWrite = false; } catch (e) { /* 未知時保留輸入 */ } }
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
    COLS.forEach(subscribe);
    db.doc('hub/meta').onSnapshot((d) => { S.meta = d.exists ? d.data() : null; render(); }, () => {});
    db.doc('shared/briefing').onSnapshot((d) => { S.briefing = d.exists ? d.data() : null; }, () => {});
    render();
  })();
})();
