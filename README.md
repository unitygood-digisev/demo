# 優樂地管理中樞

優樂地永續服務股份有限公司的公司後台，給執行長與主管一頁看完：八大系統進度、數位轉型專案、待辦清單、時程、外部情報與週報、公司知識庫、專案財務（系統 2 試作）、文件與 AI 排程。

- 平台：https://claude.ai/artifact/WRwZtths21n7A2CVemw6RU （Claude Artifact，只有被分享的人看得到）
- 原「決策平台」於 2026-11-04 改寫；網址、筆記、知識庫與 AI 員工都沿用。

## 分頁

| 分頁 | 內容 | 資料來源 |
|---|---|---|
| 總覽 | 一句結論、六個數字、下一步、等主管決定的事、八大系統、數位轉型進度、接下來的時程 | 以下各集合 |
| 八大系統 | 每個系統的狀態、完成到哪一步、卡點、下一步、資料等級、估計時數、規格連結；可直接更新 | `modules` |
| 數轉專案 | 管理層系統、永續大數據庫、永續情報雷達、本平台的步驟與連結 | `initiatives` |
| 待辦清單 | 依負責人、狀態、系統、類型篩選；勾選完成、新增、編輯 | `tasks` |
| 時程 | 已完成與接下來的里程碑、階段與閘門 | `milestones` |
| 情報與週報 | AI 員工寫的外部情報摘要、管理層週報、後台更新紀錄；知識庫素材 | `notes` |
| 知識庫 | 公司資料與知識條目；問公司知識顧問 | `kb` |
| 專案財務 | 系統 2 試作：匯入專案與請款、警示、匯出 Excel。執行長核准前不放真實資料 | `projects`、`invoices` |
| 文件與排程 | 所有文件與網站連結、AI 排程最近執行結果、AI 員工產出 | `docs`、`routines` |

## 數位轉型進度怎麼算

已完成的估計時數 ÷（已完成＋剩下的估計時數），時數來自管理層系統的 `docs/roadmap.md`。已完成：階段 0 骨架 6–8 小時、系統 7、1、5 共 28–36 小時；剩下：系統 2 10–14，系統 3、4、6、8 各 8–14，共 42–70 小時。中間值約 36%，區間 29–46%；以每週 6–8 小時計算，約還要 6–12 週。八大系統卡片改成「上線中、已完成、程式完成」任一種，進度就會自動重算。

## AI 排程

| 排程 | 時間（台北） | 做什麼 |
|---|---|---|
| 永續情報日報（副執行長） | 週一到週五 07:52 | 系統 7 主管版每日郵件 |
| 每日情報郵件（品牌行銷部版） | 週一到週五 07:50 | 系統 7 品牌行銷部版每日郵件 |
| 公司知識顧問 | 每週一 08:00 | 整理「知識庫素材」進知識庫 |
| 外部情報摘要員 | 每週一 09:00 | 寫本週外部情報摘要 |
| 管理層週報彙整員 | 每週五 17:00 | 寫管理層週報（Gmail 連接器未接，所以不寄信） |
| 後台更新員 | 每週一 07:30 | 更新排程執行結果、記錄八大系統倉庫本週變更與逾期待辦；不改任何狀態 |

提示詞全文在 `platform/routines/`。

## 資料保護

- 專案與請款（含金額）放在 `projects`、`invoices`，只有 Contributor 以上權限的人讀寫。
- AI 員工與知識顧問只讀不含金額的 `shared/briefing`；指示中禁止讀 `projects`、`invoices`。
- 資料存在 claude.ai，不是公司自有主機。內部敏感與客戶機密的全文不要放進來。

## 網站版（Vercel）

- 網址：https://uld-hub.vercel.app （Vercel 專案 `uld-hub`）
- 整個網站要密碼（HTTP Basic Auth，帳號欄可填任意文字）。密碼存在 Vercel 環境變數 `SITE_PASSWORD`，不在程式裡；沒設定時網站一律拒絕。搜尋引擎不收錄。
- 內容是唯讀快照，不含專案財務資料；勾選待辦、更新狀態、問知識顧問要到 Claude 版。
- 更新快照：用 ArtifactData 把 hub、modules、initiatives、tasks、milestones、docs、routines、notes、kb 各集合 list 到同一個資料夾（out_dir），然後：

```
node platform/build-vercel.js <快照資料夾>
cd site && npx vercel deploy --prod --yes
```

- 改密碼：`npx vercel env rm SITE_PASSWORD production`，再 `npx vercel env add SITE_PASSWORD production`，然後重新部署。

## 開發與還原

```
node --test tests/*.test.js   # 驗收測試
node platform/build.js        # 產生 platform/dist/decision-platform.html
```

- `platform/lib/calc.js`：專案財務計算；`lib/kb.js`：知識庫；`lib/hub.js`：八大系統、進度、待辦、時程規則。
- `platform/page.html`、`platform/ui.js`：畫面。
- `platform/seed/hub-seed.json`：2026-11-04 的八大系統、專案、待辦、時程、文件與排程資料。
- 還原：build 後用 Claude 把 `platform/dist/decision-platform.html` 發布到同一個 Artifact 網址，宣告 capabilities `db`（`projects`、`invoices` 讀寫限 interact）、`user`、`downloads`、`sample`；資料庫是空的時，用 ArtifactData 依 `hub-seed.json` 寫入（`hub/meta` 與各集合）。
