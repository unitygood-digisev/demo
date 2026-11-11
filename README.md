# 溯稿 SourceDraft

顧問的初稿產線：**AI 負責整理和起草，人只負責審校和補件。**

輸入「往年完稿章節」與「當年自收表」，產出可溯源的永續報告書章節初稿（0 → 0.5 階段），連同 Word 檔、自動檢核報告與事實表。依《永續報告書初稿生成器（ESG Draft Skill）v2》打造。

## 處理鏈路

```
輸入 A：往年完稿章節 ─┐
                      ├─> Step 1 物料解析與事實清洗      模型抽數值與算式 → 程式驗算、旗標
輸入 B：當年自收表 ───┘        │
                               ▼
                    Step 2 邏輯重構與初稿起草            v2 System Prompt＋已驗算事實表
                               │
                               ▼
                    Step 3 溯源錨定與風險標記            程式檢核：重算錨點、數值溯源、標記、附錄
                               │
                               ▼
              依 OUTPUT_MODE 輸出：internal（顧問版）／client（客戶版）
```

與單純貼提示詞的差別：**數字不交給模型算。** Step 1 只讓模型「找出數值、提出算式」，加總、平均、占比、同比全由程式以四捨五入（ROUND_HALF_UP）計算，並自動檢查：

- 往年完稿的總數、均值是否自洽（v1 範例的 12,450 ÷ 350 = 32.5 會被抓出，正確為 35.6）
- 同比波動是否超過 ±30%
- 同比兩端的分母口徑是否一致（期末人數 vs 年度平均人數）

Step 2 只能引用驗算後的結果；Step 3 再把初稿裡每個 `[依…計算：…]` 重算一次，並比對正文每個數字是否出自輸入物料，抓出杜撰數字。

## 安裝

```bash
pip install -e '.[web]'
```

設定 Claude API 憑證（擇一）：

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

```bash
ant auth login
```

## 使用方式

### 1. 先跑範例（不呼叫 API）

```bash
sourcedraft demo
```

以 v2 規格中的 Q12 培訓時數範例離線示範：Step 1／Step 2 使用內建的人工撰寫驗收樣本，計算與檢核為實際執行。輸出在 `output/demo/`。

### 2. 產出章節初稿

```bash
sourcedraft draft \
  --past 往年完稿_CH5.docx \
  --survey 明台資蒐表_CH5永續職場.docx 附件_訓練時數.xlsx \
  --instructions "GRI 404-1 需補齊男女平均時數拆分" \
  --client 明台產險 --year 2026 --chapter CH5永續職場 \
  --mode both --out output/明台產險
```

- `--past`、`--survey` 可放多個檔案，支援 docx／xlsx／pdf／md／txt／csv。讀取時保留〔表N〕〔工作表 · 列〕〔第N頁〕等定位，讓錨點對得到底稿；客戶原檔不會被修改。
- `--mode internal`（預設，顧問版）／`client`（客戶版）／`both`（兩版共用同一份 Step 1 事實表）。
- `--no-fact-sheet`：略過 Step 1，只用 v2 提示詞單次起草（與貼到 Dify 的效果相同），Step 3 仍會執行。
- `--model`、`--effort`：預設 `claude-opus-5-5`、`high`；也可用環境變數 `SOURCEDRAFT_MODEL`、`SOURCEDRAFT_EFFORT`。

每一版輸出：

| 檔案 | 用途 |
| --- | --- |
| `明台產險_2026_初稿CH5永續職場_internal_V1_20261111.docx` | Word 初稿；【待…】黃底，[源自…]／[依…計算] 錨點為灰色小字 |
| `…_V1_20261111.md` | 同內容 Markdown |
| `…_V1_20261111_自動檢核報告.md` | Step 3 檢核結果（錯誤／警示） |
| `…_V1_20261111_事實表.md`／`.json` | Step 1 數值、程式計算結果、旗標、缺口 |

檔名依作業手冊「客戶\_年度\_文件類型\_日期」，版號自動遞增，不覆蓋舊檔。

### 3. 網頁介面

```bash
sourcedraft serve
```

開啟 <http://127.0.0.1:8000>，上傳檔案、選模式即可。預設只綁本機；要給團隊共用請自行加上登入保護。

