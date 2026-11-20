# 電子報價單抓取程式：Admin 操作手冊

## 這是什麼

政府電子採購網的「公開取得電子報價單」招標公告（多為 150 萬以下的小額儀器採購），
g0v 與官方開放資料都沒有收錄，只能從採購網網頁取得；而採購網會擋國外 IP，
所以必須在公司（台灣）的電腦上執行。

本程式每天 10:00 自動執行一次：
1. 到採購網查「等標期內、公開取得電子報價單、財物類」的所有招標。
2. 用 Google Sheet「Keywords」分頁的關鍵字比對標案名稱。
3. 命中的寫入 Google Sheet 的 `EQuote_RAW` 分頁；每次執行結果記在 `EQuoteLog` 分頁。

標案雷達（Streamlit）掃描時會自動讀入這些資料、做 AI 評分。

## 日常檢查（每週一次即可）

打開 Google Sheet 的 **`EQuoteLog`** 分頁，看最後一列：

| status | 意思 | 要做什麼 |
|---|---|---|
| `OK` 且日期是今天或昨天 | 正常 | 無 |
| `FAIL` | 執行失敗，原因在 `message` 欄 | 看下方「常見問題」 |
| 最後一列超過 2 天前 | 排程沒有跑（電腦關機、排程被停用） | 檢查電腦與「工作排程器」 |

標案雷達的結果頁也會顯示失敗或停擺的警告。

## 安裝（只做一次）

### 事前準備
1. **IT 核准**：這台電腦需能連到 `web.pcc.gov.tw` 與 Google（`*.googleapis.com`、`oauth2.googleapis.com`）。
2. **安裝 Python 3.11 以上**：python.org 下載 Windows 版，安裝時勾選「Add python.exe to PATH」。
3. **Google 金鑰**：向維護者索取 service account 金鑰檔（`.json`），放在**專案資料夾以外**、
   只有 admin 能讀的位置，例如 `C:\TWBiddingFinder-secrets\service_account.json`。
   確認 Google Sheet 已「共用」給金鑰中的 `client_email`（編輯者權限）。

### 步驟
1. 把專案資料夾（整個 repo）放到這台電腦，例如 `C:\TWBiddingFinder`。
2. 以**系統管理員身分**執行 `runner\setup.bat`。
   第一次會建立 `runner\config.json` 後停下。
3. 用記事本編輯 `runner\config.json`：
   - `google_sheet_id`：Google Sheet 網址中 `/d/` 與 `/edit` 之間那一段。
   - `service_account_file`：金鑰檔的完整路徑（反斜線要寫兩次，如 `C:\\TWBiddingFinder-secrets\\service_account.json`）。
   - `proxy`：公司若需透過 proxy 上網才填，例如 `http://proxy.company.com:8080`；不需要就留空 `""`。
4. 再以系統管理員身分執行一次 `runner\setup.bat`。它會：
   - 測試採購網與 Google Sheet 連線，並列出目前命中的標案。
   - 測試通過才建立排程「TWBiddingFinder\EQuote」（每天 10:00，以 SYSTEM 身分執行，不需登入）。
5. 看到 `[OK] Setup done.` 即完成。

### 立即手動跑一次（驗證用）
在專案資料夾開命令提示字元：
```
runner\run_equote.bat
```
然後看 `runner\logs\equote.log` 最後幾行，以及 Google Sheet 的 `EQuoteLog`。

### 只測試抓取（不需 Google 金鑰）
裝好 Python 套件後即可執行，不需要 `config.json` 或金鑰；結果存成
`runner\logs\equote_all.csv`（全部）與 `equote_matched.csv`（關鍵字命中），可用 Excel 開啟比對採購網：
```
.venv-runner\Scripts\python.exe -X utf8 -m runner.equote_runner --local
```

## 常見問題

| 訊息 | 原因 | 處理 |
|---|---|---|
| 防火牆拒絕連線（多為非台灣 IP） | 採購網擋了這台電腦的對外 IP | 確認公司對外 IP 在台灣；若走海外 VPN/proxy，請 IT 讓此電腦直連 |
| 連線採購網失敗：ConnectTimeout / ProxyError | 公司網路或 proxy 擋住 | 請 IT 放行 `web.pcc.gov.tw`，或在 config.json 填 `proxy` |
| 找不到結果表格 table#tpam | 採購網改版 | 把 `runner\logs\last_list_page.html` 交給維護者 |
| Google Sheet 相關錯誤（403 / PERMISSION_DENIED） | Sheet 沒共用給金鑰帳號，或金鑰失效 | 重新共用 Sheet，或向維護者換新金鑰 |
| `Python not found` | 未安裝 Python 或未加入 PATH | 重新安裝 Python 並勾選 Add to PATH |

## 修改執行時間 / 停用

- 工作排程器 → 工作排程器程式庫 → `TWBiddingFinder` → `EQuote`：可改時間、停用、立即執行。
- 移除排程：系統管理員命令提示字元執行
  `schtasks /Delete /TN "TWBiddingFinder\EQuote" /F`

## 更新程式

維護者更新程式後，把新版專案檔案覆蓋到同一資料夾（保留 `runner\config.json`），
再以系統管理員身分執行一次 `runner\setup.bat` 即可。

## 資料使用

僅供內部業務使用，不對外提供或販售（見 `docs/data_sources.md` 授權說明）。
程式每天只查詢一次，每頁間隔 2 秒，不會對採購網造成負擔。
