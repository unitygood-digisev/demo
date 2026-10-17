// 公司知識庫：資料定義、搜尋與篩選。只在前端對已載入資料執行，不呼叫任何大模型或外部服務。
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KB = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const KINDS = { COMPANY_FACT: '公司資料', KNOWLEDGE_ENTRY: '知識條目' };
  const CATEGORIES = ['服務項目', '部門', '工具', '客戶類型', '流程', '指標', '其他'];
  const ENTRY_TYPES = ['SOP', '案例', '提案範本', '方法論', '常見問答', '其他'];
  const DATA_LEVELS = ['公開', '內部一般', '內部敏感', '客戶機密'];
  const EVIDENCE = ['有證據', '推測', '待確認'];
  const SENSITIVE_LEVELS = ['內部敏感', '客戶機密'];
  const SENSITIVE_WARNING = '此等級只建議存摘要與索取方式，不要存客戶名稱、金額或機密全文';

  const FIELDS = {
    COMPANY_FACT: [
      { key: 'name', label: '資料名稱', type: 'text', required: true },
      { key: 'category', label: '類別', type: 'select', options: CATEGORIES, required: true },
      { key: 'detail', label: '內容', type: 'textarea' },
      { key: 'dataLevel', label: '資料等級', type: 'select', options: DATA_LEVELS, required: true },
      { key: 'evidence', label: '證據強度', type: 'select', options: EVIDENCE, required: true },
      { key: 'source', label: '來源', type: 'text' },
      { key: 'updatedDate', label: '更新日期', type: 'date' },
    ],
    KNOWLEDGE_ENTRY: [
      { key: 'name', label: '條目標題', type: 'text', required: true },
      { key: 'entryType', label: '條目類型', type: 'select', options: ENTRY_TYPES, required: true },
      { key: 'summary', label: '摘要（三到五句）', type: 'textarea' },
      { key: 'content', label: '全文', type: 'textarea' },
      { key: 'tags', label: '標籤（逗號分隔）', type: 'text' },
      { key: 'dataLevel', label: '資料等級', type: 'select', options: DATA_LEVELS, required: true },
      { key: 'evidence', label: '證據強度', type: 'select', options: EVIDENCE, required: true },
      { key: 'source', label: '來源', type: 'text' },
      { key: 'updatedDate', label: '更新日期', type: 'date' },
      { key: 'relatedService', label: '相關服務線', type: 'text' },
    ],
  };

  const SEARCH_KEYS = ['name', 'summary', 'content', 'tags', 'detail'];

  function subtypeOf(item) {
    return item.kind === 'COMPANY_FACT' ? item.category : item.entryType;
  }

  // 篩選：kind 為 null 代表不限；subtype 為 null 代表不限。關鍵字以空白分隔，全部都要命中。
  function filterItems(items, { query = '', kind = null, subtype = null } = {}) {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    return items
      .filter((it) => !kind || it.kind === kind)
      .filter((it) => !subtype || subtypeOf(it) === subtype)
      .filter((it) => {
        if (!terms.length) return true;
        const hay = SEARCH_KEYS.map((k) => it[k] || '').join('\n').toLowerCase();
        return terms.every((t) => hay.includes(t));
      })
      .sort((a, b) => String(b.updatedDate || '').localeCompare(String(a.updatedDate || '')));
  }

  function isSensitive(level) { return SENSITIVE_LEVELS.includes(level); }

  return {
    KINDS, CATEGORIES, ENTRY_TYPES, DATA_LEVELS, EVIDENCE, SENSITIVE_WARNING, FIELDS,
    subtypeOf, filterItems, isSensitive,
  };
});
