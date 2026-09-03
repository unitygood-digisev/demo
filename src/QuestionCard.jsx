import React, { useEffect, useMemo, useRef, useState } from 'react';
import { questionBank, visibleQuestionBank } from './questions';
import { buildReportSummary } from './esgScoring';

const createEmptyAnswer = (question) => {
  if (question.kind === 'signal') {
    // 修改：確保 signal 題型同時有 path 與 selectedIds
    return { path: [], selectedIds: [] };
  }
  return { path: [] };
};

const buildTreeIndex = (nodes = []) => {
  const nodeMap = new Map();
  const childrenMap = new Map();

  nodes.forEach((node) => {
    nodeMap.set(node.id, node);
    const parentKey = node.parentId ?? '__root__';
    const bucket = childrenMap.get(parentKey) || [];
    bucket.push(node);
    childrenMap.set(parentKey, bucket);
  });

  return {
    nodeMap,
    childrenMap,
    rootNodes: childrenMap.get('__root__') || [],
  };
};

const buildPathToNode = (node, nodeMap) => {
  if (!node) return [];

  const path = [];
  let currentNode = node;

  while (currentNode) {
    path.unshift(currentNode.id);
    currentNode = currentNode.parentId ? nodeMap.get(currentNode.parentId) : null;
  }

  return path;
};

const collectTerminalPaths = (question) => {
  const { nodeMap, rootNodes } = buildTreeIndex(question.nodes);
  const terminalNodes = question.nodes.filter((node) => node.isTerminal);

  return terminalNodes
    .map((node) => buildPathToNode(node, nodeMap))
    .filter((path) => path.length > 0 && rootNodes.some((rootNode) => rootNode.id === path[0]));
};

const getLeafNode = (question, answer) => {
  const nodeMap = new Map((question.nodes || []).map((node) => [node.id, node]));
  const path = Array.isArray(answer?.path) ? answer.path : [];
  const lastNodeId = path[path.length - 1];
  return lastNodeId ? nodeMap.get(lastNodeId) || null : null;
};

