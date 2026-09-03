import React, { useState, useRef, useCallback } from 'react';
import HomePage from './HomePage';
import QuestionCard from './QuestionCard';
import ResultPage from './ResultPage';

// 👇 部署 Google Apps Script 後，把這裡換成你的 Web App URL（.../exec 結尾）
const GAS_WEB_APP_URL = 'https://script.google.com/macros/s/AKfycbzO6VZNZH_5pQIIsQlMKy3dnPgldaUbnFFPrcXgN_Fa3a9cOAgY1lHHgWmF_Aj-Wteu/exec';



// 產生一個此次填答的唯一識別碼，讓後端可以判斷「更新既有紀錄」還是「新增一筆」
function generateSessionId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

function App() {
  // 控制目前顯示的畫面: 'home' | 'survey' | 'result'
  const [currentView, setCurrentView] = useState('home');
  
  // 儲存從首頁填寫的公司資料
  const [leadData, setLeadData] = useState(null);
  
  // 儲存最後的問卷結果
  const [surveyResult, setSurveyResult] = useState(null);

  // 用 ref 存放此次填答的識別碼與名單資料，避免 callback 抓到過期的 state（closure 問題）
  const sessionIdRef = useRef(generateSessionId());
  const leadDataRef = useRef(null);

  // 實際發送到後端的函式，回傳 true/false 代表這次送出是否成功
  const postToBackend = useCallback(async (payload) => {
    if (!GAS_WEB_APP_URL || GAS_WEB_APP_URL.includes('YOUR_DEPLOYMENT_ID')) {
      console.warn('尚未設定 GAS_WEB_APP_URL，略過本次儲存。請先部署 Google Apps Script 並填入網址。');
      return false;
    }

    try {
      // 用 text/plain 避免瀏覽器發出 CORS 預檢 (preflight)，GAS 端用 e.postData.contents 解析
      const response = await fetch(GAS_WEB_APP_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain;charset=utf-8' },
        body: JSON.stringify(payload),
      });

      let success = true;
      try {
        const data = await response.json();
        if (data && data.ok === false) success = false;
      } catch (_parseErr) {
        // 讀不到回應內容不代表送出失敗，fetch 沒有丟出例外就當作已送達後端
      }
      return success;
    } catch (err) {
      console.error('儲存到後端失敗：', err);
      return false;
    }
  }, []);

  // 首頁表單送出後觸發
  const handleStartSurvey = (formData) => {
    leadDataRef.current = formData;
    setLeadData(formData);
    setCurrentView('survey');
    console.log("已暫存名單：", formData);
    // 一開始就先存一筆，確保後端已經有名單資料
    postToBackend({
      sessionId: sessionIdRef.current,
      status: 'in_progress',
      leadData: formData,
      currentIndex: 0,
      answersByCode: {},
      surveyResult: null,
    });
  };

  // 「儲存進度」按鈕觸發：QuestionCard 會直接把目前最新的 currentIndex / answersByCode 傳進來
  // 回傳 Promise<boolean>，QuestionCard 會依照結果切換按鈕文字
  const handleManualSave = useCallback((currentIndex, answersByCode) => {
    return postToBackend({
      sessionId: sessionIdRef.current,
      status: 'in_progress',
      leadData: leadDataRef.current || {},
      currentIndex,
      answersByCode,
      surveyResult: null,
    });
  }, [postToBackend]);

  // 問卷最後一題完成後觸發（QuestionCard 會一併把最後的作答內容與題目索引傳回來）
  const handleSurveyComplete = (result, answersByCode, currentIndex) => {
    // 接收問卷組件回傳的完整摘要
    setSurveyResult(result);
    setCurrentView('result');
    // 完成時儲存最終結果與狀態
    postToBackend({
      sessionId: sessionIdRef.current,
      status: 'completed',
      leadData: leadDataRef.current || {},
      currentIndex: currentIndex ?? 0,
      answersByCode: answersByCode || {},
      surveyResult: result,
    });
  };

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 py-6 sm:py-12 px-4 sm:px-6 flex items-start justify-center">
      <div className="w-full max-w-4xl">
        {currentView === 'home' && <HomePage onStartSurvey={handleStartSurvey} />}
        {currentView === 'survey' && (
          <QuestionCard
            onComplete={handleSurveyComplete}
            onSaveNow={handleManualSave}
          />
        )}
        {currentView === 'result' && <ResultPage surveyResult={surveyResult} leadData={leadData} />}
      </div>
    </div>
  );
}

export default App;