### 4. 只要提示詞（貼到 Dify／Claude Project／GPTs）

- 原文：[`sourcedraft/prompts/system_prompt_v2.md`](sourcedraft/prompts/system_prompt_v2.md)，含 `{{past_year_final_section}}` 等變數，可直接貼入。
- 帶入實際物料後的版本：

```bash
sourcedraft prompt --past 往年.docx --survey 自收表.docx --out output/prompts
```

### 5. 檢核既有初稿（人工或外包寫手交回的稿也可用）

```bash
sourcedraft verify 初稿.md --mode internal --sources 往年.docx 自收表.docx
```

## Step 3 自動檢核項目

| 檢核 | 錯誤（需修正） | 警示（需人工確認） |
| --- | --- | --- |
| 計算錨點重算 | `[依…計算：算式 = 結果]` 重算後與文中數值不符 | 算式無法自動解析 |
| 數值溯源 | — | 正文數值在輸入物料與事實表中都找不到（可能杜撰） |
| 模式標記 | client 版殘留 [源自…]／【待顧問複核】或顧問附錄；internal 版無任何 [源自…] | client 版缺「客戶補件清單」 |
| 附錄狀態 | internal 缺附錄；狀態不是「待補件／待複核／口徑待確認／數據矛盾」 | 正文待複核種類多於附錄列數 |
| 缺口覆蓋 | — | Step 1 缺口或程式旗標沒反映在稿件／客戶補件清單 |
| 進位規則 | — | 衍生百分比未統一到小數點後一位（客戶原始填報的數值不在此限） |

檢核只涵蓋可機械驗證的部分。依作業手冊 05-4，**事實、數據、專有名詞、揭露要求仍須顧問逐項確認**，初稿不可直接作為最終稿。

## 專案結構

```
sourcedraft/
  prompts/system_prompt_v2.md          v2 System Prompt 原文
  prompts/step1_extract.md             Step 1 抽取提示詞
  prompts/step2_fact_sheet_addendum.md 附加在 v2 之後的「已驗算事實表」規則
  ingest.py      docx／xlsx／pdf → 帶定位錨點的文字
  facts.py       事實表 schema、安全算式求值、驗算與旗標
  llm.py         Claude API 呼叫（串流、結構化輸出、拒答時伺服器端 fallback）
  pipeline.py    Step 1 → 2 → 3 串接與輸出
  verify.py      Step 3 自動檢核
  export_docx.py Markdown → Word
  naming.py      作業手冊檔名規則
  cli.py / web.py
examples/q12_training/   v2 規格範例：輸入、Step 1 參考輸出、internal／client 參考初稿
docs/CHANGELOG.md         v1 → v2 變更與系統化新增項目
docs/prompt_v1_reference.md
tests/                    驗收數字、v1 錯誤回歸、檢核規則、匯出
```

## 驗收（v2 規格第三節）

`pytest` 涵蓋規格的預期輸出特徵：

- 總時數 3,200 + 8,500 + 600 = 12,300 小時，較去年 12,450 減少 1.2%
- 期末人數 350 → 380（+8.6%）
- 平均每人受訓 32.4 小時（12,300 ÷ 380），去年 35.6（12,450 ÷ 350），下降 9.0%，註明「期末人數」口徑
- 線上學習平台與 AI 課程編入「多元培育管道與創新賦能」
- 附錄含 GRI 404-1 男女拆分、人數口徑確認、AI 課程參訓人數

```bash
pip install -e '.[dev]'
pytest
```

## 建議導入方式

1. 先拿一個資料標準化的章節（員工培育、公司治理）跑一次，例如明台產險 CH5 永續職場或台北慈濟對應章節。
2. 把 internal 版初稿與檢核報告直接交給負責顧問，只問兩件事：這份稿當作寫手交稿能打幾分？附錄的待補件清單有沒有省掉二次核對？
3. 確認好用後再套到其他案卷；每次跑完的檢核報告與顧問修改處，可回填到工具箱的 KM 資料庫，持續修正 Step 1 提示詞。

客戶資料屬內部 KM，請勿提交到本 repo；`output/` 已列入 `.gitignore`。
