# 資料來源

## 目前使用

| 來源 | 狀態 | 用途 |
|---|---|---|
| g0v pcc-api（`https://pcc-api.openfun.app/api/`） | 使用中 | 招標、決標、無法決標公告與明細 |
| 政府電子採購網直連（`scrapers/pccScraper.py`） | **停用**（`config.json` → `websites.pcc_gov.enabled: false`） | 保留模組，日後在台灣主機部署時可重新啟用 |

## g0v 抓取方式（2026-10-29 起）

- 每天呼叫一次 `listbydate?date=YYYYMMDD`，取得當天全部公告（約 2,700 筆），在本地比對：
  - 標題關鍵字 → 比對公告標題（去除空白後）
  - 經銷商名稱 → 比對決標／無法決標公告的投標廠商名單 `brief.companies.names`
- 只對比對到的公告呼叫 `tender?unit_id=…&job_number=…` 取明細，網址一律用 `config.json` 的 https base。
- 明細取不到時，保留該筆並改用列表資料（缺聯絡人、金額），連結指向 g0v 網頁版。
- 某一天 `listbydate` 失敗只跳過那一天；只有網路層錯誤（逾時、連線失敗）連續 3 次才停止。
  - g0v 對沒有公告的日子回 HTTP 500（2026-10-24～26 連假實測：跳過的三天正好是假日，前後上班日正常），結果頁顯示為「以下日期沒有資料（多為假日）」並標註星期。
- 請求帶 `User-Agent: TWBiddingFinder/1.0` 與 OpenFun token（Streamlit secret `OPENFUN_TOKEN`，於 https://data.openfun.tw/user 申請，免費、不需勾選任何權限）。

做法參考 bidscan.tw（其「關於」頁說明資料透過 g0v pcc-api 取得、每小時更新）。

## 歷史紀錄

依 Google Sheet「TW Bidding collector」逐筆統計（RunLog 32 次執行、Tenders_RAW 638 列、Awards_RAW 840 列）：

- **2026-06-22～06-25**：g0v 與政府採購網直連都有資料。
- **2026-07-01～10-19**：g0v 貢獻 0 筆，所有資料來自政府採購網直連。
  - 原因（2026-10-29 用 app 內「資料來源連線診斷」確認）：搜尋結果給的明細網址是 `http://pcc-api.openfun.app/api/tender?…`，對程式回 **404**；同一網址改 `https://` 回 200，與是否帶 token、模擬瀏覽器無關。
- **2026-10-19 之後**：政府採購網直連從 Streamlit Cloud 全部 `ConnectTimeout`（TCP 連線建立不起來）。
  - 診斷時 Streamlit Cloud 對外 IP：`34.19.100.134`。
  - 同期程式未改動；Streamlit 平台在 10/19 之後有更新；Streamlit 官方表示對外 IP 可能隨時變更。
  - g0v 作者文件（PLAN.md）記載採購網 2026-09 起擋含 Chrome 字樣的 User-Agent，且需輪替 proxy 避免 IP 被封。
  - 推論：採購網擋掉 Streamlit Cloud 目前的雲端 IP。**未取得官方證實。**
- **2026-10-29**：改為 g0v `listbydate` 抓取；停用政府採購網直連。

## 重新啟用政府採購網直連

1. 確認部署環境連得到 `web.pcc.gov.tw`：app「🔧 資料來源連線診斷」的「政府採購網直連」需回 HTTP 200，而非 ConnectTimeout。
2. 將 `config/config.json` 的 `websites.pcc_gov.enabled` 改為 `true`。
3. 注意：採購網會擋含 Chrome/Chromium 字樣的 User-Agent；`requests` 預設 UA 不受影響。

## Google Sheets 去重

- 決標：以 `job_number` 去重。
- 招標：以 `job_number` + `招標資料:招標狀態` 去重，讓同一案號的再次招標（如「第二次及以後公開招標」）能寫入。
  - 任一方的招標狀態為空白（舊 PCC 直連資料、明細取不到的列表資料）時，只比對 `job_number`，避免重複寫入。
- 寫入時依試算表表頭補齊所有欄位，避免缺欄造成值錯位。

## 授權

g0v 頁面註明：API 資料取自政府電子採購網，商業利用請改用政府提供的開放資料集；採購網著作權聲明僅開放個人或家庭非營利重製。

**2026-10-29 決定（專案負責人）**：本工具僅供內部自用，不轉售、不對外提供資料，判斷不屬於商業再利用，繼續使用 g0v API。若用途改變（對外提供、販售），需重新評估。
