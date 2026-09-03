import React, { useMemo } from 'react';
import {
  Chart as ChartJS,
  RadialLinearScale,
  PointElement,
  LineElement,
  Filler,
  Tooltip,
  Legend,
} from 'chart.js';
import { Radar } from 'react-chartjs-2';
import { AXIS_GUIDANCE, AXIS_NAMES, getAxisGuide, getAxisLevel, normalizeAxisScores } from './esgScoring';

ChartJS.register(RadialLinearScale, PointElement, LineElement, Filler, Tooltip, Legend);

const levelToneClass = {
  起步: 'bg-slate-100 text-slate-700 border-slate-200',
  建置中: 'bg-amber-50 text-amber-700 border-amber-200',
  已成形: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  成熟: 'bg-cyan-50 text-cyan-700 border-cyan-200',
};

const ResultPage = ({ surveyResult, leadData }) => {
  const axisScores = normalizeAxisScores(surveyResult?.axisScores);
  const axisLevels = Array.isArray(surveyResult?.axisLevels) && surveyResult.axisLevels.length === AXIS_NAMES.length
    ? surveyResult.axisLevels
    : axisScores.map((score) => getAxisLevel(score));
  const complianceResults = Array.isArray(surveyResult?.complianceResults) ? surveyResult.complianceResults : [];
  
  // 👉 提取引擎傳來的推薦清單 (若無資料預設空陣列)
  const recommendations = Array.isArray(surveyResult?.recommendations) ? surveyResult.recommendations : [];

  const data = {
    labels: AXIS_NAMES,
    datasets: [
      {
        label: '企業成熟度',
        data: axisScores,
        backgroundColor: 'rgba(15, 23, 42, 0.16)',
        borderColor: 'rgba(15, 23, 42, 0.78)',
        pointBackgroundColor: 'rgba(15, 23, 42, 1)',
        pointBorderColor: '#fff',
        pointHoverBackgroundColor: '#fff',
        pointHoverBorderColor: 'rgba(15, 23, 42, 1)',
        borderWidth: 2,
      },
    ],
  };

  const options = {
    layout: {
      padding: { top: 5, bottom: 5, left: 5, right: 5 },
    },
    scales: {
      r: {
        min: 0, max: 100, beginAtZero: true,
        ticks: { stepSize: 25, display: false },
        grid: { color: 'rgba(148, 163, 184, 0.28)' },
        angleLines: { color: 'rgba(148, 163, 184, 0.28)' },
        pointLabels: { color: '#334155', font: { size: 12, weight: '600' } },
      },
    },
    plugins: { legend: { display: false }, tooltip: { enabled: false } },
    maintainAspectRatio: false,
  };

  return (
    <div className="mx-auto w-full max-w-5xl px-4 sm:px-0 animate-fade-in-down pb-12">
      <div className="overflow-hidden rounded-3xl bg-white shadow-lg">
        {/* Header */}
        <div className="bg-gradient-to-r from-slate-900 via-slate-800 to-slate-700 px-6 py-8 sm:px-10 sm:py-10">
          <div className="text-center">
            <h1 className="text-2xl font-bold leading-snug text-white sm:text-4xl sm:leading-tight">
              永續健檢結果
              {leadData?.companyName && (
                <span className="block mb-1 mt-2 text-xl text-slate-300 sm:mb-2 sm:text-3xl font-medium">
                  {leadData.companyName}
                </span>
              )}
            </h1>
          </div>
        </div>

        <div className="space-y-8 p-6 sm:p-8">
          
          {/* 雷達圖 */}
          <div className="grid gap-6">
            <div className="overflow-hidden rounded-3xl border border-slate-200 bg-slate-50 p-4 sm:p-6">
              <div className="relative mx-auto h-[260px] w-full max-w-[280px] sm:h-[360px] sm:max-w-none">
                <Radar data={data} options={options} />
              </div>
            </div>
          </div>

          {/* 各軸文字說明 */}
          <div>
            <div className="md:grid-cols-2 grid gap-4">
              {AXIS_GUIDANCE.map((axisProfile, index) => (
                <div key={axisProfile.name} className="rounded-3xl border border-slate-200 bg-slate-50 p-5">
                  <div className="flex items-start justify-between gap-4">
                    <h4 className="mt-1 text-lg font-bold text-slate-900">{axisProfile.name}</h4>
                    <span className={`rounded-full border px-3 py-1 text-sm font-bold ${levelToneClass[axisLevels[index]] || levelToneClass.起步}`}>
                      {axisLevels[index]}
                    </span>
                  </div>
                  <p className="mt-4 text-sm leading-relaxed text-slate-700">
                    {getAxisGuide(index, axisScores[index])}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <hr className="my-3 border-slate-200" />

          {/* 合規燈號 */}
          {/* <div>
            <div className="mb-4">
              <h3 className="text-lg font-bold text-slate-900 sm:text-xl">合規狀態掃描</h3>
            </div>
            <div className="grid gap-4">
              {complianceResults.map((item) => (
                <div key={item.code} className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <p className="text-sm font-semibold tracking-wider text-slate-500 uppercase">{item.code}</p>
                      <h4 className="mt-1 text-base font-bold text-slate-900">{item.title}</h4>
                    </div>
                  </div>
                  <p className="mt-4 text-sm leading-relaxed text-slate-700">{item.description}</p>
                </div>
              ))}
            </div>
          </div> */}

          {/* 🌟 顧問建議 (淺色明亮版) */}
          {recommendations.length > 0 && (
            <>
              <hr className="my-6 border-slate-200" />
              <div>
                <div className="mb-5">
                  <h3 className="text-xl font-bold text-slate-900 sm:text-2xl flex items-center gap-2">
                    <svg className="w-6 h-6 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
                    顧問建議
                  </h3>
                  <p className="mt-1 text-sm text-slate-500">基於您的現況評估，我們建議您可以優先採取的兩項行動：</p>
                </div>
                
                <div className="grid gap-5 md:grid-cols-2">
                  {recommendations.map((rec, index) => (
                    <div key={rec.code} className="flex flex-col justify-between rounded-3xl border border-emerald-100 bg-gradient-to-br from-emerald-50/80 to-teal-50/50 p-6 sm:p-7 shadow-sm transition-transform hover:-translate-y-1">
                      <div>
                        <div className="flex items-center gap-3 mb-4">
                          {/* 淺色圓形序號 */}
                          <span className="flex items-center justify-center w-8 h-8 shrink-0 rounded-full bg-emerald-100 text-emerald-700 font-bold text-sm">
                            {index + 1}
                          </span>
                          {/* 深灰色標題 */}
                          <h4 className="text-lg sm:text-xl font-bold text-slate-800 leading-snug">{rec.name}</h4>
                        </div>
                        {/* 灰黑色內文 */}
                        <p className="text-sm sm:text-base leading-relaxed text-slate-700 mb-8">
                          {rec.message}
                        </p>
                      </div>
                      
                      {/* 綠色實心按鈕 */}
                      <a 
                        href={rec.link} 
                        target="_blank" 
                        rel="noopener noreferrer" 
                        className="inline-flex items-center justify-center w-full rounded-xl bg-emerald-600 py-3.5 px-4 text-sm sm:text-base font-bold text-white transition-all hover:bg-emerald-500 hover:shadow-md active:scale-95 touch-manipulation"
                      >
                        {rec.ctaText}
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* <hr className="my-6 border-transparent" />
          
          <button className="w-full rounded-2xl bg-slate-900 py-4 text-base font-bold text-white shadow-md transition-all hover:bg-slate-800 active:scale-[0.99] touch-manipulation">
            預約完整版永續健檢
          </button> */}
        </div>
      </div>
    </div>
  );
};

export default ResultPage;