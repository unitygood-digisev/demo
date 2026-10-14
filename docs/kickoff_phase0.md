# 階段 0 開工指令

把 CLAUDE.md 和 docs/specs/ 放好後，把下面這段直接貼給 Claude Code，它只做階段 0。

```
請先完整閱讀 CLAUDE.md，以及 docs/specs/ 下的所有規格。

這次只做「階段 0：專案骨架」，不要開始階段 1。

要做的事：
1. 建立 CLAUDE.md 第 8 節列的目錄結構、.gitignore（包含 data/raw、data/interim、data/out、.env、logs）、.env.example、pyproject.toml（含 ruff 和 pytest 設定）。
2. 實作 src/shared/ 下的所有模組（io、schema、classify、llm_client、report、logging、dates），規格見 CLAUDE.md 第 9 節。llm_client 先做成可用 mock 的版本，不要連真實的模型服務。
3. 寫 config/ 下的起始設定檔，每個門檻數值都加註「待主管確認」。sources.yaml 和 keywords.yaml 只放空範本和填寫說明，不要自己填來源。
4. 在 data/sample/ 產生系統 7 和系統 1 需要的假資料（用虛構的客戶名稱，明確標記「假資料」），包含至少一筆缺欄位、一筆重複 ID、一筆日期錯誤。
5. 為 shared 層寫測試，特別是：llm_client 在傳入不合規的資料等級時必須拒絕；io 對缺欄位、型別錯誤要整張列出。
6. 把 docs/data_requests.md 寫成一份給主管的資料需求清單，內容依系統 7、1、2 的輸入欄位整理。
7. 寫 README.md，給非技術人員看：這個專案是什麼、資料要放哪、怎麼跑、找誰。

完成後：
- 跑 ruff 和 pytest，結果貼給我。
- 依 CLAUDE.md 第 11 節的第 5 步，開一個全新的 session 做獨立驗收。
- 依第 12 節的格式回報。

遇到任何不確定的地方，先問我，不要猜。
```
