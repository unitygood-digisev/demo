export const AXIS_NAMES = [
  '治理',
  '職場',
  '環境',
  '數位',
];

export const AXIS_LEVELS = ['起步', '建置中', '已成形', '成熟'];

export const AXIS_GUIDANCE = [
  {
    name: AXIS_NAMES[0],
    levels: {
      起步: '公司治理與誠信制度尚在起點，目前多半還沒有專責人力與書面規則。',
      建置中: '已經有部分治理作為，但還沒串成完整制度，權責與文件較零散。',
      已成形: '治理制度大致完備，缺口主要在對供應商的管理與文件化程度。',
      成熟: '治理與誠信制度成熟，已具備回應國際客戶稽核的基礎。',
    },
  },
  {
    name: AXIS_NAMES[1],
    levels: {
      起步: '勞動與職場管理制度尚在起點，基本規範與申訴機制多半還沒建立。',
      建置中: '已有基本勞動制度，但落實程度與紀錄還不完整。',
      已成形: '勞動制度大致完備，缺口在人權盡職調查這類進階要求。',
      成熟: '勞動與職場管理成熟，已具備回應國際人權準則的基礎。',
    },
  },
  {
    name: AXIS_NAMES[2],
    levels: {
      起步: '環境與資源管理尚在起點，能源、廢棄物、氣候風險多半還沒系統化管理。',
      建置中: '已有部分環境管理作為，但追蹤與紀錄還不完整。',
      已成形: '環境管理大致完備，缺口在氣候風險辨識與再生能源比例追蹤。',
      成熟: '環境與資源管理成熟，已能回應多數客戶與金融機構的環境審查。',
    },
  },
  {
    name: AXIS_NAMES[3],
    levels: {
      起步: '能資源數據與數位管理尚在起點，多半還沒有系統化的統計。這一塊是所有後續作業的前置條件，越早補起來越省事。',
      建置中: '已有部分數據，但完整度與即時性還不足，多半還在人工整理階段。',
      已成形: '數據基礎大致完備，缺口在盤查的查證與數位化程度。',
      成熟: '數據與數位備妥度成熟，已具備回應客戶與查證單位的即時提供能力。',
    },
  },
];

// --- 顧問推薦服務字典檔 ---
const SERVICE_DICTIONARY = {
  'SVC-GHG': { code: 'SVC-GHG', name: 'ISO 14064-1 溫室氣體盤查輔導', link: 'https://www.unitygood.com/unity-sustainability-strategy-report-iso-service' },
  'SVC-REPORT': { code: 'SVC-REPORT', name: '永續報告書撰寫輔導', link: 'https://www.unitygood.com/unity-sustainability-strategy-report-iso-service' },
  'SVC-PROC': { code: 'SVC-PROC', name: 'ISO 20400 永續採購指南輔導', link: 'https://www.unitygood.com/unity-sustainability-strategy-report-iso-service' },
  'SVC-STRAT': { code: 'SVC-STRAT', name: '永續策略及認證輔導', link: 'https://www.unitygood.com/unity-sustainability-strategy-report-iso-service' },
  'SVC-CUSTOM': { code: 'SVC-CUSTOM', name: '創新設計及系統評估專案', link: 'https://www.unitygood.com/unity-sustainability-creative-project-service' },
  'SVC-TRAIN': { code: 'SVC-TRAIN', name: '永續工作坊／永續培力', link: 'https://www.unitygood.com/unity-sustainability-workshop-service' },
  'SVC-GAME': { code: 'SVC-GAME', name: '永續桌遊培力', link: 'https://www.unitygood.com/boardgame' },
  'SVC-CN': { code: 'SVC-CN', name: '碳中和與影響力管理輔導', link: 'https://www.unitygood.com/unity-sustainability-strategy-report-iso-service' },
  'SVC-ILAB': { code: 'SVC-ILAB', name: '永續 iLab 會員平台', link: 'https://www.unitygood.com/ilab' },
};

const clampScore = (value) => Math.max(0, Math.min(100, Math.round(Number(value) || 0)));

export const normalizeAxisScores = (axisScores) => {
  const baseScores = Array.isArray(axisScores) ? axisScores : [];
  return AXIS_NAMES.map((_, index) => clampScore(baseScores[index]));
};

