# 溯稿 SourceDraft 部署手冊（公司伺服器）

給 IT 或負責部署的同仁。照順序做完約 30 分鐘。

## 架構

```
同仁瀏覽器 ──HTTPS──> caddy（443，憑證與反向代理） ──> app（溯稿，8000） ──> Claude API
                                                         │
                                                         └─ ./data：帳號檔、上傳物料、產出初稿
```

- 全部跑在同一台伺服器的 Docker 裡，兩個容器。
- `./data` 會存放**客戶原始資料與初稿**，屬內部 KM：請納入備份、限制伺服器登入權限。
- 伺服器需能連到 `api.anthropic.com`（HTTPS 443 對外）。

## 伺服器需求

| 項目 | 建議 |
| --- | --- |
| 作業系統 | Linux（Ubuntu 22.04／24.04 皆可），或任何能跑 Docker 的主機 |
| 規格 | 2 vCPU、4 GB RAM、20 GB 硬碟起跳（模型運算在 Anthropic 端，本機負擔很輕） |
| 軟體 | Docker Engine 與 Docker Compose plugin |
| 網路 | 對內開 443（同仁連線）；對外可連 api.anthropic.com |

## 步驟

### 1. 取得程式

```bash
git clone https://github.com/unitygood-digisev/demo.git sourcedraft
```

```bash
cd sourcedraft
```

### 2. 設定金鑰與網址

```bash
cp .env.example .env
```

編輯 `.env`：

| 變數 | 填什麼 |
| --- | --- |
| `ANTHROPIC_API_KEY` | 公司的 Claude API 金鑰（Anthropic Console 建立，建議專用一把） |
| `SITE_ADDRESS` | 有網域就填網域，例如 `sourcedraft.unitygood.com`；只在內網用 IP 連線就保留 `:443` |
| `TLS_MODE` | 有公開網域：填一個 email，Caddy 會自動申請正式憑證。內網：保留 `internal`（自簽憑證，第一次連線瀏覽器會提示，需信任一次） |
| `SOURCEDRAFT_MAX_JOBS` | 同時產出的章節數，預設 2 |

```bash
chmod 600 .env
```

### 3. 建立同仁帳號

先建立資料夾並啟動一次 build：

```bash
mkdir -p data
```

```bash
docker compose build
```

每位同仁執行一次（會要求輸入密碼，至少 10 字元；同名再執行一次即為重設密碼）：

```bash
docker compose run --rm -v "$PWD/data:/data" app sourcedraft adduser 帳號名稱 --users-file /data/users.txt
```

刪除帳號：編輯 `data/users.txt`，刪掉該行後執行 `docker compose restart app`。

### 4. 啟動

```bash
docker compose up -d
```

確認狀態：

```bash
docker compose ps
```

瀏覽器打開 `https://伺服器網址或IP`，輸入帳號密碼即可使用。先按「跑內建範例」確認流程正常。

### 5. 更新版本

```bash
git pull
```

```bash
docker compose up -d --build
```

產出紀錄與帳號都在 `./data`，更新不會遺失。正在產出中的工作會因重啟中斷，頁面會標示「伺服器重新啟動，工作中斷」，重新送出即可。

## 日常維運

| 事項 | 做法 |
| --- | --- |
| 看紀錄 | `docker compose logs -f app` |
| 備份 | 備份整個 `./data` 資料夾 |
| 清理舊案 | `./data/jobs/` 底下一個資料夾一次產出，資料夾名稱開頭即日期，可依公司保存政策刪除 |
| 費用 | 每次產出的 token 用量記在 `./data/jobs/<工作>/job.json` 的 `usage`；總額在 Anthropic Console 查看並可設月上限 |
| 換金鑰 | 改 `.env` 後 `docker compose up -d` |

## 資安注意事項

- 一定要走 HTTPS（本設定已內建）。帳號密碼以 HTTP Basic 傳送，沒有 HTTPS 等於明碼。
- 所有登入同仁看得到所有人的產出紀錄（團隊共用工具的設計）。若需依客戶分權限，請先提出，需要另外開發。
- 不要把服務直接開放到網際網路；建議只開內網或公司 VPN。
- `.env`、`data/users.txt` 不可提交到 git（已列入 `.gitignore`）。
- 初稿為 0→0.5 階段產物，交付前須經顧問逐項確認事實、數據、專有名詞與揭露要求（作業手冊 05-4）。
