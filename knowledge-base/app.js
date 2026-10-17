// 公司知識庫：畫面。資料只存在瀏覽器 localStorage，不呼叫任何外部服務。
(function () {
  'use strict';
  const STORE_KEY = 'company-kb-v1';
  const $ = (id) => document.getElementById(id);

  let items = load();
  let selectedId = null;
  let filter = { query: '', kind: null, subtype: null };
  let editing = null; // { kind, id }

  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) { const v = JSON.parse(raw); if (Array.isArray(v)) return v; }
    } catch (e) { /* 無痕視窗或封鎖儲存時，用空資料 */ }
    return [];
  }

  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(items)); }
    catch (e) { alert('瀏覽器無法儲存資料（可能是無痕模式或空間不足），重新整理後資料會消失。'); }
  }

  function esc(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function today() {
    const d = new Date();
    return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
  }

  function chip(label, active, attrs) {
    return `<button type="button" class="chip ${active ? 'active' : ''}" ${attrs}>${esc(label)}</button>`;
  }

  function render() {
    const empty = items.length === 0;
    $('empty').hidden = !empty;
    $('split').hidden = empty;

    $('kindChips').innerHTML =
      chip('全部', !filter.kind && !filter.subtype, 'data-kind=""') +
      Object.entries(KB.KINDS).map(([k, label]) => chip(label, filter.kind === k, `data-kind="${k}"`)).join('');

    const subs = filter.kind === 'COMPANY_FACT' ? KB.CATEGORIES
      : filter.kind === 'KNOWLEDGE_ENTRY' ? KB.ENTRY_TYPES
      : [...KB.CATEGORIES.filter((c) => c !== '其他'), ...KB.ENTRY_TYPES];
    $('subChips').innerHTML = subs.map((s) => chip(s, filter.subtype === s, `data-sub="${esc(s)}"`)).join('');

    const list = KB.filterItems(items, filter);
    $('items').innerHTML = list.length ? list.map((it) => `
      <li data-id="${esc(it.id)}" class="${it.id === selectedId ? 'selected' : ''}">
        <div>${esc(it.name)}</div>
        <div class="meta">
          <span class="badge">${esc(KB.KINDS[it.kind])}・${esc(KB.subtypeOf(it) || '—')}</span>
          <span class="badge ${KB.isSensitive(it.dataLevel) ? 'danger' : ''}">${esc(it.dataLevel || '—')}</span>
          <span class="badge">${esc(it.evidence || '—')}</span>
          <span class="badge">${esc(it.updatedDate || '未填日期')}</span>
        </div>
      </li>`).join('') : '<li class="muted" style="cursor:default">沒有符合的資料。</li>';

    renderDetail();
  }

  function renderDetail() {
    const it = items.find((x) => x.id === selectedId);
    const el = $('detail');
    if (!it) { el.innerHTML = '<p class="muted">從左邊選一筆，查看詳情。</p>'; return; }
    const fields = KB.FIELDS[it.kind];
    el.innerHTML = `
      <h2>${esc(it.name)}</h2>
      <p class="muted">${esc(KB.KINDS[it.kind])}</p>
      ${KB.isSensitive(it.dataLevel) ? `<p class="notice">${esc(it.dataLevel)}：${esc(KB.SENSITIVE_WARNING)}。</p>` : ''}
      <dl class="kv">${fields.filter((f) => f.key !== 'name').map((f) => `<dt>${esc(f.label)}</dt><dd>${esc(it[f.key] || '—')}</dd>`).join('')}</dl>
      <div class="edit-row">
        <button type="button" class="btn small" id="btnEdit">編輯</button>
        <button type="button" class="btn small secondary" id="btnDelete">刪除</button>
      </div>`;
    $('btnEdit').addEventListener('click', () => openEditor(it.kind, it.id));
    $('btnDelete').addEventListener('click', () => {
      if (!confirm(`確定刪除「${it.name}」？`)) return;
      items = items.filter((x) => x.id !== it.id);
      selectedId = null;
      save();
      render();
    });
  }

  $('kindChips').addEventListener('click', (e) => {
    const b = e.target.closest('[data-kind]');
    if (!b) return;
    const k = b.dataset.kind || null;
    // 再按一次已選的分類即取消
    filter.kind = k && filter.kind === k ? null : k;
    filter.subtype = null;
    render();
  });
  $('subChips').addEventListener('click', (e) => {
    const b = e.target.closest('[data-sub]');
    if (!b) return;
    filter.subtype = filter.subtype === b.dataset.sub ? null : b.dataset.sub;
    render();
  });
  $('search').addEventListener('input', (e) => { filter.query = e.target.value; render(); });
  $('items').addEventListener('click', (e) => {
    const li = e.target.closest('li[data-id]');
    if (!li) return;
    selectedId = li.dataset.id;
    render();
    if (window.matchMedia('(max-width: 860px)').matches) $('detail').scrollIntoView({ behavior: 'smooth' });
  });

  // ---- 新增與編輯 ----
  const dlg = $('editDialog');

  function openEditor(kind, id) {
    editing = { kind, id };
    const it = id ? items.find((x) => x.id === id) : { dataLevel: '內部一般', evidence: '待確認', updatedDate: today() };
    $('editTitle').textContent = `${id ? '編輯' : '新增'}${KB.KINDS[kind]}`;
    $('editFields').innerHTML = KB.FIELDS[kind].map((f) => {
      const v = it[f.key] || '';
      let input;
      if (f.type === 'select') {
        input = `<select name="${f.key}" ${f.required ? 'required' : ''}><option value="">請選擇</option>${f.options.map((o) => `<option ${o === v ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
      } else if (f.type === 'textarea') {
        input = `<textarea name="${f.key}">${esc(v)}</textarea>`;
      } else {
        input = `<input name="${f.key}" value="${esc(v)}" ${f.required ? 'required' : ''} ${f.type === 'date' ? 'placeholder="YYYY/MM/DD" pattern="\\d{4}/\\d{2}/\\d{2}"' : ''}>`;
      }
      return `<label class="field">${esc(f.label)}${f.required ? ' <span class="req">*</span>' : ''}${input}</label>`;
    }).join('');
    $('editFields').querySelector('[name="dataLevel"]').addEventListener('change', updateNotice);
    updateNotice();
    dlg.showModal();
  }

  // 只是提示，不阻擋儲存
  function updateNotice() {
    const level = $('editFields').querySelector('[name="dataLevel"]').value;
    const n = $('sensitiveNotice');
    n.hidden = !KB.isSensitive(level);
    n.textContent = KB.SENSITIVE_WARNING;
  }

  $('editForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    for (const k of Object.keys(data)) data[k] = data[k].trim();
    if (!data.updatedDate) data.updatedDate = today();
    if (editing.id) {
      Object.assign(items.find((x) => x.id === editing.id), data);
      selectedId = editing.id;
    } else {
      const id = `kb_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
      items.push({ id, kind: editing.kind, ...data });
      selectedId = id;
    }
    save();
    dlg.close();
    render();
  });
  $('editCancel').addEventListener('click', () => dlg.close());

  $('btnNewFact').addEventListener('click', () => openEditor('COMPANY_FACT'));
  $('btnNewEntry').addEventListener('click', () => openEditor('KNOWLEDGE_ENTRY'));
  $('btnFirst').addEventListener('click', () => openEditor('COMPANY_FACT'));

  render();
})();