export const getAxisLevel = (score) => {
  const normalized = clampScore(score);
  if (normalized <= 25) return '起步';
  if (normalized <= 50) return '建置中';
  if (normalized <= 75) return '已成形';
  return '成熟';
};

export const getAxisGuide = (axisIndex, score) => {
  const profile = AXIS_GUIDANCE[axisIndex];
  if (!profile) return '';
  const level = getAxisLevel(score);
  return profile.levels[level] || '';
};

const getChildrenMap = (nodes = []) => {
  return nodes.reduce((map, node) => {
    const parentKey = node.parentId ?? '__root__';
    const bucket = map.get(parentKey) || [];
    bucket.push(node);
    map.set(parentKey, bucket);
    return map;
  }, new Map());
};

const getNodeMap = (nodes = []) => {
  return nodes.reduce((map, node) => map.set(node.id, node), new Map());
};

const getSelectedLeafNode = (question, answer) => {
  const nodes = question?.nodes || [];
  const nodeMap = getNodeMap(nodes);
  const path = Array.isArray(answer?.path) ? answer.path : [];
  const lastNodeId = path[path.length - 1];
  return lastNodeId ? nodeMap.get(lastNodeId) || null : null;
};

export const buildAxisScores = (answersByCode, questionBank) => {
  const axisTotals = AXIS_NAMES.map(() => ({ weightedScore: 0, weightedMax: 0 }));

  questionBank.forEach((question) => {
    if (question.kind !== 'score') return;

    const answer = answersByCode?.[question.code] || {};
    const selectedNode = getSelectedLeafNode(question, answer);
    const score = clampScore(selectedNode?.score);
    const axisIndex = question.axisIndex;
    const weight = Number(question.weight) || 0;

    if (axisIndex === undefined || axisIndex === null || axisIndex < 0 || axisIndex >= axisTotals.length) return;

    axisTotals[axisIndex].weightedScore += score * weight;
    axisTotals[axisIndex].weightedMax += 100 * weight;
  });

  return axisTotals.map(({ weightedScore, weightedMax }) => {
    if (weightedMax <= 0) return 0;
    return Math.round((weightedScore / weightedMax) * 100);
  });
};

export const buildComplianceResults = (answersByCode, questionBank) => {
  return questionBank
    .filter((question) => question.kind === 'compliance')
    .map((question) => {
      const answer = answersByCode?.[question.code] || {};
      const selectedNode = getSelectedLeafNode(question, answer);
      const lamp = selectedNode?.lamp || selectedNode?.score || '灰燈';

      const descriptionByLamp = {
        綠燈: '目前未見異常，建議持續維持現有管理。',
        黃燈: '已有改善基礎，建議持續追蹤並保留佐證。',
        紅燈: '需優先處理，建議儘速完成改善。',
        灰燈: '資訊未確認，建議先補齊現況資料。',
      };

      return {
        code: question.code,
        title: question.title,
        lamp,
        description: descriptionByLamp[lamp] || descriptionByLamp.灰燈,
      };
    });
};

export const buildSignalSummary = (answersByCode, questionBank) => {
  const signalQuestions = questionBank.filter((question) => question.kind === 'signal');

  return signalQuestions.map((question) => {
    const answer = answersByCode?.[question.code] || {};
    const selectedIds = Array.isArray(answer.selectedIds) ? answer.selectedIds : [];
    const selectedNodes = (question.nodes || []).filter((node) => selectedIds.includes(node.id));
    const total = selectedNodes.reduce((sum, node) => sum + clampScore(node.score), 0);

    return {
      code: question.code,
      title: question.title,
      score: total,
      selectedIds,
    };
  });
};

