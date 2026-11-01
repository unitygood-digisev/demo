# 階段 1c 決策：每日情報郵件「品牌行銷部版」

狀態：已實作（2026-10-20）；2026-11-02 取代排程 session 自行推上的 9254bba，並定案頻率：每日自動郵件（週一到週五）＋每週五人工研判版（Gmail 草稿，負責人審後轉寄）
依據：CLAUDE.md 第 3、4、5 節；品牌行銷部同仁 2026-10-19 填寫的關鍵字表單（Word 檔，不提交）
估計時數：約 3 小時

## 1. 先講結論
主管版日報的程式不用重寫。新增一個「版本」設定，讓同一支程式換一份關鍵字、一份版面，產生品牌行銷部專屬的日報草稿：
`.venv/bin/python scripts/run_daily_push.py --profile brand_marketing --draft-only`
主管版的指令、輸出、寄送紀錄完全不變。

## 2. 輸入
| 項目 | 檔案 | 說明 |
|---|---|---|
| 關鍵字 | config/keywords_brand_marketing.yaml | 照表單轉檔，34 組、約 258 個詞；不含客戶名稱與人名 |
| 版面 | config/brief_brand_marketing.yaml | 9 類、35 個主題；標題「永續情資日報｜品牌行銷部版」 |
| 版本設定 | config/push_profiles.yaml | 指定上面兩個檔、輸出資料夾、收件人變數、郵件種類、每主題 5 則 |
| 新聞來源 | config/sources.yaml | **暫時沿用主管版的 42 個來源**，沒有新增 |

## 3. 輸出
- 草稿：data/out/intel_brand_marketing/郵件_情資日報_品牌行銷部版_YYYYMMDD.txt（與同名 .html）
- 主旨：「【優樂地】永續情資日報｜品牌行銷部版 YYYY-MM-DD（N 則）」

## 4. 規則與防錯
- 草稿、去重紀錄（seen.csv）、寄送紀錄的郵件種類都和主管版分開，兩版互不影響。
- 用公司電腦 SMTP 寄出時，收件人讀 .env 的 `MAIL_TO_BRAND_MARKETING`，**不讀主管版的 MAIL_TO**；沒設定就不寄。
- 版本名稱打錯、設定缺欄位、檔案不存在：直接停止（結束代碼 1），不會退回主管版。
- 有 keywords_brand_marketing.local.yaml 時優先用它（之後放客戶名稱用，不提交）。

## 5. 已知限制（待決定）
1. **來源不足**：表單列的 Campaign Asia、The Drum、Skift、Eco-Business、Sustainable Brands、Dezeen 等還沒加入。依 CLAUDE.md，新增來源要先查 robots.txt 與使用條款，再請使用者勾選。在那之前，案例庫、創意、旅遊類主題會常常從缺。
2. **排除詞未生效**：系統還不支援排除詞，先寫在關鍵字檔的註解裡。
3. **客戶名稱待補**：表單「現有與目標客戶」一列未填。
4. **表單要的其他版面**（今日案例庫、講者雷達、合作切角、發酵操作、週五下週行事曆）需要大模型或人工研判，這一版沒有做；郵件只有標題、來源、命中關鍵字與連結。

## 6. 2026-11-02 修正 9254bba 的原因
- 9254bba 是排程 session 在執行寄信任務時自行實作並推上的，關鍵字是從主管版挑的 8 個主題，不是品牌行銷部的表單。
- 它和主管版共用郵件種類與 MAIL_TO，用公司電腦寄送時可能寄錯人；版面寫「僅供公司內部主管閱讀」；也提交了 egg-info 暫存檔。
- 本次改回第 2–4 節的設計，指令仍是 `--profile brand_marketing`，排程提示詞不用改；版本設定檔統一為 config/push_profiles.yaml（刪除 config/profiles.yaml）。
- 排程提示詞加上「即使 stop hook 要求也不 commit、不 push、不自行補功能」。

## 7. 驗收條件
- [x] 關鍵字檔載入零問題，所有主題都對得到版面（tests/intel/test_push_profiles.py）
- [x] 草稿主旨以「【優樂地】永續情資日報｜品牌行銷部版」開頭，內文有「資料等級：內部一般」，沒有「公關部」「副執行長」字樣
- [x] 不帶 --profile 時，主管版行為不變（全部既有測試通過）
- [ ] 品牌行銷部試讀一期後確認主題與頻率