const QuestionCard = ({ onComplete, onSaveNow }) => {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const [showHint, setShowHint] = useState(false);
  
  // 用來記錄哪一個節點目前正在觸發「晃動」動畫的 state
	// 修改為記錄被晃掉的節點 ID 陣列：
	const [shakingNodeIds, setShakingNodeIds] = useState([]);

  const [answersByCode, setAnswersByCode] = useState(() => {
    return questionBank.reduce((accumulator, question) => {
      accumulator[question.code] = createEmptyAnswer(question);
      return accumulator;
    }, {});
  });

  const currentQuestion = visibleQuestionBank[currentIndex];
  const currentAnswer = answersByCode[currentQuestion?.code] || createEmptyAnswer(currentQuestion || { kind: 'score' });

  const ENABLE_TEST_FILL = true;

  // 👇 1. 新增開發模式分數顯示開關（上線後改為 false）
  const ENABLE_DEBUG_SCORE = false; 

  const treeIndex = useMemo(() => buildTreeIndex(currentQuestion?.nodes || []), [currentQuestion]);
  const selectedPath = Array.isArray(currentAnswer.path) ? currentAnswer.path : [];
  const selectedLeafNode = getLeafNode(currentQuestion, currentAnswer);
  const canAdvance = currentQuestion?.kind === 'signal' 
    ? Array.isArray(currentAnswer.selectedIds) && currentAnswer.selectedIds.length > 0
    : selectedPath.length > 0;

  // 👇 2. 計算本題得分與累計總分 (僅在計分題型累加)
  let currentQuestionScore = 0;
  let cumulativeScore = 0;
  let maxTotalScore = 0;

  if (ENABLE_DEBUG_SCORE) {
    currentQuestionScore = selectedLeafNode?.score || 0;

    visibleQuestionBank.forEach((q) => {
      if (q.kind === 'score') {
        maxTotalScore += 100; // 假設每題最高 100 分
        
        const ans = answersByCode[q.code];
        if (ans && ans.path && ans.path.length > 0) {
          const lastNodeId = ans.path[ans.path.length - 1];
          const leafNode = q.nodes.find(n => n.id === lastNodeId);
          if (leafNode && typeof leafNode.score === 'number') {
            cumulativeScore += leafNode.score;
          }
        }
      }
    });
  }
	// --------------------------

  // const treeIndex = useMemo(() => buildTreeIndex(currentQuestion?.nodes || []), [currentQuestion]);
  // const selectedPath = Array.isArray(currentAnswer.path) ? currentAnswer.path : [];
  // const selectedLeafNode = getLeafNode(currentQuestion, currentAnswer);
  // // const canAdvance = Boolean(selectedLeafNode?.isTerminal);
	// const canAdvance = currentQuestion?.kind === 'signal' 
  //   ? Array.isArray(currentAnswer.selectedIds) && currentAnswer.selectedIds.length > 0
  //   : selectedPath.length > 0;

  useEffect(() => {
    setShowHint(false);
  }, [currentIndex]);

  // 是否有「上次儲存之後」尚未存檔的變更；剛進問卷時預設為 false（還沒有東西好存）
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const isFirstAnswersRenderRef = useRef(true);

  // 只要答案有變動，就把「儲存進度」按鈕重新標記為尚未儲存
  // 用 ref 跳過第一次 render（元件剛掛載時的初始空答案不算是「變更」）
  useEffect(() => {
    if (isFirstAnswersRenderRef.current) {
      isFirstAnswersRenderRef.current = false;
      return;
    }
    setHasUnsavedChanges(true);
  }, [answersByCode]);

  // 「儲存進度」按鈕點擊時觸發：把當下最新的題目索引與作答內容直接傳給父層
  const handleSaveClick = async () => {
    if (typeof onSaveNow !== 'function' || isSaving) return;

    setIsSaving(true);
    const success = await onSaveNow(currentIndex, answersByCode);
    setIsSaving(false);

    if (success) {
      setHasUnsavedChanges(false);
    }
  };

  useEffect(() => {
    const activeButton = document.querySelector(`[data-question-nav="${currentIndex}"]`);
    if (activeButton) {
      activeButton.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }, [currentIndex]);

  const updateAnswer = (questionCode, nextAnswer) => {
    setAnswersByCode((previous) => ({
      ...previous,
      [questionCode]: nextAnswer,
    }));
  };

	const handleSelectNode = (node) => {
    if (!currentQuestion) return;

    const noneKeywords = ['皆無', '兩者皆無', '尚未收到', '否', '不清楚', '尚未確定'];
    const isNoneOption = node.isNone || noneKeywords.some(text => node.label.includes(text));

    if (isNoneOption) {
      // 找出原本已經選取，準備被清掉的選項 ID
      let previousSelected = [];
      if (currentQuestion.kind === 'signal') {
        previousSelected = Array.isArray(currentAnswer.selectedIds) ? currentAnswer.selectedIds : [];
      } else {
        previousSelected = Array.isArray(currentAnswer.path) ? currentAnswer.path : [];
      }

      // 排除掉當前點擊的選項自己，剩下的就是需要被「晃掉」的選項
      const nodesToShake = previousSelected.filter(id => id !== node.id);

      // if (nodesToShake.length > 0) {
      //   setShakingNodeIds(nodesToShake);
      //   setTimeout(() => {
      //     setShakingNodeIds([]);
      //   }, 500);
      // }
    }

    if (currentQuestion.kind === 'signal') {
      // --- 複選題邏輯 ---
      const limit = currentQuestion.multiSelectLimit || 1;
      let nextSelectedIds = Array.isArray(currentAnswer.selectedIds) ? [...currentAnswer.selectedIds] : [];
      
      if (node.isTerminal) {
        if (isNoneOption) {
          // 若點選「尚未收到/不清楚」等皆無選項，則清空其他，只保留自己
          nextSelectedIds = [node.id];
        } else {
          // 修改：若點選一般選項，先清掉陣列裡所有的排他性選項（防呆）
          nextSelectedIds = nextSelectedIds.filter(id => {
            const n = treeIndex.nodeMap.get(id);
            return n && !noneKeywords.some(text => n.label.includes(text)) && !n.isNone;
          });

          // 點擊反選邏輯
          if (nextSelectedIds.includes(node.id)) {
            nextSelectedIds = nextSelectedIds.filter(id => id !== node.id); // 已選則取消
          } else {
            if (nextSelectedIds.length >= limit) {
              nextSelectedIds.shift(); // 若超過上限，把最早選的擠掉
            }
            nextSelectedIds.push(node.id); // 尚未選則加入
          }
        }
      }

      updateAnswer(currentQuestion.code, {
        path: buildPathToNode(node, treeIndex.nodeMap), 
        selectedIds: nextSelectedIds,                    
				isRandom: false // 新增：手動修改後拔除隨機標籤
      });
    } else {
      // --- 原本單選邏輯 ---
      updateAnswer(currentQuestion.code, {
        path: buildPathToNode(node, treeIndex.nodeMap),
				isRandom: false // 新增：手動修改後拔除隨機標籤
      });
    }
  };

  const hasAnswer = (question) => {
    const answer = answersByCode[question.code];
    if (!answer) return false;

    if (question.kind === 'signal') {
      return Array.isArray(answer.selectedIds) && answer.selectedIds.length > 0;
    }

    return Array.isArray(answer.path) && answer.path.length > 0;
  };

  const handleJumpToQuestion = (index) => {
    if (index === currentIndex) return;
    setIsTransitioning(true);
    window.setTimeout(() => {
      setCurrentIndex(index);
      setIsTransitioning(false);
    }, 160);
  };

  const handleNextQuestion = () => {
    if (!canAdvance) return;

    setIsTransitioning(true);
    window.setTimeout(() => {
      if (currentIndex < visibleQuestionBank.length - 1) {
        setCurrentIndex((previous) => previous + 1);
        setIsTransitioning(false);
        return;
      }

      const reportSummary = buildReportSummary(answersByCode, questionBank);
      if (typeof onComplete === 'function') {
        onComplete(reportSummary, answersByCode, currentIndex);
      }
      setIsTransitioning(false);
    }, 220);
  };

  // 修改：繪製精準的 L 型連結線
  const renderNodes = (parentId = null, depth = 0) => {
    const children = treeIndex.childrenMap.get(parentId ?? '__root__') || [];

    return (
      <div className={depth === 0 ? 'space-y-3' : 'mt-3 space-y-3'}>
        {children.map((node, index) => {
          const childNodes = treeIndex.childrenMap.get(node.id) || [];

					const isActive = currentQuestion.kind === 'signal' && node.isTerminal
					? (currentAnswer.selectedIds || []).includes(node.id)
					: selectedPath.includes(node.id);

          const canExpand = childNodes.length > 0 && !node.isTerminal;
          const shouldShowChildren = selectedPath.includes(node.id) && canExpand;
          const buttonClasses = isActive
            ? 'border-slate-700 bg-slate-800 text-white shadow-md'
            : 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100';

					const isShaking = shakingNodeIds.includes(node.id);
          const isLast = index === children.length - 1;

					return (
            <div key={node.id} className={`relative ${depth > 0 ? 'ml-6' : ''}`}>
              
              {/* 1. 垂直延伸線：留在最外層。如果不是最後一個節點，則線條往下貫穿整個區塊 (包含子節點的高度) */}
              {depth > 0 && !isLast && (
                <div className="absolute -top-1 -left-6 w-[2px] h-[calc(100%+12px)] bg-slate-200" />
              )}

              {/* 2. 按鈕專屬容器：多包這一層 relative，確保弧線的高度 (50%) 永遠只對齊按鈕正中央，不會被子節點撐高 */}
              <div className="relative">
                {depth > 0 && (
                  <div className="absolute -top-1 -left-6 w-4 h-[calc(50%+12px)] rounded-bl-xl border-b-2 border-l-2 border-slate-200" />
                )}

                <button
                  type="button"
                  onClick={() => handleSelectNode(node)}
                  className={`relative z-10 w-full rounded-xl border px-4 py-3.5 text-left text-sm sm:text-base font-medium transition-all touch-manipulation ${buttonClasses} ${
                    // isShakingAll ? 'animate-shake-x' : ''
										isShaking ? 'animate-shake-x' : '' // <--- 改回使用 isShaking
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <span className="leading-relaxed">{node.label}</span>
                  </div>
                </button>
              </div>

              {/* 子節點遞迴 */}
              {shouldShowChildren && renderNodes(node.id, depth + 1)}
            </div>
          );

        })}
      </div>
    );
  };

	const buildRandomVisibleAnswer = (question) => {
		const terminalPaths = collectTerminalPaths(question);
		if (terminalPaths.length === 0) {
			return createEmptyAnswer(question);
		}

		const selectedPath = terminalPaths[Math.floor(Math.random() * terminalPaths.length)];
		
		// 修改：如果是 signal 題型，必須要把 terminal 節點塞進 selectedIds 裡面
		if (question.kind === 'signal') {
			return { 
				path: selectedPath, 
				selectedIds: [selectedPath[selectedPath.length - 1]] 
			};
		}

		return { path: selectedPath };
	};

	const randomFillCurrent = () => {
    if (!ENABLE_TEST_FILL) return;

    const nextAnswers = { ...answersByCode };
    visibleQuestionBank.forEach((question) => {
      const currentAns = nextAnswers[question.code];
      
      // 檢查是否已經有手動填答的紀錄
      const alreadyAnswered = question.kind === 'signal'
        ? Array.isArray(currentAns?.selectedIds) && currentAns.selectedIds.length > 0
        : Array.isArray(currentAns?.path) && currentAns.path.length > 0;

      // 只有在「尚未填答」的情況下，才進行隨機填寫
      if (!alreadyAnswered) {
        const randomAns = buildRandomVisibleAnswer(question);
        nextAnswers[question.code] = { 
          ...randomAns, 
          isRandom: true // 新增：標記此題為隨機填答
        };
      }
    });
    setAnswersByCode(nextAnswers);
  };

  if (!currentQuestion) return null;

  return (
    <div className="mx-auto w-full max-w-3xl px-4 sm:px-0">
      {/* 新增：定義左右晃動的 CSS 動畫 */}
      <style>{`
        @keyframes shake-x {
          0%, 100% { transform: translateX(0); }
          20%, 60% { transform: translateX(-5px); }
          40%, 80% { transform: translateX(5px); }
        }
        .animate-shake-x {
          animation: shake-x 0.4s ease-in-out;
        }
      `}</style>

      <div className="mb-4 overflow-hidden rounded-2xl bg-white shadow-sm">
        <div className="flex items-center overflow-x-auto p-2 sm:p-3 hide-scrollbar" role="tablist" aria-label="問卷導覽">
          {visibleQuestionBank.map((question, index) => {
            const answered = hasAnswer(question);
            const baseClass = 'mx-1 flex-shrink-0 h-10 w-10 rounded-full text-xs font-bold transition-all duration-300 sm:h-12 sm:w-12 sm:text-sm';
            const className = index === currentIndex
              ? `${baseClass} bg-slate-800 text-white ring-2 ring-slate-400 shadow-md`
              : answered
                ? `${baseClass} bg-slate-500 text-white`
                : `${baseClass} bg-slate-100 text-slate-400 hover:bg-slate-200`;

            return (
              <button
                key={question.code}
                type="button"
                data-question-nav={index}
                onClick={() => handleJumpToQuestion(index)}
                className={className}
                title={`第 ${index + 1} 題 ${question.code}`}
              >
                {index + 1}
              </button>
            );
          })}
        </div>
      </div>

      <div className={`overflow-hidden rounded-2xl bg-white shadow-sm transition-opacity duration-300 ${isTransitioning ? 'opacity-40' : 'opacity-100'}`}>
        <div className="p-5 sm:p-8">

					{/* 👇 3. 顯示開發者 Debug 分數標籤 */}
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs font-semibold tracking-wider uppercase">
            {ENABLE_DEBUG_SCORE && (
              <span className="rounded-md bg-amber-100 px-2 py-1 text-amber-700 border border-amber-200">
                🔧 Debug: 本題 {currentQuestionScore} 分 | 累計 {cumulativeScore} / {maxTotalScore}
              </span>
            )}

						{/* 👇 新增：如果這題是隨機填答的，就顯示提示標籤 */}
            {currentAnswer.isRandom && (
              <span className="rounded-md bg-purple-100 px-2 py-1 text-purple-700 border border-purple-200">
                🤖 隨機填寫
              </span>
            )}
          </div>

          <h2 className="mb-4 text-lg font-bold leading-snug text-slate-900 sm:text-2xl">
            {currentQuestion.title}
          </h2>

          {/* <button
            type="button"
            onClick={() => setShowHint((previous) => !previous)}
            className="mb-5 rounded-full border border-slate-200 bg-slate-50 px-4 py-2 text-sm font-semibold text-slate-700 transition-all hover:bg-slate-100"
          >
            這題在問什麼
          </button> */}

          {showHint && (
            <div className="mb-6 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-700">
              <p>{currentQuestion.plainExplanation}</p>
            </div>
          )}

          <div className="space-y-4">
            {renderNodes()}
          </div>

          <div className="mt-6 border-t border-slate-200 pt-4">
            <button
              type="button"
              onClick={handleNextQuestion}
              disabled={!canAdvance}
              className={`w-full rounded-xl px-5 py-3 text-base font-bold transition-all touch-manipulation sm:w-auto ${
                canAdvance
                  ? 'bg-slate-800 text-white shadow-md hover:bg-slate-700 active:scale-[0.99]'
                  : 'cursor-not-allowed bg-slate-200 text-slate-400'
              }`}
            >
              {currentIndex === visibleQuestionBank.length - 1 ? '看結果' : '下一題'}
            </button>

            {ENABLE_TEST_FILL && (
              <button
                type="button"
                onClick={randomFillCurrent}
                className="mt-3 w-full rounded-xl bg-slate-100 px-5 py-3 text-sm font-semibold text-slate-600 transition-all hover:bg-slate-200 sm:mt-0 sm:ml-3 sm:w-auto"
              >
                暫時隨機填答剩餘題目
              </button>
            )}

            {typeof onSaveNow === 'function' && (
              <button
                type="button"
                onClick={handleSaveClick}
                disabled={isSaving}
                className={`mt-3 w-full rounded-xl border px-5 py-3 text-sm font-semibold transition-all sm:mt-0 sm:ml-3 sm:w-auto ${
                  isSaving
                    ? 'cursor-not-allowed border-slate-200 bg-slate-100 text-slate-400'
                    : hasUnsavedChanges
                      ? 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
                      : 'border-emerald-200 bg-emerald-50 text-emerald-600'
                }`}
              >
                {isSaving ? '儲存中...' : hasUnsavedChanges ? '儲存進度' : '已儲存'}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default QuestionCard;