// --- 🌟 核心：看診式顧問推薦運算引擎 ---
export const buildRecommendations = (answersByCode = {}, questionBank = [], axisScores = [], complianceResults = [], signalSummary = []) => {
  try {
    const recs = [];
    
    // 安全新增機制：確保不會推播重複的服務，且最多只出2張卡
    const addRec = (code, message, ctaText) => {
      if (recs.length < 2 && !recs.find((r) => r.code === code)) {
        recs.push({ ...SERVICE_DICTIONARY[code], message, ctaText });
      }
    };

    const getScore = (code) => {
      const q = questionBank.find((q) => q.code === code);
      const ans = answersByCode[code];
      return clampScore(getSelectedLeafNode(q, ans)?.score);
    };

    // 【優先級 1：客戶主動意願 (B3)】
    const b3Selected = answersByCode?.['B3']?.selectedIds || [];
    if (b3Selected.includes('B3-1')) addRec('SVC-GHG', '您在問卷中提到未來一年想優先處理「溫室氣體盤查」。針對這項需求，建議您可以先從 ISO 14064-1 的基準盤查著手，將第一批碳數據準備到位。', '諮詢碳盤查輔導方案');
    if (b3Selected.includes('B3-2')) addRec('SVC-REPORT', '您提到接下來想優先推進「永續報告書撰寫」。若目前內部尚缺明確架構，建議可以先安排一次報告書的健檢與利害關係人梳理，確認揭露重點。', '諮詢報告書撰寫輔導');
    if (b3Selected.includes('B3-3')) addRec('SVC-PROC', '針對您想優先處理的「客戶供應鏈問卷」需求，建議可先透過 ISO 20400 框架，將公司現有的採購與供應商管理機制做一次對齊，找出答題缺口。', '了解永續採購與供應鏈管理');
    if (b3Selected.includes('B3-4')) addRec('SVC-STRAT', '既然「ESG 策略與目標設定」是您接下來的重點，建議可以先進行一次整體的永續資源盤點，將部門權責與中長期藍圖具體定下來。', '規劃永續策略藍圖');
    if (b3Selected.includes('B3-5')) addRec('SVC-CUSTOM', '看到您有意願進行「ESG 系統導入」。在導入軟體前，建議先對現有的作業流程與數據收集方式進行評估，確保人工作業能順利銜接數位化。', '評估 ESG 系統導入');

    // 【優先級 2：針對特定法遵缺口急救】
    const checkRed = (code) => complianceResults.find((c) => c.code === code)?.lamp === '紅燈';
    if (checkRed('G4')) addRec('SVC-STRAT', '檢視您的合規狀況，目前在公平交易方面有尚未結案的紀錄。建議優先安排一次內控與治理機制的健檢，以避免後續衍生的營運與商譽風險。', '預約治理與合規盤點');
    if (checkRed('S1')) addRec('SVC-STRAT', '看到您在勞動基準法方面有尚未提出改善計畫的裁罰紀錄。這通常是勞檢與客戶稽核的必查重點，建議優先針對勞資規範進行盤點與改善。', '預約勞資規範與改善盤點');
    if (checkRed('S2')) addRec('SVC-STRAT', '根據您的回覆，目前有尚未落幕的職場平權或歧視爭議事件。建議盡快重新檢視內部的申訴機制與防範流程，以穩定職場環境與人才留任。', '預約職場平權與合規盤點');
    if (checkRed('S5')) addRec('SVC-STRAT', '您提到近期有工時或薪資相關的未結案裁罰。這在國際供應鏈稽核中屬於高風險項目，建議立即針對人事排班與出勤管理機制進行複查。', '預約勞動合規與資源盤點');
    if (checkRed('E5')) addRec('SVC-STRAT', '檢視合規狀態，貴公司目前有環保法規的未結案項目。為避免影響後續的營運許可或大客戶評鑑，建議優先針對該環境缺口擬定改善對策。', '預約環境合規與改善盤點');

    // 【優先級 3：最低軸弱項補強】
    const sortedAxes = axisScores.map((score, index) => ({ score, index })).sort((a, b) => a.score - b.score);
    for (const axis of sortedAxes) {
      if (recs.length >= 2) break; // 滿了就提早跳出
      if (axis.index === 3) {
        if (getScore('E6') <= 30) addRec('SVC-GHG', '從數據備妥度來看，貴公司尚未啟動溫室氣體盤查。因應目前的供應鏈減碳要求，建議您可以開始著手 ISO 14064-1 的基礎盤查作業。', '啟動溫室氣體盤查');
        else addRec('SVC-STRAT', '檢視您的數位備妥度，目前最缺乏的是能資源數據的系統化整合。這是後續所有盤查與問卷的基石，建議先從建立數據蒐集機制開始。', '評估能資源數據整合');
      } else if (axis.index === 0) {
        addRec('SVC-STRAT', '從治理與誠信面向來看，目前較缺乏明確的管理規則與目標。建議可以先制定一份基本的永續策略藍圖，讓內部有依循，面對客戶時也有標準答案。', '規劃永續策略藍圖');
      } else if (axis.index === 1) {
        addRec('SVC-TRAIN', '看到您在勞動與職場的指標較弱，多數基本規範尚待建立。建議可以先透過內部的培力工作坊，凝聚勞資共識並補齊必備的管理紀錄。', '了解永續培力工作坊');
      } else if (axis.index === 2) {
        addRec('SVC-GHG', '根據環境與資源面向的得分，貴公司目前尚未掌握能資源與廢棄物的具體流向。建議先從整體的環境盤查開始，建立後續管理的科學依據。', '了解環境與排放盤查');
      }
    }

    // 【優先級 4：分級補位與終極備用】
    const avgScore = axisScores.length > 0 ? axisScores.reduce((a, b) => a + b, 0) / axisScores.length : 0;
    const totalSignalScore = signalSummary.reduce((sum, s) => sum + s.score, 0);

    if (avgScore <= 25) addRec('SVC-GAME', '綜合您的整體成熟度，目前正處於 ESG 的起步階段。建議先不用急著做大型專案，可以先透過永續桌遊或基礎工作坊，讓團隊建立基本概念。', '體驗永續桌遊與培力');
    if (avgScore >= 76) addRec('SVC-CN', '檢視您的各項指標，貴公司在 ESG 的基礎建設已相當健全。接下來，建議可以往更進階的碳中和管理或社會影響力量化評估邁進。', '探索進階永續專案');
    if (totalSignalScore <= 2) addRec('SVC-ILAB', '綜合評估目前的推動現況，貴公司可能暫時缺乏推動 ESG 的相關資源。建議您可以先加入永續 iLab 平台，定期接收法規資訊，保持對議題的敏銳度即可。', '加入永續 iLab 平台');
    
    // 絕對保底 (確保一定出滿 2 張)
    addRec('SVC-STRAT', '永續發展需要通盤的策略規劃。建議您可以進行一次整體的資源盤點，將未來的目標與路徑具體定下來。', '規劃永續策略藍圖');
    addRec('SVC-CUSTOM', '每個企業的永續旅程都是獨特的。若您目前遇到推動瓶頸，歡迎與我們聊聊，為您量身打造最適合的解方。', '預約專屬顧問諮詢');

    return recs.slice(0, 2);
    
  } catch (error) {
    console.error("生成推薦邏輯時發生錯誤:", error);
    // 發生預期外錯誤時，回傳絕對安全的備案
    return [
      { ...SERVICE_DICTIONARY['SVC-STRAT'], message: '永續發展需要通盤的策略規劃。建議您可以進行一次整體的資源盤點，將未來的目標與路徑具體定下來。', ctaText: '規劃永續策略藍圖' },
      { ...SERVICE_DICTIONARY['SVC-CUSTOM'], message: '每個企業的永續旅程都是獨特的。若您目前遇到推動瓶頸，歡迎與我們聊聊，為您量身打造最適合的解方。', ctaText: '預約專屬顧問諮詢' }
    ];
  }
};

export const buildReportSummary = (answersByCode, questionBank) => {
  const axisScores = buildAxisScores(answersByCode, questionBank);
  const axisLevels = normalizeAxisScores(axisScores).map((score) => getAxisLevel(score));
  const complianceResults = buildComplianceResults(answersByCode, questionBank);
  const signalSummary = buildSignalSummary(answersByCode, questionBank);
  
  // 生成顧問專屬推薦卡片資料
  const recommendations = buildRecommendations(answersByCode, questionBank, axisScores, complianceResults, signalSummary);

  return {
    axisScores,
    axisLevels,
    complianceResults,
    signalSummary,
    recommendations, // 👉 之前漏掉的關鍵：將推薦結果包裝回傳
  };
};