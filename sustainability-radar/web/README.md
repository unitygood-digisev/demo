# 永續情報雷達

優樂地永續的每週外部情報台：法規、碳價、同業與客戶動態 → 影響哪條服務線 → 對優樂地的意義與建議行動 → 一鍵產出週報。

## 與「優樂地管理層系統」對齊（2026-10-17）

- **分組**：自家品牌／法規與準則／政府採購與政策／同業動態／客戶動態／其他，與管理層系統的外部情報週報相同。
- **規則引擎**：沿用管理層系統 `config/keywords.yaml`（雲端版，副執行長 10/15 提供，不含客戶與人名）的 23 組關鍵字與權重。相關度＝命中關鍵字權重加總；「ESG、永續、淨零」與「環境部等主管機關」要同時命中其他關鍵字才算；類別取命中權重最高的關鍵字。
- **即時新聞**（`api/news.js`）：改用管理層系統 `config/sources.yaml` 的 36 個公開 RSS 來源，不再用 Google News（其使用條款限個人非商業、禁止程式讀取）。抓取失敗的來源列在「來源異常」，沒命中關鍵字的放進「附錄：低相關與未列入」，不丟棄。
- **週報格式**：結論句在最前；每則含【重要度】、來源、日期、相關度（命中詞）、摘要、對優樂地的意義、原文連結；另有「說明」段與可選的「主管回饋單」。
- **知識庫**：新增 10/15 情報簡報中 8 則已查證的新聞（N19～N26）。

- `public/index.html`：整個前端（HTML＋CSS＋JS 內嵌，無框架、無打包）
- `api/claude.js`：AI 代理，API Key 只存在伺服器
- `api/news.js`：Google News RSS 即時新聞，不需要 AI 與金鑰

同一份 `index.html` 可在三種環境運作：Claude Artifact（`sample` 能力）、Vercel 網站（`/api/claude`）、離線（規則引擎）。

## 部署到 Vercel

在 `web/` 資料夾執行：

```bash
npm install
npx vercel login                                   # 請自己完成登入
npx vercel link --yes --project sustainability-radar
npx vercel deploy --prod --yes
npx vercel domains add sustainability-radar.vercel.app sustainability-radar   # 名稱被占用時改用其他名稱
```

部署後驗證：

```bash
curl -s https://<你的網址>/ | grep -o '<title>[^<]*'    # 應為「永續情報雷達」
curl -s https://<你的網址>/api/claude                    # 未設金鑰時應為 {"ok":false}
curl -s https://<你的網址>/api/news | head -c 300        # 應有新聞資料
```

並用無痕視窗打開網址，確認不需要 Vercel 登入（若跳出登入，請到專案 Settings → Deployment Protection 關閉 Vercel Authentication）。

## 費用保護

- **預設不設定 API Key，網站完全免費。** `/api/claude` 會回 `{"ok":false}`，頁面自動進入「離線模式（規則引擎）」，所有功能仍可使用。
- 要開啟網站版 AI：
  ```bash
  npx vercel env add ANTHROPIC_API_KEY production
  npx vercel deploy --prod --yes
  ```
  並到 console.anthropic.com 設定每月花費上限。
- 函式時限 60 秒（Vercel 免費方案上限）；單次輸入上限 16,000 字；模型輸出上限 8,000 tokens。
- AI 模型為 `claude-opus-5-5`，`quick` 等級用 low effort，其他用 medium；啟用伺服器端拒答備援（`fallbacks: "default"`）。

## 更新資料

所有資料集中在 `index.html` 的「知識庫」區塊：`AS_OF`、`NEWS`、`CARBON_PRICES`、`FX`、`DATA`、`KPIS`、`KEY_DATA`。新增情報時，每則都要有來源、可點開的網址與日期；只知道月份就寫 `YYYY-MM`；缺值用 `null`，圖表會標「未取得」。

若要改成企業內部永續長辦公室使用，改寫 `CONTEXT` 字串與 `LINES`（影響面向）的名稱即可。

## 測試結果（2026-10-17，對齊管理層系統後重測）

| # | 項目 | 結果 |
|---|---|---|
| 1 | 本機開啟 `index.html`，切換 6 個分頁，主控台無錯誤 | 通過（Playwright／Chromium） |
| 2 | 頁首顯示「離線模式（規則引擎）」，AI 按鈕全部隱藏 | 通過（可見的 AI 按鈕 0 個） |
| 3 | 貼上「環境部預告碳費優惠費率審查新制，明年起上路」 | 通過：法規與準則・碳盤查與碳費・重要度 高・相關度 7 分（命中：碳費、環境部） |
| 4 | 滑桿 200／1,000／4,000 統計卡與解讀都改變；30,000 噸一般費率 | 通過：年度碳費 NT$9,000,000 |
| 5 | 問情報官（離線）輸入「CBAM 憑證」 | 通過：N5、N6、N10、N14 |
| 6 | 週報預設勾選、複製、ISO 週數 | 通過：2026-10-17 為第 42 週；複製寫入剪貼簿 |
| 7 | 375px 無水平捲動；淺色與深色可讀 | 通過（6 分頁 × 2 色系，scrollWidth = 375） |
| 8 | Node 執行 `api/news.js` | 通過：36 個來源中 35 個成功，近 7 天 406 則；GSTC 回 HTTP 500，列在來源異常 |
| 9 | 假金鑰測 `api/claude.js` | 通過：GET `{ok:true}`；空字串 400；16,001 字 400；PUT 405；無金鑰 GET `{ok:false}` |
| 10 | 逐一打開來源連結 | 通過：原 33 個網址皆 HTTP 200；新增 8 則中，TNFD 官網擋程式讀取（403，瀏覽器可開），已用其官方 RSS 確認標題與日期 |

另以本機伺服器模擬網站模式（假的 `/api/claude` 回應）測試：深度解讀、貼上抽取（含 Markdown 程式碼框與前後雜訊的 JSON、非法 lines 過濾）、主管摘要、問情報官引用卡片、HTTP 429 顯示「AI 使用次數暫時達上限，請稍後再試。」皆正常。
